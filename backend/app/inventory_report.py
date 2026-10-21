"""Read-only inventory reports and dependency-free Office Open XML export."""
import base64
import io
import math
import re
import zipfile
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

from .inventory_count import variance


STATUSES = {
    'counting': 'Идёт подсчёт', 'submitted': 'На проверке',
    'returned': 'На пересчёте', 'posted': 'Проведена', 'cancelled': 'Отменена',
}
BUCKETS = {'incoming': 'Приход', 'outgoing': 'Расход', 'writeoff': 'Списание', 'adjustment': 'Корректировка'}
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def _number(value):
    if value is None or value == '':
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not math.isfinite(float(number)):
            raise ValueError
        return number
    except (InvalidOperation, TypeError, ValueError, OverflowError) as error:
        raise ValueError('Количество должно быть конечным числом') from error


def _product(left, right):
    return None if left is None or right is None else left * right


def build_report(state, inventory_id, items=None):
    """Use persisted snapshots; accept only actual counts from an editable draft."""
    inventory = next((row for row in state.get('logisticsState', {}).get('inventories', [])
                      if str(row.get('id')) == str(inventory_id)), None)
    if inventory is None:
        raise LookupError('Инвентаризация не найдена')
    if items is not None and not isinstance(items, list):
        raise ValueError('Передайте список фактических остатков')
    if items and inventory.get('status') not in {'counting', 'returned'}:
        raise ValueError('Фактические остатки можно менять только в черновике')
    known = {str(item['itemId']) for item in inventory.get('items', [])}
    actuals = {}
    for item in items or []:
        if not isinstance(item, dict) or 'actual' not in item:
            raise ValueError('Укажите позицию и фактический остаток')
        item_id = str(item.get('itemId', ''))
        if item_id not in known or item_id in actuals:
            raise ValueError('Позиция отсутствует в инвентаризации или указана повторно')
        actual = _number(item['actual'])
        if actual is not None and actual < 0:
            raise ValueError('Фактический остаток должен быть числом не меньше нуля')
        actuals[item_id] = actual
    catalog = {str(item['id']): item for item in [*state.get('ingredients', []), *state.get('products', [])]}
    rows, movements = [], []
    for item in inventory.get('items', []):
        item_id = str(item['itemId'])
        entity = catalog.get(item_id, {})
        summary = item.get('movementSummary') or {}
        available = summary.get('available') is True
        actual = actuals.get(item_id, _number(item.get('actual')))
        book, cost = _number(item.get('book')), _number(item.get('unitCost'))
        difference = None if actual is None or book is None else Decimal(str(variance(actual, book)))
        row = {
            'itemId': item_id, 'name': item.get('name') or entity.get('name') or item_id,
            'unit': item.get('unit') or entity.get('unit') or '',
            'lastCountAt': summary.get('lastCountAt') if available else None,
            'historyAvailable': available, 'book': book, 'unitCost': cost,
            'bookCost': _product(book, cost), 'actual': actual,
            'actualCost': _product(actual, cost), 'variance': difference,
            'varianceCost': _product(difference, cost),
        }
        for key in ('opening', 'incoming', 'outgoing', 'writtenOff', 'writtenOffCost', 'adjustments'):
            row[key] = _number(summary.get(key)) if available else None
        rows.append(row)
        if available:
            for entry in summary.get('entries', []):
                movements.append({**entry, 'name': row['name'], 'unit': row['unit']})
    surplus = sum((row['varianceCost'] for row in rows if row['varianceCost'] is not None and row['varianceCost'] > 0), Decimal(0))
    shortage = -sum((row['varianceCost'] for row in rows if row['varianceCost'] is not None and row['varianceCost'] < 0), Decimal(0))
    branch = next((b for b in state.get('branches', []) if str(b.get('id')) == str(inventory.get('branchId'))), {})
    return {
        'number': inventory.get('number', inventory_id), 'branch': branch.get('name', inventory.get('branchId', '')),
        'status': STATUSES.get(inventory.get('status'), inventory.get('status', '')),
        'countedAt': inventory.get('countedAt') or inventory.get('createdAt', ''),
        'responsible': inventory.get('responsible') or inventory.get('createdBy', ''),
        'scope': inventory.get('category', '') if inventory.get('scope') == 'category' else
                 {'selected': 'Выбранные позиции', 'serving': 'Раздача'}.get(inventory.get('scope'), 'Полная'),
        'comment': inventory.get('comment', ''), 'items': rows, 'movements': movements,
        'totals': {'counted': sum(row['actual'] is not None for row in rows), 'surplus': surplus,
                   'shortage': shortage, 'net': surplus - shortage},
    }


def filename(report):
    number = re.sub(r'[^\w-]+', '-', str(report['number']), flags=re.UNICODE).strip('-')[:100]
    return 'inventory-' + (number or 'report') + '.xlsx'


