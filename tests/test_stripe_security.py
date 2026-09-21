import json
import time

import pytest
import stripe
from fastapi import HTTPException

from app.stripe_security import construct_verified_event


def _signed(payload: bytes, secret: str) -> str:
    timestamp = int(time.time())
    signed_payload = f"{timestamp}." + payload.decode("utf-8")
    signature = stripe.WebhookSignature._compute_signature(signed_payload, secret)
    return f"t={timestamp},v1={signature}"


def test_accepts_valid_signature(monkeypatch):
    secret = "whsec_test_secret"
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)
    payload = json.dumps({"id": "evt_1", "type": "checkout.session.completed"}).encode()
    event = construct_verified_event(payload, _signed(payload, secret))
    assert event["type"] == "checkout.session.completed"


def test_rejects_missing_signature(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    with pytest.raises(HTTPException) as exc:
        construct_verified_event(b"{}", None)
    assert exc.value.status_code == 400


def test_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    with pytest.raises(HTTPException) as exc:
        construct_verified_event(b"{}", "t=1,v1=bad")
    assert exc.value.status_code == 400


def test_fails_closed_without_webhook_secret(monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc:
        construct_verified_event(b"{}", "t=1,v1=anything")
    assert exc.value.status_code == 503
