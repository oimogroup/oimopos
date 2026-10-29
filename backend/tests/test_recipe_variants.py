from copy import deepcopy
import pytest
from app.workspace import apply_action, default_state, visible_state, WorkspaceError

OWNER = {'id': 1, 'role': 'owner', 'login': 'admin', 'display_name': 'Admin'}
CASHIER = {'id': 2, 'role': 'branch', 'branch_id': 'b1', 'staff_role': 'cashier', 'login': 'cashier', 'display_name': 'Cashier', 'register_id': 1, 'shift_id': 1, 'plan_code': 'restaurant'}


def group(state):
    ingredient = state['ingredients'][0]['id']
    payload = {'name': 'Лимонад', 'category': 'Напитки', 'station': state['stations'][0]['name'], 'variants': [
        {'name': '250 мл', 'portionSize': 250, 'portionUnit': 'мл', 'price': 50, 'yield': 250, 'components': [{'ingredientId': ingredient, 'gross': 100, 'net': 90}]},
        {'name': '500 мл', 'portionSize': 500, 'portionUnit': 'мл', 'price': 80, 'yield': 500, 'components': [{'ingredientId': ingredient, 'gross': 200, 'net': 180}]},
    ]}
    _, root = apply_action(state, OWNER, 'recipe.group.upsert', payload)
    variants = [r for r in state['recipes'] if str(r['id']) == root or str(r.get('parentId')) == root]
    return payload, variants


def test_recipe_variants_keep_separate_compositions_and_sale_consumption():
    state = default_state()
    state['serviceMode'] = 'restaurant'
    payload, variants = group(state)
    small, large = variants
    assert small['portionSize'] == 250 and large['parentId'] == small['id']
    ingredient = large['components'][0]['ingredientId']
    state['logisticsState']['branchStocks']['b1'][ingredient] = 10
    _, sale_id = apply_action(state, CASHIER, 'sale.create', {'paymentMethod': 'card', 'items': [{'id': large['id'], 'quantity': 2}]})
    assert state['logisticsState']['branchStocks']['b1'][ingredient] == pytest.approx(9.6)
    assert next(s for s in state['sales'] if s['id'] == sale_id)['total'] == 160
    visible = visible_state(state, CASHIER)
    exposed = next(r for r in visible['recipes'] if r['id'] == large['id'])
    assert exposed['variantName'] == '500 мл' and exposed['portionUnit'] == 'мл'
    assert exposed['parentId'] == small['id']
    assert 'components' not in exposed


def test_group_update_is_atomic_and_preserves_ids_and_history():
    state = default_state()
    payload, variants = group(state)
    payload['id'] = variants[0]['id']
    payload['variants'] = [{**row, 'id': item['id']} for row, item in zip(payload['variants'], variants)]
    before = deepcopy(state)
    payload['variants'][1]['components'][0]['ingredientId'] = 'missing'
    with pytest.raises(WorkspaceError):
        apply_action(state, OWNER, 'recipe.group.upsert', payload)
    assert state == before
    payload['variants'][1]['components'][0]['ingredientId'] = variants[0]['components'][0]['ingredientId']
    payload['variants'][1]['price'] = 90
    apply_action(state, OWNER, 'recipe.group.upsert', payload)
    saved = [r for r in state['recipes'] if r.get('groupName') == 'Лимонад']
    assert [r['id'] for r in saved] == [r['id'] for r in variants]
    assert saved[1]['price'] == 90
    payload['variants'].pop()
    before = deepcopy(state)
    with pytest.raises(WorkspaceError):
        apply_action(state, OWNER, 'recipe.group.upsert', payload)
    assert state == before
    state['logisticsState']['batches'].append({'recipeId': saved[1]['id'], 'portionWeight': 500, 'portionWeightSource': 'legacy_recipe'})
    before = deepcopy(state)
    with pytest.raises(WorkspaceError):
        apply_action(state, OWNER, 'catalog.delete', {'kind': 'recipe', 'id': saved[0]['id']})
    assert state == before


@pytest.mark.parametrize('size,unit', [(0, 'мл'), (-1, 'г'), (float('nan'), 'мл'), (100, 'л'), (True, 'шт')])
def test_invalid_portion_is_rejected_atomically(size, unit):
    state = default_state()
    payload, variants = group(state)
    payload['id'] = variants[0]['id']
    payload['variants'] = [{**row, 'id': item['id']} for row, item in zip(payload['variants'], variants)]
    payload['variants'][1].update(portionSize=size, portionUnit=unit)
    before = deepcopy(state)
    with pytest.raises(WorkspaceError):
        apply_action(state, OWNER, 'recipe.group.upsert', payload)
    assert state == before
