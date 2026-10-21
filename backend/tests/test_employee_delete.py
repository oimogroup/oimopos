"""Employee deletion permissions, outstanding work, and retained history.

EMPLOYEE_DELETE_INTEGRATION=1 runs PostgreSQL checks using temporary copies of
the migrated tables. All writes, including temporary DDL, are rolled back.
"""
from contextlib import nullcontext
from copy import deepcopy
from http.cookies import SimpleCookie
import os
from types import SimpleNamespace

from fastapi import HTTPException, Request, Response
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from app import main
from app.schemas import EmployeeCreate, EmployeeUpdate, LoginInput
from app.security import hash_password, token_hash


OWNER = {"id": 1, "role": "owner", "tenant_id": "tenant-a", "login": "owner"}
MANAGER = {"id": 2, "role": "branch", "tenant_id": "tenant-a", "branch_id": "b1",
           "staff_role": "branch_manager", "login": "manager"}
EMPLOYEE = {"id": 10, "role": "branch", "tenant_id": "tenant-a", "branch_id": "b1",
            "staff_role": "cashier", "login": "cashier", "display_name": "Кассир"}
REQUEST = Request({"type": "http", "path": "/api/v1/employees/10", "headers": [(b"origin", b"http://127.0.0.1:8000")]})


class Connection:
    def __init__(self, employee=None, open_cash_shift=False):
        self.employee = {**EMPLOYEE, **(employee or {})}
        self.open_cash_shift = open_cash_shift
        self.calls = []

    def transaction(self):
        return nullcontext()

    def execute(self, query, params):
        self.calls.append((query, params))
        row = None
        if "FROM auth_users" in query:
            candidate = self.employee
            if (params == (candidate["id"], candidate["tenant_id"])
                    and candidate["role"] == "branch" and candidate["staff_role"] != "pos_terminal"
                    and not candidate.get("deleted_at")):
                row = candidate
        elif "FROM pos_shifts" in query and self.open_cash_shift:
            row = {"id": 30}
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: [])


@pytest.fixture
def workspace(monkeypatch):
    state = {"branches": [{"id": "b1", "managerName": "Руководитель"}], "sales": [{"cashierId": 10}],
             "logisticsState": {"productionShifts": [], "custodyDocuments": [], "batches": []}}
    row = {"version": 4, "payload": state}
    monkeypatch.setattr(main, "_workspace_row", lambda *args, **kwargs: row)
    return row


@pytest.mark.parametrize("user", [
    {**MANAGER, "staff_role": "cashier"},
    {**MANAGER, "access_permissions": {"employees": False}},
    {**OWNER, "role": "platform_owner", "tenant_id": None},
    {**OWNER, "id": 10},
])
def test_delete_denies_missing_permissions_or_self(workspace, user):
    connection = Connection()
    with pytest.raises(HTTPException) as denied:
        main.delete_employee(10, REQUEST, user, connection)
    assert denied.value.status_code == 403
    assert not connection.calls


@pytest.mark.parametrize("employee", [{"branch_id": "b2"}, {"staff_role": "branch_manager"}])
def test_manager_cannot_delete_other_branch_or_manager(workspace, employee):
    connection = Connection(employee)
    with pytest.raises(HTTPException) as denied:
        main.delete_employee(10, REQUEST, MANAGER, connection)
    assert denied.value.status_code == 403
    assert not any(query.lstrip().startswith(("UPDATE", "INSERT")) for query, _ in connection.calls)


@pytest.mark.parametrize("employee", [
    {"tenant_id": "tenant-b"}, {"role": "owner"}, {"staff_role": "pos_terminal"}, {"deleted_at": "2026-01-01"},
])
def test_unavailable_employee_cannot_be_deleted(workspace, employee):
    connection = Connection(employee)
    with pytest.raises(HTTPException) as missing:
        main.delete_employee(10, REQUEST, OWNER, connection)
    assert missing.value.status_code == 404


