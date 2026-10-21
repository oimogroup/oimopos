"""Public acquisition flow: validation, retries, rate limits and platform access."""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.onboarding_requests import install


class Connection:
    def __init__(self):
        self.rows = {}
        self.calls = []
        self.peer_total = self.phone_total = 0

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        one, many = None, []
        if 'SELECT fingerprint' in sql:
            one = self.rows.get(str(params[0]))
        elif 'FILTER (WHERE peer_key' in sql:
            one = {'peer_total': self.peer_total, 'phone_total': self.phone_total}
        elif 'INSERT INTO connection_requests' in sql:
            self.rows[str(params[0])] = {'fingerprint': params[5]}
        elif 'FROM platform_plans' in sql:
            many = [{'code': 'canteen', 'name': 'Столовая', 'monthly_price': 2000}]
        elif 'UPDATE connection_requests' in sql:
            one = {'id': params[0]} if str(params[0]) in self.rows else None
        elif 'SELECT id, name, company' in sql:
            many = []
        return SimpleNamespace(fetchone=lambda: one, fetchall=lambda: many)


@pytest.fixture
def scenario():
    app = FastAPI()
    connection = Connection()
    user = {'id': 1, 'login': 'platform', 'role': 'platform_owner'}
    install(app, lambda: user, lambda: connection, main._check_origin, main._platform_owner,
            lambda: SimpleNamespace(employee_pin_key='test-pin-key-only'))
    return TestClient(app), connection, user


def payload(**values):
    return {'request_id': str(uuid4()), 'name': 'Анна', 'company': 'Кафе Утро',
            'phone': '+996 (555) 123-456', 'plan': 'restaurant', 'consent': True, **values}


HEADERS = {'Origin': 'http://127.0.0.1:8000'}
PATH = '/api/v1/public/connection-requests'


def test_public_catalogue_exposes_only_product_pricing(scenario):
    client, db, _ = scenario
    response = client.get('/api/v1/public/plans')
    assert response.status_code == 200
    assert set(response.json()[0]) == {'code', 'name', 'monthly_price'}
    assert "WHERE code IN ('canteen', 'restaurant')" in db.calls[0][0]


def test_request_retry_is_idempotent_and_response_has_no_contact_details(scenario):
    client, db, _ = scenario
    data = payload()
    for _ in range(2):
        response = client.post(PATH, json=data, headers=HEADERS)
        assert response.status_code == 201 and response.json() == {'ok': True}
    inserts = [p for sql, p in db.calls if sql.startswith('INSERT INTO connection_requests')]
    assert len(inserts) == 1
    assert inserts[0][3] == '996555123456'
    assert 'testclient' not in inserts[0][-1]
    assert len(inserts[0][-1]) == 64
    assert client.post(PATH, json={**data, 'company': 'Другое кафе'}, headers=HEADERS).status_code == 409


@pytest.mark.parametrize('changes', [
    {'consent': False}, {'consent': 'true'}, {'name': ' '}, {'company': 'X'},
    {'phone': 'call-me'}, {'phone': '123'}, {'phone': '9'*16},
    {'plan': 'enterprise'}, {'request_id': 'invalid'}, {'unexpected': 'field'},
])
def test_invalid_request_never_reaches_database(scenario, changes):
    client, db, _ = scenario
    assert client.post(PATH, json=payload(**changes), headers=HEADERS).status_code == 422
    assert not db.calls


def test_origin_and_honeypot_are_checked_before_database(scenario):
    client, db, _ = scenario
    assert client.post(PATH, json=payload()).status_code == 403
    assert client.post(PATH, json=payload(), headers={'Origin': 'https://other.example'}).status_code == 403
    assert client.post(PATH, json=payload(website='spam'), headers=HEADERS).status_code == 422
    assert not db.calls


@pytest.mark.parametrize('peer,phone', [(100,0),(0,3)])
def test_rate_limit_blocks_excess_and_is_serialized(scenario, peer, phone):
    client, db, _ = scenario
    db.peer_total, db.phone_total = peer, phone
    assert client.post(PATH, json=payload(), headers=HEADERS).status_code == 429
    assert sum('pg_advisory_xact_lock' in sql for sql, _ in db.calls) == 2
    assert not db.rows


def test_confirmed_retry_succeeds_even_after_rate_limit(scenario):
    client, db, _ = scenario
    data = payload()
    assert client.post(PATH, json=data, headers=HEADERS).status_code == 201
    db.peer_total = 100
    assert client.post(PATH, json=data, headers=HEADERS).status_code == 201


@pytest.mark.parametrize('role', ['owner', 'branch', 'cashier'])
def test_only_platform_owner_can_read_contacts_or_mark_request(scenario, role):
    client, db, user = scenario
    user['role'] = role
    assert client.get('/api/v1/platform/connection-requests').status_code == 403
    assert client.patch(f'/api/v1/platform/connection-requests/{uuid4()}/contacted', headers=HEADERS).status_code == 403
    assert not db.calls


def test_platform_owner_can_review_and_mark_with_audit(scenario):
    client, db, _ = scenario
    data = payload()
    assert client.post(PATH, json=data, headers=HEADERS).status_code == 201
    assert client.get('/api/v1/platform/connection-requests').status_code == 200
    assert client.patch(f"/api/v1/platform/connection-requests/{data['request_id']}/contacted", headers=HEADERS).status_code == 200
    assert any('INSERT INTO platform_events' in sql for sql, _ in db.calls)
    assert client.patch(f'/api/v1/platform/connection-requests/{uuid4()}/contacted', headers=HEADERS).status_code == 404
