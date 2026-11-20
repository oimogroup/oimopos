import pytest

from app.workspace import WorkspaceError, apply_action, default_state


OWNER = {'id': 1, 'role': 'owner', 'display_name': 'Test'}


def save_component(state, component):
    return apply_action(state, OWNER, 'recipe.upsert', {
        'name': 'Блинчики с творогом', 'station': 'Кухня',
        'yield': 100, 'price': 100, 'components': [component],
    })


def test_fractional_egg_conversion_roundoff_does_not_block_recipe_save():
    state = default_state()
    state['ingredients'].append({'id': 'egg', 'name': 'Яйцо куриное', 'unit': 'шт', 'pieceWeightGrams': 65})
    gross = 85.22727273
    mass = 5.53977273
    _, identifier = save_component(state, {
        'ingredientId': 'egg', 'gross': gross, 'net': mass / 65 * 1000,
        'netWeightGrams': mass, 'pieceWeightGrams': 65,
    })
    component = next(r for r in state['recipes'] if str(r['id']) == identifier)['components'][0]
    assert component['net'] == gross
    assert component['netWeightGrams'] == mass


@pytest.mark.parametrize(('gross', 'net', 'message'), [
    (0, 1, 'брутто должно'), (1, 0, 'нетто должно'),
    (5, 6, 'нетто (6 г) больше брутто (5 г)'),
])
def test_recipe_error_identifies_ingredient_and_invalid_quantity(gross, net, message):
    state = default_state()
    ingredient = state['ingredients'][0]
    ingredient['unit'] = 'кг'
    with pytest.raises(WorkspaceError) as error:
        save_component(state, {'ingredientId': ingredient['id'], 'gross': gross, 'net': net})
    assert ingredient['name'] in str(error.value)
    assert 'Строка 1' in str(error.value)
    assert message in str(error.value)


def test_missing_ingredient_error_identifies_row():
    with pytest.raises(WorkspaceError, match='Строка 1: ингредиент не найден'):
        save_component(default_state(), {'ingredientId': 'deleted', 'gross': 10, 'net': 9})
