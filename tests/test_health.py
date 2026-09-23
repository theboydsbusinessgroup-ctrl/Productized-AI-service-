from fastapi.testclient import TestClient

from app.main import app

client=TestClient(app)


def configure_payment(monkeypatch):
    monkeypatch.setenv('DATABASE_URL','postgresql://configured')
    monkeypatch.setenv('STRIPE_PAYMENT_LINK_URL','https://buy.stripe.com/test')
    monkeypatch.setenv('STRIPE_PAYMENT_LINK_ID','plink_test_123')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_test_secret')


def test_health_reports_ready_only_when_payment_is_configured(monkeypatch):
    configure_payment(monkeypatch)
    data=client.get('/health').json()
    assert data['status']=='ok'
    assert data['persistent_store'] is True
    assert data['instant_fulfillment'] is True
    assert data['version']=='0.7.0'
    assert data['payment_gate'] is True
    assert all(data['payment_configuration'].values())


def test_health_fails_payment_gate_when_webhook_secret_is_missing(monkeypatch):
    configure_payment(monkeypatch)
    monkeypatch.delenv('STRIPE_WEBHOOK_SECRET')
    data=client.get('/health').json()
    assert data['status']=='ok'
    assert data['payment_gate'] is False
    assert data['payment_configuration']['STRIPE_WEBHOOK_SECRET'] is False


def test_offer():
    assert client.get('/offer').json()['price_usd']==49
