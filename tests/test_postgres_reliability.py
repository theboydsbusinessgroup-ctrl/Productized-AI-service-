"""Integration checks against a disposable database whose name ends in _test."""
import os
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from app.store import PostgresOrderStore


@pytest.fixture
def store():
    url = os.getenv('PRODUCTIZED_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Disposable PostgreSQL test database not configured')
    if not conninfo_to_dict(url).get('dbname', '').endswith('_test'):
        pytest.fail('Refusing to modify a database without a _test name')
    with psycopg.connect(url) as connection:
        connection.execute('''create table if not exists public.productized_ai_orders (
            order_id text primary key, state text not null, customer_email text not null,
            amount_usd integer not null, stripe_session_id text unique, intake_token text,
            intake jsonb, deliverable_text text, delivered_at timestamptz,
            updated_at timestamptz not null default now())''')
        connection.execute('''create table if not exists public.productized_ai_funnel_events (
            event_type text, order_id text, source text, metadata jsonb)''')
        connection.execute('truncate public.productized_ai_orders, public.productized_ai_funnel_events')
    return PostgresOrderStore(url)


def test_concurrent_fulfillment_keeps_exactly_one_original_pack(store):
    store.create_order('ord_race', 'test@example.com', 49, 'CHECKOUT_PENDING')
    store.mark_paid('ord_race', 'cs_test_race', 'intake_test')
    def fulfill(index):
        return store.save_fulfillment('ord_race', {'business_name': f'Business {index}'}, f'Pack {index}')
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(fulfill, range(4)))
    assert sum(row['_fulfillment_created'] for row in results) == 1
    assert len({row['deliverable_text'] for row in results}) == 1
    assert store.get_order('ord_race')['deliverable_text'] == results[0]['deliverable_text']


def test_unpaid_order_cannot_be_fulfilled(store):
    store.create_order('ord_unpaid', 'test@example.com', 49, 'CHECKOUT_PENDING')
    assert store.save_fulfillment('ord_unpaid', {}, 'unpaid content') is None
    assert store.get_order('ord_unpaid')['state'] == 'CHECKOUT_PENDING'


def test_funnel_separates_live_test_and_unknown_orders(store):
    for index, session in enumerate(['cs_live_example', 'cs_test_example', 'legacy_example', 'csXliveXfake']):
        order = f'ord_{index}'
        store.create_order(order, 'test@example.com', 49, 'CHECKOUT_PENDING')
        store.mark_paid(order, session, 'intake_test')
    summary = store.funnel_summary()
    assert summary['paid_orders'] == 4
    assert summary['live_paid_orders'] == 1
    assert summary['test_paid_orders'] == 1
    assert summary['unknown_mode_paid_orders'] == 2
    assert store.healthcheck()
