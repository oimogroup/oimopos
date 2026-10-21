from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import payroll, main
from app.workspace import default_state, apply_action, visible_state, WorkspaceError


@pytest.fixture
def setup(monkeypatch):
    state = default_state()
    current = [datetime(2026, 10, 1, 5, tzinfo=timezone.utc)]
    monkeypatch.setattr(payroll, 'now', lambda: current[0])
    from app import workspace
    monkeypatch.setattr(workspace, '_now', lambda: current[0].isoformat())
    roster = [{'id': i, 'display_name': f'Employee {i}', 'staff_role': 'waiter', 'branch_id': 'b1', 'is_active': True} for i in (1, 2)]
    owner = {'id': 99, 'role': 'owner', 'login': 'owner', 'display_name': 'Owner', '_payroll_employees': roster, '_workspace_version': 1}
    def run(action, **payload):
        payload.setdefault('requestId', str(uuid4()))
        return apply_action(state, owner, action, payload)
    def policy(employee=1, **values):
        effective = values.pop('effectiveFrom', payroll.today(state).isoformat())
        return run('payroll.policy', employeeId=employee, effectiveFrom=effective, **values)
    return state, current, owner, run, policy


def sale(id='sale-1', **values):
    return {'id': id, 'createdAt': '2026-10-01T06:00:00+00:00', 'branchId': 'b1', 'subtotal': 200, 'discountAmount': 20, 'serviceAmount': 18, 'deliveryAmount': 10, 'total': 208, 'items': [{'category': 'Горячее', 'price': 100, 'quantity': 2}], **values}


def test_percentage_excludes_service_delivery_and_respects_discount(setup):
    state, _, _, _, policy = setup
    policy(personalPercent=10)
    entry = sale()
    payroll.record_sale(state, entry, 1)
    assert entry['payrollAccruals'][0]['amount'] == 18
    assert payroll.report(state, '2026-10-01', '2026-10-01')['rows'][0]['total'] == 18


def test_category_rates_and_no_discount_item(setup):
    state, _, _, _, policy = setup
    policy(personalPercent=10, categoryRates={'Горячее': {'personal': 0}})
    entry = sale(subtotal=200, discountAmount=50, items=[{'category': 'Горячее', 'price': 100, 'quantity': 1}, {'category': 'Напитки', 'price': 100, 'quantity': 1, 'noDiscount': True}])
    payroll.record_sale(state, entry, 1)
    assert entry['payrollAccruals'][0]['amount'] == 10


def test_service_percentage_is_explicit_and_separate(setup):
    state, _, _, _, policy = setup
    policy(servicePercent=50)
    entry = sale()
    payroll.record_sale(state, entry, 1)
    assert entry['payrollAccruals'][0]['amount'] == 9


def test_rate_changes_and_late_refund_never_rewrite_old_earnings(setup):
    state, clock, _, _, policy = setup
    policy(personalPercent=10)
    entry = sale()
    payroll.record_sale(state, entry, 1)
    clock[0] = datetime(2026, 10, 2, 5, tzinfo=timezone.utc)
    policy(personalPercent=50)
    entry['refundedAt'] = '2026-10-03T06:00:00Z'
    payroll.record_refund(state, entry)
    assert payroll.report(state, '2026-10-01', '2026-10-01')['total'] == 18
    assert payroll.report(state, '2026-10-03', '2026-10-03')['total'] == -18
    assert state['payrollState']['events'][0]['amount'] == 18


def test_hourly_pay_uses_work_time_across_midnight_and_period_edges(setup):
    state, clock, _, run, policy = setup
    policy(fixedMode='hour', fixedAmount=100)
    clock[0] = datetime(2026, 10, 3, 6, tzinfo=timezone.utc)
    run('payroll.time', employeeId=1, openedAt='2026-10-01T22:00:00+05:00', closedAt='2026-10-02T06:00:00+05:00', reason='Confirmed time')
    first = payroll.report(state, '2026-10-01', '2026-10-01')['rows'][0]
    second = payroll.report(state, '2026-10-02', '2026-10-02')['rows'][0]
    assert (first['hours'], first['total']) == (2, 200)
    assert (second['hours'], second['total']) == (6, 600)


def test_shift_rate_paid_once_for_a_shift_crossing_midnight(setup):
    state, clock, _, run, policy = setup
    policy(fixedMode='shift', fixedAmount=500)
    clock[0] = datetime(2026, 10, 3, 6, tzinfo=timezone.utc)
    run('payroll.time', employeeId=1, openedAt='2026-10-01T22:00:00+05:00', closedAt='2026-10-02T06:00:00+05:00', reason='Confirmed time')
    assert payroll.report(state, '2026-10-01', '2026-10-01')['total'] == 500
    assert payroll.report(state, '2026-10-02', '2026-10-02')['total'] == 0


def test_monthly_rate_exact_for_leap_month_and_partial_period(setup):
    state, clock, _, _, policy = setup
    clock[0] = datetime(2028, 2, 1, 6, tzinfo=timezone.utc)
    policy(fixedMode='month', fixedAmount=2900)
    assert payroll.report(state, '2028-02-01', '2028-02-29')['total'] == 2900
    assert payroll.report(state, '2028-02-15', '2028-02-29')['total'] == 1500


