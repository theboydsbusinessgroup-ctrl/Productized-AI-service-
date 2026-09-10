from fastapi.testclient import TestClient
from app.main import app
client=TestClient(app)
def test_health(monkeypatch):
    monkeypatch.setenv('DATABASE_URL','postgresql://configured'); data=client.get('/health').json(); assert data['status']=='ok'; assert data['persistent_store'] is True; assert data['instant_fulfillment'] is True; assert data['version']=='0.6.0'
def test_offer(): assert client.get('/offer').json()['price_usd']==49
