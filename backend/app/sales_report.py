"""Terminal sales reports and dependency-free Office Open XML export."""
import base64
import io
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from xml.sax.saxutils import escape


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def _cashier_key(sale):
    if sale.get('paymentMethod') == 'external':
        return 'name:Внешняя касса'
    actor_id = sale.get('cashierId')
    return str(actor_id) if actor_id is not None and actor_id != '' else 'name:' + str(sale.get('cashier') or '')


def _report_cashiers(sales, accounts):
    """Resolve immutable actor IDs; receipt names remain unchanged in storage."""
    accounts = {str(account['id']): account for account in (accounts or [])}
    cashiers = {}
    # Workspace sales are usually newest first. Do not let older snapshots
    # overwrite a later name, even after an import changes the list order.
    for sale in sorted(sales, key=lambda row: (
        timestamp(row.get('createdAt')) or datetime.min.replace(tzinfo=timezone.utc),
        str(row.get('id') or ''), str(row.get('cashier') or ''),
    ), reverse=True):
        key = _cashier_key(sale)
        if key in cashiers:
            continue
        historical_name = str(sale.get('cashier') or '').strip() or 'Неизвестный кассир'
        account = accounts.get(key)
        if sale.get('paymentMethod') == 'external':
            name, status = 'Внешняя касса', 'external'
        elif account:
            name = str(account.get('display_name') or '').strip() or historical_name
            status = 'deleted' if account.get('deleted_at') else ('active' if account.get('is_active') else 'inactive')
        else:
            name, status = historical_name, 'archived'
        cashiers[key] = {'id': key, 'displayName': name, 'historicalName': historical_name, 'status': status}
    duplicate_names = Counter(row['displayName'].casefold() for row in cashiers.values())
    suffixes = {'deleted': 'удалён', 'inactive': 'доступ отключён', 'archived': 'архив'}
    for row in cashiers.values():
        label = row['displayName']
        if duplicate_names[label.casefold()] > 1 and not row['id'].startswith('name:'):
            label += ' · №' + row['id']
        if row['status'] in suffixes:
            label += ' · ' + suffixes[row['status']]
        row['name'] = label
    return sorted(cashiers.values(), key=lambda row: (row['displayName'].casefold(), row['id']))


def build_report(state, branch_id, start, end, cashier='', cashier_accounts=None):
    if not start.tzinfo or not end.tzinfo or start > end:
        raise ValueError('Укажите корректный период с часовым поясом')
    branch_sales = [s for s in state.get('sales', []) if str(s.get('branchId')) == str(branch_id)]
    cashiers = _report_cashiers(branch_sales, cashier_accounts)
    labels = {row['id']: row['name'] for row in cashiers}
    if cashier and cashier not in labels:
        raise ValueError('Кассир не найден в истории продаж этого заведения')
    selected = [s for s in branch_sales if not cashier or _cashier_key(s) == cashier]
    within = lambda value: (date := timestamp(value)) is not None and start <= date <= end
    sold = [s for s in selected if within(s.get('createdAt'))]
    returned = [s for s in selected if s.get('refundedAt') and within(s['refundedAt'])]
    dec = lambda value: Decimal(str(value or 0))
    total = lambda rows, field: sum((dec(s.get(field)) for s in rows), Decimal(0))
    methods = {}
    for method in ('cash', 'card', 'qr', 'external'):
        def amount(rows):
            return sum((dec(p.get('amount')) for s in rows for p in (s.get('payments') or [{'method': s.get('paymentMethod'), 'amount': s.get('total')}]) if p.get('method') == method), Decimal(0))
        methods[method] = float(amount(sold) - amount(returned))
    products = {}
    for rows, sign in ((sold, 1), (returned, -1)):
        for sale in rows:
            for item in sale.get('items', []):
                price = dec(item.get('price'))
                group = (str(item.get('id')), item.get('name', '—'), item.get('unit', 'порция'), price)
                row = products.setdefault(group, {'name': group[1], 'unit': group[2], 'price': float(price), 'quantity': Decimal(0), 'total': Decimal(0)})
                qty = dec(item.get('quantity')) * sign
                row['quantity'] += qty
                row['total'] += dec(item.get('total', dec(item.get('quantity')) * price)) * sign
    branch = next((b.get('name') for b in state.get('branches', []) if str(b.get('id')) == str(branch_id)), 'Заведение')
    return {'branch': branch, 'from': start.isoformat(), 'to': end.isoformat(), 'cashier': labels.get(cashier, 'Все кассиры'), 'cashiers': cashiers, 'count': sum(s.get('paymentMethod') != 'external' for s in sold), 'importCount': sum(s.get('paymentMethod') == 'external' for s in sold), 'refundCount': len(returned), 'gross': float(total(sold, 'subtotal')), 'discount': float(total(sold, 'discountAmount')), 'sales': float(total(sold, 'total')), 'refunds': float(total(returned, 'total')), 'net': float(total(sold, 'total') - total(returned, 'total')), 'payments': methods, 'products': [{**r, 'quantity': float(r['quantity']), 'total': float(r['total'])} for r in sorted(products.values(), key=lambda r: r['name'])], 'currency': next((s.get('currency') for s in sold + returned if s.get('currency')), 'KGS')}


def workbook(report, products=True):
    rows = [['Отчёт по продажам'], ['Заведение', report['branch']], ['С', report['from']], ['По', report['to']], ['Кассир', report['cashier']], ['Валюта', report['currency']], [], ['Чеков', report['count']], ['Возвратов', report['refundCount']], ['Продажи до скидок', report['gross']], ['Скидки', report['discount']], ['Оплачено', report['sales']], ['Возвращено', report['refunds']], ['Выручка с учётом возвратов', report['net']], ['Наличные', report['payments']['cash']], ['Карта', report['payments']['card']], ['QR', report['payments']['qr']]]
    rows += [['Импортированных реестров', report.get('importCount', 0)], ['Внешняя касса', report['payments'].get('external', 0)]]
    if products:
        rows += [[], ['Продажи по товарам с учётом возвратов, до скидок'], ['Наименование', 'Ед.', 'Количество', 'Цена', 'Сумма']]
        rows += [[r['name'], r['unit'], r['quantity'], r['price'], r['total']] for r in report['products']]
    def cell(value, ref):
        if isinstance(value, (int, float)):
            return f'<c r="{ref}"><v>{value}</v></c>'
        value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value))
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'
    sheet = ''.join(f'<row r="{i}">' + ''.join(cell(v, f'{chr(65+j)}{i}') for j, v in enumerate(row)) + '</row>' for i, row in enumerate(rows, 1))
    files = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Продажи" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols><col min="1" max="1" width="48" customWidth="1"/><col min="2" max="5" width="24" customWidth="1"/></cols><sheetData>' + sheet + '</sheetData></worksheet>'}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + content)
    return base64.b64encode(buffer.getvalue()).decode('ascii')
