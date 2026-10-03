# Fulfillment reliability

An authenticated retry of completed intake returns the existing download URL.
The database updates only PAID orders; concurrent submissions return the same
original completed pack instead of overwriting customer content. Only the winning
transition emits a delivery-ready event. Lost HTTP responses can therefore be
retried safely.

Handoff, success, checkout, order and internal-funnel responses use `no-store` and
`no-referrer`. Download filenames use an ASCII fallback for non-Latin business
names. Database readiness checks require the actual order and event columns.

Funnel results retain `paid_orders` for compatibility and add `live_paid_orders`,
`test_paid_orders` and `unknown_mode_paid_orders`. Existing aggregate event counts
include tests. Order counts do not establish settled revenue or profit; reconcile
Stripe refunds, fees and settlement separately.

Regression tests include concurrent fulfillment against PostgreSQL. Set
`PRODUCTIZED_TEST_DATABASE_URL` to a disposable database whose name ends in
`_test`; the fixture truncates its two test tables and refuses other names.
CI provisions its own disposable PostgreSQL service. Production schema is unchanged.
