# Payment-first MVP deployment

Production requires `STRIPE_PAYMENT_LINK_URL` and a sensitive `DATABASE_URL` pointing at the Supabase Supavisor transaction pooler.

Order lifecycle: checkout persists `CHECKOUT_PENDING`; Stripe completion moves the same durable row to `PAID`; paid intake moves it to `INTAKE`. No order state depends on Vercel server memory.
