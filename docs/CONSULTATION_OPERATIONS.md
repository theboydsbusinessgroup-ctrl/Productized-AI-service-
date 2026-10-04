# Consultation operations

This guide describes the 13 implemented endpoints in `app/consultations.py` and their private state in `app/consultation_store.py`. It does not assert that the production configuration, callbacks or customer flow are activated. Verify those separately before publishing the offer.

The offer is a separate $19 USD, 20-minute virtual session for verified purchasers of the $9 One Bottle at a Time ebook. BARBUYER identifies the offer; it is neither purchase proof nor a discount coupon. Payment precedes consultation setup. Eric manually approves the exact appointment time. A paid receipt does not reserve a time or confirm a booking.

## Configuration and credentials

Set these values in protected server configuration. Never put their values, customer records, receipt payloads or meeting links in GitHub.

| Environment variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Server connection to the private consultation tables. |
| `CONSULTATION_GUMROAD_PRODUCT_ID` | Exact qualifying Gumroad ebook product ID. |
| `CONSULTATION_GUMROAD_WEBHOOK_TOKEN` | Shared secret protecting registered Gumroad callback URLs/header requests; Ping itself remains unsigned. |
| `CONSULTATION_GUMROAD_ACCESS_TOKEN` | Private Gumroad seller API token with `view_sales` permission, used as a Bearer credential for notification readback. Required before activating checkout. |
| `CONSULTATION_PAYMENT_LINK_URL` | Hosted Stripe Payment Link; must use HTTPS on `buy.stripe.com` and contain no fragment. |
| `CONSULTATION_PAYMENT_LINK_ID` | Exact Stripe Payment Link ID accepted by the consultation webhook. |
| `CONSULTATION_STRIPE_WEBHOOK_SECRET` | Signing secret for the consultation Stripe endpoint. This is distinct from the existing content-service webhook configuration. |
| `CONSULTATION_ADMIN_TOKEN` | Dedicated operator credential for consultation queue, trusted imports, slot approval and calendar confirmation. |
| `CONSULTATION_GOOGLE_CALENDAR_ID` | Exact host calendar ID accepted when the operator records a verified calendar event. |

Use `x-consultation-admin-token: <private CONSULTATION_ADMIN_TOKEN>` for every `/consultations/internal/...` route. It is not `INTERNAL_API_TOKEN`, `REVENUE_READ_TOKEN` or a buyer token. A buyer uses `x-consultation-token` only when posting their time proposals. Tokens must never appear in public copy or customer screenshots.

Eric's default business calendar timezone is **America/Chicago**. The backend accepts each buyer's explicit IANA timezone rather than reading a default timezone environment variable. Send offset-bearing timestamps that match that named timezone; the backend normalizes them to UTC. Every slot must start in the future and last exactly 20 minutes. Dates near daylight-saving changes require particular care.

## Implemented routes

All routes are relative to `https://productized-ai-service.vercel.app`.

