from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.inventory_count import build
from app.workspace import _set_stock, apply_action, default_state


OWNER = {'id': 1, 'role': 'owner', 'display_name': 'Owner'}
USER = {'id': 2, 'role': 'branch', 'branch_id': 'b1', 'display_name': 'Cashier'}
START = datetime.now(timezone.utc) - timedelta(days=30)


def at(day):
    return (START + timedelta(days=day)).isoformat()


def movement(identifier, quantity, kind, day, **fields):
    return {'id': identifier, 'branchId': 'b1', 'itemId': 'rice', 'quantity': quantity,
            'movementType': kind, 'unitCost': 10, 'documentNumber': identifier,
            'createdAt': at(day), 'createdBy': 'Employee', **fields}


def count(identifier, day, items, **fields):
    return {'id': identifier, 'number': identifier, 'branchId': 'b1', 'status': 'posted',
            'createdAt': at(day), 'countedAt': at(day), 'postedAt': at(day),
            'items': [{'itemId': item_id, 'actual': actual, 'book': actual} for item_id, actual in items], **fields}


def selected(state, item_ids=('rice',), day=10):
    rows, _ = build(state, 'b1', {'scope': 'selected', 'itemIds': list(item_ids), 'countedAt': at(day)},
                    [*state['ingredients'], *state['products']])
    return rows


def assert_reconciles(item):
    summary = item['movementSummary']
    assert summary['opening'] + summary['incoming'] - summary['outgoing'] - summary['writtenOff'] + summary['adjustments'] == pytest.approx(item['book'])


def test_snapshot_separates_consumption_writeoffs_and_adjustments_and_filters_branch_item_date():
    state = default_state()
    state['logisticsState']['stockLedger'] = [
        movement('receipt', 10, 'supplier_receipt', 1),
        movement('refund', 2, 'sale_refund', 2),
        movement('production', -3, 'production_consumption', 3),
        movement('sale', -2, 'sale', 4),
        movement('dish-sale', -1, 'sale_consumption', 5, documentNumber='POS'),
        movement('transfer', -1, 'transfer_out', 6, relatedBranchId='b2'),
        movement('writeoff', -4, 'writeoff', 7),
        movement('inventory', -1, 'inventory_adjustment', 8),
        movement('shift-count', .5, 'ingredient_count', 9),
        movement('later', 9, 'supplier_receipt', 11),
        movement('other-branch', 900, 'supplier_receipt', 3, branchId='b2'),
        movement('other-item', 500, 'supplier_receipt', 3, itemId='beef'),
    ]
    state['logisticsState']['batches'] = [{'branchId': 'b1', 'number': 'production', 'recipeId': 101}]
    _set_stock(state, 'b1', 'rice', 29.5)

    item = selected(state)[0]
    summary = item['movementSummary']

    assert item['book'] == 20.5
    assert summary['opening'] == 20
    assert summary['openingBasis'] == 'reconstructed'
    assert summary['lastCountAt'] is None
    assert (summary['incoming'], summary['outgoing'], summary['writtenOff'], summary['adjustments']) == (12, 7, 4, -.5)
    assert summary['writtenOffCost'] == 40
    entries = {entry['id']: entry for entry in summary['entries']}
    assert list(entries) == ['receipt', 'refund', 'production', 'sale', 'dish-sale', 'transfer', 'writeoff', 'inventory', 'shift-count']
    assert entries['production']['dishName'] == next(recipe['name'] for recipe in state['recipes'] if recipe['id'] == 101)
    assert 'dishName' not in entries['dish-sale']
    assert entries['writeoff']['bucket'] == 'writeoff'
    assert entries['production']['bucket'] == entries['dish-sale']['bucket'] == 'outgoing'
    assert entries['production']['quantity'] == 3
    assert entries['production']['signedQuantity'] == -3
    assert entries['transfer']['relatedBranchId'] == 'b2'
    assert entries['shift-count']['bucket'] == 'adjustment'
    assert entries['writeoff']['actor'] == 'Employee'
    assert_reconciles(item)


