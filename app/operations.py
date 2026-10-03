import psycopg
from app.generator import build_content_pack


def process_fulfillment(store, order_id=None):
    job=store.claim_fulfillment(order_id)
    if not job:return False
    try:
        text=build_content_pack(job['intake'],job['order_id'])
        if not text or 'Day 30:' not in text:raise ValueError('incomplete_content')
        return store.complete_fulfillment(job,text)
    except Exception as exc:
        store.fail_fulfillment(job,isinstance(exc,psycopg.OperationalError))
        return False
