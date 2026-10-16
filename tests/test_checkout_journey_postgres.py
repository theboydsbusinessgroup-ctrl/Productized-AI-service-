"""Real PostgreSQL HTTP journey with a locally signed webhook simulation.

This regression does not make a Stripe purchase or call Stripe's API. It exercises
the application's signature verification, durable order store, and fulfillment
routes using a synthetic test-mode event.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import psycopg
from psycopg.conninfo import conninfo_to_dict
import pytest

from app.main import app
import app.store as store_module
from app.store import PostgresOrderStore, get_store


@pytest.fixture
def checkout_store(monkeypatch):
    """Prepare only the explicitly configured disposable PostgreSQL database."""
    database_url = os.getenv("PRODUCTIZED_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Disposable PostgreSQL test database not configured")
    if not conninfo_to_dict(database_url).get("dbname", "").endswith("_test"):
        pytest.fail("Refusing to modify a database without a _test name")

    # Match the existing PostgreSQL fixture, including its guarded table cleanup.
    with psycopg.connect(database_url) as connection:
        connection.execute("""create table if not exists public.productized_ai_orders (
            order_id text primary key, state text not null, customer_email text not null,
            amount_usd integer not null, stripe_session_id text unique, intake_token text,
            intake jsonb, deliverable_text text, delivered_at timestamptz,
            updated_at timestamptz not null default now())""")
        connection.execute("""create table if not exists public.productized_ai_funnel_events (
            event_type text, order_id text, source text, metadata jsonb)""")
        for role in ("anon", "authenticated", "service_role"):
            if not connection.execute(
                "select 1 from pg_roles where rolname=%s", (role,)
            ).fetchone():
                connection.execute(
                    psycopg.sql.SQL("create role {}").format(psycopg.sql.Identifier(role))
                )
        schema = (
            Path(__file__).parents[1] / "supabase/schemas/revenue_operations.sql"
        ).read_text()
        schema = schema.replace(
            "create table public.", "create table if not exists public."
        ).replace("create index productized", "create index if not exists productized")
        connection.execute(schema)
        connection.execute("""truncate public.productized_ai_orders,
            public.productized_ai_funnel_events, public.productized_ai_payment_receipts,
            public.productized_ai_fulfillment_jobs, public.productized_ai_reconciliations""")

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STRIPE_PAYMENT_LINK_URL", "https://buy.stripe.com/test_journey")
    monkeypatch.setenv("STRIPE_PAYMENT_LINK_ID", "plink_test_journey")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_local_journey_simulation")
    # Clear another test's cached store; get_store constructs the real implementation.
    monkeypatch.setattr(store_module, "_store", None)
    store = get_store()
    assert isinstance(store, PostgresOrderStore)
    return store


def simulated_signed_webhook(event):
    """Sign synthetic bytes locally; this is not evidence of Stripe delivery."""
    payload = json.dumps(event, separators=(",", ":")).encode()
    timestamp = int(time.time())
    signed_payload = str(timestamp).encode() + b"." + payload
    signature = hmac.new(
        os.environ["STRIPE_WEBHOOK_SECRET"].encode(), signed_payload, hashlib.sha256
    ).hexdigest()
    return payload, {
        "Stripe-Signature": f"t={timestamp},v1={signature}",
        "Content-Type": "application/json",
    }


def test_checkout_to_download_with_postgres_and_simulated_signed_webhook(checkout_store):
    store = checkout_store
    intake = {
        "business_name": "Cedar Journey Verification",
        "industry": "Home Services",
        "website": "https://example.com/journey-verification",
        "target_customer": "local homeowners",
        "tone": "friendly",
        "services": ["Window cleaning", "Gutter cleaning", "Pressure washing"],
        "promotions": ["Spring window package", "Annual maintenance plan"],
        "location": "Houston",
        "platforms": ["Instagram", "Facebook"],
        "instructions": "No hashtags.",
    }
    session_id = "cs_test_postgres_journey"
    event_id = "evt_test_postgres_journey"

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["payment_gate"] is True
        assert health.json()["database_reachable"] is True

        checkout = client.post(
            "/checkout",
            json={"customer_email": "journey@example.com", "source": "postgres-journey"},
        )
        assert checkout.status_code == 200
        order_id = checkout.json()["order_id"]
        assert checkout.json()["state"] == "CHECKOUT_PENDING"
        assert checkout.json()["amount_usd"] == 49
        destination = urlsplit(checkout.json()["checkout_url"])
        assert destination.scheme == "https" and destination.hostname == "buy.stripe.com"
        assert parse_qs(destination.query)["client_reference_id"] == [order_id]

        pending = store.get_order(order_id)
        assert pending["state"] == "CHECKOUT_PENDING"
        assert pending["customer_email"] == "journey@example.com"
        assert pending["stripe_session_id"] is None
        assert pending["intake_token"] is None
        assert pending["deliverable_text"] is None
        assert client.get("/handoff", params={"session_id": session_id}).json() == {
            "ready": False, "state": "PROCESSING"
        }
        assert client.post(f"/orders/{order_id}/intake", json=intake).status_code == 401
        assert client.get(
            f"/orders/{order_id}/deliverable", params={"token": "wrong-token"}
        ).status_code == 404

        event = {
            "id": event_id,
            "livemode": False,
            "type": "checkout.session.completed",
            "data": {"object": {
                "id": session_id,
                "client_reference_id": order_id,
                "payment_status": "paid",
                "mode": "payment",
                "amount_total": 4900,
                "currency": "usd",
                "payment_link": "plink_test_journey",
            }},
        }
        payload, headers = simulated_signed_webhook(event)
        unsigned = client.post("/webhooks/stripe", content=payload)
        assert unsigned.status_code == 400
        assert store.get_order(order_id)["state"] == "CHECKOUT_PENDING"
        paid = client.post("/webhooks/stripe", content=payload, headers=headers)
        assert paid.status_code == 200
        assert paid.json() == {"received": True, "order_id": order_id, "state": "PAID"}

        handoff = client.get("/handoff", params={"session_id": session_id})
        assert handoff.status_code == 200
        assert handoff.json()["ready"] is True
        assert handoff.json()["state"] == "PAID"
        assert handoff.json()["order_id"] == order_id
        token = handoff.json()["intake_token"]
        assert isinstance(token, str) and token
        paid_row = store.get_order(order_id)
        assert paid_row["state"] == "PAID"
        assert paid_row["stripe_session_id"] == session_id
        assert hmac.compare_digest(paid_row["intake_token"], token)
        assert client.get(
            f"/orders/{order_id}/deliverable", params={"token": token}
        ).status_code == 409
        assert client.post(
            f"/orders/{order_id}/intake",
            headers={"X-Intake-Token": "wrong-token"}, json=intake,
        ).status_code == 401

        completed = client.post(
            f"/orders/{order_id}/intake", headers={"X-Intake-Token": token}, json=intake
        )
        assert completed.status_code == 200
        assert completed.json()["state"] == "DELIVERY_READY"
        delivery_url = completed.json()["delivery_url"]
        download = client.get(delivery_url)
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("text/markdown")
        assert download.headers["content-disposition"] == (
            'attachment; filename="Cedar-Journey-Verification-30-Day-Content-Pack.md"'
        )
        for response in (checkout, handoff, completed, download):
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["referrer-policy"] == "no-referrer"

        pack = download.text
        assert pack.startswith("# 30-Day Social Content Pack — Cedar Journey Verification\n")
        assert f"Order: {order_id}\n" in pack
        assert len(re.findall(r"^### Post \d+$", pack, re.MULTILINE)) == 10
        assert len(re.findall(r"^### GBP Post \d+$", pack, re.MULTILINE)) == 5
        for heading, following, count in (
            ("## 10 Hooks", "## 10 Social Posts", 10),
            ("## 10 Captions", "## 5 Promotional Ideas", 10),
            ("## 5 Promotional Ideas", "## 5 Google Business Profile Posts", 5),
        ):
            section = pack.split(heading, 1)[1].split(following, 1)[0]
            assert re.findall(r"^(\d+)\. ", section, re.MULTILINE) == [
                str(index) for index in range(1, count + 1)
            ]
        assert re.findall(r"^Day (\d+):", pack, re.MULTILINE) == [
            str(day) for day in range(1, 31)
        ]
        posts = pack.split("## 10 Social Posts", 1)[1].split("## 10 Captions", 1)[0]
        for service in intake["services"]:
            assert service in posts
        for promotion in intake["promotions"]:
            assert promotion in pack
        captions = pack.split("## 10 Captions", 1)[1].split("## 5 Promotional Ideas", 1)[0]
        assert "#" not in captions

        # Reconstruct the store to verify persistence beyond the request's instance.
        durable_store = PostgresOrderStore(store.database_url)
        original = durable_store.get_order(order_id)
        assert original["state"] == "DELIVERY_READY"
        assert original["intake"] == intake
        assert original["deliverable_text"] == pack
        assert original["delivered_at"] is not None
        retry = client.post(
            f"/orders/{order_id}/intake", headers={"X-Intake-Token": token},
            json={**intake, "business_name": "Must Not Replace Original"},
        )
        assert retry.status_code == 200
        assert hmac.compare_digest(retry.json()["delivery_url"], delivery_url)
        assert client.get(delivery_url).text == pack
        assert client.post(
            f"/orders/{order_id}/intake",
            headers={"X-Intake-Token": "wrong-token"}, json=intake,
        ).status_code == 401
        assert client.get(
            f"/orders/{order_id}/deliverable", params={"token": "wrong-token"}
        ).status_code == 404

        duplicate = client.post("/webhooks/stripe", content=payload, headers=headers)
        assert duplicate.status_code == 200
        assert duplicate.json() == {
            "received": True, "order_id": order_id,
            "state": "DELIVERY_READY", "duplicate": True,
        }
        completed_handoff = client.get("/handoff", params={"session_id": session_id})
        assert completed_handoff.json()["state"] == "DELIVERY_READY"
        assert hmac.compare_digest(completed_handoff.json()["intake_token"], token)
        final = durable_store.get_order(order_id)
        assert final["intake"] == original["intake"]
        assert final["deliverable_text"] == original["deliverable_text"]
        assert final["delivered_at"] == original["delivered_at"]

    with durable_store._connect() as connection:
        receipts = connection.execute("""select event_id, order_id, session_id,
            livemode, amount_cents, currency from public.productized_ai_payment_receipts
            where order_id=%s""", (order_id,)).fetchall()
        assert receipts == [{
            "event_id": event_id, "order_id": order_id, "session_id": session_id,
            "livemode": False, "amount_cents": 4900, "currency": "usd",
        }]
        job = connection.execute("""select state, attempts, intake, completed_at,
            lease_token, lease_until from public.productized_ai_fulfillment_jobs
            where order_id=%s""", (order_id,)).fetchone()
        assert job["state"] == "DONE" and job["attempts"] == 1
        assert job["intake"] == intake and job["completed_at"] is not None
        assert job["lease_token"] is None and job["lease_until"] is None
        events = connection.execute("""select event_type, count(*)::int as count
            from public.productized_ai_funnel_events where order_id=%s
            group by event_type""", (order_id,)).fetchall()
        assert {row["event_type"]: row["count"] for row in events} == {
            "checkout_started": 1, "paid": 1, "delivery_ready": 1,
        }

    summary = durable_store.operations_summary()
    assert summary["live_captures"] == 0 and summary["gross_revenue"] == 0
    assert summary["unknown_mode_receipts"] == 0