| Method and route | Authentication and behavior |
| --- | --- |
| `GET /consultations` | Public landing form; collects purchase email, ebook sale/order ID or unambiguous receipt order number, and accepted terms. |
| `GET /consultations/health` | Public configuration booleans and storage check. `payment_gate` requires a reachable database and configured payment-link URL/ID, Stripe webhook secret, qualifying product ID, Gumroad webhook token, Gumroad API access token and admin token. `manual_calendar_confirmation_configured` separately reports whether the host calendar ID is configured; it is outside the payment gate. These presence/readiness checks do **not** prove valid provider registrations, delivered Gumroad notifications, secret validity, an actual calendar result or a complete buyer transaction. `automatic_calendar_booking` remains false. |
| `POST /consultations/checkout` | JSON: `customer_email`, `ebook_order_id`, `code` (`BARBUYER`), and boolean `terms_accepted`. The `ebook_order_id` field accepts the trusted sale/order ID or an unambiguous imported receipt order number. Requires an already trusted eligible ebook sale and all eight payment-gate settings, including admin, Gumroad webhook and Gumroad API access tokens. Returns request ID/state and the hosted checkout URL with `client_reference_id` and prefilled email. It does not charge a card. |
| `POST /consultations/webhooks/stripe` | Stripe's `Stripe-Signature` header and configured signing secret. Accepts the implemented live payment/refund/dispute events described below. |
| `GET /consultations/success?session_id=<private-session-id>` | Buyer return page. Polls handoff and enables time proposals only after matched payment evidence. |
| `GET /consultations/handoff?session_id=<private-session-id>` | Treat the session ID as a private capability. Returns a buyer intake token only for eligible, valid paid states. Unknown sessions are `PROCESSING`; unresolved payment/eligibility is not ready. BOOKED/COMPLETED do not reopen proposals. |
| `POST /consultations/{request_id}/times` | `x-consultation-token` header. JSON `slots` contains 1–10 objects with `start_datetime`, `end_datetime`, `timezone`. Replaces proposals, increments the revision and invalidates previous approval. Returns `booking_confirmed: false`. |
| `GET /consultations/internal/gumroad-status` | Admin header. Verifies real seller API authentication through the first `/v2/sales` page filtered by the configured product, using the protected Bearer token, a three-second deadline and no redirects. Returns only `authenticated`, `product_scoped` and `successful_sale_count`; no buyer data or credential. The count covers this first page only, not lifetime sales. Missing configuration, failed upstream authentication, malformed data or cross-product results return 503; unauthorized operators receive 401. |
| `GET /consultations/internal/requests` | Admin header. Returns `requests` and `unresolved_payments`, each capped at 100, ordered oldest first. These contain private customer/payment information. |
| `POST /consultations/internal/{request_id}/approve` | Admin header. Fields: current `revision`, exact proposed slot fields, `calendar_available: true`, and offset-bearing `calendar_checked_at`. The successful conflict check must be no more than five minutes old. The approved slot must exactly match a current proposal. Returns `booking_confirmed: false`. |
| `POST /consultations/internal/{request_id}/calendar-confirmation` | Admin header. Fields: current `revision`, exact approved slot fields, `calendar_event_id`, configured `calendar_id`, and `provider_result_verified: true`. Records the authenticated operator's verified provider result; it does not retrieve or create the event. Returns BOOKED only when stored approval, payment, purchase and identifiers satisfy the gates. |
| `POST /consultations/internal/sales/import` | Admin header. Trusted provider backfill only: `sale_id`, optional `order_number`, `product_id`, `purchase_email`, and strict booleans `payment_succeeded`, `refunded`, `disputed`. Never accept buyer assertions as trusted import evidence. |
| `POST /consultations/webhooks/gumroad/{resource}` | Secret-protected form trigger for `sale`, `refund` or `dispute`. Reads the sale and scoped successful-sales list through the authenticated Gumroad API before importing evidence; see below. |

There is no implemented API route to send a consultation confirmation email, issue a refund, mark a session COMPLETED, cancel a calendar event or autonomously approve a time. Do not invent a route or silently update database states to imply these actions happened.

## Trusted ebook-sale ingestion