def test_shift_percentage_only_while_employee_is_clocked_in(setup):
    state, _, _, _, policy = setup
    policy(personalPercent=10, shiftPercent=5)
    policy(2, shiftPercent=5)
    state['payrollState']['workShifts'] = [{'id': 's1', 'employeeId': '1', 'employeeName': 'One', 'branchId': 'b1', 'openedAt': '2026-10-01T05:00:00Z', 'closedAt': '2026-10-01T07:00:00Z'}, {'id': 's2', 'employeeId': '2', 'employeeName': 'Two', 'branchId': 'b1', 'openedAt': '2026-10-01T06:30:00Z', 'closedAt': None}]
    entry = sale()
    payroll.record_sale(state, entry, 1)
    assert len(entry['payrollAccruals']) == 1 and entry['payrollAccruals'][0]['amount'] == 27


def test_advance_approval_partial_payment_replay_and_reversal_are_consistent(setup):
    state, clock, _, run, policy = setup
    policy(fixedMode='month', fixedAmount=3100)
    run('payroll.advance', employeeId=1, amount=30, accountId='finance-bank', reason='Advance')
    clock[0] = datetime(2026, 10, 2, 6, tzinfo=timezone.utc)
    _, run_id = run('payroll.approve', start='2026-10-01', end='2026-10-01', expectedVersion=1)
    assert payroll.run_paid(state, run_id, 1) == 30 and payroll.balances(state)['1'] == 70
    payload = dict(employeeId=1, runId=run_id, amount=70, accountId='finance-bank', reason='Salary payment', requestId='payment-retry')
    _, payment = run('payroll.pay', **payload)
    before = deepcopy(state)
    assert run('payroll.pay', **payload)[1] == payment and state == before
    assert payroll.balances(state)['1'] == 0
    assert len(state['financeState']['transactions']) == 2
    run('payroll.reverse', paymentId=payment, accountId='finance-bank', reason='Wrong payment returned')
    assert payroll.balances(state)['1'] == 70
    assert payroll.run_paid(state, run_id, 1) == 30
    assert state['financeState']['transactions'][0]['type'] == 'income'
    with pytest.raises(WorkspaceError):
        run('finance.transaction.delete', id=state['financeState']['transactions'][0]['id'])


def test_closed_period_is_immutable_and_no_overpayment(setup):
    state, clock, _, run, policy = setup
    policy(fixedMode='month', fixedAmount=3100)
    clock[0] = datetime(2026, 10, 2, 6, tzinfo=timezone.utc)
    _, run_id = run('payroll.approve', start='2026-10-01', end='2026-10-01', expectedVersion=1)
    for action, payload in [('payroll.approve', dict(start='2026-10-01', end='2026-10-02', expectedVersion=1)), ('payroll.time', dict(employeeId=1, openedAt='2026-10-01T01:00:00Z', closedAt='2026-10-01T02:00:00Z', reason='Edit')), ('payroll.adjust', dict(employeeId=1, date='2026-10-01', amount=1, reason='Edit')), ('payroll.pay', dict(employeeId=1, runId=run_id, amount=101, accountId='finance-bank', reason='Too much'))]:
        before = deepcopy(state)
        with pytest.raises(WorkspaceError): run(action, **payload)
        assert state == before


def test_stale_approval_and_future_period_rejected(setup):
    state, _, _, run, policy = setup
    policy(fixedMode='month', fixedAmount=3100)
    with pytest.raises(WorkspaceError): run('payroll.approve', start='2026-10-01', end='2026-10-01', expectedVersion=0)
    with pytest.raises(WorkspaceError): run('payroll.approve', start='2026-10-01', end='2026-10-01', expectedVersion=1)


def test_cannot_pay_from_cash_drawer_or_assign_other_tenant_employee(setup):
    state, _, _, run, _ = setup
    with pytest.raises(WorkspaceError): run('payroll.policy', employeeId=999, effectiveFrom='2026-10-01')
    with pytest.raises(WorkspaceError): run('payroll.advance', employeeId=1, amount=10, accountId='finance-cash-b1', reason='Unsafe drawer')


@pytest.mark.parametrize('value', ['NaN', 'Infinity', -1, '10.001', 101])
def test_bad_rate_rejected_atomically(setup, value):
    state, _, _, _, policy = setup
    before = deepcopy(state)
    with pytest.raises(WorkspaceError): policy(personalPercent=value)
    assert state == before


def test_payroll_data_hidden_from_other_staff_and_actions_forbidden(setup):
    state, _, _, _, policy = setup
    policy(personalPercent=10)
    worker = {'id': 1, 'role': 'branch', 'display_name': 'Employee', 'branch_id': 'b1', 'staff_role': 'branch_manager'}
    payroll.record_sale(state, sale(), 1)
    with pytest.raises(WorkspaceError): apply_action(state, worker, 'payroll.advance', {'requestId': 'bad'})
    with pytest.raises(HTTPException): main._authorize_staff_action(worker, 'payroll.policy')
    assert 'payrollState' not in visible_state(state, worker)


