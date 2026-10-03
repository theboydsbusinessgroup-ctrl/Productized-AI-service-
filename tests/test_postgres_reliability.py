"""Integration checks against a disposable database whose name ends in _test."""
import os
from pathlib import Path
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
        for role in ('anon','authenticated','service_role'):
            if not connection.execute('select 1 from pg_roles where rolname=%s',(role,)).fetchone():
                connection.execute(psycopg.sql.SQL('create role {}').format(psycopg.sql.Identifier(role)))
        schema=(Path(__file__).parents[1]/'supabase/schemas/revenue_operations.sql').read_text()
        schema=schema.replace('create table public.','create table if not exists public.').replace('create index productized','create index if not exists productized')
        connection.execute(schema)
        connection.execute('truncate public.productized_ai_orders, public.productized_ai_funnel_events, public.productized_ai_payment_receipts, public.productized_ai_fulfillment_jobs, public.productized_ai_reconciliations')
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


def test_job_durable_intake_and_concurrent_claim_preserve_first_submission(store):
    store.create_order('ord_job','test@example.com',49,'CHECKOUT_PENDING')
    store.mark_paid('ord_job','cs_test_job','tok')
    store.enqueue_fulfillment('ord_job',{'business_name':'First','industry':'Repair'})
    store.enqueue_fulfillment('ord_job',{'business_name':'Second','industry':'Cleaning'})
    with ThreadPoolExecutor(max_workers=4) as executor:
        claimed=list(executor.map(lambda _:store.claim_fulfillment('ord_job'),range(4)))
    jobs=[job for job in claimed if job]
    assert len(jobs)==1 and jobs[0]['intake']['business_name']=='First'
    assert store.complete_fulfillment(jobs[0],'First pack')
    assert not store.complete_fulfillment(jobs[0],'Overwrite attempt')
    assert store.get_order('ord_job')['deliverable_text']=='First pack'
    assert store.operations_summary()['jobs']=={'DONE':1}


def test_signed_receipts_count_actual_mode_and_deduplicate_sessions(store):
    store.create_order('ord_receipt','test@example.com',49,'CHECKOUT_PENDING')
    event={'id':'evt_one','livemode':False,'data':{'object':{'amount_total':4900,'currency':'usd'}}}
    store.mark_paid('ord_receipt','cs_live_lookalike','tok',event)
    assert store.operations_summary()['gross_revenue']==0
    event['id']='evt_two'
    store.mark_paid('ord_receipt','cs_live_lookalike','tok',event)
    with store._connect() as conn:
        assert conn.execute('select count(*) as n from public.productized_ai_payment_receipts').fetchone()['n']==2
    assert store.operations_summary()['live_captures']==0


def test_expired_lease_recovered_and_old_worker_cannot_overwrite(store):
    store.create_order('ord_lease','test@example.com',49,'CHECKOUT_PENDING')
    store.mark_paid('ord_lease','cs_test_lease','tok')
    store.enqueue_fulfillment('ord_lease',{'business_name':'Acme'})
    old=store.claim_fulfillment('ord_lease')
    with store._connect() as conn:
        conn.execute("update public.productized_ai_fulfillment_jobs set lease_until=now()-interval '1 minute'")
    new=store.claim_fulfillment('ord_lease')
    assert new['attempts']==2
    assert not store.complete_fulfillment(old,'stale')
    assert store.complete_fulfillment(new,'current')


def test_unpaid_job_and_nonretryable_failure_cannot_auto_fulfill(store):
    store.create_order('ord_failure','test@example.com',49,'CHECKOUT_PENDING')
    store.enqueue_fulfillment('ord_failure',{})
    assert store.claim_fulfillment() is None
    store.mark_paid('ord_failure','cs_test_failure','tok')
    store.enqueue_fulfillment('ord_failure',{})
    job=store.claim_fulfillment()
    store.fail_fulfillment(job,False)
    assert store.claim_fulfillment() is None
    assert store.operations_summary()['jobs']=={'FAILED':1}
