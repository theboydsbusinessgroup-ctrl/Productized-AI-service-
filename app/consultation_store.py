"""Private durable consultation state. Never creates charges or appointments."""
import os
import secrets
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class ConsultationConflict(Exception):
    """An invalid or stale state transition; safe to disclose without PII."""


class PostgresConsultationStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=10)

    def healthcheck(self):
        with self._connect() as conn:
            conn.execute('select sale_id from public.boyds_consultation_sales limit 0')
            conn.execute('select request_id from public.boyds_consultations limit 0')
            conn.execute('select event_id from public.boyds_consultation_payment_receipts limit 0')
            return True

    @staticmethod
    def _eligible(sale: dict | None, product_id: str, email: str) -> bool:
        return bool(sale and sale['product_id'] == product_id and
                    sale['purchase_email'] == email.casefold() and
                    sale['payment_succeeded'] and not sale['refunded'] and not sale['disputed'])

    def import_sale(self, sale: dict[str, Any], source: str):
        with self._connect() as conn:
            # Revocation is monotonic: a delayed purchase notification cannot
            # restore a refunded/disputed purchase or revive an approved slot.
            row = conn.execute('''insert into public.boyds_consultation_sales
                (sale_id,order_number,product_id,purchase_email,payment_succeeded,refunded,disputed,source)
                values (%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict(sale_id) do update set
                  payment_succeeded=boyds_consultation_sales.payment_succeeded and excluded.payment_succeeded,
                  refunded=boyds_consultation_sales.refunded or excluded.refunded,
                  disputed=boyds_consultation_sales.disputed or excluded.disputed,
                  order_number=coalesce(boyds_consultation_sales.order_number,excluded.order_number),
                  source=excluded.source,observed_at=now()
                where boyds_consultation_sales.product_id=excluded.product_id
                  and boyds_consultation_sales.purchase_email=excluded.purchase_email
                returning *''', (sale['sale_id'], sale.get('order_number'), sale['product_id'], sale['purchase_email'].casefold(),
                    sale['payment_succeeded'], sale['refunded'], sale['disputed'], source)).fetchone()
            if not row:
                raise ConsultationConflict('Sale identity conflicts with trusted records')
            if not row['payment_succeeded'] or row['refunded'] or row['disputed']:
                conn.execute('''update public.boyds_consultations
                    set state=case when paid_at is not null then 'PAID_AWAITING_RESOLUTION' else state end,
                    approved_slot=null,approved_by=null,approved_at=null,calendar_check_at=null,
                    revision=revision+1,updated_at=now() where sale_id=%s''', (sale['sale_id'],))
            return dict(row)

    def create_request(self, sale_id: str, email: str, product_id: str):
        with self._connect() as conn:
            # Lock the qualifying purchase before inspecting its single redemption.
            matches = conn.execute('''select * from public.boyds_consultation_sales
                where sale_id=%s or order_number=%s for update''', (sale_id, sale_id)).fetchall()
            sale = matches[0] if len(matches) == 1 else None
            if not self._eligible(sale, product_id, email):
                raise ConsultationConflict('Verified qualifying ebook purchase required')
            sale_id = sale['sale_id']
            current = conn.execute('select * from public.boyds_consultations where sale_id=%s',
                                   (sale_id,)).fetchone()
            if current:
                if current['state'] != 'CHECKOUT_PENDING' or current['paid_at']:
                    raise ConsultationConflict('This purchase already has a consultation request')
                return dict(current)
            row = conn.execute('''insert into public.boyds_consultations
                (request_id,sale_id,customer_email,state) values (%s,%s,%s,'CHECKOUT_PENDING') returning *''',
                ('con_' + secrets.token_urlsafe(18), sale_id, email.casefold())).fetchone()
            return dict(row)

    def record_payment(self, event: dict, product_id: str, rejection: str | None = None):
        session = event['data']['object']
        session_id = session['id']
        reference = session.get('client_reference_id')
        email = str((session.get('customer_details') or {}).get('email') or '').casefold()
        intent = session.get('payment_intent')
        if isinstance(intent, dict):
            intent = intent.get('id')
        with self._connect() as conn:
            self._lock_payment_intent(conn, intent)
            existing = conn.execute('select * from public.boyds_consultation_payment_receipts where event_id=%s',
                                    (event['id'],)).fetchone()
            if existing:
                return {'duplicate': True, 'state': existing['resolution_state'], 'reason': existing['reason']}
            request = None
            if reference:
                # Lock the sale before the request, matching import/proposal/approval lock order.
                identity = conn.execute('select sale_id from public.boyds_consultations where request_id=%s',
                                        (reference,)).fetchone()
                if identity:
                    sale = conn.execute('select * from public.boyds_consultation_sales where sale_id=%s for update',
                                        (identity['sale_id'],)).fetchone()
                    request = conn.execute('select * from public.boyds_consultations where request_id=%s for update',
                                           (reference,)).fetchone()
            reason = rejection
            if not reason:
                if not request:
                    reason = 'unknown_or_missing_reference'
                elif request['customer_email'] != email:
                    reason = 'payment_email_mismatch'
                elif not self._eligible(sale, product_id, email):
                    reason = 'purchase_not_eligible'
                elif intent and conn.execute('''select 1 from public.boyds_consultation_payment_receipts
                    where payment_intent_id=%s and resolution_state='REVOKED' limit 1''', (intent,)).fetchone():
                    reason = 'payment_already_refunded_or_disputed'
                elif request['stripe_session_id'] and request['stripe_session_id'] != session_id:
                    reason = 'additional_payment_requires_resolution'
                elif request['state'] != 'CHECKOUT_PENDING' and request['stripe_session_id'] != session_id:
                    reason = 'request_not_payable'
            state = 'REJECTED' if rejection else ('UNMATCHED' if reason else 'MATCHED')
            attached = request['request_id'] if request else None
            # A unique event insert is also the concurrency guard. PostgreSQL waits
            # for a racing insert; the loser must not grant a second entitlement.
            inserted = conn.execute('''insert into public.boyds_consultation_payment_receipts
                (event_id,session_id,payment_intent_id,request_id,claimed_reference,customer_email,
                amount_cents,currency,livemode,event_type,resolution_state,reason)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict(event_id) do nothing returning event_id''',
                (event['id'], session_id, intent, attached, reference, email,
                 session.get('amount_total'), session.get('currency'), event.get('livemode'),
                 event['type'], state, reason)).fetchone()
            if not inserted:
                return {'duplicate': True, 'state': state, 'reason': reason}
            if not reason:
                conn.execute('''update public.boyds_consultations set
                    state='PAID_AWAITING_SCHEDULING',stripe_session_id=%s,payment_intent_id=%s,
                    intake_token=%s,paid_at=now(),payment_valid=true,updated_at=now()
                    where request_id=%s and state='CHECKOUT_PENDING' ''',
                    (session_id, intent, secrets.token_urlsafe(32), attached))
            return {'duplicate': False, 'state': state, 'reason': reason}

    @staticmethod
    def _lock_payment_intent(conn, intent: str | None):
        # An unpaid request has no PI yet, so a request-row lock alone cannot
        # serialize an early refund with its first successful payment event.
        # Both handlers take this transaction lock before inspecting receipts.
        if intent:
            conn.execute('select pg_advisory_xact_lock(hashtextextended(%s, 0))',
                         ('boyds-consultation-payment:' + intent,))

    def revoke_payment(self, event: dict):
        obj = event['data']['object']
        intent = obj.get('payment_intent')
        if isinstance(intent, dict):
            intent = intent.get('id')
        if not intent:
            return {'ignored': True, 'reason': 'missing_payment_intent'}
        is_refund = event['type'] == 'charge.refunded'
        amount = obj.get('amount_refunded') if is_refund else None
        currency = str(obj.get('currency') or '').lower() if is_refund else None
        amount = amount if type(amount) is int and amount >= 0 else None
        full_refund = is_refund and amount == 1900 and currency == 'usd'
        reason = ('refunded' if full_refund else 'refund_partial_or_unknown') if is_refund else 'disputed'
        with self._connect() as conn:
            self._lock_payment_intent(conn, intent)
            inserted = conn.execute('''insert into public.boyds_consultation_payment_receipts
                (event_id,payment_intent_id,amount_cents,currency,livemode,event_type,resolution_state,reason)
                values (%s,%s,%s,%s,%s,%s,'REVOKED',%s) on conflict(event_id) do nothing returning event_id''',
                (event['id'], intent, amount, currency, event.get('livemode'), event['type'], reason)).fetchone()
            if inserted:
                # Stripe refund amounts are cumulative. A delayed partial event
                # cannot reopen a full refund already confirmed by the provider.
                prior_full = is_refund and conn.execute('''select 1 from public.boyds_consultation_payment_receipts
                    where payment_intent_id=%s and event_type='charge.refunded'
                    and resolution_state='REVOKED' and amount_cents=1900 and currency='usd' limit 1''',
                    (intent,)).fetchone()
                state = ('REFUNDED' if prior_full else 'PAID_AWAITING_RESOLUTION') if is_refund else 'DISPUTED'
                conn.execute('''update public.boyds_consultations set payment_valid=false,state=%s,
                    approved_slot=null,approved_by=null,approved_at=null,calendar_check_at=null,
                    revision=revision+1,updated_at=now() where payment_intent_id=%s''', (state, intent))
            return {'duplicate': not bool(inserted), 'revoked': True}

    def get_by_session(self, session_id: str):
        with self._connect() as conn:
            row = conn.execute('''select c.*,s.product_id,s.purchase_email,s.payment_succeeded,s.refunded,s.disputed
                from public.boyds_consultations c join public.boyds_consultation_sales s using(sale_id)
                where stripe_session_id=%s''', (session_id,)).fetchone()
            return dict(row) if row else None

    def _lock_paid_request(self, conn, request_id: str, product_id: str):
        identity = conn.execute('select sale_id from public.boyds_consultations where request_id=%s',
                                (request_id,)).fetchone()
        if not identity:
            raise ConsultationConflict('Consultation request not found')
        sale = conn.execute('select * from public.boyds_consultation_sales where sale_id=%s for update',
                            (identity['sale_id'],)).fetchone()
        row = conn.execute('select * from public.boyds_consultations where request_id=%s for update',
                           (request_id,)).fetchone()
        if not row['payment_valid'] or not row['paid_at'] or not self._eligible(sale, product_id, row['customer_email']):
            raise ConsultationConflict('Verified payment and eligible purchase required')
        return row

    def propose_slots(self, request_id: str, token: str, slots: list[dict], product_id: str):
        with self._connect() as conn:
            row = self._lock_paid_request(conn, request_id, product_id)
            if not row['intake_token'] or not secrets.compare_digest(token.encode(), row['intake_token'].encode()):
                raise PermissionError('Invalid consultation token')
            if row['state'] not in ('PAID_AWAITING_SCHEDULING','TIMES_PROPOSED','APPROVED_AWAITING_CALENDAR'):
                raise ConsultationConflict('Consultation cannot accept new proposed times')
            updated = conn.execute('''update public.boyds_consultations set state='TIMES_PROPOSED',
                proposed_slots=%s,revision=revision+1,approved_slot=null,approved_by=null,
                approved_at=null,calendar_check_at=null,updated_at=now()
                where request_id=%s returning revision,state''', (Jsonb(slots), request_id)).fetchone()
            return dict(updated)

    def approve_slot(self, request_id: str, revision: int, slot: dict, checked_at, product_id: str):
        with self._connect() as conn:
            row = self._lock_paid_request(conn, request_id, product_id)
            if row['revision'] != revision or row['state'] != 'TIMES_PROPOSED':
                raise ConsultationConflict('Request changed; approve the current revision')
            if slot not in row['proposed_slots']:
                raise ConsultationConflict('Approve an exact slot from the current proposals')
            updated = conn.execute('''update public.boyds_consultations set state='APPROVED_AWAITING_CALENDAR',
                approved_slot=%s,approved_by='Eric Boyd',approved_at=now(),calendar_check_at=%s,updated_at=now()
                where request_id=%s returning state,revision,approved_slot''',
                (Jsonb(slot), checked_at, request_id)).fetchone()
            return dict(updated)

    def pending_requests(self):
        with self._connect() as conn:
            rows = conn.execute('''select request_id,customer_email,state,revision,proposed_slots,
                approved_slot,paid_at from public.boyds_consultations
                where paid_at is not null and state not in ('COMPLETED','REFUNDED') order by created_at limit 100''').fetchall()
            unresolved = conn.execute('''select event_id,session_id,claimed_reference,customer_email,
                amount_cents,currency,reason,received_at from public.boyds_consultation_payment_receipts
                where resolution_state in ('UNMATCHED','REJECTED') order by received_at limit 100''').fetchall()
            return {'requests': [dict(row) for row in rows], 'unresolved_payments': [dict(row) for row in unresolved]}

    def confirm_calendar_event(self, request_id: str, revision: int, slot: dict,
                               event_id: str, calendar_id: str, product_id: str):
        with self._connect() as conn:
            row = self._lock_paid_request(conn, request_id, product_id)
            if row['revision'] != revision or row['approved_slot'] != slot:
                raise ConsultationConflict('Calendar event does not match the approved request and slot')
            if row['state'] == 'BOOKED':
                if row['calendar_event_id'] == event_id and row['calendar_id'] == calendar_id:
                    return {'state': 'BOOKED', 'duplicate': True}
                raise ConsultationConflict('A different calendar event is already recorded')
            if row['state'] != 'APPROVED_AWAITING_CALENDAR':
                raise ConsultationConflict('Exact host approval is required before calendar confirmation')
            conn.execute('''update public.boyds_consultations set state='BOOKED',calendar_event_id=%s,
                calendar_id=%s,calendar_verified_at=now(),
                calendar_verification_source='authenticated_host_verified_provider_result',updated_at=now()
                where request_id=%s''', (event_id, calendar_id, request_id))
            return {'state': 'BOOKED', 'duplicate': False}


_store = None


def get_consultation_store():
    global _store
    if _store is None:
        url = os.getenv('DATABASE_URL')
        if not url:
            raise RuntimeError('Consultation database is not configured')
        _store = PostgresConsultationStore(url)
    return _store


def set_consultation_store_for_tests(store):
    global _store
    _store = store
