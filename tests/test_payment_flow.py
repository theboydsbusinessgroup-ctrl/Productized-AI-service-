from fastapi.testclient import TestClient
from app.main import app
from app.store import set_store_for_tests

client = TestClient(app)

class FakeStore:
    def __init__(self): self.orders = {}
    def create_order(self, order_id, customer_email, amount_usd, state):
        row={"order_id":order_id,"customer_email":customer_email,"amount_usd":amount_usd,"state":state,"intake_token":None,"stripe_session_id":None,"intake":None}; self.orders[order_id]=row; return row
    def get_order(self, order_id): return self.orders.get(order_id)
    def mark_paid(self, order_id, stripe_session_id, intake_token):
        row=self.orders.get(order_id)
        if not row: return None
        row.update(state="PAID",stripe_session_id=stripe_session_id,intake_token=intake_token); return row
    def save_intake(self, order_id, intake):
        row=self.orders.get(order_id)
        if not row: return None
        row.update(state="INTAKE",intake=intake); return row

def setup_function(): set_store_for_tests(FakeStore())

def test_checkout_requires_configuration(monkeypatch):
    monkeypatch.delenv("STRIPE_PAYMENT_LINK_URL", raising=False)
    assert client.post("/checkout", json={"customer_email":"buyer@example.com"}).status_code == 503

def test_paid_order_persists_and_unlocks_intake(monkeypatch):
    monkeypatch.setenv("STRIPE_PAYMENT_LINK_URL","https://buy.stripe.com/test")
    checkout=client.post("/checkout",json={"customer_email":"buyer@example.com"})
    assert checkout.status_code == 200
    order_id=checkout.json()["order_id"]
    paid=client.post("/webhooks/stripe",json={"type":"checkout.session.completed","data":{"object":{"id":"cs_test_123","client_reference_id":order_id}}})
    assert paid.status_code == 200
    token=paid.json()["intake_token"]
    intake=client.post(f"/orders/{order_id}/intake",headers={"x-intake-token":token},json={"business_name":"Acme","industry":"Home services"})
    assert intake.status_code == 200
    status=client.get(f"/orders/{order_id}")
    assert status.json()["state"] == "INTAKE"
    assert status.json()["has_intake"] is True
