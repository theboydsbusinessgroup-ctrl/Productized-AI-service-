"""HTTP boundary checks: payment claims cannot unlock consultation scheduling."""
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
import stripe
import httpx
from fastapi.testclient import TestClient

from app.consultations import Slot, health, parse_gumroad_notification
from app.consultation_store import set_consultation_store_for_tests
from app.main import app


client = TestClient(app)
WEBHOOK_SECRET = 'whsec_consultation_test_fixture'


def configure(monkeypatch):
    for name, value in {
        'DATABASE_URL': 'postgresql://not-used',
        'CONSULTATION_PAYMENT_LINK_URL': 'https://buy.stripe.com/consultation_fixture',
        'CONSULTATION_PAYMENT_LINK_ID': 'plink_consultation_fixture',
        'CONSULTATION_STRIPE_WEBHOOK_SECRET': WEBHOOK_SECRET,
        'CONSULTATION_GUMROAD_PRODUCT_ID': 'ebook_fixture',
        'CONSULTATION_ADMIN_TOKEN': 'consultation_owner_fixture',
        'CONSULTATION_GUMROAD_WEBHOOK_TOKEN': 'gumroad_notification_fixture',
        'CONSULTATION_GUMROAD_ACCESS_TOKEN': 'gumroad_access_fixture',
        'CONSULTATION_GOOGLE_CALENDAR_ID': 'host@example.com',
    }.items():
        monkeypatch.setenv(name, value)


def signed(payload):
    body = json.dumps(payload, separators=(',', ':'))
    timestamp = int(time.time())
    signature = stripe.WebhookSignature._compute_signature(f'{timestamp}.{body}', WEBHOOK_SECRET)
    return body, {'stripe-signature': f't={timestamp},v1={signature}', 'content-type': 'application/json'}


def paid_event(reference, event_id='evt_consultation_fixture', **overrides):
    session = {'id': 'cs_live_consultation_fixture', 'client_reference_id': reference,
               'payment_status': 'paid', 'mode': 'payment', 'amount_total': 1900,
               'currency': 'usd', 'payment_link': 'plink_consultation_fixture',
               'payment_intent': 'pi_consultation_fixture',
               'customer_details': {'email': 'buyer@example.com'}}
    session.update(overrides)
    return {'id': event_id, 'livemode': True, 'type': 'checkout.session.completed',
            'data': {'object': session}}


def send_event(payload):
    body, headers = signed(payload)
    return client.post('/consultations/webhooks/stripe', content=body, headers=headers)


def future_slot():
    start = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0)
    return {'start_datetime': start.isoformat(), 'end_datetime': (start + timedelta(minutes=20)).isoformat(),
            'timezone': 'Etc/UTC'}


def test_unsigned_webhook_and_unconfigured_webhook_fail_closed(monkeypatch):
    configure(monkeypatch)
    response = client.post('/consultations/webhooks/stripe', json=paid_event('con_unpaid'))
    assert response.status_code == 400
    monkeypatch.delenv('CONSULTATION_STRIPE_WEBHOOK_SECRET')
    assert send_event(paid_event('con_unpaid')).status_code == 503


def test_a_forged_signature_never_reaches_payment_storage(monkeypatch):
    configure(monkeypatch)
    body, headers = signed(paid_event('con_forged'))
    headers['stripe-signature'] = headers['stripe-signature'][:-8] + '00000000'
    assert client.post('/consultations/webhooks/stripe', content=body, headers=headers).status_code == 400


@pytest.mark.parametrize('overrides,reason', [
    ({'payment_status': 'unpaid'}, 'payment_not_paid'),
    ({'payment_link': 'plink_content_pack'}, 'unexpected_payment_link'),
])
def test_unpaid_or_other_offer_events_are_ignored(monkeypatch, overrides, reason):
    configure(monkeypatch)
    response = send_event(paid_event('con_reference', **overrides))
    assert response.status_code == 200
    assert response.json()['ignored'] is True
    assert response.json()['reason'] == reason


def test_test_mode_payment_and_query_claims_do_not_unlock_scheduling(monkeypatch):
    configure(monkeypatch)
    event = paid_event('con_reference')
    event['livemode'] = False
    assert send_event(event).json()['reason'] == 'not_live_event'
    response = client.post('/consultations/con_reference/times?paid=true', json={'slots': [future_slot()]})
    assert response.status_code == 401


def test_only_owner_credential_can_import_sales_or_approve_a_time(monkeypatch):
    configure(monkeypatch)
    slot = future_slot()
    payload = {**slot, 'revision': 1, 'calendar_available': True,
               'calendar_checked_at': datetime.now(timezone.utc).isoformat()}
    assert client.post('/consultations/internal/con_reference/approve', json=payload).status_code == 401
    assert client.get('/consultations/internal/requests').status_code == 401
    sale = {'sale_id': 'sale_1', 'product_id': 'ebook_fixture', 'purchase_email': 'buyer@example.com',
            'payment_succeeded': True, 'refunded': False, 'disputed': False}
    assert client.post('/consultations/internal/sales/import', json=sale).status_code == 401
    assert client.post('/consultations/internal/sales/import', json=sale,
                       headers={'x-consultation-admin-token': 'gumroad_notification_fixture'}).status_code == 401


