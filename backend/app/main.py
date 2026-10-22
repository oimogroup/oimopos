from __future__ import annotations
from . import production_shifts

from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
from uuid import uuid4
from urllib.parse import quote

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg import Connection
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation
from psycopg.types.json import Jsonb

from . import custody
from .transfer_history import build_transfer_history, build_cash_shift_history
from .config import get_settings
from .database import close_pool, get_connection, open_pool, pool
from .domain import DomainError, calculate_unit_costs, find_cycle
from .schemas import (
    PlanPriceUpdate,
    EmployeeCreate,
    EmployeeUpdate,
    ItemType,
    LoginInput,
    PosRegisterCreate,
    PosRegisterUpdate,
    PosShiftClose,
    PosShiftOpen,
    PosUnlockInput,
    TechnicalCardCreate,
    TechnicalCardUpdate,
    TenantCreate,
    TenantDelete,
    TenantOwnerAccessUpdate,
    TenantUpdate,
    WorkspaceActionInput,
)
from .security import hash_password, hash_pin, new_session_token, token_hash, verify_password, verify_pin
from .workspace import sale_payment_amount, WorkspaceError, apply_action, new_tenant_state, visible_state, production_context


SESSION_COOKIE = "ashkana_session"
POS_SESSION_COOKIE = "ashkana_pos_session"
POS_OPERATOR_COOKIE = "ashkana_pos_operator"

ADMIN_PERMISSION_KEYS = ("reports", "menu", "inventory", "production", "finance", "employees", "registers", "settings")
PERMISSION_DEFAULTS = {
    "branch_manager": {"posAccess": True, "posRefunds": True, "posCash": True, "posSupply": True, **{key: True for key in ADMIN_PERMISSION_KEYS}},
    "hall_admin": {"posAccess": True, "posRefunds": True, "posCash": True},
    "waiter": {"posAccess": True},
    "cashier": {"posAccess": True, "posCash": True},
    "storekeeper": {"inventory": True},
    "production": {"production": True, "posAccess": True, "posSupply": True},
    "marketer": {"reports": True, "menu": True},
    "pos_terminal": {},
}
ALL_PERMISSION_KEYS = ("posAccess", "posRefunds", "posCash", "posSupply", *ADMIN_PERMISSION_KEYS)


def _normalized_permissions(staff_role: str | None, raw: dict | None = None) -> dict[str, bool]:
    permissions = {key: False for key in ALL_PERMISSION_KEYS}
    permissions.update(PERMISSION_DEFAULTS.get(staff_role or "", {}))
    if isinstance(raw, dict) and raw:
        permissions.update({key: bool(raw.get(key)) for key in ALL_PERMISSION_KEYS})
    if staff_role == "production":
        permissions.update({key: False for key in ADMIN_PERMISSION_KEYS})
        permissions.update(posAccess=True, posSupply=True, production=True, posRefunds=False, posCash=False)
    return permissions


def _user_permissions(user: dict) -> dict[str, bool]:
    return _normalized_permissions(user.get("staff_role"), user.get("access_permissions"))


def _has_permission(user: dict, permission: str) -> bool:
    return user.get("role") == "owner" or bool(_user_permissions(user).get(permission))


def _has_admin_access(user: dict) -> bool:
    if user.get("staff_role") == "production":
        return False
    return user.get("role") == "owner" or any(_has_permission(user, key) for key in ADMIN_PERMISSION_KEYS)


def _ensure_operational_data() -> None:
    settings = get_settings()
    with pool.connection() as connection, connection.transaction():
        login = settings.platform_initial_login.lower()
        existing = connection.execute(
            "SELECT id FROM auth_users WHERE lower(login) = lower(%s) AND deleted_at IS NULL LIMIT 1",
            (login,),
        ).fetchone()
        if not existing:
            connection.execute(
                """
                INSERT INTO auth_users (login, password_hash, role, staff_role, tenant_id, branch_id, display_name)
                VALUES (%s, %s, 'platform_owner', 'platform_owner', NULL, NULL, 'Владелец платформы')
                """,
                (login, hash_password(settings.platform_initial_password)),
            )


@asynccontextmanager
async def lifespan(_: FastAPI):
    open_pool()
    _ensure_operational_data()
    from .mailer import start_worker
    mail_stop, mail_thread = start_worker(pool)
    from .payment_reconciliation import start_worker as start_payment_worker
    payment_stop,payment_thread=start_payment_worker(pool)
    try:
        yield
    finally:
        mail_stop.set()
        payment_stop.set()
        await asyncio.to_thread(mail_thread.join, 20)
        await asyncio.to_thread(payment_thread.join, 20)
        close_pool()


app = FastAPI(
    title="Oimo API",
    version="1.0.0",
    description="Локальный API кассы, склада и технологических карт.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Actor", "X-Ashkana-Client", "X-Oimo-Register", "X-Oimo-Tenant", "X-Oimo-Operator"],
)


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin or origin not in get_settings().allowed_origins:
        raise HTTPException(status_code=403, detail="Недопустимый источник запроса")


