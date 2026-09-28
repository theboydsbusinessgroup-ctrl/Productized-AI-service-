-- Declarative source of truth for the Productized AI Service order store.
-- Generate and review a migration from this file before applying schema changes.

create table public.productized_ai_orders (
  order_id text primary key,
  state text not null
    check (state = any (array['CHECKOUT_PENDING'::text, 'PAID'::text, 'DELIVERY_READY'::text])),
  customer_email text not null,
  amount_usd integer not null check (amount_usd > 0),
  stripe_session_id text unique,
  intake_token text,
  intake jsonb,
  deliverable_text text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  delivered_at timestamptz
);

create table public.productized_ai_funnel_events (
  id bigint generated always as identity primary key,
  event_type text not null,
  order_id text references public.productized_ai_orders (order_id),
  source text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index productized_ai_funnel_events_order_idx
  on public.productized_ai_funnel_events (order_id);

alter table public.productized_ai_orders enable row level security;
alter table public.productized_ai_funnel_events enable row level security;

-- These are server-only tables. The application connects directly to Postgres;
-- browser-facing Supabase roles must not access payment, intake, or funnel data.
revoke all on table public.productized_ai_orders from anon, authenticated;
revoke all on table public.productized_ai_funnel_events from anon, authenticated;
revoke all on sequence public.productized_ai_funnel_events_id_seq from anon, authenticated;

grant select, insert, update, delete on table public.productized_ai_orders to service_role;
grant select, insert, update, delete on table public.productized_ai_funnel_events to service_role;
grant usage, select on sequence public.productized_ai_funnel_events_id_seq to service_role;
