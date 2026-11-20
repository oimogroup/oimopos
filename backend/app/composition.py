"""Expand virtual preparations to raw ingredients for cost and stock deductions.

Component quantities use the existing workspace convention: grams/millilitres,
or thousandths of a piece. Preparation quantities and yields are always grams.
"""
from math import isfinite


class CompositionError(ValueError):
    pass


def catalog_sources(state):
    """Stable selector identities for import/export, without merging raw stocks."""
    return [*state.get('ingredients', []), *[
        {**row, 'id': 'preparation:' + str(row['id']), 'preparationId': str(row['id']),
         'name': str(row.get('name', '')) + ' [п/ф]', 'unit': 'кг'}
        for row in state.get('preparations', [])]]


def preparation_users(state, preparation_id):
    return [row for row in [*state.get('recipes', []), *state.get('preparations', [])]
            if any(str(component.get('preparationId', '')) == str(preparation_id)
                   for component in row.get('components', []))]


def flatten(state, item, stack=(), *, strict=False):
    ingredients = {str(row['id']): row for row in state.get('ingredients', [])} if strict else {}
    preparations = {str(row['id']): row for row in state.get('preparations', [])}
    amounts = {}

    def expand(components, factor, path):
        if len(path) > 20:
            raise CompositionError('Слишком много уровней вложенности полуфабрикатов')
        for component in components:
            try:
                gross = float(component.get('gross', component.get('net', 0)))
            except (ValueError, TypeError):
                raise CompositionError('Брутто компонента должно быть числом') from None
            if not isfinite(gross) or gross < 0:
                raise CompositionError('Брутто компонента должно быть больше нуля')
            if gross == 0:
                continue
            if component.get('preparationId') is not None:
                identity = str(component['preparationId'])
                preparation = preparations.get(identity)
                if preparation is None:
                    raise CompositionError(f'Полуфабрикат не найден: {identity}')
                if identity in path:
                    names = [preparations[key].get('name', key) for key in (*path, identity)]
                    raise CompositionError('Цикл в составе полуфабрикатов: ' + ' → '.join(names))
                try:
                    output = float(preparation.get('yield', 0))
                except (ValueError, TypeError):
                    output = 0
                if not isfinite(output) or output <= 0 or not preparation.get('components'):
                    raise CompositionError(f'Проверьте состав и выход полуфабриката «{preparation.get("name", identity)}»')
                expand(preparation['components'], factor * gross / output, (*path, identity))
            else:
                identity = str(component.get('ingredientId', ''))
                if strict and identity not in ingredients:
                    raise CompositionError(f'Ингредиент не найден: {identity}')
                amount = gross * factor
                if not isfinite(amount):
                    raise CompositionError('Слишком большое количество компонента')
                total = amounts.get(identity, 0) + amount
                if not isfinite(total):
                    raise CompositionError('Слишком большое количество компонента')
                amounts[identity] = total

    expand(item.get('components', []), 1, stack)
    return [{'ingredientId': identity, 'gross': amount, 'net': amount}
            for identity, amount in amounts.items()]
