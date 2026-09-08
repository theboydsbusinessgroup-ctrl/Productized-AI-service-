# Productized AI Service Engine

Automated system for selling fixed-scope, AI-produced digital services with payment-first fulfillment.

## Initial offer
**30-Day Social Content Pack — $49 one-time**

Deliverables:
- 10 social posts
- 10 captions
- 10 hooks
- 5 promotional ideas
- 5 Google Business Profile posts
- 30-day content calendar

Optional recurring refresh: **$29/month**.

## Core flow
Prospect → Offer → Checkout → Intake → Production → Fact Check → QA → Delivery → Follow-up → Recurring offer.

## Design principles
- Payment before production.
- Fixed scope and predictable delivery.
- No invented facts, guarantees, testimonials, or business claims.
- Automatic regeneration when QA fails.
- Human intervention only for exceptions.
- Mobile-friendly operations and clear audit trails.
- Keep acquisition compliant; no spam, fake accounts, fake reviews, or prohibited platform automation.

## State machine
`NEW → PAID → INTAKE → PRODUCTION → QA → REVISION → DELIVERY → COMPLETE → FOLLOW_UP → RECURRING`

## MVP
The first implementation is intentionally small: health endpoint, offer configuration, intake/order models, production pipeline interfaces, deterministic QA gates, and a clean path to Stripe/webhook integration.
