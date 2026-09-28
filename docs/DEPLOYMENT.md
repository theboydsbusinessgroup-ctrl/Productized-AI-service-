# Payment-first MVP deployment

Production requires the server-only payment variables documented in [PRODUCTION_CHECKOUT_DEPLOYMENT.md](PRODUCTION_CHECKOUT_DEPLOYMENT.md). `DATABASE_URL` must point to the Supabase Supavisor transaction pooler.

## Database source of truth

The verified production order-store shape is tracked in `supabase/schemas/productized_ai.sql`. It defines both required tables, integrity constraints, indexes, RLS, and server-only grants.

For schema changes:

1. edit the declarative schema;
2. generate and review a versioned Supabase migration;
3. test it on an isolated database or branch;
4. run Supabase security and performance advisors;
5. apply it to production only after review.

The production database currently records migration `20260921084423_create_productized_ai_order_store`. Do not re-run the declarative file directly against production or reset a deployed migration.

## Durable order lifecycle

Checkout persists `CHECKOUT_PENDING`; a verified and fully validated Stripe success event moves the same durable row to `PAID`; successful intake generation moves it to `DELIVERY_READY`. No order state depends on Vercel server memory.

The order and funnel tables are server-only. RLS is enabled and browser-facing `anon` and `authenticated` roles receive no table access.
