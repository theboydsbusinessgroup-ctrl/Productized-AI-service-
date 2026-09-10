from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_health(monkeypatch):
    monkeypatch.setenv("DATABASE_URL","postgresql://configured")
    monkeypatch.setenv("STRIPE_WEBHOOK_TOKEN","configured")
    monkeypatch.delenv("STRIPE_WEBHOOK_TOKEN_ENFORCED", raising=False)
    data=client.get("/health").json()
    assert data["status"] == "ok"
    assert data["persistent_store"] is True
    assert data["webhook_token_configured"] is True
    assert data["webhook_token_enforced"] is False

def test_offer():
    assert client.get("/offer").json()["price_usd"] == 49
