# Production Checkout Deployment Checklist

Use this checklist before merging or promoting payment-path changes.

## 1. Configure Vercel production variables

Add the following server-only variables in the Vercel project. Never prefix them with `NEXT_PUBLIC_` and never commit their values.

- `DATABASE_URL` — production PostgreSQL connection string.
- `STRIPE_PAYMENT_LINK_URL` — live Stripe Payment Link used by `POST /checkout`.
- `STRIPE_WEBHOOK_SECRET` — the `whsec_...` signing secret for the exact Stripe webhook endpoint below.
- `STRIPE_WEBHOOK_TOKEN` — optional random token used by `GET /internal/funnel`.
- `STRIPE_WEBHOOK_TOKEN_ENFORCED` — keep `false` unless Stripe is configured to include the query token in the endpoint URL.

Scope required payment variables to **Production**. Add them to Preview only when using Stripe test-mode resources and an isolated preview database.

## 2. Configure the Stripe endpoint

Create or update the Stripe webhook endpoint to target:

```text
https://<production-domain>/webhooks/stripe
```

Subscribe to:

```text
checkout.session.completed
```

Copy that endpoint's signing secret into Vercel as `STRIPE_WEBHOOK_SECRET`. Do not use a secret from a different endpoint or environment.

## 3. Redeploy after variable changes

Vercel environment-variable changes do not alter an already-built deployment. Redeploy the intended production revision after saving the variables.

## 4. Pre-merge verification

- CI must pass on the exact PR head.
- `GET /health` returns HTTP 200 and reports `payment_gate: true`.
- An unsigned `POST /webhooks/stripe` request is rejected with HTTP 400.
- A malformed `Stripe-Signature` is rejected with HTTP 400.
- If `STRIPE_WEBHOOK_SECRET` is absent, the route fails closed with HTTP 503.
- `POST /checkout` creates a tracked order before returning the Stripe URL.
- Production and test-mode Stripe resources are not mixed.

## 5. Controlled live verification

After merge and production deployment, complete one controlled purchase:

1. Confirm Stripe shows `checkout.session.completed` delivered successfully.
2. Confirm the order transitions from `CHECKOUT_PENDING` to `PAID`.
3. Confirm `/success?session_id=...` unlocks the intake form.
4. Submit intake and download the generated deliverable.
5. Confirm no secret, intake token, or database credential appears in browser-visible output or logs.

Do not begin customer acquisition until this flow succeeds end to end.