Register Gumroad's supported sale/refund/dispute notifications to the corresponding resource routes. Registration is an external setup step; routes and configuration alone do not prove that callbacks or API reads are active. [Gumroad's Ping documentation](https://gumroad.com/ping) states that the payload is unsigned and should trigger an API sale readback rather than establish payment facts by itself.

Protect each privately registered HTTPS callback URL with `?token=<CONSULTATION_GUMROAD_WEBHOOK_TOKEN>`, or use `x-gumroad-webhook-token` where the sender can set headers. Never expose the secret-bearing URL in public copy, GitHub, screenshots or ordinary logs. This secret controls access to the callback; it does not make the Ping a signed financial record. The separate `CONSULTATION_GUMROAD_ACCESS_TOKEN` uses `Authorization: Bearer ...` for server-to-server API reads; it never enters a query string, redirect, public error or buyer response.

The accepted trigger content type is `application/x-www-form-urlencoded`. Required lookup identity fields are `sale_id`, `product_id` and `email`; `order_number` is optional. The authenticated resource path selects `sale`, `refund` or `dispute`; a supplied `resource_name` must match. Repeated fields, unsupported resource types, more than 100 form fields and bodies above 65,536 bytes fail closed. Nonqualifying product triggers are ignored. Payment/refund flags submitted in the unsigned form are not trusted evidence.

For a qualifying trigger, the backend reads `GET https://api.gumroad.com/v2/sales/{sale_id}` with the seller Bearer token, then `GET https://api.gumroad.com/v2/sales` scoped by product, purchase email and numeric `order_id`. Both reads share an overall three-second deadline and do not follow redirects. It verifies sale/product/email identity, the numeric provider order ID, and any supplied receipt order number. The API `order_id` is stored as `order_number`; buyers can use that number or the trusted sale ID in the checkout form.

Paid eligibility requires the same sale ID in the provider's successful-sales list, API `paid` exactly true, a positive integer price, and no test/preorder authorization. API refund/dispute fields must be real JSON booleans. Refund or partial-refund evidence revokes ebook eligibility; dispute or chargeback evidence also revokes it. A refund/dispute trigger without matching API revocation evidence returns 503 rather than inventing that evidence. Failed/unknown sale status also remains ineligible. API lookup errors return 503; invalid or conflicting provider identity returns 422. Only verified API evidence is persisted with source `verified_gumroad_api_readback`, using a one-second database synchronization wait. The route does not grant a purchase from buyer input or Ping flags.

Official Ping delivery is at least once and unordered; a refund can arrive before its sale. Acknowledge responses must arrive within five seconds. Gumroad documents retries after one minute, three minutes, ten minutes and one hour only for 499, 500, 502, 503 and 504; connection errors, timeouts and other non-2xx statuses do not receive that retry schedule. The implementation's bounded API/database work is not a guarantee of delivery. Reconcile provider records periodically because notifications can be lost after retries stop. Repeated imports preserve purchase identity and refund/dispute revocation is monotonic; a delayed sale trigger cannot restore a revoked purchase.

For historical purchases or missed notifications, read the real sale and successful-sale evidence through connected Gumroad seller tools and privately submit the exact observed fields to `/consultations/internal/sales/import`. This trusted operator backfill is distinct from automated notification readback. Record provider evidence privately and never import guesses or test fixtures into production. Checkout checks already synchronized trusted records; it does not fetch arbitrary buyer-entered sales directly. A missing sale, conflicting identity, failed purchase, refund or dispute leaves checkout ineligible. One stored consultation request is allowed per sale; an unpaid CHECKOUT_PENDING request is reused safely.

Keep activation pending until the protected production API credential is configured and real provider readback, ingestion and buyer flow are verified. This guide describes built behavior, not an assertion that those external calls are deployed or active.

## Payment evidence and exceptions

Configure the consultation Stripe endpoint for `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `charge.refunded` and `charge.dispute.created`. The payment path requires a verified webhook signature, real live event, expected Payment Link, `payment_status: paid`, one-time `mode: payment`, exactly 1900 cents, USD, a payment intent, a known request reference and matching purchase/payment email. The hosted email can be edited, so a mismatch becomes an operator resolution item rather than a granted session.

The backend trusts the authenticated Stripe event payload; it does not make an additional Stripe API retrieval during webhook processing. Event IDs are deduplicated and a second distinct payment cannot grant another entitlement. Wrong amount/currency/mode payments are REJECTED; unmatched reference/email, revoked eligibility or extra payments are UNMATCHED with a reason. These may still represent money actually collected by Stripe and must be investigated. Never treat rejection as proof that no charge occurred.

Publish the consultation landing URL, not the raw Payment Link. A raw link can be paid without a validated request/reference. The backend records those payments for resolution; it cannot prevent the hosted link from collecting them or refund them automatically. Provider verification and prompt operator handling remain necessary.

A matched payment grants PAID_AWAITING_SCHEDULING. The buyer's private return page obtains the intake token and submits proposed times. Signed refund/dispute events revoke payment entitlement and invalidate slot approval; Gumroad eligibility revocation leaves an already-paid session awaiting resolution. Existing external calendar events are not automatically cancelled by either path. Review the actual provider state before further service or confirmation.

## Daily owner check and appointment handling

After configuring or rotating the protected Gumroad access token, call `GET /consultations/internal/gumroad-status` with `x-consultation-admin-token` to verify real upstream authentication without extracting or displaying the token. A successful empty product-filtered response can verify authentication with `successful_sale_count: 0`; this is not a lifetime zero-sales claim or proof of a buyer transaction. Missing/invalid credentials keep this check unavailable and checkout activation pending.

Check the protected queue **daily**, using connected tools that support authenticated HTTPS and the actual connected calendar/provider records. Keep token values and queue contents in private tool context; do not post them to a public operating board. No owner notification, email alert or daily queue reader is implemented by this backend, so the operator must initiate this check or explicitly build an additional automation.

1. Fetch `GET /consultations/internal/requests` with the admin header. Review unresolved payment receipts first, then paid scheduling requests. Each list stops at 100 and has no pagination; reaching that limit requires a protected operational database review or a future paginated endpoint so later records are not overlooked.
2. Review PAID_AWAITING_SCHEDULING buyers who have not proposed a time and TIMES_PROPOSED buyers waiting for Eric. Obtain Eric's explicit exact-time decision. The shared admin credential authorizes a tool; it is not proof that Eric approved a slot unless the operator has his actual instruction. Preserve that instruction privately.
3. For a current proposal, check the connected host calendar for overlap, including adjacent commitments, in America/Chicago and the buyer's stated timezone. If results are missing, stale or fail, do not assert availability. A clear calendar alone never authorizes the slot.
4. With Eric's actual approval and a successful conflict check performed within five minutes, post the exact current proposal and revision to the approval route. The returned state is APPROVED_AWAITING_CALENDAR, not BOOKED. If the buyer changes proposals, fetch the current revision and seek fresh approval.
5. Recheck the calendar immediately before appointment creation. Through the connected calendar tools, create the actual approved event in the configured host calendar, using the exact start/end, buyer details and privately arranged meeting information. Verify the provider's returned/read-back event, including calendar, time and attendees. Do not infer success from a local draft or failed tool call.
6. Only then post the verified event ID, configured calendar ID, exact approved slot and current revision to `/calendar-confirmation`. Set `provider_result_verified` only after actual provider verification. The backend records this authenticated operator assertion; it has no bound Google OAuth client and does not independently fetch the event.
7. Privately provide the confirmed meeting details using the approved customer channel or calendar invitation. This backend does not send that message. Stripe may send a payment receipt when configured on the Stripe account, but it is not a session confirmation. Record actual delivery privately rather than claiming an email was sent automatically.
8. Deliver the session and retain private fulfillment evidence. BOOKED remains in the queue because no completion endpoint exists. Do not assume COMPLETED merely because time passed; track completion privately and add a tested authenticated completion action before automating that state.

Implemented scheduling sequence: CHECKOUT_PENDING → PAID_AWAITING_SCHEDULING → TIMES_PROPOSED → APPROVED_AWAITING_CALENDAR → BOOKED. Failed eligibility/payment gates or post-payment availability problems require operator resolution. New proposals invalidate exact-slot approval and preserve the existing payment; they do not create a second session charge.

## Paid obligations, refunds and disputes

A paid buyer is owed the session. If Eric cannot provide it, the buyer chooses an approved replacement time or a **full $19 session-fee refund**. Do not force a replacement or retain funds against indefinite future availability. Replacement requires fresh exact-slot approval; rescheduling does not require another session charge. The ebook and consultation are separate purchases.

Investigate UNMATCHED/REJECTED receipts and any paid purchase-revocation case promptly. Verify the actual Stripe payment, ownership and full amount before arranging fulfillment or the appropriate full refund. Issuing a refund requires an authorized provider action outside this backend. Do not report a refund as completed until Stripe confirms success; maintain unresolved cases privately until resolved.

A signed live `charge.refunded` event closes the request as REFUNDED only when `amount_refunded` is an integer exactly **1900** and `currency` is **USD** (case-insensitive). Partial refunds, missing/invalid amounts or missing/wrong currency revoke payment entitlement but remain **PAID_AWAITING_RESOLUTION** in the owner queue. Verify the actual cumulative refund and resolve any remaining $19 obligation through Stripe. Once full-refund evidence is recorded for the payment intent, delayed partial/unknown refund events preserve REFUNDED. Payment and revocation handlers serialize on that same payment intent, so a racing late payment event cannot restore revoked entitlement. DISPUTED also invalidates further confirmation; handle evidence and the actual dispute through Stripe. The backend does not reopen eligibility when a dispute is later won, so resolve that case explicitly rather than assuming a reversal event restores service.

No routine customer messages, calendar writes, charges or refunds are executed by this guide. Use the connected tools for concrete authorized actions and verify their results. Preserve personal/payment data in protected operational storage, never in GitHub. The service is for adults of legal drinking age; alcohol consumption is unnecessary.
