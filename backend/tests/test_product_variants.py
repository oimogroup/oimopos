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


def test_product_variant_can_be_removed_and_replaced_without_losing_history():
    state = default_state()
    payload, variants = create(state)
    removed = variants[1]
    state['logisticsState']['branchStocks']['b1'][removed['id']] = 1
    _, sale_id = apply_action(state, CASHIER, 'sale.create', {'paymentMethod':'card','items':[{'id':removed['id'],'quantity':1}]})
    payload['variants'] = [
        {'id': variants[0]['id'], 'name': variants[0]['variantName'], 'price': variants[0]['price']},
        {'name': 'Манго', 'price': 150},
    ]

    apply_action(state, OWNER, 'product.group.upsert', payload)

    archived = next(product for product in state['products'] if product['id'] == removed['id'])
    sale = next(sale for sale in state['sales'] if sale['id'] == sale_id)
    active_variants = [product for product in state['products'] if product.get('groupName') == 'Сок' and product.get('is_active', True)]
    visible_ids = {product['id'] for product in visible_state(state, CASHIER)['products']}
    assert archived['is_active'] is False
    assert archived['parentId'] == 'juice'
    assert sale['items'][0]['id'] == removed['id']
    assert {product['variantName'] for product in active_variants} == {'Яблочный', 'Манго'}
    assert removed['id'] not in visible_ids


def test_product_variant_can_be_removed_as_group_root_without_rewriting_history():
    state = default_state()
    payload, variants = create(state)
    removed_root = variants[0]
    state['logisticsState']['branchStocks']['b1'][removed_root['id']] = 1
    _, sale_id = apply_action(state, CASHIER, 'sale.create', {'paymentMethod':'card','items':[{'id':removed_root['id'],'quantity':1}]})
    promoted = variants[1]
    payload.update({
        'id': promoted['id'],
        'previousGroupId': removed_root['id'],
        'variants': [{'id': promoted['id'], 'name': promoted['variantName'], 'price': promoted['price']}],
    })

    apply_action(state, OWNER, 'product.group.upsert', payload)

    archived_root = next(product for product in state['products'] if product['id'] == removed_root['id'])
    promoted_root = next(product for product in state['products'] if product['id'] == promoted['id'])
    sale = next(sale for sale in state['sales'] if sale['id'] == sale_id)
    assert archived_root['is_active'] is False
    assert archived_root['parentId'] == promoted['id']
    assert promoted_root['parentId'] is None
    assert sale['items'][0]['id'] == removed_root['id']
    assert promoted['id'] in {product['id'] for product in visible_state(state, CASHIER)['products']}


def test_product_variant_with_stock_cannot_be_removed():
    state = default_state()
    payload, variants = create(state)
    state['logisticsState']['branchStocks']['b1'][variants[1]['id']] = 2
    payload['variants'] = [{'id': variants[0]['id'], 'name': variants[0]['variantName'], 'price': variants[0]['price']}]
    before = deepcopy(state)

    with pytest.raises(WorkspaceError, match='обнулите остаток'):
        apply_action(state, OWNER, 'product.group.upsert', payload)

    assert state == before


def test_product_group_can_replace_all_saved_variants_with_a_new_root():
    state = default_state()
    payload, variants = create(state)
    payload.update({
        'id': 'product-new-root',
        'previousGroupId': 'juice',
        'variants': [{'name': 'Манго', 'price': 150}],
    })

    apply_action(state, OWNER, 'product.group.upsert', payload)

    active = [product for product in state['products'] if product.get('groupName') == 'Сок' and product.get('is_active', True)]
    assert len(active) == 1
    assert active[0]['id'] == 'product-new-root' and active[0]['parentId'] is None
    for variant in variants:
        archived = next(product for product in state['products'] if product['id'] == variant['id'])
        assert archived['is_active'] is False
        assert archived['parentId'] == 'product-new-root'
