from copy import deepcopy
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app import main
from app.transfer_history import build_cash_shift_history, build_transfer_history
from app.workspace import apply_action
from test_custody import COOK as KITCHEN, RECEIVER, setup
from test_transfer_history import CASHIER, COOK, state_with, transfer


def shift(key, **fields):
    return {'id': key, 'branchId': 'b1', 'employeeId': 7, 'employeeName': 'Повар',
            'openedAt': '2026-10-05T09:00:00+06:00', 'closedAt': '2026-10-05T11:00:00+06:00',
            'status': 'closed', 'registerId': 101, 'registerName': 'Касса 1', **fields}


def with_shifts(*documents, production=None):
    state = state_with(*documents)
    state['logisticsState']['productionShifts'] = production or []
    return state


def test_separate_explicit_shift_links_survive_later_acceptance_and_other_opening_cashier():
    source = transfer(status='accepted', productionShiftId='k1', receivingShiftId=11,
                      acceptedAt='2026-10-06T10:00:00+06:00', acceptedBy={'id': 8})
    state = with_shifts(source, production=[shift('k1'), shift('k2', openedAt='2026-10-06T09:00:00+06:00', closedAt=None)])
    cash = [shift(11, employeeId=999, openedAt='2026-10-06T09:00:00+06:00', closedAt=None, status='open')]
    result = build_transfer_history(state, 'b1', {**CASHIER, 'register_id': 101}, cash)
    row = result['documents'][0]
    assert row['productionShift']['id'] == 'k1'
    assert row['receivingShift']['id'] == 11
    assert row['receivingShift']['employeeId'] == 999
    assert result['currentShiftId'] == 11 and result['currentShiftKind'] == 'cash'
    assert [s['id'] for s in result['shifts']] == [11]


def test_legacy_matches_sender_and_receiving_employee_at_separate_times():
    source = transfer(status='accepted', acceptedAt='2026-10-05T13:00:00+06:00', acceptedBy={'id': 8})
    state = with_shifts(source, production=[shift('k1'), shift('wrong-actor', employeeId=9), shift('foreign', branchId='b2')])
    cash = [shift(11, employeeId=8, openedAt='2026-10-05T12:00:00+06:00', closedAt='2026-10-05T14:00:00+06:00'),
            shift(12, employeeId=8), shift(13, employeeId=8, branchId='b2')]
    row = build_transfer_history(state, 'b1', COOK, cash)['documents'][0]
    assert row['productionShift']['id'] == 'k1' and row['receivingShift']['id'] == 11
    assert 'productionShiftId' not in source and 'receivingShiftId' not in source


@pytest.mark.parametrize('production,source_fields', [
    ([shift('first'), shift('overlap')], {}),
    ([shift('first', closedAt='2026-10-05T10:00:00+06:00'), shift('next', openedAt='2026-10-05T10:00:00+06:00')], {}),
    ([shift('first')], {'createdAt': '2026-10-05T10:00:00'}),
    ([shift('first')], {'createdAt': 'not-a-date'}),
    ([shift('foreign', branchId='b2')], {'productionShiftId': 'foreign'}),
    ([shift('first')], {'productionShiftId': 'missing'}),
    ([shift('missing-close', closedAt=None)], {}),
])
def test_ambiguous_invalid_or_broken_legacy_links_remain_unassigned(production, source_fields):
    state = with_shifts(transfer(**source_fields), production=production)
    assert build_transfer_history(state, 'b1', COOK)['documents'][0]['productionShift'] is None


def test_child_outcome_explicit_shift_is_used_but_mutable_lot_owner_is_not():
    sources = [transfer('accepted', status='accepted'), transfer('rejected', status='rejected'),
               transfer('legacy', status='accepted', acceptedAt='2026-10-05T10:15:00+06:00', acceptedBy={'id': 8})]
    children = [{'id': key+'-event', 'sourceId': key, 'kind': kind, 'branchId': 'b1',
                 'createdAt': '2026-10-05T10:15:00+06:00', 'actor': {'id': 8}, 'shiftId': 12}
                for key, kind in [('accepted', 'acceptance'), ('rejected', 'rejection')]]
    state = with_shifts(*sources, *children)
    state['logisticsState']['batches'] = [{'id': 'batch', 'branchId': 'b1', 'servingLots': [{'acceptedShiftId': 12}]}]
    cash = [shift(11, employeeId=8), shift(12, employeeId=8)]
    rows = {r['id']: r for r in build_transfer_history(state, 'b1', CASHIER, cash)['documents']}
    assert rows['accepted']['receivingShift']['id'] == 12
    assert rows['rejected']['receivingShift']['id'] == 12
    assert rows['legacy']['receivingShift'] is None


