"""Public product catalogue and connection requests; no access to tenant data."""
import hashlib
import hmac
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConnectionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_id: UUID
    name: str = Field(min_length=2, max_length=100)
    company: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=7, max_length=32)
    plan: Literal['canteen', 'restaurant']
    consent: Literal[True]
    website: str = Field(default='', max_length=200)

    @field_validator('phone')
    @classmethod
    def valid_phone(cls, value):
        if any(c not in '+0123456789 ()-' for c in value):
            raise ValueError('Укажите номер телефона')
        digits = ''.join(c for c in value if c.isdigit())
        if not 7 <= len(digits) <= 15:
            raise ValueError('Проверьте номер телефона')
        return digits


def install(app, current_user, get_connection, check_origin, platform_owner, settings):
    @app.get('/api/v1/public/plans', tags=['public'])
    def public_plans(connection=Depends(get_connection)):
        return [dict(row) for row in connection.execute(
            "SELECT code, name, monthly_price, annual_price FROM platform_plans WHERE code IN ('canteen', 'restaurant') ORDER BY monthly_price, code"
        ).fetchall()]

    @app.post('/api/v1/public/connection-requests', status_code=201, tags=['public'])
    def submit(payload: ConnectionRequest, request: Request, connection=Depends(get_connection)):
        check_origin(request)
        if payload.website:
            raise HTTPException(422, 'Не удалось отправить заявку')
        fingerprint = hashlib.sha256(payload.model_dump_json(exclude={'request_id', 'website'}).encode()).hexdigest()
        # The peer address is never trusted from arbitrary forwarded headers.
        peer = request.client.host if request.client else 'unknown'
        peer_key = hmac.new(settings().employee_pin_key.encode(), peer.encode(), hashlib.sha256).hexdigest()
        with connection.transaction():
            # Serialize the rate check even when two requests arrive together.
            connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', ('onboarding:'+peer_key,))
            connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', ('onboarding-phone:'+payload.phone,))
            previous = connection.execute('SELECT fingerprint FROM connection_requests WHERE id = %s', (payload.request_id,)).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'Заявка уже отправлена. Для новых данных обновите страницу.')
                return {'ok': True}
            recent = connection.execute("SELECT count(*) FILTER (WHERE peer_key = %s) AS peer_total, count(*) FILTER (WHERE phone = %s) AS phone_total FROM connection_requests WHERE created_at > now() - interval '1 hour'", (peer_key, payload.phone)).fetchone()
            if recent['peer_total'] >= 100 or recent['phone_total'] >= 3:
                raise HTTPException(429, 'Слишком много заявок. Попробуйте позже.')
            connection.execute('INSERT INTO connection_requests (id, name, company, phone, plan, fingerprint, peer_key) VALUES (%s,%s,%s,%s,%s,%s,%s)', (payload.request_id, payload.name, payload.company, payload.phone, payload.plan, fingerprint, peer_key))
        return {'ok': True}

    @app.get('/api/v1/platform/connection-requests', tags=['platform'])
    def requests(user=Depends(current_user), connection=Depends(get_connection)):
        platform_owner(user)
        return [dict(row) for row in connection.execute('SELECT id, name, company, phone, plan, status, created_at FROM connection_requests ORDER BY created_at DESC LIMIT 200').fetchall()]

    @app.patch('/api/v1/platform/connection-requests/{request_id}/contacted', tags=['platform'])
    def contacted(request_id: UUID, request: Request, user=Depends(current_user), connection=Depends(get_connection)):
        check_origin(request)
        platform_owner(user)
        with connection.transaction():
            row = connection.execute("UPDATE connection_requests SET status = 'contacted' WHERE id = %s RETURNING id", (request_id,)).fetchone()
            if not row:
                raise HTTPException(404, 'Заявка не найдена')
            connection.execute("INSERT INTO platform_events (actor_user_id, actor_login, action, payload) VALUES (%s, %s, 'connection_request.contacted', %s)", (user['id'], user['login'], Jsonb({'requestId': str(request_id)})))
        return {'ok': True}