def test_last_count_is_per_item_and_effective_date_with_posted_tie_break():
    state = default_state()
    state['logisticsState']['inventories'] = [
        count('partial-beef', 7, [('beef', 50)]),
        count('rice-later-post', 2, [('rice', 12)], postedAt=at(4)),
        count('rice-first-post', 2, [('rice', 10)], postedAt=at(3)),
        count('older-full', 1, [('rice', 9), ('beef', 40)]),
        count('pending', 9, [('rice', 100)], status='submitted'),
        count('other-branch', 9, [('rice', 1000)], branchId='b2'),
    ]
    state['logisticsState']['stockLedger'] = [
        movement('before', 20, 'supplier_receipt', 0),
        movement('prior-correction', 2, 'inventory_adjustment', 4, documentNumber='rice-later-post'),
        movement('incoming-rice', 3, 'supplier_receipt', 5),
        movement('shift-rice', -.25, 'ingredient_count', 6),
        movement('incoming-beef-before', 10, 'supplier_receipt', 6, itemId='beef'),
        movement('outgoing-beef', -2, 'production_consumption', 8, itemId='beef'),
    ]
    _set_stock(state, 'b1', 'rice', 14.75)
    _set_stock(state, 'b1', 'beef', 48)

    items = {item['itemId']: item for item in selected(state, ['rice', 'beef'])}

    rice = items['rice']['movementSummary']
    beef = items['beef']['movementSummary']
    assert rice['lastCountId'] == 'rice-later-post'
    assert rice['lastCountAt'] == at(2)
    assert rice['opening'] == 12
    assert rice['openingBasis'] == 'inventory'
    assert [entry['id'] for entry in rice['entries']] == ['incoming-rice', 'shift-rice']
    assert beef['lastCountId'] == 'partial-beef'
    assert beef['opening'] == 50
    assert [entry['id'] for entry in beef['entries']] == ['outgoing-beef']
    for item in items.values():
        assert_reconciles(item)


def test_backdated_receipts_use_business_dates_including_legacy_documents():
    state = default_state()
    state['logisticsState']['supplies'] = [{'branchId': 'b1', 'number': 'legacy', 'receivedAt': at(4)}]
    state['logisticsState']['stockLedger'] = [
        movement('effective', 5, 'supplier_receipt', 20, effectiveAt=at(3)),
        movement('legacy', 7, 'supplier_receipt', 20),
        movement('future', 11, 'supplier_receipt', 1, effectiveAt=at(15)),
    ]
    _set_stock(state, 'b1', 'rice', 33)

    item = selected(state)[0]
    summary = item['movementSummary']

    assert item['book'] == 22
    assert summary['opening'] == 10
    assert summary['incoming'] == 12
    assert [entry['date'] for entry in summary['entries']] == [at(3), at(4)]
    assert summary['entries'][0]['createdAt'] == at(20)
    assert_reconciles(item)


def test_reconstructed_opening_does_not_claim_a_prior_count_was_unchanged_by_backdating():
    state = default_state()
    state['logisticsState']['inventories'] = [count('previous', 5, [('rice', 10)])]
    state['logisticsState']['stockLedger'] = [
        movement('late-backdated', 4, 'supplier_receipt', 8, effectiveAt=at(3)),
        movement('after-count', 2, 'supplier_receipt', 8),
    ]
    _set_stock(state, 'b1', 'rice', 16)

    item = selected(state)[0]
    summary = item['movementSummary']

    assert summary['lastCountQuantity'] == 10
    assert summary['opening'] == 14
    assert summary['openingBasis'] == 'reconstructed'
    assert [entry['id'] for entry in summary['entries']] == ['after-count']
    assert_reconciles(item)


def test_equal_count_date_uses_existing_posted_count_without_its_correction():
    state = default_state()
    state['logisticsState']['inventories'] = [count('previous', 5, [('rice', 10)])]
    state['logisticsState']['stockLedger'] = [movement('correction', 2, 'inventory_adjustment', 6, documentNumber='previous')]
    _set_stock(state, 'b1', 'rice', 10)

    summary = selected(state, day=5)[0]['movementSummary']

    assert summary['lastCountId'] == 'previous'
    assert summary['opening'] == 10
    assert summary['openingBasis'] == 'inventory'
    assert summary['entries'] == []


