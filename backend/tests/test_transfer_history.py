from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.transfer_history import build_transfer_history


COOK = {'id': 7, 'role': 'branch', 'staff_role': 'production', 'branch_id': 'b1'}
CASHIER = {**COOK, 'id': 8, 'staff_role': 'cashier'}
OWNER = {'id': 1, 'role': 'owner'}


def transfer(key='transfer', **fields):
    return {'id': key, 'number': 'УЧ-000001', 'kind': 'transfer', 'branchId': 'b1',
            'batchId': 'batch', 'batchNumber': 'АП-0001', 'recipeId': 'dish',
            'createdAt': '2026-10-05T10:00:00+06:00', 'actor': {'id': 7, 'name': 'Повар'},
            'recipient': {'id': 'branch_cashiers', 'kind': 'branch_cashiers', 'name': 'Касса заведения'},
            'weight': 2, 'status': 'pending', **fields}


def state_with(*documents):
    return {'recipes': [{'id': 'dish', 'name': 'Плов'}],
            'logisticsState': {'custodyDocuments': list(documents), 'batches': [],
                               'branchStocks': {'b1': {'rice': 123}}}}


def test_production_history_is_scoped_to_sender_and_branch():
    state = state_with(transfer('mine'), transfer('other', actor={'id': 9, 'name': 'Другой'}),
                       transfer('other-branch', branchId='b2'))
    result = build_transfer_history(state, 'b1', COOK)
    assert result['actorId'] == 7
    assert [row['id'] for row in result['documents']] == ['mine']
    assert build_transfer_history(state, 'b2', COOK)['documents'] == []
    assert [row['id'] for row in build_transfer_history(state, 'b2', OWNER)['documents']] == ['other-branch']


@pytest.mark.parametrize('role', ['cashier', 'hall_admin'])
def test_receiving_history_has_pending_and_own_outcomes_only(role):
    documents = [
        transfer('queue'),
        transfer('assigned-me', recipient={'id': '8', 'name': 'Кассир'}),
        transfer('assigned-other', recipient={'id': 9}),
        transfer('accepted-me', status='accepted', acceptedBy={'id': 8}),
        transfer('accepted-other', status='accepted', acceptedBy={'id': 9}),
        transfer('rejected-me', status='rejected', rejectedBy={'id': '8'}),
        transfer('rejected-other', status='rejected', rejectedBy={'id': 9}),
        transfer('own-sent-canceled', actor={'id': 8}, status='canceled'),
        transfer('canceled-other', status='canceled'),
        transfer('other-branch', branchId='b2'),
    ]
    result = build_transfer_history(state_with(*documents), 'b1', {**CASHIER, 'staff_role': role})
    assert {row['id'] for row in result['documents']} == {
        'queue', 'assigned-me', 'accepted-me', 'rejected-me', 'own-sent-canceled'}


@pytest.mark.parametrize('user', [OWNER, {**COOK, 'staff_role': 'branch_manager'}])
def test_managers_see_all_statuses_in_selected_branch(user):
    states = ['pending', 'accepted', 'rejected', 'canceled']
    state = state_with(*(transfer(status, status=status, actor={'id': 99}) for status in states),
                       transfer('elsewhere', branchId='b2'))
    assert {row['status'] for row in build_transfer_history(state, 'b1', user)['documents']} == set(states)


def test_linked_receipt_preserves_zero_actual_discrepancy_and_review():
    source = transfer(servingDocumentId='serving-group', name='Название при передаче',
                      status='accepted', actualWeight=0, acceptedAt='2026-10-05T10:05:00+06:00')
    acceptance = {'id': 'receipt', 'kind': 'acceptance', 'branchId': 'b1', 'sourceId': source['id'],
                  'actor': {'id': 8, 'name': 'Кассир'}, 'createdAt': '2026-10-05T10:04:00+06:00',
                  'actualWeight': 1, 'expectedWeight': 2, 'variance': -2, 'reason': 'Блюдо не доставлено',
                  'status': 'approved', 'reviewedAt': '2026-10-05T10:10:00+06:00',
                  'reviewedBy': {'id': 1, 'name': 'Владелец'}, 'reviewNote': 'Проверено'}
    row = build_transfer_history(state_with(source, acceptance), 'b1', CASHIER)['documents'][0]
    assert row['name'] == 'Название при передаче' and row['servingDocumentId'] == 'serving-group'
    assert row['status'] == 'accepted' and row['actualWeight'] == 0 and row['variance'] == -2
    assert row['acceptedAt'] == source['acceptedAt'] and row['acceptedBy']['id'] == 8
    assert row['reason'] == 'Блюдо не доставлено'
    assert row['reviewStatus'] == 'approved' and row['reviewNote'] == 'Проверено'
    assert row['reviewedBy'] == {'id': 1, 'name': 'Владелец'}


