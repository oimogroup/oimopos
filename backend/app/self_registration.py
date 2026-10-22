"""Atomic public trial signup; retrying a request never renews its trial."""
import hashlib
import hmac
import secrets
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, Response
from pydantic import Field, field_validator, TypeAdapter

from .onboarding_requests import ConnectionRequest
from .schemas import AccountLogin, ContactEmail, LoginInput, TenantCreate, UserPassword


class SignupInput(ConnectionRequest):
    email: Annotated[ContactEmail, Field(max_length=64)]
    password: UserPassword

    @field_validator('email')
    @classmethod
    def login_compatible(cls, value):
        return TypeAdapter(AccountLogin).validate_python(value)


def install(app):
    from . import main

    @app.post('/api/v1/public/register', status_code=201, tags=['public'])
    def register(payload: SignupInput, request: Request, response: Response,
                 connection=Depends(main.get_connection)):
        main._check_origin(request)
        if payload.website:
            raise HTTPException(422, 'Не удалось создать аккаунт')
        # Validate the login format before any writes, using the same owner schema.
        tenant_input = TenantCreate(
            name=payload.company, slug='trial-'+uuid4().hex[:16],
            owner_name=payload.name, email=payload.email, phone=payload.phone,
            owner_password=payload.password, register_password=secrets.token_urlsafe(48),
            location_name=payload.company, location_address='Укажите адрес в настройках',
            business_type='restaurant' if payload.plan == 'restaurant' else 'canteen',
            service_modes=['tables'] if payload.plan == 'restaurant' else ['counter'],
            plan_code=payload.plan, max_branches=1, trial_days=14,
        )
        key = main.get_settings().employee_pin_key.encode()
        fingerprint = hmac.new(key, payload.model_dump_json(exclude={'request_id', 'website'}).encode(), hashlib.sha256).hexdigest()
        peer = request.client.host if request.client else 'unknown'
        peer_key = hmac.new(key, peer.encode(), hashlib.sha256).hexdigest()
        with connection.transaction():
            for lock in ('request:'+str(payload.request_id), 'email:'+payload.email,
                         'phone:'+payload.phone, 'peer:'+peer_key):
                connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', ('signup:'+lock,))
            previous = connection.execute(
                'SELECT fingerprint, tenant_id FROM trial_registrations WHERE id = %s',
                (payload.request_id,),
            ).fetchone()
            if previous:
                if not hmac.compare_digest(previous['fingerprint'], fingerprint):
                    raise HTTPException(409, 'Данные регистрации изменились. Обновите страницу.')
            else:
                recent = connection.execute(
                    "SELECT count(*) FILTER (WHERE peer_key = %s AND created_at > now() - interval '1 hour') AS peer_total, count(*) FILTER (WHERE phone = %s) AS phone_total FROM trial_registrations",
                    (peer_key, payload.phone),
                ).fetchone()
                if recent['peer_total'] >= 10 or recent['phone_total'] >= 1:
                    raise HTTPException(429, 'Пробный аккаунт уже создан или достигнут лимит. Войдите в существующий аккаунт либо свяжитесь с Oimo.')
                if connection.execute('SELECT id FROM auth_users WHERE lower(email) = %s AND deleted_at IS NULL LIMIT 1', (payload.email,)).fetchone():
                    raise HTTPException(409, 'Этот email уже используется. Войдите в аккаунт.')
                tenant = main._provision_tenant(tenant_input, {'id': None, 'login': 'self-registration'}, connection)
                connection.execute(
                    'INSERT INTO trial_registrations (id, tenant_id, email, phone, peer_key, fingerprint) VALUES (%s,%s,%s,%s,%s,%s)',
                    (payload.request_id, tenant['id'], payload.email, payload.phone, peer_key, fingerprint),
                )
                from .mailer import enqueue_welcome
                enqueue_welcome(connection, tenant, payload.name, payload.email)
                from .account_access import send_link
                owner=connection.execute("SELECT * FROM auth_users WHERE tenant_id=%s AND role='owner'",(tenant['id'],)).fetchone()
                send_link(connection,owner,'verify')
            # Login validates the account and trial even on an old request replay.
            result = main.login(LoginInput(login=payload.email, password=payload.password), response, request, connection)
        return {**result, 'redirect': '/admin'}
