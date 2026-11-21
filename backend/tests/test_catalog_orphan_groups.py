from copy import deepcopy
from app.workspace import default_state, apply_action, visible_state
from app.catalog_groups import repair_missing_parents
from app.catalog_saves import revision

OWNER = {'id': 1, 'role': 'owner', 'display_name': 'Owner', 'branch_id': None}


def test_repair_preserves_ids_prices_stock_and_valid_groups():
    rows = [
        {'id': 'a', 'parentId': 'missing', 'is_active': False, 'price': 100},
        {'id': 'b', 'parentId': 'missing', 'price': 250},
        {'id': 'c', 'parentId': 'missing', 'price': 300},
        {'id': 'valid'}, {'id': 'child', 'parentId': 'valid'},
    ]
    before = deepcopy(rows)
    repair_missing_parents(rows)
    assert [r['parentId'] for r in rows[:3]] == ['b', None, 'b']
    assert rows[3:] == before[3:]
    assert [{k:v for k,v in r.items() if k!='parentId'} for r in rows] == [{k:v for k,v in r.items() if k!='parentId'} for r in before]
    snapshot = deepcopy(rows)
    repair_missing_parents(rows)
    assert rows == snapshot


def test_orphan_product_group_can_save_without_creating_products_or_resetting_stock():
    state = default_state()
    root = deepcopy(state['products'][0])
    root.update(id='cheese-a', name='Cheesecake — white', groupName='Cheesecake', variantName='white', parentId='missing', price=250)
    child = {**root, 'id':'cheese-b', 'name':'Cheesecake — chocolate', 'variantName':'chocolate'}
    state['products'].extend([root, child])
    state['logisticsState']['branchStocks']['b1'].update({'cheese-a': 10, 'cheese-b': 20})
    stocks = deepcopy(state['logisticsState']['branchStocks'])
    before_ids = [r['id'] for r in state['products']]
    # The UI retains the server revision from the original imported family.
    shown = visible_state(state, OWNER)
    shown_root = next(r for r in shown['products'] if r['id']=='cheese-a')
    assert shown_root['editRevision'] == revision(state, 'product.group.upsert', 'cheese-a')
    apply_action(state, OWNER, 'product.group.upsert', {'id':'cheese-a','name':'Cheesecake','category':'Desserts','unit':'шт','variants':[{'id':'cheese-a','name':'white','price':250},{'id':'cheese-b','name':'chocolate','price':250}]})
    assert [r['id'] for r in state['products']] == before_ids
    assert state['logisticsState']['branchStocks'] == stocks
    members = [r for r in state['products'] if r['id'].startswith('cheese')]
    assert [r.get('parentId') for r in members] == [None,'cheese-a']
