"""Read-only Stripe balance reconciliation. Never charges, refunds, or transfers."""
import os
from datetime import datetime, timezone
import stripe
from psycopg.types.json import Jsonb


def reconcile_stripe(store):
    key=os.getenv('STRIPE_SECRET_KEY','')
    if not key.startswith(('rk_live_','sk_live_')):
        return {'status':'not_configured','required':'STRIPE_SECRET_KEY (live read-only balance permission)'}
    client=stripe.StripeClient(key,max_network_retries=1,http_client=stripe.RequestsClient(timeout=5))
    totals={'captured_cents':0,'refund_cents':0,'fees_cents':0,'available_net_cents':0,'pending_net_cents':0}
    cursor=None
    for _ in range(10):
        params={'limit':100,'created':{'gte':int(datetime(2026,9,1,tzinfo=timezone.utc).timestamp())}}
        if cursor:params['starting_after']=cursor
        page=client.v1.balance_transactions.list(params)
        for row in page.data:
            if row.currency!='usd':raise RuntimeError('multiple_currencies_require_separate_ledgers')
            if row.type in ('charge','payment'):
                totals['captured_cents']+=row.amount
                totals['fees_cents']+=row.fee
                totals['available_net_cents' if row.status=='available' else 'pending_net_cents']+=row.net
            elif row.type in ('refund','payment_refund'):
                totals['refund_cents']-=row.amount
                totals['fees_cents']+=row.fee
                totals['available_net_cents' if row.status=='available' else 'pending_net_cents']+=row.net
        if not page.has_more:break
        if not page.data:raise RuntimeError('invalid_provider_pagination')
        cursor=page.data[-1].id
    else:raise RuntimeError('reconciliation_page_limit_exceeded')
    summary={'status':'reconciled','scope':'connected_stripe_account','currency':'usd',
        'period_start':'2026-09-01T00:00:00Z',**totals,'contribution_cents':None,
        'note':'Balance movements are not bank payout confirmation. Model/provider/acquisition costs are not fully reconciled.'}
    with store._connect() as conn:
        conn.execute('''insert into public.productized_ai_reconciliations(provider,observed_at,summary)
            values ('stripe',now(),%s) on conflict(provider) do update set observed_at=excluded.observed_at,summary=excluded.summary''',(Jsonb(summary),))
    return summary
