from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.reconciliation import reconcile_stripe


class Store:
    def __init__(self):self.saved=[]
    @contextmanager
    def _connect(self):yield self
    def execute(self,query,params):self.saved.append(params[0].obj)


def row(amount,fee,kind='charge',status='available',id='txn_1',currency='usd'):
    return SimpleNamespace(id=id,amount=amount,fee=fee,net=amount-fee,type=kind,status=status,currency=currency)


def test_reconcile_paginates_and_keeps_refunds_fees_and_pending_separate(monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY','_'.join(['rk','live','testfixture']))
    store=Store()
    with patch('app.reconciliation.stripe.StripeClient') as client:
        listing=client.return_value.v1.balance_transactions.list
        listing.side_effect=[SimpleNamespace(data=[row(4900,180)],has_more=True),
            SimpleNamespace(data=[row(-1000,0,'refund'),row(4900,180,status='pending')],has_more=False)]
        result=reconcile_stripe(store)
        assert listing.call_args_list[1].args[0]['starting_after']=='txn_1'
    assert result['captured_cents']==9800
    assert result['refund_cents']==1000
    assert result['fees_cents']==360
    assert result['pending_net_cents']==4720
    assert result['available_net_cents']==3720
    assert result['contribution_cents'] is None
    assert len(store.saved)==1


def test_partial_or_mixed_currency_result_never_replaces_last_snapshot(monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY','_'.join(['rk','live','testfixture']))
    store=Store()
    with patch('app.reconciliation.stripe.StripeClient') as client:
        client.return_value.v1.balance_transactions.list.return_value=SimpleNamespace(data=[row(500,10,currency='eur')],has_more=False)
        with pytest.raises(RuntimeError):reconcile_stripe(store)
    assert not store.saved