def _workspace_row(connection: Connection, tenant_id: str, *, for_update: bool = False) -> dict:
    suffix = " FOR UPDATE" if for_update else ""
    row = connection.execute(
        f"SELECT version, payload, updated_at FROM operational_state WHERE tenant_id = %s{suffix}",
        (tenant_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=503, detail="Операционное хранилище не инициализировано")
    return row


def _tenant_user(user: dict) -> str:
    if user["role"] == "platform_owner" or not user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Выберите рабочее место компании")
    return str(user["tenant_id"])


def _authorize_staff_action(user: dict, action: str) -> None:
    if user["role"] != "branch":
        return
    if action in {"work.shift.open", "work.shift.close"}:
        if not _has_permission(user, "posAccess"):
            raise HTTPException(403, "Нет доступа к отметке рабочего времени")
        return
    if user.get("staff_role") == "production" and (action.startswith("sale.") or action.startswith("pos.")):
        raise HTTPException(status_code=403, detail="Сотрудник производства не может выполнять продажи и кассовые операции")
    if action in {"pos.receiving.accept", "pos.receiving.reject", "pos.serving.writeoff", "pos.serving.surplus"}:
        if user.get("staff_role") not in {"cashier", "branch_manager", "hall_admin"} or not user.get("shift_id"):
            raise HTTPException(status_code=403, detail="Приёмка доступна кассиру на открытой смене")
        return
    pos_permissions = {
        "sale.import": "posAccess", "sale.create": "posAccess", "pos.order.save": "posAccess", "pos.order.remove": "posAccess", "pos.order.status": "posAccess",
        "pos.customer.upsert": "posAccess", "sale.refund": "posRefunds", "pos.cash.movement": "posCash",
    }
    if action == "supply.create" and user.get("register_id"):
        required = "posSupply"
    elif action in pos_permissions:
        required = pos_permissions[action]
    elif action == "settings.update":
        required = "settings"
    elif action.startswith("finance."):
        required = "finance"
    elif action in {"category.upsert", "station.upsert", "preparation.upsert", "ingredient.upsert", "ingredient.import", "product.upsert", "product.group.upsert", "recipe.upsert", "catalog.delete"}:
        required = "menu"
    elif action in {"supplier.upsert", "supply.create", "order.create", "order.approve", "order.send", "order.receive", "transfer.create", "transfer.approve", "transfer.dispatch", "transfer.receive", "inventory.start", "inventory.save", "inventory.submit", "inventory.cancel", "inventory.return", "inventory.post"}:
        required = "inventory"
    elif action.startswith("production.shift.") or action.startswith("custody.") or action in {"batch.create", "batch.transfer", "batch.close", "batch.release", "batch.serve", "batch.serve_many"}:
        required = "production"
    else:
        raise HTTPException(status_code=403, detail="Это действие недоступно сотруднику")
    if not _has_permission(user, required):
        raise HTTPException(status_code=403, detail="Для действия не выдано необходимое право доступа")


def _protect_cost_data(user: dict) -> None:
    if user["role"] == "branch" and not any(_has_permission(user, key) for key in ("menu", "inventory", "production", "finance")):
        raise HTTPException(status_code=403, detail="Себестоимость недоступна кассиру")


def _user_session(user: dict, state: dict | None = None) -> dict:
    if user["role"] == "platform_owner":
        return {
            "login": user["login"], "role": "platform_owner", "name": user["display_name"],
            "roleLabel": "Владелец платформы", "scope": "Все клиенты SaaS", "initials": "ВП",
            "accountVersion": user["account_version"], "route": "/platform",
        }
    if state is None:
        raise HTTPException(status_code=503, detail="Рабочее пространство компании не загружено")
    tenant = {
        "tenantId": user["tenant_id"], "tenantName": user.get("tenant_name"),
        "tenantSlug": user.get("tenant_slug"), "planCode": user.get("plan_code"),
        "serviceMode": "restaurant" if user.get("plan_code") == "restaurant" else "canteen",
        "subscriptionStatus": user.get("subscription_status"),
        "trialEndsAt": user.get("trial_ends_at"), "maxBranches": user.get("max_branches"),
        "currentPeriodEndsAt": user.get("current_period_ends_at"), "billingRequired": bool(_subscription_issue(user)),
        "emailVerified": bool(user.get("email_verified_at")),
    }
    if user["role"] == "owner":
        return {
            "login": user["login"], "role": "owner", "name": user["display_name"],
            "roleLabel": "Администратор компании", "scope": user.get("tenant_name") or "Аккаунт", "initials": "АК",
            "accountVersion": user["account_version"], "route": "/billing" if tenant["billingRequired"] else "/admin#dashboard", **tenant,
        }
    branch = next((entry for entry in state["branches"] if entry["id"] == user["branch_id"]), None)
    if not branch or branch.get("status") != "active":
        raise HTTPException(status_code=403, detail="Точка отключена")
    staff_role = user.get("staff_role") or "branch_manager"
    permissions = _user_permissions(user)
    staff_profiles = {
        "pos_terminal": ("Касса", "/pos"),
        "branch_manager": ("Руководитель", "/admin#dashboard"),
        "hall_admin": ("Администратор зала", "/pos"),
        "waiter": ("Официант", "/pos"),
        "storekeeper": ("Кладовщик", "/admin#inventory/supplies"),
        "production": ("Сотрудник производства", "/pos"),
        "marketer": ("Маркетолог", "/admin#reports/sales"),
        "cashier": ("Кассир", "/pos"),
    }
    role_label, legacy_route = staff_profiles.get(staff_role, staff_profiles["branch_manager"])
    route = legacy_route if any(permissions.get(key) for key in ADMIN_PERMISSION_KEYS) else "/pos"
    initials = "".join(word[0] for word in user["display_name"].split()[:2]).upper() or f"Т{branch['number']}"
    return {
        "login": user.get("tenant_slug") if staff_role == "pos_terminal" else user["login"],
        "role": "branch", "name": user["display_name"],
        "roleLabel": role_label, "staffRole": staff_role, "permissions": permissions, "scope": branch["name"], "initials": initials,
        "branchId": branch["id"], "accountVersion": user["account_version"],
        **({"registerId": user.get("id"), "registerName": user["display_name"]} if staff_role == "pos_terminal" else {}),
        "route": route, **tenant,
    }


def _subscription_issue(user: dict) -> str:
    if user.get('role') == 'platform_owner':
        return ''
    status = user.get('subscription_status')
    if status == 'canceled':
        return 'Подписка компании завершена'
    if status == 'past_due':
        return 'Требуется оплатить подписку компании'
    end = user.get('trial_ends_at') if status == 'trialing' else user.get('current_period_ends_at') if status == 'active' else None
    if end and end <= datetime.now(timezone.utc):
        return 'Пробный период завершён. Требуется активировать подписку' if status == 'trialing' else 'Оплаченный период завершён. Требуется продлить подписку'
    return ''


def _validate_tenant_access(user: dict, *, allow_billing: bool = False) -> None:
    if user["role"] == "platform_owner":
        return
    if user.get("tenant_status") != "active":
        raise HTTPException(status_code=403, detail="Компания временно недоступна. Обратитесь к владельцу сервиса")
    if issue := _subscription_issue(user):
        if not (allow_billing and user.get('role') == 'owner'):
            raise HTTPException(status_code=403, detail=issue)


def current_user(
    request: Request,
    ashkana_session: str | None = Cookie(default=None),
    ashkana_pos_session: str | None = Cookie(default=None),
    connection: Connection = Depends(get_connection),
) -> dict:
    session_token = ashkana_pos_session if request.headers.get("x-ashkana-client", "").lower() == "pos" else ashkana_session
    if not session_token:
        raise HTTPException(status_code=401, detail="Требуется вход")
    row = connection.execute(
        """
        SELECT u.id, u.login, u.email_verified_at, u.role, u.staff_role, u.access_permissions, u.phone, u.tenant_id, u.branch_id, u.display_name, u.is_active, u.account_version,
               s.id AS session_id, s.expires_at AS session_expires_at,
               t.name AS tenant_name, t.slug AS tenant_slug, t.status AS tenant_status,
               subscription.plan_code, subscription.status AS subscription_status, subscription.max_branches,
               subscription.trial_ends_at, subscription.current_period_ends_at
        FROM auth_sessions s
        JOIN auth_users u ON u.id = s.user_id
        LEFT JOIN tenants t ON t.id = u.tenant_id
        LEFT JOIN tenant_subscriptions subscription ON subscription.tenant_id = u.tenant_id
        WHERE s.token_hash = %s
          AND s.revoked_at IS NULL
          AND s.expires_at > CURRENT_TIMESTAMP
          AND u.is_active
          AND s.account_version = u.account_version
        """,
        (token_hash(session_token),),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Сессия истекла или доступ изменён")
    if request.headers.get('x-ashkana-client', '').lower() == 'pos':
        expected_register = request.headers.get('x-oimo-register')
        expected_tenant = request.headers.get('x-oimo-tenant')
        if (expected_register and expected_register != str(row['id'])) or (expected_tenant and expected_tenant != str(row['tenant_id'])):
            raise HTTPException(403, 'В браузере активирована другая касса. Вернитесь к исходной кассе для отправки её чеков.')
    if row.get("staff_role") == "production" and request.headers.get("x-ashkana-client", "").lower() != "pos" and request.url.path not in {"/api/v1/auth/me", "/api/v1/auth/logout"}:
        raise HTTPException(status_code=403, detail="Сотруднику производства доступен только терминал")
    _validate_tenant_access(row, allow_billing=request.url.path in {"/api/v1/auth/me", "/api/v1/auth/logout", "/api/v1/auth/email", "/api/v1/auth/email/send"} or request.url.path.startswith("/api/v1/billing"))
    if row["role"] == "branch":
        state = _workspace_row(connection, row["tenant_id"])["payload"]
        branch = next((entry for entry in state["branches"] if entry.get("id") == row["branch_id"]), None)
        if not branch or branch.get("status") != "active":
            raise HTTPException(status_code=403, detail="Точка отключена")
    connection.execute("UPDATE auth_sessions SET last_seen_at = CURRENT_TIMESTAMP WHERE id = %s", (row["session_id"],))
    result = dict(row)
    if request.headers.get('x-ashkana-client', '').lower() == 'pos':
        result['_expected_operator_id'] = request.headers.get('x-oimo-operator')
    return result


def _ensure_register_password_unique(
    connection: Connection, tenant_id: str, password: str, *, exclude_id: int | None = None,
) -> None:
    exclude_clause = " AND id <> %s" if exclude_id is not None else ""
    params = (tenant_id, exclude_id) if exclude_id is not None else (tenant_id,)
    rows = connection.execute(
        f"""
        SELECT id, password_hash
        FROM auth_users
        WHERE tenant_id = %s AND role = 'branch' AND staff_role = 'pos_terminal' AND is_active
          {exclude_clause}
        """,
        params,
    ).fetchall()
    if any(verify_password(password, row["password_hash"]) for row in rows):
        raise HTTPException(status_code=409, detail="У другой кассы уже используется такой пароль")


def _update_branch_account(connection: Connection, tenant_id: str, payload: dict, state: dict) -> None:
    branch_id = payload.get("resolvedBranchId")
    branch = next((entry for entry in state["branches"] if entry["id"] == branch_id), None)
    if not branch:
        raise HTTPException(status_code=422, detail="Точка не найдена после сохранения")
    password = str(payload.get("password", ""))
    tenant = connection.execute("SELECT slug FROM tenants WHERE id = %s", (tenant_id,)).fetchone()
    if not tenant:
        raise HTTPException(status_code=422, detail="Компания не найдена")
    branch["login"] = tenant["slug"]
    existing = connection.execute(
        "SELECT id, login, password_hash, account_version, is_active FROM auth_users WHERE tenant_id = %s AND branch_id = %s AND role = 'branch' AND staff_role = 'pos_terminal' ORDER BY id LIMIT 1",
        (tenant_id, branch_id),
    ).fetchone()
    if not existing:
        if len(password) < 8:
            raise HTTPException(status_code=422, detail="Для основной кассы нужен пароль не короче 8 символов")
        _ensure_register_password_unique(connection, tenant_id, password)
        connection.execute(
            """
            INSERT INTO auth_users (login, password_hash, role, staff_role, tenant_id, branch_id, display_name)
            VALUES (%s, %s, 'branch', 'pos_terminal', %s, %s, %s)
            """,
            (f"kassa-{uuid4().hex[:12]}", hash_password(password), tenant_id, branch_id, "Основная касса"),
        )
        return
    should_be_active = branch.get("status") == "active"
    if password:
        _ensure_register_password_unique(connection, tenant_id, password, exclude_id=existing["id"])
    access_changed = bool(password) or bool(existing["is_active"]) != should_be_active
    password_hash = hash_password(password) if password else existing["password_hash"]
    version = existing["account_version"] + (1 if access_changed else 0)
    connection.execute(
        """
        UPDATE auth_users
        SET password_hash = %s, is_active = %s, account_version = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (password_hash, should_be_active, version, existing["id"]),
    )
    if access_changed:
        connection.execute("UPDATE auth_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = %s AND revoked_at IS NULL", (existing["id"],))


def login(payload: LoginInput, response: Response, request: Request, connection: Connection = Depends(get_connection)) -> dict:
    _check_origin(request)
    user = connection.execute(
        """
        SELECT u.id, u.login, u.email_verified_at, u.password_hash, u.role, u.staff_role, u.access_permissions, u.phone, u.tenant_id, u.branch_id, u.display_name,
               u.is_active, u.account_version, t.name AS tenant_name, t.slug AS tenant_slug,
               t.status AS tenant_status, subscription.plan_code,
               subscription.status AS subscription_status, subscription.max_branches,
               subscription.trial_ends_at, subscription.current_period_ends_at
        FROM auth_users u
        LEFT JOIN tenants t ON t.id = u.tenant_id
        LEFT JOIN tenant_subscriptions subscription ON subscription.tenant_id = u.tenant_id
        WHERE lower(u.login) = lower(%s) AND u.staff_role <> 'pos_terminal'
          AND u.deleted_at IS NULL
        """,
        (payload.login,),
    ).fetchone()
    if not user or not user["is_active"] or not verify_password(payload.password, user["password_hash"]):
        candidates = connection.execute(
            """
            SELECT u.id, u.login, u.email_verified_at, u.password_hash, u.role, u.staff_role, u.access_permissions, u.phone, u.tenant_id, u.branch_id, u.display_name,
                   u.is_active, u.account_version, t.name AS tenant_name, t.slug AS tenant_slug,
                   t.status AS tenant_status, subscription.plan_code,
                   subscription.status AS subscription_status, subscription.max_branches,
                   subscription.trial_ends_at, subscription.current_period_ends_at
            FROM auth_users u
            JOIN tenants t ON t.id = u.tenant_id
            LEFT JOIN tenant_subscriptions subscription ON subscription.tenant_id = u.tenant_id
            WHERE u.role = 'branch' AND u.staff_role = 'pos_terminal' AND u.is_active
              AND (lower(t.slug) = lower(%s) OR lower(u.login) = lower(%s))
            ORDER BY u.id
            """,
            (payload.login, payload.login),
        ).fetchall()
        user = next((candidate for candidate in candidates if verify_password(payload.password, candidate["password_hash"])), None)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    requested_client = request.headers.get("x-ashkana-client", "").lower()
    authenticated_operator = dict(user) if (
        requested_client == "pos" and user["role"] == "branch"
        and user.get("staff_role") in {"branch_manager", "hall_admin", "waiter", "cashier", "production"}
        and _has_permission(dict(user), "posAccess")
    ) else None
    if user["role"] == "branch" and user.get("staff_role") != "pos_terminal" and not _has_admin_access(dict(user)) and not authenticated_operator:
        raise HTTPException(status_code=403, detail="Для сотрудника доступна только касса")
    _validate_tenant_access(user, allow_billing=requested_client != "pos")
    if requested_client == "pos" and user["staff_role"] != "pos_terminal":
        can_activate_register = user["role"] == "owner" or _has_permission(dict(user), "registers") or authenticated_operator is not None
        if not can_activate_register or not user.get("tenant_id"):
            raise HTTPException(status_code=403, detail="Активировать кассу может администратор или руководитель заведения")
        register_params: list[object] = [user["tenant_id"]]
        register_filter = ""
        if payload.register_id is not None:
            register_filter += " AND u.id = %s"
            register_params.append(payload.register_id)
        if user["role"] == "branch":
            register_filter += " AND u.branch_id = %s"
            register_params.append(user["branch_id"])
        terminal_user = connection.execute(
            f"""
            SELECT u.id, u.login, u.email_verified_at, u.password_hash, u.role, u.staff_role, u.access_permissions, u.phone, u.tenant_id, u.branch_id, u.display_name,
                   u.is_active, u.account_version, t.name AS tenant_name, t.slug AS tenant_slug,
                   t.status AS tenant_status, subscription.plan_code,
                   subscription.status AS subscription_status, subscription.max_branches,
                   subscription.trial_ends_at, subscription.current_period_ends_at
            FROM auth_users u
            JOIN tenants t ON t.id = u.tenant_id
            LEFT JOIN tenant_subscriptions subscription ON subscription.tenant_id = u.tenant_id
            WHERE u.tenant_id = %s AND u.role = 'branch' AND u.staff_role = 'pos_terminal' AND u.is_active
              {register_filter}
            ORDER BY u.id
            LIMIT 1
            """,
            tuple(register_params),
        ).fetchone()
        if not terminal_user:
            detail = "Выбранная касса недоступна" if payload.register_id is not None else "Сначала создайте активную кассу"
            raise HTTPException(status_code=404, detail=detail)
        user = terminal_user
        _validate_tenant_access(user)
    state = None if user["role"] == "platform_owner" else _workspace_row(connection, user["tenant_id"])["payload"]
    session = _user_session(dict(user), state)
    raw_token = new_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=get_settings().session_days)
    if user["staff_role"] == "pos_terminal":
        connection.execute(
            """
            UPDATE pos_operator_sessions SET revoked_at = CURRENT_TIMESTAMP
            WHERE terminal_session_id IN (
              SELECT id FROM auth_sessions WHERE user_id = %s AND revoked_at IS NULL
            ) AND revoked_at IS NULL
            """,
            (user["id"],),
        )
        connection.execute(
            "UPDATE auth_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = %s AND revoked_at IS NULL",
            (user["id"],),
        )
    created_session = connection.execute(
        """
        INSERT INTO auth_sessions (user_id, token_hash, account_version, expires_at, user_agent, remote_address)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (user["id"], token_hash(raw_token), user["account_version"], expires_at,
         request.headers.get("user-agent", "")[:500], request.client.host if request.client else ""),
    ).fetchone()
    session_cookie = POS_SESSION_COOKIE if user["staff_role"] == "pos_terminal" else SESSION_COOKIE
    response.set_cookie(
        session_cookie, raw_token, httponly=True, secure=get_settings().session_cookie_secure,
        samesite="strict", max_age=get_settings().session_days * 86400, path="/",
    )
    if session_cookie == POS_SESSION_COOKIE:
        if authenticated_operator is not None:
            operator_token = new_session_token()
            connection.execute(
                "INSERT INTO pos_operator_sessions (token_hash, terminal_session_id, employee_user_id, branch_id, expires_at) VALUES (%s, %s, %s, %s, %s)",
                (token_hash(operator_token), created_session["id"], authenticated_operator["id"], user["branch_id"], expires_at),
            )
            response.set_cookie(POS_OPERATOR_COOKIE, operator_token, httponly=True, secure=get_settings().session_cookie_secure,
                                samesite="strict", expires=expires_at.astimezone(timezone.utc), path="/")
        else:
            response.delete_cookie(POS_OPERATOR_COOKIE, path="/")
    return {"session": session}


@app.get("/api/v1/auth/me", tags=["auth"])
def me(user: dict = Depends(current_user), connection: Connection = Depends(get_connection)) -> dict:
    state = None if user["role"] == "platform_owner" else _workspace_row(connection, user["tenant_id"])["payload"]
    return {"session": _user_session(user, state)}


@app.post("/api/v1/auth/logout", tags=["auth"])
def logout(
    response: Response, request: Request, ashkana_session: str | None = Cookie(default=None),
    ashkana_pos_session: str | None = Cookie(default=None),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    is_pos_client = request.headers.get("x-ashkana-client", "").lower() == "pos"
    session_token = ashkana_pos_session if is_pos_client else ashkana_session
    if session_token:
        connection.execute("UPDATE auth_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE token_hash = %s", (token_hash(session_token),))
    response.delete_cookie(POS_SESSION_COOKIE if is_pos_client else SESSION_COOKIE, path="/")
    if is_pos_client:
        response.delete_cookie(POS_OPERATOR_COOKIE, path="/")
    return {"ok": True}


def _platform_owner(user: dict) -> None:
    if user["role"] != "platform_owner":
        raise HTTPException(status_code=403, detail="Раздел доступен только владельцу платформы")


def _company_owner(user: dict) -> None:
    if user["role"] != "owner" or not user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Сотрудниками управляет администратор компании")


def _company_admin_or_branch_manager(user: dict) -> None:
    is_owner = user["role"] == "owner" and user.get("tenant_id")
    is_manager = (
        user["role"] == "branch"
        and _has_permission(user, "employees")
        and user.get("tenant_id")
        and user.get("branch_id")
    )
    if not (is_owner or is_manager):
        raise HTTPException(status_code=403, detail="Раздел доступен администратору компании или управляющему точки")


def _assert_managed_branch(user: dict, branch_id: str) -> None:
    if user["role"] == "branch" and str(user.get("branch_id")) != str(branch_id):
        raise HTTPException(status_code=403, detail="Управляющий может работать только со своей точкой")


def _assert_permission_delegation(user: dict, permissions: dict[str, bool]) -> None:
    if user.get("role") != "branch":
        return
    missing = [key for key, enabled in permissions.items() if enabled and not _has_permission(user, key)]
    if missing:
        raise HTTPException(status_code=403, detail="Нельзя выдать сотруднику права, которых нет у вас")


def _branch_manager(user: dict) -> None:
    is_owner = user["role"] == "owner" and user.get("tenant_id")
    is_manager = user["role"] == "branch" and _has_permission(user, "registers") and user.get("branch_id")
    if not (is_owner or is_manager):
        raise HTTPException(status_code=403, detail="Недостаточно прав для управления кассами")


def _pos_terminal(user: dict) -> None:
    if user["role"] != "branch" or (user.get("staff_role") != "pos_terminal" and not _has_permission(user, "posAccess")):
        raise HTTPException(status_code=403, detail="Касса доступна только терминалу или управляющему точки")


def _operator_payload(row: dict) -> dict:
    initials = "".join(word[0] for word in row["display_name"].split()[:2]).upper() or "КС"
    role_labels = {
        "branch_manager": "Руководитель",
        "hall_admin": "Администратор зала",
        "waiter": "Официант",
        "cashier": "Кассир",
        "production": "Сотрудник производства",
    }
    return {
        "id": row["id"],
        "name": row["display_name"],
        "staffRole": row["staff_role"],
        "roleLabel": role_labels.get(row["staff_role"], "Сотрудник"),
        "initials": initials,
        "permissions": _normalized_permissions(row.get("staff_role"), row.get("access_permissions")),
        "accountVersion": int(row.get("account_version") or 0),
    }


def _current_pos_operator(
    connection: Connection,
    user: dict,
    raw_token: str | None,
    *,
    required: bool = True,
) -> dict | None:
    _pos_terminal(user)
    row = None
    if raw_token:
        row = connection.execute(
            """
            SELECT employee.id, employee.login, employee.display_name, employee.staff_role, employee.access_permissions, employee.account_version,
                   employee.branch_id, operator.id AS operator_session_id
            FROM pos_operator_sessions operator
            JOIN auth_users employee ON employee.id = operator.employee_user_id
            WHERE operator.token_hash = %s
              AND operator.terminal_session_id = %s
              AND operator.branch_id = %s
              AND operator.revoked_at IS NULL
              AND operator.expires_at > CURRENT_TIMESTAMP
              AND employee.is_active
              AND employee.tenant_id = %s
              AND employee.role = 'branch'
              AND employee.staff_role IN ('branch_manager', 'hall_admin', 'waiter', 'cashier', 'production')
            """,
            (token_hash(raw_token), user["session_id"], user["branch_id"], user["tenant_id"]),
        ).fetchone()
    if row and not _has_permission(dict(row), "posAccess"):
        row = None
    if row and user.get('_expected_operator_id') and str(row['id']) != str(user['_expected_operator_id']):
        raise HTTPException(423, 'Сотрудник в браузере сменился. Войдите по личному PIN повторно.')
    if not row:
        if required:
            raise HTTPException(status_code=423, detail="Введите личный PIN для входа в терминал")
        return None
    connection.execute(
        "UPDATE pos_operator_sessions SET last_seen_at = CURRENT_TIMESTAMP WHERE id = %s",
        (row["operator_session_id"],),
    )
    return dict(row)


def _pos_shift_payload(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": row["id"], "branchId": row["branch_id"], "registerId": row.get("register_user_id"),
        "registerName": row.get("register_name"), "openingCash": row["opening_cash"],
        "openedAt": row["opened_at"], "openedBy": row.get("opened_by"),
        "closedBy": row.get("closed_by"),
        "closingCash": row.get("closing_cash"), "expectedCash": row.get("expected_cash"),
        "variance": row.get("variance"), "closedAt": row.get("closed_at"),
    }


def _current_pos_shift(connection: Connection, user: dict) -> dict | None:
    row = connection.execute(
        """
        SELECT shift.*, employee.display_name AS opened_by
        FROM pos_shifts shift
        JOIN auth_users employee ON employee.id = shift.opened_by_user_id
        WHERE shift.tenant_id = %s AND shift.register_user_id = %s
          AND shift.branch_id = %s AND shift.closed_at IS NULL
        ORDER BY shift.opened_at DESC
        LIMIT 1
        """,
        (user["tenant_id"], user["id"], user["branch_id"]),
    ).fetchone()
    return dict(row) if row else None


@app.get("/api/v1/pos/shifts", tags=["pos"])
def list_pos_shifts(
    limit: int = Query(default=200, ge=1, le=500),
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> list[dict]:
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Кассовые смены доступны главному администратору")
    rows = connection.execute(
        """
        SELECT shift.*, register.display_name AS register_name,
               opened.display_name AS opened_by, closed.display_name AS closed_by
        FROM pos_shifts shift
        JOIN auth_users register ON register.id = shift.register_user_id
        JOIN auth_users opened ON opened.id = shift.opened_by_user_id
        LEFT JOIN auth_users closed ON closed.id = shift.closed_by_user_id
        WHERE shift.tenant_id = %s
        ORDER BY shift.opened_at DESC
        LIMIT %s
        """,
        (user["tenant_id"], limit),
    ).fetchall()
    return [_pos_shift_payload(dict(row)) for row in rows]


def _pos_history_cash_shifts(connection: Connection, user: dict) -> list[dict]:
    rows = connection.execute(
        """
        SELECT shift.id, shift.branch_id, shift.register_user_id, shift.opened_by_user_id,
               shift.opened_at, shift.closed_at, register.display_name AS register_name,
               opened.display_name AS opened_by
        FROM pos_shifts shift
        LEFT JOIN auth_users register ON register.id = shift.register_user_id
        LEFT JOIN auth_users opened ON opened.id = shift.opened_by_user_id
        WHERE shift.tenant_id = %s AND shift.branch_id = %s
        ORDER BY shift.opened_at DESC, shift.id DESC
        """,
        (user["tenant_id"], user["branch_id"]),
    ).fetchall()
    return [{"id": row["id"], "branchId": str(row["branch_id"]),
             "registerId": row["register_user_id"], "registerName": row.get("register_name") or "",
             "employeeId": row["opened_by_user_id"], "employeeName": row.get("opened_by") or "",
             "openedAt": row["opened_at"], "closedAt": row["closed_at"]} for row in rows]


@app.get("/api/v1/pos/shifts/history", tags=["pos"])
def pos_shifts_history(ashkana_pos_operator: str | None = Cookie(default=None), user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if operator.get("staff_role") == "production":
        raise HTTPException(status_code=403, detail="История чеков недоступна")
    from .company_settings import require_manager
    state = _workspace_row(connection, str(user["tenant_id"]))["payload"]
    try:
        require_manager(state, operator, "orderHistory")
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    actor = {**operator, "role": "branch", "branch_id": str(user["branch_id"]), "register_id": user["id"]}
    return build_cash_shift_history(_pos_history_cash_shifts(connection, user), str(user["branch_id"]), actor)


def _pos_register_record(connection: Connection, tenant_id: str, register_id: int) -> dict:
    row = connection.execute(
        """
        SELECT account.id, account.display_name AS name, account.branch_id, account.is_active,
               account.created_at, account.updated_at, account.login AS account_login,
               tenant.slug AS company_login,
               latest.created_at AS last_login_at, latest.last_seen_at,
               COALESCE(latest.user_agent, '') AS device_label,
               COALESCE(latest.remote_address, '') AS remote_address,
               COALESCE(latest.revoked_at IS NULL AND latest.expires_at > CURRENT_TIMESTAMP, FALSE) AS online
        FROM auth_users account
        JOIN tenants tenant ON tenant.id = account.tenant_id
        LEFT JOIN LATERAL (
          SELECT session.created_at, session.last_seen_at, session.user_agent, session.remote_address,
                 session.revoked_at, session.expires_at
          FROM auth_sessions session
          WHERE session.user_id = account.id
          ORDER BY session.created_at DESC
          LIMIT 1
        ) latest ON TRUE
        WHERE account.id = %s AND account.tenant_id = %s
          AND account.role = 'branch' AND account.staff_role = 'pos_terminal'
        """,
        (register_id, tenant_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Касса не найдена")
    return dict(row)


def _record_register_event(
    connection: Connection, user: dict, action: str, register_id: int, payload: dict,
) -> None:
    version = _workspace_row(connection, str(user["tenant_id"]))["version"]
    connection.execute(
        """
        INSERT INTO operational_events
          (tenant_id, state_version, actor_user_id, actor_login, actor_role, branch_id,
           action, entity_type, entity_id, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pos_register', %s, %s)
        """,
        (user["tenant_id"], version, user["id"], user["login"], user["role"],
         payload.get("branchId"), action, str(register_id), Jsonb(payload)),
    )


@app.get("/api/v1/pos/registers", tags=["pos"])
def list_pos_registers(
    user: dict = Depends(current_user), connection: Connection = Depends(get_connection),
) -> list[dict]:
    _branch_manager(user)
    branch_clause = " AND branch_id = %s" if user["role"] == "branch" else ""
    params = (user["tenant_id"], user["branch_id"]) if user["role"] == "branch" else (user["tenant_id"],)
    ids = [row["id"] for row in connection.execute(
        f"""
        SELECT id FROM auth_users
        WHERE tenant_id = %s AND role = 'branch' AND staff_role = 'pos_terminal'
          {branch_clause}
        ORDER BY is_active DESC, branch_id, display_name, id
        """,
        params,
    ).fetchall()]
    return [_pos_register_record(connection, str(user["tenant_id"]), register_id) for register_id in ids]


def _validate_register_login(connection: Connection, user: dict, login: str | None, register_id: int = 0) -> None:
    if login is None:
        return
    if user['role'] != 'owner':
        raise HTTPException(403, 'Изменять логин кассы может только владелец компании')
    connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('account-login:'+login,))
    if connection.execute(
        'SELECT id FROM tenants WHERE lower(slug) = %s AND id <> %s LIMIT 1',
        (login, user['tenant_id']),
    ).fetchone() or connection.execute(
        'SELECT id FROM auth_users WHERE lower(login) = %s AND id <> %s AND deleted_at IS NULL LIMIT 1',
        (login, register_id),
    ).fetchone():
        raise HTTPException(409, 'Этот логин уже используется. Выберите другой.')


@app.post("/api/v1/pos/registers", status_code=status.HTTP_201_CREATED, tags=["pos"])
def create_pos_register(
    payload: PosRegisterCreate,
    request: Request,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _branch_manager(user)
    _assert_managed_branch(user, payload.branch_id)
    tenant_id = str(user["tenant_id"])
    try:
        with connection.transaction():
            state = _workspace_row(connection, tenant_id)["payload"]
            branch = next((entry for entry in state["branches"] if entry["id"] == payload.branch_id), None)
            if not branch or branch.get("status") != "active":
                raise HTTPException(status_code=422, detail="Выберите действующую точку")
            _ensure_register_password_unique(connection, tenant_id, payload.password)
            _validate_register_login(connection, user, payload.login)
            row = connection.execute(
                """
                INSERT INTO auth_users
                  (login, password_hash, role, staff_role, tenant_id, branch_id, display_name)
                VALUES (%s, %s, 'branch', 'pos_terminal', %s, %s, %s)
                RETURNING id
                """,
                (payload.login or f"kassa-{uuid4().hex[:12]}", hash_password(payload.password), tenant_id,
                 payload.branch_id, payload.name),
            ).fetchone()
            _record_register_event(connection, user, "pos_register.create", int(row["id"]), {
                "name": payload.name, "branchId": payload.branch_id, "login": payload.login,
            })
    except UniqueViolation as error:
        if 'auth_users_login' in (error.diag.constraint_name or ''):
            raise HTTPException(409, 'Этот логин уже используется. Выберите другой.') from error
        raise HTTPException(status_code=409, detail="На этой точке уже есть касса с таким названием") from error
    return _pos_register_record(connection, tenant_id, int(row["id"]))


@app.put("/api/v1/pos/registers/{register_id}", tags=["pos"])
def update_pos_register(
    register_id: int,
    payload: PosRegisterUpdate,
    request: Request,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _branch_manager(user)
    _assert_managed_branch(user, payload.branch_id)
    tenant_id = str(user["tenant_id"])
    try:
        with connection.transaction():
            state = _workspace_row(connection, tenant_id)["payload"]
            branch = next((entry for entry in state["branches"] if entry["id"] == payload.branch_id), None)
            if not branch or (payload.is_active and branch.get("status") != "active"):
                raise HTTPException(status_code=422, detail="Выберите действующую точку")
            existing = connection.execute(
                """
                SELECT id, display_name, branch_id, password_hash, is_active, account_version
                FROM auth_users
                WHERE id = %s AND tenant_id = %s AND role = 'branch' AND staff_role = 'pos_terminal'
                FOR UPDATE
                """,
                (register_id, tenant_id),
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Касса не найдена")
            _assert_managed_branch(user, existing["branch_id"])
            _validate_register_login(connection, user, payload.login, register_id)
            if not existing["is_active"] and payload.is_active and not payload.password:
                raise HTTPException(status_code=422, detail="Для повторного включения кассы задайте новый пароль")
            if payload.password:
                _ensure_register_password_unique(connection, tenant_id, payload.password, exclude_id=register_id)
            access_changed = (
                existing["branch_id"] != payload.branch_id
                or bool(existing["is_active"]) != payload.is_active
                or bool(payload.password)
            )
            password_hash = hash_password(payload.password) if payload.password else existing["password_hash"]
            account_version = int(existing["account_version"]) + (1 if access_changed else 0)
            connection.execute(
                """
                UPDATE auth_users
                SET display_name = %s, branch_id = %s, password_hash = %s, is_active = %s,
                    account_version = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (payload.name, payload.branch_id, password_hash, payload.is_active, account_version, register_id),
            )
            if access_changed:
                connection.execute(
                    "UPDATE auth_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = %s AND revoked_at IS NULL",
                    (register_id,),
                )
            if payload.login is not None:
                connection.execute('UPDATE auth_users SET login = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s AND tenant_id = %s',
                                   (payload.login, register_id, tenant_id))
            _record_register_event(connection, user, "pos_register.update", register_id, {
                "name": payload.name, "branchId": payload.branch_id,
                "isActive": payload.is_active, "passwordChanged": bool(payload.password),
                "login": payload.login,
            })
    except UniqueViolation as error:
        if 'auth_users_login' in (error.diag.constraint_name or ''):
            raise HTTPException(409, 'Этот логин уже используется. Выберите другой.') from error
        raise HTTPException(status_code=409, detail="На этой точке уже есть касса с таким названием") from error
    return _pos_register_record(connection, tenant_id, register_id)


@app.post("/api/v1/pos/registers/{register_id}/logout", tags=["pos"])
def logout_pos_register(
    register_id: int,
    request: Request,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _branch_manager(user)
    tenant_id = str(user["tenant_id"])
    register = _pos_register_record(connection, tenant_id, register_id)
    _assert_managed_branch(user, register["branch_id"])
    connection.execute(
        """
        UPDATE pos_operator_sessions SET revoked_at = CURRENT_TIMESTAMP
        WHERE terminal_session_id IN (SELECT id FROM auth_sessions WHERE user_id = %s)
          AND revoked_at IS NULL
        """,
        (register_id,),
    )
    connection.execute(
        "UPDATE auth_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = %s AND revoked_at IS NULL",
        (register_id,),
    )
    _record_register_event(connection, user, "pos_register.logout", register_id, {
        "name": register["name"], "branchId": register["branch_id"],
    })
    return _pos_register_record(connection, tenant_id, register_id)


@app.get("/api/v1/pos/operators", tags=["pos"])
def list_pos_operators(
    user: dict = Depends(current_user), connection: Connection = Depends(get_connection),
) -> list[dict]:
    _pos_terminal(user)
    rows = connection.execute(
        """
        SELECT id, display_name, staff_role, access_permissions
        FROM auth_users
        WHERE tenant_id = %s AND role = 'branch' AND is_active
          AND branch_id = %s
          AND staff_role IN ('branch_manager', 'hall_admin', 'waiter', 'cashier', 'production') AND pin_hash IS NOT NULL
        ORDER BY CASE staff_role WHEN 'branch_manager' THEN 0 WHEN 'hall_admin' THEN 1 ELSE 2 END, display_name, id
        """,
        (user["tenant_id"], user["branch_id"]),
    ).fetchall()
    return [_operator_payload(dict(row)) for row in rows if _has_permission(dict(row), "posAccess")]


def _production_recipients(connection, tenant_id, branch_id):
    rows = connection.execute("SELECT id, display_name, staff_role, access_permissions FROM auth_users WHERE tenant_id = %s AND branch_id = %s AND role = 'branch' AND is_active ORDER BY display_name", (tenant_id, branch_id)).fetchall()
    return [{"id": row["id"], "name": row["display_name"], "branchId": branch_id} for row in rows if _has_permission(dict(row), "production")]


def _production_context_response(connection, user, branch_id):
    if not _has_permission(user, "production"):
        raise HTTPException(status_code=403, detail="Для сотрудника не разрешено производство")
    if user.get("plan_code") == "restaurant":
        raise HTTPException(status_code=403, detail="Учёт витрины доступен в режиме столовой")
    state = _workspace_row(connection, str(user["tenant_id"]))["payload"]
    return {**production_context(state, branch_id), **custody.context(state, branch_id, user), "productionShift": production_shifts.context(state, branch_id),
            "recipients": _production_recipients(connection, str(user["tenant_id"]), branch_id)}


@app.get("/api/v1/production/context", tags=["operations"])
def production_admin_context(branch_id: str | None = Query(default=None), user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
    branch = str(branch_id or user.get("branch_id") or "")
    if user.get("role") != "owner" and branch != str(user.get("branch_id")):
        raise HTTPException(status_code=403, detail="Недоступная точка")
    return _production_context_response(connection, user, branch)


@app.get("/api/v1/pos/production/context", tags=["pos"])
def pos_production_context(ashkana_pos_operator: str | None = Cookie(default=None), user: dict = Depends(current_user), connection: Connection = Depends(get_connection)) -> dict:
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    return _production_context_response(connection, {**user, "id": operator["id"], "display_name": operator["display_name"], "staff_role": operator.get("staff_role"), "access_permissions": operator.get("access_permissions") or {}}, str(user["branch_id"]))


@app.get("/api/v1/pos/transfers/history", tags=["pos"])
def pos_transfer_history(ashkana_pos_operator: str | None = Cookie(default=None), user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if user.get("plan_code") == "restaurant" or operator.get("staff_role") not in {"production", "cashier", "branch_manager", "hall_admin"}:
        raise HTTPException(status_code=403, detail="История передач доступна сотрудникам кухни и раздачи столовой")
    state = _workspace_row(connection, str(user["tenant_id"]))["payload"]
    actor = {**operator, "role": "branch", "branch_id": str(user["branch_id"]), "register_id": user["id"]}
    return build_transfer_history(state, str(user["branch_id"]), actor, _pos_history_cash_shifts(connection, user))


@app.get("/api/v1/pos/receiving", tags=["pos"])
def pos_receiving(ashkana_pos_operator: str | None = Cookie(default=None), user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
    if user.get("plan_code") == "restaurant":
        raise HTTPException(status_code=403, detail="Приёмка на раздачу доступна только в тарифе столовой")
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if operator.get("staff_role") not in {"cashier", "branch_manager", "hall_admin"}:
        raise HTTPException(status_code=403, detail="Приёмка доступна кассиру")
    if not _current_pos_shift(connection, user):
        raise HTTPException(status_code=409, detail="Сначала откройте кассовую смену")
    row = _workspace_row(connection, str(user["tenant_id"]))
    state = row["payload"]
    recipes = {str(recipe["id"]): recipe for recipe in state.get("recipes", [])}
    batches = {batch["id"]: batch for batch in state["logisticsState"]["batches"]}
    documents = []
    for entry in state["logisticsState"].get("custodyDocuments", []):
        if entry.get("branchId") != str(user["branch_id"]) or entry.get("status") != "pending" or entry.get("kind") not in {"transfer", "handover"} or entry.get("recipient", {}).get("kind") != "branch_cashiers":
            continue
        batch = batches.get(entry["batchId"], {})
        recipe = recipes.get(str(batch.get("recipeId")), {})
        documents.append({"id": entry["id"], "kind": entry["kind"], "name": recipe.get("name", "Блюдо"), "weight": entry["weight"], "sender": entry["actor"]["name"], "createdAt": entry["createdAt"], "batchNumber": batch.get("number", "")})
    for batch in batches.values():
        if str(batch.get("branchId")) != str(user["branch_id"]) or batch.get("status") == "closed":
            continue
        recipe = recipes.get(str(batch.get("recipeId")), {})
        custody.initialize(batch, recipe)
        for lot in batch["servingLots"]:
            if lot.get("legacy") and custody.lot_balance(lot) > 0:
                documents.append({"id": "legacy:" + batch["id"], "name": recipe.get("name", "Блюдо"), "weight": custody.lot_balance(lot), "sender": "Старый остаток без подтверждённой приёмки", "batchNumber": batch.get("number", ""), "legacy": True})
    return {"documents": documents, "version": row["version"]}


@app.get("/api/v1/pos/serving/writeoffs", tags=["pos"])
def pos_serving_writeoffs(ashkana_pos_operator: str | None = Cookie(default=None), user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
    if user.get("plan_code") == "restaurant":
        raise HTTPException(status_code=403, detail="Списание с раздачи доступно только для столовой")
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if operator.get("staff_role") not in {"cashier", "branch_manager", "hall_admin"} or not _current_pos_shift(connection, user):
        raise HTTPException(status_code=403, detail="Списание доступно кассиру на открытой смене")
    state = _workspace_row(connection, str(user["tenant_id"]))["payload"]
    branch_id = str(user["branch_id"])
    recipes = {str(recipe["id"]): recipe for recipe in state.get("recipes", [])}
    lots = []
    for batch in state["logisticsState"]["batches"]:
        if batch.get("branchId") != branch_id or batch.get("status") not in {"serving", "partial"}:
            continue
        recipe = recipes.get(str(batch["recipeId"]), {})
        custody.initialize(batch, recipe)
        for lot in batch["servingLots"]:
            available = custody.lot_available(lot)
            if available > 0:
                lots.append({"id": lot["id"], "batchId": batch["id"], "batchNumber": batch.get("number", ""), "name": recipe.get("name", "Блюдо"), "yield": custody.portion_weight(batch, recipe), "availableWeight": available, "responsibleName": lot.get("responsibleName")})
    keys = ("id", "number", "batchNumber", "recipeId", "weight", "reason", "status", "createdAt", "actor", "reviewedBy", "reviewNote")
    documents = [{**{key: doc.get(key) for key in keys}, "name": recipes.get(str(doc.get("recipeId")), {}).get("name", "Блюдо")} for doc in state["logisticsState"].get("custodyDocuments", []) if doc.get("branchId") == branch_id and doc.get("kind") == "writeoff" and doc.get("lotId")]
    return {"lots": lots, "documents": documents[:100]}


@app.get("/api/v1/pos/serving/surpluses", tags=["pos"])
def pos_serving_surpluses(ashkana_pos_operator: str | None = Cookie(default=None), user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
    if user.get("plan_code") == "restaurant":
        raise HTTPException(status_code=403, detail="Излишки на раздаче доступны только для столовой")
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if operator.get("staff_role") not in {"cashier", "branch_manager", "hall_admin"} or not _current_pos_shift(connection, user):
        raise HTTPException(status_code=403, detail="Излишек оформляет кассир на открытой смене")
    state = _workspace_row(connection, str(user["tenant_id"]))["payload"]
    branch_id = str(user["branch_id"])
    recipes = {str(recipe["id"]): recipe for recipe in state.get("recipes", [])}
    lots = []
    for batch in state["logisticsState"]["batches"]:
        if batch.get("branchId") != branch_id or batch.get("status") not in {"serving", "partial"}:
            continue
        recipe = recipes.get(str(batch["recipeId"]), {})
        custody.initialize(batch, recipe)
        for lot in batch["servingLots"]:
            if lot.get("legacy") or not lot.get("acceptedAt") or lot.get("responsibleId") is None or lot.get("handoverId"):
                continue
            lots.append({"id": lot["id"], "batchId": batch["id"], "batchNumber": batch.get("number", ""), "name": recipe.get("name", "Блюдо"), "yield": custody.portion_weight(batch, recipe), "availableWeight": custody.lot_available(lot)})
    keys = ("id", "number", "batchNumber", "weight", "reason", "status", "createdAt", "actor", "reviewedBy", "reviewNote")
    documents = [{**{key: doc.get(key) for key in keys}, "name": recipes.get(str(doc.get("recipeId")), {}).get("name", "Блюдо")} for doc in state["logisticsState"].get("custodyDocuments", []) if doc.get("branchId") == branch_id and doc.get("kind") == "surplus"]
    return {"lots": lots, "documents": documents[:100]}


@app.get("/api/v1/pos/supplies/context", tags=["pos"])
def pos_supply_context(
    ashkana_pos_operator: str | None = Cookie(default=None),
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if not _has_permission(operator, "posSupply"):
        raise HTTPException(status_code=403, detail="Для сотрудника не разрешена приёмка поставок")
    state = _workspace_row(connection, str(user["tenant_id"]))["payload"]
    branch_id = str(user["branch_id"])
    suppliers = [
        {
            "id": supplier["id"], "name": supplier["name"],
            "phone": supplier.get("phone", ""), "prices": supplier.get("prices", {}).get(branch_id, {}),
        }
        for supplier in state.get("suppliers", [])
        if supplier.get("status") == "active" and branch_id in supplier.get("locations", [])
    ]
    branch_costs = state.get("logisticsState", {}).get("branchCosts", {}).get(branch_id, {})
    items = [
        {
            "id": str(item["id"]), "name": item["name"], "category": item.get("category", ""),
            "unit": item.get("unit", "шт"),
            "averageCost": branch_costs.get(str(item["id"]), item.get("averageCost", 0)),
        }
        for item in [*state.get("ingredients", []), *state.get("products", [])]
    ]
    can_pay_drawer = operator.get("staff_role") != "production" and bool(_current_pos_shift(connection, user))
    accounts = [
        {"id": account["id"], "name": account["name"], "type": account.get("type", "other")}
        for account in state.get("financeState", {}).get("accounts", [])
        if account.get("status") == "active" and (not account.get("branchId") or str(account.get("branchId")) == branch_id)
        and (account.get("type") != "cash" or (can_pay_drawer and str(account.get("branchId")) == branch_id))
    ]
    supplies = [supply for supply in state.get("logisticsState", {}).get("supplies", []) if str(supply.get("branchId")) == branch_id][:20]
    settings = get_settings()
    photo_enabled = bool(getattr(settings, "openai_api_key", "") and getattr(settings, "invoice_photo_model", ""))
    return {"suppliers": suppliers, "items": items, "accounts": accounts, "supplies": supplies,
            "photoImport": {"enabled": photo_enabled, "reason": "" if photo_enabled else
                            "Распознавание фото не настроено. Фото можно прикрепить к поставке и заполнить позиции вручную"}}


@app.post("/api/v1/pos/supplies/import-preview", tags=["pos"])
def preview_supply_import(
    payload: dict, request: Request,
    ashkana_pos_operator: str | None = Cookie(default=None),
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if not _has_permission(operator, "posSupply"):
        raise HTTPException(status_code=403, detail="Для сотрудника не разрешена приёмка поставок")
    from .supply_import import preview
    state = _workspace_row(connection, str(user["tenant_id"]))["payload"]
    try:
        return preview(state, payload.get("file"), payload.get("fileName"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/pos/supplies/photos", tags=["pos"])
def upload_supply_photo(
    payload: dict, request: Request,
    ashkana_pos_operator: str | None = Cookie(default=None),
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    from . import supply_photos
    from .invoice_photo import PhotoInvoiceError

    _check_origin(request)
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if not _has_permission(operator, "posSupply"):
        raise HTTPException(status_code=403, detail="Для сотрудника не разрешена приёмка поставок")
    try:
        with connection.transaction():
            return supply_photos.upload(connection, user, operator, payload.get("file"), payload.get("fileName"))
    except (supply_photos.PhotoStorageError, PhotoInvoiceError) as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@app.post("/api/v1/pos/supplies/photos/{photo_id}/recognize", tags=["pos"])
def recognize_supply_photo(
    photo_id: str, request: Request,
    ashkana_pos_operator: str | None = Cookie(default=None),
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
):
    from . import supply_photos

    _check_origin(request)
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if not _has_permission(operator, "posSupply"):
        raise HTTPException(status_code=403, detail="Для сотрудника не разрешена приёмка поставок")
    state = _workspace_row(connection, str(user["tenant_id"]))["payload"]
    try:
        with connection.transaction():
            result, status_code = supply_photos.recognize(connection, user, operator, photo_id, state, get_settings())
        if status_code != 200:
            return JSONResponse(result, status_code=status_code)
        return result
    except supply_photos.PhotoStorageError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


def _supply_photo_user(
    request: Request, client: str = Query(default=""),
    ashkana_session: str | None = Cookie(default=None),
    ashkana_pos_session: str | None = Cookie(default=None),
    connection: Connection = Depends(get_connection),
) -> dict:
    # Browser <img>/<a> requests cannot set the terminal header. Scope only this
    # photo route to the requested cookie, without falling back to an admin login.
    if client == "pos":
        headers = [(key, value) for key, value in request.scope.get("headers", [])
                   if key.lower() != b"x-ashkana-client"]
        request = Request({**request.scope, "headers": [*headers, (b"x-ashkana-client", b"pos")]})
    return current_user(request, ashkana_session, ashkana_pos_session, connection)


@app.get("/api/v1/pos/supplies/photos/{photo_id}", tags=["pos"])
def get_supply_photo(
    photo_id: str, download: bool = False,
    ashkana_pos_operator: str | None = Cookie(default=None),
    user: dict = Depends(_supply_photo_user),
    connection: Connection = Depends(get_connection),
) -> Response:
    from . import supply_photos

    tenant_id = _tenant_user(user)
    operator = None
    if user.get("staff_role") == "pos_terminal":
        operator = _current_pos_operator(connection, user, ashkana_pos_operator)
        if not _has_permission(operator, "posSupply"):
            raise HTTPException(status_code=403, detail="Для сотрудника не разрешена приёмка поставок")
    elif user.get("role") != "owner" and not _has_permission(user, "inventory"):
        raise HTTPException(status_code=403, detail="Фотография поставки недоступна")
    try:
        photo = supply_photos.get_photo(connection, tenant_id, photo_id)
        if user.get("role") != "owner" and str(photo["branch_id"]) != str(user.get("branch_id")):
            raise supply_photos.PhotoStorageError("Фотография не найдена", 404)
        if not photo["linked"]:
            supply_photos.require_uploader(photo, user, operator or user)
        else:
            state = _workspace_row(connection, tenant_id)["payload"]
            if not any(supply.get("photo", {}).get("id") == photo_id
                       and str(supply.get("branchId")) == str(photo["branch_id"])
                       for supply in state.get("logisticsState", {}).get("supplies", [])):
                raise supply_photos.PhotoStorageError("Фотография поставки не найдена", 404)
    except supply_photos.PhotoStorageError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    disposition = "attachment" if download else "inline"
    return Response(bytes(photo["content"]), media_type=photo["content_type"], headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(photo['file_name'], safe='')}",
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })


@app.get("/api/v1/pos/operator", tags=["pos"])
def get_pos_operator(
    ashkana_pos_operator: str | None = Cookie(default=None),
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    operator = _current_pos_operator(connection, user, ashkana_pos_operator, required=False)
    return {
        "operator": _operator_payload(operator) if operator else None,
        "shift": _pos_shift_payload(_current_pos_shift(connection, user)) if operator else None,
    }


@app.post("/api/v1/pos/unlock", tags=["pos"])
def unlock_pos(
    payload: PosUnlockInput,
    response: Response,
    request: Request,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _pos_terminal(user)
    failure: tuple[int, str] | None = None
    raw_token: str | None = None
    operator: dict | None = None
    with connection.transaction():
        terminal = connection.execute(
            """SELECT id, pin_failed_attempts,
                      (pin_locked_until IS NOT NULL AND pin_locked_until > CURRENT_TIMESTAMP) AS pin_locked
               FROM auth_users WHERE id = %s AND tenant_id = %s FOR UPDATE""",
            (user["id"], user["tenant_id"]),
        ).fetchone()
        if not terminal:
            raise HTTPException(status_code=401, detail="Войдите в терминал заново")
        if terminal["pin_locked"]:
            raise HTTPException(status_code=429, detail="Слишком много попыток. Повторите через 5 минут")
        candidates = connection.execute(
            """SELECT id, display_name, staff_role, access_permissions, pin_hash, account_version,
                      (pin_locked_until IS NOT NULL AND pin_locked_until > CURRENT_TIMESTAMP) AS pin_locked
               FROM auth_users
               WHERE tenant_id = %s AND branch_id = %s AND role = 'branch' AND is_active
                 AND staff_role IN ('branch_manager', 'hall_admin', 'waiter', 'cashier', 'production')
                 AND pin_hash IS NOT NULL
               ORDER BY id FOR UPDATE""",
            (user["tenant_id"], user["branch_id"]),
        ).fetchall()
        matches = [dict(candidate) for candidate in candidates
                   if _has_permission(dict(candidate), "posAccess") and verify_pin(payload.pin, candidate["pin_hash"])]
        row = matches[0] if len(matches) == 1 else None
        if len(matches) > 1:
            failure = (409, "Этот PIN назначен нескольким сотрудникам. Попросите руководителя назначить разные PIN")
        elif row and row["pin_locked"]:
            failure = (429, "PIN временно заблокирован. Повторите через 5 минут")
        elif not row:
            attempts = int(terminal["pin_failed_attempts"]) + 1
            if attempts >= 5:
                connection.execute(
                    "UPDATE auth_users SET pin_failed_attempts = 0, pin_locked_until = CURRENT_TIMESTAMP + INTERVAL '5 minutes' WHERE id = %s",
                    (terminal["id"],),
                )
                failure = (429, "Слишком много неверных попыток. Повторите через 5 минут")
            else:
                connection.execute("UPDATE auth_users SET pin_failed_attempts = %s WHERE id = %s",
                                   (attempts, terminal["id"]))
                failure = (401, f"Неверный PIN. Осталось попыток: {5 - attempts}")
        else:
            connection.execute(
                "UPDATE auth_users SET pin_failed_attempts = 0, pin_locked_until = NULL WHERE id = %s",
                (terminal["id"],),
            )
            connection.execute(
                "UPDATE pos_operator_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE terminal_session_id = %s AND revoked_at IS NULL",
                (user["session_id"],),
            )
            raw_token = new_session_token()
            connection.execute(
                """
                INSERT INTO pos_operator_sessions
                  (token_hash, terminal_session_id, employee_user_id, branch_id, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (token_hash(raw_token), user["session_id"], row["id"], user["branch_id"],
                 user["session_expires_at"]),
            )
            operator = dict(row)
    if failure:
        raise HTTPException(status_code=failure[0], detail=failure[1])
    response.set_cookie(
        POS_OPERATOR_COOKIE, raw_token, httponly=True, secure=get_settings().session_cookie_secure,
        samesite="strict", expires=user["session_expires_at"].astimezone(timezone.utc), path="/",
    )
    return {
        "operator": _operator_payload(operator),
        "shift": _pos_shift_payload(_current_pos_shift(connection, user)),
    }


@app.post("/api/v1/pos/shifts/open", tags=["pos"])
def open_pos_shift(
    payload: PosShiftOpen,
    request: Request,
    ashkana_pos_operator: str | None = Cookie(default=None),
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _workspace_row(connection, str(user["tenant_id"]), for_update=True)
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if operator.get("staff_role") == "production":
        raise HTTPException(status_code=403, detail="Сотруднику производства недоступны кассовые смены")
    existing = _current_pos_shift(connection, user)
    if existing:
        return {"shift": _pos_shift_payload(existing)}
    try:
        row = connection.execute(
            """
            INSERT INTO pos_shifts
              (tenant_id, register_user_id, branch_id, opened_by_user_id, opening_cash)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (user["tenant_id"], user["id"], user["branch_id"], operator["id"], payload.opening_cash),
        ).fetchone()
    except UniqueViolation as error:
        raise HTTPException(status_code=409, detail="На этой кассе уже открыта смена") from error
    row = {**dict(row), "opened_by": operator["display_name"]}
    return {"shift": _pos_shift_payload(row)}


@app.get("/api/v1/pos/shifts/closing-stock", tags=["pos"])
def closing_shift_stock(ashkana_pos_operator: str | None = Cookie(default=None), user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
    from .shift_reconciliation import serving_rows
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if operator.get("staff_role") == "production":
        raise HTTPException(status_code=403, detail="Недоступно сотруднику производства")
    if not _current_pos_shift(connection, user):
        raise HTTPException(status_code=409, detail="Нет открытой кассовой смены")
    row = _workspace_row(connection, str(user["tenant_id"]))
    return {"version":row["version"], "required":user.get("plan_code") != "restaurant", "rows":serving_rows(row["payload"], {**user, "id":operator["id"], "register_id":user["id"]}) if user.get("plan_code") != "restaurant" else []}


@app.post("/api/v1/pos/shifts/close", tags=["pos"])
def close_pos_shift(
    payload: PosShiftClose,
    request: Request,
    ashkana_pos_operator: str | None = Cookie(default=None),
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _workspace_row(connection, str(user["tenant_id"]), for_update=True)
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if operator.get("staff_role") == "production":
        raise HTTPException(status_code=403, detail="Сотруднику производства недоступны кассовые смены")
    shift = _current_pos_shift(connection, user)
    if not shift:
        raise HTTPException(status_code=409, detail="На этой кассе нет открытой смены")
    workspace = _workspace_row(connection, str(user["tenant_id"]))
    state = workspace["payload"]
    if user.get("plan_code") != "restaurant":
        if payload.state_version != workspace["version"]:
            raise HTTPException(status_code=409, detail="Учёт изменился. Обновите окно закрытия смены и пересчитайте остатки")
        from .shift_reconciliation import close_serving
        try:
            from .workspace import _require_unlocked
            _require_unlocked(state, str(user["branch_id"]))
            close_serving(state, {**user, "id":operator["id"], "display_name":operator["display_name"], "register_id":user["id"], "shift_id":shift["id"]}, payload.stock_counts, payload.stock_confirmed)
        except (custody.CustodyError, WorkspaceError) as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        connection.execute("UPDATE operational_state SET payload = %s, version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE tenant_id = %s", (Jsonb(state), user["tenant_id"]))
    cash_sales = sum(
        sale_payment_amount(sale, "cash")
        for sale in state.get("sales", [])
        if str(sale.get("shiftId")) == str(shift["id"])
    )
    cash_refunds = sum(
        sale_payment_amount(sale, "cash")
        for sale in state.get("sales", [])
        if str(sale.get("refundShiftId")) == str(shift["id"])
    )
    cash_movements = state.get("posState", {}).get("cashMovements", [])
    deposits = sum(
        Decimal(str(movement.get("amount", 0)))
        for movement in cash_movements
        if str(movement.get("shiftId")) == str(shift["id"]) and movement.get("type") == "deposit"
    )
    withdrawals = sum(
        Decimal(str(movement.get("amount", 0)))
        for movement in cash_movements
        if str(movement.get("shiftId")) == str(shift["id"]) and movement.get("type") in {"expense", "collection"}
    )
    expected_cash = Decimal(str(shift["opening_cash"])) + cash_sales - cash_refunds + deposits - withdrawals
    variance = payload.closing_cash - expected_cash
    row = connection.execute(
        """
        UPDATE pos_shifts
        SET closed_by_user_id = %s, closing_cash = %s, expected_cash = %s,
            variance = %s, closed_at = CURRENT_TIMESTAMP
        WHERE id = %s AND closed_at IS NULL
        RETURNING *
        """,
        (operator["id"], payload.closing_cash, expected_cash, variance, shift["id"]),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="Смена уже закрыта")
    row = {**dict(row), "opened_by": shift["opened_by"]}
    return {"shift": _pos_shift_payload(row)}


@app.post("/api/v1/pos/lock", tags=["pos"])
def lock_pos(
    response: Response,
    request: Request,
    ashkana_pos_operator: str | None = Cookie(default=None),
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _pos_terminal(user)
    if ashkana_pos_operator:
        connection.execute(
            """
            UPDATE pos_operator_sessions SET revoked_at = CURRENT_TIMESTAMP
            WHERE token_hash = %s AND terminal_session_id = %s AND revoked_at IS NULL
            """,
            (token_hash(ashkana_pos_operator), user["session_id"]),
        )
    response.delete_cookie(POS_OPERATOR_COOKIE, path="/")
    return {"ok": True}


def _employee_record(connection: Connection, tenant_id: str, employee_id: int) -> dict:
    row = connection.execute(
        """
        SELECT account.id, account.display_name, account.phone, account.login, account.branch_id,
               account.staff_role, account.access_permissions AS permissions, account.is_active, account.created_at, account.updated_at,
               (account.pin_hash IS NOT NULL) AS has_pin,
               (account.pin_encrypted IS NOT NULL) AS can_reveal_pin,
               GREATEST(MAX(session.last_seen_at), MAX(operator.last_seen_at)) AS last_seen_at
        FROM auth_users account
        LEFT JOIN auth_sessions session ON session.user_id = account.id
        LEFT JOIN pos_operator_sessions operator ON operator.employee_user_id = account.id
        WHERE account.id = %s AND account.tenant_id = %s AND account.role = 'branch'
          AND account.staff_role <> 'pos_terminal'
          AND account.deleted_at IS NULL
        GROUP BY account.id
        """,
        (employee_id, tenant_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    return dict(row)


def _sync_branch_managers(connection: Connection, tenant_id: str, state: dict) -> None:
    managers = {
        row["branch_id"]: row
        for row in connection.execute(
            """
            SELECT branch_id, display_name
            FROM auth_users
            WHERE tenant_id = %s AND role = 'branch' AND staff_role = 'branch_manager' AND is_active
              AND deleted_at IS NULL
            """,
            (tenant_id,),
        ).fetchall()
    }
    for branch in state["branches"]:
        manager = managers.get(branch["id"])
        branch["managerName"] = manager["display_name"] if manager else "Не назначен"


@app.get("/api/v1/employees", tags=["employees"])
def list_employees(user: dict = Depends(current_user), connection: Connection = Depends(get_connection)) -> list[dict]:
    _company_admin_or_branch_manager(user)
    branch_clause = " AND account.branch_id = %s" if user["role"] == "branch" else ""
    params = (user["tenant_id"], user["branch_id"]) if user["role"] == "branch" else (user["tenant_id"],)
    rows = connection.execute(
        f"""
        SELECT account.id, account.display_name, account.phone, account.login, account.branch_id,
               account.staff_role, account.access_permissions AS permissions, account.is_active, account.created_at, account.updated_at,
               (account.pin_hash IS NOT NULL) AS has_pin,
               (account.pin_encrypted IS NOT NULL) AS can_reveal_pin,
               GREATEST(MAX(session.last_seen_at), MAX(operator.last_seen_at)) AS last_seen_at
        FROM auth_users account
        LEFT JOIN auth_sessions session ON session.user_id = account.id
        LEFT JOIN pos_operator_sessions operator ON operator.employee_user_id = account.id
        WHERE account.tenant_id = %s AND account.role = 'branch'
          AND account.staff_role <> 'pos_terminal'
          AND account.deleted_at IS NULL
          {branch_clause}
        GROUP BY account.id
        ORDER BY account.is_active DESC, account.display_name, account.id
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _employee_pin_key() -> str:
    key = get_settings().employee_pin_key
    if len(key) < 32:
        raise HTTPException(status_code=503, detail="Не настроен ключ хранения PIN-кодов")
    return key


def _store_employee_pin(connection: Connection, employee_id: int, tenant_id: str, pin: str | None) -> None:
    if pin:
        connection.execute(
            "UPDATE auth_users SET pin_encrypted = pgp_sym_encrypt(%s, %s, 'cipher-algo=aes256') WHERE id = %s AND tenant_id = %s",
            (pin, _employee_pin_key(), employee_id, tenant_id),
        )


@app.post("/api/v1/employees/{employee_id}/pin/reveal", tags=["employees"])
def reveal_employee_pin(employee_id: int, request: Request, response: Response,
                        user: dict = Depends(current_user), connection: Connection = Depends(get_connection)) -> dict:
    _check_origin(request)
    _company_admin_or_branch_manager(user)
    employee = _employee_record(connection, str(user["tenant_id"]), employee_id)
    _assert_managed_branch(user, employee["branch_id"])
    if user["role"] == "branch" and employee["staff_role"] == "branch_manager":
        raise HTTPException(status_code=403, detail="PIN руководителя доступен владельцу аккаунта")
    response.headers["Cache-Control"] = "no-store"
    if not employee.get("can_reveal_pin"):
        return {"pin": None, "requires_reset": True}
    row = connection.execute(
        "SELECT pgp_sym_decrypt(pin_encrypted, %s) AS pin FROM auth_users WHERE id = %s AND tenant_id = %s",
        (_employee_pin_key(), employee_id, user["tenant_id"]),
    ).fetchone()
    connection.execute(
        "INSERT INTO audit_events (tenant_id, actor, action, entity_type, entity_id, after_state) VALUES (%s, %s, 'employee.pin.reveal', 'employee', %s, %s)",
        (user["tenant_id"], user["login"], str(employee_id), Jsonb({"viewed": True})),
    )
    return {"pin": row["pin"], "requires_reset": False}


def _assert_unique_employee_pin(connection: Connection, tenant_id: str, branch_id: str,
                                pin: str | None, employee_id: int = 0) -> None:
    if not pin:
        return
    rows = connection.execute(
        """SELECT pin_hash FROM auth_users WHERE tenant_id = %s AND branch_id = %s
           AND role = 'branch' AND staff_role <> 'pos_terminal' AND is_active
           AND id <> %s AND pin_hash IS NOT NULL""",
        (tenant_id, branch_id, employee_id),
    ).fetchall()
    if any(verify_pin(pin, row["pin_hash"]) for row in rows):
        raise HTTPException(status_code=409, detail="Этот PIN уже используется в заведении. Укажите другой PIN")


@app.post("/api/v1/employees", status_code=status.HTTP_201_CREATED, tags=["employees"])
def create_employee(
    payload: EmployeeCreate,
    request: Request,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _company_admin_or_branch_manager(user)
    _assert_managed_branch(user, payload.branch_id)
    if user["role"] == "branch" and payload.staff_role.value == "branch_manager":
        raise HTTPException(status_code=403, detail="Руководителя назначает владелец аккаунта")
    tenant_id = str(user["tenant_id"])
    permissions = _normalized_permissions(
        payload.staff_role.value,
        payload.permissions.model_dump() if payload.permissions is not None else None,
    )
    _assert_permission_delegation(user, permissions)
    if permissions["posAccess"] and not payload.pin:
        raise HTTPException(status_code=422, detail="Для доступа к кассе укажите PIN из 4 цифр")
    if any(permissions[key] for key in ADMIN_PERMISSION_KEYS) and (not payload.login or not payload.password):
        raise HTTPException(status_code=422, detail="Для доступа к админ-панели нужны логин и временный пароль")
    try:
        with connection.transaction():
            workspace = _workspace_row(connection, tenant_id, for_update=True)
            state = workspace["payload"]
            branch = next((entry for entry in state["branches"] if entry["id"] == payload.branch_id), None)
            if not branch:
                raise HTTPException(status_code=422, detail="Выбранное заведение не найдено")
            _assert_unique_employee_pin(connection, tenant_id, payload.branch_id, payload.pin)
            employee_login = payload.login or f"cashier-{uuid4().hex}@internal"
            employee_password = payload.password or new_session_token()
            pin_hash = hash_pin(payload.pin) if payload.pin else None
            row = connection.execute(
                """
                INSERT INTO auth_users
                  (login, password_hash, pin_hash, role, staff_role, access_permissions, tenant_id, branch_id, display_name, phone)
                VALUES (%s, %s, %s, 'branch', %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (employee_login, hash_password(employee_password), pin_hash, payload.staff_role.value, Jsonb(permissions), tenant_id,
                 payload.branch_id, payload.display_name, payload.phone),
            ).fetchone()
            _store_employee_pin(connection, int(row["id"]), tenant_id, payload.pin)
            _sync_branch_managers(connection, tenant_id, state)
            version = int(workspace["version"]) + 1
            connection.execute(
                "UPDATE operational_state SET version = %s, payload = %s, updated_at = CURRENT_TIMESTAMP WHERE tenant_id = %s",
                (version, Jsonb(state), tenant_id),
            )
            connection.execute(
                """
                INSERT INTO operational_events
                  (tenant_id, state_version, actor_user_id, actor_login, actor_role, branch_id, action, entity_type, entity_id, payload)
                VALUES (%s, %s, %s, %s, %s, NULL, 'employee.create', 'employee', %s, %s)
                """,
                (tenant_id, version, user["id"], user["login"], user["role"], str(row["id"]), Jsonb({
                    "displayName": payload.display_name, "branchId": payload.branch_id,
                    "staffRole": payload.staff_role.value, "login": payload.login,
                    "pinConfigured": bool(payload.pin), "permissions": permissions,
                })),
            )
    except UniqueViolation as error:
        raise HTTPException(status_code=409, detail="Этот логин уже используется") from error
    return _employee_record(connection, tenant_id, int(row["id"]))


@app.put("/api/v1/employees/{employee_id}", tags=["employees"])
def update_employee(
    employee_id: int,
    payload: EmployeeUpdate,
    request: Request,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _company_admin_or_branch_manager(user)
    _assert_managed_branch(user, payload.branch_id)
    tenant_id = str(user["tenant_id"])
    try:
        with connection.transaction():
            workspace = _workspace_row(connection, tenant_id, for_update=True)
            state = workspace["payload"]
            if not any(entry["id"] == payload.branch_id for entry in state["branches"]):
                raise HTTPException(status_code=422, detail="Выбранное заведение не найдено")
            existing = connection.execute(
                """
                SELECT id, login, password_hash, pin_hash, branch_id, staff_role, access_permissions, display_name, phone,
                       is_active, account_version
                FROM auth_users
                WHERE id = %s AND tenant_id = %s AND role = 'branch' AND staff_role <> 'pos_terminal'
                  AND deleted_at IS NULL
                FOR UPDATE
                """,
                (employee_id, tenant_id),
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Сотрудник не найден")
            _assert_managed_branch(user, existing["branch_id"])
            target_role = payload.staff_role.value
            if user["role"] == "branch" and (existing["staff_role"] == "branch_manager" or target_role == "branch_manager"):
                raise HTTPException(status_code=403, detail="Руководителя назначает владелец аккаунта")
            permissions = _normalized_permissions(
                target_role,
                payload.permissions.model_dump() if payload.permissions is not None else existing["access_permissions"],
            )
            _assert_permission_delegation(user, permissions)
            target_login = payload.login or existing["login"]
            admin_access = any(permissions[key] for key in ADMIN_PERMISSION_KEYS)
            if admin_access and (not payload.login or target_login.endswith("@internal")):
                raise HTTPException(status_code=422, detail="Для доступа к админ-панели укажите логин")
            if admin_access and existing["login"].endswith("@internal") and not payload.password:
                raise HTTPException(status_code=422, detail="При включении админ-панели задайте временный пароль")
            if permissions["posAccess"] and not payload.pin and not existing["pin_hash"]:
                raise HTTPException(status_code=422, detail="Для доступа к кассе укажите PIN из 4 цифр")
            target_pin = payload.pin
            if not target_pin and payload.is_active and (
                existing["branch_id"] != payload.branch_id or not existing["is_active"]
            ) and existing["pin_hash"]:
                saved_pin = connection.execute(
                    "SELECT pgp_sym_decrypt(pin_encrypted, %s) AS pin FROM auth_users WHERE id = %s",
                    (_employee_pin_key(), employee_id),
                ).fetchone()
                target_pin = saved_pin["pin"] if saved_pin else None
                if not target_pin:
                    raise HTTPException(status_code=422, detail="Задайте новый PIN при переносе или активации сотрудника")
            if payload.is_active:
                _assert_unique_employee_pin(connection, tenant_id, payload.branch_id, target_pin, employee_id)
            access_changed = (
                existing["login"].lower() != target_login.lower()
                or existing["branch_id"] != payload.branch_id
                or existing["staff_role"] != target_role
                or _normalized_permissions(existing["staff_role"], existing["access_permissions"]) != permissions
                or bool(existing["is_active"]) != payload.is_active
                or bool(payload.password)
            )
            password_hash = hash_password(payload.password) if payload.password else existing["password_hash"]
            pin_hash = hash_pin(payload.pin) if payload.pin else existing["pin_hash"]
            account_version = int(existing["account_version"]) + (1 if access_changed else 0)
            connection.execute(
                """
                UPDATE auth_users
                SET display_name = %s, phone = %s, login = %s, branch_id = %s, staff_role = %s, access_permissions = %s,
                    password_hash = %s, pin_hash = %s, pin_failed_attempts = 0, pin_locked_until = NULL,
                    is_active = %s, account_version = %s,
                    email_verified_at = CASE WHEN lower(login) = lower(%s) THEN email_verified_at ELSE NULL END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (payload.display_name, payload.phone, target_login, payload.branch_id, target_role, Jsonb(permissions),
                 password_hash, pin_hash, payload.is_active, account_version, target_login, employee_id),
            )
            _store_employee_pin(connection, employee_id, tenant_id, payload.pin)
            if access_changed:
                connection.execute(
                    "UPDATE auth_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = %s AND revoked_at IS NULL",
                    (employee_id,),
                )
            if access_changed or payload.pin:
                connection.execute(
                    "UPDATE pos_operator_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE employee_user_id = %s AND revoked_at IS NULL",
                    (employee_id,),
                )
            _sync_branch_managers(connection, tenant_id, state)
            version = int(workspace["version"]) + 1
            connection.execute(
                "UPDATE operational_state SET version = %s, payload = %s, updated_at = CURRENT_TIMESTAMP WHERE tenant_id = %s",
                (version, Jsonb(state), tenant_id),
            )
            connection.execute(
                """
                INSERT INTO operational_events
                  (tenant_id, state_version, actor_user_id, actor_login, actor_role, branch_id, action, entity_type, entity_id, payload)
                VALUES (%s, %s, %s, %s, %s, NULL, 'employee.update', 'employee', %s, %s)
                """,
                (tenant_id, version, user["id"], user["login"], user["role"], str(employee_id), Jsonb({
                    "displayName": payload.display_name, "branchId": payload.branch_id,
                    "staffRole": target_role, "login": payload.login,
                    "isActive": payload.is_active, "passwordChanged": bool(payload.password),
                    "pinChanged": bool(payload.pin), "permissions": permissions,
                })),
            )
    except UniqueViolation as error:
        raise HTTPException(status_code=409, detail="Этот логин уже используется") from error
    return _employee_record(connection, tenant_id, employee_id)


def _assert_employee_responsibility_closed(connection: Connection, tenant_id: str, state: dict,
                                           employee_id: int) -> None:
    """Do not leave shifts or personal receipts that require this account stuck."""
    logistics = state.get("logisticsState", {})
    identity = str(employee_id)
    if any(shift.get("status") == "open" and str(shift.get("employeeId")) == identity
           for shift in logistics.get("productionShifts", [])):
        raise HTTPException(status_code=409, detail="Перед удалением сотрудник должен закрыть смену производства")
    if connection.execute(
        "SELECT id FROM pos_shifts WHERE tenant_id = %s AND opened_by_user_id = %s AND closed_at IS NULL LIMIT 1",
        (tenant_id, employee_id),
    ).fetchone():
        raise HTTPException(status_code=409, detail="Перед удалением закройте кассовую смену, открытую сотрудником")
    for document in logistics.get("custodyDocuments", []):
        if (document.get("status") == "pending" and document.get("kind") in {"transfer", "handover"}
                and str((document.get("recipient") or {}).get("id")) == identity):
            raise HTTPException(status_code=409, detail="Перед удалением завершите или отмените передачи, адресованные лично сотруднику")
    # Closed shifts, pooled handovers and existing stock keep the original actor
    # identity; the next cashier, cook or manager can continue their accounting.


@app.delete("/api/v1/employees/{employee_id}", tags=["employees"])
def delete_employee(
    employee_id: int,
    request: Request,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _company_admin_or_branch_manager(user)
    if str(employee_id) == str(user["id"]):
        raise HTTPException(status_code=403, detail="Нельзя удалить собственную учётную запись")
    tenant_id = str(user["tenant_id"])
    with connection.transaction():
        workspace = _workspace_row(connection, tenant_id, for_update=True)
        state = workspace["payload"]
        employee = connection.execute(
            """
            SELECT id, login, display_name, branch_id, staff_role
            FROM auth_users
            WHERE id = %s AND tenant_id = %s AND role = 'branch'
              AND staff_role <> 'pos_terminal' AND deleted_at IS NULL
            FOR UPDATE
            """,
            (employee_id, tenant_id),
        ).fetchone()
        if not employee:
            raise HTTPException(status_code=404, detail="Сотрудник не найден")
        _assert_managed_branch(user, employee["branch_id"])
        if user["role"] == "branch" and employee["staff_role"] == "branch_manager":
            raise HTTPException(status_code=403, detail="Руководителя удаляет владелец аккаунта")
        _assert_employee_responsibility_closed(connection, tenant_id, state, employee_id)
        from .payroll import current_shift, stop_employee
        if current_shift(state, employee_id):
            raise HTTPException(409, "Перед удалением закройте рабочую смену сотрудника")
        stop_employee(state, employee_id)
        # Keep the original identity for history. The partial unique login index
        # lets a new employee reuse this login without inheriting this user ID.
        connection.execute(
            """
            UPDATE auth_users
            SET deleted_at = CURRENT_TIMESTAMP, is_active = FALSE,
                account_version = account_version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
            """,
            (employee_id, tenant_id),
        )
        connection.execute(
            "UPDATE auth_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = %s AND revoked_at IS NULL",
            (employee_id,),
        )
        connection.execute(
            "UPDATE pos_operator_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE employee_user_id = %s AND revoked_at IS NULL",
            (employee_id,),
        )
        _sync_branch_managers(connection, tenant_id, state)
        version = int(workspace["version"]) + 1
        connection.execute(
            "UPDATE operational_state SET version = %s, payload = %s, updated_at = CURRENT_TIMESTAMP WHERE tenant_id = %s",
            (version, Jsonb(state), tenant_id),
        )
        connection.execute(
            """
            INSERT INTO operational_events
              (tenant_id, state_version, actor_user_id, actor_login, actor_role, branch_id, action, entity_type, entity_id, payload)
            VALUES (%s, %s, %s, %s, %s, %s, 'employee.delete', 'employee', %s, %s)
            """,
            (tenant_id, version, user["id"], user["login"], user["role"], employee["branch_id"], str(employee_id), Jsonb({
                "displayName": employee["display_name"], "branchId": employee["branch_id"],
                "staffRole": employee["staff_role"], "login": employee["login"],
            })),
        )
    return {"ok": True, "employee_id": employee_id, "version": version}


def _tenant_record(connection: Connection, tenant_id: str) -> dict:
    row = connection.execute(
        """
        SELECT tenant.id, tenant.slug, tenant.name, tenant.status, tenant.created_at, tenant.updated_at,
               tenant.contact_email, tenant.phone, tenant.business_status, tenant.business_type,
               tenant.service_modes, tenant.employee_range,
               subscription.plan_code, subscription.status AS subscription_status,
               subscription.max_branches, subscription.trial_ends_at, subscription.current_period_ends_at,
               COALESCE(jsonb_array_length(workspace.payload -> 'branches'), 0) AS branch_count,
               workspace.payload -> 'branches' -> 0 ->> 'name' AS first_location_name,
               workspace.payload -> 'branches' -> 0 ->> 'address' AS first_location_address,
               COUNT(users.id) FILTER (WHERE users.is_active) AS active_users,
               MAX(users.login) FILTER (WHERE users.role = 'owner' AND users.is_active) AS owner_login,
               MAX(users.display_name) FILTER (WHERE users.role = 'owner' AND users.is_active) AS owner_name
        FROM tenants tenant
        LEFT JOIN tenant_subscriptions subscription ON subscription.tenant_id = tenant.id
        LEFT JOIN operational_state workspace ON workspace.tenant_id = tenant.id
        LEFT JOIN auth_users users ON users.tenant_id = tenant.id
        WHERE tenant.id = %s
        GROUP BY tenant.id, subscription.tenant_id, workspace.tenant_id
        """,
        (tenant_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    return dict(row)


def _validate_plan(code: str):
    if code not in {"canteen", "restaurant", "starter", "business", "enterprise"}:
        raise HTTPException(status_code=422, detail="Неизвестный тариф")


@app.get("/api/v1/platform/plans", tags=["platform"])
def list_plans(user: dict = Depends(current_user), connection: Connection = Depends(get_connection)) -> list[dict]:
    _platform_owner(user)
    return [dict(row) for row in connection.execute("SELECT * FROM platform_plans ORDER BY monthly_price, code").fetchall()]


@app.put("/api/v1/platform/plans/{code}", tags=["platform"])
def update_plan(code: str, payload: PlanPriceUpdate, request: Request, user: dict = Depends(current_user), connection: Connection = Depends(get_connection)) -> dict:
    _check_origin(request)
    _platform_owner(user)
    with connection.transaction():
        row = connection.execute("UPDATE platform_plans SET monthly_price = %s, annual_price = COALESCE(%s, annual_price), updated_at = CURRENT_TIMESTAMP WHERE code = %s RETURNING *", (payload.monthly_price, payload.annual_price, code)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Тариф не найден")
        connection.execute("INSERT INTO platform_events (actor_user_id, actor_login, action, payload) VALUES (%s, %s, 'plan.update', %s)", (user["id"], user["login"], Jsonb({"planCode": code, "monthlyPrice": str(row['monthly_price']), "annualPrice": str(row['annual_price'])})))
    return dict(row)


@app.get("/api/v1/platform/tenants", tags=["platform"])
def list_tenants(user: dict = Depends(current_user), connection: Connection = Depends(get_connection)) -> list[dict]:
    _platform_owner(user)
    tenant_ids = [row["id"] for row in connection.execute("SELECT id FROM tenants ORDER BY created_at DESC").fetchall()]
    return [_tenant_record(connection, tenant_id) for tenant_id in tenant_ids]


@app.post("/api/v1/platform/tenants", status_code=status.HTTP_201_CREATED, tags=["platform"])
def create_tenant(
    payload: TenantCreate,
    request: Request,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _platform_owner(user)
    return _provision_tenant(payload, user, connection)


def _provision_tenant(payload: TenantCreate, user: dict, connection: Connection) -> dict:
    _validate_plan(payload.plan_code)
    tenant_id = f"tenant-{uuid4()}"
    trial_ends_at = datetime.now(timezone.utc) + timedelta(days=payload.trial_days) if payload.trial_days else None
    subscription_status = "trialing" if payload.trial_days else "active"
    owner_login = str(payload.owner_login or payload.email)
    branch_id = "b1"
    state = new_tenant_state()
    if payload.plan_code == "restaurant":
        from .company_settings import company_settings
        state["companySettings"] = company_settings(state)
        state["companySettings"]["general"]["floorPlan"] = True
        state["companySettings"]["orders"]["tables"] = [f"Стол {number}" for number in range(1, 11)]
    branch = {
        "id": branch_id,
        "number": 1,
        "short": payload.location_name,
        "name": payload.location_name,
        "address": payload.location_address,
        "phone": payload.phone,
        "workHours": {"open": payload.location_open_time, "close": payload.location_close_time},
        "managerName": "Не назначен",
        "login": payload.slug,
        "status": "active",
        "route": f"Поставщики → {payload.location_name}",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "createdBy": payload.owner_name,
    }
    state["branches"] = [branch]
    inventory_items = [*state["ingredients"], *state["products"]]
    state["logisticsState"]["branchStocks"][branch_id] = {str(item["id"]): 0 for item in inventory_items}
    state["logisticsState"]["branchCosts"][branch_id] = {str(item["id"]): 0 for item in inventory_items}
    try:
        with connection.transaction():
            connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('account-login:'+payload.slug,))
            if connection.execute('SELECT id FROM auth_users WHERE lower(login) = %s AND deleted_at IS NULL LIMIT 1', (payload.slug,)).fetchone():
                raise HTTPException(409, 'Код компании уже используется как логин. Выберите другой.')
            connection.execute(
                """
                INSERT INTO tenants
                  (id, slug, name, status, contact_email, phone, business_status, business_type, service_modes, employee_range)
                VALUES (%s, %s, %s, 'active', %s, %s, %s, %s, %s, %s)
                """,
                (tenant_id, payload.slug, payload.name, payload.email, payload.phone,
                 payload.business_status, payload.business_type, Jsonb(payload.service_modes), payload.employee_range),
            )
            connection.execute(
                """
                INSERT INTO tenant_subscriptions (tenant_id, plan_code, status, max_branches, trial_ends_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (tenant_id, payload.plan_code, subscription_status, payload.max_branches, trial_ends_at),
            )
            connection.execute(
                "INSERT INTO operational_state (tenant_id, version, payload) VALUES (%s, 1, %s)",
                (tenant_id, Jsonb(state)),
            )
            connection.execute(
                """
                INSERT INTO auth_users (login, password_hash, role, staff_role, tenant_id, branch_id, display_name)
                VALUES (%s, %s, 'owner', 'company_admin', %s, NULL, %s)
                """,
                (owner_login, hash_password(payload.owner_password), tenant_id, payload.owner_name),
            )
            connection.execute(
                """
                INSERT INTO auth_users (login, password_hash, role, staff_role, tenant_id, branch_id, display_name)
                VALUES (%s, %s, 'branch', 'pos_terminal', %s, %s, 'Основная касса')
                """,
                (f"kassa-{uuid4().hex[:12]}", hash_password(payload.register_password), tenant_id, branch_id),
            )
            connection.execute(
                """
                INSERT INTO platform_events (actor_user_id, actor_login, action, tenant_id, payload)
                VALUES (%s, %s, 'tenant.create', %s, %s)
                """,
                (user["id"], user["login"], tenant_id, Jsonb({
                    "name": payload.name, "slug": payload.slug, "ownerLogin": owner_login,
                    "businessType": payload.business_type, "locationName": payload.location_name,
                    "locationAddress": payload.location_address, "planCode": payload.plan_code,
                    "maxBranches": payload.max_branches,
                })),
            )
    except UniqueViolation as error:
        constraint = error.diag.constraint_name or ""
        detail = "Этот логин уже используется" if "auth_users_login" in constraint else "Код компании уже используется"
        raise HTTPException(status_code=409, detail=detail) from error
    return _tenant_record(connection, tenant_id)


@app.delete("/api/v1/platform/tenants/{tenant_id}", tags=["platform"])
def delete_tenant(
    tenant_id: str,
    payload: TenantDelete,
    request: Request,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _platform_owner(user)
    with connection.transaction():
        tenant = connection.execute(
            "SELECT name FROM tenants WHERE id = %s FOR UPDATE", (tenant_id,),
        ).fetchone()
        if not tenant:
            raise HTTPException(404, "Компания не найдена")
        if payload.confirmation_name != tenant["name"]:
            raise HTTPException(400, "Введите точное название компании")
        if connection.execute('SELECT id FROM subscription_payments WHERE tenant_id = %s LIMIT 1', (tenant_id,)).fetchone():
            raise HTTPException(409, 'У аккаунта есть история платежей. Используйте архивирование для сохранения финансовой истории.')
        connection.execute("SELECT tenant_id FROM operational_state WHERE tenant_id = %s FOR UPDATE", (tenant_id,))
        # Child records must go first; sessions and PIN sessions cascade with users.
        for table in ("technical_card_components", "technical_cards", "catalog_items",
                      "operational_events", "audit_events", "pos_shifts", "platform_events"):
            connection.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tenant_id,))
        connection.execute("DELETE FROM auth_users WHERE tenant_id = %s", (tenant_id,))
        connection.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        connection.execute(
            "INSERT INTO platform_events (actor_user_id, actor_login, action, payload) VALUES (%s, %s, 'tenant.delete', %s)",
            (user["id"], user["login"], Jsonb({"deleted_tenant_id": tenant_id, "name": tenant["name"]})),
        )
    return {"deleted": True, "id": tenant_id}


@app.put("/api/v1/platform/tenants/{tenant_id}", tags=["platform"])
def update_tenant(
    tenant_id: str,
    payload: TenantUpdate,
    request: Request,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _platform_owner(user)
    with connection.transaction():
        existing = connection.execute(
            """
            SELECT tenant.name, tenant.status, tenant.contact_email, tenant.phone,
                   tenant.business_status, tenant.business_type, tenant.service_modes, tenant.employee_range,
                   subscription.plan_code,
                   subscription.status AS subscription_status, subscription.max_branches
            FROM tenants tenant
            JOIN tenant_subscriptions subscription ON subscription.tenant_id = tenant.id
            WHERE tenant.id = %s
            FOR UPDATE
            """,
            (tenant_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Компания не найдена")
        _validate_plan(payload.plan_code or existing["plan_code"])
        if (existing["plan_code"] == "restaurant") != ((payload.plan_code or existing["plan_code"]) == "restaurant"):
            workspace = _workspace_row(connection, tenant_id, for_update=True)["payload"]
            active_batches = any(batch.get("status") != "closed" for batch in workspace.get("logisticsState", {}).get("batches", []))
            if active_batches or workspace.get("posState", {}).get("openOrders"):
                raise HTTPException(status_code=409, detail="Перед сменой режима закройте партии производства и открытые заказы")
            from .company_settings import company_settings
            workspace["companySettings"] = company_settings(workspace)
            workspace["companySettings"]["general"]["floorPlan"] = payload.plan_code == "restaurant"
            if payload.plan_code == "restaurant" and not workspace["companySettings"]["orders"]["tables"]:
                workspace["companySettings"]["orders"]["tables"] = [f"Стол {number}" for number in range(1, 11)]
            connection.execute("UPDATE operational_state SET payload = %s, version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE tenant_id = %s", (Jsonb(workspace), tenant_id))
        values = {
            "name": payload.name or existing["name"],
            "status": payload.status or existing["status"],
            "contact_email": payload.email or existing["contact_email"],
            "phone": payload.phone or existing["phone"],
            "business_status": payload.business_status or existing["business_status"],
            "business_type": payload.business_type or existing["business_type"],
            "service_modes": payload.service_modes if payload.service_modes is not None else existing["service_modes"],
            "employee_range": payload.employee_range or existing["employee_range"],
            "plan_code": payload.plan_code or existing["plan_code"],
            "subscription_status": payload.subscription_status or existing["subscription_status"],
            "max_branches": payload.max_branches or existing["max_branches"],
        }
        connection.execute(
            """
            UPDATE tenants
            SET name = %s, status = %s, contact_email = %s, phone = %s,
                business_status = %s, business_type = %s, service_modes = %s,
                employee_range = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (values["name"], values["status"], values["contact_email"], values["phone"],
             values["business_status"], values["business_type"], Jsonb(values["service_modes"]),
             values["employee_range"], tenant_id),
        )
        connection.execute(
            """
            UPDATE tenant_subscriptions
            SET plan_code = %s, status = %s, max_branches = %s, updated_at = CURRENT_TIMESTAMP
            WHERE tenant_id = %s
            """,
            (values["plan_code"], values["subscription_status"], values["max_branches"], tenant_id),
        )
        if values["status"] != "active" or values["subscription_status"] == "canceled":
            connection.execute(
                """
                UPDATE auth_sessions session
                SET revoked_at = CURRENT_TIMESTAMP
                FROM auth_users account
                WHERE session.user_id = account.id AND account.tenant_id = %s AND session.revoked_at IS NULL
                """,
                (tenant_id,),
            )
        connection.execute(
            """
            INSERT INTO platform_events (actor_user_id, actor_login, action, tenant_id, payload)
            VALUES (%s, %s, 'tenant.update', %s, %s)
            """,
            (user["id"], user["login"], tenant_id, Jsonb(values)),
        )
    return _tenant_record(connection, tenant_id)


@app.put("/api/v1/platform/tenants/{tenant_id}/owner-access", tags=["platform"])
def update_tenant_owner_access(
    tenant_id: str,
    payload: TenantOwnerAccessUpdate,
    request: Request,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    _platform_owner(user)
    try:
        with connection.transaction():
            owner = connection.execute(
                """
                SELECT id, login, password_hash, display_name, account_version
                FROM auth_users
                WHERE tenant_id = %s AND role = 'owner' AND is_active
                FOR UPDATE
                """,
                (tenant_id,),
            ).fetchone()
            if not owner:
                raise HTTPException(status_code=404, detail="Администратор компании не найден")
            duplicate = connection.execute(
                "SELECT id FROM auth_users WHERE lower(login) = lower(%s) AND deleted_at IS NULL AND id <> %s",
                (payload.owner_login, owner["id"]),
            ).fetchone()
            if duplicate:
                raise HTTPException(status_code=409, detail="Этот логин уже используется")
            access_changed = owner["login"].lower() != payload.owner_login.lower() or bool(payload.owner_password)
            password_hash = hash_password(payload.owner_password) if payload.owner_password else owner["password_hash"]
            version = owner["account_version"] + (1 if access_changed else 0)
            connection.execute(
                """
                UPDATE auth_users
                SET login = %s, display_name = %s, password_hash = %s, account_version = %s,
                    email_verified_at = CASE WHEN lower(login) = lower(%s) THEN email_verified_at ELSE NULL END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (payload.owner_login, payload.owner_name, password_hash, version, payload.owner_login, owner["id"]),
            )
            if access_changed:
                connection.execute('UPDATE auth_action_tokens SET consumed_at=now() WHERE user_id=%s AND consumed_at IS NULL',(owner['id'],))
                connection.execute(
                    "UPDATE auth_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = %s AND revoked_at IS NULL",
                    (owner["id"],),
                )
            connection.execute(
                """
                INSERT INTO platform_events (actor_user_id, actor_login, action, tenant_id, payload)
                VALUES (%s, %s, 'tenant.owner_access.update', %s, %s)
                """,
                (user["id"], user["login"], tenant_id, Jsonb({
                    "ownerName": payload.owner_name,
                    "ownerLogin": payload.owner_login,
                    "passwordChanged": bool(payload.owner_password),
                })),
            )
    except UniqueViolation as error:
        raise HTTPException(status_code=409, detail="Этот логин уже используется") from error
    return _tenant_record(connection, tenant_id)


@app.get("/api/v1/platform/events", tags=["platform"])
def list_platform_events(
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> list[dict]:
    _platform_owner(user)
    return [dict(row) for row in connection.execute(
        "SELECT * FROM platform_events ORDER BY created_at DESC LIMIT %s", (limit,),
    ).fetchall()]


@app.get("/api/v1/workspace", tags=["operations"])
def get_workspace(user: dict = Depends(current_user), connection: Connection = Depends(get_connection)) -> dict:
    tenant_id = _tenant_user(user)
    row = _workspace_row(connection, tenant_id)
    return {"version": row["version"], "updatedAt": row["updated_at"], "state": visible_state(row["payload"], user)}


@app.post("/api/v1/workspace/inventories/{inventory_id}/export", tags=["operations"])
def export_inventory(
    inventory_id: str, payload: dict, request: Request,
    user: dict = Depends(current_user), connection: Connection = Depends(get_connection),
) -> dict:
    from .inventory_report import build_report, filename, workbook
    _check_origin(request)
    tenant_id = _tenant_user(user)
    if user.get("role") not in {"owner", "branch"}:
        raise HTTPException(status_code=403, detail="Инвентаризация недоступна")
    _authorize_staff_action(user, "inventory.save")
    state = visible_state(_workspace_row(connection, tenant_id)["payload"], user)
    try:
        report = build_report(state, inventory_id, payload.get("items"))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"xlsx": workbook(report), "filename": filename(report)}


@app.post("/api/v1/workspace/actions", tags=["operations"])
def workspace_action(
    command: WorkspaceActionInput, request: Request, user: dict = Depends(current_user),
    ashkana_pos_operator: str | None = Cookie(default=None),
    connection: Connection = Depends(get_connection),
) -> dict:
    _check_origin(request)
    if command.action in {"sale.create", "sale.import"} and request.headers.get("X-Ashkana-Client") != "pos":
        raise HTTPException(status_code=403, detail="Продажи проводятся через терминал с кассиром и сменой")
    tenant_id = _tenant_user(user)
    locked_workspace = _workspace_row(connection, tenant_id, for_update=True)
    acting_user = user
    previous_operation = None
    replayable_operations = {"supply.create", "batch.create", "pos.cash.movement"}
    pos_actions = {
        "work.shift.open", "work.shift.close",
        "pos.receiving.accept", "pos.receiving.reject", "pos.serving.writeoff", "pos.serving.surplus",
        "sale.import", "sale.create", "sale.refund", "pos.order.save", "pos.order.remove",
        "pos.customer.upsert", "pos.cash.movement", "supply.create", "pos.order.status",
        "batch.create", "batch.transfer", "batch.close", "batch.release", "batch.serve", "batch.serve_many",
    }
    if (command.action in pos_actions or command.action.startswith("custody.") or command.action.startswith("production.shift.")) and request.headers.get("X-Ashkana-Client") == "pos":
        operator = _current_pos_operator(connection, user, ashkana_pos_operator)
        shift = _current_pos_shift(connection, user)
        from .workspace import operation_replay, sale_replay
        replay_user = {**user, "id": operator["id"], "register_id": user["id"]}
        try:
            previous_sale = sale_replay(locked_workspace["payload"], replay_user, command.payload) if command.action == "sale.create" else None
            if command.action in replayable_operations:
                previous_operation = operation_replay(locked_workspace["payload"], replay_user, command.action, command.payload)
        except WorkspaceError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        if command.action == "sale.create" and not command.payload.get("requestId"):
            raise HTTPException(status_code=422, detail="Обновите терминал: не указан идентификатор оплаты")
        if not shift and not previous_sale and not previous_operation and operator.get("staff_role") != "production" and not command.action.startswith("work.shift."):
            raise HTTPException(status_code=409, detail="Сначала откройте кассовую смену")
        acting_user = {
            **user,
            "id": operator["id"],
            "login": operator["login"],
            "display_name": operator["display_name"],
            "branch_id": user["branch_id"],
            "staff_role": operator.get("staff_role") or "cashier",
            "access_permissions": operator.get("access_permissions") or {},
            "register_id": user["id"],
            "shift_id": shift["id"] if shift else None,
        }
    _authorize_staff_action(acting_user, command.action)
    if command.action in replayable_operations:
        from .workspace import operation_replay
        try:
            previous_operation = operation_replay(locked_workspace["payload"], acting_user, command.action, command.payload)
        except WorkspaceError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        if previous_operation:
            entity_type, entity_id = previous_operation
            return {"version": locked_workspace["version"],
                    "state": visible_state(locked_workspace["payload"], user if request.headers.get("X-Ashkana-Client") == "pos" else acting_user),
                    "entity": {"type": entity_type, "id": entity_id}}
    if command.action in {"batch.release", "batch.transfer", "custody.send", "custody.handover"}:
        recipient_id = str(command.payload.get("recipientId", ""))
        recipients = _production_recipients(connection, str(tenant_id), str(acting_user.get("branch_id") or command.payload.get("branchId", "")))
        selected = next((entry for entry in recipients if str(entry["id"]) == recipient_id), None)
        if not selected:
            raise HTTPException(status_code=422, detail="Выберите действующего получателя с правом производства")
        acting_user = {**acting_user, "_custody_recipient": selected}
    if acting_user.get("role") == "branch" and not acting_user.get("register_id"):
        acting_user["_company_write"] = True
    try:
        with connection.transaction():
            row = _workspace_row(connection, tenant_id, for_update=True)
            state = row["payload"]
            if acting_user.get("staff_role") == "production" and not command.action.startswith(("production.shift.", "work.shift.")):
                kitchen_shift = production_shifts.current(state, str(acting_user.get("branch_id")))
                if not kitchen_shift or str(kitchen_shift["employeeId"]) != str(acting_user["id"]):
                    raise HTTPException(status_code=409, detail="Сначала примите смену производства")
                acting_user = {**acting_user, "production_shift_id": kitchen_shift["id"]}

            if command.action == "branch.upsert" and not command.payload.get("id"):
                active_count = sum(branch.get("status") == "active" for branch in state["branches"])
                if active_count >= int(user.get("max_branches") or 1):
                    raise HTTPException(status_code=409, detail="Достигнут лимит точек по тарифу компании")
            if command.action.startswith("payroll."):
                if acting_user.get("role") != "owner":
                    raise HTTPException(403, "Зарплата доступна только владельцу компании")
                acting_user = {**acting_user, "_payroll_employees": _payroll_roster(connection, tenant_id), "_workspace_version": int(row["version"])}
            entity_type, entity_id = apply_action(state, acting_user, command.action, command.payload)
            if command.action == "supply.create" and command.payload.get("photoId"):
                from .supply_photos import PhotoStorageError, bind_supply
                try:
                    bind_supply(connection, state, acting_user, command.payload, entity_id)
                except PhotoStorageError as error:
                    raise HTTPException(status_code=error.status_code, detail=str(error)) from error
            if command.action == "branch.upsert":
                _update_branch_account(connection, tenant_id, command.payload, state)
            version = int(row["version"]) + 1
            connection.execute(
                "UPDATE operational_state SET version = %s, payload = %s, updated_at = CURRENT_TIMESTAMP WHERE tenant_id = %s",
                (version, Jsonb(state), tenant_id),
            )
            audit_payload = {key: value for key, value in command.payload.items() if key != "password"}
            if command.action == "settings.update":
                audit_payload = {"section": command.payload.get("section"), "fields": list(command.payload.get("values", {}))}
            connection.execute(
                """
                INSERT INTO operational_events
                  (tenant_id, state_version, actor_user_id, actor_login, actor_role, branch_id, action, entity_type, entity_id, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (tenant_id, version, acting_user["id"], acting_user["login"], acting_user["role"], acting_user.get("branch_id"), command.action, entity_type, entity_id, Jsonb(audit_payload)),
            )
    except WorkspaceError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return {"version": version, "state": visible_state(state, user if request.headers.get("X-Ashkana-Client") == "pos" else acting_user), "entity": {"type": entity_type, "id": entity_id}}


@app.get("/api/v1/audit-events", tags=["operations"])
def list_operational_events(
    limit: int = Query(default=100, ge=1, le=500), user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> list[dict]:
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Журнал доступен главному администратору")
    return [dict(row) for row in connection.execute(
        "SELECT * FROM operational_events WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s",
        (user["tenant_id"], limit),
    ).fetchall()]


def _load_graph(connection: Connection, tenant_id: str) -> tuple[dict[str, dict], dict[int, dict], dict[str, Decimal]]:
    item_rows = connection.execute(
        """
        SELECT id, item_type, name, category, unit, purchase_cost, sale_price,
               is_active, version, created_at, updated_at
        FROM catalog_items
        WHERE tenant_id = %s AND is_active
        ORDER BY item_type, name
        """,
        (tenant_id,),
    ).fetchall()
    card_rows = connection.execute(
        """
        SELECT id, output_item_id, yield_quantity, yield_weight_grams, station, version, created_at, updated_at
        FROM technical_cards
        WHERE tenant_id = %s
        ORDER BY id
        """,
        (tenant_id,),
    ).fetchall()
    component_rows = connection.execute(
        """
        SELECT id, technical_card_id, component_item_id, gross_quantity, net_quantity
        FROM technical_card_components
        WHERE tenant_id = %s
        ORDER BY technical_card_id, id
        """,
        (tenant_id,),
    ).fetchall()

    items = {row["id"]: dict(row) for row in item_rows}
    cards = {row["id"]: {**dict(row), "components": []} for row in card_rows}
    output_to_card: dict[str, tuple[Decimal, list[tuple[str, Decimal]]]] = {}
    for row in component_rows:
        component = dict(row)
        card = cards.get(row["technical_card_id"])
        if card:
            card["components"].append(component)
    for card in cards.values():
        output_to_card[card["output_item_id"]] = (
            card["yield_quantity"],
            [(component["component_item_id"], component["gross_quantity"]) for component in card["components"]],
        )
    try:
        costs = calculate_unit_costs(
            {item_id: item["purchase_cost"] for item_id, item in items.items()},
            output_to_card,
        )
    except DomainError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return items, cards, costs


def _card_response(connection: Connection, tenant_id: str, card_id: int) -> dict:
    items, cards, costs = _load_graph(connection, tenant_id)
    card = cards.get(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Техкарта не найдена")
    output_item = items[card["output_item_id"]]
    components = []
    total_cost = Decimal("0")
    for component in card["components"]:
        item = items[component["component_item_id"]]
        unit_cost = costs.get(item["id"], Decimal("0"))
        line_cost = unit_cost * component["gross_quantity"]
        total_cost += line_cost
        components.append({
            "id": component["id"],
            "item": item,
            "gross_quantity": component["gross_quantity"],
            "net_quantity": component["net_quantity"],
            "unit_cost": unit_cost,
            "line_cost": line_cost,
        })
    return {
        **{key: value for key, value in card.items() if key != "components"},
        "output_item": output_item,
        "unit_cost": costs.get(output_item["id"], Decimal("0")),
        "total_cost": total_cost,
        "components": components,
    }


def _validate_component_ids(connection: Connection, tenant_id: str, component_ids: list[str]) -> None:
    existing = {
        row["id"]
        for row in connection.execute(
            "SELECT id FROM catalog_items WHERE tenant_id = %s AND is_active AND id = ANY(%s)",
            (tenant_id, component_ids),
        ).fetchall()
    }
    missing = sorted(set(component_ids) - existing)
    if missing:
        raise HTTPException(status_code=422, detail={"message": "Позиции состава не найдены", "item_ids": missing})


def _validate_cycle(connection: Connection, tenant_id: str, output_item_id: str, component_ids: list[str]) -> None:
    rows = connection.execute(
        """
        SELECT tc.output_item_id, array_agg(tcc.component_item_id ORDER BY tcc.id) AS component_ids
        FROM technical_cards tc
        LEFT JOIN technical_card_components tcc ON tcc.technical_card_id = tc.id AND tcc.tenant_id = tc.tenant_id
        WHERE tc.tenant_id = %s
        GROUP BY tc.output_item_id
        """,
        (tenant_id,),
    ).fetchall()
    adjacency = {row["output_item_id"]: [value for value in row["component_ids"] if value] for row in rows}
    cycle = find_cycle(output_item_id, component_ids, adjacency)
    if cycle:
        raise HTTPException(status_code=422, detail={"message": "Обнаружен цикл в техкартах", "path": cycle})


@app.get("/health", tags=["system"])
def health(connection: Connection = Depends(get_connection)) -> dict:
    row = connection.execute("SELECT current_database() AS database").fetchone()
    migration = connection.execute("SELECT max(version) AS version FROM schema_migrations").fetchone()
    return {"status": "ok", "database": row["database"], "migration": migration["version"]}


@app.get("/api/v1/catalog-items", tags=["catalog"])
def list_catalog_items(
    item_type: list[ItemType] | None = Query(default=None),
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> list[dict]:
    _protect_cost_data(user)
    items, cards, costs = _load_graph(connection, _tenant_user(user))
    types = {value.value for value in item_type} if item_type else None
    items_with_cards = {card["output_item_id"] for card in cards.values()}
    return [
        {**item, "unit_cost": costs.get(item["id"], Decimal("0")), "has_technical_card": item["id"] in items_with_cards}
        for item in items.values()
        if types is None or item["item_type"] in types
    ]


@app.get("/api/v1/technical-cards", tags=["technical-cards"])
def list_technical_cards(user: dict = Depends(current_user), connection: Connection = Depends(get_connection)) -> list[dict]:
    _protect_cost_data(user)
    tenant_id = _tenant_user(user)
    _, cards, _ = _load_graph(connection, tenant_id)
    return [_card_response(connection, tenant_id, card_id) for card_id in cards]


@app.get("/api/v1/technical-cards/{card_id}", tags=["technical-cards"])
def get_technical_card(card_id: int, user: dict = Depends(current_user), connection: Connection = Depends(get_connection)) -> dict:
    _protect_cost_data(user)
    return _card_response(connection, _tenant_user(user), card_id)


@app.post("/api/v1/technical-cards", status_code=status.HTTP_201_CREATED, tags=["technical-cards"])
def create_technical_card(
    payload: TechnicalCardCreate,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Техкарты изменяет главный администратор")
    tenant_id = _tenant_user(user)
    output_id = payload.output_item.id or f"item-{uuid4()}"
    component_ids = [component.item_id for component in payload.components]
    _validate_component_ids(connection, tenant_id, component_ids)
    _validate_cycle(connection, tenant_id, output_id, component_ids)
    try:
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO catalog_items
                  (id, tenant_id, item_type, name, category, unit, purchase_cost, sale_price)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    output_id,
                    tenant_id,
                    payload.output_item.item_type.value,
                    payload.output_item.name,
                    payload.output_item.category,
                    payload.output_item.unit,
                    payload.output_item.purchase_cost,
                    payload.output_item.sale_price,
                ),
            )
            card = connection.execute(
                """
                INSERT INTO technical_cards (tenant_id, output_item_id, yield_quantity, yield_weight_grams, station)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (tenant_id, output_id, payload.yield_quantity, payload.yield_weight_grams, payload.station),
            ).fetchone()
            connection.executemany(
                """
                INSERT INTO technical_card_components
                  (tenant_id, technical_card_id, component_item_id, gross_quantity, net_quantity)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (tenant_id, card["id"], component.item_id, component.gross_quantity, component.net_quantity)
                    for component in payload.components
                ],
            )
            connection.execute(
                """
                INSERT INTO audit_events (tenant_id, actor, action, entity_type, entity_id, after_state)
                VALUES (%s, %s, 'create', 'technical_card', %s, %s)
                """,
                (tenant_id, user["login"], str(card["id"]), Jsonb(payload.model_dump(mode="json"))),
            )
    except (UniqueViolation, ForeignKeyViolation, CheckViolation) as error:
        raise HTTPException(status_code=409, detail="Не удалось создать техкарту: конфликт или некорректная связь") from error
    return _card_response(connection, tenant_id, card["id"])


@app.put("/api/v1/technical-cards/{card_id}", tags=["technical-cards"])
def update_technical_card(
    card_id: int,
    payload: TechnicalCardUpdate,
    user: dict = Depends(current_user),
    connection: Connection = Depends(get_connection),
) -> dict:
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Техкарты изменяет главный администратор")
    tenant_id = _tenant_user(user)
    existing = _card_response(connection, tenant_id, card_id)
    output_id = existing["output_item_id"]
    component_ids = [component.item_id for component in payload.components]
    if output_id in component_ids:
        raise HTTPException(status_code=422, detail="Позиция не может входить в собственную техкарту")
    _validate_component_ids(connection, tenant_id, component_ids)
    _validate_cycle(connection, tenant_id, output_id, component_ids)
    try:
        with connection.transaction():
            updated = connection.execute(
                """
                UPDATE technical_cards
                SET yield_quantity = %s, yield_weight_grams = %s, station = %s,
                    version = version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = %s AND id = %s AND version = %s
                RETURNING id
                """,
                (payload.yield_quantity, payload.yield_weight_grams, payload.station, tenant_id, card_id, payload.version),
            ).fetchone()
            if not updated:
                raise HTTPException(status_code=409, detail="Техкарта уже изменена другим пользователем; обновите страницу")
            connection.execute(
                """
                UPDATE catalog_items
                SET name = %s, category = %s, unit = %s, purchase_cost = %s,
                    sale_price = %s, version = version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = %s AND id = %s
                """,
                (payload.name, payload.category, payload.unit, payload.purchase_cost, payload.sale_price, tenant_id, output_id),
            )
            connection.execute(
                "DELETE FROM technical_card_components WHERE tenant_id = %s AND technical_card_id = %s",
                (tenant_id, card_id),
            )
            connection.executemany(
                """
                INSERT INTO technical_card_components
                  (tenant_id, technical_card_id, component_item_id, gross_quantity, net_quantity)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (tenant_id, card_id, component.item_id, component.gross_quantity, component.net_quantity)
                    for component in payload.components
                ],
            )
            connection.execute(
                """
                INSERT INTO audit_events (tenant_id, actor, action, entity_type, entity_id, before_state, after_state)
                VALUES (%s, %s, 'update', 'technical_card', %s, %s, %s)
                """,
                (
                    tenant_id,
                    user["login"],
                    str(card_id),
                    Jsonb(existing),
                    Jsonb(payload.model_dump(mode="json")),
                ),
            )
    except HTTPException:
        raise
    except (UniqueViolation, ForeignKeyViolation, CheckViolation) as error:
        raise HTTPException(status_code=409, detail="Не удалось обновить техкарту: конфликт или некорректная связь") from error
    return _card_response(connection, tenant_id, card_id)


@app.get('/api/v1/pos/sales-report', tags=['pos'])
def terminal_sales_report(start: datetime, end: datetime, cashier: str = '', products: bool = True, ashkana_pos_operator: str | None = Cookie(default=None), user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
    from .company_settings import require_manager
    from .sales_report import build_report, workbook
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    if operator.get('staff_role') == 'production':
        raise HTTPException(status_code=403, detail='Недоступно сотруднику производства')
    state = _workspace_row(connection, str(user['tenant_id']))['payload']
    try:
        require_manager(state, operator, 'reports')
        # Include retained and moved accounts: historical receipt ownership is
        # an immutable user ID, independent of a reused login or current branch.
        cashier_accounts = connection.execute(
            'SELECT id, display_name, is_active, deleted_at FROM auth_users WHERE tenant_id = %s',
            (user['tenant_id'],),
        ).fetchall()
        report = build_report(state, user['branch_id'], start, end, cashier, cashier_accounts)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {**report, 'xlsx': workbook(report, products)}


@app.post('/api/v1/pos/sales-import/preview', tags=['pos'])
def preview_sales_import(payload: dict, request: Request, ashkana_pos_operator: str | None = Cookie(default=None), user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
    _check_origin(request)
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    acting = {**user, **operator, 'role': 'branch', 'branch_id': user['branch_id']}
    _authorize_staff_action(acting, 'sale.import')
    if user.get('plan_code') == 'restaurant':
        raise HTTPException(status_code=403, detail='Импорт списывает блюда с раздачи столовой')
    from .sales_import import preview
    state = _workspace_row(connection, str(user['tenant_id']))['payload']
    try:
        return preview(state, user['branch_id'], payload.get('file'))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

from .onboarding_requests import install as install_onboarding_requests
install_onboarding_requests(app, current_user, get_connection, _check_origin, _platform_owner, get_settings)


def _payroll_roster(connection, tenant_id):
    return [dict(row) for row in connection.execute("SELECT id, display_name, staff_role, branch_id, is_active, deleted_at FROM auth_users WHERE tenant_id = %s AND role = 'branch' AND staff_role <> 'pos_terminal' ORDER BY display_name", (tenant_id,)).fetchall()]


@app.get('/api/v1/payroll', tags=['payroll'])
def payroll_context(start: str | None = None, end: str | None = None, user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
    if user.get('role') != 'owner':
        raise HTTPException(403, 'Зарплата доступна только владельцу компании')
    from . import payroll
    from .company_settings import company_settings
    tenant_id = _tenant_user(user)
    row = _workspace_row(connection, tenant_id)
    state = row['payload']
    current = payroll.today(state)
    default_end = current - timedelta(days=1)
    first = start or default_end.replace(day=1).isoformat()
    last = end or default_end.isoformat()
    roster = _payroll_roster(connection, tenant_id)
    try:
        calculated = payroll.report(state, first, last, roster)
    except WorkspaceError as error:
        raise HTTPException(error.status_code, str(error)) from error
    data = payroll.data(state)
    runs = []
    for run in data.get('runs', []):
        runs.append({**run, 'rows': [{**r, 'paid': payroll.run_paid(state, run['id'], r['employeeId'])} for r in run['rows']]})
    from copy import deepcopy
    from .workspace import _ensure_finance
    finance = _ensure_finance(deepcopy(state))
    return {**calculated, 'version': row['version'], 'companyToday': current.isoformat(), 'currency': company_settings(state)['general']['currency'], 'timezone': str(payroll.zone(state)), 'employees': roster, 'policies': data.get('policies', []), 'runs': runs, 'payments': data.get('payments', []), 'events': data.get('events', [])[-300:], 'workShifts': data.get('workShifts', [])[-200:], 'balances': payroll.balances(state), 'accounts': [a for a in finance.get('accounts', []) if a.get('status') == 'active' and a.get('type') in {'bank', 'safe'}], 'categories': sorted({str(i.get('category', '')) for key in ('products', 'recipes') for i in state.get(key, [])})}


@app.get('/api/v1/pos/work-shift', tags=['payroll'])
def current_work_shift(ashkana_pos_operator: str | None = Cookie(default=None), user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
    from .payroll import current_shift
    operator = _current_pos_operator(connection, user, ashkana_pos_operator)
    state = _workspace_row(connection, _tenant_user(user))['payload']
    return {'shift': current_shift(state, operator['id'])}


@app.get('/api/v1/pnl', tags=['finance'])
def pnl_report(start: str, end: str, branch: str = 'all', user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
    if user.get('role') != 'owner':
        raise HTTPException(403, 'P&L доступен только владельцу компании')
    from .pnl import report
    state = _workspace_row(connection, _tenant_user(user))['payload']
    try:
        return report(state, start, end, None if branch == 'all' else branch)
    except WorkspaceError as error:
        raise HTTPException(error.status_code, str(error)) from error

from .offline_pos import install as install_offline_pos
install_offline_pos(app)

from .self_registration import install as install_self_registration
install_self_registration(app)

from .mailer import install as install_mailer
install_mailer(app)

from .billing import install as install_billing
install_billing(app)

from .account_access import install as install_account_access
install_account_access(app)

from .operations import install as install_operations
install_operations(app)
