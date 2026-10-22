"""Register settings and workspace read-permission regressions."""
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from app import main
from app.schemas import PosRegisterCreate, PosRegisterUpdate, WorkspaceActionInput
from pydantic import ValidationError
from app.security import verify_password
from app.workspace import apply_action, default_state, visible_state


OWNER = {"id": 1, "role": "owner", "tenant_id": "tenant-a", "login": "owner"}
BRANCH = {"id": 2, "role": "branch", "tenant_id": "tenant-a", "branch_id": "b1",
          "staff_role": "branch_manager", "login": "manager"}
REQUEST = Request({"type": "http", "path": "/api/v1/pos/registers/10",
                   "headers": [(b"origin", b"http://127.0.0.1:8000")]})


class RegisterConnection:
    def __init__(self, active=True):
        self.register = {"id": 10, "display_name": "Касса 1", "branch_id": "b1",
                         "login": "old-kassa",
                         "password_hash": "previous-password-hash", "is_active": active,
                         "account_version": 3}
        self.revoked = []
        self.events = []
        self.taken_login = False
        self.taken_company_code = False

    def transaction(self):
        return nullcontext()

    def execute(self, query, params):
        row = None
        if "SELECT id, display_name, branch_id" in query:
            row = deepcopy(self.register)
        elif "SET display_name = %s, branch_id = %s" in query:
            name, branch, password, active, version, identity = params
            assert identity == self.register["id"]
            self.register.update(display_name=name, branch_id=branch, password_hash=password,
                                 is_active=active, account_version=version)
        elif "UPDATE auth_sessions" in query:
            self.revoked.append(params[0])
        elif 'SELECT id FROM tenants WHERE lower(slug)' in query:
            row = {'id':'other-tenant'} if self.taken_company_code else None
        elif 'SELECT id FROM auth_users WHERE lower(login)' in query:
            row = {'id':99} if self.taken_login else None
        elif 'UPDATE auth_users SET login = %s' in query:
            login, identity, tenant = params
            assert identity == self.register['id'] and tenant == 'tenant-a'
            self.register['login'] = login
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: [])


@pytest.fixture
def register_environment(monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(allowed_origins=["http://127.0.0.1:8000"]))
    state = {"branches": [{"id": identity, "status": "active"} for identity in ("b1", "b2")]}
    monkeypatch.setattr(main, "_workspace_row", lambda *args, **kwargs: {"payload": state})
    monkeypatch.setattr(main, "_pos_register_record", lambda connection, *args: deepcopy(connection.register))
    monkeypatch.setattr(main, "_record_register_event", lambda connection, user, action, identity, payload: connection.events.append((action, identity, payload)))


@pytest.mark.parametrize("changes,initial_active,expected_version,revoked", [
    ({"name": "Новое имя"}, True, 3, False),
    ({"password": "Updated-password-2026"}, True, 4, True),
    ({"is_active": False}, True, 4, True),
    ({"password": "Updated-password-2026"}, False, 4, True),
    ({"branch_id": "b2"}, True, 4, True),
])
def test_register_settings_save_without_employee_pin_fields(register_environment, changes, initial_active, expected_version, revoked):
    connection = RegisterConnection(initial_active)
    payload = PosRegisterUpdate(**{"name": "Касса 1", "branch_id": "b1", **changes})
    saved = main.update_pos_register(10, payload, REQUEST, OWNER, connection)

    assert saved["display_name"] == payload.name
    assert saved["branch_id"] == payload.branch_id
    assert saved["is_active"] == payload.is_active
    assert saved["account_version"] == expected_version
    assert connection.revoked == ([10] if revoked else [])
    if payload.password:
        assert verify_password(payload.password, saved["password_hash"])
    else:
        assert saved["password_hash"] == "previous-password-hash"
    assert connection.events[0][0] == "pos_register.update"


def test_owner_can_change_terminal_login_without_changing_credentials_or_revoking_session(register_environment):
    connection=RegisterConnection()
    payload=PosRegisterUpdate(name='Касса 1',branch_id='b1',login=' UTRO-KASSA1 ')
    saved=main.update_pos_register(10,payload,REQUEST,OWNER,connection)
    assert saved['login']=='utro-kassa1'
    assert saved['password_hash']=='previous-password-hash' and saved['account_version']==3
    assert not connection.revoked
    assert connection.events[-1][2]['login']=='utro-kassa1'


@pytest.mark.parametrize('collision', ['taken_login','taken_company_code'])
def test_register_login_cannot_use_other_user_or_company_code(register_environment,collision):
    connection=RegisterConnection();setattr(connection,collision,True)
    with pytest.raises(HTTPException) as error:
        main.update_pos_register(10,PosRegisterUpdate(name='Касса 1',branch_id='b1',login='taken-name'),REQUEST,OWNER,connection)
    assert error.value.status_code==409
    assert connection.register['login']=='old-kassa' and not connection.events


