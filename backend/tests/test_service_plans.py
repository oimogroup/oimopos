from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from contextlib import nullcontext

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request
from app import main
from app.schemas import PlanPriceUpdate
from app.workspace import apply_action, default_state, visible_state, WorkspaceError, recipe_requirements

USER = {'id':2,'login':'cashier','display_name':'Cashier','role':'branch','branch_id':'b1','staff_role':'branch_manager','register_id':3,'shift_id':4,'plan_code':'restaurant'}


def scenario():
    state=default_state()
    recipe=state['recipes'][0]
    recipe['components']=[{'ingredientId': 'i1', 'gross': 250, 'net':200}, {'ingredientId':'i1','gross':50,'net':40}]
    state['logisticsState']['branchStocks']['b1']['i1']=3
    state['logisticsState']['batches']=[]
    return state,recipe


def test_restaurant_sells_without_batches_and_aggregates_ingredients():
    state,recipe=scenario()
    assert recipe_requirements(recipe)=={'i1':.3}
    visible=visible_state(state,USER)
    assert visible['serviceMode']=='restaurant'
    assert visible['recipes'][0]['availableToOrder']==10
    assert 'components' not in visible_state(state,{**USER,'staff_role':'cashier'})['recipes'][0]
    apply_action(state,USER,'sale.create',{'items':[{'id':recipe['id'],'quantity':2}], 'paymentMethod':'card'})
    assert state['logisticsState']['branchStocks']['b1']['i1']==pytest.approx(2.4)
    assert state['sales'][0]['items'][0]['ingredientAllocations'][0]['quantity']==pytest.approx(.6)
    assert state['sales'][0]['items'][0]['batchAllocations']==[]
    assert state['logisticsState']['batches']==[]


def test_shared_ingredients_cannot_be_oversold_between_dishes():
    state,recipe=scenario()
    second=state['recipes'][1]
    second['components']=deepcopy(recipe['components'])
    stock=deepcopy(state['logisticsState']['branchStocks'])
    with pytest.raises(WorkspaceError,match='Недостаточно ингредиентов'):
        apply_action(state,USER,'sale.create',{'items':[{'id':recipe['id'],'quantity':6},{'id':second['id'],'quantity':6}],'paymentMethod':'card'})
    assert state['logisticsState']['branchStocks']==stock


def test_refund_does_not_turn_prepared_food_back_into_raw_ingredients():
    state,recipe=scenario()
    _,sale_id=apply_action(state,USER,'sale.create',{'items':[{'id':recipe['id'],'quantity':1}], 'paymentMethod':'card'})
    apply_action(state,USER,'sale.refund',{'id':sale_id,'reason':'Возврат оплаты'})
    assert state['logisticsState']['branchStocks']['b1']['i1']==pytest.approx(2.7)
    assert state['sales'][0]['refundedAt']


@pytest.mark.parametrize('plan',['canteen','starter','business','enterprise'])
def test_canteen_and_legacy_require_serving_batches(plan):
    state,recipe=scenario()
    with pytest.raises(WorkspaceError,match='На раздаче недостаточно'):
        apply_action(state,{**USER,'plan_code':plan},'sale.create',{'items':[{'id':recipe['id'],'quantity':1}],'paymentMethod':'card'})
    assert visible_state(state,{**USER,'plan_code':plan})['serviceMode']=='canteen'


def test_restaurant_cannot_consume_ingredients_twice_using_batches():
    state,recipe=scenario()
    with pytest.raises(WorkspaceError,match='Ресторан'):
        apply_action(state,USER,'batch.create',{'recipeId':recipe['id'],'weight':1})


@pytest.mark.parametrize('value',['-1','NaN','Infinity','10000000000','2.001'])
@pytest.mark.parametrize('field',['monthly_price','annual_price'])
def test_price_validation(value,field):
    with pytest.raises(ValidationError): PlanPriceUpdate(**{'monthly_price':3500,field:value})


def test_only_platform_owner_can_read_or_change_prices(monkeypatch):
    monkeypatch.setattr(main,'_check_origin',lambda request:None)
    with pytest.raises(HTTPException) as error: main.list_plans(USER,None)
    assert error.value.status_code==403
    with pytest.raises(HTTPException) as error: main.update_plan('canteen',PlanPriceUpdate(monthly_price=0),None,USER,None)
    assert error.value.status_code==403


def test_price_save_is_persistent_and_audited(monkeypatch):
    monkeypatch.setattr(main,'_check_origin',lambda request:None)
    class Connection:
        def __init__(self): self.calls=[]
        def transaction(self): return nullcontext()
        def execute(self,sql,params):
            self.calls.append((sql,params))
            return SimpleNamespace(fetchone=lambda:{'code':'canteen','monthly_price':params[0],'annual_price':params[1]})
    connection=Connection()
    result=main.update_plan('canteen',PlanPriceUpdate(monthly_price='3499.50',annual_price='41994'),None,{'id':1,'login':'owner','role':'platform_owner'},connection)
    assert result['monthly_price']==Decimal('3499.50') and result['annual_price']==Decimal('41994')
    assert any('platform_events' in sql for sql,_ in connection.calls)


@pytest.mark.parametrize('pending',['batch','order'])
def test_mode_switch_rejected_when_operational_documents_are_open(monkeypatch,pending):
    from app.schemas import TenantUpdate
    monkeypatch.setattr(main,'_check_origin',lambda request:None)
    state=default_state()
    state['logisticsState']['batches']=[]
    state['posState']={'openOrders':[]}
    if pending=='batch': state['logisticsState']['batches']=[{'status':'serving'}]
    else: state['posState']['openOrders']=[{'id':'open'}]
    monkeypatch.setattr(main,'_workspace_row',lambda *args,**kwargs:{'payload':state})
    class Connection:
        def transaction(self): return nullcontext()
        def execute(self,sql,params):
            assert 'SELECT tenant.name' in sql, 'Blocked switch must not write subscription or workspace'
            return SimpleNamespace(fetchone=lambda:{'plan_code':'canteen'})
    with pytest.raises(HTTPException) as error:
        main.update_tenant('t1',TenantUpdate(plan_code='restaurant'),None,{'role':'platform_owner'},Connection())
    assert error.value.status_code==409
