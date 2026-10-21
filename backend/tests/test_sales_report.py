import base64
import io
import zipfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET
import pytest
from app.sales_report import build_report, workbook


def test_report_period_branch_cashier_refunds_and_excel():
    start = datetime.fromisoformat('2026-09-21T00:00:00+06:00')
    end = datetime.fromisoformat('2026-09-21T23:59:59+06:00')
    sale = {'branchId':'b', 'cashierId':1, 'cashier':'Алия', 'createdAt':'2026-09-21T06:00:00Z', 'subtotal':100, 'discountAmount':10, 'total':90, 'payments':[{'method':'cash','amount':30},{'method':'card','amount':60}], 'items':[{'id':'x','name':'=Тест & кофе','unit':'шт','price':50,'quantity':2}]}
    previous = {**sale, 'createdAt':'2026-09-20T06:00:00Z','refundedAt':'2026-09-21T07:00:00Z'}
    state = {'branches':[{'id':'b','name':'Столовая'}], 'sales':[sale,previous,{**sale,'branchId':'other'}, {**sale,'cashierId':2,'cashier':'Бакыт'}]}
    r = build_report(state,'b',start,end,'1')
    assert (r['count'],r['refundCount'],r['sales'],r['refunds'],r['net']) == (1,1,90,90,0)
    assert r['payments'] == {'cash':0,'card':0,'qr':0,'external':0}
    assert r['products'][0]['quantity'] == 0
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(workbook(r)))) as z:
        for name in z.namelist(): ET.fromstring(z.read(name))
        sheet = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        assert not sheet.findall('.//s:f',ns)
        assert sheet.find('.//s:c[@r="B8"]/s:v',ns).text == '1'
    assert build_report(state,'b',start,end)['sales'] == 180
    with pytest.raises(ValueError): build_report(state,'b',end,start)


def test_mixed_payment_and_historical_prices():
    start=datetime.fromisoformat('2026-09-21T00:00:00+00:00'); end=datetime.fromisoformat('2026-09-22T00:00:00+00:00')
    sale={'branchId':'b','createdAt':start.isoformat(),'total':12.3,'subtotal':12.3,'payments':[{'method':'cash','amount':2.1},{'method':'card','amount':10.2}], 'items':[{'id':'a','name':'Чай','price':12.3,'quantity':1}]}
    r=build_report({'sales':[sale]},'b',start,end)
    assert r['payments']=={'cash':2.1,'card':10.2,'qr':0,'external':0}
    assert r['products'][0]['total']==12.3


START = datetime.fromisoformat('2026-10-06T00:00:00+05:00')
END = datetime.fromisoformat('2026-10-06T23:59:59.999999+05:00')


def receipt(**changes):
    return {'id': 'sale-1', 'branchId': 'b', 'cashierId': 4, 'cashier': 'Daison',
            'createdAt': START.isoformat(), 'paymentMethod': 'cash', 'subtotal': 100,
            'discountAmount': 0, 'total': 100, 'items': [], **changes}


def test_deleted_cashier_and_reused_login_remain_distinct_without_rewriting_history():
    state = {'sales': [receipt(), receipt(id='new-sale', cashierId=12, total=50)]}
    accounts = [
        {'id': 4, 'login': 'daison', 'display_name': 'Daison', 'is_active': False, 'deleted_at': START},
        {'id': 12, 'login': 'DAISON', 'display_name': 'Daison', 'is_active': True, 'deleted_at': None},
    ]
    before = deepcopy(state)
    deleted = build_report(state, 'b', START, END, '4', accounts)
    current = build_report(state, 'b', START, END, '12', accounts)
    assert (deleted['count'], deleted['sales'], current['count'], current['sales']) == (1, 100, 1, 50)
    assert deleted['cashier'] == 'Daison · №4 · удалён'
    assert current['cashier'] == 'Daison · №12'
    assert {row['id']: row['status'] for row in deleted['cashiers']} == {'4': 'deleted', '12': 'active'}
    assert state == before
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(workbook(deleted)))) as archive:
        assert 'Daison · №4 · удалён' in archive.read('xl/worksheets/sheet1.xml').decode()


@pytest.mark.parametrize('newest_first', [True, False])
def test_latest_receipt_name_is_stable_without_account_and_current_name_takes_precedence(newest_first):
    newest = receipt(id='new', cashier='Новое имя', createdAt=(START + timedelta(hours=2)).isoformat())
    oldest = receipt(id='old', cashier='Старое имя')
    state = {'sales': [newest, oldest] if newest_first else [oldest, newest]}
    historical = build_report(state, 'b', START, END, '4')
    assert historical['cashier'] == 'Новое имя · архив'
    account = {'id': 4, 'display_name': 'Актуальное имя', 'is_active': True}
    current = build_report(state, 'b', START, END, '4', [account])
    assert current['cashier'] == 'Актуальное имя'
    assert current['cashiers'][0]['historicalName'] == 'Новое имя'
    assert current['sales'] == historical['sales'] == 200