def _column(index):
    result = ''
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(65 + digit) + result
    return result


def _text(value):
    # XML 1.0 permits tabs/newlines and Unicode text, but not controls/surrogates.
    return escape(re.sub(r'[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]', '', str(value)))


def _sheet(rows, header_row, data_end, money_columns, widths):
    def cell(value, row_number, col):
        ref = f'{_column(col)}{row_number}'
        if value is None:
            return f'<c r="{ref}"/>'
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            number = _number(value)
            style = 2 if col in money_columns or (row_number > data_end and isinstance(value, Decimal)) else 3
            return f'<c r="{ref}" s="{style}"><v>{number}</v></c>'
        style = ' s="1"' if row_number in {1, header_row} else ''
        return f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{_text(value)}</t></is></c>'
    content = ''.join(f'<row r="{i}">' + ''.join(cell(value, i, col) for col, value in enumerate(row, 1)) + '</row>'
                      for i, row in enumerate(rows, 1))
    columns = ''.join(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths, 1))
    last_column = _column(max(len(row) for row in rows))
    return (f'<worksheet xmlns="{NS}"><dimension ref="A1:{last_column}{len(rows)}"/>'
            f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{header_row}" topLeftCell="A{header_row + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            '<sheetFormatPr defaultRowHeight="18"/>'
            f'<cols>{columns}</cols><sheetData>{content}</sheetData>'
            f'<autoFilter ref="A{header_row}:{last_column}{max(header_row, data_end)}"/></worksheet>')


def workbook(report):
    headers = ['№', 'Наименование', 'Ед.', 'Последняя инвентаризация', 'Начальный остаток',
               'Приход', 'Расход без списаний', 'Списано', 'Стоимость списаний', 'Корректировки',
               'Учётный остаток', 'Себестоимость единицы', 'Учётная стоимость', 'Фактический остаток',
               'Фактическая стоимость', 'Расхождение, количество', 'Расхождение, стоимость']
    fields = ['name', 'unit', 'lastCountAt', 'opening', 'incoming', 'outgoing', 'writtenOff',
              'writtenOffCost', 'adjustments', 'book', 'unitCost', 'bookCost', 'actual',
              'actualCost', 'variance', 'varianceCost']
    note = 'Пустые ячейки истории означают, что снимок движений недоступен.' if any(not row['historyAvailable'] for row in report['items']) else ''
    rows = [['Инвентаризация'], ['Номер документа', report['number']], ['Заведение', report['branch']],
            ['Статус', report['status']], ['Дата подсчёта', report['countedAt']],
            ['Ответственный', report['responsible']], ['Область проверки', report['scope']],
            ['Комментарий', report['comment']], [note], [], headers]
    header_row = len(rows)
    rows += [[index, *(row[key] for key in fields)] for index, row in enumerate(report['items'], 1)]
    data_end = len(rows)
    totals = report['totals']
    rows += [[], ['Подсчитано позиций', totals['counted']], ['Всего позиций', len(report['items'])],
             ['Излишки, стоимость', totals['surplus']], ['Недостача, стоимость', totals['shortage']],
             ['Итоговое расхождение, стоимость', totals['net']]]
    sheets = [('Инвентаризация', _sheet(rows, header_row, data_end, {9, 12, 13, 15, 17},
                                      [7, 38, 9, 28, 20, 18, 22, 18, 24, 20, 22, 26, 24, 24, 26, 26, 28]))]
    if report['movements']:
        rows = [['Движения по снимку инвентаризации'], ['Номер документа', report['number']], [],
                ['Дата движения', 'Документ', 'Наименование', 'Ед.', 'Вид движения', 'Группа',
                 'Количество', 'Себестоимость единицы', 'Стоимость', 'Ответственный']]
        for entry in report['movements']:
            rows.append([entry.get('date'), entry.get('documentNumber'), entry['name'], entry['unit'],
                         entry.get('movementType'), BUCKETS.get(entry.get('bucket'), entry.get('bucket')),
                         _number(entry.get('quantity')), _number(entry.get('unitCost')),
                         _number(entry.get('cost')), entry.get('actor')])
        sheets.append(('Движения', _sheet(rows, 4, len(rows), {8, 9}, [28, 22, 38, 9, 28, 20, 20, 26, 24, 28])))
    types = ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1))
    relationships = ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
    files = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + types + '</Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1)) + '</sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + relationships + '<Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        'xl/styles.xml': f'<styleSheet xmlns="{NS}"><numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.###"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment wrapText="1"/></xf><xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
        **{f'xl/worksheets/sheet{i}.xml': sheet for i, (_, sheet) in enumerate(sheets, 1)},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + content)
    return base64.b64encode(buffer.getvalue()).decode('ascii')
