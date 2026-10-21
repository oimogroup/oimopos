"""External sales register: stock consumption without a second cash payment."""
import base64
import hashlib
import io
import json
import math
import re
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4
from xml.etree import ElementTree as ET
from . import custody


def norm(value):
    return re.sub(r'\s+', ' ', str(value).strip()).casefold().replace('ё', 'е')


def report_date(title):
    """This importer accepts a single daily aggregate, never invents daily splits."""
    match = re.fullmatch(r'\s*Реестр\s+продаж\s+с\s+(\d{2}\.\d{2}\.\d{4})\s+по\s+(\d{2}\.\d{2}\.\d{4})\s*', str(title), re.IGNORECASE)
    if not match:
        raise ValueError('Укажите период в заголовке: «Реестр продаж с ДД.ММ.ГГГГ по ДД.ММ.ГГГГ»')
    try:
        start, end = (datetime.strptime(value, '%d.%m.%Y').date() for value in match.groups())
    except ValueError as error:
        raise ValueError('Некорректная дата в заголовке реестра продаж') from error
    if start != end:
        raise ValueError('Загрузите реестр за один день: сводный файл за несколько дней нельзя распределить по датам продаж')
    return start.isoformat()


def report_timestamp(day, company_timezone):
    """Keep daily revenue and stock on the same company-local reporting date."""
    # The source contains no individual receipt times; noon is the reporting convention.
    return datetime.fromisoformat(day).replace(hour=12, tzinfo=ZoneInfo(company_timezone)).isoformat()


def row_identity(row):
    code = norm(row.get('code') or '')
    if code:
        # Excel can serialize the same integer code as 10 or 10.0.
        return ('code', re.sub(r'^(\d+)\.0+$', r'\1', code))
    return ('name', norm(row.get('name') or row.get('recipeName') or ''), norm(row.get('unit') or '').rstrip('.'))


def posted_rows(state, branch, day):
    identities = set()
    for doc in state.get('externalSalesImports', []):
        if doc.get('branchId') != branch or doc.get('status', 'posted') != 'posted':
            continue
        try:
            doc_day = report_date(doc.get('title', ''))
        except ValueError:
            # Existing unsupported historical documents are left untouched.
            continue
        if doc_day == day:
            identities.update(row_identity(row) for row in doc.get('items', []))
    return identities


def saved_mappings(state, branch):
    """Only previously posted, unambiguous choices may prefill another daily file."""
    mappings = {}
    for doc in state.get('externalSalesImports', []):
        if doc.get('branchId') != branch or doc.get('status', 'posted') != 'posted':
            continue
        for row in doc.get('items', []):
            key = row_identity(row)
            if key[0] != 'code':
                continue
            target = ('product:' + str(row['productId'])) if row.get('productId') is not None else str(row['recipeId']) if row.get('recipeId') is not None else None
            if target is not None:
                mappings.setdefault(key, set()).add(target)
    return mappings


