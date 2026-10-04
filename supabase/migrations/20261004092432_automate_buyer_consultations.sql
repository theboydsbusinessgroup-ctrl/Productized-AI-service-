-- Server-only Behind The Bar consultation state; independent of AI orders.
create table public.boyds_consultation_sales (
  sale_id text primary key,
  order_number text unique,
  product_id text not null,
  purchase_email text not null,
  payment_succeeded boolean not null,
  refunded boolean not null default false,
  disputed boolean not null default false,
  source text not null,
  observed_at timestamptz not null default now()
);

create table public.boyds_consultations (
  request_id text primary key,
  sale_id text not null unique references public.boyds_consultation_sales(sale_id),
  customer_email text not null,
  state text not null check (state in ('CHECKOUT_PENDING','PAID_AWAITING_SCHEDULING',
    'TIMES_PROPOSED','APPROVED_AWAITING_CALENDAR','PAID_AWAITING_RESOLUTION',
    'REFUNDED','DISPUTED','BOOKED','COMPLETED')),
  stripe_session_id text unique,
  payment_intent_id text unique,
  intake_token text,
  paid_at timestamptz,
  payment_valid boolean not null default false,
  revision integer not null default 0,
  proposed_slots jsonb not null default '[]'::jsonb,
  approved_slot jsonb,
  approved_by text,
  approved_at timestamptz,
  calendar_check_at timestamptz,
  calendar_event_id text unique,
  calendar_id text,
  calendar_verified_at timestamptz,
  calendar_verification_source text,
  terms_version text not null default 'payment-first-v1',
  terms_accepted_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.boyds_consultation_payment_receipts (
  event_id text primary key,
  session_id text,
  payment_intent_id text,
  request_id text references public.boyds_consultations(request_id),
  claimed_reference text,
  customer_email text,
  amount_cents integer,
  currency text,
  livemode boolean,
  event_type text not null,
  resolution_state text not null check (resolution_state in ('MATCHED','UNMATCHED','REJECTED','REVOKED')),
  reason text,
  received_at timestamptz not null default now()
);
create index boyds_consultation_receipts_session_idx on public.boyds_consultation_payment_receipts(session_id);
create index boyds_consultation_receipts_intent_idx on public.boyds_consultation_payment_receipts(payment_intent_id);
create index boyds_consultation_receipts_request_idx on public.boyds_consultation_payment_receipts(request_id);

alter table public.boyds_consultation_sales enable row level security;
alter table public.boyds_consultations enable row level security;
alter table public.boyds_consultation_payment_receipts enable row level security;
revoke all on public.boyds_consultation_sales, public.boyds_consultations,
  public.boyds_consultation_payment_receipts from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname='anon') then
    revoke all on public.boyds_consultation_sales, public.boyds_consultations,
      public.boyds_consultation_payment_receipts from anon;
  end if;
  if exists (select 1 from pg_roles where rolname='authenticated') then
    revoke all on public.boyds_consultation_sales, public.boyds_consultations,
      public.boyds_consultation_payment_receipts from authenticated;
  end if;
  if exists (select 1 from pg_roles where rolname='service_role') then
    grant select, insert, update, delete on public.boyds_consultation_sales,
      public.boyds_consultations, public.boyds_consultation_payment_receipts to service_role;
  end if;
end $$;
