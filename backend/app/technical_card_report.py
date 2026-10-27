"""Technical cards and preparations and dependency-free Office Open XML export."""
import base64
import io
import math
import re
import zipfile
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def _number(value):
    if value is None or value == '':
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not math.isfinite(float(number)):
            raise ValueError
        return number
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        raise ValueError('Количество должно быть конечным числом')


def _column(index):
    result = ''
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(65 + digit) + result
    return result


def _text(value):
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


def _money(value):
    return float(Decimal(str(value or 0)))


def filename(count):
    return f'техкарты-{count}.xlsx'


def workbook(recipes, preparations, ingredients_by_id):
    items = []
    for recipe in recipes:
        items.append({**recipe, 'kind': 'техкарта'})
    for preparation in preparations:
        items.append({**preparation, 'kind': 'полуфабрикат'})
    rows = [['Технологические карты и полуфабрикаты'], ['Всего позиций', len(items)], [], ['№', 'Вид', 'Наименование', 'Категория', 'Цех', 'Выход, г', 'Цена продажи', 'Компонентов']]
    header_row = len(rows)
    for index, item in enumerate(items, 1):
        components = item.get('components', []) or []
        rows.append([
            index,
            item.get('kind', ''),
            item.get('name', ''),
            item.get('category', ''),
            item.get('station', ''),
            _number(item.get('yield')),
            _money(item.get('price')),
            len(components),
        ])
    data_end = len(rows)
    sheets = [('Техкарты', _sheet(rows, header_row, data_end, {6}, [6, 16, 40, 20, 20, 12, 16, 12]))]

    rows = [['Состав'], [], ['Карта', 'Вид', 'Категория', 'Ингредиент', 'Брутто', 'Нетто', 'Ед.', 'Себестоимость, ед.', 'Сумма строки', 'Цех', 'Выход', 'Цена продажи', 'Процесс', 'Используется в', 'Масса нетто г', 'Масса штуки г']]
    header_row = len(rows)
    data_end = header_row
    for index, item in enumerate(items, 1):
        card_name = item.get('name', '')
        kind = item.get('kind', '')
        for component in item.get('components', []) or []:
            ingredient = ingredients_by_id.get(str(component.get('ingredientId')), {})
            unit = ingredient.get('unit', '')
            unit_cost = _number(ingredient.get('averageCost'))
            line_cost = (unit_cost or Decimal(0)) * _number(component.get('gross') or 0) / 1000
            rows.append([
                card_name,
                kind,
                item.get('category', ''),
                ingredient.get('name', str(component.get('ingredientId', ''))),
                _number(component.get('gross') or 0) / (1000 if unit == 'шт' else 1),
                _number(component.get('net') or 0) / (1000 if unit == 'шт' else 1),
                {'кг': 'г', 'л': 'мл'}.get(unit, unit),
                unit_cost / 1000 if unit_cost is not None and unit != 'шт' else unit_cost,
                _money(line_cost),
                item.get('station', ''),
                _number(item.get('yield')),
                _number(item.get('price')),
                item.get('process', ''),
                item.get('usedIn', ''),
                _number(component.get('netWeightGrams')),
                _number(component.get('pieceWeightGrams') or ingredient.get('pieceWeightGrams')),
            ])
            data_end += 1
    sheets.append(('Состав', _sheet(rows, header_row, data_end, {7, 8}, [40, 12, 40, 40, 12, 12, 10, 16, 16])))

    types = ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1))
    relationships = ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
    files = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + types + '</Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1)) + '</sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + relationships + '<Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        'xl/styles.xml': f'<styleSheet xmlns="{NS}"><numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.###"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellStyleXfs><cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment wrapText="1"/></xf><xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
        **{f'xl/worksheets/sheet{i}.xml': sheet for i, (_, sheet) in enumerate(sheets, 1)},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + content)
    return base64.b64encode(buffer.getvalue()).decode('ascii')
