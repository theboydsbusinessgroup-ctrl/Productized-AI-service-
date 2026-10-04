"""Payment-first consultations. Slot approval remains an authenticated host action."""
import asyncio
import os
import secrets
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import stripe
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field, StrictBool

from app.consultation_store import ConsultationConflict, get_consultation_store

router = APIRouter(prefix='/consultations', tags=['consultations'])
PRICE_CENTS = 1900
DURATION_MINUTES = 20
PAID_STATES = {'PAID_AWAITING_SCHEDULING', 'TIMES_PROPOSED', 'APPROVED_AWAITING_CALENDAR'}
PAYMENT_SETTING_NAMES = (
    'DATABASE_URL', 'CONSULTATION_PAYMENT_LINK_URL', 'CONSULTATION_PAYMENT_LINK_ID',
    'CONSULTATION_STRIPE_WEBHOOK_SECRET', 'CONSULTATION_GUMROAD_PRODUCT_ID',
    'CONSULTATION_GUMROAD_WEBHOOK_TOKEN', 'CONSULTATION_GUMROAD_ACCESS_TOKEN',
    'CONSULTATION_ADMIN_TOKEN',
)


def _product_id():
    value = os.getenv('CONSULTATION_GUMROAD_PRODUCT_ID')
    if not value:
        raise HTTPException(503, 'Qualifying ebook verification is not configured')
    return value


def _admin(token: str | None):
    expected = os.getenv('CONSULTATION_ADMIN_TOKEN')
    if not expected or not secrets.compare_digest((token or '').encode(), expected.encode()):
        raise HTTPException(401, 'Unauthorized')


def _operation(callback):
    try:
        return callback(get_consultation_store())
    except PermissionError:
        raise HTTPException(401, 'Invalid consultation token')
    except ConsultationConflict as exc:
        raise HTTPException(409, str(exc))
    except Exception:
        raise HTTPException(503, 'Consultation storage unavailable; retry safely')


class Checkout(BaseModel):
    customer_email: EmailStr
    ebook_order_id: str = Field(min_length=1, max_length=200)
    code: str = Field(default='BARBUYER', max_length=30)
    terms_accepted: StrictBool


class TrustedSale(BaseModel):
    sale_id: str = Field(min_length=1, max_length=200)
    order_number: str | None = Field(default=None, min_length=1, max_length=200)
    product_id: str = Field(min_length=1, max_length=200)
    purchase_email: EmailStr
    payment_succeeded: StrictBool
    refunded: StrictBool
    disputed: StrictBool


class Slot(BaseModel):
    start_datetime: datetime
    end_datetime: datetime
    timezone: str = Field(min_length=1, max_length=80)

    def canonical(self):
        start, end = self.start_datetime, self.end_datetime
        if start.tzinfo is None or end.tzinfo is None:
            raise HTTPException(422, 'Times must include UTC offsets and a timezone')
        try:
            zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise HTTPException(422, 'Use an IANA timezone such as America/Chicago')
        # Offset-bearing timestamps avoid accepting nonexistent local DST times.
        if start.utcoffset() != start.astimezone(zone).utcoffset() or end.utcoffset() != end.astimezone(zone).utcoffset():
            raise HTTPException(422, 'Timestamp offset does not match the named timezone')
        start, end = start.astimezone(dt_timezone.utc), end.astimezone(dt_timezone.utc)
        if start <= datetime.now(dt_timezone.utc) or end - start != timedelta(minutes=DURATION_MINUTES):
            raise HTTPException(422, 'Choose a future slot lasting exactly 20 minutes')
        return {'start_datetime': start.isoformat(), 'end_datetime': end.isoformat(), 'timezone': self.timezone}


class Proposals(BaseModel):
    slots: list[Slot] = Field(min_length=1, max_length=10)


class Approval(Slot):
    revision: int = Field(ge=1)
    calendar_available: StrictBool
    calendar_checked_at: datetime


class CalendarConfirmation(Slot):
    revision: int = Field(ge=1)
    calendar_event_id: str = Field(min_length=5, max_length=1024)
    calendar_id: str = Field(min_length=1, max_length=320)
    provider_result_verified: StrictBool


