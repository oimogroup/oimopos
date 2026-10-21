"""Accrual operating expenses and P&L. Cash payments never recognize a cost twice."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from . import payroll

D = lambda value: Decimal(str(value or 0))
require = payroll.require
money = payroll.money


def ensure(state):
    result = state.setdefault('pnlState', {})
    for key in ('expenses', 'payments', 'requests'):
        result.setdefault(key, [])
    return result


def paid(state, expense_id):
    return money(sum((D(p['amount']) for p in state.get('pnlState', {}).get('payments', []) if p['expenseId'] == expense_id and not p.get('reversedAt')), D(0)))


def local_day(state, value):
    text = str(value or '')
    return payroll.day(text) if len(text) == 10 else payroll.clock(text).astimezone(payroll.zone(state)).date()


def portion(entry, first, last):
    start, end = payroll.day(entry['start']), payroll.day(entry['end'])
    # Rounded cumulative allocation preserves every cent across consecutive periods.
    def through(day):
        days = max(0, min((day-start).days+1, (end-start).days+1))
        return D(money(D(entry['amount']) * days / ((end-start).days+1)))
    return through(last) - through(first-timedelta(days=1))


def report(state, start, end, branch_id=None):
    from .workspace import _ensure_finance, WorkspaceError
    from .company_settings import company_settings
    first, last = payroll.day(start), payroll.day(end)
    require(first <= last and (last-first).days <= 366, 'Выберите период до 367 дней')
    require(last <= payroll.today(state), 'P&L рассчитывается по сегодняшний день включительно')
    require(not branch_id or any(str(b['id']) == str(branch_id) for b in state.get('branches', [])), 'Заведение не найдено', 404)
    selected = lambda row: not branch_id or str(row.get('branchId')) == str(branch_id)
    within = lambda value: first <= local_day(state, value) <= last
    finance = _ensure_finance(deepcopy(state))
    categories = {c['id']: c['name'] for c in finance['categories']}
    revenue, cost = D(0), D(0)
    missing_cost, undated = set(), 0
    product_ids = {str(p['id']) for p in state.get('products', [])}
    for sale in state.get('sales', []):
        if not selected(sale):
            continue
        for field, sign in (('createdAt', 1), ('refundedAt', -1)):
            if not sale.get(field) or not within(sale[field]):
                continue
            revenue += D(sale.get('total')) * sign
            for item in sale.get('items', []):
                if item.get('unitCost') is None:
                    missing_cost.add(str(sale.get('id')))
                    continue
                unit = D(item.get('unitCost'))
                # Products are returned to inventory; consumed/prepared food is not.
                if sign == -1 and str(item.get('id')) not in product_ids and (item.get('ingredientAllocations') or any(a.get('lotId') and not str(a['lotId']).startswith('legacy-') for a in item.get('batchAllocations', []))):
                    unit = D(0)
                cost += unit * D(item.get('quantity')) * sign
    groups = {}
    add = lambda key, value: groups.__setitem__(key, groups.get(key, D(0)) + value)
    other_income = D(0)
    excluded_sources = {'payroll.pay', 'payroll.advance', 'payroll.reverse', 'pnl.pay', 'pnl.reverse'}
    for t in finance['transactions']:
        if not selected(t) or t.get('sourceType') in excluded_sources or t.get('affectsProfit') is False:
            continue
        if t.get('type') == 'transfer' or t.get('categoryId') in {'finance-expense-purchases', 'finance-income-supplier-refunds', 'finance-income-payroll-refunds'}:
            continue
        value = t.get('recognitionDate') or t.get('occurredAt')
        try:
            match = within(value)
        except WorkspaceError:
            undated += 1
            continue
        if not match:
            continue
        if t.get('type') == 'expense':
            add(t.get('categoryId'), D(t.get('amount')))
        elif t.get('type') == 'income':
            other_income += D(t.get('amount'))
    expense_docs = []
    all_expenses = state.get('pnlState', {}).get('expenses', [])
    for expense in all_expenses:
        if not selected(expense):
            continue
        value = portion(expense, first, last)
        if not expense.get('voidedAt'):
            add(expense['categoryId'], value)
        if payroll.day(expense['start']) <= last and payroll.day(expense['end']) >= first:
            expense_docs.append({**expense, 'paid': paid(state, expense['id']), 'recognized': money(value) if not expense.get('voidedAt') else 0})
    categories['pnl-stock-losses'] = 'Списания и недостачи'
    stock_review = False
    for row in state.get('logisticsState', {}).get('stockLedger', []):
        if row.get('movementType') != 'inventory_adjustment' or not selected(row) or not within(row.get('effectiveAt') or row.get('createdAt')):
            continue
        value = D(row.get('quantity')) * D(row.get('unitCost'))
        if value < 0:
            add('pnl-stock-losses', -value)
        else:
            other_income += value
    for doc in state.get('logisticsState', {}).get('custodyDocuments', []):
        if not selected(doc):
            continue
        kind, status = doc.get('kind'), doc.get('status')
        if kind == 'count' and status in {'review', 'approved', 'recorded'} and within(doc.get('createdAt')):
            value = D(doc.get('variance')) * D(doc.get('costPerKg'))
            stock_review |= status == 'review'
        elif kind in {'writeoff', 'surplus'} and status == 'approved' and within(doc.get('reviewedAt') or doc.get('createdAt')):
            value = D(doc.get('costAmount')) * (-1 if kind == 'writeoff' else 1)
        else:
            continue
        if value < 0:
            add('pnl-stock-losses', -value)
        else:
            other_income += value
    wages = payroll.report(state, start, end, branch_id=branch_id)
    manual_wages = groups.get('finance-expense-payroll', D(0))
    add('finance-expense-payroll', D(wages['total']))
    expenses = sum(groups.values(), D(0))
    warnings = []
    if any(r.get('status') != 'synced' and selected(r) and within(r['createdAt']) for r in state.get('offlinePos', {}).get('receipts', [])):
        warnings.append('Есть автономные чеки на проверке. Финансовый результат предварительный до их сверки.')
    if stock_review:
        warnings.append('Есть расхождения витрины на проверке. Их стоимость уже включена по фактическому пересчёту.')
    if missing_cost:
        warnings.append(f'В {len(missing_cost)} чеках нет сохранённой себестоимости. Прибыль предварительная; стоимость по текущим ценам не подставляется.')
    if wages['openShifts']:
        warnings.append('Есть открытые рабочие смены: оплата по часам и сменам ещё не полностью учтена.')
    if not state.get('payrollState', {}).get('policies'):
        warnings.append('Ставки зарплат ещё не настроены. Внесите зарплату вручную или настройте автоматический расчёт.')
    if manual_wages and wages['total']:
        warnings.append('Есть ручные расходы на зарплату вместе с автоматическим начислением. Проверьте, что это разные суммы; для повторной оплаты начисленной зарплаты отключите «Влияние на прибыль».')
    if branch_id and (any(not t.get('branchId') and t.get('type') != 'transfer' for t in finance['transactions']) or any(not e.get('branchId') and not e.get('voidedAt') for e in all_expenses)):
        warnings.append('Общие расходы компании показаны только в отчёте «Вся сеть» и не распределяются между заведениями автоматически.')
    if undated:
        warnings.append(f'Операций без корректной даты: {undated}. Исправьте их для полного расчёта.')
    return {'start': start, 'end': end, 'branchId': branch_id or 'all', 'currency': company_settings(state)['general']['currency'], 'revenue': money(revenue), 'cost': money(cost), 'gross': money(revenue-cost), 'otherIncome': money(other_income), 'expenses': money(expenses), 'net': money(revenue-cost+other_income-expenses), 'margin': money((revenue-cost+other_income-expenses)/revenue*100) if revenue > 0 else None, 'expenseGroups': [{'id': key, 'name': categories.get(key, 'Без категории'), 'amount': money(value)} for key, value in sorted(groups.items(), key=lambda row: str(row[0])) if value], 'documents': list(reversed(expense_docs)), 'payments': [p for p in state.get('pnlState', {}).get('payments', []) if any(e['id'] == p['expenseId'] for e in expense_docs)], 'warnings': warnings, 'categories': [c for c in finance['categories'] if c['kind'] == 'expense' and c.get('status') == 'active' and c['id'] not in {'finance-expense-payroll', 'finance-expense-purchases'}], 'accounts': [a for a in finance['accounts'] if a.get('status') == 'active' and a['type'] in {'bank', 'safe'}], 'companyToday': payroll.today(state).isoformat()}


def apply(state, user, action, payload):
    require(user.get('role') == 'owner', 'P&L доступен только владельцу компании', 403)
    request_id = str(payload.get('requestId') or '')
    require(0 < len(request_id) <= 200, 'Не указан идентификатор операции')
    old = next((r for r in state.get('pnlState', {}).get('requests', []) if r['id'] == request_id), None)
    if old:
        require(old['actor'] == user['id'] and old['action'] == action and old['payload'] == payload, 'Идентификатор использован для другой операции', 409)
        return old['entityType'], old['entityId']
    candidate = deepcopy(state)
    result = _apply(candidate, user, action, payload)
    ensure(candidate)['requests'].append({'id': request_id, 'actor': user['id'], 'action': action, 'payload': deepcopy(payload), 'entityType': result[0], 'entityId': result[1]})
    state.clear()
    state.update(candidate)
    return result


def _apply(state, user, action, payload):
    from .workspace import _ensure_finance, _next_number
    data, finance = ensure(state), _ensure_finance(state)
    stamp = payroll.now().isoformat()
    reason = str(payload.get('reason') or '').strip()
    require(3 <= len(reason) <= 1000, 'Укажите основание от 3 до 1000 символов')
    if action == 'pnl.expense.create':
        first, last = payroll.day(payload.get('start')), payroll.day(payload.get('end'))
        require(first <= last and (last-first).days <= 366, 'Укажите период расхода до 367 дней')
        category = next((c for c in finance['categories'] if c['id'] == payload.get('categoryId') and c['kind'] == 'expense' and c.get('status') == 'active'), None)
        require(category and category['id'] not in {'finance-expense-purchases', 'finance-expense-payroll'}, 'Выберите статью расхода. Зарплата учитывается в разделе «Зарплата», запасы — в поставках.')
        branch = str(payload.get('branchId') or '') or None
        require(not branch or any(str(b['id']) == branch for b in state.get('branches', [])), 'Заведение не найдено', 404)
        amount = payroll.amount(payload.get('amount'))
        require(amount > 0, 'Сумма должна быть положительной')
        entry = {'id': f'pnl-expense-{uuid4()}', 'start': first.isoformat(), 'end': last.isoformat(), 'amount': money(amount), 'categoryId': category['id'], 'branchId': branch, 'reason': reason, 'createdAt': stamp, 'createdById': user['id']}
        data['expenses'].append(entry)
        return 'pnl_expense', entry['id']
    expense = next((e for e in data['expenses'] if e['id'] == payload.get('expenseId')), None)
    require(expense and not expense.get('voidedAt'), 'Расход не найден или отменён', 404)
    if action == 'pnl.expense.void':
        require(paid(state, expense['id']) == 0, 'Сначала отмените выплаты по расходу', 409)
        expense.update(voidedAt=stamp, voidedById=user['id'], voidReason=reason)
        return 'pnl_expense', expense['id']
    require(action in {'pnl.pay', 'pnl.reverse'}, 'Неизвестная операция P&L', 404)
    account = next((a for a in finance['accounts'] if a['id'] == payload.get('accountId') and a.get('status') == 'active' and a['type'] in {'bank', 'safe'}), None)
    require(account, 'Выберите банковский счёт или сейф')
    require(not account.get('branchId') or str(account['branchId']) == str(expense.get('branchId')), 'Счёт относится к другому заведению')
    if action == 'pnl.pay':
        value = payroll.amount(payload.get('amount'))
        require(0 < value <= D(expense['amount'])-D(paid(state, expense['id'])), 'Сумма превышает неоплаченный остаток', 409)
        payment = {'id': f'pnl-payment-{uuid4()}', 'expenseId': expense['id'], 'amount': money(value), 'accountId': account['id'], 'createdAt': stamp, 'createdById': user['id'], 'reason': reason}
        data['payments'].append(payment)
        kind = 'expense'
    else:
        payment = next((p for p in data['payments'] if p['id'] == payload.get('paymentId') and p['expenseId'] == expense['id']), None)
        require(payment and not payment.get('reversedAt'), 'Оплата уже отменена или не найдена', 409)
        value = D(payment['amount'])
        payment.update(reversedAt=stamp, reversedById=user['id'], reversalReason=reason)
        kind = 'income'
    finance['transactions'].insert(0, {'id': f'finance-transaction-{uuid4()}', 'number': _next_number('РС', finance['transactions']), 'type': kind, 'amount': money(value), 'occurredAt': stamp, 'accountId': account['id'], 'destinationAccountId': None, 'categoryId': expense['categoryId'] if kind == 'expense' else 'finance-income-other', 'branchId': expense['branchId'], 'counterparty': expense['reason'], 'comment': reason, 'automatic': True, 'sourceType': action, 'sourceId': payment['id'], 'documentId': expense['id'], 'createdAt': stamp, 'createdBy': user['display_name']})
    return 'pnl_payment', payment['id']
