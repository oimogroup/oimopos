"""Operational payroll: dated rates, explicit work time, immutable periods and money documents."""
import calendar
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4
from zoneinfo import ZoneInfo


def now():
    return datetime.now(timezone.utc)


def require(ok, message, status=422):
    from .workspace import WorkspaceError
    if not ok:
        raise WorkspaceError(message, status)


def amount(value, *, signed=False, percent=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        require(False, 'Укажите корректную сумму или процент')
    require(result.is_finite() and abs(result) <= (100 if percent else 999999999), 'Сумма или процент вне допустимого диапазона')
    require(signed or result >= 0, 'Значение не может быть отрицательным')
    require(result == result.quantize(Decimal('.01')), 'Укажите не более двух знаков после запятой')
    return result


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def clock(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        require(result.tzinfo is not None, 'Укажите время с часовым поясом')
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        require(False, 'Некорректная дата и время')


def day(value):
    try:
        result = date.fromisoformat(str(value))
        require(result.isoformat() == value, 'Укажите дату в формате ГГГГ-ММ-ДД')
        return result
    except (ValueError, TypeError):
        require(False, 'Некорректная дата')


def zone(state):
    from .company_settings import company_settings
    return ZoneInfo(company_settings(state)['general']['timezone'])


def today(state):
    return now().astimezone(zone(state)).date()


def data(state):
    return state.get('payrollState', {})


def ensure(state):
    payroll = state.setdefault('payrollState', {})
    for key in ('policies', 'workShifts', 'events', 'runs', 'payments', 'requests'):
        payroll.setdefault(key, [])
    return payroll


def policy_at(state, employee_id, at):
    ended = data(state).get('employmentEnds', {}).get(str(employee_id))
    if ended and at > day(ended):
        return None
    candidates = [p for p in data(state).get('policies', []) if str(p['employeeId']) == str(employee_id) and day(p['effectiveFrom']) <= at]
    return max(candidates, key=lambda p: (p['effectiveFrom'], p['sequence'])) if candidates else None


def current_shift(state, employee_id):
    return next((s for s in data(state).get('workShifts', []) if str(s['employeeId']) == str(employee_id) and not s.get('closedAt')), None)


def assert_open_period(state, start, end):
    require(not any(day(r['start']) <= end and day(r['end']) >= start for r in data(state).get('runs', [])), 'Период уже начислен. Используйте корректировку в открытом периоде.', 409)


def _percent_base(sale):
    items = sale.get('items', [])
    values = [Decimal(str(i['price'])) * Decimal(str(i['quantity'])) for i in items]
    discountable = sum((v for i, v in zip(items, values) if not i.get('noDiscount')), Decimal(0))
    discount = Decimal(str(sale.get('discountAmount', 0)))
    net = [v - (discount * v / discountable if not i.get('noDiscount') and discountable else 0) for i, v in zip(items, values)]
    target = Decimal(str(sale.get('subtotal', sum(values)))) - discount
    total = sum(net, Decimal(0))
    return [(str(i.get('category', '')), v * target / total if total else Decimal(0)) for i, v in zip(items, net)]


def record_sale(state, sale, owner_id):
    if not data(state).get('policies'):
        return
    payroll = ensure(state)
    at = clock(sale['createdAt'])
    on = at.astimezone(zone(state)).date()
    shifts = [s for s in payroll['workShifts'] if s['branchId'] == sale['branchId'] and clock(s['openedAt']) <= at and (not s.get('closedAt') or clock(s['closedAt']) > at)]
    workers = {str(owner_id)} | {str(s['employeeId']) for s in shifts}
    bases = _percent_base(sale)
    accruals = []
    for employee in sorted(workers):
        policy = policy_at(state, employee, on)
        if not policy:
            continue
        personal = Decimal(0)
        common = Decimal(0)
        in_shift = any(str(s['employeeId']) == employee for s in shifts)
        for category, base in bases:
            overrides = policy.get('categoryRates', {}).get(category, {})
            if employee == str(owner_id):
                personal += base * Decimal(str(overrides.get('personal', policy['personalPercent']))) / 100
            if in_shift:
                common += base * Decimal(str(overrides.get('shift', policy['shiftPercent']))) / 100
        service = Decimal(str(sale.get('serviceAmount', 0))) * Decimal(str(policy['servicePercent'])) / 100 if employee == str(owner_id) else Decimal(0)
        total = money(personal + common + service)
        if total:
            entry = {'id': f"earning-{sale['id']}-{employee}", 'employeeId': employee, 'employeeName': policy['employeeName'], 'branchId': sale['branchId'], 'date': on.isoformat(), 'occurredAt': sale['createdAt'], 'type': 'sales', 'saleId': sale['id'], 'policyId': policy['id'], 'personal': money(personal), 'shift': money(common), 'service': money(service), 'amount': total}
            payroll['events'].append(entry)
            accruals.append(deepcopy(entry))
    sale['payrollAccruals'] = accruals
    sale['orderOwnerId'] = owner_id


def record_refund(state, sale):
    if not sale.get('payrollAccruals'):
        return
    payroll = ensure(state)
    on = clock(sale['refundedAt']).astimezone(zone(state)).date().isoformat()
    for original in sale['payrollAccruals']:
        payroll['events'].append({**deepcopy(original), 'id': f"refund-{original['id']}", 'type': 'refund', 'date': on, 'occurredAt': sale['refundedAt'], **{key: -original[key] for key in ('personal', 'shift', 'service', 'amount')}})


def _employee(state, user, identifier):
    match = next((e for e in user.get('_payroll_employees', []) if str(e['id']) == str(identifier)), None)
    require(match and match.get('is_active') and not match.get('deleted_at'), 'Выберите действующего сотрудника вашей компании', 403)
    return match


def report(state, start, end, employees=(), branch_id=None):
    first, last = day(start), day(end)
    require(first <= last and (last-first).days <= 366, 'Выберите период до 367 дней')
    payroll = data(state)
    roster = {str(e['id']): {'employeeId': str(e['id']), 'employeeName': e['display_name'], 'staffRole': e.get('staff_role'), 'branchId': e.get('branch_id')} for e in employees}
    for p in payroll.get('policies', []):
        roster.setdefault(str(p['employeeId']), {key: p.get(key) for key in ('employeeId', 'employeeName', 'staffRole', 'branchId')})
    for event in payroll.get('events', []):
        roster.setdefault(str(event['employeeId']), {'employeeId': str(event['employeeId']), 'employeeName': event['employeeName']})
    rows = []
    for employee, meta in roster.items():
        fixed = Decimal(0)
        seconds = Decimal(0)
        shift_count = 0
        on = first
        while on <= last:
            policy = policy_at(state, employee, on)
            if policy and policy['fixedMode'] == 'month' and (not branch_id or str(policy.get('branchId')) == str(branch_id)):
                fixed += Decimal(str(policy['fixedAmount'])) / calendar.monthrange(on.year, on.month)[1]
            on += timedelta(days=1)
        for shift in payroll.get('workShifts', []):
            if str(shift['employeeId']) != employee or not shift.get('closedAt') or (branch_id and str(shift.get('branchId')) != str(branch_id)):
                continue
            opened, closed = clock(shift['openedAt']), clock(shift['closedAt'])
            opening_day = opened.astimezone(zone(state)).date()
            if first <= opening_day <= last:
                shift_count += 1
                policy = policy_at(state, employee, opening_day)
                if policy and policy['fixedMode'] == 'shift':
                    fixed += Decimal(str(policy['fixedAmount']))
            on = max(first, opening_day)
            while on <= min(last, closed.astimezone(zone(state)).date()):
                begin = datetime.combine(on, time.min, zone(state)).astimezone(timezone.utc)
                finish = datetime.combine(on+timedelta(days=1), time.min, zone(state)).astimezone(timezone.utc)
                elapsed = max(0, (min(closed, finish)-max(opened, begin)).total_seconds())
                seconds += Decimal(str(elapsed))
                policy = policy_at(state, employee, on)
                if policy and policy['fixedMode'] == 'hour':
                    fixed += Decimal(str(policy['fixedAmount'])) * Decimal(str(elapsed)) / 3600
                on += timedelta(days=1)
        events = [e for e in payroll.get('events', []) if str(e['employeeId']) == employee and first <= day(e['date']) <= last and (not branch_id or str(e.get('branchId')) == str(branch_id))]
        commission = sum((Decimal(str(e['amount'])) for e in events if e['type'] != 'adjustment'), Decimal(0))
        adjustment = sum((Decimal(str(e['amount'])) for e in events if e['type'] == 'adjustment'), Decimal(0))
        rows.append({**meta, 'hours': float(seconds/3600), 'shifts': shift_count, 'fixed': money(fixed), 'commission': money(commission), 'adjustment': money(adjustment), 'total': money(Decimal(str(money(fixed))) + commission + adjustment)})
    return {'start': start, 'end': end, 'rows': sorted(rows, key=lambda e: e['employeeName'].casefold()), 'total': money(sum((Decimal(str(e['total'])) for e in rows), Decimal(0))), 'openShifts': [s for s in payroll.get('workShifts', []) if not s.get('closedAt') and clock(s['openedAt']).astimezone(zone(state)).date() <= last and (not branch_id or str(s.get('branchId')) == str(branch_id))]}


def balances(state):
    payroll = data(state)
    result = {}
    for run in payroll.get('runs', []):
        for row in run['rows']:
            key = str(row['employeeId'])
            result[key] = result.get(key, Decimal(0)) + Decimal(str(row['total']))
    for payment in payroll.get('payments', []):
        if not payment.get('reversedAt'):
            key = str(payment['employeeId'])
            result[key] = result.get(key, Decimal(0)) - Decimal(str(payment['amount']))
    return {key: money(value) for key, value in result.items()}


def run_paid(state, run_id, employee_id):
    return money(sum((Decimal(str(a['amount'])) for p in data(state).get('payments', []) if str(p['employeeId']) == str(employee_id) and not p.get('reversedAt') for a in p.get('allocations', []) if a['runId'] == run_id), Decimal(0)))


def apply(state, user, action, payload):
    if action.startswith('payroll.'):
        require(user.get('role') == 'owner', 'Зарплата доступна только владельцу компании', 403)
    else:
        require(user.get('register_id') and user.get('id'), 'Рабочее время отмечается сотрудником по личному PIN', 403)
    request_id = str(payload.get('requestId') or '').strip()
    require(0 < len(request_id) <= 200, 'Не указан идентификатор операции')
    previous = next((r for r in data(state).get('requests', []) if r['requestId'] == request_id), None)
    if previous:
        require(previous['action'] == action and str(previous['actorId']) == str(user['id']) and previous['payload'] == payload, 'Идентификатор использован для другой операции', 409)
        return previous['entityType'], previous['entityId']
    expected = payload.get('expectedVersion')
    if action == 'payroll.approve' or (action == 'payroll.time' and payload.get('id')):
        require(isinstance(expected, int) and expected == user.get('_workspace_version'), 'Данные изменились. Обновите расчёт перед начислением.', 409)
    candidate = deepcopy(state)
    entity_type, entity_id = _apply(candidate, user, action, payload)
    ensure(candidate)['requests'].append({'requestId': request_id, 'action': action, 'actorId': user['id'], 'payload': deepcopy(payload), 'entityType': entity_type, 'entityId': entity_id})
    state.clear()
    state.update(candidate)
    return entity_type, entity_id


def _apply(state, user, action, payload):
    payroll = ensure(state)
    timestamp = now().isoformat()
    from .company_settings import company_settings
    currency = company_settings(state)['general']['currency']
    if action == 'payroll.policy':
        employee = _employee(state, user, payload.get('employeeId'))
        effective = day(payload.get('effectiveFrom'))
        require(effective >= today(state), 'Ставка меняется с сегодняшнего дня или будущей даты')
        assert_open_period(state, effective, effective)
        mode = payload.get('fixedMode', 'none')
        require(mode in {'none', 'hour', 'shift', 'month'}, 'Выберите способ начисления ставки')
        rates = {k: money(amount(payload.get(k, 0), percent=True)) for k in ('personalPercent', 'shiftPercent', 'servicePercent')}
        category_rates = payload.get('categoryRates', {})
        require(isinstance(category_rates, dict) and len(category_rates) <= 100, 'Проверьте ставки категорий')
        known = {str(i.get('category', '')) for key in ('products', 'recipes') for i in state.get(key, [])}
        overrides = {}
        for name, values in category_rates.items():
            require(name in known and isinstance(values, dict) and set(values) <= {'personal', 'shift'}, 'Выберите существующую категорию и процент')
            overrides[name] = {k: money(amount(v, percent=True)) for k, v in values.items()}
        entry = {'id': f'pay-policy-{uuid4()}', 'sequence': len(payroll['policies'])+1, 'employeeId': str(employee['id']), 'employeeName': employee['display_name'], 'staffRole': employee.get('staff_role'), 'branchId': employee.get('branch_id'), 'effectiveFrom': effective.isoformat(), 'fixedMode': mode, 'fixedAmount': money(amount(payload.get('fixedAmount', 0))), **rates, 'categoryRates': overrides, 'createdAt': timestamp, 'createdById': user['id'], 'currency': currency}
        payroll['policies'].append(entry)
        return 'payroll_policy', entry['id']
    if action in {'work.shift.open', 'work.shift.close'}:
        active = current_shift(state, user['id'])
        if action.endswith('open'):
            require(not active, 'Рабочая смена уже открыта', 409)
            entry = {'id': f'work-shift-{uuid4()}', 'employeeId': str(user['id']), 'employeeName': user['display_name'], 'branchId': user['branch_id'], 'openedAt': timestamp, 'closedAt': None, 'source': 'employee'}
            payroll['workShifts'].append(entry)
            return 'work_shift', entry['id']
        require(active and active['branchId'] == user['branch_id'], 'На этой точке нет открытой рабочей смены', 409)
        require(clock(timestamp) > clock(active['openedAt']), 'Проверьте время окончания')
        assert_open_period(state, clock(active['openedAt']).astimezone(zone(state)).date(), today(state))
        active['closedAt'] = timestamp
        return 'work_shift', active['id']
    if action == 'payroll.time':
        employee = _employee(state, user, payload.get('employeeId'))
        start, end = clock(payload.get('openedAt')), clock(payload.get('closedAt'))
        require(start < end <= now() and end-start <= timedelta(hours=48), 'Смена должна быть завершённой, не длиннее 48 часов')
        require(len(str(payload.get('reason', '')).strip()) >= 3, 'Укажите основание ручной отметки')
        assert_open_period(state, start.astimezone(zone(state)).date(), end.astimezone(zone(state)).date())
        require(not any(str(s['employeeId']) == str(employee['id']) and s['id'] != payload.get('id') and start < (clock(s['closedAt']) if s.get('closedAt') else now()) and end > clock(s['openedAt']) for s in payroll['workShifts']), 'Рабочие смены сотрудника пересекаются', 409)
        entry = {'id': f'work-shift-{uuid4()}', 'employeeId': str(employee['id']), 'employeeName': employee['display_name'], 'branchId': employee['branch_id'], 'openedAt': start.isoformat(), 'closedAt': end.isoformat(), 'source': 'owner', 'reason': str(payload['reason']).strip()[:1000], 'createdAt': timestamp, 'createdById': user['id']}
        target = next((s for s in payroll['workShifts'] if s['id'] == payload.get('id')), None)
        if payload.get('id'):
            require(target and str(target['employeeId']) == str(employee['id']), 'Рабочая смена не найдена', 404)
            assert_open_period(state, clock(target['openedAt']).astimezone(zone(state)).date(), clock(target.get('closedAt') or timestamp).astimezone(zone(state)).date())
            target.setdefault('corrections', []).append({'openedAt': target['openedAt'], 'closedAt': target.get('closedAt'), 'changedAt': timestamp, 'changedById': user['id'], 'reason': entry['reason']})
            target.update(openedAt=entry['openedAt'], closedAt=entry['closedAt'])
            return 'work_shift', target['id']
        payroll['workShifts'].append(entry)
        return 'work_shift', entry['id']
    if action == 'payroll.adjust':
        employee = _employee(state, user, payload.get('employeeId'))
        on = day(payload.get('date'))
        require(on <= today(state), 'Корректировка не может быть в будущем')
        assert_open_period(state, on, on)
        value = amount(payload.get('amount'), signed=True)
        require(value != 0 and 3 <= len(str(payload.get('reason', '')).strip()) <= 1000, 'Укажите ненулевую сумму и основание корректировки')
        entry = {'id': f'pay-adjustment-{uuid4()}', 'employeeId': str(employee['id']), 'employeeName': employee['display_name'], 'branchId': employee['branch_id'], 'date': on.isoformat(), 'occurredAt': timestamp, 'type': 'adjustment', 'amount': money(value), 'reason': str(payload['reason']).strip(), 'createdById': user['id']}
        payroll['events'].append(entry)
        return 'payroll_adjustment', entry['id']
    if action == 'payroll.approve':
        first, last = day(payload.get('start')), day(payload.get('end'))
        require(last < today(state), 'Начисляйте только завершённые календарные дни')
        assert_open_period(state, first, last)
        calculated = report(state, first.isoformat(), last.isoformat(), user.get('_payroll_employees', []))
        require(not calculated['openShifts'], 'Сначала закройте рабочие смены, затрагивающие период', 409)
        require(any(row['total'] for row in calculated['rows']), 'За период нет начислений')
        entry = {**calculated, 'id': f'payroll-run-{uuid4()}', 'currency': currency, 'timezone': str(zone(state)), 'createdAt': timestamp, 'createdById': user['id']}
        payroll['runs'].append(entry)
        # Existing advances reduce amounts due without creating another financial expense.
        for row in entry['rows']:
            remaining = max(Decimal(0), Decimal(str(row['total'])))
            for payment in payroll['payments']:
                available = Decimal(str(payment.get('unallocatedAmount', 0)))
                if payment.get('reversedAt') or str(payment['employeeId']) != str(row['employeeId']) or available <= 0:
                    continue
                applied = min(remaining, available)
                if applied:
                    payment['allocations'].append({'runId': entry['id'], 'amount': money(applied)})
                    payment['unallocatedAmount'] = money(available-applied)
                    remaining -= applied
        return 'payroll_run', entry['id']
    if action in {'payroll.pay', 'payroll.advance', 'payroll.reverse'}:
        from .workspace import _ensure_finance, _next_number
        finance = _ensure_finance(state)
        account = next((a for a in finance['accounts'] if a['id'] == payload.get('accountId')), None)
        require(account and account.get('status') == 'active' and account.get('type') in {'bank', 'safe'}, 'Выберите действующий банковский счёт или сейф. Выплату из кассового ящика оформляйте отдельно.')
        reason = str(payload.get('reason', '')).strip()
        require(3 <= len(reason) <= 1000, 'Укажите основание выплаты или отмены')
        if action == 'payroll.reverse':
            payment = next((p for p in payroll['payments'] if p['id'] == payload.get('paymentId')), None)
            require(payment and not payment.get('reversedAt'), 'Выплата уже отменена или не найдена', 409)
            require(payment['currency'] == currency, 'Валюта выплаты отличается от валюты компании')
            value = Decimal(str(payment['amount']))
            payment.update(reversedAt=timestamp, reversedById=user['id'], reversalReason=reason)
            entity_id = payment['id']
            kind, category = 'income', 'finance-income-payroll-refunds'
        else:
            value = amount(payload.get('amount'))
            require(value > 0, 'Сумма выплаты должна быть положительной')
            employee_id = str(payload.get('employeeId'))
            if action == 'payroll.pay':
                run = next((r for r in payroll['runs'] if r['id'] == payload.get('runId')), None)
                row = next((r for r in run['rows'] if str(r['employeeId']) == employee_id), None) if run else None
                require(row and run['currency'] == currency, 'Сотрудник или ведомость не найдены')
                due = Decimal(str(row['total']))-Decimal(str(run_paid(state, run['id'], employee_id)))
                require(value <= due and value <= Decimal(str(balances(state).get(employee_id, 0))), 'Сумма превышает задолженность с учётом всех выплат и корректировок', 409)
                employee_name = row['employeeName']
            else:
                employee = _employee(state, user, employee_id)
                employee_name = employee['display_name']
            payment = {'id': f'payroll-payment-{uuid4()}', 'employeeId': employee_id, 'employeeName': employee_name, 'amount': money(value), 'currency': currency, 'accountId': account['id'], 'occurredAt': timestamp, 'reason': reason, 'createdById': user['id'], 'unallocatedAmount': money(value) if action == 'payroll.advance' else 0, 'allocations': [] if action == 'payroll.advance' else [{'runId': run['id'], 'amount': money(value)}]}
            payroll['payments'].append(payment)
            entity_id = payment['id']
            kind, category = 'expense', 'finance-expense-payroll'
        if not any(c['id'] == category for c in finance['categories']):
            finance['categories'].append({'id': category, 'name': 'Возвраты выплат сотрудникам', 'kind': kind, 'status': 'active'})
        finance['transactions'].insert(0, {'id': f'finance-transaction-{uuid4()}', 'number': _next_number('ЗП', finance['transactions']), 'type': kind, 'amount': money(value), 'occurredAt': timestamp, 'accountId': account['id'], 'destinationAccountId': None, 'categoryId': category, 'branchId': account.get('branchId'), 'counterparty': payment['employeeName'], 'comment': reason, 'createdAt': timestamp, 'createdBy': user['display_name'], 'automatic': True, 'documentId': entity_id, 'sourceType': action, 'sourceId': entity_id})
        return 'payroll_payment', entity_id
    require(False, 'Неизвестная операция зарплаты', 404)


def stop_employee(state, employee_id):
    if not any(str(p['employeeId']) == str(employee_id) for p in data(state).get('policies', [])):
        return
    ensure(state).setdefault('employmentEnds', {})[str(employee_id)] = today(state).isoformat()
