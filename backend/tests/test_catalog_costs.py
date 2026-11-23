from copy import deepcopy
from fastapi.testclient import TestClient
import pytest
from app.catalog_costs import unit_cost
from app import main, technical_card_report


def state():
    return {'branches':[{'id':'b1','status':'active'},{'id':'b2','status':'active'},{'id':'closed','status':'inactive'}],
            'ingredients':[{'id':'horse','name':'Horse','unit':'кг','averageCost':0}], 'products':[],
            'recipes':[{'id':1,'name':'Dish','components':[{'ingredientId':'horse','gross':180,'net':180}]}], 'preparations':[],
            'logisticsState':{'branchStocks':{'b1':{'horse':11},'b2':{'horse':1},'closed':{'horse':100}},'branchCosts':{'b1':{'horse':650},'b2':{'horse':900},'closed':{'horse':50}}}}


def test_warehouse_cost_overrides_stale_catalog_and_weights_network_by_stock():
    data=state();before=deepcopy(data)
    assert unit_cost(data,'horse','b1')==650
    assert unit_cost(data,'horse')==pytest.approx((11*650+900)/12)
    assert data==before


def test_empty_stock_retains_known_prices_and_negative_stock_does_not_distort_average():
    data=state();data['logisticsState']['branchStocks']={'b1':{'horse':-5},'b2':{'horse':0}}
    assert unit_cost(data,'horse')==775
    data['logisticsState']['branchStocks']['b2']['horse']=1
    assert unit_cost(data,'horse')==900
    data['logisticsState']['branchCosts']={};data['ingredients'][0]['averageCost']=100
    assert unit_cost(data,'horse')==100


def test_zero_branch_cost_is_not_replaced_by_old_catalog_price():
    data=state();data['ingredients'][0]['averageCost']=100
    data['logisticsState']['branchCosts']['b1']['horse']=0
    assert unit_cost(data,'horse','b1')==0


def test_export_uses_current_warehouse_price_without_rewriting_catalog(monkeypatch):
    data=state();captured={};before=deepcopy(data)
    def workbook(recipes,preparations,ingredients):captured.update(ingredients);return 'xlsx'
    monkeypatch.setattr(technical_card_report,'workbook',workbook)
    monkeypatch.setattr(main,'_workspace_row',lambda *args,**kwargs:{'payload':data})
    overrides=main.app.dependency_overrides.copy()
    main.app.dependency_overrides[main.current_user]=lambda:{'role':'branch','tenant_id':'t','branch_id':'b1','access_permissions':{'menu':True}}
    main.app.dependency_overrides[main.get_connection]=lambda:object()
    try:
        response=TestClient(main.app).get('/api/v1/technical-cards/export')
        assert response.status_code==200
        assert captured['horse']['averageCost']==650
        assert captured['horse']['averageCost']*.18==117
        assert data==before
    finally:
        main.app.dependency_overrides.clear();main.app.dependency_overrides.update(overrides)
