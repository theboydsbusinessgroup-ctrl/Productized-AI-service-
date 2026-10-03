# Revenue automation operations

The October 3 implementation retains the existing Vercel/Supabase deployment. No new paid infrastructure is required.

## Durable fulfillment

Authenticated intake creates one durable job per paid order. First accepted intake wins. The HTTP request attempts fulfillment immediately. A daily Vercel cron at 06:00 UTC recovers pending work and expired two-minute leases. Each claim has a random fencing token; an old worker cannot overwrite a new worker's delivery. Order delivery, job completion, and delivery-event insertion commit together. Transient database faults back off; five attempts or nonretryable errors enter FAILED for review. Browser responses of 202 mean intake is stored, not delivered.

The daily cadence fits the free scheduling constraint. Increase recovery frequency only if the account's existing plan permits it, or reuse an authenticated scheduler. No plan upgrade was requested.

## Payment and financial evidence

Verified, amount/link-bound Stripe checkout webhooks store event/session IDs, actual livemode, amount and currency in the same transaction as the paid transition. Session deduplication prevents double counting. Only true livemode receipts enter live capture totals; string prefixes alone do not establish mode. Receipt coverage begins October 3 and does not establish lifetime revenue.

`GET /internal/revenue` uses the dedicated REVENUE_READ_TOKEN and returns sanitized aggregates. Jarvis reads it only through its authenticated owner revenue route. Neither Jarvis nor the public dashboard gets customer email, intake, deliverables, database credentials, or Stripe credentials.

Daily read-only balance reconciliation requires STRIPE_SECRET_KEY with live balance-read permission. That credential is not currently configured. The worker reports not_configured rather than inventing settlement, refund, fee, or contribution numbers. Reconciliation paginates up to 1,000 transactions from September 1, fails closed on partial/mixed-currency results, and preserves the previous snapshot on failure. Account balance movements are distinct from bank payout confirmation and product-specific revenue.

Model/provider/acquisition costs must be reconciled before contribution is reported. No payments, refunds, payouts or transfers are initiated by this worker.

## Quality and product expectations

Generation remains free deterministic drafting. Every service is rotated into posts, supported tone changes affect bodies, no-hashtag/no-discount constraints apply, and calendar entries point to specific content. The website describes structured drafts and the limits of free-form instruction handling. No external website research is claimed. Three representative sample packs are in docs/samples. Customer review remains necessary for claims, availability, pricing, and free-form instructions before publication.

## Configuration and recovery

Production needs DATABASE_URL, Stripe payment-link/webhook configuration, REVENUE_READ_TOKEN and CRON_SECRET. The latter two are distinct newly generated secrets. `/internal/automation` requires the exact cron bearer token. Existing orders are preserved by the additive migration; server-only operations tables have RLS and no browser-role grants.

Review FAILED jobs in private database operations. Correct their cause before explicitly requeueing; do not blindly replay financial provider mutations. Monitoring and automated retry behavior cannot create provider approvals, OAuth identity, or customer demand.
