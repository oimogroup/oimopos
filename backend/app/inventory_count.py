"""Inventory snapshots for warehouse goods and separately accepted serving lots."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from math import fsum, isclose
from . import custody


def variance(actual, book):
    """A count has millesimal precision; hidden fractions aren't discrepancies."""
    actual, book = float(actual), float(book)
    rounded = lambda value: Decimal(str(value)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
    return 0.0 if rounded(actual) == rounded(book) else actual - book


def _legacy_import_date(state, row):
    """Resolve old product imports from their documents without rewriting the ledger."""
    from .company_settings import company_settings
    from .sales_import import report_date, report_timestamp
    dates = set()
    for document in state.get('externalSalesImports', []):
        if (document.get('status', 'posted') != 'posted'
                or document.get('branchId') != row.get('branchId')
                or document.get('title') != row.get('documentNumber')
                or not any(item.get('productId') is not None
                           and str(item['productId']) == str(row.get('itemId'))
                           for item in document.get('items', []))):
            continue
        try:
            day = report_date(document['title'])
            # A materialized sale freezes the original timezone even for older
            # imports whose document did not yet contain a timezone snapshot.
            sales = [sale for sale in state.get('sales', [])
                     if document.get('id') and sale.get('branchId') == row.get('branchId')
                     and sale.get('paymentMethod') == 'external'
                     and (sale.get('importId') == document['id']
                          or sale.get('id') == 'sale-' + str(document['id']))]
            if sales:
                for sale in sales:
                    date = datetime.fromisoformat(sale['createdAt'].replace('Z', '+00:00'))
                    if date.tzinfo is None or date.date().isoformat() != day:
                        return None
                    dates.add(date)
            else:
                zone = document.get('timezone') or company_settings(state)['general']['timezone']
                dates.add(datetime.fromisoformat(report_timestamp(day, zone)))
        except (ValueError, TypeError, KeyError, AttributeError):
            # Unsupported or conflicting history must not receive a guessed date.
            return None
    return next(iter(dates)).isoformat() if len(dates) == 1 else None


def movement_date(state, row):
    value = row.get('effectiveAt')
    if not value and row.get('movementType') == 'supplier_receipt':
        # Read legacy documents without rewriting their audit timestamps.
        documents = [*state['logisticsState'].get('supplies', []), *state['logisticsState'].get('directOrders', [])]
        matches = [d for d in documents if d.get('branchId') == row.get('branchId') and d.get('number') == row.get('documentNumber') and d.get('receivedAt')]
        dates = {d['receivedAt'] for d in matches}
        if len(dates) == 1:
            value = dates.pop()
    if not value and row.get('movementType') == 'inventory_adjustment':
        documents = state['logisticsState'].get('inventories', [])
        dates = {d.get('countedAt') or d.get('createdAt') for d in documents
                 if d.get('status') == 'posted' and d.get('branchId') == row.get('branchId')
                 and d.get('number') == row.get('documentNumber')}
        if len(dates) == 1:
            value = dates.pop()
    if not value and row.get('movementType') == 'sale':
        value = _legacy_import_date(state, row)
    try:
        date = datetime.fromisoformat(str(value or row['createdAt']).replace('Z', '+00:00'))
        if date.tzinfo is not None:
            return date
    except (ValueError, TypeError):
        pass
    return datetime.fromisoformat(row['createdAt'].replace('Z', '+00:00'))


def _last_counts(state, branch, date):
    """A partial count establishes an opening only for its own warehouse items."""
    latest = {}
    for document in state['logisticsState'].get('inventories', []):
        if document.get('branchId') != branch or document.get('status') != 'posted':
            continue
        at = document.get('countedAt') or document.get('createdAt')
        try:
            counted_at = datetime.fromisoformat(at.replace('Z', '+00:00'))
            if counted_at.tzinfo is None or counted_at > date:
                continue
            posted_at = datetime.fromisoformat((document.get('postedAt') or document['createdAt']).replace('Z', '+00:00'))
            if posted_at.tzinfo is None:
                posted_at = counted_at
        except (ValueError, TypeError, AttributeError, KeyError):
            continue
        key = (counted_at, posted_at, str(document.get('createdAt', '')), str(document.get('id', '')))
        for item in document.get('items', []):
            if item.get('lotId'):
                continue
            item_id = str(item.get('itemId'))
            if item_id not in latest or key > latest[item_id][0]:
                latest[item_id] = (key, document, item)
    return latest


def _movement_bucket(row, quantity):
    kind = row.get('movementType', '')
    if kind in {'inventory_adjustment', 'ingredient_count', 'stock_adjustment', 'transfer_variance'} or quantity == 0:
        return 'adjustment'
    if quantity < 0 and kind in {'writeoff', 'write_off', 'stock_writeoff', 'warehouse_writeoff', 'ingredient_writeoff', 'inventory_writeoff'}:
        return 'writeoff'
    return 'incoming' if quantity > 0 else 'outgoing'


def _movement_summary(state, branch, date, book, rows, previous):
    """Copy the known ledger interval once; later edits never rewrite the count."""
    last_at, document, previous_item = (previous[0][0], previous[1], previous[2]) if previous else (None, {}, {})
    entries = []
    for row_at, index, row in sorted(rows, key=lambda value: (value[0], value[1])):
        if row_at > date or (last_at is not None and row_at <= last_at):
            continue
        if previous and row.get('movementType') == 'inventory_adjustment' and row.get('documentNumber') == document.get('number'):
            continue
        signed_quantity = float(row['quantity'])
        bucket = _movement_bucket(row, signed_quantity)
        quantity = signed_quantity if bucket == 'adjustment' else abs(signed_quantity)
        unit_cost = float(row['unitCost']) if row.get('unitCost') is not None else None
        entry = {
            'id': str(row.get('id') or 'legacy-ledger-' + str(index)),
            'date': row_at.isoformat(), 'effectiveAt': row_at.isoformat(),
            'createdAt': row.get('createdAt'), 'documentNumber': row.get('documentNumber', ''),
            'movementType': row.get('movementType', ''), 'bucket': bucket,
            'quantity': quantity, 'signedQuantity': signed_quantity,
            'unitCost': unit_cost, 'cost': quantity * unit_cost if unit_cost is not None else None,
            'actor': str(row.get('createdBy') or ''),
        }
        if row.get('relatedBranchId'):
            entry['relatedBranchId'] = row['relatedBranchId']
        dish_name = row.get('dishName') or row.get('recipeName')
        if not dish_name and row.get('movementType') == 'production_consumption' and row.get('documentNumber'):
            batches = [batch for batch in state['logisticsState'].get('batches', [])
                       if batch.get('branchId') == branch and batch.get('number') == row['documentNumber']]
            if len(batches) == 1:
                recipe = next((recipe for recipe in state.get('recipes', [])
                               if str(recipe['id']) == str(batches[0].get('recipeId'))), {})
                dish_name = recipe.get('name')
        if dish_name:
            entry['dishName'] = str(dish_name)
        entries.append(entry)
    incoming = fsum(entry['quantity'] for entry in entries if entry['bucket'] == 'incoming')
    outgoing = fsum(entry['quantity'] for entry in entries if entry['bucket'] == 'outgoing')
    written_off = fsum(entry['quantity'] for entry in entries if entry['bucket'] == 'writeoff')
    adjustments = fsum(entry['quantity'] for entry in entries if entry['bucket'] == 'adjustment')
    writeoff_costs = [entry['cost'] for entry in entries if entry['bucket'] == 'writeoff']
    # Initial stock may predate the ledger. Keep it explicit rather than inventing
    # a receipt. A later backdated operation may also change the restored opening.
    opening = book - fsum(entry['signedQuantity'] for entry in entries)
    previous_quantity = previous_item.get('actual')
    previous_balance = None
    if previous_quantity is not None:
        previous_balance = float(previous_quantity)
        if previous_item.get('book') is not None:
            previous_balance = float(previous_item['book']) + variance(previous_quantity, previous_item['book'])
    return {
        'available': True, 'asOf': date.isoformat(),
        'lastCountAt': last_at.isoformat() if last_at else None,
        'lastCountId': document.get('id'), 'lastCountNumber': document.get('number'),
        'lastCountQuantity': previous_quantity,
        'opening': opening,
        'openingBasis': 'inventory' if previous_balance is not None and isclose(opening, previous_balance, rel_tol=0, abs_tol=0.000001) else 'reconstructed',
        'historyStartAt': entries[0]['date'] if entries else None,
        'incoming': incoming, 'outgoing': outgoing, 'writtenOff': written_off,
        'writtenOffCost': fsum(writeoff_costs) if all(cost is not None for cost in writeoff_costs) else None,
        'adjustments': adjustments, 'entries': entries,
    }


def build(state, branch, payload, entities):
    from .workspace import _require, _stock, _cost, _now
    scope = payload.get('scope', 'full')
    _require(scope in {'full','category','selected','serving'}, 'Неизвестный тип проверки')
    at = payload.get('countedAt') or _now()
    try:
        date = datetime.fromisoformat(at.replace('Z','+00:00'))
        _require(date.tzinfo is not None and date <= datetime.now(timezone.utc), 'Проверьте дату подсчёта')
    except (ValueError, TypeError):
        _require(False, 'Проверьте дату подсчёта')
    if scope == 'serving':
        _require(not payload.get('countedAt'), 'Раздача проверяется на текущий момент')
        items=[]
        for b in state['logisticsState']['batches']:
            if b.get('branchId') != branch or b.get('status') == 'closed': continue
            recipe=next((r for r in state['recipes'] if str(r['id'])==str(b.get('recipeId'))),{})
            for lot in b.get('servingLots',[]):
                _require(not lot.get('handoverId') and not lot.get('reservedWeight'), 'Завершите передачи и заявки на списание перед проверкой раздачи')
                _require(not custody.has_pending_surplus(state, lot['id']), 'Сначала рассмотрите заявки на излишки перед проверкой раздачи', 409)
                if not lot.get('acceptedAt'):continue
                weight=custody.lot_available(lot)
                items.append({'itemId':'lot:'+lot['id'],'lotId':lot['id'],'batchId':b['id'],'name':recipe.get('name','Блюдо')+' · '+str(b.get('number','')), 'unit':'кг','book':weight,'currentBook':weight,'actual':None,'unitCost':float(b.get('cost',0))/max(float(b.get('actualWeight',0)),.000001),'movementSummary':{'available':False,'reason':'serving_custody'}})
        return items, at
    if scope=='selected':
        ids={str(i) for i in payload.get('itemIds',[])}
        _require(ids and ids <= {str(e['id']) for e in entities}, 'Выберите существующие позиции')
        entities=[e for e in entities if str(e['id']) in ids]
    ledger=state['logisticsState'].get('stockLedger',[])
    branch_rows = []
    item_rows = {}
    for index, row in enumerate(ledger):
        if row.get('branchId') != branch:
            continue
        dated_row = (movement_date(state, row), index, row)
        branch_rows.append(dated_row)
        item_rows.setdefault(str(row['itemId']), []).append(dated_row)
    previous_counts = _last_counts(state, branch, date)
    if payload.get('countedAt'):
        _require(branch_rows and date >= min(row[0] for row in branch_rows), 'На эту дату нет истории движений')
        _require(not any(i.get('status')=='posted' and i.get('branchId')==branch and datetime.fromisoformat(i.get('countedAt',i['createdAt']).replace('Z','+00:00'))>date for i in state['logisticsState']['inventories']), 'После этой даты уже проведена инвентаризация')
    items=[]
    for e in entities:
        current=_stock(state,branch,e['id'])
        rows = item_rows.get(str(e['id']), [])
        later=sum(float(row['quantity']) for row_at, _, row in rows if row_at > date)
        _require(current-later >= -0.000001, 'История движений не позволяет восстановить остаток: ' + e.get('name', str(e['id'])))
        items.append({'itemId':str(e['id']),'name':e.get('name',str(e['id'])),'unit':e.get('unit',''),'category':e.get('category',''),'book':current-later,'currentBook':current,'actual':None,'unitCost':_cost(state,branch,e['id']),'movementSummary':_movement_summary(state,branch,date,current-later,rows,previous_counts.get(str(e['id'])))})
    return items,at


def current(state, branch, item):
    from .workspace import _stock, _require
    if not item.get('lotId'):return _stock(state,branch,item['itemId'])
    b=next(b for b in state['logisticsState']['batches'] if b['id']==item['batchId'])
    _require(b.get('status') != 'closed', 'Партия закрыта — начните новый подсчёт раздачи', 409)
    lot = next(l for l in b['servingLots'] if l['id']==item['lotId'])
    _require(not custody.has_pending_surplus(state, lot['id']), 'Сначала рассмотрите заявки на излишки перед проверкой раздачи', 409)
    return custody.lot_available(lot)


def adjust(state, branch, item, difference):
    from .workspace import _set_stock
    if item.get('lotId'):
        b=next(b for b in state['logisticsState']['batches'] if b['id']==item['batchId'])
        lot=next(l for l in b['servingLots'] if l['id']==item['lotId'])
        lot['adjustmentWeight']=float(lot.get('adjustmentWeight',0))+difference
    else:_set_stock(state,branch,item['itemId'],current(state,branch,item)+difference)
