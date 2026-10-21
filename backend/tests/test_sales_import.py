import base64
import io
import zipfile
from copy import deepcopy
import pytest
from app.sales_import import parse, preview, commit
from app.workspace import default_state, WorkspaceError

USER = {'id': 2, 'role': 'branch', 'staff_role': 'cashier', 'shift_id': 4, 'branch_id': 'b1', 'plan_code': 'canteen', 'display_name': 'Cashier'}

def file(quantity=2, name='Rice', unit='шт', *, title='Реестр продаж с 25.09.2026 по 25.09.2026', rows=None):
    output = io.BytesIO()
    def text(col, value): return f'<c r="{col}" t="inlineStr"><is><t>{value}</t></is></c>'
    sheet = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
    sheet += '<row r="1">'+text('A1',title)+'</row>'
    sheet += '<row r="4">'+text('H4','Ед. изм')+text('I4','Количество')+text('K4','Сумма')+'</row>'
    for number, row_name, code, row_unit, qty, total in rows or [(7, name, '10', unit, quantity, 100)]:
        sheet += f'<row r="{number}">'+text(f'B{number}',row_name)+text(f'F{number}',code)+text(f'H{number}',row_unit)+f'<c r="I{number}"><v>{qty}</v></c><c r="K{number}"><v>{total}</v></c></row>'
    sheet += '</sheetData></worksheet>'
    with zipfile.ZipFile(output,'w') as z:z.writestr('xl/worksheets/sheet1.xml',sheet)
    return base64.b64encode(output.getvalue()).decode()

def scenario():
    s=default_state();s['recipes']=[{'id':101,'name':'Rice','yield':250}]
    s['logisticsState']['batches']=[{'id':'batch1','recipeId':101,'branchId':'b1','portionWeight':250,'soldPortions':0,'servingLots':[{'id':'lot1','acceptedAt':'now','responsibleId':2,'acceptedWeight':1,'soldWeight':0}]}]
    return s

def test_import_consumes_accepted_lot_only_and_cannot_repeat():
    s=scenario();stocks=deepcopy(s['logisticsState']['branchStocks']);sales=deepcopy(s['sales'])
    payload={'file':file(),'selections':[{'row':'7','recipeId':'101'}]}
    commit(s,USER,payload)
    assert s['logisticsState']['batches'][0]['servingLots'][0]['soldWeight']==.5
    assert s['logisticsState']['branchStocks']==stocks
    assert len(s['sales'])==len(sales)+1
    assert s['sales'][0]['paymentMethod']=='external'
    assert s['sales'][0]['shiftId'] is None
    assert preview(s,'b1',payload['file'])['rows'][0]['posted']
    with pytest.raises(WorkspaceError):commit(s,USER,payload)

def test_shortage_and_wrong_branch_leave_state_unchanged():
    for user,quantity in [(USER,10),({**USER,'branch_id':'b2'},1)]:
        s=scenario();before=deepcopy(s)
        with pytest.raises(WorkspaceError):commit(s,user,{'file':file(quantity),'selections':[{'row':'7','recipeId':101}]})
        assert s==before

def test_pending_or_locked_stock_cannot_be_consumed():
    for key,value in [('acceptedAt',None),('handoverId','pending')]:
        s=scenario();s['logisticsState']['batches'][0]['servingLots'][0][key]=value
        with pytest.raises(WorkspaceError):commit(s,USER,{'file':file(),'selections':[{'row':'7','recipeId':101}]})

def test_parser_and_permissions():
    assert parse(file())['rows'][0]['quantity']==2
    for raw in ['', 'not-base64']:
        with pytest.raises(ValueError):parse(raw)
    for changes in [{'staff_role':'production'},{'shift_id':None},{'plan_code':'restaurant'}]:
        with pytest.raises(WorkspaceError):commit(scenario(),{**USER,**changes},{'file':file(),'selections':[{'row':'7','recipeId':101}]})


