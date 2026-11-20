from copy import deepcopy
from uuid import uuid4

import pytest

from app.composition import CompositionError, catalog_sources, flatten
from app.technical_card_import import prepare_import, preview
from app.technical_card_report import workbook
from app.workspace import WorkspaceError, apply_action, default_state, recipe_requirements, restaurant_availability, visible_state

OWNER = {'id': 1, 'role': 'owner', 'login': 'owner', 'display_name': 'Owner'}
CASHIER = {'id': 2, 'role': 'branch', 'branch_id': 'b1', 'staff_role': 'cashier', 'login': 'cashier',
           'display_name': 'Cashier', 'register_id': 1, 'shift_id': 20, 'plan_code': 'restaurant'}
PRODUCTION = {**CASHIER, 'staff_role': 'branch_manager', 'plan_code': 'canteen'}


def scenario():
    state = default_state()
    for identity, name, unit, cost in [('pf-flour', 'Мука', 'кг', 100), ('pf-water', 'Вода', 'л', 0), ('pf-meat', 'Мясо', 'кг', 500)]:
        state['ingredients'].append({'id': identity, 'name': name, 'unit': unit, 'averageCost': cost})
        state['logisticsState']['branchStocks']['b1'][identity] = 10
        state['logisticsState']['branchCosts']['b1'][identity] = cost
    apply_action(state, OWNER, 'preparation.upsert', {
        'id': 'dough', 'name': 'Тесто', 'station': 'Кухня', 'yield': 1000,
        'components': [{'ingredientId': 'pf-flour', 'gross': 600, 'net': 600}, {'ingredientId': 'pf-water', 'gross': 400, 'net': 400}],
    })
    _, recipe_id = apply_action(state, OWNER, 'recipe.upsert', {
        'name': 'Манты', 'station': 'Кухня', 'price': 200, 'yield': 300,
        'components': [{'preparationId': 'dough', 'gross': 200, 'net': 200}, {'ingredientId': 'pf-meat', 'gross': 100, 'net': 100}],
    })
    recipe = next(row for row in state['recipes'] if str(row['id']) == recipe_id)
    return state, recipe


def test_preparation_is_preserved_and_expands_proportionally_with_duplicate_raw_sources():
    state, recipe = scenario()
    assert recipe['components'][0]['preparationId'] == 'dough'
    assert 'ingredientId' not in recipe['components'][0]
    assert recipe_requirements(recipe, state=state) == pytest.approx({'pf-flour': .12, 'pf-water': .08, 'pf-meat': .1})
    recipe['components'].append({'ingredientId': 'pf-flour', 'gross': 30, 'net': 30})
    assert recipe_requirements(recipe, 2, state) == pytest.approx({'pf-flour': .3, 'pf-water': .16, 'pf-meat': .2})
    assert state['preparations'][0]['cost'] == 60


def test_sale_deducts_raw_ingredients_once_and_refund_keeps_frozen_consumption():
    state, recipe = scenario()
    _, sale_id = apply_action(state, CASHIER, 'sale.create', {'items': [{'id': recipe['id'], 'quantity': 2}], 'paymentMethod': 'cash', 'received': 400})
    sale = state['sales'][0]
    assert sale['items'][0]['unitCost'] == pytest.approx(62)
    assert state['logisticsState']['branchStocks']['b1']['pf-flour'] == pytest.approx(9.76)
    assert 'dough' not in state['logisticsState']['branchStocks']['b1']
    allocations = deepcopy(sale['items'][0]['ingredientAllocations'])
    apply_action(state, OWNER, 'preparation.upsert', {
        **state['preparations'][0], 'components': [{'ingredientId': 'pf-flour', 'gross': 800, 'net': 800}, {'ingredientId': 'pf-water', 'gross': 200, 'net': 200}],
    })
    assert recipe_requirements(recipe, state=state)['pf-flour'] == pytest.approx(.16)
    assert sale['items'][0]['ingredientAllocations'] == allocations
    apply_action(state, {**CASHIER, 'staff_role': 'hall_admin'}, 'sale.refund', {'id': sale_id, 'reason': 'Тест возврата'})
    # Refunding prepared food does not turn it back into raw flour or meat.
    assert state['logisticsState']['branchStocks']['b1']['pf-flour'] == pytest.approx(9.76)
    assert state['logisticsState']['branchStocks']['b1']['pf-meat'] == pytest.approx(9.8)
    assert sale['items'][0]['ingredientAllocations'] == allocations


