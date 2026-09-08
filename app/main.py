from fastapi import FastAPI
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

app = FastAPI(title="Productized AI Service Engine", version="0.1.0")

class OrderState(str, Enum):
    NEW = "NEW"
    PAID = "PAID"
    INTAKE = "INTAKE"
    PRODUCTION = "PRODUCTION"
    QA = "QA"
    REVISION = "REVISION"
    DELIVERY = "DELIVERY"
    COMPLETE = "COMPLETE"
    FOLLOW_UP = "FOLLOW_UP"
    RECURRING = "RECURRING"

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
    state: OrderState = OrderState.NEW
    customer_email: str
    intake: Optional[Intake] = None

@app.get("/health")
def health():
    return {"status": "ok", "service": "productized-ai-service-engine", "version": "0.1.0"}

@app.get("/offer")
def offer():
    return {
        "name": "30-Day Social Content Pack",
        "price_usd": 49,
        "recurring_refresh_usd": 29,
        "delivery": "automated after payment and intake",
        "deliverables": [
            "10 social posts", "10 captions", "10 hooks",
            "5 promotional ideas", "5 Google Business Profile posts",
            "30-day content calendar"
        ],
    }

@app.post("/orders")
def create_order(order: Order):
    return order