@pytest.mark.parametrize("user", [OWNER, MANAGER])
def test_owner_and_authorized_manager_can_delete(workspace, user):
    state_before = deepcopy(workspace["payload"])
    connection = Connection()
    assert main.delete_employee(10, REQUEST, user, connection) == {"ok": True, "employee_id": 10, "version": 5}
    assert workspace["payload"]["sales"] == state_before["sales"]
    assert workspace["payload"]["logisticsState"] == state_before["logisticsState"]
    event = next(params for query, params in connection.calls if "'employee.delete'" in query)
    assert event[:7] == ("tenant-a", 5, user["id"], user["login"], user["role"], "b1", "10")
    assert event[-1].obj["displayName"] == "Кассир"


@pytest.mark.parametrize("kind", ["production", "cash", "transfer", "handover"])
def test_delete_rejects_open_personal_work_without_writes(workspace, kind):
    logistics = workspace["payload"]["logisticsState"]
    if kind == "production":
        logistics["productionShifts"] = [{"employeeId": "10", "status": "open"}]
    elif kind in {"transfer", "handover"}:
        logistics["custodyDocuments"] = [{"kind": kind, "status": "pending", "recipient": {"id": "10"}}]
    connection = Connection(open_cash_shift=kind == "cash")
    with pytest.raises(HTTPException) as conflict:
        main.delete_employee(10, REQUEST, OWNER, connection)
    assert conflict.value.status_code == 409
    assert not any(query.lstrip().startswith(("UPDATE", "INSERT")) for query, _ in connection.calls)


def test_closed_shifts_stock_and_group_handover_preserve_history_and_allow_delete(workspace):
    logistics = workspace["payload"]["logisticsState"]
    logistics["productionShifts"] = [{"employeeId": 10, "status": "closed"}, {"employeeId": 11, "status": "open"}]
    logistics["custodyDocuments"] = [
        {"kind": "transfer", "status": "accepted", "recipient": {"id": 10}},
        {"kind": "handover", "status": "pending", "previousResponsible": {"id": 10},
         "recipient": {"kind": "branch_cashiers"}},
        {"kind": "writeoff", "status": "pending", "responsible": {"id": 10}},
    ]
    logistics["batches"] = [{"kitchenResponsibleId": 10, "actualWeight": 5,
                              "servingLots": [{"responsibleId": 10, "acceptedWeight": 2}]}]
    before = deepcopy(logistics)
    assert main.delete_employee(10, REQUEST, OWNER, Connection())["ok"]
    assert logistics == before


def test_invalid_origin_cannot_delete(workspace):
    connection = Connection()
    with pytest.raises(HTTPException) as denied:
        main.delete_employee(10, Request({"type": "http", "headers": []}), OWNER, connection)
    assert denied.value.status_code == 403
    assert not connection.calls


