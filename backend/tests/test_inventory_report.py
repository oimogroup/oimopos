import base64
from copy import deepcopy
from decimal import Decimal
import io
from types import SimpleNamespace
from xml.etree import ElementTree as ET
import zipfile

from fastapi import HTTPException, Request
import pytest

from app import main
from app.inventory_count import variance
from app.inventory_report import build_report, filename, workbook
from app.workspace import default_state


NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REQUEST = Request({'type': 'http', 'headers': [(b'origin', b'http://127.0.0.1:8000')]})


@pytest.fixture
def state():
    state = default_state()
    state['logisticsState']['inventories'] = [{
        'id': 'count-1', 'number': 'ИНВ-0007', 'branchId': 'b1', 'status': 'counting',
        'countedAt': '2026-09-29T14:30:00+06:00', 'createdAt': '2026-09-30T08:30:00Z',
        'responsible': 'Айгүл', 'scope': 'full', 'comment': 'Проверка склада',
        'items': [
            {'itemId': 'p-1', 'name': '=Чай & кофе <新> ☕\x00\ud800', 'unit': 'кг',
             'book': 12, 'actual': 10, 'unitCost': 3.5,
             'movementSummary': {
                 'available': True, 'lastCountAt': '2026-09-01T12:00:00Z',
                 'opening': 10, 'incoming': 8, 'outgoing': 3, 'writtenOff': 2,
                 'writtenOffCost': 7, 'adjustments': -1,
                 'entries': [{'date': '2026-09-20T10:00:00Z', 'documentNumber': 'СП-1',
                              'movementType': 'writeoff', 'bucket': 'writeoff', 'quantity': 2,
                              'unitCost': 3.5, 'cost': 7, 'actor': 'Айгүл'}],
             }},
            {'itemId': 'removed-product', 'name': 'Архивный товар', 'unit': 'шт',
             'book': 2, 'actual': 3, 'unitCost': 4},
            {'itemId': 'uncounted', 'name': 'Ещё не подсчитано', 'unit': 'кг',
             'book': 1000, 'actual': None, 'unitCost': 100},
        ],
    }]
    return state


def sheets(report):
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(workbook(report)))) as archive:
        assert archive.testzip() is None
        # Every package part must be valid XML, including relationships/styles.
        parsed = {name: ET.fromstring(archive.read(name)) for name in archive.namelist()}
        assert all(not root.findall('.//s:f', NS) for root in parsed.values())
        return parsed


def value(sheet, reference):
    cell = sheet.find(f'.//s:c[@r="{reference}"]', NS)
    if cell is None:
        return None
    number = cell.find('s:v', NS)
    if number is not None:
        return Decimal(number.text)
    text = cell.find('s:is/s:t', NS)
    return text.text if text is not None else None


def test_complete_xlsx_preserves_snapshot_movements_and_missing_counts(state):
    before = deepcopy(state)
    report = build_report(state, 'count-1')
    assert state == before
    assert len(report['items']) == 3
    assert report['totals'] == {'counted': 2, 'surplus': 4, 'shortage': 7, 'net': -3}
    first = report['items'][0]
    # Outgoing excludes writeoffs; neither report totals nor book stock reapply them.
    assert first['book'] == first['opening'] + first['incoming'] - first['outgoing'] - first['writtenOff'] + first['adjustments'] == 12
    assert first['writtenOffCost'] == 7 and first['varianceCost'] == -7
    package = sheets(report)
    sheet = package['xl/worksheets/sheet1.xml']
    assert value(sheet, 'B2') == 'ИНВ-0007'
    assert value(sheet, 'B5') == '2026-09-29T14:30:00+06:00'
    assert value(sheet, 'B6') == 'Айгүл'
    assert value(sheet, 'B12') == '=Чай & кофе <新> ☕'
    assert sheet.find('.//s:c[@r="B12"]', NS).get('t') == 'inlineStr'
    assert value(sheet, 'E12') == 10
    assert value(sheet, 'G12') == 3
    assert value(sheet, 'H12') == 2
    assert value(sheet, 'I12') == 7
    assert value(sheet, 'K12') == 12
    assert value(sheet, 'N12') == 10
    assert value(sheet, 'O12') == 35
    assert value(sheet, 'P12') == -2
    assert value(sheet, 'Q12') == -7
    assert value(sheet, 'B13') == 'Архивный товар'
    assert all(value(sheet, column + '13') is None for column in ('D', 'E', 'F', 'G', 'H', 'I', 'J'))
    assert all(value(sheet, column + '14') is None for column in ('N', 'O', 'P', 'Q'))
    movements = package['xl/worksheets/sheet2.xml']
    assert value(movements, 'B5') == 'СП-1'
    assert value(movements, 'F5') == 'Списание'
    assert value(movements, 'G5') == 2 and value(movements, 'I5') == 7


