"""Permission and read-only boundaries of the terminal supply-file preview."""
import base64
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main


TERMINAL = {
    "id": 81, "role": "branch", "staff_role": "pos_terminal",
    "tenant_id": "tenant-supply-preview", "branch_id": "b1", "plan_code": "canteen",
    "access_permissions": {"posSupply": True},
}
PAYLOAD = {
    "file": base64.b64encode("Наименование;Количество;Цена\nРис;2;100\n".encode()).decode(),
    "fileName": "supply.csv",
}


class NoSQLConnection:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("Supply preview must not execute business SQL")


@pytest.fixture
def preview_endpoint(monkeypatch):
    from app import supply_import

    request = Request({
        "type": "http", "method": "POST", "path": "/api/v1/pos/supplies/import-preview",
        "headers": [(b"origin", b"http://127.0.0.1:8000"), (b"x-ashkana-client", b"pos")],
    })
    state = {
        "ingredients": [{"id": "rice", "name": "Рис", "unit": "кг"}], "products": [],
        "logisticsState": {"branchStocks": {"b1": {"rice": 0}}, "supplies": [], "stockLedger": []},
        "financeState": {"transactions": []}, "sales": [],
    }
    harness = SimpleNamespace(
        request=request, connection=NoSQLConnection(), state=state, calls=[],
        actor={"id": 82, "role": "branch", "staff_role": "production", "access_permissions": {"production": True}},
        result={"fileName": "supply.csv", "rows": [{"itemId": "rice", "quantity": 2, "price": 100}], "total": 200},
    )

    def origin(actual):
        assert actual is request
        harness.calls.append("origin")

    def operator(connection, user, token):
        assert connection is harness.connection
        assert user is TERMINAL
        assert token == "preview-operator-cookie"
        harness.calls.append("operator")
        return harness.actor

    def workspace(connection, tenant_id, for_update=False):
        assert connection is harness.connection
        assert tenant_id == TERMINAL["tenant_id"]
        assert not for_update
        harness.calls.append("workspace")
        return {"payload": state, "version": 7}

    def parse(actual_state, encoded, file_name):
        assert actual_state is state
        assert encoded == PAYLOAD["file"]
        assert file_name == PAYLOAD["fileName"]
        harness.calls.append("parser")
        return harness.result

    def no_shift(*_args, **_kwargs):
        raise AssertionError("A supply preview does not require an open cash shift")

    monkeypatch.setattr(main, "_check_origin", origin)
    monkeypatch.setattr(main, "_current_pos_operator", operator)
    monkeypatch.setattr(main, "_workspace_row", workspace)
    monkeypatch.setattr(main, "_current_pos_shift", no_shift)
    monkeypatch.setattr(supply_import, "preview", parse)
    harness.parser_module = supply_import
    harness.invoke = lambda payload=PAYLOAD: main.preview_supply_import(
        payload=payload, request=request, ashkana_pos_operator="preview-operator-cookie",
        user=TERMINAL, connection=harness.connection,
    )
    return harness


def test_supply_preview_route_is_registered_as_post():
    routes = [route for route in main.app.routes if getattr(route, "path", None) == "/api/v1/pos/supplies/import-preview"]
    assert len(routes) == 1
    assert routes[0].methods == {"POST"}
    assert routes[0].endpoint is main.preview_supply_import


def test_production_with_legacy_permissions_can_preview_without_stock_mutation(preview_endpoint):
    harness = preview_endpoint
    before = deepcopy(harness.state)
    payload = deepcopy(PAYLOAD)
    result = harness.invoke(payload)
    assert result == harness.result
    assert harness.calls == ["origin", "operator", "workspace", "parser"]
    assert harness.state == before
    assert payload == PAYLOAD


@pytest.mark.parametrize("permissions", [{}, {"posAccess": True}, {"posAccess": True, "posSupply": False}])
def test_cashier_without_supply_grant_cannot_preview_or_read_catalog(preview_endpoint, permissions):
    harness = preview_endpoint
    harness.actor = {"id": 83, "role": "branch", "staff_role": "cashier", "access_permissions": permissions}
    before = deepcopy(harness.state)
    with pytest.raises(HTTPException) as error:
        harness.invoke()
    assert error.value.status_code == 403
    assert harness.calls == ["origin", "operator"]
    assert harness.state == before


def test_cashier_with_explicit_supply_grant_can_preview(preview_endpoint):
    harness = preview_endpoint
    harness.actor = {"id": 83, "role": "branch", "staff_role": "cashier", "access_permissions": {"posAccess": True, "posSupply": True}}
    before = deepcopy(harness.state)
    assert harness.invoke() == harness.result
    assert harness.calls == ["origin", "operator", "workspace", "parser"]
    assert harness.state == before


def test_preview_uses_authenticated_tenant_not_payload_scope(preview_endpoint):
    harness = preview_endpoint
    result = harness.invoke({**PAYLOAD, "tenantId": "other-tenant", "branchId": "other-branch"})
    assert result == harness.result
    assert harness.calls == ["origin", "operator", "workspace", "parser"]


def test_origin_rejection_happens_before_operator_or_catalog_lookup(preview_endpoint, monkeypatch):
    harness = preview_endpoint

    def denied_origin(_request):
        harness.calls.append("origin")
        raise HTTPException(status_code=403, detail="Origin rejected")

    monkeypatch.setattr(main, "_check_origin", denied_origin)
    with pytest.raises(HTTPException) as error:
        harness.invoke()
    assert error.value.status_code == 403
    assert harness.calls == ["origin"]


def test_locked_terminal_cannot_preview_or_read_catalog(preview_endpoint, monkeypatch):
    harness = preview_endpoint

    def locked_operator(*_args):
        harness.calls.append("operator")
        raise HTTPException(status_code=423, detail="Enter personal PIN")

    monkeypatch.setattr(main, "_current_pos_operator", locked_operator)
    with pytest.raises(HTTPException) as error:
        harness.invoke()
    assert error.value.status_code == 423
    assert harness.calls == ["origin", "operator"]


def test_invalid_file_is_reported_as_422_without_accounting_changes(preview_endpoint, monkeypatch):
    harness = preview_endpoint
    before = deepcopy(harness.state)

    def invalid_file(_state, _encoded, _file_name):
        harness.calls.append("parser")
        raise ValueError("Некорректный файл поставки")

    monkeypatch.setattr(harness.parser_module, "preview", invalid_file)
    with pytest.raises(HTTPException) as error:
        harness.invoke({"file": "not-base64", "fileName": "broken.xlsx"})
    assert error.value.status_code == 422
    assert error.value.detail == "Некорректный файл поставки"
    assert harness.calls == ["origin", "operator", "workspace", "parser"]
    assert harness.state == before