def test_checkout_requires_accepted_terms_before_any_storage(monkeypatch):
    configure(monkeypatch)
    payload = {'customer_email': 'buyer@example.com', 'ebook_order_id': 'sale_1', 'terms_accepted': False}
    assert client.post('/consultations/checkout', json=payload).status_code == 422
    payload['terms_accepted'] = 'true'
    assert client.post('/consultations/checkout', json=payload).status_code == 422


@pytest.mark.parametrize('change', ['naive', 'wrong_duration', 'past', 'wrong_timezone_offset'])
def test_slot_dates_are_future_exact_duration_and_timezone_aware(change):
    slot = future_slot()
    if change == 'naive':
        slot['start_datetime'] = slot['start_datetime'][:-6]
    elif change == 'wrong_duration':
        slot['end_datetime'] = (datetime.fromisoformat(slot['start_datetime']) + timedelta(minutes=21)).isoformat()
    elif change == 'past':
        start = datetime.now(timezone.utc) - timedelta(days=1)
        slot['start_datetime'], slot['end_datetime'] = start.isoformat(), (start + timedelta(minutes=20)).isoformat()
    else:
        slot['timezone'] = 'America/Chicago'
    with pytest.raises(Exception) as exc:
        Slot(**slot).canonical()
    assert getattr(exc.value, 'status_code', None) == 422


def test_provider_callback_needs_a_separate_secret_and_valid_identity(monkeypatch):
    configure(monkeypatch)
    data = 'product_id=ebook_fixture&email=buyer%40example.com'
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    assert client.post('/consultations/webhooks/gumroad/sale', content=data, headers=headers).status_code == 401
    response = client.post('/consultations/webhooks/gumroad/sale', content=data,
                           headers={**headers, 'x-gumroad-webhook-token': 'gumroad_notification_fixture'})
    assert response.status_code == 422


def test_unsigned_ping_is_only_an_identity_trigger_and_never_payment_evidence():
    fields = {'sale_id': 'sale_1', 'order_number': 'receipt_1', 'product_id': 'ebook_fixture',
              'email': 'buyer@example.com', 'test': 'false'}
    purchase = parse_gumroad_notification(fields, 'sale')
    assert not hasattr(purchase, 'payment_succeeded') and not hasattr(purchase, 'refunded')
    assert purchase.order_number == 'receipt_1'
    assert parse_gumroad_notification({**fields, 'refunded': 'true'}, 'refund').sale_id == 'sale_1'
    assert parse_gumroad_notification({**fields, 'test': 'true'}, 'sale').sale_id == 'sale_1'
    with pytest.raises(ValueError):
        parse_gumroad_notification({**fields, 'resource_name': 'refund'}, 'sale')


def test_payment_readiness_requires_operational_intake_and_owner_secrets(monkeypatch):
    configure(monkeypatch)
    class ReachableStore:
        def healthcheck(self):
            return True
    set_consultation_store_for_tests(ReachableStore())
    try:
        assert health()['payment_gate'] is True
        monkeypatch.delenv('CONSULTATION_GUMROAD_WEBHOOK_TOKEN')
        assert health()['payment_gate'] is False
        monkeypatch.setenv('CONSULTATION_GUMROAD_WEBHOOK_TOKEN', 'fixture')
        monkeypatch.delenv('CONSULTATION_GUMROAD_ACCESS_TOKEN')
        assert health()['payment_gate'] is False
        monkeypatch.setenv('CONSULTATION_GUMROAD_ACCESS_TOKEN', 'fixture')
        monkeypatch.delenv('CONSULTATION_ADMIN_TOKEN')
        assert health()['payment_gate'] is False
    finally:
        set_consultation_store_for_tests(None)


def test_consultation_pages_do_not_claim_booking_from_payment_redirect():
    response = client.get('/consultations/success?paid=true&session_id=forged')
    assert response.status_code == 200
    assert 'Scheduling opens after Stripe confirms successful payment' in response.text
    assert "'/consultations/handoff?session_id='" in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    landing = client.get('/consultations')
    assert 'Payment buys your session; it does not reserve a time' in landing.text
    assert 'https://boydsbusiness.gumroad.com/l/yknubt' in landing.text
    assert "if(d.state==='BOOKED'||d.state==='COMPLETED')" in response.text
    assert 'Your session is confirmed.' in response.text


def mock_gumroad(monkeypatch, *, api_sale=None, listed=None, failure=None):
    value = {'id': 'sale_1', 'product_id': 'ebook_fixture', 'email': 'buyer@example.com',
             'purchase_email': 'buyer@example.com', 'order_id': 12345,
             'paid': True, 'price': 900, 'refunded': False, 'disputed': False}
    value.update(api_sale or {})
    requests = []
    def handle(request):
        requests.append(request)
        if failure:
            raise failure
        if request.url.path.endswith('/sales/sale_1'):
            return httpx.Response(200, json={'success': True, 'sale': value})
        assert request.url.path == '/v2/sales'
        assert dict(request.url.params) == {'product_id': 'ebook_fixture', 'email': value['purchase_email'],
                                          'order_id': str(value['order_id'])}
        return httpx.Response(200, json={'success': True, 'sales': [value] if listed is None else listed})
    original = httpx.AsyncClient
    monkeypatch.setattr('app.consultations.httpx.AsyncClient', lambda **kwargs:
                        original(transport=httpx.MockTransport(handle), **kwargs))
    return requests