def test_snapshots_and_current_shift_are_scoped_private_and_read_only():
    state = with_shifts(transfer(productionShiftId='own'), production=[
        shift('own', closedAt=None, status='open', openRequest={'payload': 'secret'}, openingCounts=[1]),
        shift('other', employeeId=9), shift('foreign', branchId='b2')])
    cash = [shift(11, employeeId=8, closingCash=999, requestPayload={'secret': True}),
            shift(12, employeeId=9, registerId=102, closedAt=None, status='open'),
            shift(13, employeeId=8, registerId=101, closedAt=None, status='open'),
            shift(14, branchId='b2')]
    before = deepcopy((state, cash))
    kitchen = build_transfer_history(state, 'b1', COOK, cash)
    archive = build_cash_shift_history(cash, 'b1', {**CASHIER, 'register_id': 101})
    assert kitchen['currentShiftId'] == 'own'
    assert [s['id'] for s in kitchen['shifts']] == ['own']
    assert {s['id'] for s in archive['shifts']} == {11, 12, 13}
    assert archive['currentShiftId'] == 13
    allowed = {'id', 'number', 'kind', 'branchId', 'employeeId', 'employeeName', 'openedAt', 'closedAt', 'status', 'registerId', 'registerName'}
    assert all(set(s) <= allowed for s in kitchen['shifts'] + archive['shifts'])
    kitchen['documents'][0]['productionShift']['employeeName'] = 'Changed'
    archive['shifts'][0]['registerName'] = 'Changed'
    assert (state, cash) == before
    assert build_cash_shift_history(cash, 'b2', CASHIER) == {'shifts': [], 'currentShiftId': None}


@pytest.mark.parametrize('outcome', ['accept', 'reject'])
def test_transfer_and_outcome_persist_action_shift_and_replays_do_not_reassign(outcome):
    state, batch, _ = setup()
    actor = {**KITCHEN, 'production_shift_id': 'kitchen-first', '_custody_recipient':
             {'id': 'branch_cashiers', 'kind': 'branch_cashiers', 'name': 'Касса', 'branchId': 'b1'}}
    sent = {'requestId': 'send', 'id': batch['id'], 'weight': 1, 'line': 'Витрина'}
    _, doc_id = apply_action(state, actor, 'batch.transfer', sent)
    source = next(d for d in state['logisticsState']['custodyDocuments'] if d['id'] == doc_id)
    assert source['productionShiftId'] == batch['transfers'][0]['productionShiftId'] == 'kitchen-first'
    receiver = {**RECEIVER, 'shift_id': 51, 'register_id': 101}
    payload = {'requestId': 'outcome', 'documentId': doc_id, 'actualWeight': 1, 'reason': 'Проверка передачи'}
    result = apply_action(state, receiver, 'pos.receiving.'+outcome, payload)
    event = next(d for d in state['logisticsState']['custodyDocuments'] if d['id'] == result[1])
    assert event['shiftId'] == source['receivingShiftId'] == batch['transfers'][0]['receivingShiftId'] == 51
    assert event['registerId'] == source['receivingRegisterId'] == 101
    before = deepcopy(state)
    assert apply_action(state, {**actor, 'production_shift_id': 'kitchen-later'}, 'batch.transfer', sent)[1] == doc_id
    assert apply_action(state, {**receiver, 'shift_id': 52}, 'pos.receiving.'+outcome, payload) == result
    assert state == before