LANDING_HTML = r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Your home-bar session | Behind The Bar</title><style>body{font:17px system-ui;background:#101c2c;color:#182334;margin:0}.wrap{max-width:660px;margin:auto;padding:30px 18px}.card{background:#fffdf7;padding:30px;border-radius:20px}h1{font-size:38px;line-height:1.1}.price{font-size:30px;font-weight:800}p,li{line-height:1.6}a{color:#145b86}label{display:block;margin-top:18px;font-weight:700}input,button{font:inherit;box-sizing:border-box;width:100%;padding:13px;border-radius:9px;border:1px solid #b6bfca}button{margin-top:20px;background:#182334;color:white;font-weight:800;cursor:pointer}button[disabled]{opacity:.65;cursor:default}.terms{font-size:14px;font-weight:400}.terms input{width:auto;margin-right:8px}.small{font-size:14px;color:#526172}#error{color:#9a2525}</style></head><body><main class="wrap"><div class="card"><p>BEHIND THE BAR · EBOOK BUYER OFFER</p><h1>Build a home bar that works for you.</h1><p class="price">$19 · 20-minute virtual session</p><p>Bring your bottle list and recipe questions. We can work through your shopping plan, measuring and equipment. Drinking is not required.</p><p>For verified buyers of <em>One Bottle at a Time</em>. One session per qualifying purchase, purchased separately from the $9 ebook. <a href="https://boydsbusiness.gumroad.com/l/yknubt">Get the $9 ebook</a>.</p><ol><li>Verify your ebook purchase and pay securely through Stripe.</li><li>After successful payment, propose any future date and time.</li><li>Eric approves the exact slot before a calendar invitation is arranged.</li></ol><p>Payment buys your session; it does not reserve a time. If Eric cannot provide it, choose an approved replacement time or a full $19 session refund. Rescheduling does not require another session payment.</p><form id="buy" data-checkout-ready="true"><label for="email">Your ebook purchase email</label><input id="email" type="email" autocomplete="email" required><label for="order">Ebook order ID</label><input id="order" maxlength="200" required><p class="small">Use the private order ID from your Gumroad receipt. BARBUYER identifies this offer and is not proof of purchase. Keep receipts private.</p><label class="terms"><input id="terms" type="checkbox" required>I accept: payment is required before scheduling; Eric approves the date and time; changing a slot needs fresh approval. If a paid session cannot be provided, I may choose an approved replacement or a full session-fee refund. For buyer cancellations/no-shows, contact us to request rescheduling.</label><button id="button">Pay $19 securely</button><p id="error" role="alert"></p></form><p class="small">Adults of legal drinking age. Ingredients and equipment are not included. Help: theboydsbusinessgroup@gmail.com</p></div></main><script>document.getElementById('buy').addEventListener('submit',async e=>{e.preventDefault();if(e.currentTarget.dataset.checkoutReady!=='true')return;const b=document.getElementById('button'),err=document.getElementById('error');b.disabled=true;err.textContent='';try{const r=await fetch('/consultations/checkout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({customer_email:document.getElementById('email').value,ebook_order_id:document.getElementById('order').value,code:'BARBUYER',terms_accepted:document.getElementById('terms').checked})});const d=await r.json();if(!r.ok)throw Error(d.detail||'Checkout could not be prepared');location.href=d.checkout_url}catch(ex){err.textContent=typeof ex.message==='string'?ex.message:'Please contact support to verify your purchase.';b.disabled=false}});</script></body></html>'''

SUCCESS_HTML = r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Choose your preferred time | Behind The Bar</title><style>body{font:17px system-ui;background:#f7f3ea;color:#182334;margin:0}.wrap{max-width:600px;margin:auto;padding:28px}label{display:block;margin:18px 0 7px}input,button{font:inherit;width:100%;padding:12px;box-sizing:border-box}button{margin-top:22px;background:#182334;color:white;border:0;border-radius:9px}#form{display:none}p{line-height:1.6}</style></head><body><main class="wrap"><h1>Your virtual home-bar session</h1><p id="status" role="status">Checking your payment. Scheduling opens after Stripe confirms successful payment.</p><form id="form"><label for="start">Preferred date and start time</label><input id="start" type="datetime-local" required><label for="zone">Your timezone</label><input id="zone" readonly required><p>Choose any future time. Eric must approve the exact slot. Submitting a request does not reserve the time or create a meeting invitation.</p><button>Send preferred time for approval</button></form><p>If Eric cannot provide your paid session, choose an approved replacement or a full $19 session refund. Help: theboydsbusinessgroup@gmail.com</p></main><script>let requestId='',token='';const sid=new URLSearchParams(location.search).get('session_id'),statusEl=document.getElementById('status'),form=document.getElementById('form');const localZone=Intl.DateTimeFormat().resolvedOptions().timeZone;document.getElementById('zone').value=localZone;let tries=0;async function poll(){if(!sid){statusEl.textContent='Missing payment reference. Contact support with your Stripe receipt privately.';return}try{const r=await fetch('/consultations/handoff?session_id='+encodeURIComponent(sid),{cache:'no-store'});if(!r.ok)throw Error('Cannot check payment');const d=await r.json();if(d.state==='BOOKED'||d.state==='COMPLETED'){form.style.display='none';statusEl.textContent=d.state==='COMPLETED'?'Your session is completed. Thank you.':'Your session is confirmed.';if(d.approved_slot&&d.approved_slot.start_datetime){const when=new Date(d.approved_slot.start_datetime);if(!isNaN(when))statusEl.textContent+=' '+when.toLocaleString(undefined,{timeZone:d.approved_slot.timezone,timeZoneName:'short'})}return}if(d.ready){requestId=d.request_id;token=d.intake_token;statusEl.textContent=d.state==='APPROVED_AWAITING_CALENDAR'?'Eric approved your proposed slot. The calendar invitation is still pending.':'Payment verified. Propose a time for Eric to approve.';form.style.display='block';return}statusEl.textContent=d.state==='PROCESSING'?'Waiting for Stripe payment verification. If this continues, contact support with your receipt privately.':'Your payment or ebook eligibility needs review. Please contact support.';if(d.state!=='PROCESSING')return}catch(e){statusEl.textContent='Unable to check payment yet. Please retry or contact support.'}if(++tries<30)setTimeout(poll,2000)}form.addEventListener('submit',async e=>{e.preventDefault();try{if(document.getElementById('zone').value!==localZone)throw Error('Set the time using your device timezone: '+localZone);const start=new Date(document.getElementById('start').value),end=new Date(start.getTime()+20*60000);const pad=n=>String(n).padStart(2,'0');function stamp(d){const off=-d.getTimezoneOffset();return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+pad(d.getHours())+':'+pad(d.getMinutes())+':00'+(off<0?'-':'+')+pad(Math.floor(Math.abs(off)/60))+':'+pad(Math.abs(off)%60)}const r=await fetch('/consultations/'+encodeURIComponent(requestId)+'/times',{method:'POST',headers:{'Content-Type':'application/json','x-consultation-token':token},body:JSON.stringify({slots:[{start_datetime:stamp(start),end_datetime:stamp(end),timezone:localZone}]})});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Please check the date and timezone');statusEl.textContent='Preferred time received. Eric will review it; your session is not confirmed yet.';form.style.display='none'}catch(e){statusEl.textContent=e.message}});poll();</script></body></html>'''


@router.get('', response_class=HTMLResponse)
def landing():
    html = LANDING_HTML
    if not all(os.getenv(name) for name in PAYMENT_SETTING_NAMES):
        html = html.replace('data-checkout-ready="true"', 'data-checkout-ready="false"')
        html = html.replace('<button id="button">', '<button id="button" disabled>')
        html = html.replace('<p id="error" role="alert"></p>',
                            '<p id="error" role="status">Session checkout is temporarily unavailable. '
                            'Please check back or contact support.</p>')
    return HTMLResponse(html)


@router.get('/health')
def health():
    configured = {key: bool(os.getenv(key)) for key in PAYMENT_SETTING_NAMES}
    reachable = False
    if configured['DATABASE_URL']:
        try:
            reachable = get_consultation_store().healthcheck()
        except Exception:
            pass
    return {'payment_gate': all(configured.values()) and reachable, 'configuration': configured,
            'database_reachable': reachable, 'slot_approval': 'manual',
            'manual_calendar_confirmation_configured': bool(os.getenv('CONSULTATION_GOOGLE_CALENDAR_ID')),
            'automatic_calendar_booking': False}


@router.post('/checkout')
def checkout(payload: Checkout):
    if not payload.terms_accepted or payload.code.upper() != 'BARBUYER':
        raise HTTPException(422, 'Accept the session terms and use offer code BARBUYER')
    if not all(os.getenv(name) for name in PAYMENT_SETTING_NAMES):
        raise HTTPException(503, 'Consultation checkout is not configured')
    base = os.environ['CONSULTATION_PAYMENT_LINK_URL']
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or parsed.hostname != 'buy.stripe.com' or parsed.fragment:
        raise HTTPException(503, 'Consultation payment URL is invalid')
    row = _operation(lambda store: store.create_request(payload.ebook_order_id.strip(),
                     str(payload.customer_email).casefold(), _product_id()))
    sep = '&' if parsed.query else '?'
    return {'request_id': row['request_id'], 'state': row['state'], 'amount_usd': 19,
            'checkout_url': base + sep + urlencode({'client_reference_id': row['request_id'],
                                                    'prefilled_email': str(payload.customer_email)})}


@router.post('/webhooks/stripe')
async def stripe_webhook(request: Request):
    secret = os.getenv('CONSULTATION_STRIPE_WEBHOOK_SECRET')
    if not secret:
        raise HTTPException(503, 'Consultation webhook verification is not configured')
    signature = request.headers.get('stripe-signature')
    if not signature:
        raise HTTPException(400, 'Missing Stripe-Signature header')
    try:
        event = stripe.Webhook.construct_event(await request.body(), signature, secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(400, 'Invalid Stripe webhook signature')
    if not event.get('id') or event.get('livemode') is not True:
        return {'received': True, 'ignored': True, 'reason': 'not_live_event'}
    kind = event.get('type')
    if kind in ('charge.refunded', 'charge.dispute.created'):
        result = _operation(lambda store: store.revoke_payment(event))
        return {'received': True, **result}
    if kind not in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        return {'received': True, 'ignored': True}
    session = event.get('data', {}).get('object', {})
    link = os.getenv('CONSULTATION_PAYMENT_LINK_ID')
    if not link:
        raise HTTPException(503, 'Consultation Payment Link verification is not configured')
    if session.get('payment_link') != link:
        return {'received': True, 'ignored': True, 'reason': 'unexpected_payment_link'}
    if session.get('payment_status') != 'paid':
        return {'received': True, 'ignored': True, 'reason': 'payment_not_paid'}
    if not session.get('id'):
        raise HTTPException(400, 'Missing Checkout Session identity')
    rejection = None
    if session.get('mode') != 'payment':
        rejection = 'unexpected_checkout_mode'
    elif session.get('amount_total') != PRICE_CENTS:
        rejection = 'unexpected_amount'
    elif str(session.get('currency', '')).lower() != 'usd':
        rejection = 'unexpected_currency'
    elif not session.get('payment_intent'):
        rejection = 'missing_payment_intent'
    result = _operation(lambda store: store.record_payment(event, _product_id(), rejection))
    return {'received': True, **result}


@router.get('/handoff')
def handoff(session_id: str):
    row = _operation(lambda store: store.get_by_session(session_id))
    if not row:
        return {'ready': False, 'state': 'PROCESSING'}
    eligible = (row['product_id'] == _product_id() and row['payment_succeeded']
                and not row['refunded'] and not row['disputed'])
    if row['payment_valid'] and eligible and row['state'] in ('BOOKED', 'COMPLETED'):
        return {'ready': False, 'state': row['state'], 'approved_slot': row.get('approved_slot')}
    if not row['payment_valid'] or not eligible or row['state'] not in PAID_STATES:
        return {'ready': False, 'state': 'PAID_AWAITING_RESOLUTION'}
    return {'ready': True, 'state': row['state'], 'request_id': row['request_id'],
            'intake_token': row['intake_token'], 'revision': row['revision'],
            'approved_slot': row.get('approved_slot')}


@router.get('/success', response_class=HTMLResponse)
def success():
    return HTMLResponse(SUCCESS_HTML)


@router.post('/{request_id}/times')
def propose_times(request_id: str, payload: Proposals,
                  x_consultation_token: str | None = Header(default=None)):
    if not x_consultation_token:
        raise HTTPException(401, 'Invalid consultation token')
    slots = [slot.canonical() for slot in payload.slots]
    result = _operation(lambda store: store.propose_slots(request_id, x_consultation_token, slots, _product_id()))
    return {'request_id': request_id, **result, 'booking_confirmed': False}


@router.get('/internal/requests')
def internal_requests(x_consultation_admin_token: str | None = Header(default=None)):
    _admin(x_consultation_admin_token)
    return _operation(lambda store: store.pending_requests())


@router.post('/internal/{request_id}/approve')
def approve(request_id: str, payload: Approval,
            x_consultation_admin_token: str | None = Header(default=None)):
    _admin(x_consultation_admin_token)
    slot = payload.canonical()
    checked = payload.calendar_checked_at
    now = datetime.now(dt_timezone.utc)
    if not payload.calendar_available or checked.tzinfo is None or not timedelta(0) <= now - checked <= timedelta(minutes=5):
        raise HTTPException(422, 'A successful calendar conflict check within five minutes is required')
    result = _operation(lambda store: store.approve_slot(request_id, payload.revision, slot, checked, _product_id()))
    return {'request_id': request_id, **result, 'booking_confirmed': False,
            'next_step': 'Create the calendar appointment and verify the provider result before confirming'}


@router.post('/internal/{request_id}/calendar-confirmation')
def confirm_calendar(request_id: str, payload: CalendarConfirmation,
                     x_consultation_admin_token: str | None = Header(default=None)):
    _admin(x_consultation_admin_token)
    expected_calendar = os.getenv('CONSULTATION_GOOGLE_CALENDAR_ID')
    if not expected_calendar:
        raise HTTPException(503, 'Consultation calendar confirmation is not configured')
    if not payload.provider_result_verified or payload.calendar_id != expected_calendar:
        raise HTTPException(422, 'Verify the actual provider event in the configured host calendar')
    slot = payload.canonical()
    result = _operation(lambda store: store.confirm_calendar_event(request_id, payload.revision, slot,
                        payload.calendar_event_id, payload.calendar_id, _product_id()))
    return {'request_id': request_id, **result, 'booking_confirmed': True,
            'verification_source': 'authenticated_host_verified_provider_result'}


@router.post('/internal/sales/import')
def import_sale(payload: TrustedSale, x_consultation_admin_token: str | None = Header(default=None)):
    _admin(x_consultation_admin_token)
    if payload.product_id != _product_id():
        raise HTTPException(422, 'Unexpected qualifying product')
    _operation(lambda store: store.import_sale(payload.model_dump(mode='json'), 'trusted_operator_provider_read'))
    return {'accepted': True, 'sale_id': payload.sale_id}


class GumroadTrigger(BaseModel):
    sale_id: str = Field(min_length=1, max_length=200)
    product_id: str = Field(min_length=1, max_length=200)
    email: EmailStr
    order_number: str | None = Field(default=None, min_length=1, max_length=200)


def parse_gumroad_notification(fields: dict[str, str], resource: str):
    """Parse only lookup identity. An unsigned ping cannot attest payment state."""
    if resource not in ('sale', 'refund', 'dispute'):
        raise ValueError('Unsupported resource')
    if fields.get('resource_name') not in (None, '', resource):
        raise ValueError('Resource identity mismatch')
    return GumroadTrigger(sale_id=fields['sale_id'], product_id=fields['product_id'],
                          email=fields['email'], order_number=fields.get('order_number') or None)


def _api_flag(sale: dict, name: str):
    # Purchase#as_json omits nil fields. Only actual JSON booleans are accepted;
    # strings and other truthy values cannot become trusted financial evidence.
    value = sale.get(name, False)
    if type(value) is not bool:
        raise ValueError('Invalid provider state')
    return value


def _successful_sales_response(response: httpx.Response):
    """Require a successful seller API response and a well-formed sales list."""
    response.raise_for_status()
    body = response.json()
    if (not isinstance(body, dict) or body.get('success') is not True
            or not isinstance(body.get('sales'), list)
            or any(not isinstance(sale, dict) for sale in body['sales'])):
        raise ValueError('Provider successful-sale state not verified')
    return body['sales']


@router.get('/internal/gumroad-status')
async def gumroad_status(x_consultation_admin_token: str | None = Header(default=None)):
    """Verify credential access without disclosing the credential or buyer data."""
    _admin(x_consultation_admin_token)
    product_id = _product_id()
    token = os.getenv('CONSULTATION_GUMROAD_ACCESS_TOKEN')
    if not token:
        raise HTTPException(503, 'Verified Gumroad sale lookup is not configured')
    try:
        async with asyncio.timeout(3):
            async with httpx.AsyncClient(timeout=3, follow_redirects=False,
                                         headers={'Authorization': 'Bearer ' + token}) as client:
                response = await client.get('https://api.gumroad.com/v2/sales',
                                            params={'product_id': product_id})
                sales = _successful_sales_response(response)
                if any(sale.get('product_id') != product_id for sale in sales):
                    raise ValueError('Provider product scope not verified')
                count = sum(sale.get('paid') is True and type(sale.get('price')) is int
                            and sale['price'] > 0 and not _api_flag(sale, 'test')
                            and not _api_flag(sale, 'is_preorder_authorization')
                            and not _api_flag(sale, 'refunded')
                            and not _api_flag(sale, 'partially_refunded')
                            and not _api_flag(sale, 'disputed')
                            and not _api_flag(sale, 'chargedback') for sale in sales)
        # This count is for the first response page, never a lifetime total.
        return {'authenticated': True, 'product_scoped': True, 'successful_sale_count': count}
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError):
        raise HTTPException(503, 'Gumroad credential verification unavailable')


def _verified_api_sale(sale: dict, trigger: GumroadTrigger, resource: str, successful_ids: set[str]):
    if not isinstance(sale, dict) or sale.get('id') != trigger.sale_id:
        raise ValueError('Sale identity mismatch')
    if sale.get('product_id') != trigger.product_id:
        raise ValueError('Product identity mismatch')
    original_email = sale.get('purchase_email') or sale.get('email')
    emails = {str(sale.get('email') or '').casefold(), str(original_email or '').casefold()}
    if str(trigger.email).casefold() not in emails:
        raise ValueError('Purchase identity mismatch')
    order = sale.get('order_id')
    if isinstance(order, bool) or not isinstance(order, (str, int)) or not str(order).isdigit():
        raise ValueError('Missing provider order identity')
    if trigger.order_number is not None and str(order) != trigger.order_number:
        raise ValueError('Order identity mismatch')
    refunded = _api_flag(sale, 'refunded') or _api_flag(sale, 'partially_refunded')
    disputed = _api_flag(sale, 'disputed') or _api_flag(sale, 'chargedback')
    if resource == 'refund' and not refunded or resource == 'dispute' and not disputed:
        raise HTTPException(503, 'Provider revocation is not yet verified; retry notification')
    price = sale.get('price')
    successful = (trigger.sale_id in successful_ids and sale.get('paid') is True
                  and type(price) is int and price > 0
                  and not _api_flag(sale, 'test') and not _api_flag(sale, 'is_preorder_authorization'))
    return TrustedSale(sale_id=trigger.sale_id, product_id=trigger.product_id,
                       order_number=str(order), purchase_email=original_email,
                       payment_succeeded=successful, refunded=refunded, disputed=disputed)


async def fetch_verified_gumroad_sale(trigger: GumroadTrigger, resource: str):
    """Read the seller's sale and attest successful state through the scoped list.

    The show API also exposes failed/test rows. Its `paid` field only means a
    nonzero price. The successful-sales list excludes failed/test purchases;
    matching the same ID there is required before granting paid eligibility.
    Both reads share an overall three-second deadline. Credentials never enter
    a query string, log message, redirect, or returned provider error.
    """
    token = os.getenv('CONSULTATION_GUMROAD_ACCESS_TOKEN')
    if not token:
        raise HTTPException(503, 'Verified Gumroad sale lookup is not configured')
    try:
        async with asyncio.timeout(3):
            async with httpx.AsyncClient(timeout=3, follow_redirects=False,
                                         headers={'Authorization': 'Bearer ' + token}) as client:
                response = await client.get('https://api.gumroad.com/v2/sales/' + quote(trigger.sale_id, safe=''))
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict) or body.get('success') is not True or not isinstance(body.get('sale'), dict):
                    raise ValueError('Provider sale not verified')
                sale = body['sale']
                # Validate identity before using any provider values in a query.
                current = _verified_api_sale(sale, trigger, resource, set())
                if current.refunded or current.disputed:
                    # Revocation is established by the current seller-only API
                    # read; no success-list membership can restore this purchase.
                    return current
                listing = await client.get('https://api.gumroad.com/v2/sales', params={
                    'product_id': trigger.product_id, 'email': sale.get('purchase_email') or sale.get('email'),
                    'order_id': str(sale['order_id'])})
                listed = _successful_sales_response(listing)
                matches = [row for row in listed if row.get('id') == trigger.sale_id]
                successful_ids = {matches[0]['id']} if len(matches) == 1 else set()
                verified = _verified_api_sale(sale, trigger, resource, successful_ids)
                if matches:
                    latest = _verified_api_sale(matches[0], trigger, 'sale', successful_ids)
                    verified = verified.model_copy(update={
                        'payment_succeeded': verified.payment_succeeded and latest.payment_succeeded,
                        'refunded': verified.refunded or latest.refunded,
                        'disputed': verified.disputed or latest.disputed})
                if not verified.payment_succeeded and not verified.refunded and not verified.disputed:
                    raise HTTPException(503, 'Successful paid ebook purchase is not yet verified; retry notification')
                return verified
    except HTTPException:
        raise
    except (httpx.HTTPError, TimeoutError):
        raise HTTPException(503, 'Gumroad lookup unavailable; retry notification')
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, 'Provider response does not verify the qualifying purchase')


