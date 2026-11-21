"""Lost acknowledgements and stale forms must not duplicate or overwrite saves."""
from contextlib import nullcontext
from copy import deepcopy
import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import catalog_saves, main
from app.schemas import WorkspaceActionInput
from app.workspace import default_state, visible_state

OWNER = {'id': 1, 'tenant_id': 'catalog-test', 'role': 'owner', 'login': 'owner', 'display_name': 'Owner'}
REQUEST = Request({'type': 'http', 'path': '/api/v1/workspace/actions', 'method': 'POST', 'headers': []})


class Database:
    def __init__(self):
        self.state = default_state()
        self.version = 1
        self.events = []
        self.writes = []

    def transaction(self):
        return nullcontext()

    def execute(self, query, params):
        self.writes.append((query, params))
        if query.lstrip().startswith('SELECT action, entity_type'):
            rows = [row for row in self.events if row['actor'] == params[1] and row['payload'].get('_catalogSave', {}).get('requestId') == params[3]]
            return type('Result', (), {'fetchone': lambda _: rows[-1] if rows else None})()
        if 'INSERT INTO operational_events' in query:
            self.events.append({'actor': params[2], 'action': params[6], 'entity_type': params[7], 'entity_id': params[8], 'payload': params[9].obj})
            self.version = params[1]


@pytest.fixture
def database(monkeypatch):
    database = Database()
    monkeypatch.setattr(main, '_workspace_row', lambda *args, **kw: {'payload': database.state, 'version': database.version})
    monkeypatch.setattr(main, '_check_origin', lambda *args: None)
    return database


def command(database, **kwargs):
    recipe = deepcopy(database.state['recipes'][0])
    recipe.update(name='Обновлённый плов', station='Кухня')
    return WorkspaceActionInput(action='recipe.upsert', payload=recipe,
        expected_revision=catalog_saves.revision(database.state, 'recipe.upsert', recipe['id']), **kwargs)


def test_retry_after_lost_acknowledgement_does_not_apply_twice(database):
    edit = command(database, request_id='same-request-123456789')
    first = main.workspace_action(edit, REQUEST, OWNER, None, database, True)
    saved = deepcopy(database.state)
    second = main.workspace_action(edit, REQUEST, OWNER, None, database, True)
    assert second['replayed'] and second['entity'] == first['entity']
    assert database.state == saved and database.version == 2
    assert len(database.events) == 1
    status = main.catalog_operation_status(edit.request_id, OWNER, database)
    assert status['confirmed'] and status['entity'] == first['entity']
    assert not main.catalog_operation_status('unknown-operation-123456', OWNER, database)['confirmed']


def test_reusing_request_id_with_other_content_is_rejected(database):
    edit = command(database, request_id='same-request-123456789')
    main.workspace_action(edit, REQUEST, OWNER, None, database, True)
    edit.payload['name'] = 'Другие данные'
    with pytest.raises(HTTPException) as error:
        main.workspace_action(edit, REQUEST, OWNER, None, database, True)
    assert error.value.status_code == 409 and len(database.events) == 1


def test_stale_form_cannot_overwrite_another_tab_but_unrelated_sales_are_allowed(database):
    edit = command(database)
    database.state['sales'].append({'id': 'unrelated'})
    catalog_saves.check_revision(database.state, edit)
    database.state['recipes'][0]['name'] = 'Сохранено в другой вкладке'
    before = deepcopy(database.state)
    with pytest.raises(HTTPException) as error:
        main.workspace_action(edit, REQUEST, OWNER, None, database, True)
    assert error.value.status_code == 409 and database.state == before and not database.events


def test_group_revision_includes_children_and_modifier_definitions():
    state = default_state()
    root = state['recipes'][0]
    child = {**deepcopy(root), 'id': 9999, 'parentId': root['id']}
    state['recipes'].append(child)
    root['modifierSetIds'] = ['sauce']
    state['modifierSets'] = [{'id': 'sauce', 'name': 'Соус'}]
    old = catalog_saves.revision(state, 'recipe.group.upsert', root['id'])
    child['price'] += 1
    changed = catalog_saves.revision(state, 'recipe.group.upsert', root['id'])
    assert old != changed
    state['modifierSets'][0]['name'] = 'Новый соус'
    assert changed != catalog_saves.revision(state, 'recipe.upsert', root['id'])