def test_manager_cannot_change_terminal_login(register_environment):
    connection=RegisterConnection()
    with pytest.raises(HTTPException) as error:
        main.update_pos_register(10,PosRegisterUpdate(name='Касса 1',branch_id='b1',login='new-kassa'),REQUEST,BRANCH,connection)
    assert error.value.status_code==403 and connection.register['login']=='old-kassa'


@pytest.mark.parametrize('login',['ab','a'*65,'доставка','has space','<script>','x\ny'])
def test_register_login_validation(login):
    for schema in (PosRegisterCreate,PosRegisterUpdate):
        with pytest.raises(ValidationError):
            schema(name='Касса',branch_id='b1',login=login,password='safe-password')


def test_disabled_register_still_requires_password_to_reactivate(register_environment):
    connection = RegisterConnection(active=False)
    before = deepcopy(connection.register)
    with pytest.raises(HTTPException) as denied:
        main.update_pos_register(10, PosRegisterUpdate(name="Касса", branch_id="b1"), REQUEST, OWNER, connection)
    assert denied.value.status_code == 422
    assert connection.register == before
    assert not connection.revoked and not connection.events


def test_manager_cannot_move_register_to_another_branch(register_environment):
    connection = RegisterConnection()
    before = deepcopy(connection.register)
    with pytest.raises(HTTPException) as denied:
        main.update_pos_register(10, PosRegisterUpdate(name="Касса", branch_id="b2"), REQUEST, BRANCH, connection)
    assert denied.value.status_code == 403
    assert connection.register == before


@pytest.mark.parametrize("profile", [
    {"staff_role": "branch_manager"},
    {"staff_role": "pos_terminal"},
    {"staff_role": "cashier"},
    {"staff_role": "cashier", "access_permissions": {"employees": True}},
])
def test_cash_shift_counts_are_scoped_to_employee_branch(profile):
    state = default_state()
    counts = [{"id": "count-1", "branchId": "b1", "actor": {"name": "Свой кассир"}, "counts": []},
              {"id": "count-2", "branchId": "b2", "actor": {"name": "Другая точка"}, "counts": [{"actualWeight": 12}]}]
    state["logisticsState"]["cashShiftCounts"] = deepcopy(counts)

    view = visible_state(state, {**BRANCH, **profile})
    assert view["logisticsState"]["cashShiftCounts"] == counts[:1]
    assert visible_state(state, OWNER)["logisticsState"]["cashShiftCounts"] == counts
    assert state["logisticsState"]["cashShiftCounts"] == counts


def cost_state():
    state = default_state()
    state["logisticsState"]["custodyDocuments"] = [{"id": "custody-1", "branchId": "b1", "costPerKg": 20, "costAmount": 100}]
    state["sales"] = [{"id": "sale-1", "branchId": "b1", "total": 200, "items": [{
        "id": 201, "name": "Плов", "quantity": 1, "price": 200, "unitCost": 70,
        "ingredientAllocations": [{"itemId": "rice", "quantity": .2, "unitCost": 30}],
        "batchAllocations": [{"batchId": "batch-1", "responsibleName": "Повар",
                              "productionIngredients": [{"itemId": "rice", "quantity": .2, "unitCost": 30}]}],
    }]}]
    return state


@pytest.mark.parametrize("permissions", [{"employees": True}, {"reports": True}])
def test_custom_permissions_hide_costs_without_changing_history(permissions):
    state = cost_state()
    before = deepcopy(state)
    view = visible_state(state, {**BRANCH, "access_permissions": permissions})

    assert view["logisticsState"]["branchCosts"] == {"b1": {}}
    assert view["logisticsState"]["custodyDocuments"] == []
    if permissions.get("reports"):
        sale = view["sales"][0]
        assert sale["total"] == 200
        item = sale["items"][0]
        assert item["price"] == 200
        assert "unitCost" not in item
        assert "unitCost" not in item["ingredientAllocations"][0]
        assert "unitCost" not in item["batchAllocations"][0]["productionIngredients"][0]
        assert item["batchAllocations"][0]["responsibleName"] == "Повар"
    else:
        assert view["sales"] == []
    assert state == before


@pytest.mark.parametrize("permission", ["menu", "inventory", "production", "finance"])
def test_cost_permissions_retain_branch_costs_and_report_snapshots(permission):
    state = cost_state()
    view = visible_state(state, {**BRANCH, "access_permissions": {permission: True, "reports": True}})
    assert view["logisticsState"]["branchCosts"]["b1"] == state["logisticsState"]["branchCosts"]["b1"]
    assert view["logisticsState"]["custodyDocuments"] == state["logisticsState"]["custodyDocuments"]
    assert view["sales"][0]["items"][0]["unitCost"] == 70


