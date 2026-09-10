# Payment-first MVP deployment

## Required environment variables

- `STRIPE_PAYMENT_LINK_URL`: Stripe Payment Link for the $49 30-Day Social Content Pack.
- `STRIPE_WEBHOOK_SHARED_SECRET`: optional temporary shared secret for webhook hardening during MVP wiring.

## Revenue flow

1. Client requests `/checkout` with an email address.
2. Engine creates an internal order in `CHECKOUT_PENDING` and returns the Stripe checkout URL with `client_reference_id`.
3. Stripe completion webhook moves the order to `PAID` and creates a one-time intake token.
4. Paid customer submits `/orders/{order_id}/intake` with that token.
5. Order moves to `INTAKE`, ready for the production worker.

## Next production hardening

The in-memory order store is intentionally temporary. Before public deployment, replace it with Supabase/Postgres and replace the shared-secret webhook check with Stripe signature verification. Production should also send the intake link automatically after payment and enqueue content generation only after the PAID transition.
