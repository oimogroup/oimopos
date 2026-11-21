from copy import deepcopy

import pytest

from app.workspace import apply_action, default_state, WorkspaceError
from app.ingredient_rules import unit_change_reason

OWNER={'id':1,'role':'owner','login':'owner','display_name':'Owner'}


@pytest.mark.parametrize('source',['stock','recipe','preparation','ledger','document','modifier','sale'])
def test_unit_change_cannot_reinterpret_used_inventory(source):
    state=default_state()
    item={'id':'unit-test','name':'Проверка единицы','unit':'кг','category':'Крупы','averageCost':100}
    state['ingredients'].append(item)
    if source=='stock':state['logisticsState']['branchStocks']['b1'][item['id']]=10
    if source=='recipe':state['recipes'][0]['components'].append({'ingredientId':item['id'],'gross':100,'net':100})
    if source=='preparation':state['preparations']=[{'id':'dough','components':[{'ingredientId':item['id'],'gross':100,'net':100}]}]
    if source=='ledger':state['logisticsState']['stockLedger']=[{'itemId':item['id'],'quantity':0}]
    if source=='document':state['logisticsState']['inventories']=[{'items':[{'itemId':item['id']}]}]
    if source=='modifier':state['modifierSets']=[{'id':'extra','options':[{'sourceId':item['id']}]}]
    if source=='sale':state['sales']=[{'items':[{'id':123,'ingredientAllocations':[{'itemId':item['id']}]}]}]
    before=deepcopy(item)
    with pytest.raises(WorkspaceError) as error:
        apply_action(state,OWNER,'ingredient.upsert',{**item,'unit':'шт'})
    assert error.value.status_code==409 and item==before
    assert unit_change_reason(state,item['id'])


def test_unused_zero_stock_ingredient_may_change_unit_and_products_are_also_guarded():
    state=default_state()
    item={'id':'unused-unit','name':'Не используется','category':'Крупы','unit':'кг','averageCost':0}
    state['ingredients'].append(item)
    apply_action(state,OWNER,'ingredient.upsert',{**item,'unit':'шт'})
    assert item['unit']=='шт'
    product=state['products'][0]
    state['logisticsState']['branchStocks']['b1'][product['id']]=5
    with pytest.raises(WorkspaceError):
        apply_action(state,OWNER,'product.upsert',{**product,'unit':'кг'})
    assert product['unit']=='шт'


def test_loss_edit_recalculates_live_gross_preserving_net_yields_history_and_stock():
    state=default_state();ingredient=state['ingredients'][0]
    ingredient['losses']={'boil':50}
    component={'ingredientId':ingredient['id'],'gross':200,'net':100,'netWeightGrams':100,'method':'boil'}
    untreated={**component,'method':'none','gross':150}
    state['recipes'][0]['components']=[deepcopy(component),untreated]
    state['preparations']=[{'id':'test-pf','yield':100,'components':[deepcopy(component)]}]
    history={'cost':200,'portionWeight':250,'portionWeightSource':'production','ingredientSnapshot':[{'itemId':ingredient['id'],'quantity':2,'unitCost':100}]}
    state['logisticsState']['batches']=[deepcopy(history)]
    previous_stock=deepcopy(state['logisticsState']['branchStocks'])
    output=state['recipes'][0]['yield']
    apply_action(state,OWNER,'ingredient.upsert',{**deepcopy(ingredient),'losses':{'boil':25}})
    for row in [state['recipes'][0]['components'][0],state['preparations'][0]['components'][0]]:
        assert row['gross']==pytest.approx(100/.75)
        assert row['net']==row['netWeightGrams']==100
    assert untreated['gross']==150 and state['recipes'][0]['yield']==output
    assert state['preparations'][0]['yield']==100
    assert state['logisticsState']['batches'][0]==history
    assert state['logisticsState']['branchStocks']==previous_stock


def test_piece_ingredient_loss_uses_piece_quantities_and_preserves_mass():
    state=default_state()
    ingredient={'id':'egg-loss','name':'Яйцо','unit':'шт','pieceWeightGrams':50,'losses':{'fry':50}}
    state['ingredients'].append(ingredient)
    component={'ingredientId':ingredient['id'],'gross':4000,'net':2000,'netWeightGrams':100,'pieceWeightGrams':50,'method':'fry'}
    state['recipes'][0]['components']=[component]
    apply_action(state,OWNER,'ingredient.upsert',{**deepcopy(ingredient),'losses':{'fry':25}})
    assert component['gross']==pytest.approx(2000/.75)
    assert component['net']==2000 and component['netWeightGrams']==100


@pytest.mark.parametrize('original',['Крупы','крупы','КРУПЫ'])
def test_category_rename_updates_case_variants_without_losing_cover(original):
    state=default_state();ingredient=state['ingredients'][0]
    ingredient['category']='крупы'
    state['ingredientCategoryCovers']={'КРУПЫ':{'color':'#123456','image':''}}
    apply_action(state,OWNER,'category.upsert',{'kind':'ingredient','originalName':original,'name':'Зерновые'})
    assert ingredient['category']=='Зерновые'
    assert state['ingredientCategoryCovers']['Зерновые']['color']=='#123456'
    assert 'КРУПЫ' not in state['ingredientCategoryCovers']


@pytest.mark.parametrize('old_losses',[None,{}])
def test_legacy_empty_losses_can_be_edited(old_losses):
    state=default_state();ingredient=state['ingredients'][0]
    ingredient['losses']=old_losses
    component={'ingredientId':ingredient['id'],'gross':100,'net':100,'method':'boil'}
    state['recipes'][0]['components']=[component]
    apply_action(state,OWNER,'ingredient.upsert',{**deepcopy(ingredient),'losses':{'boil':25}})
    assert component['gross']==pytest.approx(100/.75)


@pytest.mark.parametrize('invalid',[-1,100,101,float('nan'),float('inf'),'abc',True,{},[]])
def test_invalid_losses_are_rejected_without_clamping_or_rewriting_composition(invalid):
    state=default_state();ingredient=state['ingredients'][0]
    ingredient['losses']={'boil':25}
    component={'ingredientId':ingredient['id'],'gross':200,'net':150,'method':'boil'}
    state['recipes'][0]['components']=[component]
    before=deepcopy(ingredient)
    with pytest.raises(WorkspaceError) as error:
        apply_action(state,OWNER,'ingredient.upsert',{**deepcopy(ingredient),'losses':{'boil':invalid}})
    assert error.value.status_code==422 and ingredient==before and component['gross']==200


def test_metadata_only_edit_preserves_existing_losses_and_gross():
    state=default_state();ingredient=state['ingredients'][0]
    ingredient['losses']={'boil':25}
    component={'ingredientId':ingredient['id'],'gross':200,'net':150,'method':'boil'}
    state['recipes'][0]['components']=[component]
    payload={**deepcopy(ingredient),'name':'Новое имя'};payload.pop('losses')
    apply_action(state,OWNER,'ingredient.upsert',payload)
    assert ingredient['losses']['boil']==25 and component['gross']==200