@pytest.mark.parametrize("user", [OWNER, BRANCH, {**BRANCH, "staff_role": "pos_terminal"},
                                  {**BRANCH, "access_permissions": {"employees": True}}])
def test_replay_metadata_is_not_exposed_or_removed_from_stored_documents(user):
    state = default_state()
    metadata = {"requestId": "retry", "requestPayload": {"amount": 100}, "requestActorId": 2, "requestRegisterId": 10}
    state["logisticsState"]["supplies"] = [{"id": "supply-1", "branchId": "b1", "items": [], **metadata}]
    state["logisticsState"]["batches"] = [{"id": "batch-1", "branchId": "b1", "recipeId": 201,
                                            "actualWeight": 1, "status": "kitchen", **metadata}]
    state.setdefault("posState", {})["cashMovements"] = [{"id": "cash-1", "branchId": "b1", "amount": 100, **metadata}]
    before = deepcopy(state)
    view = visible_state(state, user)
    for records in (view["logisticsState"]["supplies"], view["logisticsState"]["batches"], view["posState"]["cashMovements"]):
        for row in records:
            assert not set(metadata).intersection(row)
    assert state == before


OPERATIONS = [
    ("supply.create", "cashier", {"supplierId": "supplier-frunze", "items": [{"itemId": "rice", "quantity": 1, "price": 10}]}),
    ("batch.create", "production", {"recipeId": 201, "weight": .4}),
    ("pos.cash.movement", "cashier", {"type": "deposit", "amount": 100, "comment": "Размен"}),
]


class NoBusinessWritesConnection:
    def transaction(self):
        return nullcontext()

    def execute(self, *args):
        pytest.fail("A committed replay or rejected request must not write state or another audit event")


@pytest.fixture
def committed_operation(request, monkeypatch):
    action, role, fields = request.param
    state = default_state()
    payload = {**fields, "requestId": "committed-operation"}
    operator = {"id": 2, "login": "employee", "display_name": "Сотрудник", "staff_role": role,
                "access_permissions": {"posAccess": True, "posSupply": True, "posCash": True}}
    terminal = {**BRANCH, "id": 10, "staff_role": "pos_terminal", "access_permissions": {}}
    actor = {**terminal, **operator, "register_id": 10, "shift_id": 20}
    entity = apply_action(state, actor, action, payload)
    monkeypatch.setattr(main, "_check_origin", lambda request: None)
    monkeypatch.setattr(main, "_workspace_row", lambda *args, **kwargs: {"version": 7, "payload": state})
    monkeypatch.setattr(main, "_current_pos_operator", lambda *args: operator)
    monkeypatch.setattr(main, "_current_pos_shift", lambda *args: None)
    http_request = Request({"type": "http", "path": "/api/v1/workspace/actions", "headers": [(b"x-ashkana-client", b"pos")]})
    return state, payload, operator, terminal, entity, http_request, action


@pytest.mark.parametrize("committed_operation", OPERATIONS, indirect=True)
def test_committed_operation_replays_after_shift_closed_without_more_writes(committed_operation):
    state, payload, operator, terminal, entity, request, action = committed_operation
    before = deepcopy(state)
    result = main.workspace_action(WorkspaceActionInput(action=action, payload=payload), request,
                                   terminal, "operator-token", NoBusinessWritesConnection())
    assert result["version"] == 7
    assert result["entity"] == {"type": entity[0], "id": entity[1]}
    assert state == before


@pytest.mark.parametrize("committed_operation", OPERATIONS, indirect=True)
@pytest.mark.parametrize("change,status", [("payload", 409), ("employee", 403), ("register", 403), ("new_request", 409)])
def test_closed_shift_replay_does_not_accept_changed_identity_payload_or_new_request(committed_operation, change, status):
    state, payload, operator, terminal, entity, request, action = committed_operation
    before = deepcopy(state)
    payload = deepcopy(payload)
    if change == "payload":
        payload["comment"] = "Другой запрос"
    elif change == "employee":
        operator["id"] = 99
    elif change == "register":
        terminal["id"] = 99
    else:
        payload["requestId"] = "new-operation"
    with pytest.raises(HTTPException) as denied:
        main.workspace_action(WorkspaceActionInput(action=action, payload=payload), request,
                              terminal, "operator-token", NoBusinessWritesConnection())
    assert denied.value.status_code == status
    assert state == before


@pytest.mark.parametrize("committed_operation", [OPERATIONS[0], OPERATIONS[2]], indirect=True)
def test_replay_still_requires_current_operator_permissions(committed_operation):
    state, payload, operator, terminal, entity, request, action = committed_operation
    operator["access_permissions"] = {"posAccess": True}
    before = deepcopy(state)
    with pytest.raises(HTTPException) as denied:
        main.workspace_action(WorkspaceActionInput(action=action, payload=payload), request,
                              terminal, "operator-token", NoBusinessWritesConnection())
    assert denied.value.status_code == 403
    assert state == before
