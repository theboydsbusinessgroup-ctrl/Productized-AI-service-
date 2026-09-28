from fastapi.testclient import TestClient

from app.main import app
from app.store import set_store_for_tests


client=TestClient(app)


class FunnelStore:
    def funnel_summary(self):
        return {'events':{'page_view':1},'paid_orders':0}


def setup_function():
    set_store_for_tests(FunnelStore())


def test_internal_funnel_accepts_header_token(monkeypatch):
    monkeypatch.setenv('INTERNAL_API_TOKEN','internal_test_secret')
    response=client.get('/internal/funnel',headers={'x-internal-token':'internal_test_secret'})
    assert response.status_code==200
    assert response.json()['events']['page_view']==1


def test_internal_funnel_rejects_secret_in_query_string(monkeypatch):
    monkeypatch.setenv('INTERNAL_API_TOKEN','internal_test_secret')
    response=client.get('/internal/funnel',params={'token':'internal_test_secret'})
    assert response.status_code==401


def test_internal_funnel_fails_closed_without_configured_token(monkeypatch):
    monkeypatch.delenv('INTERNAL_API_TOKEN',raising=False)
    monkeypatch.delenv('STRIPE_WEBHOOK_TOKEN',raising=False)
    response=client.get('/internal/funnel',headers={'x-internal-token':'anything'})
    assert response.status_code==401
