"""Report account metadata stays read-only and within the authenticated tenant."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main
from test_sales_report import START, END, receipt


@pytest.fixture
def report_endpoint(monkeypatch):
    harness = SimpleNamespace(
        state={'sales': [receipt()], 'companySettings': {'security': {'reports': 'always'}}},
        operator={'id': 9, 'role': 'branch', 'staff_role': 'branch_manager'},
        accounts=[{'id': 4, 'display_name': 'Daison', 'is_active': False, 'deleted_at': START}],
        calls=[],
    )

    class ReadOnlyConnection:
        def execute(self, sql, parameters):
            normalized = ' '.join(sql.split())
            assert normalized == 'SELECT id, display_name, is_active, deleted_at FROM auth_users WHERE tenant_id = %s'
            assert parameters == ('authenticated-tenant',)
            harness.calls.append('accounts')
            return SimpleNamespace(fetchall=lambda: harness.accounts)

    connection = ReadOnlyConnection()
    terminal = {'id': 20, 'tenant_id': 'authenticated-tenant', 'branch_id': 'b', 'staff_role': 'pos_terminal'}

    def operator(actual_connection, user, token):
        assert actual_connection is connection and user is terminal and token == 'operator-cookie'
        harness.calls.append('operator')
        return harness.operator

    def workspace(actual_connection, tenant_id, for_update=False):
        assert actual_connection is connection and tenant_id == terminal['tenant_id'] and not for_update
        harness.calls.append('workspace')
        return {'payload': harness.state}

    monkeypatch.setattr(main, '_current_pos_operator', operator)
    monkeypatch.setattr(main, '_workspace_row', workspace)
    harness.invoke = lambda **changes: main.terminal_sales_report(
        **{'start': START, 'end': END, 'cashier': '4', 'products': True, **changes},
        ashkana_pos_operator='operator-cookie', user=terminal, connection=connection,
    )
    return harness


def test_report_resolves_deleted_identity_with_tenant_scoped_read_only_lookup(report_endpoint):
    before = deepcopy(report_endpoint.state)
    result = report_endpoint.invoke()
    assert result['cashier'] == 'Daison · удалён'
    assert result['cashiers'][0]['id'] == '4'
    assert result['sales'] == 100 and result['xlsx']
    assert report_endpoint.calls == ['operator', 'workspace', 'accounts']
    assert report_endpoint.state == before


@pytest.mark.parametrize('role', ['production', 'cashier'])
def test_report_permission_denial_precedes_account_disclosure(report_endpoint, role):
    report_endpoint.operator['staff_role'] = role
    with pytest.raises(HTTPException) as error:
        report_endpoint.invoke()
    assert error.value.status_code == 403
    assert 'accounts' not in report_endpoint.calls


@pytest.mark.parametrize('changes', [{'cashier': 'other-branch-user'}, {'start': END, 'end': START}])
def test_bad_report_filter_is_422_instead_of_mislabeled_all_cashiers(report_endpoint, changes):
    with pytest.raises(HTTPException) as error:
        report_endpoint.invoke(**changes)
    assert error.value.status_code == 422