def parse(encoded):
    if not isinstance(encoded, str) or len(encoded) > 3_000_000:
        raise ValueError('Размер файла должен быть не больше 2 МБ')
    try:
        raw = base64.b64decode(encoded, validate=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(x.file_size for x in archive.infolist()) > 20_000_000:
                raise ValueError('Слишком большой распакованный файл')
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            def xml(path):
                data = archive.read(path)
                if b'<!DOCTYPE' in data or b'<!ENTITY' in data:
                    raise ValueError('Неподдерживаемый XML')
                return ET.fromstring(data)
            strings = [''.join(t.text or '' for t in x.findall('.//s:t', ns)) for x in xml('xl/sharedStrings.xml').findall('s:si', ns)] if 'xl/sharedStrings.xml' in archive.namelist() else []
            rows = []
            for row in xml('xl/worksheets/sheet1.xml').findall('.//s:sheetData/s:row', ns):
                cells = {}
                for cell in row.findall('s:c', ns):
                    value = cell.find('s:v', ns)
                    value = value.text if value is not None else ''
                    if cell.get('t') == 's': value = strings[int(value)]
                    elif cell.get('t') == 'inlineStr': value = ''.join(t.text or '' for t in cell.findall('.//s:t', ns))
                    cells[re.sub(r'\d', '', cell.get('r', ''))] = value or ''
                rows.append((int(row.get('r')), cells))
    except (KeyError, IndexError, TypeError, zipfile.BadZipFile, ET.ParseError, ValueError) as error:
        raise ValueError('Не удалось прочитать Excel: нужен реестр «Склад/Блюдо, Код, Ед. изм, Количество, Цена, Сумма»') from error
    if not any(norm(c.get('I')) == 'количество' and norm(c.get('K')) == 'сумма' and norm(c.get('H')) in {'ед. изм', 'ед. изм.'} for _, c in rows):
        raise ValueError('Не найдены столбцы реестра продаж')
    title = next((c.get('A') for _, c in rows if norm(c.get('A', '')).startswith('реестр продаж')), '')
    if not title: raise ValueError('В реестре не указан период продаж')
    day = report_date(title)
    result = []
    for number, c in rows:
        if not c.get('B', '').strip() or not c.get('F', '').strip(): continue
        try:
            quantity, total = float(c['I']), float(c['K'])
            if not all(math.isfinite(x) and x >= 0 for x in [quantity, total]): raise ValueError()
        except (KeyError, ValueError): raise ValueError(f'Некорректное количество или сумма в строке {number}')
        if quantity == 0: continue
        result.append({'row': str(number), 'name': c['B'].strip(), 'code': c['F'], 'unit': c.get('H', '').strip(), 'quantity': quantity, 'total': total})
    if not result or len(result) > 1000: raise ValueError('В файле должно быть от 1 до 1000 строк продаж')
    identities = [row_identity(row) for row in result]
    if len(set(identities)) != len(identities):
        raise ValueError('В реестре повторяются коды товаров. Объедините продажи каждого товара за день в одну строку')
    semantic = [{k: v for k, v in r.items() if k != 'row'} for r in result]
    for index, row in enumerate(result): row['sourceKey'] = str(index)
    digest = hashlib.sha256(json.dumps([title, semantic], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'title': title, 'date': day, 'digest': digest, 'rows': result}


def lots(state, branch, recipe):
    for batch in reversed(state['logisticsState']['batches']):
        if batch.get('branchId') != branch or batch.get('status') == 'closed' or str(batch.get('recipeId')) != str(recipe['id']): continue
        for lot in batch.get('servingLots', []):
            available = custody.lot_available(lot)
            if available > 0 and custody.portion_weight(batch, recipe) > 0:
                yield batch, lot, available


def preview(state, branch, encoded):
    data = parse(encoded)
    posted = posted_rows(state, branch, data['date'])
    from .workspace import _stock
    recipes = state['recipes']
    products = state.get('products', [])
    mappings = saved_mappings(state, branch)
    current_targets = {str(recipe['id']) for recipe in recipes} | {'product:' + str(product['id']) for product in products}
    for row in data['rows']:
        previous_targets = mappings.get(row_identity(row))
        row['recipeId'] = ''
        if previous_targets is not None:
            if len(previous_targets) == 1 and next(iter(previous_targets)) in current_targets:
                row['recipeId'] = next(iter(previous_targets))
                row['mappingSaved'] = True
        else:
            matches = [r for r in recipes if norm(r['name']) == norm(row['name'])]
            row['recipeId'] = str(matches[0]['id']) if len(matches) == 1 else ''
            product_matches = [p for p in products if norm(p['name']) == norm(row['name'])]
            if not matches and len(product_matches) == 1: row['recipeId'] = 'product:' + str(product_matches[0]['id'])
        if not row['unit'] and row['recipeId']:
            matched_product = next((product for product in products if 'product:' + str(product['id']) == row['recipeId']), None)
            row['unit'] = matched_product.get('unit', 'шт') if matched_product else 'порция'
            row['unitInferred'] = True
        row['posted'] = row_identity(row) in posted
    data['recipes'] = [{'id': str(r['id']), 'name': r['name'], 'availablePortions': round(sum(w * 1000 / custody.portion_weight(b, r) for b, _, w in lots(state, branch, r)), 3)} for r in recipes]
    data['recipes'] += [{'id': 'product:' + str(p['id']), 'name': p['name'], 'availablePortions': _stock(state, branch, p['id']), 'unit': p.get('unit', 'шт')} for p in products]
    return data


def commit(state, user, payload):
    from .workspace import WorkspaceError, _stock, _set_stock, _cost, _ledger, _require_unlocked
    if user.get('role') != 'branch' or user.get('staff_role') not in {'cashier', 'branch_manager', 'hall_admin'} or not user.get('shift_id'):
        raise WorkspaceError('Импорт доступен кассиру на открытой смене', 403)
    if user.get('plan_code') == 'restaurant': raise WorkspaceError('Этот импорт списывает блюда с раздачи столовой', 403)
    branch = user['branch_id']
    _require_unlocked(state, branch)
    try: data = parse(payload.get('file'))
    except ValueError as error: raise WorkspaceError(str(error), 422) from error
    selections = payload.get('selections')
    if not isinstance(selections, list) or not 0 < len(selections) <= 1000: raise WorkspaceError('Выберите строки для списания')
    rows = {r['row']: r for r in data['rows']}
    posted = posted_rows(state, branch, data['date'])
    from .company_settings import company_settings
    general = company_settings(state)['general']
    occurred_at = report_timestamp(data['date'], general['timezone'])
    draft = deepcopy(state)
    output, seen = [], set()
    for selection in selections:
        if not isinstance(selection, dict): raise WorkspaceError('Некорректная строка импорта')
        key = str(selection.get('row'))
        if key in seen or (rows.get(key) and row_identity(rows[key]) in posted): raise WorkspaceError('Продажи этого товара за выбранный день уже проведены или повторяются', 409)
        seen.add(key)
        row = rows.get(key)
        product = next((p for p in draft.get('products', []) if 'product:' + str(p['id']) == str(selection.get('recipeId'))), None)
        if row and product:
            if not row['unit']: row = {**row, 'unit': product.get('unit', 'шт'), 'unitInferred': True}
            if norm(row['unit']).rstrip('.') != norm(product.get('unit', 'шт')).rstrip('.'): raise WorkspaceError('Единица товара должна совпадать с файлом: ' + product['name'])
            quantity = row['quantity']
            if not product.get('weighted') and not float(quantity).is_integer(): raise WorkspaceError('Штучный товар должен иметь целое количество')
            _require_unlocked(draft, branch)
            if quantity > _stock(draft, branch, product['id']): raise WorkspaceError('Недостаточно остатка: ' + product['name'], 409)
            cost = _cost(draft, branch, product['id'])
            _set_stock(draft, branch, product['id'], _stock(draft, branch, product['id']) - quantity)
            _ledger(draft, branch_id=branch, item_id=product['id'], quantity=-quantity, unit_cost=cost, movement_type='sale', document_number=data['title'], actor=user.get('display_name', ''))
            draft['logisticsState']['stockLedger'][0]['effectiveAt'] = occurred_at
            output.append({**row, 'sourceRow': key, 'productId': product['id'], 'recipeName': product['name'], 'unitCost': cost, 'allocations': []})
            continue
        recipe = next((r for r in draft['recipes'] if str(r['id']) == str(selection.get('recipeId'))), None)
        if not row or not recipe: raise WorkspaceError('Сопоставьте каждую выбранную строку с блюдом')
        if not row['unit']: row = {**row, 'unit': 'порция', 'unitInferred': True}
        unit = norm(row['unit'])
        if unit not in {'шт', 'шт.', 'пор', 'пор.', 'порция', 'кг', 'г'}: raise WorkspaceError(f'{row["name"]}: единица {unit} не поддерживается')
        by_weight = unit in {'кг', 'г'}
        remaining = row['quantity'] / (1000 if unit == 'г' else 1)
        allocations = []
        for batch, lot, available in lots(draft, branch, recipe):
            portion = custody.portion_weight(batch, recipe) / 1000
            capacity = available if by_weight else available / portion
            take = min(remaining, capacity)
            weight = take if by_weight else take * portion
            lot['soldWeight'] = float(lot.get('soldWeight', 0)) + weight
            batch['soldPortions'] = float(batch.get('soldPortions', 0)) + weight / portion
            batch['servedPortions'] = batch['soldPortions']
            allocations.append({'batchId': batch['id'], 'batchNumber': batch.get('number'), 'lotId': lot['id'], 'weight': weight, 'portions': weight / portion, 'quantity': weight / portion, 'responsibleId': lot.get('responsibleId'), 'responsibleName': lot.get('responsibleName'), 'line': lot.get('line')})
            remaining -= take
            if remaining < 1e-7: break
        if remaining > 1e-7: raise WorkspaceError(f'{recipe["name"]}: на принятой раздаче недостаточно, не хватает {remaining:.3f} {"кг" if by_weight else "порций"}', 409)
        output.append({**row, 'sourceRow': key, 'recipeId': recipe['id'], 'recipeName': recipe['name'], 'allocations': allocations})
    doc = {'id': 'external-sales-' + str(uuid4()), 'branchId': branch, 'digest': data['digest'], 'title': data['title'], 'reportDate': data['date'], 'fileName': str(payload.get('fileName', ''))[:200], 'createdAt': datetime.now(timezone.utc).isoformat(), 'createdById': user['id'], 'createdBy': user.get('display_name', user.get('login')), 'shiftId': user['shift_id'], 'items': output, 'total': round(sum(r['total'] for r in output), 2), 'status': 'posted', 'paymentRecorded': False}
    doc.update(currency=general['currency'], timezone=general['timezone'])
    draft.setdefault('externalSalesImports', []).append(doc)
    materialize_sales(draft)
    state.clear(); state.update(draft)
    return 'external_sales_import', doc['id']


def materialize_sales(state):
    """Create reporting sales for posted imports without touching inventory twice."""
    from .company_settings import company_settings
    general = company_settings(state)['general']
    for doc in state.get('externalSalesImports', []):
        sale_id = 'sale-' + doc['id']
        if any(s.get('id') == sale_id for s in state['sales']): continue
        try:
            day = report_date(doc['title'])
        except ValueError:
            # Do not silently date an unsupported legacy report or block new imports.
            continue
        occurred = report_timestamp(day, doc.get('timezone') or general['timezone'])
        items = []
        for row in doc['items']:
            cost = row.get('unitCost', 0) * row['quantity']
            for allocation in row.get('allocations', []):
                batch = next((b for b in state['logisticsState']['batches'] if b['id'] == allocation['batchId']), {})
                cost += float(batch.get('cost', 0)) * allocation['weight'] / max(float(batch.get('actualWeight', 0)), .000001)
            items.append({'id': row.get('productId', row.get('recipeId')), 'name': row['recipeName'], 'category': '', 'unit': row['unit'], 'quantity': row['quantity'], 'price': row['total']/row['quantity'], 'total': row['total'], 'unitCost': cost/row['quantity'], 'batchAllocations': row.get('allocations', []), 'ingredientAllocations': []})
        branch = next((b for b in state['branches'] if b['id'] == doc['branchId']), {})
        state['sales'].insert(0, {'id': sale_id, 'number': max([int(s.get('number', 0)) for s in state['sales'] if s.get('branchId') == doc['branchId']] or [0])+1, 'branchId': doc['branchId'], 'branch': branch.get('name', ''), 'cashier': 'Внешняя касса', 'cashierId': None, 'registerId': None, 'shiftId': None, 'createdAt': occurred, 'source': 'external', 'importId': doc['id'], 'importedAt': doc['createdAt'], 'paymentMethod': 'external', 'payments': [{'method': 'external', 'amount': doc['total']}], 'subtotal': doc['total'], 'discountAmount': 0, 'discountPercent': 0, 'total': doc['total'], 'received': doc['total'], 'change': 0, 'currency': doc.get('currency') or general['currency'], 'comment': doc['title'] + ' · ' + doc.get('fileName', ''), 'items': items})
        doc['saleId'] = sale_id
