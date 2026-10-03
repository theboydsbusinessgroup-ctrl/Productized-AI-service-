import os
import secrets
from typing import Any

import psycopg
from psycopg.rows import dict_row

class PostgresOrderStore:
    def __init__(self,database_url:str): self.database_url=database_url
    def _connect(self): return psycopg.connect(self.database_url,row_factory=dict_row,connect_timeout=10)
    def healthcheck(self)->bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                # Reachability alone cannot establish checkout/fulfillment readiness.
                cur.execute('select order_id,state,customer_email,amount_usd,stripe_session_id,intake_token,intake,deliverable_text,delivered_at,updated_at from public.productized_ai_orders limit 0')
                cur.execute('select event_type,order_id,source,metadata from public.productized_ai_funnel_events limit 0')
                cur.execute('select order_id,state,lease_token,available_at from public.productized_ai_fulfillment_jobs limit 0')
                cur.execute('select event_id,livemode,amount_cents from public.productized_ai_payment_receipts limit 0')
                cur.execute('select observed_at,summary from public.productized_ai_reconciliations limit 0')
                cur.execute('select 1')
                return cur.fetchone() is not None
    def create_order(self,order_id:str,customer_email:str,amount_usd:int,state:str)->dict[str,Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute('insert into public.productized_ai_orders (order_id,state,customer_email,amount_usd) values (%s,%s,%s,%s) returning *',(order_id,state,customer_email,amount_usd)); return dict(cur.fetchone())
    def get_order(self,order_id:str)->dict[str,Any]|None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute('select * from public.productized_ai_orders where order_id=%s',(order_id,)); row=cur.fetchone(); return dict(row) if row else None
    def get_order_by_session(self,stripe_session_id:str)->dict[str,Any]|None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute('select * from public.productized_ai_orders where stripe_session_id=%s',(stripe_session_id,)); row=cur.fetchone(); return dict(row) if row else None
    def mark_paid(self,order_id:str,stripe_session_id:str|None,intake_token:str,event:dict|None=None)->dict[str,Any]|None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update public.productized_ai_orders set state='PAID',stripe_session_id=%s,intake_token=%s,updated_at=now() where order_id=%s and state='CHECKOUT_PENDING' returning *",(stripe_session_id,intake_token,order_id))
                row=cur.fetchone()
                if not row:
                    cur.execute("select * from public.productized_ai_orders where order_id=%s and stripe_session_id=%s and state in ('PAID','DELIVERY_READY')",(order_id,stripe_session_id))
                    row=cur.fetchone()
                if row and event:
                    session=event['data']['object']
                    cur.execute('''insert into public.productized_ai_payment_receipts
                        (event_id,order_id,session_id,livemode,amount_cents,currency)
                        values (%s,%s,%s,%s,%s,%s) on conflict(event_id) do nothing''',
                        (event['id'],order_id,stripe_session_id,event.get('livemode'),session['amount_total'],session['currency']))
                return dict(row) if row else None
    def save_fulfillment(self,order_id:str,intake:dict[str,Any],deliverable_text:str)->dict[str,Any]|None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update public.productized_ai_orders set state='DELIVERY_READY',intake=%s::jsonb,deliverable_text=%s,delivered_at=now(),updated_at=now() where order_id=%s and state='PAID' returning *",(psycopg.types.json.Jsonb(intake),deliverable_text,order_id))
                row=cur.fetchone()
                if row:
                    return {**dict(row), '_fulfillment_created': True}
                # A concurrent submission may already have fulfilled this order.
                # Return the original result rather than replacing purchased content.
                cur.execute("select * from public.productized_ai_orders where order_id=%s and state='DELIVERY_READY'",(order_id,))
                row=cur.fetchone()
                return {**dict(row), '_fulfillment_created': False} if row else None

    def log_event(self,event_type:str,order_id:str|None=None,source:str|None=None,metadata:dict[str,Any]|None=None):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("insert into public.productized_ai_funnel_events(event_type,order_id,source,metadata) values (%s,%s,%s,%s::jsonb)",(event_type,order_id,source,psycopg.types.json.Jsonb(metadata or {})))

    def enqueue_fulfillment(self,order_id:str,intake:dict):
        with self._connect() as conn:
            conn.execute('''insert into public.productized_ai_fulfillment_jobs(order_id,intake)
                select order_id,%s::jsonb from public.productized_ai_orders where order_id=%s and state='PAID'
                on conflict(order_id) do nothing''',(psycopg.types.json.Jsonb(intake),order_id))

    def claim_fulfillment(self,order_id:str|None=None):
        token=secrets.token_urlsafe(18)
        with self._connect() as conn:
            row=conn.execute('''update public.productized_ai_fulfillment_jobs set state='RUNNING',
                attempts=attempts+1,lease_token=%s,lease_until=now()+interval '2 minutes'
                where order_id=(select order_id from public.productized_ai_fulfillment_jobs
                where (state='PENDING' or (state='RUNNING' and lease_until<now())) and attempts<5
                and available_at<=now() and (%s::text is null or order_id=%s)
                order by available_at for update skip locked limit 1) returning *''',(token,order_id,order_id)).fetchone()
            # Expired final leases are surfaced rather than silently abandoned.
            conn.execute("update public.productized_ai_fulfillment_jobs set state='FAILED',error_code='attempts_exhausted' where state='RUNNING' and lease_until<now() and attempts>=5")
            return dict(row) if row else None

    def complete_fulfillment(self,job:dict,text:str):
        with self._connect() as conn:
            active=conn.execute("select order_id from public.productized_ai_fulfillment_jobs where order_id=%s and state='RUNNING' and lease_token=%s for update",(job['order_id'],job['lease_token'])).fetchone()
            if not active:return False
            row=conn.execute("update public.productized_ai_orders set state='DELIVERY_READY',intake=%s::jsonb,deliverable_text=%s,delivered_at=now(),updated_at=now() where order_id=%s and state='PAID' returning order_id",(psycopg.types.json.Jsonb(job['intake']),text,job['order_id'])).fetchone()
            if not row and not conn.execute("select order_id from public.productized_ai_orders where order_id=%s and state='DELIVERY_READY'",(job['order_id'],)).fetchone():
                raise RuntimeError('order_not_paid')
            conn.execute("update public.productized_ai_fulfillment_jobs set state='DONE',completed_at=now(),lease_token=null,lease_until=null where order_id=%s",(job['order_id'],))
            if row:conn.execute("insert into public.productized_ai_funnel_events(event_type,order_id,metadata) values ('delivery_ready',%s,'{}')",(job['order_id'],))
            return True

    def fail_fulfillment(self,job:dict,retryable:bool):
        with self._connect() as conn:
            conn.execute("""update public.productized_ai_fulfillment_jobs set state=%s,
                available_at=now()+make_interval(secs=>least(3600,30*power(2,attempts)::int)),
                error_code=%s,lease_token=null,lease_until=null where order_id=%s and lease_token=%s""",
                ('PENDING' if retryable and job['attempts']<5 else 'FAILED','transient_storage' if retryable else 'generation_or_state_error',job['order_id'],job['lease_token']))

    def operations_summary(self):
        with self._connect() as conn:
            receipts=conn.execute('''select count(distinct session_id) filter(where livemode is true)::int as live_captures,
                coalesce(sum(amount_cents) filter(where livemode is true),0)::bigint as gross_cents,
                count(*) filter(where livemode is null)::int as unknown_mode_receipts
                from (select distinct on(session_id) * from public.productized_ai_payment_receipts order by session_id,received_at) r''').fetchone()
            jobs=conn.execute('select state,count(*)::int as count from public.productized_ai_fulfillment_jobs group by state').fetchall()
            reconciliation=conn.execute("select observed_at,summary from public.productized_ai_reconciliations where provider='stripe'").fetchone()
            return {'status':'webhook_receipts_only','scope':'productized_ai','currency':'usd',
                'gross_revenue':float(receipts['gross_cents'])/100,'live_captures':receipts['live_captures'],
                'unknown_mode_receipts':receipts['unknown_mode_receipts'],'refunds':None,'fees':None,'contribution':None,
                'settlement_verified':False,'coverage_since':'2026-10-03T06:47:25Z',
                'jobs':{r['state']:r['count'] for r in jobs},
                'reconciliation':dict(reconciliation) if reconciliation else None,
                'observed_at':conn.execute('select now() as observed_at').fetchone()['observed_at']}

    def funnel_summary(self):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select event_type,count(*)::int as count from public.productized_ai_funnel_events group by event_type order by event_type")
                counts={r['event_type']:r['count'] for r in cur.fetchall()}
                cur.execute("""select count(*)::int as paid_orders,
                    count(*) filter (where left(stripe_session_id,8) = 'cs_live_')::int as live_paid_orders,
                    count(*) filter (where left(stripe_session_id,8) = 'cs_test_')::int as test_paid_orders,
                    count(*) filter (where stripe_session_id is null or
                        (left(stripe_session_id,8) not in ('cs_live_','cs_test_')))::int as unknown_mode_paid_orders
                    from public.productized_ai_orders where state in ('PAID','DELIVERY_READY')""")
                paid=dict(cur.fetchone())
                return {'events':counts,**paid,'revenue_note':'Event counts and paid_orders include tests. Use live_paid_orders for live order counts; settlement, refunds and profit require Stripe reconciliation.'}

_store=None
def get_store():
    global _store
    if _store is None:
        database_url=os.getenv('DATABASE_URL')
        if not database_url: raise RuntimeError('DATABASE_URL is not configured')
        _store=PostgresOrderStore(database_url)
    return _store
def set_store_for_tests(store):
    global _store; _store=store
