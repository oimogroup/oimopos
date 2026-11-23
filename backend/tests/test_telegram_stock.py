from decimal import Decimal
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app import telegram_stock as tg


def test_thresholds_are_per_item_and_missing_stock_is_zero():
    data={'ingredients':[{'id':'rice','name':'Рис','unit':'кг','limit':5},{'id':'salt','name':'Соль','limit':0},{'id':'off','name':'Off','limit':10,'is_active':False}],
          'products':[{'id':'rice','name':'Ready rice','limit':2}], 'stocks':{'rice':2}}
    result=tg.shortages(data)
    assert {r['key'] for r in result}=={'ingredients:rice','products:rice'}
    assert all(r['quantity']==2 for r in result)
    assert tg.shortages({'ingredients':[{'id':'a','name':'A','limit':1}], 'stocks':{}})[0]['quantity']==0


@pytest.mark.parametrize('quantity,minimum,low', [(5,5,True),(6,5,False),(-1,5,True),(0,0,False),('NaN',1,False),(1,'Infinity',False)])
def test_threshold_boundaries(quantity,minimum,low):
    assert bool(tg.shortages({'products':[{'id':'x','name':'X','limit':minimum}], 'stocks':{'x':quantity}})) is low


def test_alert_episode_and_recovery():
    first={'key':'ingredients:a'};second={'key':'products:b'}
    known,pending=tg.plan_alert([first,second],['ingredients:a','old'])
    assert known==['ingredients:a'] and pending==[second]
    assert tg.plan_alert([first],['ingredients:a'])[1]==[]
    assert tg.plan_alert([],['ingredients:a'])==([],[])
    assert tg.plan_alert([first],[])[1]==[first]
    assert len(tg.plan_alert([{'key':str(i)} for i in range(50)],[])[1])==20


def test_message_has_branch_units_and_limits_without_markup():
    message=tg.format_message('Buffet <b>1</b>',[{'name':'Мука','unit':'кг','quantity':Decimal('1.2345'),'minimum':Decimal('5'),'key':'a'}])
    assert 'Buffet <b>1</b>' in message and 'Мука' in message and '1,234 кг' in message and 'минимум 5' in message


def test_routes_are_tenant_branch_scoped_and_group_only():
    assert tg.valid_routes([{'branchId':'a','chatId':'-100123','threadId':'5','enabled':True}],{'a':'A'})==[('a',-100123,5,True)]
    for routes in [[{'branchId':'other'}],[{'branchId':'a','chatId':'123','enabled':True}],[{'branchId':'a','enabled':True}],[{'branchId':'a','threadId':'-1'}],[{'branchId':'a'},{'branchId':'a'}]]:
        with pytest.raises(HTTPException):tg.valid_routes(routes,{'a':'A'})


@pytest.mark.parametrize('role',['branch','platform_owner','cashier'])
def test_only_company_owner_can_manage(role):
    with pytest.raises(HTTPException) as e:tg.context(None,{'role':role,'tenant_id':'a'})
    assert e.value.status_code==403


def test_network_exception_never_exposes_token(monkeypatch):
    token='123456:abcdefghijklmnopqrstuv_secret'
    def fail(*args,**kwargs):raise RuntimeError('https://api.telegram.org/bot'+token)
    monkeypatch.setattr(tg,'urlopen',fail)
    with pytest.raises(tg.TelegramError) as e:tg.bot_request(token,'getMe')
    assert token not in str(e.value) and 'api.telegram' not in str(e.value)


def test_encryption_key_is_domain_separated_and_required():
    key=tg.encryption_key(SimpleNamespace(employee_pin_key='x'*32))
    assert len(key)==64 and key!='x'*32
    with pytest.raises(HTTPException):tg.encryption_key(SimpleNamespace(employee_pin_key=''))


def test_rate_limit_uses_retry_after(monkeypatch):
    import json
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return json.dumps({'ok':False,'error_code':429,'parameters':{'retry_after':123}}).encode()
    monkeypatch.setattr(tg,'urlopen',lambda *args,**kwargs:Response())
    with pytest.raises(tg.TelegramError) as e:tg.bot_request('123456:abcdefghijklmnopqrstuv','sendMessage')
    assert e.value.retry_after==123


@pytest.mark.parametrize('method,path', [('GET','/api/v1/integrations/telegram'),('PUT','/api/v1/integrations/telegram'),('POST','/api/v1/integrations/telegram/groups'),('POST','/api/v1/integrations/telegram/test/b1')])
def test_http_endpoints_reject_staff_before_sql(method,path):
    from fastapi.testclient import TestClient
    from app import main
    class NoSQL:
        def execute(self,*args,**kwargs):raise AssertionError('Staff accessed integration SQL')
    saved=dict(main.app.dependency_overrides)
    main.app.dependency_overrides[main.current_user]=lambda:{'role':'branch','tenant_id':'t1'}
    main.app.dependency_overrides[main.get_connection]=lambda:NoSQL()
    try:
        client=TestClient(main.app)
        response=client.request(method,path,json={} if method=='PUT' else None)
        assert response.status_code==403
    finally:
        main.app.dependency_overrides.clear();main.app.dependency_overrides.update(saved)


def test_message_size_is_bounded_for_long_names_and_large_values():
    rows=[{'name':'X'*500,'unit':'kg','key':str(i),'quantity':Decimal('-1e100'),'minimum':Decimal('1e100')} for i in range(20)]
    assert len(tg.format_message('B'*500,rows))<4096
