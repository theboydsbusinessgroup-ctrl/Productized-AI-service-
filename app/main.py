import os
import secrets
from enum import Enum
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, EmailStr, Field

from app.generator import build_content_pack
from app.store import get_store

app=FastAPI(title='Productized AI Service Engine',version='0.7.0')
OFFER={'id':'social-content-pack-30d','name':'30-Day Social Content Pack','price_usd':49,'recurring_refresh_usd':29,'deliverables':['10 social posts','10 captions','10 hooks','5 promotional ideas','5 Google Business Profile posts','30-day content calendar']}
class OrderState(str,Enum): CHECKOUT_PENDING='CHECKOUT_PENDING'; PAID='PAID'; DELIVERY_READY='DELIVERY_READY'
class CheckoutRequest(BaseModel): customer_email:EmailStr; source:Optional[str]=None
class CheckoutResponse(BaseModel): order_id:str; state:OrderState; amount_usd:int; checkout_url:str
class Intake(BaseModel):
    business_name:str=Field(min_length=1); industry:str=Field(min_length=1); website:Optional[str]=None; target_customer:str=''; tone:str='professional and approachable'; services:list[str]=Field(default_factory=list); promotions:list[str]=Field(default_factory=list); location:str=''; platforms:list[str]=Field(default_factory=lambda:['Instagram','Facebook']); instructions:str=''

class FunnelEvent(BaseModel): event_type:str; source:Optional[str]=None; metadata:dict={}

@app.post('/events')
def log_public_event(event:FunnelEvent):
    if event.event_type not in {'page_view'}: raise HTTPException(400,'Unsupported event')
    try: get_store().log_event(event.event_type,source=event.source,metadata=event.metadata)
    except Exception: pass
    return {'ok':True}

@app.get('/internal/funnel')
def funnel_summary(token:str):
    expected=os.getenv('STRIPE_WEBHOOK_TOKEN')
    if not expected or not secrets.compare_digest(token,expected): raise HTTPException(401,'Unauthorized')
    return get_store().funnel_summary()

