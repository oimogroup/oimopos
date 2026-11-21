import pytest
from app.workspace import default_state, apply_action, visible_state, WorkspaceError
from app.marketing import discount
from app.catalog_saves import revision

OWNER = {"id": 1, "role": "owner", "branch_id": None, "display_name": "Owner"}
CASHIER = {"id": 2, "role": "branch", "branch_id": "b1", "display_name": "Cashier", "staff_role": "branch_manager", "register_id": 10, "shift_id": 20}


def setup():
    state = default_state()
    apply_action(state, OWNER, 'marketing.group.upsert', {'id': 'regular', 'name': 'Regulars', 'discountPercent': 10})
    apply_action(state, OWNER, 'marketing.customer.upsert', {'id': 'guest', 'name': 'Guest', 'phone': '+996 700 000 001', 'groupId': 'regular', 'personalDiscountPercent': None})
    return state


def sale(state):
    apply_action(state, CASHIER, 'sale.create', {'customerId': 'guest', 'paymentMethod': 'cash', 'received': 100, 'items': [{'id': 'p-1', 'quantity': 2}]})
    return state['sales'][0]


def test_group_discount_is_shared_by_pos_order_and_sale_and_history_is_frozen():
    state = setup()
    shown = visible_state(state, CASHIER)
    assert shown['posState']['customers'][0]['discountPercent'] == 10
    apply_action(state, CASHIER, 'pos.order.save', {'customerId': 'guest', 'items': [{'id': 'p-1', 'quantity': 2}]})
    assert state['posState']['openOrders'][0]['discountPercent'] == 10
    first = sale(state)
    assert first['total'] == 72
    group = state['posState']['customerGroups'][0]
    apply_action(state, OWNER, 'marketing.group.upsert', {**group, 'expectedRevision': group['editRevision'], 'discountPercent': 20})
    assert first['total'] == 72
    assert sale(state)['total'] == 64


def test_personal_discount_overrides_group_including_zero():
    state = setup()
    c = state['posState']['customers'][0]
    for value in [5, 0]:
        apply_action(state, OWNER, 'marketing.customer.upsert', {**c, 'expectedRevision': c['editRevision'], 'personalDiscountPercent': value})
        assert discount(state, c) == value
    apply_action(state, OWNER, 'marketing.customer.upsert', {**c, 'expectedRevision': c['editRevision'], 'personalDiscountPercent': None})
    assert discount(state, c) == 10


def test_archived_guest_is_hidden_at_pos_but_history_is_retained_and_cannot_sell():
    state = setup()
    first = sale(state)
    c = state['posState']['customers'][0]
    apply_action(state, OWNER, 'marketing.customer.archive', {'id': c['id'], 'expectedRevision': c['editRevision']})
    assert visible_state(state, CASHIER)['posState']['customers'] == []
    assert visible_state(state, OWNER)['posState']['customers'][0]['archivedAt']
    assert first['customerId'] == 'guest' and first['total'] == 72
    with pytest.raises(WorkspaceError, match='Гость недоступен'):
        sale(state)


def test_group_with_members_cannot_be_archived_and_stale_edit_is_rejected():
    state = setup()
    g = state['posState']['customerGroups'][0]
    with pytest.raises(WorkspaceError, match='перенесите'):
        apply_action(state, OWNER, 'marketing.group.archive', {'id': g['id'], 'expectedRevision': g['editRevision']})
    with pytest.raises(WorkspaceError, match='другим сотрудником'):
        apply_action(state, OWNER, 'marketing.group.upsert', {**g, 'expectedRevision': 'stale', 'discountPercent': 50})
    assert g['discountPercent'] == 10


def test_phone_duplicates_are_normalized_across_admin_and_pos():
    state = setup()
    for user, action in [(OWNER, 'marketing.customer.upsert'), (CASHIER, 'pos.customer.upsert')]:
        with pytest.raises(WorkspaceError, match='телефоном'):
            apply_action(state, user, action, {'name': 'Other', 'phone': '996700000001', 'personalDiscountPercent': 0})


@pytest.mark.parametrize('value', [-1, 101, float('nan'), float('inf'), True, '10'])
def test_invalid_discounts_are_rejected(value):
    with pytest.raises(WorkspaceError):
        apply_action(default_state(), OWNER, 'marketing.group.upsert', {'name': 'Bad', 'discountPercent': value})


@pytest.mark.parametrize('action', ['marketing.customer.upsert', 'marketing.customer.archive', 'marketing.group.upsert', 'marketing.group.archive', 'marketing.exclusion.update'])
def test_marketing_mutations_require_owner(action):
    with pytest.raises(WorkspaceError) as e:
        apply_action(default_state(), CASHIER, action, {})
    assert e.value.status_code == 403


def test_exclusion_changes_pos_total_and_checks_catalog_revision():
    state = setup()
    payload = {'kind': 'product', 'id': 'p-1', 'noDiscount': True, 'expectedRevision': revision(state, 'product.upsert', 'p-1')}
    apply_action(state, OWNER, 'marketing.exclusion.update', payload)
    assert sale(state)['total'] == 80
    assert visible_state(state, CASHIER)['products'][0].get('noDiscount') is not None
    with pytest.raises(WorkspaceError, match='изменена'):
        apply_action(state, OWNER, 'marketing.exclusion.update', {**payload, 'noDiscount': False})


def test_recipe_exclusion_reaches_cashier_projection():
    state = setup()
    recipe = state['recipes'][0]
    apply_action(state, OWNER, 'marketing.exclusion.update', {'kind': 'recipe', 'id': recipe['id'], 'noDiscount': True, 'expectedRevision': revision(state, 'recipe.upsert', recipe['id'])})
    assert visible_state(state, CASHIER)['recipes'][0]['noDiscount'] is True


def test_recipe_exclusion_and_group_discount_apply_only_to_eligible_lines():
    from custody_helpers import accepted_transfer
    state = setup()
    apply_action(state, CASHIER, 'batch.create', {'recipeId': 201, 'weight': 0.76})
    batch = state['logisticsState']['batches'][0]
    accepted_transfer(state, CASHIER, {'id': batch['id'], 'weight': 0.76, 'temperature': 65, 'line': 'Counter'})
    apply_action(state, OWNER, 'marketing.exclusion.update', {'kind': 'recipe', 'id': 201, 'noDiscount': True, 'expectedRevision': revision(state, 'recipe.upsert', 201)})
    apply_action(state, CASHIER, 'sale.create', {'customerId': 'guest', 'paymentMethod': 'cash', 'received': 500, 'items': [{'id': 201, 'quantity': 1}, {'id': 'p-1', 'quantity': 1}]})
    receipt = state['sales'][0]
    assert receipt['subtotal'] == 270
    assert receipt['discountAmount'] == 4
    assert receipt['total'] == 266
