from fastapi.testclient import TestClient
from app.main import app
from app.reconciliation import reconcile_stripe


def test_revenue_and_worker_require_distinct_configured_secrets(monkeypatch):
    monkeypatch.setenv('REVENUE_READ_TOKEN','read-test')
    monkeypatch.setenv('CRON_SECRET','cron-test')
    client=TestClient(app)
    assert client.get('/internal/revenue').status_code==401
    assert client.get('/internal/automation').status_code==401
    assert client.get('/internal/automation',headers={'Authorization':'Bearer read-test'}).status_code==401
    assert client.get('/internal/revenue',headers={'x-revenue-token':'cron-test'}).status_code==401


def test_unconfigured_reconciliation_never_reports_zero_as_settled(monkeypatch):
    monkeypatch.delenv('STRIPE_SECRET_KEY',raising=False)
    result=reconcile_stripe(None)
    assert result['status']=='not_configured'
    assert 'captured_cents' not in result


def test_test_mode_key_cannot_feed_live_reconciliation(monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_fixture')
    assert reconcile_stripe(None)['status']=='not_configured'
