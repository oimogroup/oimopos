from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app import payroll, pnl
from app.workspace import WorkspaceError, apply_action, default_state, visible_state

OWNER = {'id': 99, 'role': 'owner', 'display_name': 'Owner', 'login': 'owner'}


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(payroll, 'now', lambda: datetime(2026, 11, 30, 12, tzinfo=timezone.utc))
    state = default_state()
    def run(action, **payload):
        return apply_action(state, OWNER, action, {'requestId': str(uuid4()), **payload})
    return state, run


def expense(run, **values):
    return run('pnl.expense.create', **{'start': '2026-10-01', 'end': '2026-10-31', 'amount': 3100, 'categoryId': 'finance-expense-rent', 'reason': 'October rent', **values})[1]


def transaction(run, **values):
    return run('finance.transaction.create', **{'type': 'expense', 'occurredAt': '2026-11-05', 'amount': 100, 'accountId': 'finance-bank', 'categoryId': 'finance-expense-utilities', **values})


def test_unpaid_expense_is_allocated_by_recognition_period(setup):
    state, run = setup
    expense(run)
    assert pnl.report(state, '2026-10-01', '2026-10-31')['expenses'] == 3100
    assert pnl.report(state, '2026-10-10', '2026-10-15')['expenses'] == 600
    assert pnl.report(state, '2026-11-01', '2026-11-30')['expenses'] == 0
    assert state['financeState']['transactions'] == []


def test_allocation_preserves_cents_between_adjacent_periods(setup):
    state, run = setup
    expense(run, amount=100, start='2026-10-31', end='2026-11-02')
    october = pnl.report(state, '2026-10-31', '2026-10-31')['expenses']
    november = pnl.report(state, '2026-11-01', '2026-11-02')['expenses']
    assert october == 33.33 and november == 66.67


def test_late_payment_and_reversal_change_cash_without_changing_pnl(setup):
    state, run = setup
    identifier = expense(run)
    _, payment = run('pnl.pay', expenseId=identifier, amount=1000, accountId='finance-bank', reason='First payment')
    assert pnl.paid(state, identifier) == 1000
    assert pnl.report(state, '2026-10-01', '2026-10-31')['expenses'] == 3100
    assert pnl.report(state, '2026-11-01', '2026-11-30')['net'] == 0
    with pytest.raises(WorkspaceError):
        run('pnl.expense.void', expenseId=identifier, reason='Cancel document')
    run('pnl.reverse', expenseId=identifier, paymentId=payment, accountId='finance-bank', reason='Money returned')
    assert pnl.paid(state, identifier) == 0
    assert sum(t['amount'] * (-1 if t['type'] == 'expense' else 1) for t in state['financeState']['transactions']) == 0
    assert pnl.report(state, '2026-11-01', '2026-11-30')['otherIncome'] == 0
    run('pnl.expense.void', expenseId=identifier, reason='Wrong document')
    report = pnl.report(state, '2026-10-01', '2026-10-31')
    assert report['expenses'] == 0 and report['documents'][0]['voidedAt']
    with pytest.raises(WorkspaceError):
        run('finance.transaction.delete', id=state['financeState']['transactions'][0]['id'])


def test_replay_overpay_conflicting_reuse_and_failure_atomicity(setup):
    state, run = setup
    identifier = expense(run, amount=100)
    payload = {'requestId': 'same-request', 'expenseId': identifier, 'amount': 60, 'accountId': 'finance-bank', 'reason': 'Payment'}
    first = apply_action(state, OWNER, 'pnl.pay', payload)
    assert apply_action(state, OWNER, 'pnl.pay', payload) == first
    assert len(state['pnlState']['payments']) == 1
    before = deepcopy(state)
    with pytest.raises(WorkspaceError):
        apply_action(state, OWNER, 'pnl.pay', {**payload, 'amount': 61})
    with pytest.raises(WorkspaceError):
        run('pnl.pay', **{**payload, 'requestId': 'new-request', 'amount': 50})
    assert state == before


def test_payroll_is_expensed_when_earned_and_never_again_when_paid(setup):
    state, run = setup
    state['payrollState'] = {'policies': [{'id': 'rate', 'sequence': 1, 'employeeId': '1', 'employeeName': 'Anna', 'branchId': 'b1', 'effectiveFrom': '2026-10-01', 'fixedMode': 'month', 'fixedAmount': 3100}], 'workShifts': [], 'events': [], 'runs': [], 'payments': [], 'requests': []}
    report = pnl.report(state, '2026-10-01', '2026-10-31')
    assert report['expenses'] == 3100
    state['financeState']['transactions'] += [
        {'type': 'expense', 'amount': 3100, 'sourceType': 'payroll.pay', 'occurredAt': '2026-11-05', 'categoryId': 'finance-expense-payroll'},
        {'type': 'expense', 'amount': 100, 'sourceType': 'payroll.advance', 'occurredAt': '2026-11-06', 'categoryId': 'finance-expense-payroll'},
        {'type': 'income', 'amount': 100, 'sourceType': 'payroll.reverse', 'occurredAt': '2026-11-07', 'categoryId': 'finance-income-payroll-refunds'},
    ]
    assert pnl.report(state, '2026-11-01', '2026-11-30')['expenses'] == 3100
    assert pnl.report(state, '2026-11-01', '2026-11-30')['otherIncome'] == 0


