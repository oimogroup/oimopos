from copy import deepcopy
import pytest
from app.workspace import apply_action, default_state, WorkspaceError
from app.technical_card_import import prepare_import, preview
from app.technical_card_report import workbook

OWNER={'id':1,'role':'owner','display_name':'Test'}


def test_piece_weight_and_net_mass_persist_without_changing_stock_or_cost():
    state=default_state()
    apply_action(state,OWNER,'ingredient.upsert',{'id':'eggs-test','name':'Eggs','unit':'шт','averageCost':10,'pieceWeightGrams':55})
    stock=deepcopy(state['logisticsState']['branchStocks'])
    component={'ingredientId':'eggs-test','gross':2000,'net':2000,'netWeightGrams':110}
    _,id=apply_action(state,OWNER,'preparation.upsert',{'name':'Egg prep','station':'Kitchen','yield':110,'components':[component]})
    prep=next(i for i in state['preparations'] if i['id']==id)
    assert prep['cost']==20
    assert prep['components'][0]['netWeightGrams']==110
    assert state['logisticsState']['branchStocks']==stock
    catalog={i['id']:i for i in state['ingredients']}
    imported=preview(state,workbook([], [prep],catalog),'prep.xlsx')
    assert imported['rows'][0]['unit']=='шт'
    assert imported['rows'][0]['gross']==2
    assert prepare_import(state,imported['rows'])[0]['components'][0]['netWeightGrams']==110


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf')])
def test_invalid_piece_weight_rejected(value):
    with pytest.raises(WorkspaceError):
        apply_action(default_state(),OWNER,'ingredient.upsert',{'name':'Egg','unit':'шт','pieceWeightGrams':value})