def trigger_callback(resource='sale', **fields):
    from urllib.parse import urlencode
    payload = {'sale_id': 'sale_1', 'product_id': 'ebook_fixture', 'email': 'buyer@example.com',
               'order_number': '12345', 'resource_name': resource}
    payload.update(fields)
    return client.post('/consultations/webhooks/gumroad/' + resource, content=urlencode(payload),
                       headers={'content-type': 'application/x-www-form-urlencoded',
                                'x-gumroad-webhook-token': 'gumroad_notification_fixture'})


def test_gumroad_callback_reads_provider_state_and_keeps_credentials_out_of_urls(monkeypatch):
    configure(monkeypatch)
    observed = []
    class SaleStore:
        def import_sale(self, value, source):
            observed.append((value, source))
    set_consultation_store_for_tests(SaleStore())
    try:
        requests = mock_gumroad(monkeypatch)
        response = trigger_callback(refunded='true', failed='true')
        assert response.status_code == 200
        assert len(requests) == 2
        assert all(request.headers['authorization'] == 'Bearer gumroad_access_fixture' for request in requests)
        assert all('access_token' not in request.url.query.decode() and 'gumroad_access_fixture' not in str(request.url)
                   for request in requests)
        assert observed[0][0]['payment_succeeded'] is True and observed[0][0]['refunded'] is False
        assert observed[0][1] == 'verified_gumroad_api_readback'
    finally:
        set_consultation_store_for_tests(None)


@pytest.mark.parametrize('api_sale,listed', [
    ({'id': 'another_sale'}, None),
    ({'product_id': 'another_product'}, None),
    ({'email': 'another@example.com', 'purchase_email': 'another@example.com'}, None),
    ({'order_id': 54321}, None),
    ({}, []),
    ({'test': True}, None),
    ({'paid': False, 'price': 0}, None),
])
def test_api_identity_mismatch_test_failed_or_unsettled_sale_never_imports(monkeypatch, api_sale, listed):
    configure(monkeypatch)
    class NeverImport:
        def import_sale(self, value, source):
            raise AssertionError('Unverified purchase was imported')
    set_consultation_store_for_tests(NeverImport())
    try:
        mock_gumroad(monkeypatch, api_sale=api_sale, listed=listed)
        response = trigger_callback()
        assert response.status_code in (422, 503)
    finally:
        set_consultation_store_for_tests(None)


@pytest.mark.parametrize('resource', ['refund', 'dispute'])
def test_unsigned_revocation_flag_does_not_create_a_tombstone_without_api_evidence(monkeypatch, resource):
    configure(monkeypatch)
    mock_gumroad(monkeypatch)
    response = trigger_callback(resource, refunded='true', disputed='true')
    assert response.status_code == 503
    assert 'Provider revocation is not yet verified' in response.json()['detail']


@pytest.mark.parametrize('resource,flag', [('refund', 'refunded'), ('dispute', 'disputed')])
def test_verified_api_revocation_is_imported_even_for_a_delayed_sale_notification(monkeypatch, resource, flag):
    configure(monkeypatch)
    observed = []
    class SaleStore:
        def import_sale(self, value, source):
            observed.append(value)
    set_consultation_store_for_tests(SaleStore())
    try:
        mock_gumroad(monkeypatch, api_sale={flag: True})
        assert trigger_callback(resource).status_code == 200
        assert observed[0][flag] is True
    finally:
        set_consultation_store_for_tests(None)


def test_lookup_failure_is_retryable_and_never_returns_credential_or_provider_body(monkeypatch):
    configure(monkeypatch)
    mock_gumroad(monkeypatch, failure=httpx.ConnectTimeout('gumroad_access_fixture must stay private'))
    response = trigger_callback()
    assert response.status_code == 503
    assert 'gumroad_access_fixture' not in response.text
    monkeypatch.delenv('CONSULTATION_GUMROAD_ACCESS_TOKEN')
    assert trigger_callback().status_code == 503


def test_refund_visible_in_second_api_read_prevents_a_stale_positive_sale_import(monkeypatch):
    configure(monkeypatch)
    observed = []
    class SaleStore:
        def import_sale(self, value, source):
            observed.append(value)
    listed = [{'id': 'sale_1', 'product_id': 'ebook_fixture', 'email': 'buyer@example.com',
               'purchase_email': 'buyer@example.com', 'order_id': 12345, 'paid': True,
               'price': 900, 'refunded': True, 'disputed': False}]
    set_consultation_store_for_tests(SaleStore())
    try:
        mock_gumroad(monkeypatch, listed=listed)
        assert trigger_callback().status_code == 200
        assert observed[0]['refunded'] is True
    finally:
        set_consultation_store_for_tests(None)