def test_draft_values_are_read_only_and_cannot_replace_server_snapshot(state):
    before = deepcopy(state)
    report = build_report(state, 'count-1', [
        {'itemId': 'p-1', 'actual': 0, 'book': 500, 'unitCost': 900, 'name': 'Forged',
         'movementSummary': {'available': True, 'incoming': 1000}},
        {'itemId': 'removed-product', 'actual': None},
    ])
    assert state == before
    assert report['items'][0]['actual'] == 0
    assert report['items'][0]['actualCost'] == 0
    assert report['items'][0]['book'] == 12
    assert report['items'][0]['unitCost'] == Decimal('3.5')
    assert report['items'][0]['incoming'] == 8
    assert report['items'][0]['name'] != 'Forged'
    assert report['items'][1]['actual'] is None
    assert report['totals'] == {'counted': 1, 'surplus': 0, 'shortage': 42, 'net': -42}


@pytest.mark.parametrize('actual,book', [(5.556, 5.5556), (5.555, 5.5556), (2.0004, 2), (0, 0.0005)])
def test_variance_uses_the_same_precision_rule_as_posting(state, actual, book):
    item = state['logisticsState']['inventories'][0]['items'][0]
    item.update(actual=actual, book=book)
    report = build_report(state, 'count-1')
    assert report['items'][0]['variance'] == Decimal(str(variance(actual, book)))
    assert report['items'][0]['varianceCost'] == Decimal(str(variance(actual, book))) * Decimal('3.5')


@pytest.mark.parametrize('overrides', [
    {}, [{'itemId': 'no-such-item', 'actual': 1}], [{'itemId': 'p-1', 'actual': -1}],
    [{'itemId': 'p-1', 'actual': 'NaN'}], [{'itemId': 'p-1', 'actual': 'Infinity'}],
    [{'itemId': 'p-1', 'actual': True}], [{'itemId': 'p-1'}],
    [{'itemId': 'p-1', 'actual': 1}, {'itemId': 'p-1', 'actual': 2}],
])
def test_invalid_actual_overrides_are_rejected(state, overrides):
    with pytest.raises(ValueError):
        build_report(state, 'count-1', overrides)


def test_final_documents_and_unavailable_history_are_preserved(state):
    inventory = state['logisticsState']['inventories'][0]
    inventory['status'] = 'posted'
    inventory['items'][0]['movementSummary']['writtenOffCost'] = None
    inventory['items'][1]['movementSummary'] = {'available': False, 'reason': 'serving_custody'}
    report = build_report(state, 'count-1')
    assert report['items'][0]['writtenOffCost'] is None
    assert report['items'][1]['opening'] is None
    assert report['status'] == 'Проведена'
    assert value(sheets(report)['xl/worksheets/sheet1.xml'], 'I12') is None
    with pytest.raises(ValueError):
        build_report(state, 'count-1', [{'itemId': 'p-1', 'actual': 1}])
    with pytest.raises(LookupError):
        build_report(state, 'missing')
    assert filename({'number': '../ИНВ-1\r\n/../../'}) == 'inventory-ИНВ-1.xlsx'


class ReadOnlyConnection:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def execute(self, sql, params):
        assert sql.strip().startswith('SELECT')
        assert 'FOR UPDATE' not in sql
        self.calls.append((sql, params))
        return SimpleNamespace(fetchone=lambda: {'payload': self.state})


def test_endpoint_exports_only_visible_branch_and_never_writes(state):
    before = deepcopy(state)
    connection = ReadOnlyConnection(state)
    user = {'id': 2, 'role': 'branch', 'staff_role': 'storekeeper', 'branch_id': 'b1', 'tenant_id': 't1'}
    response = main.export_inventory('count-1', {'items': [{'itemId': 'p-1', 'actual': 11}]}, REQUEST, user, connection)
    assert response['filename'] == 'inventory-ИНВ-0007.xlsx'
    assert base64.b64decode(response['xlsx']).startswith(b'PK')
    assert state == before and len(connection.calls) == 1
    assert connection.calls[0][1] == ('t1',)
    with pytest.raises(HTTPException) as denied:
        main.export_inventory('count-1', {}, REQUEST, {**user, 'branch_id': 'b2'}, connection)
    assert denied.value.status_code == 404


def test_endpoint_requires_inventory_permission_and_tenant(state):
    connection = ReadOnlyConnection(state)
    user = {'id': 2, 'role': 'branch', 'staff_role': 'cashier', 'branch_id': 'b1', 'tenant_id': 't1'}
    for unauthorized in (user, {**user, 'role': 'platform_owner'}, {**user, 'role': 'owner', 'tenant_id': None}):
        with pytest.raises(HTTPException) as denied:
            main.export_inventory('count-1', {}, REQUEST, unauthorized, connection)
        assert denied.value.status_code == 403
    assert connection.calls == []
    response = main.export_inventory('count-1', {}, REQUEST, {**user, 'role': 'owner'}, connection)
    assert response['xlsx']
