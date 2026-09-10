import os
import secrets
from enum import Enum
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from app.store import get_store

app = FastAPI(title="Productized AI Service Engine", version="0.3.2")

OFFER = {"id":"social-content-pack-30d","name":"30-Day Social Content Pack","price_usd":49,"recurring_refresh_usd":29,"deliverables":["10 social posts","10 captions","10 hooks","5 promotional ideas","5 Google Business Profile posts","30-day content calendar"]}

class OrderState(str, Enum):
    NEW="NEW"; CHECKOUT_PENDING="CHECKOUT_PENDING"; PAID="PAID"; INTAKE="INTAKE"; PRODUCTION="PRODUCTION"; QA="QA"; REVISION="REVISION"; DELIVERY="DELIVERY"; COMPLETE="COMPLETE"; FOLLOW_UP="FOLLOW_UP"; RECURRING="RECURRING"

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
    services: list[str] = Field(default_factory=list)
    promotions: list[str] = Field(default_factory=list)
    location: str = ""
    platforms: list[str] = Field(default_factory=lambda: ["Instagram", "Facebook"])
    instructions: str = ""

def _new_order_id():
    return f"ord_{secrets.token_urlsafe(9)}"

@app.get("/health")
def health():
    return {"status":"ok","service":"productized-ai-service-engine","version":"0.3.2","payment_gate":True,"persistent_store":bool(os.getenv("DATABASE_URL")),"webhook_token_configured":bool(os.getenv("STRIPE_WEBHOOK_TOKEN")),"webhook_token_enforced":os.getenv("STRIPE_WEBHOOK_TOKEN_ENFORCED","false").lower()=="true"}

@app.get("/offer")
def offer():
    return OFFER

@app.post("/checkout", response_model=CheckoutResponse)
def create_checkout(payload: CheckoutRequest):
    checkout_base = os.getenv("STRIPE_PAYMENT_LINK_URL")
    if not checkout_base:
        raise HTTPException(status_code=503, detail="Checkout is not configured")
    order_id = _new_order_id()
    try:
        get_store().create_order(order_id, str(payload.customer_email), OFFER["price_usd"], OrderState.CHECKOUT_PENDING.value)
    except Exception:
        raise HTTPException(status_code=503, detail="Order storage unavailable")
    separator = "&" if "?" in checkout_base else "?"
    return CheckoutResponse(order_id=order_id,state=OrderState.CHECKOUT_PENDING,amount_usd=OFFER["price_usd"],checkout_url=f"{checkout_base}{separator}client_reference_id={order_id}")

@app.post("/webhooks/stripe")
async def stripe_webhook(event: dict, token: str | None = Query(default=None)):
    enforce = os.getenv("STRIPE_WEBHOOK_TOKEN_ENFORCED","false").lower()=="true"
    if enforce:
        expected = os.getenv("STRIPE_WEBHOOK_TOKEN")
        if not expected or not secrets.compare_digest(token or "", expected):
            raise HTTPException(status_code=401, detail="Invalid webhook token")
    if event.get("type") != "checkout.session.completed":
        return {"received":True,"ignored":True}
    session = event.get("data",{}).get("object",{})
    order_id = session.get("client_reference_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="Missing client_reference_id")
    intake_token = secrets.token_urlsafe(24)
    try:
        order = get_store().mark_paid(order_id, session.get("id"), intake_token)
    except Exception:
        raise HTTPException(status_code=503, detail="Order storage unavailable")
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"received":True,"order_id":order_id,"state":OrderState.PAID,"intake_token":intake_token}

@app.post("/orders/{order_id}/intake")
def submit_intake(order_id: str, intake: Intake, x_intake_token: str | None = None):
    try:
        order = get_store().get_order(order_id)
    except Exception:
        raise HTTPException(status_code=503, detail="Order storage unavailable")
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order["state"] != OrderState.PAID.value:
        raise HTTPException(status_code=402, detail="Payment required before intake")
    if not order.get("intake_token") or x_intake_token != order["intake_token"]:
        raise HTTPException(status_code=401, detail="Invalid intake token")
    try:
        get_store().save_intake(order_id, intake.model_dump())
    except Exception:
        raise HTTPException(status_code=503, detail="Order storage unavailable")
    return {"order_id":order_id,"state":OrderState.INTAKE,"accepted":True}

@app.get("/orders/{order_id}")
def get_order(order_id: str):
    try:
        order = get_store().get_order(order_id)
    except Exception:
        raise HTTPException(status_code=503, detail="Order storage unavailable")
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"order_id":order["order_id"],"state":order["state"],"amount_usd":order["amount_usd"],"has_intake":order.get("intake") is not None}
