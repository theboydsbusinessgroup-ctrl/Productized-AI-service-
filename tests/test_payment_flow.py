import json
import time

import stripe
from fastapi.testclient import TestClient

from app.main import app
from app.store import set_store_for_tests

client=TestClient(app)
class FakeStore:
    def __init__(self): self.orders={}
    def create_order(self,order_id,customer_email,amount_usd,state):
        row={'order_id':order_id,'customer_email':customer_email,'amount_usd':amount_usd,'state':state,'intake_token':None,'stripe_session_id':None,'intake':None,'deliverable_text':None}; self.orders[order_id]=row; return row
    def get_order(self,order_id): return self.orders.get(order_id)
    def get_order_by_session(self,session_id): return next((r for r in self.orders.values() if r.get('stripe_session_id')==session_id),None)
    def mark_paid(self,order_id,stripe_session_id,intake_token):
        row=self.orders.get(order_id)
        if not row:return None
        if row['state'] in {'PAID','DELIVERY_READY'}:
            return row if row.get('stripe_session_id')==stripe_session_id else None
        if row['state']!='CHECKOUT_PENDING': return None
        row.update(state='PAID',stripe_session_id=stripe_session_id,intake_token=intake_token);return row
    def save_fulfillment(self,order_id,intake,deliverable_text):
        row=self.orders.get(order_id)
        if not row:return None
        row.update(state='DELIVERY_READY',intake=intake,deliverable_text=deliverable_text);return row

def setup_function(): set_store_for_tests(FakeStore())

def signed_webhook(payload,secret):
    body=json.dumps(payload,separators=(',',':'))
    timestamp=int(time.time())
    signature=stripe.WebhookSignature._compute_signature(f"{timestamp}.{body}",secret)
    return body,{'stripe-signature':f't={timestamp},v1={signature}','content-type':'application/json'}

def paid_session(order_id,**overrides):
    session={'id':'cs_test_123','client_reference_id':order_id,'payment_status':'paid','mode':'payment','amount_total':4900,'currency':'usd'}
    session.update(overrides)
    return {'type':'checkout.session.completed','data':{'object':session}}

def test_full_zero_cost_fulfillment(monkeypatch):
    secret='whsec_test_secret'
    monkeypatch.setenv('STRIPE_PAYMENT_LINK_URL','https://buy.stripe.com/test'); monkeypatch.setenv('STRIPE_WEBHOOK_SECRET',secret); monkeypatch.delenv('STRIPE_WEBHOOK_TOKEN_ENFORCED',raising=False)
    c=client.post('/checkout',json={'customer_email':'buyer@example.com'}); oid=c.json()['order_id']
    payload,headers=signed_webhook(paid_session(oid),secret)
    assert client.post('/webhooks/stripe',content=payload,headers=headers).status_code==200
    h=client.get('/handoff?session_id=cs_test_123').json(); token=h['intake_token']
    r=client.post(f'/orders/{oid}/intake',headers={'x-intake-token':token},json={'business_name':'Acme','industry':'Home Services','location':'Houston','services':['Repairs']})
    assert r.status_code==200 and r.json()['state']=='DELIVERY_READY'
    d=client.get(r.json()['delivery_url'])
    assert d.status_code==200 and '30-Day Social Content Pack — Acme' in d.text and 'Day 30:' in d.text
    assert 'attachment;' in d.headers['content-disposition']


def test_webhook_does_not_fulfill_unpaid_session(monkeypatch):
    secret='whsec_test_secret'
    monkeypatch.setenv('STRIPE_PAYMENT_LINK_URL','https://buy.stripe.com/test')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET',secret)
    order_id=client.post('/checkout',json={'customer_email':'buyer@example.com'}).json()['order_id']
    payload,headers=signed_webhook(paid_session(order_id,payment_status='unpaid'),secret)
    response=client.post('/webhooks/stripe',content=payload,headers=headers)
    assert response.status_code==200
    assert response.json()['reason']=='payment_not_paid'
    assert client.get('/handoff',params={'session_id':'cs_test_123'}).json()['state']=='PROCESSING'


def test_webhook_does_not_fulfill_wrong_amount(monkeypatch):
    secret='whsec_test_secret'
    monkeypatch.setenv('STRIPE_PAYMENT_LINK_URL','https://buy.stripe.com/test')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET',secret)
    order_id=client.post('/checkout',json={'customer_email':'buyer@example.com'}).json()['order_id']
    payload,headers=signed_webhook(paid_session(order_id,amount_total=100),secret)
    response=client.post('/webhooks/stripe',content=payload,headers=headers)
    assert response.status_code==200
    assert response.json()['reason']=='unexpected_amount'


def test_duplicate_webhook_preserves_intake_token(monkeypatch):
    secret='whsec_test_secret'
    monkeypatch.setenv('STRIPE_PAYMENT_LINK_URL','https://buy.stripe.com/test')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET',secret)
    order_id=client.post('/checkout',json={'customer_email':'buyer@example.com'}).json()['order_id']
    payload,headers=signed_webhook(paid_session(order_id),secret)
    first=client.post('/webhooks/stripe',content=payload,headers=headers)
    assert first.status_code==200
    first_token=client.get('/handoff',params={'session_id':'cs_test_123'}).json()['intake_token']
    second=client.post('/webhooks/stripe',content=payload,headers=headers)
    assert second.status_code==200
    assert second.json()['duplicate'] is True
    assert client.get('/handoff',params={'session_id':'cs_test_123'}).json()['intake_token']==first_token