def test_linked_events_supply_missing_legacy_snapshot_fields_and_cannot_cross_branches():
    accepted = transfer('accepted', status=None)
    rejected = transfer('rejected', status=None)
    canceled = transfer('canceled', status=None)
    events = [
        {'id': 'receipt', 'kind': 'acceptance', 'sourceId': 'accepted', 'branchId': 'b1',
         'createdAt': '2026-10-05T11:00:00+06:00', 'actor': {'id': 8}, 'actualWeight': 0, 'status': 'review'},
        {'id': 'rejection', 'kind': 'rejection', 'sourceId': 'rejected', 'branchId': 'b1',
         'createdAt': '2026-10-05T11:10:00+06:00', 'actor': {'id': 8}, 'reason': 'Не доставлено'},
        {'id': 'cancel', 'kind': 'cancel', 'sourceId': 'canceled', 'branchId': 'b1',
         'createdAt': '2026-10-05T11:20:00+06:00', 'actor': {'id': 7}, 'reason': 'Ошибка отправки'},
        {'id': 'wrong-branch', 'kind': 'acceptance', 'sourceId': 'accepted', 'branchId': 'b2',
         'createdAt': '2026-10-05T12:00:00+06:00', 'actor': {'id': 9}, 'actualWeight': 999},
    ]
    state = state_with(accepted, rejected, canceled, *events)
    rows = {row['id']: row for row in build_transfer_history(state, 'b1', COOK)['documents']}
    assert rows['accepted']['actualWeight'] == 0 and rows['accepted']['variance'] == -2
    assert rows['accepted']['acceptedBy'] == {'id': 8}
    assert rows['accepted']['reviewStatus'] == 'review'
    assert rows['rejected']['status'] == 'rejected' and rows['rejected']['rejectReason'] == 'Не доставлено'
    assert rows['canceled']['status'] == 'canceled' and rows['canceled']['cancelReason'] == 'Ошибка отправки'
    assert {row['id'] for row in build_transfer_history(state, 'b1', CASHIER)['documents']} == {'accepted', 'rejected'}


def test_history_is_read_only_and_whitelists_nested_and_top_level_data():
    source = transfer(costAmount=500, costPerKg=250, requestPayload={'private': True},
                      actor={'id': 7, 'name': 'Повар', 'private': 'hidden'},
                      recipient={'id': 8, 'name': 'Кассир', 'private': 'hidden'})
    state = state_with(source)
    before = deepcopy(state)
    result = build_transfer_history(state, 'b1', COOK)
    assert state == before
    row = result['documents'][0]
    assert row['name'] == 'Плов'
    assert not {'costAmount', 'costPerKg', 'requestPayload', 'branchId', 'batchId'} & row.keys()
    assert row['actor'] == {'id': 7, 'name': 'Повар'}
    assert row['recipient'] == {'id': 8, 'name': 'Кассир'}
    row['actor']['name'] = 'Изменено'
    row['recipient']['name'] = 'Изменено'
    assert state == before


