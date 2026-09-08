# Architecture

## Pipeline
1. Acquire prospect through compliant channels.
2. Present a fixed-scope offer.
3. Accept payment through Stripe Checkout/webhooks.
4. Collect structured intake.
5. Create production job.
6. Generate content from verified customer inputs.
7. Run fact-checking and policy checks.
8. Run quality scoring.
9. Regenerate below threshold.
10. Package and deliver.
11. Request satisfaction signal.
12. Offer recurring refresh.

## AI worker contracts
### Sales
Explains only configured capabilities and pricing. No fabricated claims or unauthorized discounts.

### Intake
Converts customer responses into structured fields and flags missing critical inputs.

### Production
Creates only the contracted deliverables and uses the customer's verified facts as the source of truth.

### Fact checker
Flags unsupported claims, fake statistics, guarantees, fabricated testimonials, and contradictions.

### QA
Scores completeness, originality, readability, brand fit, factual safety, and scope compliance. Below-threshold jobs return to revision.

### Delivery
Produces a predictable package and records delivery status.

### Retention
After completion, presents the configured recurring refresh without deceptive pressure.

## Automation boundary
Financial actions, account permissions, platform policies, and customer-facing claims must remain auditable. Automation must not bypass third-party terms or impersonate a human where prohibited.
