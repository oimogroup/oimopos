"""Custody documents for cooked food. Quantities are kilograms, never raw stock."""
from datetime import datetime, timezone
from math import isfinite
from uuid import uuid4


class CustodyError(ValueError):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


def require(condition, message, status=409):
    if not condition:
        raise CustodyError(message, status)


def number(value):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        raise CustodyError("Укажите корректное количество", 422)
    require(isfinite(value) and value >= 0, "Количество не может быть отрицательным", 422)
    return round(value, 6)


def now():
    return datetime.now(timezone.utc).isoformat()


def manager(user):
    return user.get('role') == 'owner' or user.get('staff_role') == 'branch_manager'


def initialize(batch, recipe):
    if 'servingLots' in batch:
        return
    # Old records do not prove who actually received the food.
    batch['servingLots'] = []
    batch['dispatchedWeight'] = number(batch.get('transferredWeight'))
    if number(batch.get('transferredWeight')):
        batch['servingLots'].append({'id': 'legacy-'+str(batch['id']), 'line': batch.get('servingLine') or 'Витрина',
            'acceptedWeight': number(batch.get('transferredWeight')), 'soldWeight': number(batch.get('soldPortions'))*portion_weight(batch, recipe)/1000,
            'responsibleId': None, 'responsibleName': 'Приёмка ранее не фиксировалась', 'legacy': True,
            'writeoffWeight': 0, 'reservedWeight': 0, 'adjustmentWeight': 0})


def portion_weight(batch, recipe):
    return number(batch.get('portionWeight') or recipe.get('yield'))


def lot_balance(lot):
    return max(0, round(number(lot.get('acceptedWeight')) + float(lot.get('adjustmentWeight', 0)) - number(lot.get('soldWeight')) - number(lot.get('writeoffWeight')) - number(lot.get('reservedWeight')), 6))


def lot_available(lot):
    if lot.get('legacy') or not lot.get('acceptedAt') or lot.get('responsibleId') is None:
        return 0
    return 0 if lot.get('handoverId') else lot_balance(lot)


def has_pending_surplus(state, lot_id):
    return any(document.get('kind') == 'surplus' and document.get('lotId') == lot_id
               and document.get('status') == 'pending'
               for document in state['logisticsState'].get('custodyDocuments', []))


def kitchen_balance(batch):
    pending = sum(number(t.get('weight')) for t in batch.get('transfers', []) if t.get('status') == 'pending')
    return max(0, round(number(batch.get('actualWeight')) + float(batch.get('kitchenAdjustment', 0)) - number(batch.get('dispatchedWeight', batch.get('transferredWeight'))) - pending - number(batch.get('kitchenWriteoffWeight')) - number(batch.get('kitchenReservedWeight')), 6))


def serving_balance(batch, recipe):
    if 'servingLots' not in batch:
        return 0
    return sum(lot_available(lot) for lot in batch['servingLots'])


def snapshot_actor(user):
    return {'id': user.get('id'), 'name': user.get('display_name', '')}


def find_batch(state, user, batch_id):
    batch = next((b for b in state['logisticsState']['batches'] if str(b['id']) == str(batch_id)), None)
    require(batch and (user.get('role') == 'owner' or batch['branchId'] == user.get('branch_id')), 'Партия недоступна', 403)
    require(batch.get('status') != 'closed', 'Партия закрыта')
    recipe = next((r for r in state['recipes'] if str(r['id']) == str(batch['recipeId'])), {})
    initialize(batch, recipe)
    batch["custodyVersion"] = 1
    return batch, recipe


def responsible(user, lot, batch):
    return bool(user.get('_production_shift_intake')) or bool(user.get('_cash_shift_count')) or manager(user) or (lot and str(lot.get('responsibleId')) == str(user.get('id'))) or (lot is None and str(batch.get('kitchenResponsibleId', batch.get('createdById'))) == str(user.get('id')))


