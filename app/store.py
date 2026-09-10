import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

class PostgresOrderStore:
    def __init__(self,database_url:str): self.database_url=database_url
    def _connect(self): return psycopg.connect(self.database_url,row_factory=dict_row,connect_timeout=10)
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
    def mark_paid(self,order_id:str,stripe_session_id:str|None,intake_token:str)->dict[str,Any]|None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update public.productized_ai_orders set state='PAID',stripe_session_id=%s,intake_token=%s,updated_at=now() where order_id=%s returning *",(stripe_session_id,intake_token,order_id)); row=cur.fetchone(); return dict(row) if row else None
    def save_fulfillment(self,order_id:str,intake:dict[str,Any],deliverable_text:str)->dict[str,Any]|None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update public.productized_ai_orders set state='DELIVERY_READY',intake=%s::jsonb,deliverable_text=%s,delivered_at=now(),updated_at=now() where order_id=%s returning *",(psycopg.types.json.Jsonb(intake),deliverable_text,order_id)); row=cur.fetchone(); return dict(row) if row else None

    def log_event(self,event_type:str,order_id:str|None=None,source:str|None=None,metadata:dict[str,Any]|None=None):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("insert into public.productized_ai_funnel_events(event_type,order_id,source,metadata) values (%s,%s,%s,%s::jsonb)",(event_type,order_id,source,psycopg.types.json.Jsonb(metadata or {})))

    def funnel_summary(self):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select event_type,count(*)::int as count from public.productized_ai_funnel_events group by event_type order by event_type")
                counts={r['event_type']:r['count'] for r in cur.fetchall()}
                cur.execute("select count(*)::int as paid_orders from public.productized_ai_orders where state in ('PAID','DELIVERY_READY')")
                paid=cur.fetchone()['paid_orders']
                return {'events':counts,'paid_orders':paid}

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