def test_external_report_and_idempotent_materialization():
    from app.sales_import import materialize_sales
    from app.sales_report import build_report
    from datetime import datetime, timezone
    s=scenario()
    commit(s,USER,{'file':file(),'selections':[{'row':'7','recipeId':101}]})
    before=deepcopy(s)
    materialize_sales(s)
    assert s==before
    report=build_report(s,'b1',datetime(2026,9,25,tzinfo=timezone.utc),datetime(2026,9,26,tzinfo=timezone.utc))
    assert report['net']==100 and report['payments']['external']==100
    assert report['payments']['cash']==0 and report['count']==0 and report['importCount']==1
    assert report['products'][0]['quantity']==2


def test_product_import_consumes_stock_and_creates_sale():
    from app.workspace import _set_stock, _stock
    s=scenario();s['products']=[{'id':'water','name':'Rice','unit':'шт','weighted':False}]
    _set_stock(s,'b1','water',10,20)
    commit(s,USER,{'file':file(),'selections':[{'row':'7','recipeId':'product:water'}]})
    assert _stock(s,'b1','water')==8
    assert s['sales'][0]['items'][0]['unitCost']==20
    assert s['logisticsState']['batches'][0]['servingLots'][0]['soldWeight']==0


def test_missing_unit_uses_recipe_portions():
    s=scenario()
    encoded=file(unit='')
    assert preview(s,'b1',encoded)['rows'][0]['unit']=='порция'
    commit(s,USER,{'file':encoded,'selections':[{'row':'7','recipeId':101}]})
    assert s['sales'][0]['items'][0]['unit']=='порция'
    assert s['logisticsState']['batches'][0]['servingLots'][0]['soldWeight']==.5


@pytest.mark.parametrize('title', [
    'Реестр продаж с 31.09.2026 по 31.09.2026',
    'Реестр продаж с 24.09.2026 по 26.09.2026',
    'Реестр продаж с 26.09.2026 по 24.09.2026',
    'Реестр продаж без периода',
])
def test_invalid_or_multi_day_period_rejected_before_any_changes(title):
    s=scenario();before=deepcopy(s);encoded=file(title=title)
    with pytest.raises(ValueError):preview(s,'b1',encoded)
    with pytest.raises(WorkspaceError) as error:
        commit(s,USER,{'file':encoded,'selections':[{'row':'7','recipeId':101}]})
    assert error.value.status_code==422
    assert s==before


def test_changed_reordered_report_cannot_repeat_rows_but_remaining_rows_can_post():
    s=scenario()
    first=file(rows=[(7,'Rice','10','шт',1,100),(8,'Rice small','11','шт',1,50)])
    commit(s,USER,{'file':first,'selections':[{'row':'7','recipeId':101}]})
    # Old stored imports have no new reportDate field; preserve dedup for them.
    s['externalSalesImports'][0].pop('reportDate')
    changed=file(title='  Реестр продаж с 25.09.2026 по 25.09.2026  ',rows=[
        (12,'Rice small','11','шт',1,50),(13,'Renamed Rice','10.0','шт',2,200)])
    assert [row['posted'] for row in preview(s,'b1',changed)['rows']]==[False,True]
    before=deepcopy(s)
    with pytest.raises(WorkspaceError) as error:
        commit(s,USER,{'file':changed,'selections':[{'row':'12','recipeId':101},{'row':'13','recipeId':101}]})
    assert error.value.status_code==409
    assert s==before
    commit(s,USER,{'file':changed,'selections':[{'row':'12','recipeId':101}]})
    assert s['logisticsState']['batches'][0]['servingLots'][0]['soldWeight']==.5
    assert sum(sale['total'] for sale in s['sales'])==150
    assert all(row['posted'] for row in preview(s,'b1',first)['rows'])


def test_daily_product_identity_is_scoped_by_branch_and_date():
    s=scenario();encoded=file(quantity=1)
    commit(s,USER,{'file':encoded,'selections':[{'row':'7','recipeId':101}]})
    assert not preview(s,'b2',encoded)['rows'][0]['posted']
    next_day=file(quantity=1,title='Реестр продаж с 26.09.2026 по 26.09.2026')
    assert not preview(s,'b1',next_day)['rows'][0]['posted']
    commit(s,USER,{'file':next_day,'selections':[{'row':'7','recipeId':101}]})
    assert len(s['sales'])==2


