from app.security import hash_password, hash_pin, token_hash, verify_password, verify_pin
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.main import (
    _assert_managed_branch,
    _authorize_staff_action,
    _branch_manager,
    _company_admin_or_branch_manager,
    _protect_cost_data,
    _tenant_user,
    _update_branch_account,
    _user_session,
    _validate_tenant_access,
)
from app.workspace import new_tenant_state


class _Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row

    def fetchall(self):
        return [] if self.row is None else [self.row]


class _NewBranchConnection:
    def __init__(self):
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        if "SELECT slug FROM tenants" in query:
            return _Result({"slug": "test-company"})
        if "SELECT id, login, password_hash" in query:
            return _Result()
        if "SELECT id FROM auth_users" in query:
            assert params == ("new-point",)
            return _Result()
        return _Result()


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("Correct-horse-1")
    second = hash_password("Correct-horse-1")

    assert first != second
    assert "Correct-horse-1" not in first
    assert verify_password("Correct-horse-1", first)
    assert not verify_password("wrong-password", first)


def test_five_character_password_is_hashed_and_four_is_rejected() -> None:
    encoded = hash_password('abcde')
    assert verify_password('abcde', encoded)
    assert not verify_password('abcd', encoded)
    with pytest.raises(ValueError):
        hash_password('abcd')


def test_cashier_pin_is_salted_and_verifiable() -> None:
    encoded = hash_pin("4821")

    # A random hexadecimal hash may contain the four PIN digits by chance.
    assert encoded.startswith("pbkdf2_sha256$")
    assert encoded != "4821"
    assert encoded != hash_pin("4821")
    assert verify_pin("4821", encoded)
    assert not verify_pin("4822", encoded)


def test_session_token_hash_is_stable_and_not_plaintext() -> None:
    token = "secret-session-token"
    assert token_hash(token) == token_hash(token)
    assert token_hash(token) != token


def test_new_branch_login_duplicate_check_has_no_untyped_null_parameter() -> None:
    connection = _NewBranchConnection()
    state = {"branches": [{"id": "b2", "managerName": "Новый управляющий"}]}

    _update_branch_account(connection, "tenant-test", {
        "resolvedBranchId": "b2",
        "login": "new-point",
        "password": "Strong-password-2026",
    }, state)

    assert any("INSERT INTO auth_users" in query for query, _ in connection.calls)


def test_platform_owner_has_separate_route_and_no_tenant_workspace() -> None:
    platform_user = {
        "login": "platform", "role": "platform_owner", "display_name": "Владелец",
        "account_version": 1, "tenant_id": None,
    }

    session = _user_session(platform_user)

    assert session["route"].startswith("/platform")
    with pytest.raises(HTTPException) as error:
        _tenant_user(platform_user)
    assert error.value.status_code == 403


def test_new_tenant_starts_without_points_or_operational_documents() -> None:
    state = new_tenant_state()

    assert state["branches"] == []
    assert state["suppliers"] == []
    assert state["sales"] == []
    assert state["logisticsState"]["branchStocks"] == {}
    assert state["logisticsState"]["directOrders"] == []


def test_expired_trial_is_blocked() -> None:
    with pytest.raises(HTTPException) as error:
        _validate_tenant_access({
            "role": "owner",
            "tenant_status": "active",
            "subscription_status": "trialing",
            "trial_ends_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        })

    assert error.value.status_code == 403


def test_point_terminal_session_opens_pos() -> None:
    state = new_tenant_state()
    state["branches"] = [{"id": "b1", "number": 1, "name": "Столовая №1", "status": "active"}]
    terminal = {
        "login": "point.one", "role": "branch", "staff_role": "pos_terminal", "branch_id": "b1",
        "display_name": "Терминал точки", "account_version": 1, "tenant_id": "tenant-test",
    }

    session = _user_session(terminal, state)

    assert session["staffRole"] == "pos_terminal"
    assert session["roleLabel"] == "Касса"
    assert session["route"].startswith("/pos")


def test_staff_permissions_are_separated_by_job() -> None:
    cashier = {"role": "branch", "staff_role": "cashier"}
    storekeeper = {"role": "branch", "staff_role": "storekeeper"}
    production = {"role": "branch", "staff_role": "production"}
    terminal = {"role": "branch", "staff_role": "pos_terminal"}

    _authorize_staff_action(cashier, "sale.create")
    _authorize_staff_action(storekeeper, "supply.create")
    _authorize_staff_action(production, "batch.create")

    with pytest.raises(HTTPException) as cashier_error:
        _authorize_staff_action(cashier, "supply.create")
    with pytest.raises(HTTPException) as terminal_error:
        _authorize_staff_action(terminal, "sale.create")
    with pytest.raises(HTTPException) as production_error:
        _authorize_staff_action(production, "sale.create")
    with pytest.raises(HTTPException) as cost_error:
        _protect_cost_data(cashier)

    assert cashier_error.value.status_code == 403
    assert terminal_error.value.status_code == 403
    assert production_error.value.status_code == 403
    assert cost_error.value.status_code == 403


def test_owner_and_manager_register_permissions() -> None:
    manager = {
        "role": "branch", "staff_role": "branch_manager",
        "tenant_id": "tenant-test", "branch_id": "b1",
    }

    _company_admin_or_branch_manager(manager)
    _branch_manager(manager)
    _assert_managed_branch(manager, "b1")

    with pytest.raises(HTTPException) as other_point_error:
        _assert_managed_branch(manager, "b2")
    with pytest.raises(HTTPException) as employee_error:
        _company_admin_or_branch_manager({
            "role": "branch", "staff_role": "storekeeper",
            "tenant_id": "tenant-test", "branch_id": "b1",
        })
    _branch_manager({"role": "owner", "staff_role": "company_admin", "tenant_id": "tenant-test"})

    assert other_point_error.value.status_code == 403
    assert employee_error.value.status_code == 403