@router.post('/webhooks/gumroad/{resource}')
async def gumroad_webhook(resource: str, request: Request, token: str | None = None,
                          x_gumroad_webhook_token: str | None = Header(default=None)):
    expected = os.getenv('CONSULTATION_GUMROAD_WEBHOOK_TOKEN')
    supplied = x_gumroad_webhook_token or token or ''
    if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, 'Unauthorized')
    content_type = request.headers.get('content-type', '').split(';', 1)[0]
    if content_type != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Use provider form-encoded notifications')
    try:
        raw = await request.body()
        if len(raw) > 65536:
            raise ValueError('Payload too large')
        parsed = parse_qs(raw.decode('utf-8'), keep_blank_values=True, strict_parsing=True, max_num_fields=100)
        if any(len(values) != 1 for values in parsed.values()):
            raise ValueError('Repeated fields')
        trigger = parse_gumroad_notification({key: value[0] for key, value in parsed.items()}, resource)
    except (ValueError, UnicodeDecodeError, KeyError):
        raise HTTPException(422, 'Provider notification does not establish an eligible purchase')
    if trigger.product_id != _product_id():
        return {'received': True, 'ignored': True}
    payload = await fetch_verified_gumroad_sale(trigger, resource)
    try:
        # Gumroad has a five-second response limit. A slow database can finish
        # this idempotent import in its thread, while 503 prompts a safe retry.
        await asyncio.wait_for(asyncio.to_thread(_operation, lambda store:
            store.import_sale(payload.model_dump(mode='json'), 'verified_gumroad_api_readback')), timeout=1)
    except TimeoutError:
        raise HTTPException(503, 'Sale synchronization pending; retry notification')
    return {'received': True}
