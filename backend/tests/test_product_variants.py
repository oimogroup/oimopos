from copy import deepcopy
import pytest
from app.workspace import apply_action, default_state, visible_state, WorkspaceError

OWNER = {"id": 1, "role": "owner", "login": "admin", "display_name": "Admin"}
CASHIER = {"display_name": "Кассир", "login": "cashier", "id": 2, "role": "branch", "branch_id": "b1", "staff_role": "cashier", "register_id": 1, "shift_id": 1}


def create(state):
    station = state['stations'][0]
    station['destination'] = 'Принтер кухни'
    payload = {'id':'juice', 'name':'Сок', 'station':station['name'], 'category':'Напитки', 'unit':'шт', 'color':'#336699', 'variants':[{'name':'Яблочный','price':100,'barcode':'111'}, {'name':'Апельсиновый','price':120,'barcode':'222'}]}
    apply_action(state, OWNER, 'product.group.upsert', payload)
    return payload, [p for p in state['products'] if p.get('groupName') == 'Сок']


def test_variants_have_independent_stock_sale_and_station_route():
    state = default_state()
    payload, variants = create(state)
    first, second = variants
    state['logisticsState']['branchStocks']['b1'].update({first['id']:10, second['id']:7})
    _, sale_id = apply_action(state, CASHIER, 'sale.create', {'paymentMethod':'card','items':[{'id':second['id'],'quantity':2}]})
    sale = next(s for s in state['sales'] if s['id'] == sale_id)
    assert sale['total'] == 240
    assert state['logisticsState']['branchStocks']['b1'][first['id']] == 10
    assert state['logisticsState']['branchStocks']['b1'][second['id']] == 5
    assert sale['items'][0]['name'] == 'Сок — Апельсиновый'
    assert sale['items'][0]['destination'] == 'Принтер кухни'
    visible = visible_state(state, CASHIER)
    assert next(p for p in visible['products'] if p['id'] == second['id'])['parentId'] == 'juice'
    assert visible['sales'][0]['items'][0]['destination'] == 'Принтер кухни'
    apply_action(state, CASHIER, 'pos.order.save', {'items':[{'id':first['id'],'quantity':1}]})
    assert state['posState']['openOrders'][0]['items'][0]['station'] == payload['station']


def test_variant_edit_preserves_ids_stock_and_is_atomic_on_invalid_input():
    state=default_state(); payload, variants=create(state)
    state['logisticsState']['branchStocks']['b1'][variants[1]['id']]=8
    payload['variants']=[{'id':p['id'],'name':p['variantName'],'price':p['price']+10} for p in variants]
    apply_action(state, OWNER, 'product.group.upsert', payload)
    assert state['logisticsState']['branchStocks']['b1'][variants[1]['id']]==8
    snapshot=deepcopy(state)
    payload['variants'][1]['name']=payload['variants'][0]['name']
    with pytest.raises(WorkspaceError): apply_action(state, OWNER, 'product.group.upsert', payload)
    assert state==snapshot
    with pytest.raises(WorkspaceError): apply_action(state, OWNER, 'catalog.delete', {'kind':'product','id':'juice'})
    assert state==snapshot


def test_delete_unused_group_and_station_protection():
    state=default_state(); payload, variants=create(state)
    with pytest.raises(WorkspaceError): apply_action(state, OWNER, 'catalog.delete', {'kind':'station','id':payload['station']})
    apply_action(state, OWNER, 'catalog.delete', {'kind':'product','id':'juice'})
    assert not any(p.get('groupName')=='Сок' for p in state['products'])


def test_product_variant_volumes_survive_edit_and_cashier_projection():
    state = default_state()
    payload, variants = create(state)
    payload['variants'] = [{**row, 'id': item['id'], 'portionSize': size, 'portionUnit': 'мл'} for row, item, size in zip(payload['variants'], variants, [250, 500])]
    apply_action(state, OWNER, 'product.group.upsert', payload)
    exposed = visible_state(state, CASHIER)['products']
    assert next(p for p in exposed if p['id'] == variants[1]['id'])['portionSize'] == 500
    before = deepcopy(state)
    payload['variants'][1]['portionSize'] = 0
    with pytest.raises(WorkspaceError):
        apply_action(state, OWNER, 'product.group.upsert', payload)
    assert state == before
