from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app import offline_pos as offline, payroll
from app.workspace import default_state, visible_state, WorkspaceError, apply_action


@pytest.fixture
def setup(monkeypatch):
    current = [datetime(2026, 10, 22, 6, tzinfo=timezone.utc)]
    monkeypatch.setattr(payroll, 'now', lambda: current[0])
    from app import workspace
    monkeypatch.setattr(workspace, '_now', lambda: current[0].isoformat())
    state = default_state()
    state['logisticsState']['branchStocks']['b1']['p-1'] = 20
    terminal = {'id': 10, 'tenant_id': 'tenant-a', 'role': 'branch', 'branch_id': 'b1', 'plan_code': 'canteen'}
    operator = {'id': 2, 'login': 'anna', 'display_name': 'Anna', 'staff_role': 'cashier', 'access_permissions': {}, 'branch_id': 'b1'}
    shift = {'id': 20, 'closed_at': None}
    lease = offline.issue(state, terminal, operator, shift)
    current[0] += timedelta(minutes=1)
    def receipt(**values):
        payload = {'requestId': str(uuid4()), 'orderType': 'dine-in', 'items': [{'id': 'p-1', 'quantity': 2}], 'payments': [{'method': 'cash', 'amount': 100}], 'received': 100}
        return {'token': lease['token'], 'payload': payload, 'createdAt': current[0].isoformat(), 'total': 80, **values}
    return state, terminal, operator, shift, lease, current, receipt


@pytest.mark.parametrize('subscription_status,field',[('trialing','trial_ends_at'),('active','current_period_ends_at')])
def test_offline_lease_stops_at_subscription_end(setup,subscription_status,field):
    state,terminal,operator,shift,old,current,_=setup
    end=current[0]+timedelta(minutes=30)
    terminal.update(subscription_status=subscription_status,**{field:end})
    new=offline.issue(state,terminal,operator,shift,old['token'])
    assert new['token']!=old['token']
    assert datetime.fromisoformat(new['expiresAt'])==end


def test_receipt_saved_once_and_duplicate_response_is_stable(setup):
    state, terminal, _, _, _, _, receipt = setup
    row = receipt()
    first = offline.receive(state, terminal, row)
    assert first['status'] == 'synced'
    assert state['logisticsState']['branchStocks']['b1']['p-1'] == 18
    assert state['sales'][0]['createdAt'] == row['createdAt']
    assert state['sales'][0]['originalShiftId'] == 20
    assert state['sales'][0]['cashierId'] == 2
    again = offline.receive(state, terminal, row, employee_active=False, shift_open=False)
    assert again['saleId'] == first['saleId'] and len(state['sales']) == 1
    assert len(state['offlinePos']['receipts']) == 1


def test_unknown_response_to_online_sale_does_not_duplicate(setup):
    state, terminal, _, _, _, _, receipt = setup
    row = receipt()
    actor = {'id': 2, 'role': 'branch', 'branch_id': 'b1', 'register_id': 10, 'shift_id': 20, 'display_name': 'Anna', 'login': 'anna', 'staff_role': 'cashier'}
    _, identifier = apply_action(state, actor, 'sale.create', row['payload'])
    result = offline.receive(state, terminal, row, employee_active=False, shift_open=False)
    assert result['saleId'] == identifier and len(state['sales']) == 1
    assert state['logisticsState']['branchStocks']['b1']['p-1'] == 18


def test_frozen_catalog_keeps_price_and_restores_current_configuration(setup):
    state, terminal, _, _, _, _, receipt = setup
    state['products'][0]['price'] = 999
    state['products'][0]['name'] = 'Renamed product'
    current_catalog = deepcopy(state['products'])
    result = offline.receive(state, terminal, receipt())
    assert result['status'] == 'synced'
    assert state['sales'][0]['total'] == 80
    assert state['products'] == current_catalog
    assert state['sales'][0]['items'][0]['price'] == 40


