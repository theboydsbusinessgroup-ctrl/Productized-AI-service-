"""Durable entitlement/race checks against an isolated *_test PostgreSQL DB."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, local

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from app.consultation_store import (ConsultationConflict, PostgresConsultationStore,
                                    set_consultation_store_for_tests)
from test_consultations import (client, configure, future_slot, paid_event, send_event)


@pytest.fixture
def store(monkeypatch):
    configure(monkeypatch)
    url = os.getenv('PRODUCTIZED_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Disposable PostgreSQL database not configured')
    if not conninfo_to_dict(url).get('dbname', '').endswith('_test'):
        pytest.fail('Refusing to modify a database without a _test name')
    schema = (Path(__file__).parents[1] / 'supabase/schemas/consultations.sql').read_text()
    schema = schema.replace('create table public.', 'create table if not exists public.')
    schema = schema.replace('create index boyds_', 'create index if not exists boyds_')
    with psycopg.connect(url) as conn:
        conn.execute(schema)
        conn.execute('truncate public.boyds_consultation_payment_receipts, public.boyds_consultations, public.boyds_consultation_sales')
    result = PostgresConsultationStore(url)
    set_consultation_store_for_tests(result)
    yield result
    set_consultation_store_for_tests(None)


def sale(store, **overrides):
    value = {'sale_id': 'sale_fixture', 'product_id': 'ebook_fixture', 'purchase_email': 'buyer@example.com',
             'payment_succeeded': True, 'refunded': False, 'disputed': False}
    value.update(overrides)
    store.import_sale(value, 'trusted_operator_provider_read')
    return value


def checkout():
    return client.post('/consultations/checkout', json={'customer_email': 'buyer@example.com',
                       'ebook_order_id': 'sale_fixture', 'code': 'BARBUYER', 'terms_accepted': True})


def paid_request(store):
    sale(store)
    response = checkout()
    assert response.status_code == 200
    request_id = response.json()['request_id']
    assert send_event(paid_event(request_id)).status_code == 200
    handoff = client.get('/consultations/handoff?session_id=cs_live_consultation_fixture').json()
    assert handoff['ready'] is True
    return request_id, handoff['intake_token']


def test_only_a_matching_trusted_qualifying_purchase_gets_a_payment_url(store):
    assert checkout().status_code == 409
    sale(store, purchase_email='someone_else@example.com')
    assert checkout().status_code == 409
    with store._connect() as conn:
        assert conn.execute('select count(*) as n from public.boyds_consultations').fetchone()['n'] == 0


@pytest.mark.parametrize('bad', [
    {'refunded': True}, {'disputed': True}, {'payment_succeeded': False}, {'product_id': 'another_product'},
])
def test_ineligible_purchases_cannot_start_checkout(store, bad):
    sale(store, **bad)
    assert checkout().status_code == 409


def test_pending_checkout_has_no_scheduling_token_and_repeat_checkout_reuses_one_request(store):
    sale(store)
    first, second = checkout().json(), checkout().json()
    assert first['request_id'] == second['request_id']
    assert 'client_reference_id=con_' in first['checkout_url']
    assert 'prefilled_email=buyer%40example.com' in first['checkout_url']
    assert client.get('/consultations/handoff?session_id=cs_live_consultation_fixture').json()['ready'] is False
    response = client.post(f"/consultations/{first['request_id']}/times", json={'slots': [future_slot()]},
                           headers={'x-consultation-token': 'made_up'})
    assert response.status_code == 409


def test_payment_first_flow_then_manual_slot_approval_never_claims_calendar_booking(store):
    request_id, token = paid_request(store)
    slot = future_slot()
    proposed = client.post(f'/consultations/{request_id}/times', json={'slots': [slot]},
                           headers={'x-consultation-token': token})
    assert proposed.status_code == 200
    revision = proposed.json()['revision']
    approval = {**slot, 'revision': revision, 'calendar_available': True,
                'calendar_checked_at': datetime.now(timezone.utc).isoformat()}
    response = client.post(f'/consultations/internal/{request_id}/approve', json=approval,
                           headers={'x-consultation-admin-token': 'consultation_owner_fixture'})
    assert response.status_code == 200
    assert response.json()['state'] == 'APPROVED_AWAITING_CALENDAR'
    assert response.json()['booking_confirmed'] is False
    assert checkout().status_code == 409


@pytest.mark.parametrize('overrides,reason', [
    ({'amount_total': 1800}, 'unexpected_amount'),
    ({'currency': 'eur'}, 'unexpected_currency'),
    ({'mode': 'subscription'}, 'unexpected_checkout_mode'),
    ({'customer_details': {'email': 'other@example.com'}}, 'payment_email_mismatch'),
    ({'client_reference_id': None}, 'unknown_or_missing_reference'),
])
def test_paid_mismatches_are_durable_unresolved_payments_not_entitlements(store, overrides, reason):
    sale(store)
    request_id = checkout().json()['request_id']
    event = paid_event(request_id, **overrides)
    response = send_event(event)
    assert response.status_code == 200
    assert response.json()['reason'] == reason
    assert client.get('/consultations/handoff?session_id=cs_live_consultation_fixture').json()['ready'] is False
    unresolved = store.pending_requests()['unresolved_payments']
    assert len(unresolved) == 1 and unresolved[0]['reason'] == reason


def test_duplicate_and_concurrent_events_grant_one_entitlement_preserve_token(store):
    sale(store)
    request_id = checkout().json()['request_id']
    event = paid_event(request_id)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: store.record_payment(event, 'ebook_fixture'), range(4)))
    assert sum(not item['duplicate'] for item in responses) == 1
    token = store.get_by_session('cs_live_consultation_fixture')['intake_token']
    event['id'] = 'evt_second_notification'
    event['type'] = 'checkout.session.async_payment_succeeded'
    store.record_payment(event, 'ebook_fixture')
    assert store.get_by_session('cs_live_consultation_fixture')['intake_token'] == token
    with store._connect() as conn:
        assert conn.execute('select count(*) as n from public.boyds_consultations where payment_valid').fetchone()['n'] == 1


def test_changing_a_paid_slot_resets_approval_and_stale_revision_cannot_be_approved(store):
    request_id, token = paid_request(store)
    from app.consultations import Slot
    original = Slot(**future_slot()).canonical()
    revision = store.propose_slots(request_id, token, [original], 'ebook_fixture')['revision']
    store.approve_slot(request_id, revision, original, datetime.now(timezone.utc), 'ebook_fixture')
    changed = dict(original)
    changed['start_datetime'] = (datetime.fromisoformat(original['start_datetime']) + timedelta(days=1)).isoformat()
    changed['end_datetime'] = (datetime.fromisoformat(original['end_datetime']) + timedelta(days=1)).isoformat()
    revised = store.propose_slots(request_id, token, [changed], 'ebook_fixture')
    with pytest.raises(ConsultationConflict):
        store.approve_slot(request_id, revision, original, datetime.now(timezone.utc), 'ebook_fixture')
    current = store.get_by_session('cs_live_consultation_fixture')
    assert revised['revision'] > revision and current['approved_slot'] is None
    assert current['payment_valid'] is True and current['state'] == 'TIMES_PROPOSED'


@pytest.mark.parametrize('kind', ['charge.refunded', 'charge.dispute.created'])
def test_provider_revocation_blocks_scheduling_and_payment_replay_cannot_restore_it(store, kind):
    request_id, token = paid_request(store)
    event = {'id': 'evt_revoked_fixture', 'livemode': True, 'type': kind,
             'data': {'object': {'payment_intent': 'pi_consultation_fixture', 'amount_refunded': 1900}}}
    assert send_event(event).status_code == 200
    response = client.post(f'/consultations/{request_id}/times', json={'slots': [future_slot()]},
                           headers={'x-consultation-token': token})
    assert response.status_code == 409
    replay = paid_event(request_id, event_id='evt_late_success')
    assert send_event(replay).json()['reason'] == 'payment_already_refunded_or_disputed'
    assert client.get('/consultations/handoff?session_id=cs_live_consultation_fixture').json()['ready'] is False


def test_refund_arriving_before_payment_success_cannot_unlock_an_entitlement(store):
    sale(store)
    request_id = checkout().json()['request_id']
    event = {'id': 'evt_early_refund', 'livemode': True, 'type': 'charge.refunded',
             'data': {'object': {'payment_intent': 'pi_consultation_fixture', 'amount_refunded': 1900}}}
    assert send_event(event).status_code == 200
    assert send_event(paid_event(request_id)).json()['reason'] == 'payment_already_refunded_or_disputed'
    assert store.get_by_session('cs_live_consultation_fixture') is None


def test_ebook_refund_is_monotonic_and_blocks_an_existing_paid_request(store):
    request_id, token = paid_request(store)
    sale(store, refunded=True)
    sale(store, refunded=False)
    current = store.get_by_session('cs_live_consultation_fixture')
    assert current['refunded'] is True and current['state'] == 'PAID_AWAITING_RESOLUTION'
    with pytest.raises(ConsultationConflict):
        store.propose_slots(request_id, token, [future_slot()], 'ebook_fixture')


@pytest.mark.parametrize('available,age', [(False, 0), (True, 6)])
def test_calendar_conflict_or_stale_check_blocks_owner_approval(store, available, age):
    request_id, token = paid_request(store)
    slot = future_slot()
    proposal = client.post(f'/consultations/{request_id}/times', json={'slots': [slot]},
                           headers={'x-consultation-token': token}).json()
    approval = {**slot, 'revision': proposal['revision'], 'calendar_available': available,
                'calendar_checked_at': (datetime.now(timezone.utc)-timedelta(minutes=age)).isoformat()}
    response = client.post(f'/consultations/internal/{request_id}/approve', json=approval,
                           headers={'x-consultation-admin-token': 'consultation_owner_fixture'})
    assert response.status_code == 422


def test_private_tables_are_not_available_to_browser_roles(store):
    with store._connect() as conn:
        tables = ('boyds_consultation_sales', 'boyds_consultations', 'boyds_consultation_payment_receipts')
        for table in tables:
            enabled = conn.execute('select relrowsecurity from pg_class where oid=%s::regclass',
                                   ('public.' + table,)).fetchone()
            assert enabled['relrowsecurity'] is True
            for role in ('anon', 'authenticated'):
                if conn.execute('select 1 from pg_roles where rolname=%s', (role,)).fetchone():
                    assert not conn.execute('select has_table_privilege(%s,%s,\'SELECT\') as permitted',
                                            (role, 'public.' + table)).fetchone()['permitted']


def refund_event(event_id='evt_refund_amount_fixture', **details):
    obj = {'payment_intent': 'pi_consultation_fixture', **details}
    return {'id': event_id, 'livemode': True, 'type': 'charge.refunded',
            'data': {'object': obj}}


@pytest.mark.parametrize('details', [
    {'amount_refunded': 500, 'currency': 'usd'},
    {'amount_refunded': 1900},
    {'currency': 'usd'},
    {'amount_refunded': 1900, 'currency': 'eur'},
])
def test_partial_or_unknown_refund_keeps_paid_obligation_in_owner_queue(store, details):
    request_id, _ = paid_request(store)
    store.revoke_payment(refund_event(**details))
    row = store.get_by_session('cs_live_consultation_fixture')
    assert row['payment_valid'] is False
    assert row['state'] == 'PAID_AWAITING_RESOLUTION'
    assert any(item['request_id'] == request_id for item in store.pending_requests()['requests'])
    assert client.get('/consultations/handoff?session_id=cs_live_consultation_fixture').json()['ready'] is False


def test_full_refund_closes_obligation_but_late_partial_event_cannot_reopen_it(store):
    request_id, _ = paid_request(store)
    store.revoke_payment(refund_event('evt_partial_first', amount_refunded=500, currency='usd'))
    assert store.get_by_session('cs_live_consultation_fixture')['state'] == 'PAID_AWAITING_RESOLUTION'
    store.revoke_payment(refund_event('evt_full_refund', amount_refunded=1900, currency='usd'))
    assert store.get_by_session('cs_live_consultation_fixture')['state'] == 'REFUNDED'
    store.revoke_payment(refund_event('evt_delayed_partial', amount_refunded=500, currency='usd'))
    store.revoke_payment(refund_event('evt_delayed_unknown', currency='usd'))
    row = store.get_by_session('cs_live_consultation_fixture')
    assert row['state'] == 'REFUNDED' and row['payment_valid'] is False
    assert all(item['request_id'] != request_id for item in store.pending_requests()['requests'])
    with store._connect() as conn:
        receipt = conn.execute('''select amount_cents,currency from public.boyds_consultation_payment_receipts
            where event_id='evt_full_refund' ''').fetchone()
        assert receipt['amount_cents'] == 1900 and receipt['currency'] == 'usd'


@pytest.mark.parametrize('first', ['success', 'revocation'])
@pytest.mark.parametrize('kind', ['charge.refunded', 'charge.dispute.created'])
def test_concurrent_payment_success_and_revocation_are_serialized_in_both_orders(store, first, kind):
    sale(store)
    request_id = checkout().json()['request_id']
    acquired_first, attempted_second, acquired_second, release_first = (Event() for _ in range(4))
    context = local()

    class PausedStore(PostgresConsultationStore):
        def _lock_payment_intent(self, conn, intent):
            if context.operation == first:
                super()._lock_payment_intent(conn, intent)
                acquired_first.set()
                if not release_first.wait(5):
                    raise AssertionError('Test did not release the first payment-intent lock')
            else:
                attempted_second.set()
                super()._lock_payment_intent(conn, intent)
                acquired_second.set()

    guarded = PausedStore(store.database_url)
    revocation = refund_event('evt_concurrent_revoke', amount_refunded=1900, currency='usd')
    revocation['type'] = kind

    def perform(operation):
        context.operation = operation
        if operation == 'success':
            return guarded.record_payment(paid_event(request_id), 'ebook_fixture')
        return guarded.revoke_payment(revocation)

    second = 'revocation' if first == 'success' else 'success'
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(perform, first)
        try:
            assert acquired_first.wait(5), 'First handler did not acquire its PI lock'
            second_result = pool.submit(perform, second)
            assert attempted_second.wait(5), 'Second handler did not attempt the same PI lock'
            assert not acquired_second.wait(0.15), 'Revocation and success bypassed mutual exclusion'
        finally:
            release_first.set()
        first_result.result(timeout=5)
        second_result.result(timeout=5)

    with store._connect() as conn:
        row = conn.execute('select payment_valid from public.boyds_consultations where request_id=%s',
                           (request_id,)).fetchone()
        assert row['payment_valid'] is False
    assert client.get('/consultations/handoff?session_id=cs_live_consultation_fixture').json()['ready'] is False
    replay = store.record_payment(paid_event(request_id, event_id='evt_after_concurrent_revoke'), 'ebook_fixture')
    assert replay['reason'] == 'payment_already_refunded_or_disputed'