def test_clock_in_out_does_not_follow_operator_session_or_cash_shift(setup):
    state, clock, _, _, _ = setup
    worker = {'id': 1, 'role': 'branch', 'display_name': 'Employee', 'branch_id': 'b1', 'register_id': 10, 'staff_role': 'waiter'}
    opened = {'requestId': 'clock-in'}
    first = apply_action(state, worker, 'work.shift.open', opened)
    assert apply_action(state, worker, 'work.shift.open', opened) == first
    assert payroll.current_shift(state, 1)
    clock[0] = datetime(2026, 10, 1, 13, tzinfo=timezone.utc)
    apply_action(state, {**worker, 'register_id': 20}, 'work.shift.close', {'requestId': 'clock-out'})
    assert not payroll.current_shift(state, 1)
    assert payroll.report(state, '2026-10-01', '2026-10-01')['total'] == 0


def test_rate_change_conflict_and_time_overlap_have_no_side_effects(setup):
    state, clock, _, run, policy = setup
    policy(fixedMode='hour', fixedAmount=10)
    clock[0] = datetime(2026, 10, 2, 6, tzinfo=timezone.utc)
    run('payroll.time', employeeId=1, openedAt='2026-10-01T01:00:00Z', closedAt='2026-10-01T03:00:00Z', reason='Verified')
    before = deepcopy(state)
    with pytest.raises(WorkspaceError): run('payroll.time', employeeId=1, openedAt='2026-10-01T02:00:00Z', closedAt='2026-10-01T04:00:00Z', reason='Overlap')
    assert state == before
    with pytest.raises(WorkspaceError): policy(personalPercent=5, effectiveFrom='2026-09-30')


def test_deleted_employee_stops_future_monthly_accrual_even_with_future_policy(setup):
    state, _, _, _, policy = setup
    policy(fixedMode='month', fixedAmount=3100)
    payroll.stop_employee(state, 1)
    assert payroll.report(state, '2026-10-01', '2026-10-31')['total'] == 100


def test_order_owner_gets_commission_even_when_another_cashier_closes_it(setup):
    state, _, _, _, policy = setup
    policy(personalPercent=10)
    actor = {'id': 1, 'login': 'one', 'display_name': 'One', 'role': 'branch', 'staff_role': 'branch_manager', 'branch_id': 'b1', 'plan_code': 'restaurant', 'register_id': 11, 'shift_id': 12}
    _, order_id = apply_action(state, actor, 'pos.order.save', {'items': [{'id': 'p-1', 'quantity': 1}]})
    second = {**actor, 'id': 2, 'display_name': 'Two'}
    apply_action(state, second, 'pos.order.save', {'id': order_id, 'items': [{'id': 'p-1', 'quantity': 2}]})
    payload = {'items': [{'id': 'p-1', 'quantity': 2}], 'openOrderId': order_id, 'paymentMethod': 'card', 'requestId': 'owner-sale'}
    _, sale_id = apply_action(state, second, 'sale.create', payload)
    paid = next(s for s in state['sales'] if s['id'] == sale_id)
    assert paid['cashierId'] == 2 and paid['orderOwnerId'] == 1
    assert paid['payrollAccruals'][0]['employeeId'] == '1'
    assert paid['payrollAccruals'][0]['amount'] == pytest.approx(paid['subtotal']*.1)
    before = deepcopy(state)
    assert apply_action(state, second, 'sale.create', payload)[1] == sale_id
    assert state == before
    apply_action(state, second, 'sale.refund', {'id': sale_id, 'reason': 'Guest refund'})
    assert sum(e['amount'] for e in state['payrollState']['events']) == 0
    visible = visible_state(state, second)
    assert 'payrollState' not in visible
    assert all('payrollAccruals' not in s for s in visible['sales'])


def test_manual_time_correction_is_audited_and_rejects_stale_version(setup):
    state, clock, _, run, policy = setup
    policy(fixedMode='hour', fixedAmount=100)
    clock[0] = datetime(2026, 10, 2, 6, tzinfo=timezone.utc)
    _, identity = run('payroll.time', employeeId=1, openedAt='2026-10-01T01:00:00Z', closedAt='2026-10-01T03:00:00Z', reason='Verified')
    with pytest.raises(WorkspaceError): run('payroll.time', id=identity, employeeId=1, openedAt='2026-10-01T01:00:00Z', closedAt='2026-10-01T04:00:00Z', reason='Corrected', expectedVersion=0)
    run('payroll.time', id=identity, employeeId=1, openedAt='2026-10-01T01:00:00Z', closedAt='2026-10-01T04:00:00Z', reason='Corrected', expectedVersion=1)
    assert len(state['payrollState']['workShifts']) == 1
    assert len(state['payrollState']['workShifts'][0]['corrections']) == 1
    assert payroll.report(state, '2026-10-01', '2026-10-01')['total'] == 300