def test_stock_conflict_is_kept_and_owner_resolves_atomically(setup):
    state, terminal, _, _, _, _, receipt = setup
    state['logisticsState']['branchStocks']['b1']['p-1'] = 0
    row = receipt()
    result = offline.receive(state, terminal, row)
    assert result['status'] == 'conflict' and 'Недостаточно' in result['error']
    assert state['sales'] == []
    assert state['logisticsState']['branchStocks']['b1']['p-1'] == 0
    with pytest.raises(WorkspaceError):
        offline.resolve(state, {'role': 'branch'}, row['payload']['requestId'], 'Reason')
    state['logisticsState']['branchStocks']['b1']['p-1'] = 5
    resolved = offline.resolve(state, {'id': 99, 'role': 'owner'}, row['payload']['requestId'], 'Поставка проверена', 21)
    assert resolved['status'] == 'synced' and resolved['resolvedById'] == 99
    assert state['sales'][0]['shiftId'] == 21 and state['sales'][0]['originalShiftId'] == 20
    assert state['logisticsState']['branchStocks']['b1']['p-1'] == 3
    offline.resolve(state, {'id': 99, 'role': 'owner'}, row['payload']['requestId'], 'Повтор решения', 21)
    assert len(state['sales']) == 1


@pytest.mark.parametrize('employee_active,shift_open', [(False, True), (True, False)])
def test_access_or_shift_changes_require_review_without_losing_receipt(setup, employee_active, shift_open):
    state, terminal, _, _, _, _, receipt = setup
    result = offline.receive(state, terminal, receipt(), employee_active, shift_open)
    assert result['status'] == 'conflict' and state['sales'] == []
    assert result['total'] == 80 and result['payload']['items']


def test_different_register_or_tenant_cannot_submit_another_lease(setup):
    state, terminal, _, _, _, _, receipt = setup
    for changed in ({'id': 11}, {'tenant_id': 'tenant-b'}, {'branch_id': 'b2'}):
        with pytest.raises(WorkspaceError):
            offline.receive(state, {**terminal, **changed}, receipt())
    assert not state['sales']


def test_reused_id_with_different_data_is_rejected(setup):
    state, terminal, _, _, _, _, receipt = setup
    row = receipt(); offline.receive(state, terminal, row)
    changed = deepcopy(row); changed['payload']['items'][0]['quantity'] = 1
    with pytest.raises(WorkspaceError):
        offline.receive(state, terminal, changed)
    assert len(state['sales']) == 1


@pytest.mark.parametrize('change', ['total', 'card', 'old', 'future', 'customer', 'delivery'])
def test_invalid_or_forged_receipts_never_change_stock(setup, change):
    state, terminal, _, _, lease, current, receipt = setup
    row = receipt()
    if change == 'total': row['total'] = 1
    if change == 'card': row['payload']['payments'][0]['method'] = 'card'
    if change == 'old': row['createdAt'] = (current[0]-timedelta(days=2)).isoformat()
    if change == 'future': row['createdAt'] = (current[0]+timedelta(hours=2)).isoformat()
    if change == 'customer': row['payload']['customerId'] = 'customer'
    if change == 'delivery': row['payload']['orderType'] = 'delivery'
    try:
        result = offline.receive(state, terminal, row)
        assert result['status'] == 'conflict'
    except WorkspaceError:
        pass
    assert state['logisticsState']['branchStocks']['b1']['p-1'] == 20
    assert not state['sales']


def test_grant_reuse_expiry_and_no_plain_token_in_workspace(setup):
    state, terminal, operator, shift, lease, current, _ = setup
    again = offline.issue(state, terminal, operator, shift, lease['token'])
    assert again['id'] == lease['id'] and len(state['offlinePos']['leases']) == 1
    current[0] += timedelta(days=1)
    fresh = offline.issue(state, terminal, operator, shift, lease['token'])
    assert fresh['id'] != lease['id']
    assert lease['token'] not in repr(state)
    owner = visible_state(state, {'id': 99, 'role': 'owner'})
    assert 'offlinePos' not in owner


def test_inventory_after_sale_requires_review(setup):
    state, terminal, _, _, _, current, receipt = setup
    row = receipt()
    state['logisticsState']['inventories'] = [{'id': 'inv', 'branchId': 'b1', 'status': 'posted', 'createdAt': (current[0]+timedelta(hours=1)).isoformat(), 'countedAt': (current[0]+timedelta(hours=1)).isoformat(), 'postedAt': (current[0]+timedelta(hours=2)).isoformat()}]
    result = offline.receive(state, terminal, row)
    assert result['status'] == 'conflict' and 'инвентаризация' in result['error']


