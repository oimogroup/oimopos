from contextlib import nullcontext
from copy import deepcopy
import json

from starlette.requests import Request

from app import main
from app.schemas import WorkspaceActionInput
from app.workspace import default_state, visible_state
from app.workspace_patch import state_patch


def restore(before, patch):
    state = {**before, **patch['replace']}
    for key in patch['remove']:
        del state[key]
    for key, updates in patch['collections'].items():
        rows = {str(row['id']): row for row in before[key]}
        rows.update({str(row['id']): row for row in updates['upsert']})
        state[key] = [rows[identifier] for identifier in updates['order']]
    return state


def test_catalog_patch_preserves_photos_removals_order_and_other_state_changes():
    photo = 'data:image/jpeg;base64,' + 'a' * 200_000
    before = {'recipes': [{'id': 1, 'name': 'Old', 'image': photo}, {'id': 2}, {'id': 3}],
              'modifierSets': [], 'logisticsState': {'batches': []}, 'obsolete': True}
    after = deepcopy(before)
    after['recipes'] = [after['recipes'][2], after['recipes'][0], {'id': 4}]
    after['modifierSets'] = [{'id': 'extra', 'name': 'Sauce'}]
    after['logisticsState']['batches'].append({'id': 'batch'})
    del after['obsolete']
    patch = state_patch(before, after)
    assert restore(before, patch) == after
    assert photo not in json.dumps(patch)
    assert len(json.dumps(patch)) < 1000


def test_compact_recipe_save_returns_patch_matching_full_visible_state(monkeypatch):
    state = default_state()
    photo = 'data:image/jpeg;base64,' + 'a' * 200_000
    state['recipes'][0]['image'] = photo
    recipe = deepcopy(state['recipes'][1])
    recipe['name'] = 'Updated recipe'
    recipe['station'] = 'Кухня'
    user = {'id': 1, 'role': 'owner', 'login': 'owner', 'display_name': 'Owner', 'tenant_id': 'test'}
    before = visible_state(state, user)
    row = {'version': 7, 'payload': state}

    class Connection:
        def transaction(self):
            return nullcontext()

        def execute(self, *args):
            return None

    reads = []
    def workspace_row(*args, **kwargs):
        reads.append(True)
        return row

    monkeypatch.setattr(main, '_workspace_row', workspace_row)
    monkeypatch.setattr(main, '_check_origin', lambda request: None)
    request = Request({'type': 'http', 'method': 'POST', 'path': '/api/v1/workspace/actions', 'headers': []})
    response = main.workspace_action(WorkspaceActionInput(action='recipe.upsert', payload=recipe), request,
                                     user, None, Connection(), compact_catalog=True)
    assert response['baseVersion'] == 7
    assert response['version'] == 8
    assert 'state' not in response
    assert len(reads) == 1
    assert restore(before, response['statePatch']) == visible_state(state, user)
    assert photo not in json.dumps(response)
    assert len(json.dumps(response)) < len(json.dumps(visible_state(state, user))) / 10
    assert response['statePatch']['collections']['recipes']['upsert'][0]['name'] == recipe['name']