def test_batch_cost_stock_and_shortage_use_expanded_raw_composition():
    state, recipe = scenario()
    apply_action(state, PRODUCTION, 'batch.create', {'recipeId': recipe['id'], 'weight': .6})
    batch = state['logisticsState']['batches'][0]
    assert batch['cost'] == pytest.approx(124)
    assert state['logisticsState']['branchStocks']['b1']['pf-flour'] == pytest.approx(9.76)
    state['logisticsState']['branchStocks']['b1']['pf-flour'] = .01
    assert restaurant_availability(state, recipe, 'b1') == 0
    before = deepcopy(state['logisticsState']['branchStocks'])
    with pytest.raises(WorkspaceError, match='Недостаточно'):
        apply_action(state, CASHIER, 'sale.create', {'items': [{'id': recipe['id'], 'quantity': 1}], 'paymentMethod': 'cash', 'received': 200})
    assert state['logisticsState']['branchStocks'] == before


def test_nested_preparation_and_cycles_are_checked_before_updating_definition():
    state, recipe = scenario()
    apply_action(state, OWNER, 'preparation.upsert', {'id': 'nested', 'name': 'Тесто вложенное', 'station': 'Кухня', 'yield': 500,
        'components': [{'preparationId': 'dough', 'gross': 500, 'net': 500}]})
    assert recipe_requirements({'components': [{'preparationId': 'nested', 'gross': 100, 'net': 100}]}, state=state) == pytest.approx({'pf-flour': .06, 'pf-water': .04})
    before = deepcopy(state['preparations'])
    with pytest.raises(WorkspaceError, match='Цикл'):
        apply_action(state, OWNER, 'preparation.upsert', {**state['preparations'][0], 'components': [{'preparationId': 'nested', 'gross': 500, 'net': 500}]})
    assert state['preparations'] == before
    with pytest.raises(WorkspaceError, match='Цикл'):
        apply_action(state, OWNER, 'preparation.upsert', {**state['preparations'][0], 'components': [{'preparationId': 'dough', 'gross': 500, 'net': 500}]})


def test_used_preparation_and_its_last_raw_ingredient_cannot_be_deleted():
    state, recipe = scenario()
    with pytest.raises(WorkspaceError, match='используется'):
        apply_action(state, OWNER, 'catalog.delete', {'kind': 'preparation', 'id': 'dough'})
    state['logisticsState']['branchStocks']['b1']['pf-flour'] = 0
    with pytest.raises(WorkspaceError, match='используемый полуфабрикат'):
        apply_action(state, OWNER, 'catalog.delete', {'kind': 'ingredient', 'id': 'pf-flour'})


def test_authorized_snapshot_resolves_preparations_without_exposing_recipe_to_cashier():
    state, recipe = scenario()
    result = visible_state(state, {**OWNER, 'branch_id': 'b1', 'plan_code': 'restaurant'})
    exposed = next(row for row in result['recipes'] if row['id'] == recipe['id'])
    assert {row['ingredientId']: row['gross'] for row in exposed['rawComponents']} == pytest.approx({'pf-flour': 120, 'pf-water': 80, 'pf-meat': 100})
    assert 'rawComponents' not in recipe
    cashier = visible_state(state, CASHIER)
    hidden = next(row for row in cashier['recipes'] if row['id'] == recipe['id'])
    assert 'components' not in hidden and 'rawComponents' not in hidden


def test_export_import_preserves_preparation_reference_and_mass():
    state, recipe = scenario()
    sources = {str(row['id']): row for row in catalog_sources(state)}
    sources['preparation:dough']['averageCost'] = 60
    table = workbook([recipe], [], sources)
    rows = preview(state, table, 'manty.xlsx')['rows']
    assert rows[0]['ingredientId'] == 'preparation:dough'
    imported = prepare_import(state, rows)[0]
    assert imported['components'][0]['preparationId'] == 'dough'
    assert imported['components'][0]['gross'] == 200
    assert imported['yield'] == 300


def test_offline_receipt_uses_preparation_definition_frozen_when_lease_was_issued():
    from app import offline_pos
    state, recipe = scenario()
    terminal = {'id': 1, 'role': 'branch', 'tenant_id': 'test', 'branch_id': 'b1', 'plan_code': 'restaurant'}
    lease = offline_pos.issue(state, terminal, CASHIER, {'id': 20, 'closed_at': None})
    apply_action(state, OWNER, 'preparation.upsert', {**state['preparations'][0],
        'components': [{'ingredientId': 'pf-flour', 'gross': 800, 'net': 800}, {'ingredientId': 'pf-water', 'gross': 200, 'net': 200}]})
    receipt = {'token': lease['token'], 'createdAt': lease['issuedAt'], 'total': 200,
               'payload': {'requestId': str(uuid4()), 'orderType': 'dine-in', 'items': [{'id': recipe['id'], 'quantity': 1}],
                           'payments': [{'method': 'cash', 'amount': 200}], 'received': 200}}
    result = offline_pos.receive(state, terminal, receipt)
    assert result['status'] == 'synced'
    assert state['logisticsState']['branchStocks']['b1']['pf-flour'] == pytest.approx(9.88)
    assert state['preparations'][0]['components'][0]['gross'] == 800
