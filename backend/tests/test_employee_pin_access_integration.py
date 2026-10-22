"""Real employee/PIN lifecycle in an isolated PostgreSQL database only."""
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app import main
from test_billing_integration import system, DSN

pytestmark = pytest.mark.skipif(not DSN, reason="isolated PIN database required")


def employee(system, role="cashier", pin="0123", **changes):
    payload = {"display_name": "PIN test", "branch_id": "b1", "staff_role": role,
               "login": "pin-" + uuid4().hex, "password": "abcde", "pin": pin,
               **changes}
    response = system.client.post("/api/v1/employees", json=payload)
    assert response.status_code == 201, response.text
    return response.json(), payload


@pytest.fixture
def device(system):
    register = system.client.get("/api/v1/pos/registers").json()[0]
    client = TestClient(main.app, base_url="https://oimo.example", headers={
        "Origin": "https://oimo.example", "X-Ashkana-Client": "pos",
    })
    try:
        result = client.post("/api/v1/auth/login", json={
            "login": register["account_login"],
            "password": "Test-terminal-" + system.user["login"].split("@")[0],
        })
        assert result.status_code == 200, result.text
        yield client, register
    finally:
        client.close()


@pytest.mark.parametrize("role", ["branch_manager", "hall_admin", "waiter", "cashier", "production", "storekeeper", "marketer"])
def test_configured_pos_permission_accepts_pin_and_restores_operator(system, device, role):
    saved, _ = employee(system, role, permissions={"posAccess": True})
    reveal = system.client.post(f"/api/v1/employees/{saved['id']}/pin/reveal")
    assert reveal.status_code == 200 and reveal.json()["pin"] == "0123"
    client, _ = device
    assert saved["id"] in [row["id"] for row in client.get("/api/v1/pos/operators").json()]
    unlocked = client.post("/api/v1/pos/unlock", json={"pin": "0123"})
    assert unlocked.status_code == 200, unlocked.text
    assert unlocked.json()["operator"]["id"] == saved["id"]
    assert client.get("/api/v1/pos/operator").json()["operator"]["id"] == saved["id"]
    if role == "production":
        assert not unlocked.json()["operator"]["permissions"]["posCash"]


def test_wrong_pin_is_distinct_from_revoked_terminal_and_correct_pin_still_works(system, device):
    saved, _ = employee(system)
    client, register = device
    denied = client.post("/api/v1/pos/unlock", json={"pin": "9999"})
    assert denied.status_code == 401
    assert denied.json()["detail"]["code"] == "invalid_pin"
    assert denied.json()["detail"]["attemptsRemaining"] == 4
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/pos/unlock", json={"pin": "0123"}).json()["operator"]["id"] == saved["id"]
    with system.connect() as connection:
        row = connection.execute("SELECT pin_failed_attempts, pin_locked_until FROM auth_users WHERE id=%s", (register["id"],)).fetchone()
    assert row == {"pin_failed_attempts": 0, "pin_locked_until": None}


def test_reset_delete_and_recreate_use_current_pin_and_new_employee_identity(system, device):
    saved, payload = employee(system)
    client, _ = device
    assert client.post("/api/v1/pos/unlock", json={"pin": "0123"}).status_code == 200
    changed = system.client.put(f"/api/v1/employees/{saved['id']}", json={**payload, "pin": "4321"})
    assert changed.status_code == 200, changed.text
    assert client.get("/api/v1/pos/operator").json()["operator"] is None
    assert client.post("/api/v1/pos/unlock", json={"pin": "0123"}).status_code == 401
    assert client.post("/api/v1/pos/unlock", json={"pin": "4321"}).status_code == 200
    assert system.client.delete(f"/api/v1/employees/{saved['id']}").status_code == 200
    empty = client.post("/api/v1/pos/unlock", json={"pin": "4321"})
    assert empty.status_code == 409 and empty.json()["detail"]["code"] == "pos_no_pin_access"
    recreated, _ = employee(system, pin="4321", login=payload["login"])
    assert recreated["id"] != saved["id"]
    assert client.post("/api/v1/pos/unlock", json={"pin": "4321"}).json()["operator"]["id"] == recreated["id"]


def test_empty_or_disabled_pos_access_does_not_consume_pin_attempts(system, device):
    client, register = device
    for _ in range(6):
        denied = client.post("/api/v1/pos/unlock", json={"pin": "0123"})
        assert denied.status_code == 409 and denied.json()["detail"]["code"] == "pos_no_pin_access"
    saved, payload = employee(system, permissions={"posAccess": False})
    assert saved["id"] not in [row["id"] for row in client.get("/api/v1/pos/operators").json()]
    assert client.post("/api/v1/pos/unlock", json={"pin": "0123"}).status_code == 409
    with system.connect() as connection:
        assert connection.execute("SELECT pin_failed_attempts FROM auth_users WHERE id=%s", (register["id"],)).fetchone()["pin_failed_attempts"] == 0
    enabled = system.client.put(f"/api/v1/employees/{saved['id']}", json={**payload, "permissions": {"posAccess": True}})
    assert enabled.status_code == 200, enabled.text
    assert client.post("/api/v1/pos/unlock", json={"pin": "0123"}).status_code == 200


def test_wrong_branch_pin_never_grants_access(system, device):
    saved, _ = employee(system)
    client, _ = device
    assert client.post("/api/v1/pos/unlock", json={"pin": "0123"}).status_code == 200
    with system.connect() as connection:
        connection.execute("UPDATE auth_users SET branch_id='another-point' WHERE id=%s", (saved["id"],))
    assert client.get("/api/v1/pos/operator").json()["operator"] is None
    assert client.get("/api/v1/pos/operators").json() == []
    assert client.post("/api/v1/pos/unlock", json={"pin": "0123"}).status_code == 409


def test_five_incorrect_attempts_still_lock_terminal_until_expiry(system, device):
    employee(system)
    client, register = device
    assert [client.post("/api/v1/pos/unlock", json={"pin": "9999"}).status_code for _ in range(5)] == [401, 401, 401, 401, 429]
    assert client.post("/api/v1/pos/unlock", json={"pin": "0123"}).status_code == 429
    with system.connect() as connection:
        connection.execute("UPDATE auth_users SET pin_locked_until=now()-interval '1 second' WHERE id=%s", (register["id"],))
    assert client.post("/api/v1/pos/unlock", json={"pin": "0123"}).status_code == 200