def test_review_event_fallback_and_source_review_snapshot_precedence():
    source = transfer(status='accepted', actualWeight=1)
    acceptance = {'id': 'receipt', 'kind': 'acceptance', 'branchId': 'b1', 'sourceId': source['id'],
                  'createdAt': '2026-10-05T10:05:00+06:00', 'actor': {'id': 8}, 'reason': 'Недовес'}
    review = {'id': 'review', 'kind': 'review', 'branchId': 'b1', 'sourceId': 'receipt',
              'createdAt': '2026-10-05T10:10:00+06:00', 'actor': {'id': 1, 'name': 'Владелец'},
              'decision': 'approve', 'reason': 'Проверка завершена'}
    state = state_with(source, acceptance, review)
    row = build_transfer_history(state, 'b1', COOK)['documents'][0]
    assert row['reviewStatus'] == 'approved'
    assert row['reviewedAt'] == review['createdAt']
    assert row['reviewedBy'] == {'id': 1, 'name': 'Владелец'}
    assert row['reviewNote'] == 'Проверка завершена'
    source.update(reviewStatus='approved', reviewedAt='2026-10-05T10:15:00+06:00',
                  reviewedBy={'id': 2, 'name': 'Руководитель'}, reviewNote='Снимок источника')
    row = build_transfer_history(state, 'b1', COOK)['documents'][0]
    assert row['reviewedAt'] == source['reviewedAt']
    assert row['reviewedBy'] == source['reviewedBy']
    assert row['reviewNote'] == 'Снимок источника'


def test_full_history_sorts_by_time_not_timestamp_text_without_truncation():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    documents = [transfer(str(index), createdAt=(start + timedelta(minutes=index)).isoformat())
                 for index in range(1001)]
    documents += [transfer('latest-utc', createdAt='2026-10-05T05:00:00Z'),
                  transfer('earlier-local', createdAt='2026-10-05T10:00:00+06:00')]
    rows = build_transfer_history(state_with(*documents), 'b1', COOK)['documents']
    assert len(rows) == 1003
    assert [row['id'] for row in rows[:3]] == ['latest-utc', 'earlier-local', '1000']


@pytest.mark.parametrize('staff_role,plan_code', [('waiter', 'canteen'), ('production', 'restaurant')])
def test_endpoint_rejects_role_or_restaurant_before_reading_workspace(monkeypatch, staff_role, plan_code):
    from app import main
    from fastapi import HTTPException

    operator = {**COOK, 'staff_role': staff_role}
    terminal = {'id': 101, 'role': 'branch', 'staff_role': 'pos_terminal',
                'tenant_id': 'terminal-tenant', 'branch_id': 'b1', 'plan_code': plan_code}
    monkeypatch.setattr(main, '_current_pos_operator', lambda *args: operator)

    def unexpected_read(*args, **kwargs):
        pytest.fail('Forbidden history must not read workspace or cash shifts')

    monkeypatch.setattr(main, '_workspace_row', unexpected_read)
    monkeypatch.setattr(main, '_current_pos_shift', unexpected_read)
    with pytest.raises(HTTPException) as error:
        main.pos_transfer_history('operator-cookie', terminal, object())
    assert error.value.status_code == 403


@pytest.mark.parametrize('staff_role', ['production', 'cashier', 'hall_admin', 'branch_manager'])
def test_endpoint_uses_terminal_tenant_and_branch_without_cash_shift(monkeypatch, staff_role):
    from app import main

    terminal = {'id': 101, 'role': 'branch', 'staff_role': 'pos_terminal',
                'tenant_id': 'terminal-tenant', 'branch_id': 'b1', 'plan_code': 'canteen'}
    operator = {**COOK, 'id': 8, 'staff_role': staff_role,
                'tenant_id': 'untrusted-operator-tenant', 'branch_id': 'b2'}
    connection = object()
    state = state_with(transfer('mine', actor={'id': 8}),
                       transfer('other-branch', actor={'id': 8}, branchId='b2'))
    before = deepcopy(state)
    calls = []

    def current_operator(actual_connection, actual_terminal, cookie):
        assert actual_connection is connection and actual_terminal is terminal and cookie == 'operator-cookie'
        return operator

    def workspace(actual_connection, tenant_id):
        assert actual_connection is connection
        calls.append(tenant_id)
        return {'payload': state}

    def no_cash_shift(*args, **kwargs):
        pytest.fail('Read-only history must remain available without a cash shift')

    monkeypatch.setattr(main, '_current_pos_operator', current_operator)
    monkeypatch.setattr(main, '_workspace_row', workspace)
    monkeypatch.setattr(main, '_current_pos_shift', no_cash_shift)
    monkeypatch.setattr(main, '_pos_history_cash_shifts', lambda *args: [])
    result = main.pos_transfer_history('operator-cookie', terminal, connection)
    assert calls == ['terminal-tenant']
    assert result['actorId'] == operator['id']
    assert [row['id'] for row in result['documents']] == ['mine']
    assert state == before