def test_database_delta_and_audit_do_not_resend_unchanged_photos(database):
    photo = 'data:image/jpeg;base64,' + 'a' * 200000
    before = deepcopy(database.state)
    before['recipes'][0]['image'] = photo
    after = deepcopy(before)
    after['recipes'][0]['name'] = 'Новое название'
    after['recipes'].append({'id': 9999, 'name': 'Новое блюдо'})
    catalog_saves.update(database, 'tenant', 2, before, after)
    query, params = database.writes[-1]
    assert 'jsonb_set' in query
    values = [getattr(value, 'obj', value) for value in params]
    assert photo not in json.dumps(values) and len(json.dumps(values)) < 1000
    audit = catalog_saves.audit_payload({'image': photo, 'variants': [{'image': photo}], '_catalogSave': {'forged': True}})
    assert photo not in json.dumps(audit) and '_catalogSave' not in audit


def test_preparation_revisions_are_exposed_only_to_catalog_owners(database):
    state = database.state
    state['preparations'] = [{'id': 'dough', 'name': 'Тесто', 'components': [], 'yield': 1000}]
    output = visible_state(state, OWNER)
    assert output['recipes'][0]['editRevision'] == catalog_saves.revision(state, 'recipe.upsert', state['recipes'][0]['id'])
    assert output['preparations'][0]['editRevision']
    assert 'editRevision' not in state['recipes'][0]


@pytest.mark.parametrize('action,collection', [('ingredient.upsert','ingredients'),('product.upsert','products'),('supplier.upsert','suppliers')])
def test_other_catalogs_reject_stale_edits_and_new_id_collisions(database,action,collection):
    row=database.state[collection][0]
    payload={**deepcopy(row),'name':'Старая вкладка'}
    edit=WorkspaceActionInput(action=action,payload=payload,expected_revision=catalog_saves.revision(database.state,action,row['id']))
    row['name']='Сохранено другим пользователем'
    with pytest.raises(HTTPException) as error:
        main.workspace_action(edit,REQUEST,OWNER,None,database,True)
    assert error.value.status_code==409 and not database.events
    edit.expected_revision='new'
    with pytest.raises(HTTPException) as error:
        catalog_saves.check_revision(database.state,edit)
    assert error.value.status_code==409


def test_category_revisions_are_per_category_and_follow_cover_changes(database):
    payload={'kind':'ingredient','originalName':'Крупы','name':'Новая категория'}
    revision=catalog_saves.revision(database.state,'category.upsert','Крупы',kind='ingredient')
    command=WorkspaceActionInput(action='category.upsert',payload=payload,expected_revision=revision)
    database.state['ingredientCategories'].append('Другая категория')
    catalog_saves.check_revision(database.state,command)
    database.state['ingredientCategoryCovers']={'Крупы':{'color':'#123456'}}
    with pytest.raises(HTTPException) as error:
        main.workspace_action(command,REQUEST,OWNER,None,database,True)
    assert error.value.status_code==409


@pytest.mark.parametrize('action,collection', [('ingredient.upsert','ingredients'),('product.upsert','products'),('supplier.upsert','suppliers')])
def test_other_catalogs_replay_after_lost_response(database,action,collection):
    row=database.state[collection][0]
    payload={**deepcopy(row),'name':'Новое имя'}
    command=WorkspaceActionInput(action=action,payload=payload,expected_revision=catalog_saves.revision(database.state,action,row['id']),request_id='catalog-expanded-12345678')
    first=main.workspace_action(command,REQUEST,OWNER,None,database,True)
    second=main.workspace_action(command,REQUEST,OWNER,None,database,True)
    assert second['replayed'] and second['entity']==first['entity'] and len(database.events)==1