def test_financial_transactions_dates_equity_purchases_and_tax(setup):
    state, run = setup
    transaction(run, recognitionDate='2026-10-31')
    transaction(run, type='income', categoryId='finance-income-other', amount=50000, affectsProfit=False)
    transaction(run, categoryId='finance-expense-taxes', amount=200)
    state['financeState']['transactions'].append({'type': 'expense', 'amount': 9999, 'categoryId': 'finance-expense-purchases', 'occurredAt': '2026-11-05'})
    state['financeState']['transactions'].append({'type': 'income', 'amount': 9999, 'categoryId': 'finance-income-supplier-refunds', 'occurredAt': '2026-11-05'})
    assert pnl.report(state, '2026-10-01', '2026-10-31')['expenses'] == 100
    november = pnl.report(state, '2026-11-01', '2026-11-30')
    assert november['expenses'] == 200 and november['otherIncome'] == 0 and november['net'] == -200


def test_sales_refunds_snapshot_cost_and_consumed_food(setup):
    state, _ = setup
    state['products'] = [{'id': 'water', 'cost': 999}]
    state['sales'] = [{'id': 's1', 'branchId': 'b1', 'createdAt': '2026-10-20T22:00:00Z', 'refundedAt': '2026-11-05T00:00:00Z', 'total': 1000, 'items': [{'id': 'water', 'quantity': 2, 'unitCost': 50}, {'id': 'soup', 'quantity': 1, 'unitCost': 200, 'ingredientAllocations': [{'itemId': 1}]}]}]
    october = pnl.report(state, '2026-10-01', '2026-10-31')
    november = pnl.report(state, '2026-11-01', '2026-11-30')
    assert (october['revenue'], october['cost'], october['gross']) == (1000, 300, 700)
    assert (november['revenue'], november['cost'], november['gross']) == (-1000, -100, -900)
    assert pnl.report(state, '2026-10-21', '2026-10-21')['revenue'] == 1000


def test_missing_cost_is_explicit_instead_of_current_catalog_price(setup):
    state, _ = setup
    state['sales'] = [{'id': 'legacy', 'branchId': 'b1', 'createdAt': '2026-10-01', 'total': 100, 'items': [{'id': 1, 'quantity': 1}]}]
    report = pnl.report(state, '2026-10-01', '2026-10-31')
    assert report['cost'] == 0 and any('себестоимости' in w for w in report['warnings'])


def test_inventory_losses_and_approved_food_writeoff_are_counted_once(setup):
    state, _ = setup
    state['logisticsState']['stockLedger'] = [
        {'branchId': 'b1', 'movementType': 'inventory_adjustment', 'quantity': -2, 'unitCost': 50, 'createdAt': '2026-11-01', 'effectiveAt': '2026-10-31'},
        {'branchId': 'b1', 'movementType': 'inventory_adjustment', 'quantity': 1, 'unitCost': 10, 'createdAt': '2026-10-31'},
        {'branchId': 'b1', 'movementType': 'production_consumption', 'quantity': -10, 'unitCost': 50, 'createdAt': '2026-10-31'},
    ]
    state['logisticsState']['custodyDocuments'] = [
        {'branchId': 'b1', 'kind': 'writeoff', 'status': 'approved', 'costAmount': 200, 'createdAt': '2026-10-31', 'reviewedAt': '2026-11-01'},
        {'branchId': 'b1', 'kind': 'writeoff', 'status': 'pending', 'costAmount': 9999, 'createdAt': '2026-10-31'},
        {'branchId': 'b1', 'kind': 'count', 'status': 'review', 'variance': -1, 'costPerKg': 20, 'createdAt': '2026-10-31'},
    ]
    october = pnl.report(state, '2026-10-01', '2026-10-31')
    november = pnl.report(state, '2026-11-01', '2026-11-30')
    assert october['expenses'] == 120 and october['otherIncome'] == 10
    assert any('витрины на проверке' in w for w in october['warnings'])
    assert november['expenses'] == 200


def test_branch_isolation_shared_cost_and_salary(setup):
    state, run = setup
    expense(run, branchId='b1', amount=100)
    expense(run, amount=50)
    state['payrollState'] = {'policies': [{'id': 'rate', 'sequence': 1, 'employeeId': '1', 'employeeName': 'Anna', 'branchId': 'b2', 'effectiveFrom': '2026-10-01', 'fixedMode': 'month', 'fixedAmount': 3100}], 'events': []}
    branch = pnl.report(state, '2026-10-01', '2026-10-31', 'b1')
    assert branch['expenses'] == 100 and len(branch['documents']) == 1
    assert any('Общие расходы' in w for w in branch['warnings'])
    assert pnl.report(state, '2026-10-01', '2026-10-31')['expenses'] == 3250
    with pytest.raises(WorkspaceError):
        pnl.report(state, '2026-10-01', '2026-10-31', 'another-tenant')


@pytest.mark.parametrize('values', [{'amount': -1}, {'amount': 'NaN'}, {'amount': 1.001}, {'end': '2026-09-01'}, {'categoryId': 'finance-expense-payroll'}, {'categoryId': 'finance-expense-purchases'}, {'branchId': 'other-tenant'}, {'start': 'bad'}])
def test_invalid_expenses_are_atomic(setup, values):
    state, run = setup
    before = deepcopy(state)
    with pytest.raises(WorkspaceError):
        expense(run, **values)
    assert before == state


def test_permissions_privacy_and_future_report(setup):
    state, run = setup
    expense(run)
    branch = {'id': 2, 'role': 'branch', 'branch_id': 'b1', 'display_name': 'Cashier', 'login': 'branch'}
    with pytest.raises(WorkspaceError):
        apply_action(state, branch, 'pnl.expense.create', {'requestId': 'new'})
    assert 'pnlState' not in visible_state(state, branch)
    with pytest.raises(WorkspaceError):
        pnl.report(state, '2026-11-01', '2026-12-31')
    from app.main import pnl_report
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        pnl_report('2026-10-01', '2026-10-31', user=branch, connection=None)
    assert error.value.status_code == 403
