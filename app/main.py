import os
import secrets
from enum import Enum
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

app = FastAPI(title="Productized AI Service Engine", version="0.2.0")

OFFER = {
    "id": "social-content-pack-30d",
    "name": "30-Day Social Content Pack",
    "price_usd": 49,
    "recurring_refresh_usd": 29,
    "deliverables": [
        "10 social posts",
        "10 captions",
        "10 hooks",
        "5 promotional ideas",
        "5 Google Business Profile posts",
        "30-day content calendar",
    ],
}


class OrderState(str, Enum):
    NEW = "NEW"
    CHECKOUT_PENDING = "CHECKOUT_PENDING"
    PAID = "PAID"
    INTAKE = "INTAKE"
    PRODUCTION = "PRODUCTION"
    QA = "QA"
    REVISION = "REVISION"
    DELIVERY = "DELIVERY"
    COMPLETE = "COMPLETE"
    FOLLOW_UP = "FOLLOW_UP"
    RECURRING = "RECURRING"


class CheckoutRequest(BaseModel):
    customer_email: EmailStr


class CheckoutResponse(BaseModel):
    order_id: str
    state: OrderState
    amount_usd: int
    checkout_url: str


class Intake(BaseModel):
    business_name: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    website: Optional[str] = None
    target_customer: str = ""
    tone: str = "professional and approachable"
    services: list[str] = []
    promotions: list[str] = []
    location: str = ""
    platforms: list[str] = ["Instagram", "Facebook"]
    instructions: str = ""


class Order(BaseModel):
    order_id: str
    state: OrderState
    customer_email: EmailStr
    amount_usd: int = OFFER["price_usd"]
    intake_token: Optional[str] = None
    intake: Optional[Intake] = None
    stripe_session_id: Optional[str] = None


ORDERS: dict[str, Order] = {}


def _new_order_id() -> str:
    return f"ord_{secrets.token_urlsafe(9)}"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "productized-ai-service-engine",
        "version": "0.2.0",
        "payment_gate": True,
    }


@app.get("/offer")
def offer():
    return OFFER


@app.post("/checkout", response_model=CheckoutResponse)
def create_checkout(payload: CheckoutRequest):
    order_id = _new_order_id()
    checkout_base = os.getenv("STRIPE_PAYMENT_LINK_URL")
    if not checkout_base:
        raise HTTPException(
            status_code=503,
            detail="Checkout is not configured. Set STRIPE_PAYMENT_LINK_URL.",
        )

    order = Order(
        order_id=order_id,
        customer_email=payload.customer_email,
        state=OrderState.CHECKOUT_PENDING,
    )
    ORDERS[order_id] = order
    separator = "&" if "?" in checkout_base else "?"
    checkout_url = f"{checkout_base}{separator}client_reference_id={order_id}"
    return CheckoutResponse(
        order_id=order_id,
        state=order.state,
        amount_usd=order.amount_usd,
        checkout_url=checkout_url,
    )


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, x_webhook_secret: str | None = Header(default=None)):
    expected = os.getenv("STRIPE_WEBHOOK_SHARED_SECRET")
    if expected and x_webhook_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    event = await request.json()
    if event.get("type") != "checkout.session.completed":
        return {"received": True, "ignored": True}

    session = event.get("data", {}).get("object", {})
    order_id = session.get("client_reference_id")
    if not order_id or order_id not in ORDERS:
        raise HTTPException(status_code=404, detail="Order not found")

    order = ORDERS[order_id]
    order.state = OrderState.PAID
    order.stripe_session_id = session.get("id")
    order.intake_token = secrets.token_urlsafe(24)
    return {
        "received": True,
        "order_id": order_id,
        "state": order.state,
        "intake_token": order.intake_token,
    }


@app.post("/orders/{order_id}/intake")
def submit_intake(order_id: str, intake: Intake, x_intake_token: str | None = Header(default=None)):
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.state != OrderState.PAID:
        raise HTTPException(status_code=402, detail="Payment required before intake")
    if not order.intake_token or x_intake_token != order.intake_token:
        raise HTTPException(status_code=401, detail="Invalid intake token")

    order.intake = intake
    order.state = OrderState.INTAKE
    return {"order_id": order_id, "state": order.state, "accepted": True}


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {
        "order_id": order.order_id,
        "state": order.state,
        "amount_usd": order.amount_usd,
        "has_intake": order.intake is not None,
    }
