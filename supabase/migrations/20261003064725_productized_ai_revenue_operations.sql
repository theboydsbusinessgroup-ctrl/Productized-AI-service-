-- Additive server-only operations state. No existing orders are rewritten.
create table public.productized_ai_payment_receipts (
  event_id text primary key,
  order_id text not null references public.productized_ai_orders(order_id),
  session_id text not null,
  livemode boolean,
  amount_cents integer not null check (amount_cents >= 0),
  currency text not null,
  received_at timestamptz not null default now()
);
create index productized_ai_receipts_session_idx on public.productized_ai_payment_receipts(session_id);

create table public.productized_ai_fulfillment_jobs (
  order_id text primary key references public.productized_ai_orders(order_id),
  intake jsonb not null,
  state text not null default 'PENDING' check(state in ('PENDING','RUNNING','DONE','FAILED')),
  attempts integer not null default 0 check(attempts between 0 and 5),
  lease_token text,
  lease_until timestamptz,
  available_at timestamptz not null default now(),
  error_code text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);
create index productized_ai_jobs_pending_idx on public.productized_ai_fulfillment_jobs(available_at)
  where state in ('PENDING','RUNNING');

create table public.productized_ai_reconciliations (
  provider text primary key,
  observed_at timestamptz not null,
  summary jsonb not null
);

alter table public.productized_ai_payment_receipts enable row level security;
alter table public.productized_ai_fulfillment_jobs enable row level security;
alter table public.productized_ai_reconciliations enable row level security;
revoke all on public.productized_ai_payment_receipts, public.productized_ai_fulfillment_jobs,
  public.productized_ai_reconciliations from anon, authenticated;
grant select, insert, update, delete on public.productized_ai_payment_receipts,
  public.productized_ai_fulfillment_jobs, public.productized_ai_reconciliations to service_role;
