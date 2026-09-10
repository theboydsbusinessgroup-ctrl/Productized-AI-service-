from fastapi.testclient import TestClient

from app.main import ORDERS, app

client = TestClient(app)


def setup_function():
    ORDERS.clear()


def test_checkout_requires_configuration(monkeypatch):
    monkeypatch.delenv("STRIPE_PAYMENT_LINK_URL", raising=False)
    response = client.post("/checkout", json={"customer_email": "buyer@example.com"})
    assert response.status_code == 503


def test_paid_order_unlocks_intake(monkeypatch):
    monkeypatch.setenv("STRIPE_PAYMENT_LINK_URL", "https://buy.stripe.com/test")
    checkout = client.post("/checkout", json={"customer_email": "buyer@example.com"})
    assert checkout.status_code == 200
    data = checkout.json()
    assert data["state"] == "CHECKOUT_PENDING"
    assert "client_reference_id=" in data["checkout_url"]

    order_id = data["order_id"]
    unpaid = client.post(
        f"/orders/{order_id}/intake",
        headers={"x-intake-token": "nope"},
        json={"business_name": "Acme", "industry": "Home services"},
    )
    assert unpaid.status_code == 402

    paid = client.post(
        "/webhooks/stripe",
        json={
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_123", "client_reference_id": order_id}},
        },
    )
    assert paid.status_code == 200
    token = paid.json()["intake_token"]

    intake = client.post(
        f"/orders/{order_id}/intake",
        headers={"x-intake-token": token},
        json={"business_name": "Acme", "industry": "Home services"},
    )
    assert intake.status_code == 200
    assert intake.json()["state"] == "INTAKE"


def test_unrelated_stripe_event_is_ignored():
    response = client.post("/webhooks/stripe", json={"type": "customer.created", "data": {}})
    assert response.status_code == 200
    assert response.json()["ignored"] is True