@pytest.fixture
def database():
    if os.environ.get("EMPLOYEE_DELETE_INTEGRATION") != "1":
        pytest.skip("Opt-in PostgreSQL test against temporary copies of migrated tables")
    dsn = os.environ.get("EMPLOYEE_DELETE_TEST_DATABASE_URL") or main.get_settings().database_url
    connection = psycopg.connect(dsn, row_factory=dict_row)
    try:
        # LIKE INCLUDING ALL creates fresh identity sequences. No production rows,
        # sequences or constraints are changed; temp tables shadow only this session.
        for table in ("auth_users", "auth_sessions", "pos_operator_sessions", "pos_shifts",
                      "operational_state", "operational_events", "tenants", "tenant_subscriptions"):
            connection.execute(f"CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING ALL) ON COMMIT DROP")
        connection.execute("ALTER TABLE pos_shifts ADD FOREIGN KEY (opened_by_user_id) REFERENCES auth_users(id)")
        connection.execute("ALTER TABLE operational_events ADD FOREIGN KEY (actor_user_id) REFERENCES auth_users(id)")
        connection.execute("SELECT deleted_at FROM auth_users LIMIT 0")  # Requires migrations 014 and 015.
        connection.execute("INSERT INTO tenants (id, slug, name) VALUES ('tenant-a', 'delete-test', 'Тест удаления')")
        connection.execute("""INSERT INTO tenant_subscriptions (tenant_id, plan_code, status)
                              VALUES ('tenant-a', 'canteen', 'active')""")
        for account in (OWNER, MANAGER, EMPLOYEE, {**EMPLOYEE, "id": 90, "login": "register", "staff_role": "pos_terminal"}):
            connection.execute(
                """INSERT INTO auth_users (id, tenant_id, login, password_hash, role, staff_role, branch_id, display_name)
                   OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, 'test-hash', %s, %s, %s, %s)""",
                (account["id"], account["tenant_id"], account["login"], account["role"],
                 account.get("staff_role", "company_admin"), account.get("branch_id"), account.get("display_name", "Руководитель")),
            )
        # Only the copied TEMP table's fresh identity sequence is advanced.
        connection.execute("ALTER TABLE auth_users ALTER COLUMN id RESTART WITH 100")
        state = {"branches": [{"id": "b1", "name": "Тестовая точка", "status": "active", "managerName": "Руководитель"}],
                 "sales": [{"id": "sale-1", "cashierId": 10, "cashier": "Кассир", "total": 100}],
                 "logisticsState": {"productionShifts": [{"employeeId": 10, "status": "closed"}],
                                    "custodyDocuments": [{"id": "doc-1", "actor": {"id": 10, "name": "Кассир"}, "status": "recorded"}]}}
        connection.execute("INSERT INTO operational_state (tenant_id, version, payload) VALUES ('tenant-a', 4, %s)", (Jsonb(state),))
        for user_id, raw_token in ((10, "employee-token"), (90, "register-token")):
            connection.execute(
                "INSERT INTO auth_sessions (user_id, token_hash, account_version, expires_at) VALUES (%s, %s, 1, now() + interval '1 day')",
                (user_id, token_hash(raw_token)),
            )
        terminal_session = connection.execute("SELECT id FROM auth_sessions WHERE user_id = 90").fetchone()["id"]
        connection.execute(
            """INSERT INTO pos_operator_sessions (token_hash, terminal_session_id, employee_user_id, branch_id, expires_at)
               VALUES (%s, %s, 10, 'b1', now() + interval '1 day')""", (token_hash("operator-token"), terminal_session),
        )
        connection.execute("""INSERT INTO pos_shifts (tenant_id, register_user_id, branch_id, opened_by_user_id, closed_by_user_id, closed_at)
                              VALUES ('tenant-a', 90, 'b1', 10, 10, now())""")
        connection.execute("""INSERT INTO operational_events
          (tenant_id, state_version, actor_user_id, actor_login, actor_role, action, entity_type, entity_id, payload)
          VALUES ('tenant-a', 4, 10, 'cashier', 'branch', 'sale.create', 'sale', 'sale-1', '{"total":100}')""")
        yield connection
    finally:
        connection.rollback()
        connection.close()


