from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from app import database, main
from app.workspace import default_state


@pytest.mark.parametrize('known_version', [None, 6, 7])
def test_workspace_polling_only_loads_payload_when_version_changed(known_version):
    class Connection:
        def __init__(self):
            self.payload_reads = 0

        def execute(self, sql, params):
            assert params == ('test-tenant',)
            if 'payload' in sql:
                self.payload_reads += 1
                row = {'version': 7, 'updated_at': None, 'payload': default_state()}
            else:
                row = {'version': 7}

            class Result:
                def fetchone(self):
                    return row
            return Result()

    connection = Connection()
    user = {'role': 'owner', 'tenant_id': 'test-tenant'}
    overrides = main.app.dependency_overrides.copy()
    main.app.dependency_overrides[main.current_user] = lambda: user
    main.app.dependency_overrides[main.get_connection] = lambda: connection
    try:
        params = {} if known_version is None else {'since_version': known_version}
        response = TestClient(main.app).get('/api/v1/workspace', params=params)
        assert response.status_code == 200
        assert response.json()['version'] == 7
        if known_version == 7:
            assert response.json() == {'version': 7, 'unchanged': True}
            assert connection.payload_reads == 0
        else:
            assert 'state' in response.json()
            assert connection.payload_reads == 1
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(overrides)


def test_exhausted_pool_returns_retryable_service_unavailable(monkeypatch):
    class ExhaustedPool:
        @contextmanager
        def connection(self, timeout):
            assert timeout == 5
            raise PoolTimeout('could not obtain connection')
            yield

    monkeypatch.setattr(database, 'pool', ExhaustedPool())
    with pytest.raises(HTTPException) as error:
        next(database.get_connection())
    assert error.value.status_code == 503
    assert error.value.headers == {'Retry-After': '5'}
