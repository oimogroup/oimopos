"""Regressions for cross-document accounting and access boundaries."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from app import main
from app.workspace import apply_action, default_state, WorkspaceError, _set_stock
from test_workspace import OWNER, BRANCH, POS_MANAGER
from test_custody import setup, send, accept, RECEIVER


def supply(state, user=BRANCH, **extra):
    _, key = apply_action(state, user, 'supply.create', {
        'supplierId': 'supplier-frunze',
        'items': [{'itemId': 'rice', 'quantity': .333, 'price': 1.01}], **extra,
    })
    return next(s for s in state['logisticsState']['supplies'] if s['id'] == key)


def test_fractional_supply_can_be_paid_in_full_and_retry_is_validated():
    state = default_state()
    doc = supply(state)
    assert doc['total'] == doc['debt'] == .34
    payment = {'id': doc['id'], 'amount': .34, 'accountId': 'finance-bank', 'requestId': 'pay'}
    apply_action(state, OWNER, 'supply.pay', payment)
    apply_action(state, OWNER, 'supply.pay', payment)
    assert doc['debt'] == 0 and doc['paymentStatus'] == 'paid'
    assert len(doc['payments']) == 1
    with pytest.raises(WorkspaceError, match='другого платежа'):
        apply_action(state, OWNER, 'supply.pay', {**payment, 'amount': .33})
    transaction = next(t for t in state['financeState']['transactions'] if t.get('documentId') == doc['id'])
    with pytest.raises(WorkspaceError, match='связана с документом'):
        apply_action(state, OWNER, 'finance.transaction.delete', {'id': transaction['id']})
    assert transaction in state['financeState']['transactions']


def test_supplier_cash_expense_links_to_shift_once_without_duplicate_finance_expense():
    state = default_state()
    doc = supply(state, POS_MANAGER, payments=[{'accountId': 'finance-cash-b1', 'amount': .34}])
    cash = [m for m in state['posState']['cashMovements'] if m.get('documentId') == doc['id']]
    assert len(cash) == 1
    assert cash[0]['amount'] == .34 and cash[0]['type'] == 'expense'
    assert cash[0]['shiftId'] == POS_MANAGER['shift_id']
    assert cash[0]['registerId'] == POS_MANAGER['register_id']
    assert len([t for t in state['financeState']['transactions'] if t.get('documentId') == doc['id']]) == 1


def test_cash_payment_without_register_shift_does_not_change_stock():
    state = default_state()
    stocks = deepcopy(state['logisticsState']['branchStocks'])
    with pytest.raises(WorkspaceError, match='открытой смене'):
        supply(state, payments=[{'accountId': 'finance-cash-b1', 'amount': .34}])
    assert state['logisticsState']['branchStocks'] == stocks
    assert not state['logisticsState']['supplies']


@pytest.mark.parametrize('action', ['inventory.post', 'inventory.return'])
def test_branch_company_write_permission_cannot_approve_inventory(action):
    state = default_state()
    _, key = apply_action(state, BRANCH, 'inventory.start', {'scope': 'selected', 'itemIds': ['rice']})
    apply_action(state, BRANCH, 'inventory.submit', {'id': key, 'items': [{'itemId': 'rice', 'actual': 68}]})
    with pytest.raises(WorkspaceError) as error:
        apply_action(state, {**BRANCH, '_company_write': True}, action, {'id': key, 'comment': 'review'})
    assert error.value.status_code == 403


def test_inventory_blocks_refunds_before_any_mutation():
    state = default_state()
    _, key = apply_action(state, POS_MANAGER, 'sale.create', {'items': [{'id': 'p-1', 'quantity': 1}], 'paymentMethod': 'card'})
    apply_action(state, BRANCH, 'inventory.start', {'scope': 'selected', 'itemIds': ['p-1']})
    before = deepcopy(state)
    with pytest.raises(WorkspaceError, match='инвентаризация'):
        apply_action(state, POS_MANAGER, 'sale.refund', {'id': key, 'reason': 'refund'})
    assert state == before


@pytest.mark.parametrize('action', ['custody.writeoff', 'pos.serving.writeoff', 'pos.serving.surplus'])
def test_serving_inventory_locks_lot_changes(action):
    state, batch, _ = setup()
    accept(state, send(state, batch))
    apply_action(state, BRANCH, 'inventory.start', {'scope': 'serving'})
    before = deepcopy(state)
    with pytest.raises(WorkspaceError, match='инвентаризация'):
        apply_action(state, {**RECEIVER, 'shift_id': 5}, action, {
            'batchId': batch['id'], 'lotId': batch['servingLots'][0]['id'],
            'weight': .1, 'reason': 'test', 'requestId': action,
        })
    assert state == before


def test_historical_count_uses_receipt_date_including_legacy_ledger():
    from app.inventory_count import build
    state = default_state()
    _set_stock(state, 'b1', 'rice', 0)
    now = datetime.now(timezone.utc)
    received_at = (now - timedelta(days=2)).isoformat()
    doc = supply(state, receivedAt=received_at)
    payload = {'scope': 'selected', 'itemIds': ['rice'], 'countedAt': (now - timedelta(days=1)).isoformat()}
    assert state['logisticsState']['stockLedger'][0]['effectiveAt'] == received_at
    assert build(state, 'b1', payload, state['ingredients'])[0][0]['book'] == .333
    del state['logisticsState']['stockLedger'][0]['effectiveAt']
    assert build(state, 'b1', payload, state['ingredients'])[0][0]['book'] == .333
    assert doc['receivedAt'] == received_at


def test_hidden_fraction_does_not_create_inventory_shortage():
    state = default_state()
    _set_stock(state, 'b1', 'rice', 5.42604)
    _, key = apply_action(state, BRANCH, 'inventory.start', {'scope': 'selected', 'itemIds': ['rice']})
    apply_action(state, BRANCH, 'inventory.submit', {'id': key, 'items': [{'itemId': 'rice', 'actual': 5.426}]})
    apply_action(state, OWNER, 'inventory.post', {'id': key})
    assert state['logisticsState']['branchStocks']['b1']['rice'] == 5.42604
    assert not state['logisticsState']['stockLedger']


def test_pos_supply_context_filters_branch_before_limit(monkeypatch):
    state = default_state()
    state['logisticsState']['supplies'] = [{'id': str(i), 'branchId': 'b2'} for i in range(25)] + [{'id': 'own', 'branchId': 'b1'}]
    monkeypatch.setattr(main, '_current_pos_operator', lambda *a: {**BRANCH, 'staff_role': 'production'})
    monkeypatch.setattr(main, '_has_permission', lambda *a: True)
    monkeypatch.setattr(main, '_workspace_row', lambda *a: {'payload': state})
    context = main.pos_supply_context(None, {**BRANCH, 'tenant_id': 'test'}, None)
    assert [s['id'] for s in context['supplies']] == ['own']
    assert all(a['type'] != 'cash' for a in context['accounts'])


def test_cash_shift_cannot_close_during_inventory(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request
    from app.schemas import PosShiftClose
    state = default_state()
    apply_action(state, BRANCH, 'inventory.start', {'scope': 'selected', 'itemIds': ['rice']})
    monkeypatch.setattr(main, '_check_origin', lambda *a: None)
    monkeypatch.setattr(main, '_workspace_row', lambda *a, **k: {'payload': state, 'version': 1})
    monkeypatch.setattr(main, '_current_pos_operator', lambda *a: POS_MANAGER)
    monkeypatch.setattr(main, '_current_pos_shift', lambda *a: {'id': 20})
    before = deepcopy(state)
    with pytest.raises(HTTPException) as error:
        main.close_pos_shift(PosShiftClose(closing_cash=0, state_version=1, stock_confirmed=True),
            Request({'type': 'http', 'headers': []}), None, {**BRANCH, 'tenant_id': 'test'}, None)
    assert error.value.status_code == 409 and 'инвентаризация' in error.value.detail
    assert state == before
