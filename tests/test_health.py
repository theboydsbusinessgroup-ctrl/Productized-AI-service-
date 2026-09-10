from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["payment_gate"] is True


def test_offer():
    response = client.get("/offer")
    assert response.status_code == 200
    assert response.json()["price_usd"] == 49
    assert response.json()["id"] == "social-content-pack-30d"
