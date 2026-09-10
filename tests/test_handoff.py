from fastapi.testclient import TestClient
from app.main import app
from app.store import set_store_for_tests

client=TestClient(app)

class FakeStore:
    def __init__(self,row=None): self.row=row
    def get_order_by_session(self,sid): return self.row

def test_handoff_waits_when_webhook_not_processed():
    set_store_for_tests(FakeStore(None))
    r=client.get('/handoff?session_id=cs_test_wait')
    assert r.status_code==200 and r.json()['ready'] is False

def test_handoff_returns_paid_intake_token():
    set_store_for_tests(FakeStore({'order_id':'ord_1','state':'PAID','intake_token':'tok_1'}))
    r=client.get('/handoff?session_id=cs_test_paid')
    assert r.status_code==200
    assert r.json()=={'ready':True,'state':'PAID','order_id':'ord_1','intake_token':'tok_1'}

def test_success_page_is_mobile_intake_handoff():
    r=client.get('/success?session_id=cs_test_1')
    assert r.status_code==200
    assert 'Submit and start production' in r.text
    assert 'viewport' in r.text