@pytest.mark.parametrize(('account', 'label', 'status'), [
    ({'is_active': True}, 'Daison', 'active'),
    ({'is_active': False}, 'Daison · доступ отключён', 'inactive'),
    ({'is_active': False, 'deleted_at': START}, 'Daison · удалён', 'deleted'),
    (None, 'Daison · архив', 'archived'),
])
def test_cashier_status_labels_do_not_remove_receipts(account, label, status):
    accounts = [{**account, 'id': 4, 'display_name': 'Daison'}] if account else []
    report = build_report({'sales': [receipt()]}, 'b', START, END, '4', accounts)
    assert report['cashier'] == label
    assert report['cashiers'][0]['status'] == status
    assert report['sales'] == 100


def test_legacy_name_is_not_reassigned_to_current_same_name_or_login():
    report = build_report({'sales': [receipt(cashierId=None)]}, 'b', START, END, 'name:Daison', [
        {'id': 12, 'display_name': 'Daison', 'login': 'Daison', 'is_active': True},
    ])
    assert report['cashiers'] == [{'id': 'name:Daison', 'displayName': 'Daison',
                                  'historicalName': 'Daison', 'status': 'archived', 'name': 'Daison · архив'}]
    assert report['sales'] == 100


def test_cashier_options_cover_branch_history_but_totals_follow_period_and_branch():
    state = {'sales': [receipt(createdAt=(START-timedelta(days=3)).isoformat()),
                       receipt(cashierId=7, cashier='Кассир другой точки', branchId='other')]}
    report = build_report(state, 'b', START, END, '4')
    assert [row['id'] for row in report['cashiers']] == ['4']
    assert report['count'] == report['sales'] == report['net'] == 0
    assert report['cashier'] == 'Daison · архив'
    with pytest.raises(ValueError, match='истории продаж'):
        build_report(state, 'b', START, END, '7')


def test_exact_timezone_boundaries_and_return_date_are_independent_of_sale_date():
    state = {'sales': [
        receipt(id='start', createdAt=START.astimezone(timezone.utc).isoformat()),
        receipt(id='end', createdAt=END.astimezone(timezone.utc).isoformat()),
        receipt(id='before', createdAt=(START-timedelta(microseconds=1)).isoformat()),
        receipt(id='after', createdAt=(END+timedelta(microseconds=1)).isoformat()),
        receipt(id='refund', createdAt=(START-timedelta(days=1)).isoformat(),
                refundedAt=START.isoformat(), refundedBy='Другой сотрудник', total=30),
        receipt(id='future-refund', createdAt=START.isoformat(), refundedAt=(END+timedelta(days=1)).isoformat(), total=20),
        receipt(id='invalid', createdAt='bad-date'),
        receipt(id='naive', createdAt='2026-10-06T12:00:00'),
    ]}
    report = build_report(state, 'b', START, END, '4')
    assert (report['count'], report['refundCount'], report['sales'], report['refunds'], report['net']) == (3, 1, 220, 30, 190)
    assert report['payments']['cash'] == 190


@pytest.mark.parametrize(('start', 'end'), [(START.replace(tzinfo=None), END), (START, END.replace(tzinfo=None)), (END, START)])
def test_invalid_report_period_is_rejected(start, end):
    with pytest.raises(ValueError, match='период'):
        build_report({'sales': []}, 'b', start, end)


def test_import_totals_use_effective_report_date_and_explicit_line_total():
    imported = receipt(cashierId=None, cashier='Внешняя касса', source='external',
                       paymentMethod='external', importedAt=(END+timedelta(days=5)).isoformat(),
                       total=205, subtotal=205, items=[{'id': 'rice', 'name': 'Рис', 'unit': 'кг',
                                                     'quantity': 1.7, 'price': 120.49, 'total': 205}])
    state = {'sales': [imported, receipt(cashierId=12)]}
    report = build_report(state, 'b', START, END, 'name:Внешняя касса')
    assert report['cashier'] == 'Внешняя касса'
    assert report['cashiers'][1]['status'] == 'external'
    assert (report['count'], report['importCount'], report['sales'], report['net']) == (0, 1, 205, 205)
    assert report['payments'] == {'cash': 0, 'card': 0, 'qr': 0, 'external': 205}
    assert report['products'][0]['total'] == 205
    assert report['products'][0]['quantity'] == 1.7


def test_net_uses_decimal_subtraction_for_sales_and_refunds():
    state = {'sales': [receipt(total=.3), receipt(id='refund', total=.2,
                        createdAt=(START-timedelta(days=1)).isoformat(), refundedAt=START.isoformat())]}
    report = build_report(state, 'b', START, END)
    assert report['net'] == report['payments']['cash'] == .1
