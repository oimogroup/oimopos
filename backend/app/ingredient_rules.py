"""Safe changes to measurement units and live recipe loss coefficients."""
from math import isfinite


def parse_losses(value):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError('Потери должны быть указаны отдельно для каждого способа обработки')
    result = {}
    for key in ('boil', 'fry', 'bake', 'clean'):
        raw = value.get(key)
        try:
            number = float(raw) if raw not in (None, '') else 0.0
        except (ValueError, TypeError):
            raise ValueError('Укажите потери от 0 до 99%') from None
        if isinstance(raw, bool) or not isfinite(number) or not 0 <= number <= 99:
            raise ValueError('Укажите потери от 0 до 99%')
        result[key] = number
    return result


def unit_change_reason(state, identity):
    identity = str(identity)
    logistics = state.get('logisticsState', {})
    if any(abs(float(rows.get(identity, 0) or 0)) > 1e-9 for rows in logistics.get('branchStocks', {}).values()):
        return 'Нельзя менять единицу измерения при наличии остатка. Создайте новую позицию с нужной единицей.'
    for row in [*state.get('recipes', []), *state.get('preparations', [])]:
        if any(str(component.get('ingredientId', '')) == identity for component in row.get('components', [])):
            return 'Нельзя менять единицу измерения: ингредиент входит в состав техкарты или полуфабриката.'
    for group in state.get('modifierSets', []):
        if any(str(option.get('sourceId', '')) == identity for option in group.get('options', [])):
            return 'Нельзя менять единицу измерения: позиция используется в модификаторе.'
    if any(str(row.get('itemId', '')) == identity for row in logistics.get('stockLedger', [])):
        return 'Нельзя менять единицу измерения позиции с историей складских движений.'
    for collection in ('supplies', 'directOrders', 'pointTransfers', 'requests', 'inventories', 'writeoffs', 'preparationProductions'):
        for document in logistics.get(collection, []):
            if any(str(item.get('itemId', item.get('ingredientId', ''))) == identity
                   for item in [*document.get('items', []), *document.get('ingredientSnapshot', [])]):
                return 'Нельзя менять единицу измерения позиции из складских документов.'
    for sale in state.get('sales', []):
        for item in sale.get('items', []):
            if str(item.get('id', '')) == identity or any(str(row.get('itemId', row.get('ingredientId', ''))) == identity for row in [*item.get('ingredientAllocations', []), *item.get('modifierAllocations', [])]):
                return 'Нельзя менять единицу измерения позиции с историей продаж.'
    return ''


def loss_changes(state, ingredient, losses):
    """Keep required net quantities and yields; plan before mutating any recipe."""
    changes = []
    old_losses = ingredient.get('losses') if isinstance(ingredient.get('losses'), dict) else {}
    for item in [*state.get('recipes', []), *state.get('preparations', [])]:
        for component in item.get('components', []):
            method = component.get('method', 'none')
            if str(component.get('ingredientId', '')) != str(ingredient['id']) or not isinstance(method, str) or method not in losses:
                continue
            if float(old_losses.get(method, 0) or 0) == losses[method]:
                continue
            net = float(component.get('net', component.get('gross', 0)))
            gross = net / (1 - losses[method] / 100)
            if not isfinite(gross) or gross < 0:
                raise ValueError('Проверьте состав: невозможно пересчитать потери ингредиента')
            changes.append((component, gross))
    return changes
