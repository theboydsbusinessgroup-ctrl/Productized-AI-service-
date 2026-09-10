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
        row.update(state='PAID',stripe_session_id=stripe_session_id,intake_token=intake_token);return row
    def save_fulfillment(self,order_id,intake,deliverable_text):
        row=self.orders.get(order_id)
        if not row:return None
        row.update(state='DELIVERY_READY',intake=intake,deliverable_text=deliverable_text);return row

def setup_function(): set_store_for_tests(FakeStore())
def test_full_zero_cost_fulfillment(monkeypatch):
    monkeypatch.setenv('STRIPE_PAYMENT_LINK_URL','https://buy.stripe.com/test'); monkeypatch.delenv('STRIPE_WEBHOOK_TOKEN_ENFORCED',raising=False)
    c=client.post('/checkout',json={'customer_email':'buyer@example.com'}); oid=c.json()['order_id']
    assert client.post('/webhooks/stripe',json={'type':'checkout.session.completed','data':{'object':{'id':'cs_test_123','client_reference_id':oid}}}).status_code==200
    h=client.get('/handoff?session_id=cs_test_123').json(); token=h['intake_token']
    r=client.post(f'/orders/{oid}/intake',headers={'x-intake-token':token},json={'business_name':'Acme','industry':'Home Services','location':'Houston','services':['Repairs']})
    assert r.status_code==200 and r.json()['state']=='DELIVERY_READY'
    d=client.get(r.json()['delivery_url'])
    assert d.status_code==200 and '30-Day Social Content Pack — Acme' in d.text and 'Day 30:' in d.text
    assert 'attachment;' in d.headers['content-disposition']
