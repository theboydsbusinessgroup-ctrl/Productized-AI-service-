from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_webhook_route_rejects_unsigned_request(monkeypatch):
    """The public Stripe route itself must fail closed, not only a helper function."""
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    response = client.post(
        "/webhooks/stripe",
        json={"id": "evt_unsigned", "type": "unhandled.event"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Missing Stripe-Signature header"
