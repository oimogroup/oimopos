from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException, Request, Response

from app import main
from app.schemas import PosUnlockInput
from app.security import hash_pin


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.row or []


class OperatorConnection:
    def __init__(self):
        self.calls = []
        self.terminal = {"id": 1, "pin_failed_attempts": 0, "pin_locked": False}
        self.extra = []
        self.employee = {
            "id": 42, "display_name": "Кассир", "staff_role": "cashier",
            "access_permissions": {}, "pin_hash": hash_pin("4821"),
            "pin_failed_attempts": 0, "pin_locked": False,
        }

    def transaction(self):
        return nullcontext()

    def commit(self):
        self.calls.append(("COMMIT", ()))

    def execute(self, query, params):
        self.calls.append((query, params))
        if "FROM auth_users WHERE id" in query:
            return Result(self.terminal)
        if "FROM auth_users" in query:
            return Result([self.employee, *self.extra])
        return Result()


def terminal(expires_at):
    return {
        "id": 1, "role": "branch", "staff_role": "pos_terminal",
        "session_id": 10, "branch_id": "b1", "tenant_id": "test",
        "session_expires_at": expires_at,
    }


@pytest.mark.parametrize("hours_left", [2, 48, 168])
@pytest.mark.parametrize("zone", [timezone.utc, ZoneInfo("UTC"), ZoneInfo("Asia/Almaty")])
def test_cashier_session_and_cookie_last_until_terminal_session_expires(hours_left, zone):
    expires_at = (datetime.now(zone) + timedelta(hours=hours_left)).replace(microsecond=0)
    connection = OperatorConnection()
    response = Response()
    request = Request({"type": "http", "headers": [(b"origin", b"http://127.0.0.1:8000")]})

    result = main.unlock_pos(PosUnlockInput(pin="4821"), response, request, terminal(expires_at), connection)

    assert result["operator"]["id"] == 42
    inserted = next(params for query, params in connection.calls if "INSERT INTO pos_operator_sessions" in query)
    assert inserted[-1] == expires_at
    cookie = SimpleCookie(response.headers["set-cookie"])[main.POS_OPERATOR_COOKIE]
    assert parsedate_to_datetime(cookie["expires"]) == expires_at
    assert cookie["httponly"] and cookie["samesite"] == "strict"


def test_wrong_pin_does_not_create_or_extend_cashier_session():
    connection = OperatorConnection()
    response = Response()
    request = Request({"type": "http", "headers": [(b"origin", b"http://127.0.0.1:8000")]})
    with pytest.raises(HTTPException) as error:
        main.unlock_pos(PosUnlockInput(pin="0000"), response, request, terminal(datetime.now(timezone.utc) + timedelta(days=7)), connection)
    assert error.value.status_code == 401
    assert error.value.detail["code"] == "invalid_pin"
    assert error.value.detail["attemptsRemaining"] == 4
    assert any(query == "COMMIT" for query, _ in connection.calls)
    assert not any("INSERT INTO pos_operator_sessions" in query for query, _ in connection.calls)
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("token", [None, "expired-or-revoked-token"])
def test_missing_or_invalid_cashier_session_cannot_close_shift(token):
    connection = OperatorConnection()
    with pytest.raises(HTTPException) as error:
        main._current_pos_operator(connection, terminal(datetime.now(timezone.utc)), token)
    assert error.value.status_code == 423
    assert not any("UPDATE pos_operator_sessions" in query for query, _ in connection.calls)


def unlock(connection, **payload):
    return main.unlock_pos(PosUnlockInput(**payload), Response(),
        Request({"type": "http", "headers": [(b"origin", b"http://127.0.0.1:8000")]}),
        terminal(datetime.now(timezone.utc) + timedelta(days=1)), connection)


def test_pin_identifies_employee_even_if_legacy_client_supplies_wrong_id():
    connection = OperatorConnection()
    assert unlock(connection, pin="4821", employee_id=99)["operator"]["id"] == 42
    query, params = next((q, p) for q, p in connection.calls if "ORDER BY id" in q)
    assert params == ("test", "b1")
    assert "AND is_active" in query and "branch_id = %s" in query


def test_duplicate_pin_never_selects_first_employee():
    connection = OperatorConnection()
    connection.extra = [{**connection.employee, "id": 43}]
    with pytest.raises(HTTPException) as error:
        unlock(connection, pin="4821")
    assert error.value.status_code == 409
    assert not any("INSERT INTO pos_operator_sessions" in q for q, _ in connection.calls)


def test_production_pin_keeps_production_only_permissions():
    connection = OperatorConnection()
    connection.employee["staff_role"] = "production"
    operator = unlock(connection, pin="4821")["operator"]
    assert operator["staffRole"] == "production"
    assert operator["permissions"]["production"]
    assert not operator["permissions"]["posCash"]


def test_disabled_pos_access_cannot_unlock():
    connection = OperatorConnection()
    connection.employee["access_permissions"] = {"posAccess": False}
    with pytest.raises(HTTPException) as error:
        unlock(connection, pin="4821")
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "pos_no_pin_access"
    assert not any("SET pin_failed_attempts" in query for query, _ in connection.calls)


def test_fifth_wrong_pin_locks_terminal():
    connection = OperatorConnection()
    connection.terminal["pin_failed_attempts"] = 4
    with pytest.raises(HTTPException) as error:
        unlock(connection, pin="0000")
    assert error.value.status_code == 429
    assert any("INTERVAL '5 minutes'" in q and p == (1,) for q, p in connection.calls)


def test_locked_terminal_does_not_check_employees():
    connection = OperatorConnection()
    connection.terminal["pin_locked"] = True
    with pytest.raises(HTTPException) as error:
        unlock(connection, pin="4821")
    assert error.value.status_code == 429
    assert len(connection.calls) == 1


def test_employee_pin_must_be_unique_in_branch():
    connection = OperatorConnection()
    with pytest.raises(HTTPException) as error:
        main._assert_unique_employee_pin(connection, "test", "b1", "4821", 50)
    assert error.value.status_code == 409
    assert connection.calls[0][1] == ("test", "b1", 50)
    main._assert_unique_employee_pin(connection, "test", "b1", "7319", 50)
