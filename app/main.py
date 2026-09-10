import os
import secrets
from enum import Enum
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field

from app.store import get_store

app=FastAPI(title='Productized AI Service Engine',version='0.4.0')
OFFER={'id':'social-content-pack-30d','name':'30-Day Social Content Pack','price_usd':49,'recurring_refresh_usd':29,'deliverables':['10 social posts','10 captions','10 hooks','5 promotional ideas','5 Google Business Profile posts','30-day content calendar']}

class OrderState(str,Enum):
    CHECKOUT_PENDING='CHECKOUT_PENDING'; PAID='PAID'; INTAKE='INTAKE'
class CheckoutRequest(BaseModel): customer_email: EmailStr
class CheckoutResponse(BaseModel): order_id:str; state:OrderState; amount_usd:int; checkout_url:str
class Intake(BaseModel):
    business_name:str=Field(min_length=1); industry:str=Field(min_length=1); website:Optional[str]=None; target_customer:str=''; tone:str='professional and approachable'; services:list[str]=Field(default_factory=list); promotions:list[str]=Field(default_factory=list); location:str=''; platforms:list[str]=Field(default_factory=lambda:['Instagram','Facebook']); instructions:str=''

@app.get('/health')
def health():
    return {'status':'ok','service':'productized-ai-service-engine','version':'0.4.0','payment_gate':True,'persistent_store':bool(os.getenv('DATABASE_URL'))}

@app.get('/offer')
def offer(): return OFFER

@app.post('/checkout',response_model=CheckoutResponse)
def create_checkout(payload:CheckoutRequest):
    base=os.getenv('STRIPE_PAYMENT_LINK_URL')
    if not base: raise HTTPException(503,'Checkout is not configured')
    order_id=f"ord_{secrets.token_urlsafe(9)}"
    try: get_store().create_order(order_id,str(payload.customer_email),49,'CHECKOUT_PENDING')
    except Exception: raise HTTPException(503,'Order storage unavailable')
    sep='&' if '?' in base else '?'
    return CheckoutResponse(order_id=order_id,state=OrderState.CHECKOUT_PENDING,amount_usd=49,checkout_url=f'{base}{sep}client_reference_id={order_id}')

@app.post('/webhooks/stripe')
async def stripe_webhook(event:dict,token:str|None=Query(default=None)):
    enforce=os.getenv('STRIPE_WEBHOOK_TOKEN_ENFORCED','false').lower()=='true'
    if enforce:
        expected=os.getenv('STRIPE_WEBHOOK_TOKEN')
        if not expected or not secrets.compare_digest(token or '',expected): raise HTTPException(401,'Invalid webhook token')
    if event.get('type')!='checkout.session.completed': return {'received':True,'ignored':True}
    session=event.get('data',{}).get('object',{}); order_id=session.get('client_reference_id')
    if not order_id: raise HTTPException(400,'Missing client_reference_id')
    intake_token=secrets.token_urlsafe(24)
    try: order=get_store().mark_paid(order_id,session.get('id'),intake_token)
    except Exception: raise HTTPException(503,'Order storage unavailable')
    if not order: raise HTTPException(404,'Order not found')
    return {'received':True,'order_id':order_id,'state':'PAID'}

@app.get('/handoff')
def handoff(session_id:str):
    try: order=get_store().get_order_by_session(session_id)
    except Exception: raise HTTPException(503,'Order storage unavailable')
    if not order: return {'ready':False,'state':'PROCESSING'}
    if order['state']=='PAID': return {'ready':True,'state':'PAID','order_id':order['order_id'],'intake_token':order['intake_token']}
    if order['state']=='INTAKE': return {'ready':True,'state':'INTAKE','order_id':order['order_id']}
    return {'ready':False,'state':order['state']}

