import os

import stripe
from fastapi import HTTPException


def construct_verified_event(payload: bytes, signature: str | None):
    """Return a Stripe event only after cryptographic signature verification."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "Stripe webhook verification is not configured")
    if not signature:
        raise HTTPException(400, "Missing Stripe-Signature header")

    try:
        return stripe.Webhook.construct_event(payload, signature, secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(400, "Invalid Stripe webhook signature")