def test_restaurant_deducts_raw_materials_not_serving_stock(setup):
    state, terminal, operator, shift, _, current, receipt = setup
    terminal['plan_code'] = 'restaurant'
    state['logisticsState']['branchStocks']['b1']['rice'] = 10
    state['recipes'] = [{'id': 1, 'name': 'Rice', 'category': 'Горячее', 'price': 100, 'yield': 200, 'components': [{'ingredientId': 'rice', 'gross': 200}]}]
    lease = offline.issue(state, terminal, operator, shift)
    row = receipt(token=lease['token'], total=100)
    row['payload']['items'] = [{'id': 1, 'quantity': 1}]
    result = offline.receive(state, terminal, row)
    assert result['status'] == 'synced'
    assert state['logisticsState']['branchStocks']['b1']['rice'] == 9.8


def test_late_salary_percent_is_moved_to_current_open_period(setup):
    state, terminal, _, _, _, current, receipt = setup
    state['payrollState'] = {'policies': [{'id': 'p', 'sequence': 1, 'employeeId': '2', 'employeeName': 'Anna', 'effectiveFrom': '2026-10-01', 'fixedMode': 'none', 'fixedAmount': 0, 'personalPercent': 10, 'shiftPercent': 0, 'servicePercent': 0}], 'workShifts': [], 'events': [], 'runs': [{'start': '2026-10-01', 'end': '2026-10-22'}]}
    row = receipt(); current[0] += timedelta(days=1)
    result = offline.receive(state, terminal, row)
    assert result['status'] == 'synced'
    event = state['payrollState']['events'][0]
    assert event['amount'] == 8 and event['date'] == '2026-10-23' and event['originalDate'] == '2026-10-22'


def test_owner_can_reconcile_existing_server_receipt_without_another_deduction(setup):
    state, terminal, _, _, _, _, receipt = setup
    row=receipt();row['payload']['payments'][0]['amount']=1000;row['payload']['received']=1000
    state['products'][0]['price']=99
    actor={'id':2,'role':'branch','branch_id':'b1','register_id':10,'shift_id':20,'display_name':'Anna','login':'anna','staff_role':'cashier'}
    _, identifier=apply_action(state,actor,'sale.create',row['payload'])
    result=offline.receive(state,terminal,row)
    assert result['status']=='conflict'
    resolved=offline.resolve(state,{'id':99,'role':'owner'},row['payload']['requestId'],'Исходный чек и деньги проверены',accept_server=True)
    assert resolved['saleId']==identifier and resolved['serverTotal']==198 and resolved['discrepancyAcknowledged']
    assert len(state['sales'])==1 and state['logisticsState']['branchStocks']['b1']['p-1']==18


@pytest.mark.parametrize('headers', [[(b'x-oimo-register',b'11')],[(b'x-oimo-tenant',b'tenant-b')]])
def test_terminal_identity_guard_rejects_shared_cookie_from_another_register(headers):
    from app import main
    from fastapi import HTTPException, Request
    from types import SimpleNamespace
    row={'id':10,'tenant_id':'tenant-a','role':'branch','staff_role':'pos_terminal'}
    connection=SimpleNamespace(execute=lambda *args:SimpleNamespace(fetchone=lambda:row))
    request=Request({'type':'http','path':'/api/v1/workspace','headers':[(b'x-ashkana-client',b'pos'),*headers]})
    with pytest.raises(HTTPException) as error:
        main.current_user(request,None,'terminal-cookie',connection)
    assert error.value.status_code==403


def test_pin_operator_guard_does_not_silently_switch_cashier():
    from app import main
    from fastapi import HTTPException
    from types import SimpleNamespace
    row={'id':3,'staff_role':'cashier','access_permissions':{},'operator_session_id':30}
    connection=SimpleNamespace(execute=lambda *args:SimpleNamespace(fetchone=lambda:row))
    terminal={'id':10,'tenant_id':'tenant-a','branch_id':'b1','role':'branch','staff_role':'pos_terminal','session_id':50,'_expected_operator_id':'2'}
    with pytest.raises(HTTPException) as error:
        main._current_pos_operator(connection,terminal,'operator-cookie')
    assert error.value.status_code==423