@app.get('/success',response_class=HTMLResponse)
def success_page(session_id:str):
    return HTMLResponse('''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Payment received</title><style>body{font-family:system-ui,-apple-system,sans-serif;background:#f7f3ea;color:#15223a;margin:0}.wrap{max-width:680px;margin:auto;padding:28px}.card{background:white;border-radius:20px;padding:24px;box-shadow:0 8px 30px #00000012}h1{margin-top:0}label{display:block;font-weight:600;margin:14px 0 6px}input,textarea{width:100%;box-sizing:border-box;padding:13px;border:1px solid #ccd3df;border-radius:10px;font-size:16px}button{width:100%;margin-top:20px;padding:14px;border:0;border-radius:10px;background:#15223a;color:white;font-size:17px;font-weight:700}#form{display:none}.muted{color:#667085}.ok{color:#137333;font-weight:700}</style></head><body><div class="wrap"><div class="card"><h1>Payment received.</h1><p id="status" class="muted">Confirming your order and preparing your intake form…</p><form id="form"><label>Business name</label><input id="business_name" required><label>Industry</label><input id="industry" required><label>Website</label><input id="website"><label>Target customer</label><textarea id="target_customer"></textarea><label>Brand tone</label><input id="tone" value="professional and approachable"><label>Location</label><input id="location"><label>Services to promote</label><textarea id="services" placeholder="One per line"></textarea><label>Current promotions</label><textarea id="promotions" placeholder="One per line"></textarea><label>Platforms</label><input id="platforms" value="Instagram, Facebook"><label>Anything else we should know?</label><textarea id="instructions"></textarea><button>Submit and start production</button></form></div></div><script>const sid=new URLSearchParams(location.search).get('session_id');let orderId='',token='';const statusEl=document.getElementById('status'),form=document.getElementById('form');async function poll(){if(!sid){statusEl.textContent='Missing checkout session. Please contact support.';return;}let r=await fetch('/handoff?session_id='+encodeURIComponent(sid));let d=await r.json();if(d.state==='INTAKE'){statusEl.className='ok';statusEl.textContent='Your intake has already been submitted. Production is queued.';return;}if(d.ready){orderId=d.order_id;token=d.intake_token;statusEl.textContent='Confirmed. Tell us about your business so production can begin.';form.style.display='block';return;}setTimeout(poll,1500)}form.addEventListener('submit',async e=>{e.preventDefault();const lines=id=>document.getElementById(id).value.split(/\n|,/).map(x=>x.trim()).filter(Boolean);const payload={business_name:business_name.value,industry:industry.value,website:website.value||null,target_customer:target_customer.value,tone:tone.value,services:lines('services'),promotions:lines('promotions'),location:location.value,platforms:lines('platforms'),instructions:instructions.value};let r=await fetch('/orders/'+orderId+'/intake',{method:'POST',headers:{'Content-Type':'application/json','x-intake-token':token},body:JSON.stringify(payload)});if(r.ok){form.style.display='none';statusEl.className='ok';statusEl.textContent='Intake received. Your order is now queued for production.'}else{statusEl.textContent='We could not submit the intake. Please try again.'}});poll();</script></body></html>''')

@app.post('/orders/{order_id}/intake')
def submit_intake(order_id:str,intake:Intake,x_intake_token:str|None=Header(default=None)):
    try: order=get_store().get_order(order_id)
    except Exception: raise HTTPException(503,'Order storage unavailable')
    if not order: raise HTTPException(404,'Order not found')
    if order['state']!='PAID': raise HTTPException(402,'Payment required before intake')
    if not order.get('intake_token') or x_intake_token!=order['intake_token']: raise HTTPException(401,'Invalid intake token')
    try: get_store().save_intake(order_id,intake.model_dump())
    except Exception: raise HTTPException(503,'Order storage unavailable')
    return {'order_id':order_id,'state':'INTAKE','accepted':True,'production_ready':True}

@app.get('/orders/{order_id}')
def get_order(order_id:str):
    try: order=get_store().get_order(order_id)
    except Exception: raise HTTPException(503,'Order storage unavailable')
    if not order: raise HTTPException(404,'Order not found')
    return {'order_id':order['order_id'],'state':order['state'],'amount_usd':order['amount_usd'],'has_intake':order.get('intake') is not None}
