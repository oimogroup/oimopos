"""Kitchen shifts with explicit opening/closing counts, separate from cash shifts."""
from uuid import uuid4
from . import custody
from .composition import produced_sources


def current(state, branch_id):
    return next((shift for shift in state['logisticsState'].get('productionShifts', []) if shift['branchId'] == branch_id and shift['status'] == 'open'), None)


def ingredient_stocks(state, branch_id):
    stock = state['logisticsState'].get('branchStocks', {}).get(branch_id, {})
    return sorted([{'id': str(item['id']), 'name': item['name'], 'unit': item.get('unit') or 'кг',
                    'quantity': float(stock.get(str(item['id']), stock.get(item['id'], 0)) or 0)}
                   for item in [*state.get('ingredients', []), *produced_sources(state)]], key=lambda item: item['name'].casefold())


def context(state, branch_id):
    rows = []
    recipes = {str(recipe['id']): recipe for recipe in state.get('recipes', [])}
    for batch in state['logisticsState'].get('batches', []):
        if batch.get('branchId') != branch_id or batch.get('status') == 'closed':
            continue
        balance = custody.kitchen_balance(batch)
        if balance > 0:
            rows.append({'batchId': batch['id'], 'number': batch['number'], 'name': recipes.get(str(batch['recipeId']), {}).get('name', 'Блюдо'), 'expectedWeight': balance})
    return {'shift': current(state, branch_id), 'counts': rows, 'ingredientStocks': ingredient_stocks(state, branch_id)}


def apply(state, user, action, payload):
    custody.require(action in {'production.shift.open', 'production.shift.close'}, 'Неизвестная операция смены', 422)
    branch_id = user.get('branch_id')
    custody.require(branch_id and user.get('staff_role') in {'production', 'branch_manager'}, 'Смена доступна сотруднику производства', 403)
    custody.require(user.get('plan_code') != 'restaurant', 'Смены производства доступны для столовой', 403)
    shifts = state['logisticsState'].setdefault('productionShifts', [])
    request_id = str(payload.get('requestId', '')).strip()
    custody.require(0 < len(request_id) <= 80, 'Не указан идентификатор операции', 422)
    key = 'openRequest' if action.endswith('open') else 'closeRequest'
    replay = next((shift for shift in shifts if shift.get(key, {}).get('requestId') == request_id and shift['branchId'] == branch_id), None)
    if replay:
        custody.require(replay[key]['payload'] == payload and replay[key]['actorId'] == user['id'], 'Запрос уже использован для другой операции')
        return 'production_shift', replay['id']
    active = current(state, branch_id)
    opening = action == 'production.shift.open'
    custody.require(not active if opening else bool(active), 'Смена уже открыта другим сотрудником' if opening else 'Смена уже закрыта')
    if not opening:
        custody.require(str(active['employeeId']) == str(user['id']), 'Закрыть смену должен принявший её сотрудник', 403)
    pending = [d for d in state['logisticsState'].get('custodyDocuments', []) if d.get('branchId') == branch_id and d.get('status') == 'pending' and (d.get('kind') == 'transfer' or (d.get('kind') == 'writeoff' and not d.get('lotId')))]
    custody.require(opening or not pending, 'Сначала завершите приёмку передач с кухни и рассмотрение списаний кухни')
    expected = context(state, branch_id)['counts']
    supplied = payload.get('counts', [])
    custody.require(isinstance(supplied, list) and len(supplied) == len(expected) and {r.get('batchId') for r in supplied} == {r['batchId'] for r in expected}, 'Остатки изменились. Обновите смену и повторите пересчёт')
    # Validate every row before mutating quantities.
    for row in expected:
        actual = next(r for r in supplied if r.get('batchId') == row['batchId'])
        custody.require(abs(custody.number(actual.get('expectedWeight')) - row['expectedWeight']) <= 1e-6, 'Остатки изменились. Повторите пересчёт')
        custody.require('actualWeight' in actual, 'Укажите фактический вес', 422)
        if abs(custody.number(actual['actualWeight']) - row['expectedWeight']) > 1e-6:
            custody.reason(actual)
    shift = {'id': 'kitchen-shift-'+str(uuid4()), 'branchId': branch_id, 'employeeId': user['id'], 'employeeName': user['display_name'], 'openedAt': custody.now(), 'status': 'open'} if opening else active
    from .shift_reconciliation import count_ingredients
    ingredient_facts = count_ingredients(state, user, payload.get('ingredientCounts'), 'opening' if opening else 'closing', shift['id'])
    facts = []
    for row in expected:
        actual = next(r for r in supplied if r['batchId'] == row['batchId'])
        batch = next(b for b in state['logisticsState']['batches'] if b['id'] == row['batchId'])
        previous = {'id': batch.get('kitchenResponsibleId', batch.get('createdById')), 'name': batch.get('kitchenResponsibleName', batch.get('createdBy'))}
        _, doc_id = custody.apply(state, {**user, '_production_shift_intake': True}, 'custody.count', {**actual, 'requestId': str(uuid4())})
        facts.append({**row, 'actualWeight': custody.number(actual['actualWeight']), 'reason': actual.get('reason', ''), 'previousResponsible': previous, 'documentId': doc_id})
        if opening:
            batch.update(kitchenResponsibleId=user['id'], kitchenResponsibleName=user['display_name'])
    shift['openingCounts' if opening else 'closingCounts'] = facts
    shift['openingIngredientStocks' if opening else 'closingIngredientStocks'] = ingredient_stocks(state, branch_id)
    shift['openingIngredientCounts' if opening else 'closingIngredientCounts'] = ingredient_facts
    shift[key] = {'requestId': request_id, 'payload': payload, 'actorId': user['id']}
    if opening:
        shift['acceptedBatches'] = []
        for batch in state['logisticsState']['batches']:
            if batch.get('branchId') == branch_id and batch.get('status') != 'closed':
                shift['acceptedBatches'].append(batch['id'])
                batch.update(kitchenResponsibleId=user['id'], kitchenResponsibleName=user['display_name'])
        shifts.insert(0, shift)
    else:
        shift.update(status='closed', closedAt=custody.now(), closedBy=custody.snapshot_actor(user))
    return 'production_shift', shift['id']