def test_duplicate_product_codes_are_not_silently_imported_twice():
    encoded=file(rows=[(7,'Rice','10','шт',1,100),(8,'Rice','10.0','шт',1,100)])
    with pytest.raises(ValueError,match='повторяются коды'):parse(encoded)


def test_unsupported_legacy_report_does_not_block_valid_import_or_change_history():
    s=scenario()
    legacy={'id':'old','branchId':'b1','title':'Реестр продаж с 31.09.2026 по 31.09.2026','items':[],'status':'posted'}
    s['externalSalesImports']=[deepcopy(legacy)]
    commit(s,USER,{'file':file(),'selections':[{'row':'7','recipeId':101}]})
    assert s['externalSalesImports'][0]==legacy
    assert len(s['sales'])==1


def test_import_uses_and_freezes_company_currency_timezone():
    from datetime import datetime
    from app.sales_import import materialize_sales
    from app.sales_report import build_report
    s=scenario();s['companySettings']={'general':{'timezone':'Asia/Almaty','currency':'KZT'}}
    commit(s,USER,{'file':file(),'selections':[{'row':'7','recipeId':101}]})
    sale=deepcopy(s['sales'][0])
    assert sale['createdAt']=='2026-09-25T12:00:00+05:00'
    assert sale['currency']=='KZT'
    report=build_report(s,'b1',datetime.fromisoformat('2026-09-25T00:00:00+05:00'),datetime.fromisoformat('2026-09-25T23:59:59+05:00'))
    assert report['currency']=='KZT' and report['payments']['external']==100
    s['companySettings']['general'].update(timezone='UTC',currency='USD')
    s['sales']=[]
    materialize_sales(s)
    assert s['sales'][0]==sale


def test_import_snapshots_responsible_employee_and_serving_line():
    s=scenario();batch=s['logisticsState']['batches'][0]
    batch.update(number='ПР-123')
    batch['servingLots'][0].update(responsibleId=42,responsibleName='Алия',line='Раздача')
    commit(s,USER,{'file':file(),'selections':[{'row':'7','recipeId':101}]})
    allocation=s['sales'][0]['items'][0]['batchAllocations'][0]
    assert allocation['responsibleId']==42 and allocation['responsibleName']=='Алия'
    assert allocation['line']=='Раздача' and allocation['batchNumber']=='ПР-123'
    s['logisticsState']['batches'][0]['servingLots'][0]['responsibleName']='Другой кассир'
    assert allocation['responsibleName']=='Алия'


def test_preview_reuses_successful_mapping_by_code_only_within_branch():
    s=scenario()
    commit(s,USER,{'file':file(name='Rice external'),'selections':[{'row':'7','recipeId':101}]})
    tomorrow=file(name='Rice renamed',title='Реестр продаж с 26.09.2026 по 26.09.2026')
    row=preview(s,'b1',tomorrow)['rows'][0]
    assert row['recipeId']=='101' and row['mappingSaved'] and not row['posted']
    assert preview(s,'b2',tomorrow)['rows'][0]['recipeId']==''
    s['recipes']=[]
    assert preview(s,'b1',tomorrow)['rows'][0]['recipeId']==''


def test_conflicting_past_mappings_require_manual_choice_even_if_name_matches():
    s=scenario();s['recipes'].append({'id':102,'name':'Other recipe','yield':250})
    s['externalSalesImports']=[{'branchId':'b1','status':'posted','title':'Реестр продаж с 24.09.2026 по 24.09.2026','items':[
        {'code':'10','recipeId':101},{'code':'10','recipeId':102}]}]
    assert preview(s,'b1',file())['rows'][0]['recipeId']==''


def test_saved_product_mapping_infers_unit_from_mapped_card_after_name_change():
    from app.workspace import _set_stock
    s=scenario();s['products']=[{'id':'water','name':'Water bottle','unit':'шт','weighted':False}]
    _set_stock(s,'b1','water',10,20)
    commit(s,USER,{'file':file(name='External water'),'selections':[{'row':'7','recipeId':'product:water'}]})
    row=preview(s,'b1',file(name='Different water name',unit='',title='Реестр продаж с 26.09.2026 по 26.09.2026'))['rows'][0]
    assert row['recipeId']=='product:water' and row['unit']=='шт' and row['unitInferred']
