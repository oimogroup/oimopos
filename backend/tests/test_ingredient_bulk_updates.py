from copy import deepcopy
import pytest
from app.workspace import apply_action, default_state, WorkspaceError

OWNER = {'id':1, 'role':'owner', 'display_name':'Owner'}


def test_bulk_update_preserves_ids_stock_cost_and_losses():
    state = default_state()
    item = state['ingredients'][0]
    before_stock = deepcopy(state['logisticsState']['branchStocks'])
    apply_action(state, OWNER, 'ingredient.import', {'updateExisting':True, 'items':[
        {'name':item['name'], 'unit':item['unit'], 'averageCost':123, 'losses':{'boil':15}},
        {'name':'Bulk new', 'unit':'кг', 'averageCost':99}]})
    updated = next(i for i in state['ingredients'] if i['id']==item['id'])
    assert updated['averageCost']==123 and updated['losses']['boil']==15
    for branch, stocks in before_stock.items():
        for key, value in stocks.items():
            assert state['logisticsState']['branchStocks'][branch][key] == value


def test_bulk_update_is_atomic_on_invalid_last_row():
    state = default_state()
    before = deepcopy(state)
    item = state['ingredients'][0]
    with pytest.raises(WorkspaceError):
        apply_action(state, OWNER, 'ingredient.import', {'updateExisting':True, 'items':[
            {'name':item['name'], 'unit':item['unit'], 'averageCost':123},
            {'name':'Invalid', 'unit':'кг', 'averageCost':float('inf')}]})
    assert state['ingredients'] == before['ingredients']
    assert state['logisticsState'] == before['logisticsState']


def test_bulk_update_rejects_unit_changes():
    state = default_state()
    item = state['ingredients'][0]
    with pytest.raises(WorkspaceError):
        apply_action(state, OWNER, 'ingredient.import', {'updateExisting':True, 'items':[
            {'name':item['name'], 'unit':'шт' if item['unit']!='шт' else 'кг'}]})