@app.get('/', response_class=HTMLResponse)
def landing_page():
    return HTMLResponse(r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>30-Day Social Content Pack</title><meta name="description" content="Get 30 days of ready-to-use social content for your business for $49."><style>body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#0f1c31;color:#172033}.page{min-height:100vh;background:linear-gradient(180deg,#0f1c31 0,#162947 42%,#f7f3ea 42%,#f7f3ea 100%)}.wrap{max-width:960px;margin:auto;padding:28px 20px 60px}.hero{color:white;padding:38px 0 46px}.eyebrow{font-size:13px;letter-spacing:.16em;text-transform:uppercase;color:#e2bd62;font-weight:800}.hero h1{font-size:clamp(38px,7vw,68px);line-height:.98;margin:14px 0 18px;max-width:820px}.hero p{font-size:20px;line-height:1.5;max-width:700px;color:#e8edf5}.grid{display:grid;grid-template-columns:1.2fr .8fr;gap:24px;align-items:start}.card{background:white;border-radius:22px;padding:28px;box-shadow:0 16px 50px #00000018}.price{font-size:48px;font-weight:850;margin:0}.once{color:#687386}.check{padding:0;list-style:none}.check li{padding:9px 0;border-bottom:1px solid #edf0f4}.check li:before{content:'✓';font-weight:900;margin-right:10px;color:#1b7f55}.buy{position:sticky;top:20px}.buy h2{margin-top:0}.buy p{color:#5e6878;line-height:1.5}label{display:block;font-weight:700;margin:18px 0 7px}input{width:100%;box-sizing:border-box;padding:15px;border:1px solid #cbd2dc;border-radius:11px;font-size:16px}button{width:100%;margin-top:16px;border:0;border-radius:11px;padding:16px;background:#15223a;color:white;font-size:17px;font-weight:800;cursor:pointer}.fine{font-size:12px!important;color:#7b8493!important;text-align:center}.steps{margin-top:24px}.steps strong{display:block;margin-bottom:5px}.badge{display:inline-block;padding:7px 10px;border-radius:999px;background:#eef2f7;font-size:12px;font-weight:800}.error{color:#a12626;font-size:14px;margin-top:10px;min-height:20px}@media(max-width:760px){.grid{grid-template-columns:1fr}.buy{position:static}.hero{padding-top:20px}.page{background:linear-gradient(180deg,#0f1c31 0,#162947 35%,#f7f3ea 35%,#f7f3ea 100%)}}</style></head><body><div class="page"><div class="wrap"><section class="hero"><div class="eyebrow">Done-for-you content • instant delivery</div><h1>Stop wondering what to post for the next 30 days.</h1><p>Answer a few questions about your business and receive a personalized social content pack immediately after checkout.</p></section><div class="grid"><section class="card"><span class="badge">30-Day Social Content Pack</span><h2>What you get</h2><ul class="check"><li>10 ready-to-use social posts</li><li>10 captions</li><li>10 scroll-stopping hooks</li><li>5 promotional campaign ideas</li><li>5 Google Business Profile posts</li><li>A 30-day posting calendar</li><li>Personalized to your business, services, audience, location and tone</li><li>Instant secure download after intake</li></ul><div class="steps"><h2>How it works</h2><p><strong>1. Purchase securely.</strong> Checkout is handled by Stripe.</p><p><strong>2. Tell us about your business.</strong> Complete the short post-payment intake.</p><p><strong>3. Download immediately.</strong> Your personalized content pack is generated and delivered on the spot.</p></div></section><aside class="card buy"><p class="price">$49</p><p class="once">One-time purchase. No subscription required.</p><h2>Get your content pack</h2><p>Enter the email you want attached to your order. We create your tracked order first, then send you to secure Stripe checkout.</p><form id="buyForm"><label for="email">Email address</label><input id="email" name="email" type="email" autocomplete="email" placeholder="you@business.com" required><button id="buyButton" type="submit">Get 30 Days of Content — $49</button><div id="error" class="error"></div></form><p class="fine">Secure payment via Stripe. Digital service. Review generated content for current pricing, claims and local requirements before publishing.</p></aside></div></div></div><script>const src=new URLSearchParams(location.search).get('src')||document.referrer||'direct';fetch('/events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event_type:'page_view',source:src})}).catch(()=>{});const form=document.getElementById('buyForm'),btn=document.getElementById('buyButton'),err=document.getElementById('error');form.addEventListener('submit',async e=>{e.preventDefault();err.textContent='';btn.disabled=true;btn.textContent='Preparing secure checkout…';try{const r=await fetch('/checkout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({customer_email:document.getElementById('email').value,source:src})});const d=await r.json();if(!r.ok||!d.checkout_url)throw new Error(d.detail||'Checkout could not be started.');location.href=d.checkout_url}catch(ex){err.textContent=ex.message||'Checkout could not be started. Please try again.';btn.disabled=false;btn.textContent='Get 30 Days of Content — $49'}});</script></body></html>''')

@app.get('/health')
def health(): return {'status':'ok','service':'productized-ai-service-engine','version':'0.7.0','payment_gate':True,'persistent_store':bool(os.getenv('DATABASE_URL')),'instant_fulfillment':True}
@app.get('/offer')
def offer(): return OFFER
@app.post('/checkout',response_model=CheckoutResponse)
def create_checkout(payload:CheckoutRequest):
    base=os.getenv('STRIPE_PAYMENT_LINK_URL')
    if not base: raise HTTPException(503,'Checkout is not configured')
    order_id=f"ord_{secrets.token_urlsafe(9)}"
    try: get_store().create_order(order_id,str(payload.customer_email),49,'CHECKOUT_PENDING')
    except Exception: raise HTTPException(503,'Order storage unavailable')
    try: get_store().log_event('checkout_started',order_id=order_id,source=payload.source)
    except Exception: pass
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
    try: order=get_store().mark_paid(order_id,session.get('id'),secrets.token_urlsafe(24))
    except Exception: raise HTTPException(503,'Order storage unavailable')
    if not order: raise HTTPException(404,'Order not found')
    try: get_store().log_event('paid',order_id=order_id,metadata={'stripe_session_id':session.get('id')})
    except Exception: pass
    return {'received':True,'order_id':order_id,'state':'PAID'}
@app.get('/handoff')
def handoff(session_id:str):
    try: order=get_store().get_order_by_session(session_id)
    except Exception: raise HTTPException(503,'Order storage unavailable')
    if not order: return {'ready':False,'state':'PROCESSING'}
    if order['state']=='PAID': return {'ready':True,'state':'PAID','order_id':order['order_id'],'intake_token':order['intake_token']}
    if order['state']=='DELIVERY_READY': return {'ready':True,'state':'DELIVERY_READY','order_id':order['order_id'],'intake_token':order['intake_token'],'delivery_url':f"/orders/{order['order_id']}/deliverable?token={order['intake_token']}"}
    return {'ready':False,'state':order['state']}
@app.get('/success',response_class=HTMLResponse)
def success_page(session_id:str):
    return HTMLResponse('''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Your Content Pack</title><style>body{font-family:system-ui,-apple-system,sans-serif;background:#f7f3ea;color:#15223a;margin:0}.wrap{max-width:680px;margin:auto;padding:28px}.card{background:white;border-radius:20px;padding:24px;box-shadow:0 8px 30px #00000012}h1{margin-top:0}label{display:block;font-weight:600;margin:14px 0 6px}input,textarea{width:100%;box-sizing:border-box;padding:13px;border:1px solid #ccd3df;border-radius:10px;font-size:16px}button,.download{display:block;box-sizing:border-box;text-align:center;width:100%;margin-top:20px;padding:14px;border:0;border-radius:10px;background:#15223a;color:white;font-size:17px;font-weight:700;text-decoration:none}#form,#download{display:none}.muted{color:#667085}.ok{color:#137333;font-weight:700}</style></head><body><div class="wrap"><div class="card"><h1>Payment received.</h1><p id="status" class="muted">Confirming your order and preparing your intake form…</p><form id="form"><label>Business name</label><input id="business_name" required><label>Industry</label><input id="industry" required><label>Website</label><input id="website"><label>Target customer</label><textarea id="target_customer"></textarea><label>Brand tone</label><input id="tone" value="professional and approachable"><label>Location</label><input id="location"><label>Services to promote</label><textarea id="services" placeholder="One per line"></textarea><label>Current promotions</label><textarea id="promotions" placeholder="One per line"></textarea><label>Platforms</label><input id="platforms" value="Instagram, Facebook"><label>Anything else we should know?</label><textarea id="instructions"></textarea><button>Generate my content pack</button></form><a id="download" class="download">Download your content pack</a></div></div><script>const sid=new URLSearchParams(location.search).get('session_id');let orderId='',token='';const statusEl=document.getElementById('status'),form=document.getElementById('form'),dl=document.getElementById('download');function showDownload(url){form.style.display='none';statusEl.className='ok';statusEl.textContent='Your content pack is ready.';dl.href=url;dl.style.display='block'}async function poll(){if(!sid){statusEl.textContent='Missing checkout session. Please contact support.';return;}let r=await fetch('/handoff?session_id='+encodeURIComponent(sid));let d=await r.json();if(d.state==='DELIVERY_READY'){showDownload(d.delivery_url);return;}if(d.ready){orderId=d.order_id;token=d.intake_token;statusEl.textContent='Confirmed. Tell us about your business and your pack will be generated immediately.';form.style.display='block';return;}setTimeout(poll,1500)}form.addEventListener('submit',async e=>{e.preventDefault();statusEl.textContent='Generating your content pack…';const lines=id=>document.getElementById(id).value.split(/\n|,/).map(x=>x.trim()).filter(Boolean);const payload={business_name:business_name.value,industry:industry.value,website:website.value||null,target_customer:target_customer.value,tone:tone.value,services:lines('services'),promotions:lines('promotions'),location:location.value,platforms:lines('platforms'),instructions:instructions.value};let r=await fetch('/orders/'+orderId+'/intake',{method:'POST',headers:{'Content-Type':'application/json','x-intake-token':token},body:JSON.stringify(payload)});let d=await r.json();if(r.ok){showDownload(d.delivery_url)}else{statusEl.textContent='We could not generate the pack. Please try again.'}});poll();</script></body></html>''')
@app.post('/orders/{order_id}/intake')
def submit_intake(order_id:str,intake:Intake,x_intake_token:str|None=Header(default=None)):
    try: order=get_store().get_order(order_id)
    except Exception: raise HTTPException(503,'Order storage unavailable')
    if not order: raise HTTPException(404,'Order not found')
    if order['state']!='PAID': raise HTTPException(409,'Order is not awaiting intake')
    if not order.get('intake_token') or x_intake_token!=order['intake_token']: raise HTTPException(401,'Invalid intake token')
    pack=build_content_pack(intake.model_dump(),order_id)
    try: saved=get_store().save_fulfillment(order_id,intake.model_dump(),pack)
    except Exception: raise HTTPException(503,'Fulfillment storage unavailable')
    if not saved: raise HTTPException(404,'Order not found')
    try: get_store().log_event('delivery_ready',order_id=order_id)
    except Exception: pass
    return {'order_id':order_id,'state':'DELIVERY_READY','accepted':True,'delivery_url':f'/orders/{order_id}/deliverable?token={x_intake_token}'}
@app.get('/orders/{order_id}/deliverable',response_class=PlainTextResponse)
def deliverable(order_id:str,token:str):
    try: order=get_store().get_order(order_id)
    except Exception: raise HTTPException(503,'Order storage unavailable')
    if not order or order.get('intake_token')!=token: raise HTTPException(404,'Deliverable not found')
    if order['state']!='DELIVERY_READY' or not order.get('deliverable_text'): raise HTTPException(409,'Deliverable is not ready')
    safe=''.join(c if c.isalnum() or c in '-_' else '-' for c in (order.get('intake') or {}).get('business_name','content-pack')).strip('-') or 'content-pack'
    return PlainTextResponse(order['deliverable_text'],media_type='text/markdown',headers={'Content-Disposition':f'attachment; filename="{safe}-30-Day-Content-Pack.md"'})
@app.get('/orders/{order_id}')
def get_order(order_id:str):
    try: order=get_store().get_order(order_id)
    except Exception: raise HTTPException(503,'Order storage unavailable')
    if not order: raise HTTPException(404,'Order not found')
    return {'order_id':order['order_id'],'state':order['state'],'amount_usd':order['amount_usd'],'has_intake':order.get('intake') is not None,'deliverable_ready':bool(order.get('deliverable_text'))}