def document(state, user, batch, kind, payload, **fields):
    docs = state['logisticsState'].setdefault('custodyDocuments', [])
    entry = {'id': 'custody-'+str(uuid4()), 'number': f'УЧ-{len(docs)+1:06}', 'kind': kind,
             'branchId': batch['branchId'], 'batchId': batch['id'], 'batchNumber': batch['number'],
             'recipeId': batch['recipeId'], 'createdAt': now(), 'actor': snapshot_actor(user),
             'requestId': str(payload.get('requestId', '')), 'status': 'recorded', **fields}
    entry['costPerKg'] = number(batch.get('cost')) / max(number(batch.get('actualWeight')), 0.000001)
    if 'weight' in entry: entry['costAmount'] = round(entry['weight'] * entry['costPerKg'], 2)
    docs.insert(0, entry)
    return entry


def reason(payload):
    text = str(payload.get('reason', '')).strip()
    require(3 <= len(text) <= 500, 'Укажите причину (от 3 до 500 символов)', 422)
    return text


def recipient(user, batch):
    target = user.get('_custody_recipient')
    require(target and str(target.get('branchId')) == str(batch['branchId']), 'Выберите действующего получателя этого заведения', 422)
    return target


def send(state, user, batch, payload):
    line = str(payload.get('line', '')).strip()
    require(0 < len(line) <= 80, 'Укажите витрину (до 80 символов)', 422)
    require(responsible(user, None, batch), 'Передачу оформляет ответственный за кухню или руководитель', 403)
    target = recipient(user, batch)
    weight = number(payload.get('weight'))
    require(0 < weight <= kitchen_balance(batch)+1e-6, 'На кухне недостаточно готового блюда')
    production_shift_id = user.get('production_shift_id')
    if production_shift_id is None:
        own_shifts = [shift for shift in state['logisticsState'].get('productionShifts', [])
                      if str(shift.get('branchId')) == str(batch['branchId']) and shift.get('status') == 'open'
                      and str(shift.get('employeeId')) == str(user.get('id'))]
        if len(own_shifts) == 1:
            production_shift_id = own_shifts[0]['id']
    entry = document(state, user, batch, 'transfer', payload, weight=weight, line=line, recipient=target, responsible={'id':batch.get('kitchenResponsibleId',batch.get('createdById')),'name':batch.get('kitchenResponsibleName',batch.get('createdBy'))}, status='pending', productionShiftId=production_shift_id)
    batch.setdefault('transfers', []).append({'id': entry['id'], 'weight': weight, 'line': line, 'status': 'pending',
        'transferredAt': entry['createdAt'], 'transferredBy': user['display_name'], 'requestId': entry['requestId'], 'recipient': target,
        'productionShiftId': entry['productionShiftId']})
    return entry


def context(state, branch_id, user):
    names = {str(recipe['id']): recipe['name'] for recipe in state.get('recipes', [])}
    docs = [{**d, 'name': d.get('name') or names.get(str(d.get('recipeId')), 'Блюдо')} for d in state['logisticsState'].get('custodyDocuments', []) if d['branchId'] == branch_id]
    lots = []
    kitchens = []
    for batch in state['logisticsState']['batches']:
        if batch['branchId'] != branch_id or batch.get('status') == 'closed':
            continue
        recipe = next((r for r in state['recipes'] if str(r['id']) == str(batch['recipeId'])), {})
        initialize(batch, recipe)
        kitchens.append({'id':batch['id'],'name':recipe.get('name','Блюдо'),'number':batch['number'],'availableWeight':kitchen_balance(batch),'canAct':responsible(user,None,batch),'responsibleName':batch.get('createdBy','Не зафиксирован')})
        for lot in batch['servingLots']:
            lots.append({**lot, 'batchId': batch['id'], 'batchNumber': batch['number'], 'name': recipe.get('name', 'Блюдо'),
                'availableWeight': lot_available(lot), 'balanceWeight': lot_balance(lot), 'canAct': responsible(user, lot, batch)})
    for sale in state.get('sales', []):
        if sale.get('branchId') != branch_id:
            continue
        for item in sale.get('items', []):
            for allocation in item.get('batchAllocations', []):
                if not allocation.get('lotId'):
                    continue
                docs.append({'id':sale['id']+':'+allocation['lotId'], 'number':'Чек '+str(sale['number']), 'kind':'sale',
                    'batchNumber':next((batch['number'] for batch in state['logisticsState']['batches'] if batch['id']==allocation['batchId']),''),
                    'createdAt':sale['createdAt'],'actor':{'id':sale.get('cashierId'),'name':sale.get('cashier','')},
                    'responsible':{'id':allocation.get('responsibleId'),'name':allocation.get('responsibleName')},
                    'weight':allocation.get('weight'),'line':allocation.get('line'), 'status':'refunded' if sale.get('refundedAt') else 'recorded',
                    'reason':sale.get('refundReason') or item['name']})
    docs.sort(key=lambda row:row['createdAt'],reverse=True)
    return {'kitchens': kitchens, 'lots': lots, 'documents': docs, 'canReview': manager(user), 'actorId': user.get('id')}