def test_no_history_is_an_explicit_reconstructed_opening_without_fabricated_receipt():
    state = default_state()
    items, _ = build(state, 'b1', {'scope': 'selected', 'itemIds': ['rice']}, state['ingredients'])
    summary = items[0]['movementSummary']
    assert summary['opening'] == items[0]['book']
    assert summary['openingBasis'] == 'reconstructed'
    assert summary['lastCountAt'] is summary['historyStartAt'] is None
    assert summary['incoming'] == summary['outgoing'] == summary['writtenOff'] == 0
    assert summary['entries'] == []


def test_unknown_historical_writeoff_cost_stays_unknown():
    state = default_state()
    row = movement('writeoff', -2, 'writeoff', 1)
    del row['unitCost']
    state['logisticsState']['stockLedger'] = [row]
    summary = selected(state)[0]['movementSummary']
    assert summary['writtenOff'] == 2
    assert summary['writtenOffCost'] is None
    assert summary['entries'][0]['unitCost'] is summary['entries'][0]['cost'] is None


def test_snapshot_survives_save_return_submit_post_and_catalog_or_ledger_edits():
    state = default_state()
    state['logisticsState']['stockLedger'] = [movement('receipt', 5, 'supplier_receipt', 1)]
    _, inventory_id = apply_action(state, USER, 'inventory.start', {'scope': 'selected', 'itemIds': ['rice']})
    inventory = next(document for document in state['logisticsState']['inventories'] if document['id'] == inventory_id)
    item = inventory['items'][0]
    snapshot = deepcopy(item)
    state['ingredients'][0].update(name='Renamed', unit='New unit', category='New category')
    state['logisticsState']['stockLedger'][0].update(quantity=900, unitCost=900, createdBy='Changed')
    supplied = {'id': inventory_id, 'items': [{'itemId': 'rice', 'actual': item['book'] - 1, 'movementSummary': {'opening': -900}}]}

    for action in ['inventory.save', 'inventory.submit']:
        apply_action(state, USER, action, supplied)
    apply_action(state, OWNER, 'inventory.return', {'id': inventory_id, 'comment': 'Recount'})
    apply_action(state, USER, 'inventory.submit', supplied)
    apply_action(state, OWNER, 'inventory.post', {'id': inventory_id})

    assert item['movementSummary'] == snapshot['movementSummary']
    assert {key: item[key] for key in ('name', 'unit', 'category')} == {key: snapshot[key] for key in ('name', 'unit', 'category')}
    assert all(entry['documentNumber'] != inventory['number'] for entry in item['movementSummary']['entries'])
    assert inventory['status'] == 'posted'


def test_serving_count_keeps_custody_separate_from_ingredient_movements():
    state = default_state()
    state['logisticsState']['stockLedger'] = [movement('production', -3, 'production_consumption', 1)]
    state['logisticsState']['batches'] = [{'id': 'batch', 'branchId': 'b1', 'recipeId': 101,
        'actualWeight': 5, 'cost': 100, 'servingLots': [{'id': 'lot', 'acceptedAt': at(1), 'responsibleId': 2, 'acceptedWeight': 5, 'soldWeight': 1}]}]

    items, _ = build(state, 'b1', {'scope': 'serving'}, [])

    assert items[0]['book'] == 4
    assert items[0]['movementSummary'] == {'available': False, 'reason': 'serving_custody'}


def test_opening_preserves_previous_count_millesimal_precision_rule():
    state = default_state()
    previous = count('previous', 2, [('rice', 1.0)])
    previous['items'][0]['book'] = 1.0001
    state['logisticsState']['inventories'] = [previous]
    state['logisticsState']['stockLedger'] = [movement('sale', -.25, 'sale_consumption', 3)]
    _set_stock(state, 'b1', 'rice', .7501)

    item = selected(state)[0]

    assert item['movementSummary']['opening'] == pytest.approx(1.0001)
    assert item['movementSummary']['openingBasis'] == 'inventory'
    assert item['book'] == .7501
    assert_reconciles(item)