def test_database_delete_revokes_access_retains_identity_and_all_history(database):
    before = main._workspace_row(database, "tenant-a")["payload"]
    employee_before = database.execute("SELECT * FROM auth_users WHERE id = 10").fetchone()
    events_before = database.execute("SELECT * FROM operational_events ORDER BY id").fetchall()
    shifts_before = main.list_pos_shifts(200, OWNER, database)
    assert main.delete_employee(10, REQUEST, OWNER, database) == {"ok": True, "employee_id": 10, "version": 5}
    employee = database.execute("SELECT * FROM auth_users WHERE id = 10").fetchone()
    assert employee["deleted_at"] is not None and not employee["is_active"]
    assert employee["account_version"] == employee_before["account_version"] + 1
    for field in ("id", "login", "display_name", "branch_id", "staff_role", "password_hash", "created_at"):
        assert employee[field] == employee_before[field]
    assert database.execute("SELECT revoked_at FROM auth_sessions WHERE user_id = 10").fetchone()["revoked_at"]
    assert database.execute("SELECT revoked_at FROM pos_operator_sessions WHERE employee_user_id = 10").fetchone()["revoked_at"]
    assert database.execute("SELECT revoked_at FROM auth_sessions WHERE user_id = 90").fetchone()["revoked_at"] is None
    assert main._workspace_row(database, "tenant-a")["payload"] == before
    assert main.list_pos_shifts(200, OWNER, database) == shifts_before
    assert database.execute("SELECT * FROM operational_events WHERE action = 'sale.create' ORDER BY id").fetchall() == events_before
    assert database.execute("SELECT count(*) AS total FROM operational_events WHERE action = 'employee.delete'").fetchone()["total"] == 1
    assert 10 not in {employee["id"] for employee in main.list_employees(OWNER, database)}
    with pytest.raises(HTTPException) as unauthorized:
        main.current_user(REQUEST, "employee-token", None, database)
    assert unauthorized.value.status_code == 401
    terminal_session = database.execute("SELECT id FROM auth_sessions WHERE user_id = 90").fetchone()["id"]
    terminal = {**EMPLOYEE, "id": 90, "staff_role": "pos_terminal", "session_id": terminal_session}
    assert 10 not in {employee["id"] for employee in main.list_pos_operators(terminal, database)}
    with pytest.raises(HTTPException) as locked:
        main._current_pos_operator(database, terminal, "operator-token")
    assert locked.value.status_code == 423
    for action in (
        lambda: main._employee_record(database, "tenant-a", 10),
        lambda: main.reveal_employee_pin(10, REQUEST, Response(), OWNER, database),
        lambda: main.update_employee(10, EmployeeUpdate(display_name="Кассир", branch_id="b1", staff_role="cashier", is_active=True), REQUEST, OWNER, database),
        lambda: main.delete_employee(10, REQUEST, OWNER, database),
    ):
        with pytest.raises(HTTPException) as missing:
            action()
        assert missing.value.status_code == 404
    with pytest.raises(psycopg.errors.CheckViolation), database.transaction():
        database.execute("UPDATE auth_users SET is_active = TRUE WHERE id = 10")
    database.execute("UPDATE auth_users SET login = 'CASHIER' WHERE id = 2")
    assert database.execute("SELECT login FROM auth_users WHERE id = 10").fetchone()["login"] == "cashier"
    assert database.execute("SELECT * FROM operational_events WHERE action = 'sale.create' ORDER BY id").fetchall() == events_before


def test_database_manager_name_and_version_update_on_delete(database):
    assert main.delete_employee(2, REQUEST, OWNER, database)["version"] == 5
    assert main._workspace_row(database, "tenant-a")["payload"]["branches"][0]["managerName"] == "Не назначен"


def test_database_open_shift_denial_is_atomic(database):
    database.execute("UPDATE pos_shifts SET closed_at = NULL, closed_by_user_id = NULL")
    with pytest.raises(HTTPException) as conflict:
        main.delete_employee(10, REQUEST, OWNER, database)
    assert conflict.value.status_code == 409
    assert database.execute("SELECT is_active, deleted_at FROM auth_users WHERE id = 10").fetchone() == {"is_active": True, "deleted_at": None}
    assert database.execute("SELECT revoked_at FROM auth_sessions WHERE user_id = 10").fetchone()["revoked_at"] is None
    assert main._workspace_row(database, "tenant-a")["version"] == 4
    assert database.execute("SELECT count(*) AS total FROM operational_events WHERE action = 'employee.delete'").fetchone()["total"] == 0


