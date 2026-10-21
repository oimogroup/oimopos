"""Backdated external sales must not become a second inventory shortage."""
from copy import deepcopy
from datetime import datetime

import pytest

from app.inventory_count import movement_date
from app.sales_import import commit
from app.workspace import _set_stock, _stock, apply_action, default_state
from test_sales_import import USER, file, scenario


TITLE = 'Реестр продаж с 10.01.2025 по 10.01.2025'
COUNTED_AT = '2025-01-11T23:59:59+05:00'
OWNER = {'id': 1, 'role': 'owner', 'display_name': 'Owner'}


def imported_product():
    state = default_state()
    state['companySettings'] = {'general': {'timezone': 'Asia/Almaty', 'currency': 'KZT'}}
    _set_stock(state, 'b1', 'p-1', 10, 20)
    state['logisticsState']['stockLedger'] = [{
        'id': 'opening', 'branchId': 'b1', 'itemId': 'p-1', 'quantity': 10,
        'unitCost': 20, 'movementType': 'supplier_receipt', 'documentNumber': 'opening',
        'createdAt': '2025-01-09T12:00:00+05:00',
    }]
    commit(state, USER, {'file': file(title=TITLE),
                         'selections': [{'row': '7', 'recipeId': 'product:p-1'}]})
    return state


@pytest.mark.parametrize('legacy', [False, True])
def test_backdated_import_count_does_not_subtract_sold_products_twice(legacy):
    state = imported_product()
    movement = state['logisticsState']['stockLedger'][0]
    if legacy:
        del movement['effectiveAt']
    else:
        assert movement['effectiveAt'] == state['sales'][0]['createdAt'] == '2025-01-10T12:00:00+05:00'
    before = deepcopy(movement)
    _, inventory_id = apply_action(state, OWNER, 'inventory.start', {
        'branchId': 'b1', 'scope': 'selected', 'itemIds': ['p-1'], 'countedAt': COUNTED_AT,
    })
    inventory = next(document for document in state['logisticsState']['inventories']
                     if document['id'] == inventory_id)
    assert inventory['items'][0]['book'] == 8
    assert inventory['items'][0]['movementSummary']['outgoing'] == 2
    apply_action(state, OWNER, 'inventory.submit', {
        'id': inventory_id, 'items': [{'itemId': 'p-1', 'actual': 8}],
    })
    apply_action(state, OWNER, 'inventory.post', {'id': inventory_id})
    assert _stock(state, 'b1', 'p-1') == 8
    assert movement == before
    assert not any(row['movementType'] == 'inventory_adjustment'
                   for row in state['logisticsState']['stockLedger'])


@pytest.mark.parametrize('sale_available', [False, True])
def test_legacy_import_keeps_original_timezone_after_company_setting_changes(sale_available):
    state = imported_product()
    movement = state['logisticsState']['stockLedger'][0]
    del movement['effectiveAt']
    state['companySettings']['general']['timezone'] = 'America/New_York'
    if sale_available:
        del state['externalSalesImports'][0]['timezone']
    else:
        state['sales'] = []
    assert movement_date(state, movement).isoformat() == '2025-01-10T12:00:00+05:00'


@pytest.mark.parametrize('change', ['branch', 'product', 'recipe', 'status', 'title', 'ambiguous'])
def test_legacy_fallback_requires_unambiguous_matching_posted_product_import(change):
    state = imported_product()
    movement = state['logisticsState']['stockLedger'][0]
    del movement['effectiveAt']
    document = state['externalSalesImports'][0]
    if change == 'branch':
        document['branchId'] = 'b2'
    elif change == 'product':
        document['items'][0]['productId'] = 'p-2'
    elif change == 'recipe':
        document['items'][0]['recipeId'] = document['items'][0].pop('productId')
    elif change == 'status':
        document['status'] = 'cancelled'
    elif change == 'title':
        document['title'] = movement['documentNumber'] = 'Реестр продаж с 10.01.2025 по 11.01.2025'
    else:
        state['sales'] = []
        other = deepcopy(document)
        other.update(id='other-import', timezone='UTC')
        state['externalSalesImports'].append(other)
    snapshot = deepcopy(state)
    assert movement_date(state, movement) == datetime.fromisoformat(movement['createdAt'])
    assert state == snapshot


def test_explicit_effective_date_and_regular_sales_keep_their_existing_dates():
    state = imported_product()
    movement = state['logisticsState']['stockLedger'][0]
    movement['effectiveAt'] = '2025-01-10T15:00:00+05:00'
    assert movement_date(state, movement).isoformat() == movement['effectiveAt']
    del movement['effectiveAt']
    movement['documentNumber'] = 'ЧЕК-1'
    assert movement_date(state, movement) == datetime.fromisoformat(movement['createdAt'])


def test_recipe_import_only_consumes_serving_lot_and_still_uses_report_date():
    state = scenario()
    stocks = deepcopy(state['logisticsState']['branchStocks'])
    ledger = deepcopy(state['logisticsState']['stockLedger'])
    commit(state, USER, {'file': file(title=TITLE), 'selections': [{'row': '7', 'recipeId': 101}]})
    assert state['logisticsState']['stockLedger'] == ledger
    assert state['logisticsState']['branchStocks'] == stocks
    assert state['logisticsState']['batches'][0]['servingLots'][0]['soldWeight'] == .5
    assert state['sales'][0]['createdAt'].startswith('2025-01-10T12:00:00')
