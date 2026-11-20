from copy import deepcopy

import pytest

from app.workspace import WorkspaceError, apply_action, default_state, visible_state

OWNER = {'id': 1, 'role': 'owner', 'display_name': 'Owner'}


def test_read_merges_legacy_categories_and_keeps_empty_groups_and_images():
    state = default_state()
    state['menuCategories'] = [{'name': 'Напитки', 'color': '#123456'}]
    state['recipeCategories'] = [{'name': 'напитки', 'image': 'legacy-image', 'is_active': False}]
    state['productCategories'] = [{'name': 'Пустая группа', 'color': '#abcdef'}]
    state['products'][0]['category'] = 'НАПИТКИ'
    before = deepcopy(state)
    output = visible_state(state, OWNER)
    assert state == before  # read normalization does not write to production
    assert output['menuCategories'] == output['recipeCategories'] == output['productCategories']
    drinks = [row for row in output['menuCategories'] if row['name'].lower() == 'напитки']
    assert drinks == [{'name': 'Напитки', 'color': '#123456', 'image': 'legacy-image', 'is_active': False}]
    assert any(row['name'] == 'Пустая группа' for row in output['menuCategories'])
    assert output['products'][0]['category'] == 'Напитки'


@pytest.mark.parametrize('kind', ['menu', 'recipe', 'product'])
def test_creating_category_from_any_legacy_kind_makes_it_available_to_both(kind):
    state = default_state()
    apply_action(state, OWNER, 'category.upsert', {'kind': kind, 'name': 'Общие десерты', 'color': '#112233'})
    output = visible_state(state, OWNER)
    for registry in ('menuCategories', 'recipeCategories', 'productCategories'):
        assert any(row['name'] == 'Общие десерты' for row in output[registry])
    assert 'recipeCategories' not in state
    assert 'productCategories' not in state


@pytest.mark.parametrize('kind', ['menu-category', 'recipe-category', 'product-category'])
def test_hiding_shared_category_updates_both_views_and_can_be_reversed(kind):
    state = default_state()
    apply_action(state, OWNER, 'catalog.stop', {'kind': kind, 'id': 'Напитки', 'is_active': False})
    output = visible_state(state, OWNER)
    assert output['recipeCategories'] == output['productCategories'] == output['menuCategories']
    assert next(row for row in state['menuCategories'] if row['name'] == 'Напитки')['is_active'] is False
    apply_action(state, OWNER, 'catalog.stop', {'kind': kind, 'id': 'Напитки', 'is_active': True})
    assert next(row for row in state['menuCategories'] if row['name'] == 'Напитки')['is_active'] is True


@pytest.mark.parametrize('kind', ['menu-category', 'recipe-category', 'product-category'])
def test_shared_category_delete_checks_both_collections_and_removes_empty_group(kind):
    state = default_state()
    state['products'][0]['category'] = 'Только товары'
    with pytest.raises(WorkspaceError, match='Сначала перенесите'):
        apply_action(state, OWNER, 'catalog.delete', {'kind': kind, 'id': 'Только товары'})
    apply_action(state, OWNER, 'category.upsert', {'kind': 'menu', 'name': 'Пустая'})
    apply_action(state, OWNER, 'catalog.delete', {'kind': kind, 'id': 'Пустая'})
    output = visible_state(state, OWNER)
    assert not any(row['name'] == 'Пустая' for row in output['menuCategories'])


def test_menu_and_ingredient_categories_are_still_separate():
    state = default_state()
    state['ingredients'][0]['category'] = 'Напитки'
    apply_action(state, OWNER, 'category.upsert', {'kind': 'menu', 'originalName': 'Напитки', 'name': 'Бар'})
    assert state['ingredients'][0]['category'] == 'Напитки'


def test_blank_legacy_category_is_normalized_without_losing_position():
    state = default_state()
    state['products'][0]['category'] = '   '
    output = visible_state(state, OWNER)
    assert output['products'][0]['category'] == 'Без категории'
    assert any(row['name'] == 'Без категории' for row in output['menuCategories'])
