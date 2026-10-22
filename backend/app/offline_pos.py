"""Register-scoped offline cash receipts, frozen prices and explicit reconciliation."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import secrets
from uuid import uuid4

from . import payroll
from .workspace import WorkspaceError, apply_action, sale_replay, visible_state


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def ensure(state):
    data = state.setdefault('offlinePos', {})
    data.setdefault('leases', [])
    data.setdefault('receipts', [])
    return data


def issue(state, terminal, operator, shift, existing_token=''):
    from .company_settings import company_settings
    from .main import _has_permission
    payroll.require(shift and not shift.get('closed_at'), 'Для автономной работы сначала откройте кассовую смену', 409)
    payroll.require(operator.get('staff_role') != 'production' and _has_permission(operator, 'posAccess'), 'Автономные продажи недоступны этому сотруднику', 403)
    payroll.require(str(operator.get('branch_id')) == str(terminal['branch_id']), 'Сотрудник относится к другому заведению', 403)
    settings = company_settings(state)
    payroll.require(settings['security']['closeReceipt'] != 'always' or operator.get('staff_role') in {'branch_manager', 'hall_admin'}, 'Для автономных продаж этому сотруднику требуется подтверждение руководителя', 403)
    token = secrets.token_urlsafe(32)
    catalog = {key: deepcopy(state.get(key, [])) for key in ('products', 'recipes', 'preparations', 'ingredients', 'stations')}
    for rows in catalog.values():
        for row in rows:
            row.pop('image', None)
    catalog['companySettings'] = deepcopy(state.get('companySettings', {}))
    expires=payroll.now()+timedelta(hours=24)
    end=terminal.get('trial_ends_at') if terminal.get('subscription_status')=='trialing' else terminal.get('current_period_ends_at')
    if end: expires=min(expires,payroll.clock(end.isoformat() if hasattr(end,'isoformat') else end))
    previous = next((g for g in state.get('offlinePos', {}).get('leases', []) if g['tokenHash'] == digest(existing_token)), None) if existing_token else None
    if previous and previous['tenantId'] == str(terminal['tenant_id']) and str(previous['registerId']) == str(terminal['id']) and previous['operator'] == {k:operator.get(k) for k in ('id','login','display_name','staff_role','access_permissions','account_version')} and previous['shiftId'] == shift['id'] and previous['branchId'] == str(terminal['branch_id']) and previous.get('planCode') == terminal.get('plan_code') and previous['catalog'] == catalog and payroll.now()+timedelta(hours=1) < payroll.clock(previous['expiresAt']) <= expires:
        return {'token':existing_token, 'id':previous['id'], 'issuedAt':previous['issuedAt'], 'expiresAt':previous['expiresAt'], 'shiftId':previous['shiftId'], 'registerId':previous['registerId'], 'operatorId':operator['id']}
    lease = {'id': str(uuid4()), 'tokenHash': digest(token), 'tenantId': str(terminal['tenant_id']), 'registerId': terminal['id'], 'branchId': str(terminal['branch_id']), 'operator': {k: operator.get(k) for k in ('id', 'login', 'display_name', 'staff_role', 'access_permissions', 'account_version')}, 'shiftId': shift['id'], 'planCode':terminal.get('plan_code'), 'issuedAt': payroll.now().isoformat(), 'expiresAt': expires.isoformat(), 'catalog': catalog}
    ensure(state)['leases'].append(lease)
    return {'token': token, 'id': lease['id'], 'issuedAt': lease['issuedAt'], 'expiresAt': lease['expiresAt'], 'shiftId': lease['shiftId'], 'registerId': lease['registerId'], 'operatorId': operator['id']}


def _identity(lease):
    return {'role': 'branch', **lease['operator'], 'branch_id': lease['branchId'], 'register_id': lease['registerId'], 'shift_id': lease['shiftId'], 'plan_code':lease.get('planCode')}


def _validate_receipt(lease, receipt):
    p = receipt.get('payload')
    payroll.require(isinstance(p, dict), 'Некорректный чек')
    request_id = p.get('requestId')
    payroll.require(isinstance(request_id, str) and 8 <= len(request_id) <= 80, 'Некорректный идентификатор чека')
    payroll.require(not p.get('openOrderId') and not p.get('customerId') and not p.get('discountPercent'), 'Офлайн доступны новые заказы без персональных скидок')
    payroll.require(p.get('orderType', 'dine-in') in {'dine-in', 'takeaway'}, 'Доставка требует связи с сервером')
    payroll.require(isinstance(p.get('items'), list) and 0 < len(p['items']) <= 100, 'Проверьте позиции чека')
    payments = p.get('payments')
    payroll.require(isinstance(payments, list) and len(payments) == 1 and payments[0].get('method') == 'cash', 'Автономно поддерживается оплата наличными')
    expected = payroll.amount(receipt.get('total'))
    payroll.require(expected > 0, 'Сумма чека должна быть положительной')
    at = payroll.clock(receipt.get('createdAt'))
    payroll.require(payroll.clock(lease['issuedAt'])-timedelta(minutes=2) <= at <= payroll.clock(lease['expiresAt']), 'Чек создан вне срока автономного доступа')
    payroll.require(at <= payroll.now()+timedelta(minutes=2), 'Дата чека находится в будущем')
    return p


def _post(state, lease, receipt, shift_id=None, reviewed=False):
    """Calculate using server-held historical prices, deduct current real stock atomically."""
    actor = _identity(lease)
    if shift_id:
        actor['shift_id'] = shift_id
    payload = receipt['payload']
    existing = sale_replay(state, actor, payload)
    if existing:
        payroll.require(Decimal(str(existing['total'])) == Decimal(str(receipt['total'])), 'Серверный чек найден, но сумма отличается. Требуется проверка владельца.', 409)
        return deepcopy(state), existing['id']
    if not reviewed:
        for inventory in state.get('logisticsState', {}).get('inventories', []):
            if inventory.get('branchId') == lease['branchId'] and inventory.get('status') == 'posted' and inventory.get('postedAt') and payroll.clock(inventory['postedAt']) > payroll.clock(lease['issuedAt']):
                counted = inventory.get('countedAt') or inventory.get('createdAt')
                payroll.require(not counted or payroll.clock(counted) < payroll.clock(receipt['createdAt']), 'После автономной продажи проведена инвентаризация. Проверьте, не учтён ли уже расход в фактическом остатке.', 409)
    draft = deepcopy(state)
    original = {key: deepcopy(draft.get(key)) for key in lease['catalog']}
    for key, value in lease['catalog'].items():
        draft[key] = deepcopy(value)
    # Timestamp is an internal grant-validated value, never accepted by normal sale.create.
    actor['_offline_created_at'] = receipt['createdAt']
    _, identifier = apply_action(draft, actor, 'sale.create', deepcopy(payload))
    sale = next(s for s in draft['sales'] if s['id'] == identifier)
    payroll.require(Decimal(str(sale['total'])) == Decimal(str(receipt['total'])), 'Сумма автономного чека не совпадает с сохранёнными ценами', 409)
    sale.update(offline=True, offlineNumber='Л-'+payload['requestId'], offlineLeaseId=lease['id'], syncedAt=payroll.now().isoformat(), originalShiftId=lease['shiftId'])
    for event in draft.get('payrollState', {}).get('events', []):
        if event.get('saleId') == identifier and any(r['start'] <= event['date'] <= r['end'] for r in draft['payrollState'].get('runs', [])):
            event.update(date=payroll.today(draft).isoformat(), reason='Поздняя синхронизация автономного чека', originalDate=event['date'])
    original_ids = {row['id'] for row in state.get('logisticsState', {}).get('stockLedger', [])}
    for row in draft.get('logisticsState', {}).get('stockLedger', []):
        if row['id'] not in original_ids:
            row['effectiveAt'] = receipt['createdAt']
    for key, value in original.items():
        if value is None:
            draft.pop(key, None)
        else:
            draft[key] = value
    return draft, identifier


def receive(state, terminal, receipt, employee_active=True, shift_open=True):
    payroll.require(isinstance(receipt, dict), 'Некорректный чек')
    token = str(receipt.get('token') or '')
    payroll.require(len(token) <= 100, 'Некорректный доступ')
    lease = next((g for g in ensure(state)['leases'] if secrets.compare_digest(g['tokenHash'], digest(token))), None)
    payroll.require(lease and lease['tenantId'] == str(terminal['tenant_id']) and str(lease['registerId']) == str(terminal['id']) and lease['branchId'] == str(terminal['branch_id']), 'Автономный доступ принадлежит другой кассе', 403)
    payload = _validate_receipt(lease, receipt)
    fingerprint = digest(json.dumps({key: receipt.get(key) for key in ('payload', 'createdAt', 'total')}, sort_keys=True, ensure_ascii=False))
    previous = next((r for r in ensure(state)['receipts'] if r['requestId'] == payload['requestId']), None)
    if previous:
        payroll.require(previous['fingerprint'] == fingerprint and previous['leaseId'] == lease['id'], 'Идентификатор чека уже использован с другими данными', 409)
        return previous
    entry = {'id': str(uuid4()), 'requestId': payload['requestId'], 'leaseId': lease['id'], 'registerId': lease['registerId'], 'branchId': lease['branchId'], 'employeeName': lease['operator']['display_name'], 'createdAt': receipt['createdAt'], 'total': float(receipt['total']), 'payload': deepcopy(payload), 'fingerprint': fingerprint, 'status': 'pending', 'receivedAt': payroll.now().isoformat()}
    try:
        # A previously confirmed sale is replayable even after its shift closed.
        replay = sale_replay(state, _identity(lease), payload)
        payroll.require(replay or employee_active, 'Доступ сотрудника изменился. Требуется проверка владельца.', 409)
        payroll.require(replay or shift_open, 'Исходная кассовая смена закрыта. Требуется проверка владельца.', 409)
        payroll.require(replay or payroll.now() <= payroll.clock(lease['expiresAt'])+timedelta(days=30), 'Длительная задержка синхронизации. Требуется проверка владельца.', 409)
        result, identifier = _post(state, lease, entry)
        state.clear(); state.update(result)
        entry.update(status='synced', saleId=identifier)
    except WorkspaceError as error:
        entry.update(status='conflict', error=str(error))
    ensure(state)['receipts'].append(entry)
    return entry


def resolve(state, owner, request_id, reason, shift_id=None, accept_server=False):
    payroll.require(owner.get('role') == 'owner', 'Решение доступно владельцу', 403)
    payroll.require(3 <= len(reason.strip()) <= 1000, 'Укажите основание решения')
    entry = next((r for r in ensure(state)['receipts'] if r['requestId'] == request_id), None)
    payroll.require(entry, 'Чек не найден', 404)
    if entry['status'] == 'synced':
        return entry
    lease = next(g for g in ensure(state)['leases'] if g['id'] == entry['leaseId'])
    if accept_server:
        existing = sale_replay(state, _identity(lease), entry['payload'])
        payroll.require(existing, 'Исходный серверный чек не найден', 409)
        entry.update(status='synced', saleId=existing['id'], serverTotal=existing['total'], discrepancyAcknowledged=True, resolvedAt=payroll.now().isoformat(), resolvedById=owner['id'], resolutionReason=reason.strip())
        entry.pop('error', None)
        return entry
    result, identifier = _post(state, lease, entry, shift_id, reviewed=True)
    state.clear(); state.update(result)
    entry = next(r for r in ensure(state)['receipts'] if r['requestId'] == request_id)
    entry.update(status='synced', saleId=identifier, resolvedAt=payroll.now().isoformat(), resolvedById=owner['id'], resolutionReason=reason.strip(), replacementShiftId=shift_id)
    entry.pop('error', None)
    return entry


def install(app):
    from fastapi import Depends, Cookie, Request, HTTPException
    from psycopg import Connection
    from psycopg.types.json import Jsonb
    from .main import current_user, get_connection, _tenant_user, _workspace_row, _check_origin, _pos_terminal, _current_pos_operator, _current_pos_shift, _has_permission

    def persist(connection, tenant, row, state, actor, action, entity):
        version = int(row['version'])+1
        connection.execute('UPDATE operational_state SET version=%s,payload=%s,updated_at=CURRENT_TIMESTAMP WHERE tenant_id=%s', (version, Jsonb(state), tenant))
        connection.execute('INSERT INTO operational_events (tenant_id,state_version,actor_user_id,actor_login,actor_role,branch_id,action,entity_type,entity_id,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', (tenant,version,actor['id'],actor['login'],actor['role'],actor.get('branch_id'),action,'offline_receipt',entity,Jsonb({})))
        return version

    @app.post('/api/v1/pos/offline/lease', tags=['offline'])
    def lease_endpoint(payload: dict, request: Request, user: dict = Depends(current_user), ashkana_pos_operator: str | None = Cookie(default=None), connection: Connection = Depends(get_connection)):
        _check_origin(request); _pos_terminal(user)
        operator = _current_pos_operator(connection, user, ashkana_pos_operator)
        shift = _current_pos_shift(connection, user)
        tenant = _tenant_user(user)
        try:
            with connection.transaction():
                row = _workspace_row(connection, tenant, for_update=True)
                state = row['payload']
                payroll.require(isinstance(payload.get('version'), int) and payload['version'] == int(row['version']), 'Данные кассы обновились. Загрузите меню перед подготовкой автономного доступа.', 409)
                lease_count = len(state.get('offlinePos', {}).get('leases', []))
                result = issue(state, user, operator, shift, str(payload.get('token') or ''))
                result['version'] = persist(connection, tenant, row, state, user, 'offline.lease', result['id']) if len(state['offlinePos']['leases']) != lease_count else row['version']
                return result
        except WorkspaceError as error:
            raise HTTPException(error.status_code, str(error)) from error

    @app.post('/api/v1/pos/offline/receipts', tags=['offline'])
    def sync_endpoint(payload: dict, request: Request, user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
        _check_origin(request); _pos_terminal(user)
        tenant = _tenant_user(user)
        try:
            with connection.transaction():
                row = _workspace_row(connection, tenant, for_update=True)
                state = row['payload']
                g = next((g for g in state.get('offlinePos', {}).get('leases', []) if g['tokenHash'] == digest(str(payload.get('token') or ''))), None)
                payroll.require(g, 'Автономный доступ не найден', 403)
                employee = connection.execute('SELECT id,staff_role,access_permissions,is_active,deleted_at,branch_id,account_version FROM auth_users WHERE id=%s AND tenant_id=%s', (g['operator']['id'],tenant)).fetchone()
                shift = connection.execute('SELECT id,closed_at FROM pos_shifts WHERE id=%s AND tenant_id=%s AND register_user_id=%s', (g['shiftId'],tenant,user['id'])).fetchone()
                active = bool(employee and employee['is_active'] and not employee.get('deleted_at') and str(employee.get('branch_id')) == g['branchId'] and employee.get('staff_role') != 'production' and int(employee.get('account_version') or 0) == int(g['operator'].get('account_version') or 0) and _has_permission(dict(employee), 'posAccess'))
                already_received = any(r['requestId'] == payload.get('payload', {}).get('requestId') for r in state.get('offlinePos', {}).get('receipts', []))
                entry = receive(state, user, payload, active, bool(shift and not shift['closed_at']))
                version = row['version'] if already_received else persist(connection, tenant, row, state, user, 'offline.sync', entry['id'])
                return {'version':version, 'state':visible_state(state,user), 'receipt':{k:v for k,v in entry.items() if k not in {'payload','fingerprint'}}, 'entity':{'type':'sale','id':entry.get('saleId')}}
        except WorkspaceError as error:
            raise HTTPException(error.status_code, str(error)) from error

    @app.get('/api/v1/offline/receipts', tags=['offline'])
    def review_endpoint(user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
        if user.get('role') != 'owner': raise HTTPException(403, 'Журнал доступен владельцу')
        state = _workspace_row(connection,_tenant_user(user))['payload']
        rows=[]
        for row in state.get('offlinePos', {}).get('receipts', []):
            if row['status'] == 'synced': continue
            existing=next((s for s in state.get('sales', []) if s.get('requestId')==row['requestId'] and s.get('registerId')==row['registerId']), None)
            rows.append({**{k:v for k,v in row.items() if k != 'fingerprint'}, **({'serverTotal':existing['total']} if existing else {})})
        return rows

    @app.post('/api/v1/offline/receipts/resolve', tags=['offline'])
    def resolve_endpoint(payload: dict, request: Request, user: dict = Depends(current_user), connection: Connection = Depends(get_connection)):
        _check_origin(request)
        if user.get('role') != 'owner': raise HTTPException(403, 'Решение доступно владельцу')
        tenant = _tenant_user(user)
        try:
            with connection.transaction():
                row = _workspace_row(connection,tenant,for_update=True); state=row['payload']
                entry=next((r for r in state.get('offlinePos',{}).get('receipts',[]) if r['requestId']==payload.get('requestId')),None)
                payroll.require(entry,'Чек не найден',404)
                lease=next(g for g in state['offlinePos']['leases'] if g['id']==entry['leaseId'])
                if entry['status'] == 'synced': return {'receipt':entry}
                if payload.get('acceptServer') is True:
                    result=resolve(state,user,entry['requestId'],str(payload.get('reason') or ''),accept_server=True)
                    persist(connection,tenant,row,state,user,'offline.reconcile',entry['id'])
                    return {'receipt':result}
                if payload.get('useCurrentShift'):
                    shift=connection.execute('SELECT id FROM pos_shifts WHERE tenant_id=%s AND register_user_id=%s AND closed_at IS NULL ORDER BY opened_at DESC LIMIT 1', (tenant,lease['registerId'])).fetchone()
                else:
                    shift=connection.execute('SELECT id FROM pos_shifts WHERE tenant_id=%s AND id=%s AND closed_at IS NULL', (tenant,lease['shiftId'])).fetchone()
                payroll.require(shift,'Откройте смену этой кассы и выберите проведение в текущую смену',409)
                result=resolve(state,user,entry['requestId'],str(payload.get('reason') or ''),shift['id'])
                persist(connection,tenant,row,state,user,'offline.resolve',entry['id'])
                return {'receipt':result}
        except WorkspaceError as error:
            raise HTTPException(error.status_code,str(error)) from error