def test_database_repeated_login_reuse_creates_new_identity_and_keeps_old_history(database):
    original_password = "original-password-10"
    database.execute("UPDATE auth_users SET password_hash = %s WHERE id = 10", (hash_password(original_password),))
    original_employee = database.execute("SELECT * FROM auth_users WHERE id = 10").fetchone()
    history = main._workspace_row(database, "tenant-a")["payload"]
    events = database.execute("SELECT * FROM operational_events WHERE action = 'sale.create' ORDER BY id").fetchall()
    shifts = main.list_pos_shifts(200, OWNER, database)
    terminal_session = database.execute("SELECT id FROM auth_sessions WHERE user_id = 90").fetchone()["id"]
    terminal = {**EMPLOYEE, "id": 90, "staff_role": "pos_terminal", "session_id": terminal_session}
    previous_id = 10
    identities = {10}
    old_passwords = [original_password]
    old_tokens = ["employee-token"]

    for generation in (1, 2):
        main.delete_employee(previous_id, REQUEST, OWNER, database)
        new_password = f"replacement-password-{generation}"
        created = main.create_employee(
            EmployeeCreate(display_name=f"Новый сотрудник {generation}", branch_id="b1", staff_role="storekeeper",
                           login="CaShIeR", password=new_password),
            REQUEST, OWNER, database,
        )
        assert created["id"] not in identities
        assert created["login"] == "cashier" and created["is_active"]
        assert database.execute("""SELECT id FROM auth_users
                                   WHERE lower(login) = 'cashier' AND deleted_at IS NULL""").fetchall() == [{"id": created["id"]}]
        for old_id in identities:
            old = database.execute("SELECT login, deleted_at, is_active FROM auth_users WHERE id = %s", (old_id,)).fetchone()
            assert old["login"] == "cashier" and old["deleted_at"] is not None and not old["is_active"]
        for old_token in old_tokens:
            with pytest.raises(HTTPException) as unauthorized:
                main.current_user(REQUEST, old_token, None, database)
            assert unauthorized.value.status_code == 401
        with pytest.raises(HTTPException) as locked:
            main._current_pos_operator(database, terminal, "operator-token")
        assert locked.value.status_code == 423
        for old_password in old_passwords:
            rejected_response = Response()
            with pytest.raises(HTTPException) as unauthorized:
                main.login(LoginInput(login="CASHIER", password=old_password), rejected_response, REQUEST, database)
            assert unauthorized.value.status_code == 401
            assert "set-cookie" not in rejected_response.headers

        response = Response()
        logged_in = main.login(LoginInput(login="CaShIeR", password=new_password), response, REQUEST, database)
        assert logged_in["session"]["name"] == created["display_name"]
        cookie = SimpleCookie(response.headers["set-cookie"])[main.SESSION_COOKIE].value
        authenticated = main.current_user(REQUEST, cookie, None, database)
        assert authenticated["id"] == created["id"]
        assert authenticated["staff_role"] == "storekeeper"
        assert database.execute("SELECT user_id FROM auth_sessions WHERE token_hash = %s", (token_hash(cookie),)).fetchone()["user_id"] == created["id"]
        assert main._workspace_row(database, "tenant-a")["payload"] == history
        assert main.list_pos_shifts(200, OWNER, database) == shifts
        assert database.execute("SELECT * FROM operational_events WHERE action = 'sale.create' ORDER BY id").fetchall() == events
        archived_employee = database.execute("SELECT * FROM auth_users WHERE id = 10").fetchone()
        for field in ("id", "login", "display_name", "branch_id", "staff_role", "password_hash", "created_at"):
            assert archived_employee[field] == original_employee[field]
        identities.add(created["id"])
        previous_id = created["id"]
        old_passwords.append(new_password)
        old_tokens.append(cookie)

    assert len(identities) == 3
    assert main._workspace_row(database, "tenant-a")["version"] == 8
    assert database.execute("SELECT actor_user_id FROM operational_events WHERE action = 'sale.create'").fetchone()["actor_user_id"] == 10


@pytest.mark.parametrize("active", [True, False])
def test_database_live_or_disabled_employee_still_reserves_case_insensitive_login(database, active):
    database.execute("UPDATE auth_users SET is_active = %s WHERE id = 10", (active,))
    before = main._workspace_row(database, "tenant-a")
    with pytest.raises(HTTPException) as conflict:
        main.create_employee(
            EmployeeCreate(display_name="Другой сотрудник", branch_id="b1", staff_role="storekeeper",
                           login="CaShIeR", password="another-password"),
            REQUEST, OWNER, database,
        )
    assert conflict.value.status_code == 409
    assert database.execute("SELECT id, is_active, deleted_at FROM auth_users WHERE lower(login) = 'cashier'").fetchall() == [
        {"id": 10, "is_active": active, "deleted_at": None},
    ]
    assert main._workspace_row(database, "tenant-a") == before
    assert database.execute("SELECT count(*) AS total FROM operational_events WHERE action = 'employee.create'").fetchone()["total"] == 0
    # Exercise PostgreSQL's case-insensitive constraint without schema normalization.
    with pytest.raises(psycopg.errors.UniqueViolation), database.transaction():
        database.execute("UPDATE auth_users SET login = 'CASHIER' WHERE id = 2")
