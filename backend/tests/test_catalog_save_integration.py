"""Real PostgreSQL races, opt-in and confined to a fresh isolated schema."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest
from fastapi import HTTPException

from app import catalog_saves, main
from app.schemas import WorkspaceActionInput
from app.workspace import default_state
from test_catalog_save_reliability import OWNER, REQUEST

DSN = os.environ.get('CATALOG_TEST_DATABASE_URL', '')
pytestmark = pytest.mark.skipif(not DSN, reason='isolated catalog PostgreSQL required')


@pytest.fixture
def database(monkeypatch):
    schema = 'catalog_save_test_' + uuid4().hex
    def connect():
        connection = psycopg.connect(DSN, row_factory=dict_row)
        connection.execute(f'SET search_path TO {schema}')
        connection.execute("SET lock_timeout = '5s'")
        return connection
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA {schema}')
    state = default_state()
    state['recipes'][1]['image'] = 'data:image/jpeg;base64,' + 'a' * 200000
    try:
        with connect() as connection:
            connection.execute('CREATE TABLE operational_state (tenant_id text PRIMARY KEY, version int, payload jsonb, updated_at timestamptz)')
            connection.execute('CREATE TABLE operational_events (tenant_id text,state_version int,actor_user_id int,actor_login text,actor_role text,branch_id text,action text,entity_type text,entity_id text,payload jsonb)')
            connection.execute('INSERT INTO operational_state VALUES (%s,1,%s,now())', (OWNER['tenant_id'], Jsonb(state)))
        monkeypatch.setattr(main, '_check_origin', lambda *args: None)
        yield connect, state
    finally:
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA {schema} CASCADE')


def edit(state, name, request_id=None):
    payload = deepcopy(state['recipes'][0])
    payload.update(name=name, station='Кухня')
    return WorkspaceActionInput(action='recipe.upsert', payload=payload,
        expected_revision=catalog_saves.revision(state, 'recipe.upsert', payload['id']), request_id=request_id)


def run(connect, command):
    try:
        with connect() as connection:
            return 200, main.workspace_action(command, REQUEST, OWNER, None, connection, True)
    except HTTPException as error:
        return error.status_code, error.detail


def test_two_tabs_cannot_overwrite_each_other(database):
    connect, state = database
    commands = [edit(state, 'Первое окно'), edit(state, 'Второе окно')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda command: run(connect, command), commands))
    assert sorted(status for status, _ in results) == [200, 409]
    with connect() as connection:
        row = main._workspace_row(connection, OWNER['tenant_id'])
        assert row['version'] == 2
        assert row['payload']['recipes'][1]['image'] == state['recipes'][1]['image']
        assert connection.execute('SELECT count(*) AS count FROM operational_events').fetchone()['count'] == 1


def test_simultaneous_retries_commit_exactly_once(database):
    connect, state = database
    command = edit(state, 'Одна операция', str(uuid4()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(connect, command), range(2)))
    assert [status for status, _ in results] == [200, 200]
    assert results[0][1]['entity'] == results[1][1]['entity']
    assert sum(bool(result.get('replayed')) for _, result in results) == 1
    with connect() as connection:
        assert main._workspace_row(connection, OWNER['tenant_id'])['version'] == 2
        assert connection.execute('SELECT count(*) AS count FROM operational_events').fetchone()['count'] == 1
        assert main.catalog_operation_status(command.request_id, OWNER, connection)['confirmed']


def test_delta_sql_handles_nested_removals_nulls_and_append(database):
    connect, before = database
    after = deepcopy(before)
    del after['recipes'][0]['category']
    after['recipes'][0]['portionSize'] = None
    after['recipes'].append({'id': 9999, 'name': 'Новая карточка'})
    with connect() as connection:
        catalog_saves.update(connection, OWNER['tenant_id'], 2, before, after)
    with connect() as connection:
        assert main._workspace_row(connection, OWNER['tenant_id'])['payload'] == after


def test_manufacture_and_writeoff_retries_move_stock_once(database):
    from test_preparation_components import scenario
    connect, _ = database
    state, _ = scenario()
    with connect() as connection:
        connection.execute('UPDATE operational_state SET payload=%s WHERE tenant_id=%s', (Jsonb(state), OWNER['tenant_id']))
    produce = WorkspaceActionInput(action='preparation.produce', payload={
        'preparationId': 'dough', 'branchId': 'b1', 'weight': 1, 'requestId': str(uuid4())})
    writeoff = WorkspaceActionInput(action='stock.writeoff', payload={
        'itemId': 'preparation:dough', 'branchId': 'b1', 'quantity': .25, 'reason': 'Порча', 'requestId': str(uuid4())})
    for command in [produce, writeoff]:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(connect, command), range(2)))
        assert [status for status, _ in results] == [200, 200]
        assert results[0][1]['entity'] == results[1][1]['entity']
    with connect() as connection:
        row = main._workspace_row(connection, OWNER['tenant_id'])
        stocks = row['payload']['logisticsState']['branchStocks']['b1']
        assert stocks['preparation:dough'] == .75 and stocks['pf-flour'] == 9.4
        assert row['version'] == 3
        assert connection.execute('SELECT count(*) AS count FROM operational_events').fetchone()['count'] == 2


@pytest.mark.parametrize('action,collection',[('ingredient.upsert','ingredients'),('product.upsert','products'),('supplier.upsert','suppliers'),('category.upsert',None)])
def test_all_catalog_forms_serialize_competing_revisions(database,action,collection):
    connect,state=database
    if collection:
        row=state[collection][0]
        payload={**deepcopy(row),'name':'Первое окно'}
        expected=catalog_saves.revision(state,action,row['id'])
    else:
        payload={'kind':'ingredient','originalName':'Крупы','name':'Первое окно'}
        expected=catalog_saves.revision(state,action,'Крупы',kind='ingredient')
    commands=[WorkspaceActionInput(action=action,payload={**payload,'name':name},expected_revision=expected,request_id=str(uuid4())) for name in ['Первое окно','Второе окно']]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda command:run(connect,command),commands))
    assert sorted(status for status,_ in results)==[200,409]
    with connect() as connection:
        assert main._workspace_row(connection,OWNER['tenant_id'])['version']==2
        assert connection.execute('SELECT count(*) AS count FROM operational_events').fetchone()['count']==1


def test_category_acknowledgement_replays_after_rename(database):
    connect,state=database
    command=WorkspaceActionInput(action='category.upsert',payload={'kind':'ingredient','originalName':'Крупы','name':'Зерновые'},
        expected_revision=catalog_saves.revision(state,'category.upsert','Крупы',kind='ingredient'),request_id=str(uuid4()))
    first=run(connect,command);second=run(connect,command)
    assert first[0]==second[0]==200 and second[1]['replayed']
    assert first[1]['entity']==second[1]['entity']