def apply(state, user, action, payload):
    require(user.get('plan_code') != 'restaurant', 'Операция доступна для столовой', 403)
    docs = state['logisticsState'].setdefault('custodyDocuments', [])
    request_id = str(payload.get('requestId', '')).strip()
    require(0 < len(request_id) <= 80, 'Не указан идентификатор операции', 422)
    # Preserve the complete request to detect accidental reuse with different data.
    replay = next((d for d in docs if d.get('requestId') == request_id and d.get('actor', {}).get('id') == user.get('id')), None)
    if replay:
        require(user.get('role') == 'owner' or replay['branchId'] == user.get('branch_id'), 'Документ относится к другой точке', 403)
        require(replay.get('requestPayload') == payload and replay.get('requestAction') == action, 'Идентификатор уже использован для другой операции')
        return 'custody_document', replay['id']
    if action in {'custody.accept', 'custody.review', 'custody.cancel', 'custody.reject'}:
        source = next((d for d in docs if d['id'] == payload.get('documentId')), None)
        require(source, 'Документ не найден', 404)
        if action == 'custody.review' and source.get('kind') == 'ingredient_count':
            require(manager(user) and (user.get('role') == 'owner' or source['branchId'] == user.get('branch_id')), 'Проверка доступна руководителю этого заведения', 403)
            require(source['status'] == 'review', 'Документ уже рассмотрен')
            require(payload.get('decision') == 'approve', 'Фактический пересчёт сохраняется неизменно; добавьте результат проверки')
            note = reason(payload)
            source.update(status='approved', reviewedAt=now(), reviewedBy=snapshot_actor(user), reviewNote=note)
            result = {**source, 'id':'custody-'+str(uuid4()), 'kind':'review', 'sourceId':source['id'], 'createdAt':now(), 'actor':snapshot_actor(user), 'requestId':request_id, 'requestPayload':payload, 'requestAction':action}
            docs.insert(0, result)
            return 'custody_document', result['id']
        batch, recipe = find_batch(state, user, source['batchId'])
    else:
        batch, recipe = find_batch(state, user, payload.get('batchId', payload.get('id')))
    from .workspace import _locked
    require(not _locked(state, batch['branchId']), 'На точке идёт инвентаризация — движения временно заблокированы', 409)
    lot = next((l for l in batch['servingLots'] if l['id'] == payload.get('lotId')), None)
    if payload.get('lotId'):
        require(lot, 'Остаток витрины не найден', 404)
    if action == 'custody.confirm_stock':
        require(user.get('_receiving_cashier'), 'Остатки подтверждает кассир на смене', 403)
        require(lot and lot.get('legacy'), 'Остаток уже принят или недоступен')
        require(not lot.get('handoverId') and not number(lot.get('reservedWeight')), 'Сначала завершите передачу ответственности или списание')
        require('actualWeight' in payload, 'Укажите фактический вес', 422)
        expected = lot_balance(lot)
        actual = number(payload['actualWeight'])
        require(actual <= max(number(batch.get('actualWeight'))*2, expected*2, 1), 'Проверьте фактический вес')
        delta = round(actual-expected, 6)
        note = reason(payload) if abs(delta)>1e-6 else str(payload.get('reason', '')).strip()
        lot['adjustmentWeight'] = float(lot.get('adjustmentWeight', 0))+delta
        lot.update(legacy=False, acceptedAt=now(), responsibleId=user['id'], responsibleName=user['display_name'])
        result = document(state, user, batch, 'opening_acceptance', payload, lotId=lot['id'], expectedWeight=expected, actualWeight=actual, variance=delta, reason=note, responsible=snapshot_actor(user), status='review' if abs(delta)>1e-6 else 'recorded')
    elif action == 'custody.send':
        result = send(state, user, batch, payload)
    elif action == 'custody.accept':
        require(source['status'] == 'pending' and source['kind'] in {'transfer', 'handover'}, 'Передача уже обработана')
        require(bool(user.get('_receiving_cashier')) if source['recipient'].get('kind') == 'branch_cashiers' else str(source['recipient']['id']) == str(user.get('id')), 'Приёмку подтверждает кассир на смене или назначенный получатель', 403)
        require('actualWeight' in payload, 'Укажите фактический вес', 422)
        actual = number(payload.get('actualWeight'))
        expected = number(source['weight'])
        require(actual <= max(number(batch['actualWeight'])*2, expected, 1), 'Проверьте фактический вес')
        delta = round(actual-expected, 6)
        note = reason(payload) if abs(delta) > 1e-6 else str(payload.get('reason', '')).strip()
        if source['kind'] == 'transfer':
            transfer = next(t for t in batch['transfers'] if t.get('id') == source['id'])
            transfer.update(status='accepted', acceptedAt=now(), acceptedBy=snapshot_actor(user), actualWeight=actual,
                            receivingShiftId=user.get('shift_id'), receivingRegisterId=user.get('register_id'))
            batch['dispatchedWeight'] = number(batch.get('dispatchedWeight'))+expected
            batch['transferredWeight'] = number(batch.get('transferredWeight'))+actual
            lot = {'id': 'lot-'+str(uuid4()), 'acceptedWeight': actual, 'soldWeight': 0, 'writeoffWeight': 0, 'reservedWeight': 0,
                   'adjustmentWeight': 0, 'line': source['line'], 'responsibleId': user['id'], 'responsibleName': user['display_name'], 'acceptedAt': now()}
            batch['servingLots'].append(lot)
            batch['status'] = 'partial' if kitchen_balance(batch) > 1e-6 else 'serving'
        else:
            lot = next(l for l in batch['servingLots'] if l['id'] == source['lotId'])
            require(lot.get('handoverId') == source['id'], 'Остаток уже передан')
            require(not has_pending_surplus(state, lot['id']), 'Сначала рассмотрите заявку на излишек этой партии')
            lot['adjustmentWeight'] = float(lot.get('adjustmentWeight', 0))+delta
            lot.update(responsibleId=user['id'], responsibleName=user['display_name'], handoverId=None, legacy=False, acceptedAt=now())
        lot.update(registerId=user.get('register_id'), acceptedShiftId=user.get('shift_id'))
        source.update(status='accepted', acceptedAt=now(), actualWeight=actual, acceptedBy=snapshot_actor(user),
                      receivingShiftId=user.get('shift_id'), receivingRegisterId=user.get('register_id'))
        result = document(state,user,batch,'acceptance',payload,sourceId=source['id'],lotId=lot['id'],expectedWeight=expected,actualWeight=actual,
            variance=delta,reason=note,responsible=source.get('previousResponsible') or source.get('responsible'),sender=source['actor'],recipient=snapshot_actor(user),line=lot['line'],status='review' if abs(delta)>1e-6 else 'recorded',
            shiftId=user.get('shift_id'), registerId=user.get('register_id'))
    elif action == 'custody.reject':
        require(user.get('_receiving_cashier') and source.get('recipient', {}).get('kind') == 'branch_cashiers', 'Отклонить передачу может кассир на смене', 403)
        require(source['status'] == 'pending' and source['kind'] == 'transfer', 'Передача уже обработана')
        note = reason(payload)
        next(t for t in batch['transfers'] if t.get('id') == source['id']).update(
            status='rejected', receivingShiftId=user.get('shift_id'), receivingRegisterId=user.get('register_id'))
        source.update(status='rejected', rejectedAt=now(), rejectedBy=snapshot_actor(user), rejectReason=note,
                      receivingShiftId=user.get('shift_id'), receivingRegisterId=user.get('register_id'))
        result = document(state, user, batch, 'rejection', payload, sourceId=source['id'], reason=note,
                          shiftId=user.get('shift_id'), registerId=user.get('register_id'))
    elif action == 'custody.cancel':
        require(source['status']=='pending' and source['kind'] in {'transfer','handover'}, 'Передача уже обработана')
        require(manager(user) or source['actor']['id']==user.get('id'), 'Отмена доступна отправителю или руководителю',403)
        note=reason(payload)
        if source['kind']=='transfer':
            next(t for t in batch['transfers'] if t.get('id')==source['id'])['status']='canceled'
        else:
            next(l for l in batch['servingLots'] if l['id']==source['lotId'])['handoverId']=None
        source.update(status='canceled',canceledAt=now(),canceledBy=snapshot_actor(user),cancelReason=note)
        result=document(state,user,batch,'cancel',payload,sourceId=source['id'],reason=note)
    elif action == 'custody.surplus':
        require(user.get('_serving_surplus'), 'Излишек оформляет кассир на открытой смене', 403)
        require(lot and not lot.get('legacy') and lot.get('acceptedAt') and lot.get('responsibleId') is not None, 'Выберите ранее принятую партию')
        require(not lot.get('handoverId'), 'Сначала завершите передачу ответственности')
        require(not any(d.get('kind') == 'surplus' and d.get('lotId') == lot['id'] and d.get('status') == 'pending' for d in docs), 'По этой партии уже ожидается подтверждение излишка')
        weight = number(payload.get('weight'))
        require(0 < weight <= 10000, 'Проверьте количество излишка', 422)
        note = reason(payload)
        result = document(state, user, batch, 'surplus', payload, lotId=lot['id'], weight=weight,
                          expectedWeight=lot_balance(lot), reason=note, status='pending',
                          shiftId=user.get('shift_id'), responsible={'id':lot['responsibleId'], 'name':lot.get('responsibleName')})
    elif action == 'custody.close':
        require(manager(user),'Закрытие доступно руководителю',403)
        require(kitchen_balance(batch)<=1e-6 and all(lot_balance(row)<=1e-6 for row in batch['servingLots']),'Перед закрытием оформите остатки и списания')
        require(not any(d['batchId']==batch['id'] and d['status'] in {'pending','review'} for d in docs),'Остались неподтверждённые документы')
        note=reason(payload)
        batch.update(status='closed',closedAt=now(),closedBy=user['display_name'])
        result=document(state,user,batch,'close',payload,reason=note)
    elif action == 'custody.review':
        require(manager(user), 'Подтверждение доступно руководителю', 403)
        require(source['status'] in {'pending','review'}, 'Документ уже рассмотрен')
        decision = payload.get('decision')
        require(decision in {'approve','reject'}, 'Выберите решение')
        require(source['kind'] in {'writeoff', 'surplus'} or decision == 'approve', 'Расхождение фиксируется неизменно; руководитель добавляет результат проверки')
        note=reason(payload)
        if source['kind'] == 'surplus':
            require(source['status'] == 'pending', 'Излишек уже рассмотрен')
            target = next((entry for entry in batch['servingLots'] if entry['id'] == source.get('lotId')), None)
            require(target and not target.get('legacy') and target.get('acceptedAt'), 'Принятая партия не найдена')
            if decision == 'approve':
                require(not target.get('handoverId'), 'Сначала отмените передачу ответственности этой партии')
                target['adjustmentWeight'] = round(float(target.get('adjustmentWeight', 0)) + source['weight'], 6)
        elif source['kind'] == 'writeoff':
            target = next((l for l in batch['servingLots'] if l['id']==source.get('lotId')), None)
            weight=source['weight']
            if target:
                target['reservedWeight']=max(0,number(target.get('reservedWeight'))-weight)
                if decision=='approve': target['writeoffWeight']=number(target.get('writeoffWeight'))+weight
            else:
                batch['kitchenReservedWeight']=max(0,number(batch.get('kitchenReservedWeight'))-weight)
                if decision=='approve': batch['kitchenWriteoffWeight']=number(batch.get('kitchenWriteoffWeight'))+weight
        else:
            require(source['status']=='review','Этот документ не требует рассмотрения')
        source.update(status='approved' if decision=='approve' else 'rejected',reviewedAt=now(),reviewedBy=snapshot_actor(user),reviewNote=note)
        result=document(state,user,batch,'review',payload,sourceId=source['id'],decision=decision,reason=note)
    elif action in {'custody.writeoff','custody.count','custody.handover'}:
        terminal_writeoff = action == 'custody.writeoff' and user.get('_serving_writeoff')
        require(terminal_writeoff or responsible(user,lot,batch),'Операция доступна ответственному сотруднику или руководителю',403)
        if terminal_writeoff:
            require(lot and lot_available(lot) > 0, 'Нет принятого остатка для списания')
        require(not lot or not lot.get('handoverId'),'Остаток ожидает приёмки новым сотрудником')
        if lot and action in {'custody.count', 'custody.handover'}:
            require(not has_pending_surplus(state, lot['id']), 'Сначала рассмотрите заявку на излишек этой партии')
        balance=lot_balance(lot) if lot else kitchen_balance(batch)
        if action=='custody.writeoff':
            weight=number(payload.get('weight'))
            require(0<weight<=balance+1e-6,'Количество больше доступного остатка')
            note=reason(payload)
            result=document(state,user,batch,'writeoff',payload,lotId=lot['id'] if lot else None,weight=weight,reason=note,
                expectedWeight=balance,responsible={'id':lot.get('responsibleId'),'name':lot.get('responsibleName')} if lot else {'id':batch.get('kitchenResponsibleId',batch.get('createdById')),'name':batch.get('kitchenResponsibleName',batch.get('createdBy'))},status='pending')
            if lot: lot['reservedWeight']=number(lot.get('reservedWeight'))+weight
            else: batch['kitchenReservedWeight']=number(batch.get('kitchenReservedWeight'))+weight
        elif action=='custody.count':
            require('expectedWeight' in payload and abs(number(payload['expectedWeight'])-balance)<=1e-6,'Остаток изменился. Обновите данные и пересчитайте блюдо')
            require(lot or not any(t.get('status')=='pending' for t in batch.get('transfers',[])),'Сначала завершите приёмку переданных партий')
            require(not (number(lot.get('reservedWeight')) if lot else number(batch.get('kitchenReservedWeight'))),'Сначала рассмотрите заявки на списание')
            require('actualWeight' in payload, 'Укажите фактический остаток', 422)
            actual=number(payload.get('actualWeight'))
            require(actual<=max(number(batch['actualWeight'])*2,balance,1),'Проверьте фактический остаток')
            delta=round(actual-balance,6)
            note=reason(payload) if abs(delta)>1e-6 else str(payload.get('reason','')).strip()
            result=document(state,user,batch,'count',payload,lotId=lot['id'] if lot else None,expectedWeight=balance,actualWeight=actual,variance=delta,reason=note,
                responsible={'id':lot.get('responsibleId'),'name':lot.get('responsibleName')} if lot else {'id':batch.get('kitchenResponsibleId',batch.get('createdById')),'name':batch.get('kitchenResponsibleName',batch.get('createdBy'))},status='review' if abs(delta)>1e-6 else 'recorded')
            if lot: lot['adjustmentWeight']=float(lot.get('adjustmentWeight',0))+delta
            else: batch['kitchenAdjustment']=float(batch.get('kitchenAdjustment',0))+delta
        else:
            require('expectedWeight' in payload and abs(number(payload['expectedWeight'])-balance)<=1e-6,'Остаток изменился. Обновите данные')
            require(lot,'Передать ответственность можно за остаток витрины')
            require(not number(lot.get('reservedWeight')),'Сначала рассмотрите заявки на списание')
            target=recipient(user, batch)
            require(str(target['id'])!=str(lot.get('responsibleId')),'Выберите другого ответственного')
            result=document(state,user,batch,'handover',payload,lotId=lot['id'],line=lot['line'],weight=balance,recipient=target,
                previousResponsible={'id':lot.get('responsibleId'),'name':lot.get('responsibleName')},status='pending')
            lot['handoverId']=result['id']
    else:
        raise CustodyError('Неизвестная операция',404)
    result.update(requestPayload=dict(payload),requestAction=action)
    return 'custody_document',result['id']