def test_manager_transfer_records_own_active_production_shift_without_borrowing_other_cook_shift():
    state, batch, _ = setup()
    actor = {**KITCHEN, 'staff_role': 'branch_manager', '_custody_recipient': {'id': 102, 'branchId': 'b1'}}
    state['logisticsState']['productionShifts'] = [shift('own', employeeId=actor['id'], status='open', closedAt=None)]
    apply_action(state, actor, 'batch.transfer', {'requestId': 'manager', 'id': batch['id'], 'weight': 1, 'line': 'Витрина'})
    assert state['logisticsState']['custodyDocuments'][0]['productionShiftId'] == 'own'
    state['logisticsState']['productionShifts'][0]['employeeId'] = 999
    apply_action(state, actor, 'batch.transfer', {'requestId': 'manager-other', 'id': batch['id'], 'weight': 1, 'line': 'Витрина'})
    assert state['logisticsState']['custodyDocuments'][0]['productionShiftId'] is None


TERMINAL = {'id': 101, 'role': 'branch', 'staff_role': 'pos_terminal', 'tenant_id': 't1', 'branch_id': 'b1', 'plan_code': 'canteen'}


@pytest.mark.parametrize('role,policy,allowed', [('cashier', 'never', True), ('waiter', 'never', True),
    ('cashier', 'always', False), ('hall_admin', 'always', True), ('branch_manager', 'always', True), ('production', 'never', False)])
def test_cash_history_access_uses_current_operator_and_existing_order_history_policy(monkeypatch, role, policy, allowed):
    operator = {**CASHIER, 'staff_role': role, 'branch_id': 'untrusted', 'tenant_id': 'untrusted'}
    state = {'companySettings': {'security': {'orderHistory': policy}}}
    calls = []
    monkeypatch.setattr(main, '_current_pos_operator', lambda connection, user, cookie: operator)
    monkeypatch.setattr(main, '_workspace_row', lambda connection, tenant: {'payload': state} if tenant == 't1' else pytest.fail('wrong tenant'))
    def load(connection, user):
        calls.append(user)
        return [shift(51, employeeId=999, status='open', closedAt=None), shift(52, branchId='b2')]
    monkeypatch.setattr(main, '_pos_history_cash_shifts', load)
    if not allowed:
        with pytest.raises(HTTPException) as error:
            main.pos_shifts_history('cookie', TERMINAL, object())
        assert error.value.status_code == 403 and not calls
    else:
        result = main.pos_shifts_history('cookie', TERMINAL, object())
        assert calls == [TERMINAL]
        assert result['currentShiftId'] == 51 and [s['id'] for s in result['shifts']] == [51]


def test_cash_shift_sql_is_read_only_tenant_branch_scoped_and_has_no_financial_projection():
    class Connection:
        def execute(self, sql, parameters):
            assert parameters == ('t1', 'b1')
            assert 'shift.tenant_id = %s AND shift.branch_id = %s' in sql
            assert 'shift.*' not in sql and 'cash' not in sql and 'UPDATE' not in sql
            return self
        def fetchall(self):
            return [{'id': 51, 'branch_id': 'b1', 'register_user_id': 101, 'opened_by_user_id': 8,
                     'opened_at': datetime(2026, 10, 5, tzinfo=timezone.utc), 'closed_at': None,
                     'register_name': 'Касса 1', 'opened_by': 'Кассир'}]
    rows = main._pos_history_cash_shifts(Connection(), TERMINAL)
    result = build_cash_shift_history(rows, 'b1', {**CASHIER, 'register_id': 101})
    assert result['currentShiftId'] == 51
    assert result['shifts'][0]['employeeName'] == 'Кассир'
    assert result['shifts'][0]['openedAt'] == '2026-10-05T00:00:00+00:00'


def test_transfer_endpoint_hydrates_cash_shift_catalog_from_terminal_scope(monkeypatch):
    source = transfer(status='rejected', rejectedBy={'id': 8}, receivingShiftId=51)
    monkeypatch.setattr(main, '_current_pos_operator', lambda *args: CASHIER)
    monkeypatch.setattr(main, '_workspace_row', lambda *args: {'payload': state_with(source)})
    monkeypatch.setattr(main, '_pos_history_cash_shifts', lambda connection, terminal: [shift(51, employeeId=999)] if terminal is TERMINAL else pytest.fail('wrong terminal'))
    result = main.pos_transfer_history('cookie', TERMINAL, object())
    assert result['documents'][0]['receivingShift']['id'] == 51
    assert result['shifts'][0]['id'] == 51
