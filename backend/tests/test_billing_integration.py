"""Real SQL + real auth, isolated database only; all provider HTTP is mocked.

Run via scripts/billing_smoke.py. Never point BILLING_TEST_DATABASE_URL at a user DB.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode
from uuid import uuid4
import xml.etree.ElementTree as ET

import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from app import main, billing, freedompay as fp, legal, mailer, account_access
from app.config import Settings
from app.schemas import TenantCreate

DSN=os.environ.get('BILLING_TEST_DATABASE_URL','')
pytestmark=pytest.mark.skipif(not DSN,reason='isolated billing database required')


@pytest.fixture
def system(monkeypatch):
    cfg=Settings(database_url='',employee_pin_key='test-only-key-'+'x'*32,public_app_url='https://oimo.example',
                 cors_origins='https://oimo.example',session_cookie_secure=True,freedompay_enabled=True,
                 freedompay_merchant_id='123',freedompay_secret_key=SecretStr('test-secret'),freedompay_test_mode=False,
                 seller_legal_name='TEST SELLER ONLY',seller_tax_id='TEST-INN',seller_address='Test address',seller_phone='Test phone',seller_bank_details='Test bank',smtp_password=SecretStr(''))
    for module in (main,billing,legal,mailer,account_access): monkeypatch.setattr(module,'get_settings',lambda:cfg)
    def connect(): return psycopg.connect(DSN,row_factory=dict_row)
    def dependency():
        with connect() as connection: yield connection
    main.app.dependency_overrides[main.get_connection]=dependency
    provider_state={};calls=[]
    class Reply:
        def __init__(self,raw): self.raw=raw
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,limit): return self.raw
    def opener(handler):
        def post(request,timeout):
            path=request.full_url.rsplit('/',1)[-1]
            values={key:entries[0] for key,entries in parse_qs(request.data.decode()).items()}
            assert fp.verify(path,values,'test-secret');calls.append((path,values))
            identifier=values['pg_order_id']
            if path in ('init_payment','init_payment.php'):
                if provider_state.get('timeout'): raise TimeoutError('mock uncertain response')
                payment=str(uuid4().int % 10**25 + 1)
                provider_state[identifier]={'pg_status':'ok','pg_payment_id':payment,'pg_amount':values['pg_amount'],'pg_currency':'KGS','pg_payment_status':'pending','pg_captured':'0','pg_testing_mode':values['pg_testing_mode']}
                result={'pg_status':'ok','pg_payment_id':payment,'pg_redirect_url':'https://api.freedompay.kg/payment/'+payment}
            else: result=dict(provider_state[identifier])
            result['pg_salt']='reply-salt';result['pg_sig']=fp.sign(path,result,'test-secret')
            root=ET.Element('response')
            for key,value in result.items(): ET.SubElement(root,key).text=value
            return Reply(ET.tostring(root))
        return SimpleNamespace(open=post)
    monkeypatch.setattr(fp,'build_opener',opener)
    client=TestClient(main.app,base_url='https://oimo.example',headers={'Origin':'https://oimo.example'})
    company_id=uuid4().hex[:16];email=company_id+'@example.com';password='Test-password-'+company_id
    with connect() as connection:
        connection.execute('DELETE FROM auth_rate_limits')
        tenant=main._provision_tenant(TenantCreate(name='Test '+company_id,slug='t-'+company_id,owner_name='Test Owner',email=email,phone='996555123456',owner_password=password,register_password='Test-terminal-'+company_id,plan_code='canteen',max_branches=1,trial_days=14,service_modes=['counter'],location_name='Test',location_address='Test'),{'id':None,'login':'test'},connection)
        connection.execute("UPDATE auth_users SET email_verified_at=now() WHERE tenant_id=%s AND role='owner'",(tenant['id'],))
        user=connection.execute('SELECT * FROM auth_users WHERE tenant_id=%s AND role=%s',(tenant['id'],'owner')).fetchone()
    logged=client.post('/api/v1/auth/login',json={'login':email,'password':password})
    assert logged.status_code==200,logged.text
    yield SimpleNamespace(client=client,cfg=cfg,connect=connect,tenant=tenant['id'],user=user,state=provider_state,calls=calls)
    main.app.dependency_overrides.clear();client.close()


def checkout(system,request_id=None,**changes):
    payload={'request_id':str(request_id or uuid4()),'terms_accepted':True,'terms_version':legal.version(system.cfg),**changes}
    return system.client.post('/api/v1/billing/checkout',json=payload)


def callback(system,order,**changes):
    values={'pg_order_id':order['id'],'pg_payment_id':order['provider_payment_id'],'pg_amount':str(order['amount']),'pg_currency':'KGS','pg_testing_mode':'1' if order['testing'] else '0','pg_result':'1','pg_captured':'1','pg_salt':'notification','pg_merchant_id':'123',**changes}
    values['pg_sig']=fp.sign('result',values,'test-secret')
    return system.client.post('/api/v1/billing/freedompay/result',content=urlencode(values),headers={'content-type':'application/x-www-form-urlencoded'})


def subscription(system):
    with system.connect() as connection: return connection.execute('SELECT * FROM tenant_subscriptions WHERE tenant_id=%s',(system.tenant,)).fetchone()


def test_checkout_server_price_legal_consent_and_replay(system):
    before=subscription(system);identifier=uuid4()
    assert checkout(system,amount=1).status_code==422
    assert checkout(system,terms_accepted=False).status_code==422
    assert checkout(system,terms_version='outdated-terms').status_code==409
    assert checkout(system,billing_period='weekly').status_code==422
    response=checkout(system,identifier);assert response.status_code==200,response.text
    order=response.json();assert Decimal(str(order['amount']))==3500 and order['currency']=='KGS' and order['period_months']==1
    assert checkout(system,identifier).json()['id']==order['id']
    assert checkout(system).json()['id']==order['id']
    assert len(system.calls)==1 and system.calls[0][1]['pg_user_contact_email']==system.user['login']
    assert subscription(system)==before
    with system.connect() as connection:
        row=connection.execute('SELECT terms_snapshot FROM subscription_payments WHERE id=%s',(order['id'],)).fetchone()
        assert row['terms_snapshot']['seller']['seller_legal_name']=='TEST SELLER ONLY'
        assert row['terms_snapshot']['period']=='calendar-month'


def test_annual_quote_freezes_price_and_term_and_duplicate_callback_extends_once(system):
    # A future paid period, leap day and remaining trial must all be respected.
    paid_until=datetime(2028,2,29,14,30,tzinfo=timezone.utc)
    with system.connect() as connection:
        connection.execute("UPDATE tenant_subscriptions SET status='active',current_period_ends_at=%s WHERE tenant_id=%s",(paid_until,system.tenant))
    identifier=uuid4();overview=system.client.get('/api/v1/billing').json()
    response=checkout(system,identifier,billing_period='annual',price_version=overview['plan']['updated_at'])
    assert response.status_code==200,response.text
    order=response.json();assert Decimal(str(order['amount']))==42000 and order['period_months']==12
    assert system.calls[0][1]['pg_amount']=='42000.00' and '12 months' in system.calls[0][1]['pg_description']
    assert checkout(system,identifier).status_code==409
    assert checkout(system).status_code==409  # No accidental monthly order alongside the annual quote.
    assert len(system.calls)==1
    with system.connect() as connection:
        original=connection.execute('SELECT * FROM platform_plans WHERE code=%s',('canteen',)).fetchone()
        # Price changes affect new orders; this quote retains its amount and term.
        connection.execute("UPDATE platform_plans SET annual_price=43000,monthly_price=3600,updated_at=clock_timestamp() WHERE code='canteen'")
    try:
        replay=checkout(system,identifier,billing_period='annual',price_version=overview['plan']['updated_at'])
        assert replay.status_code==200 and Decimal(str(replay.json()['amount']))==42000
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses=list(executor.map(lambda _:callback(system,order),range(4)))
        assert all(response.status_code==200 for response in responses)
        assert len({response.content for response in responses})==1
        assert subscription(system)['current_period_ends_at']==datetime(2029,2,28,14,30,tzinfo=timezone.utc)
        with system.connect() as connection:
            saved=connection.execute('SELECT * FROM subscription_payments WHERE id=%s',(order['id'],)).fetchone()
            assert saved['terms_snapshot']['period']=='calendar-year' and saved['terms_snapshot']['period_months']==12
            assert saved['service_starts_at']==paid_until
            assert connection.execute('SELECT count(*) AS n FROM email_outbox WHERE dedup_key=%s',('subscription:'+order['id'],)).fetchone()['n']==1
        # After completion a new purchase must acknowledge the updated catalogue price.
        assert checkout(system,billing_period='annual',price_version=overview['plan']['updated_at']).status_code==409
        fresh=system.client.get('/api/v1/billing').json()
        assert Decimal(str(checkout(system,billing_period='annual',price_version=fresh['plan']['updated_at']).json()['amount']))==43000
    finally:
        with system.connect() as connection:
            connection.execute('UPDATE platform_plans SET monthly_price=%s,annual_price=%s,updated_at=%s WHERE code=%s',(original['monthly_price'],original['annual_price'],original['updated_at'],'canteen'))


@pytest.mark.parametrize('plan,period,expected',[('canteen','annual',42000),('restaurant','monthly',4000),('restaurant','annual',48000)])
def test_each_plan_uses_server_price_and_preserves_trial(system,plan,period,expected):
    with system.connect() as connection:
        connection.execute('UPDATE tenant_subscriptions SET plan_code=%s WHERE tenant_id=%s',(plan,system.tenant))
    before=subscription(system)
    order=checkout(system,billing_period=period).json()
    assert Decimal(str(order['amount']))==expected and order['period_months']==(12 if period=='annual' else 1)
    assert callback(system,order).status_code==200
    with system.connect() as connection:
        saved=connection.execute('SELECT * FROM subscription_payments WHERE id=%s',(order['id'],)).fetchone()
    assert saved['service_starts_at']==before['trial_ends_at']
    assert saved['service_ends_at']==billing.add_months(before['trial_ends_at'],12 if period=='annual' else 1)


def test_parallel_checkout_creates_one_provider_order_and_disabled_mode_cannot_charge(system):
    system.cfg.freedompay_enabled=False
    assert checkout(system).status_code==503 and not system.calls
    system.cfg.freedompay_enabled=True
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses=list(executor.map(lambda _:checkout(system),range(4)))
    assert all(response.status_code==200 for response in responses)
    assert len({response.json()['id'] for response in responses})==1 and len(system.calls)==1
    main.app.dependency_overrides[main.current_user]=lambda:{'id':system.user['id'],'role':'branch','tenant_id':system.tenant}
    assert system.client.get('/api/v1/billing').status_code==403
    assert checkout(system).status_code==403
    main.app.dependency_overrides[main.current_user]=lambda:{'id':system.user['id'],'role':'platform_owner'}
    with system.connect() as connection:
        name=connection.execute('SELECT name FROM tenants WHERE id=%s',(system.tenant,)).fetchone()['name']
    assert system.client.request('DELETE','/api/v1/platform/tenants/'+system.tenant,json={'confirmation_name':name}).status_code==409


def test_success_capture_currency_and_duplicate_notifications(system):
    order=checkout(system).json();before=subscription(system)
    for change in ({'pg_amount':'0.01'},{'pg_currency':'KZT'},{'pg_testing_mode':'1'},{'pg_payment_id':'999999'},{'pg_sig':'0'*32}):
        if 'pg_sig' in change:
            response=system.client.post('/api/v1/billing/freedompay/result',data={'pg_order_id':order['id'],'pg_salt':'x',**change})
        else: response=callback(system,order,**change)
        assert response.status_code in (400,403),response.text
    pending=callback(system,order,pg_captured='0');assert pending.status_code==200
    assert subscription(system)==before
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses=list(executor.map(lambda _:callback(system,order),range(4)))
    assert all(response.status_code==200 for response in responses)
    assert len({response.content for response in responses})==1
    assert pending.content==responses[0].content and fp.verify('result',fp.parse_xml(responses[0].content),'test-secret')
    after=subscription(system)
    assert after['status']=='active' and after['current_period_ends_at']==billing.next_month(before['trial_ends_at'])
    assert callback(system,order,pg_result='0').status_code==200
    assert subscription(system)==after
    with system.connect() as connection:
        assert connection.execute('SELECT count(*) AS n FROM email_outbox WHERE dedup_key=%s',('subscription:'+order['id'],)).fetchone()['n']==1
        assert connection.execute("SELECT count(*) AS n FROM subscription_payment_events WHERE order_id=%s AND payload->>'accessApplied'='true'",(order['id'],)).fetchone()['n']==1


def test_test_mode_never_grants_live_service_and_status_can_reconcile_bound_payment(system):
    system.cfg.freedompay_test_mode=True;before=subscription(system);order=checkout(system,billing_period='annual').json()
    assert callback(system,order).status_code==200 and subscription(system)==before
    system.cfg.freedompay_test_mode=False
    assert callback(system,order).status_code==200 and subscription(system)==before
    with system.connect() as connection:
        connection.execute("UPDATE subscription_payments SET status='failed' WHERE id=%s",(order['id'],))
    live=checkout(system).json();assert live['testing'] is False
    state=system.state[live['id']];state.update(pg_payment_status='success',pg_captured='1');del state['pg_testing_mode']
    verified=system.client.post('/api/v1/billing/orders/'+live['id']+'/refresh',json={})
    assert verified.status_code==200,verified.text
    assert verified.json()['status']=='paid' and subscription(system)['status']=='active'


def test_expired_owner_can_pay_and_tenant_isolation_refunds_require_provider_proof(system):
    with system.connect() as connection:
        connection.execute("UPDATE tenant_subscriptions SET trial_ends_at=now()-interval '1 day' WHERE tenant_id=%s",(system.tenant,))
    assert system.client.get('/api/v1/workspace').status_code==403
    assert system.client.get('/api/v1/auth/me').json()['session']['route']=='/billing'
    order=checkout(system).json();assert callback(system,order).status_code==200
    assert system.client.get('/api/v1/workspace').status_code==200
    assert system.client.post('/api/v1/billing/orders/'+order['id']+'/refund-request',json={'reason':'Unused period refund'}).status_code==200
    assert system.client.post('/api/v1/billing/orders/'+order['id']+'/refund-request',json={'reason':'Request retry'}).status_code==200
    with system.connect() as connection:
        refund=connection.execute('SELECT * FROM subscription_refund_requests WHERE order_id=%s',(order['id'],)).fetchone()
    assert system.client.get('/api/v1/platform/billing').status_code==403
    # Platform admin is test-only, retaining real authorization on all owner paths above.
    main.app.dependency_overrides[main.current_user]=lambda:{'id':system.user['id'],'role':'platform_owner'}
    path='/api/v1/platform/billing/refunds/'+str(refund['id'])+'/resolve'
    payload={'decision':'approved','reason':'Confirmed agreement','access_until':billing.now().isoformat()}
    assert system.client.post(path,json=payload).status_code==409
    assert callback(system,order,pg_refund_amount='-'+str(order['amount'])).status_code==200
    assert system.client.post(path,json=payload).status_code==200
    after=subscription(system);assert after['status']=='past_due'
    assert system.client.post(path,json=payload).status_code==200 and subscription(system)==after
    main.app.dependency_overrides[main.current_user]=lambda:{'id':system.user['id'],'role':'owner','tenant_id':'another-tenant'}
    assert system.client.post('/api/v1/billing/orders/'+order['id']+'/refresh',json={}).status_code==404
    assert system.client.post('/api/v1/billing/orders/'+order['id']+'/refund-request',json={'reason':'Wrong company'}).status_code==404


def test_unknown_initialization_is_not_repeated_and_tariff_change_requires_review(system):
    system.state['timeout']=True;identifier=uuid4();response=checkout(system,identifier);assert response.status_code==200,response.text
    assert response.json()['status']=='creating'
    assert checkout(system,identifier).json()['id']==response.json()['id'] and len(system.calls)==1
    assert checkout(system).json()['id']==response.json()['id'] and len(system.calls)==1
    with system.connect() as connection: connection.execute("UPDATE subscription_payments SET expires_at=now()-interval '1 hour' WHERE id=%s",(response.json()['id'],))
    assert checkout(system).json()['id']==response.json()['id'] and len(system.calls)==1
    system.state['timeout']=False
    with system.connect() as connection: connection.execute("UPDATE subscription_payments SET status='failed' WHERE id=%s",(response.json()['id'],))
    order=checkout(system).json();before=subscription(system)
    with system.connect() as connection: connection.execute('UPDATE tenant_subscriptions SET max_branches=2 WHERE tenant_id=%s',(system.tenant,))
    assert callback(system,order).status_code==200
    with system.connect() as connection:
        row=connection.execute('SELECT status,applied_at FROM subscription_payments WHERE id=%s',(order['id'],)).fetchone()
        assert row=={'status':'review','applied_at':None}
    assert subscription(system)['current_period_ends_at']==before['current_period_ends_at']


def test_background_reconciliation_restores_missed_notification_without_new_charge(system):
    from app import payment_reconciliation
    from types import SimpleNamespace
    pool=SimpleNamespace(connection=system.connect)
    order=checkout(system).json()
    with system.connect() as connection:
        connection.execute('UPDATE subscription_payments SET checked_at=now() WHERE id<>%s',(order['id'],))
    system.state[order['id']].update(pg_payment_status='success',pg_captured='1')
    before=subscription(system)
    assert payment_reconciliation.reconcile_one(pool,system.cfg) is True
    after=subscription(system)
    assert after['current_period_ends_at']==billing.next_month(before['trial_ends_at'])
    with system.connect() as connection:
        assert connection.execute('SELECT status FROM subscription_payments WHERE id=%s',(order['id'],)).fetchone()['status']=='paid'
    assert sum(path in ('init_payment','init_payment.php') for path,_ in system.calls)==1
    assert callback(system,order).status_code==200 and subscription(system)==after
