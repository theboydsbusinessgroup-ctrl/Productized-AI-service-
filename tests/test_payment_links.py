from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.payment_links import build_payment_link
from app.store import set_store_for_tests


@pytest.mark.parametrize('base', [
    'https://example.com/pay', 'http://buy.stripe.com/pay',
    'https://buy.stripe.com@evil.example/pay',
    'https://user@buy.stripe.com/pay', 'https://buy.stripe.com:8443/pay',
    'https://buy.stripe.com/pay#fragment', 'https://buy.stripe.com/',
])
def test_invalid_checkout_destinations_fail_closed(base):
    with pytest.raises(ValueError):
        build_payment_link(base, {'client_reference_id': 'ord_new'})


def test_existing_reference_is_replaced_and_other_parameters_survive():
    result = build_payment_link(
        'https://buy.stripe.com/pay?client_reference_id=old&locale=en&client_reference_id=older',
        {'client_reference_id': 'ord_new', 'prefilled_email': 'buyer+test@example.com'})
    assert parse_qs(urlsplit(result).query) == {
        'client_reference_id': ['ord_new'], 'locale': ['en'],
        'prefilled_email': ['buyer+test@example.com']}


def test_invalid_url_disables_checkout_before_creating_order(monkeypatch):
    class RejectingStore:
        def healthcheck(self):
            return True

        def create_order(self, *args):
            pytest.fail('An invalid payment destination must not create an order')

    set_store_for_tests(RejectingStore())
    monkeypatch.setenv('DATABASE_URL', 'postgresql://configured')
    monkeypatch.setenv('STRIPE_PAYMENT_LINK_URL', 'https://example.com/pay')
    monkeypatch.setenv('STRIPE_PAYMENT_LINK_ID', 'plink_test')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_test')
    client = TestClient(app)
    assert client.get('/health').json()['payment_gate'] is False
    assert client.post('/checkout', json={'customer_email': 'buyer@example.com'}).status_code == 503
