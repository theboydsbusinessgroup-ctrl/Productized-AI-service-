from fastapi.testclient import TestClient

from app.main import app
from app.store import set_store_for_tests

client = TestClient(app)


class Store:
    def __init__(self, state='PAID', business='Acme'):
        self.row = {'order_id': 'ord_retry', 'state': state, 'intake_token': 'tok_retry',
                    'intake': {'business_name': business}, 'deliverable_text': 'original pack'}
        self.writes = 0
    def get_order(self, order_id):
        return self.row.copy()
    def get_order_by_session(self, session_id):
        return self.row.copy()
    def save_fulfillment(self, order_id, intake, text):
        self.writes += 1
        self.row.update(state='DELIVERY_READY', intake=intake, deliverable_text=text)
        return self.row.copy()
    def log_event(self, *args, **kwargs):
        pass


    def enqueue_fulfillment(self,order_id,intake):
        self.job={'order_id':order_id,'intake':intake}
    def claim_fulfillment(self,order_id=None):
        return getattr(self,'job',None)
    def complete_fulfillment(self,job,text):
        self.save_fulfillment(job['order_id'],job['intake'],text)
        self.job=None
        return True
    def fail_fulfillment(self,job,retryable):
        pass

def test_authenticated_retry_returns_original_deliverable():
    store = Store()
    set_store_for_tests(store)
    headers = {'x-intake-token': 'tok_retry'}
    url = '/orders/ord_retry/intake'
    first = client.post(url, headers=headers, json={'business_name': 'Acme', 'industry': 'Repairs'})
    original = store.row['deliverable_text']
    retry = client.post(url, headers=headers, json={'business_name': 'Different', 'industry': 'Cleaning'})
    assert first.status_code == retry.status_code == 200
    assert first.json()['delivery_url'] == retry.json()['delivery_url']
    assert store.writes == 1
    assert store.row['deliverable_text'] == original


def test_completed_order_retry_still_requires_correct_token():
    set_store_for_tests(Store(state='DELIVERY_READY'))
    response = client.post('/orders/ord_retry/intake', headers={'x-intake-token': 'wrong'},
                           json={'business_name': 'Acme', 'industry': 'Repairs'})
    assert response.status_code == 401


def test_token_handoff_and_download_are_not_cacheable():
    set_store_for_tests(Store(state='DELIVERY_READY'))
    for url in ['/handoff?session_id=cs_test_retry', '/success?session_id=cs_test_retry',
                '/orders/ord_retry/deliverable?token=tok_retry']:
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['referrer-policy'] == 'no-referrer'


def test_non_latin_business_name_can_download_pack():
    set_store_for_tests(Store(state='DELIVERY_READY', business='東京 Café'))
    response = client.get('/orders/ord_retry/deliverable?token=tok_retry')
    assert response.status_code == 200
    response.headers['content-disposition'].encode('ascii')
