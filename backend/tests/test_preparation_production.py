"""Prepared stock replaces raw consumption only after explicit manufacture."""
from copy import deepcopy

import pytest

from app.workspace import apply_action, recipe_requirements, WorkspaceError, visible_state
from app.inventory_report import build_report
from test_preparation_components import scenario, OWNER, CASHIER, PRODUCTION


def produce(state, weight=1, **extra):
    return apply_action(state, OWNER, 'preparation.produce', {'preparationId': 'dough', 'branchId': 'b1', 'weight': weight, **extra})


def test_manufacture_then_sale_uses_dough_once_at_frozen_weighted_cost():
    state, recipe = scenario()
    produce(state, 2, requestId='prepare-dough')
    stocks = state['logisticsState']['branchStocks']['b1']
    assert stocks['pf-flour'] == pytest.approx(8.8)
    assert stocks['pf-water'] == pytest.approx(9.2)
    assert stocks['preparation:dough'] == 2
    assert recipe_requirements(recipe, state=state) == pytest.approx({'preparation:dough': .2, 'pf-meat': .1})
    # Editing today's formula must not recost yesterday's ready-made stock.
    apply_action(state, OWNER, 'preparation.upsert', {**state['preparations'][0], 'components': [
        {'ingredientId': 'pf-flour', 'gross': 800, 'net': 800}, {'ingredientId': 'pf-water', 'gross': 200, 'net': 200}]})
    apply_action(state, CASHIER, 'sale.create', {'items': [{'id': recipe['id'], 'quantity': 2}], 'paymentMethod': 'cash', 'received': 400})
    assert stocks['preparation:dough'] == pytest.approx(1.6)
    assert stocks['pf-flour'] == pytest.approx(8.8)
    assert state['sales'][0]['items'][0]['unitCost'] == pytest.approx(62)
    assert state['sales'][0]['items'][0]['ingredientAllocations'][0]['name'] == 'Тесто [п/ф]'
    produce(state, 1)
    assert state['logisticsState']['branchCosts']['b1']['preparation:dough'] == pytest.approx((1.6*60+80)/2.6)


def test_manufacture_retry_shortage_and_inventory_lock_are_atomic():
    state, recipe = scenario()
    produce(state, requestId='same-production')
    before = deepcopy(state)
    assert produce(state, requestId='same-production')[1] == state['logisticsState']['preparationProductions'][0]['id']
    assert state == before
    with pytest.raises(WorkspaceError):
        produce(state, 100)
    assert state == before
    apply_action(state, OWNER, 'inventory.start', {'branchId': 'b1', 'scope': 'selected', 'itemIds': ['preparation:dough']})
    with pytest.raises(WorkspaceError, match='инвентаризация'):
        produce(state)


def test_manufactured_dough_participates_in_inventory_and_cannot_be_deleted_with_stock():
    state, _ = scenario()
    produce(state)
    _, key = apply_action(state, OWNER, 'inventory.start', {'branchId': 'b1', 'scope': 'selected', 'itemIds': ['preparation:dough']})
    inventory = next(row for row in state['logisticsState']['inventories'] if row['id'] == key)
    assert len(inventory['items']) == 1 and inventory['items'][0]['book'] == 1
    apply_action(state, OWNER, 'inventory.submit', {'id': key, 'items': [{'itemId': 'preparation:dough', 'actual': .7}]})
    apply_action(state, OWNER, 'inventory.post', {'id': key})
    assert state['logisticsState']['branchStocks']['b1']['preparation:dough'] == pytest.approx(.7)
    with pytest.raises(WorkspaceError):
        apply_action(state, OWNER, 'catalog.delete', {'kind': 'preparation', 'id': 'dough'})


def test_no_silent_raw_fallback_when_prepared_stock_runs_out():
    state, recipe = scenario()
    produce(state, .1)
    before = deepcopy(state)
    with pytest.raises(WorkspaceError):
        apply_action(state, CASHIER, 'sale.create', {'items': [{'id': recipe['id'], 'quantity': 1}], 'paymentMethod': 'cash', 'received': 200})
    assert state == before


def test_preparation_production_history_is_branch_and_role_scoped():
    state, _ = scenario()
    produce(state)
    state['logisticsState']['preparationProductions'].append({'id': 'other', 'branchId': 'b2', 'preparationId': 'dough'})
    assert visible_state(state, CASHIER)['logisticsState']['preparationProductions'] == []
    view = visible_state(state, {**PRODUCTION, 'staff_role': 'branch_manager'})
    assert [row['branchId'] for row in view['logisticsState']['preparationProductions']] == ['b1']
    keeper = visible_state(state, {**PRODUCTION, 'staff_role': 'storekeeper'})
    assert keeper['preparations'] == [] and keeper['producedStockItems'][0]['id'] == 'preparation:dough'
    assert 'components' not in keeper['producedStockItems'][0]


def test_writeoff_is_server_side_idempotent_and_affects_profit_once():
    from app import pnl
    from app.workspace import _now
    state, _ = scenario()
    produce(state)
    day = pnl.local_day(state, _now()).isoformat()
    before = pnl.report(state, day, day)['expenses']
    payload = {'branchId': 'b1', 'itemId': 'preparation:dough', 'quantity': .25, 'reason': 'Порча', 'requestId': 'writeoff-dough'}
    first = apply_action(state, OWNER, 'stock.writeoff', payload)
    assert apply_action(state, OWNER, 'stock.writeoff', payload) == first
    assert state['logisticsState']['branchStocks']['b1']['preparation:dough'] == .75
    assert len(state['logisticsState']['writeoffs']) == 1
    assert pnl.report(state, day, day)['expenses'] - before == pytest.approx(15)
    before_state = deepcopy(state)
    with pytest.raises(WorkspaceError):
        apply_action(state, OWNER, 'stock.writeoff', {**payload, 'quantity': .5})
    assert state == before_state


def test_manufactured_preparation_can_transfer_without_consuming_raw_again():
    state, _ = scenario()
    produce(state, 2)
    # Existing warehouse transfer lifecycle must accept the same stock identity.
    receiver = {**PRODUCTION, 'branch_id': 'b2'}
    _, key = apply_action(state, receiver, 'transfer.create', {'sourceBranchId': 'b1',
        'items': [{'itemId': 'preparation:dough', 'requested': .5}]})
    apply_action(state, OWNER, 'transfer.approve', {'id': key})
    apply_action(state, PRODUCTION, 'transfer.dispatch', {'id': key})
    apply_action(state, receiver, 'transfer.receive', {'id': key, 'items': [{'itemId': 'preparation:dough', 'received': .5}]})
    assert state['logisticsState']['branchStocks']['b1']['preparation:dough'] == 1.5
    assert state['logisticsState']['branchStocks']['b2']['preparation:dough'] == .5
    assert state['logisticsState']['branchCosts']['b2']['preparation:dough'] == 60
    assert state['logisticsState']['branchStocks']['b1']['pf-flour'] == pytest.approx(8.8)


def test_kitchen_shift_counts_include_manufactured_preparations():
    from app.production_shifts import ingredient_stocks
    state, _ = scenario()
    produce(state, 2)
    rows = ingredient_stocks(state, 'b1')
    dough = next(row for row in rows if row['id'] == 'preparation:dough')
    assert dough['quantity'] == 2 and dough['unit'] == 'кг'
