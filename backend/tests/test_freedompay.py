from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
import hashlib

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import billing, freedompay as fp, legal, main
from app.config import Settings


def config(**changes):
    seller={field:'' for field in (*legal.FIELDS,*legal.OPTIONAL_FIELDS)}
    return Settings(database_url='',public_app_url='https://oimo.example',freedompay_merchant_id='123',freedompay_secret_key=SecretStr('test-secret'),**{**seller,**changes})


def test_diagnostics_distinguish_failures_without_leaking_provider_data():
    error=fp.ProviderError('Provider confirmation unavailable')
    error.__cause__=HTTPError('https://example.com/secret',403,'private response',{},None)
    assert fp.diagnostic(error)=='transport_failure http_status=403'
    error.__cause__=URLError(TimeoutError('private details'))
    assert fp.diagnostic(error)=='transport_failure cause=timeout'
    assert fp.diagnostic(fp.ProviderError('Invalid provider signature'))=='invalid_signature'
    assert fp.diagnostic(fp.ProviderError('Invalid provider XML'))=='invalid_xml'
    assert fp.diagnostic(ValueError('private payment data'))=='payment_validation_failed'
    assert fp.diagnostic(fp.ProviderError('private response'))=='payment_validation_failed'


def test_protocol_signature_uses_sorted_values_script_and_secret():
    values={'pg_order_id':'order-1','pg_salt':'salt','pg_merchant_id':'123','pg_currency':'KGS','pg_amount':'10.00','pg_testing_mode':'0'}
    expected=hashlib.md5(b'init_payment;10.00;KGS;123;order-1;salt;0;test-secret').hexdigest()
    assert fp.sign('init_payment',values,'test-secret')==expected
    values['pg_sig']=expected
    assert fp.verify('init_payment',values,'test-secret')
    assert not fp.verify('result',values,'test-secret')
    values['pg_amount']='1.00'
    assert not fp.verify('init_payment',values,'test-secret')


def test_xml_ack_is_signed_and_nested_refunds_are_verified_in_order():
    xml=fp.response_xml('result','ok','test-secret','Payment & receipt')
    parsed=fp.parse_xml(xml)
    assert fp.verify('result',parsed,'test-secret')
    assert parsed['pg_description']=='Payment & receipt'
    nested=fp.parse_xml(b'<response><pg_refund_payments><pg_refund_payment><pg_amount>-1</pg_amount></pg_refund_payment><pg_refund_payment><pg_amount>-2</pg_amount></pg_refund_payment></pg_refund_payments></response>')
    assert fp.sign('x',nested,'s')==hashlib.md5(b'x;-1;-2;s').hexdigest()


@pytest.mark.parametrize('raw',[
    b'<!DOCTYPE response [<!ENTITY e SYSTEM "file:///etc/passwd">]><response>&e;</response>',
    b'<response><pg_amount>1</pg_amount><pg_amount>2</pg_amount></response>',
    b'<response><pg_sig attr="x">1</pg_sig></response>',b'<other/>',b'<response/>',b'x'*131073,
])
def test_invalid_xml_is_rejected(raw):
    with pytest.raises(fp.ProviderError): fp.parse_xml(raw)


@pytest.mark.parametrize('raw',[b'pg_amount=1&pg_amount=2',b'pg_amount[x]=1',b'pg_salt=%FF',b'x=1&'*101,b'x='+b'a'*8193])
def test_ambiguous_or_unbounded_forms_are_rejected(raw):
    with pytest.raises((ValueError,UnicodeError)): fp.form_values(raw,'application/x-www-form-urlencoded')


def test_multipart_provider_notifications_and_file_rejection():
    raw=b'--test\r\nContent-Disposition: form-data; name="pg_salt"\r\n\r\nsalt\r\n--test--\r\n'
    assert fp.form_values(raw,'multipart/form-data; boundary=test')=={'pg_salt':'salt'}
    with pytest.raises(ValueError): fp.form_values(raw.replace(b'name="pg_salt"',b'name="pg_salt"; filename="file"'),'multipart/form-data; boundary=test')


@pytest.mark.parametrize('url',['http://api.freedompay.kg/pay','https://evil.example','https://freedompay.kg.evil.example/pay','https://api.freedompay.kg:bad/pay','https://user:pass@api.freedompay.kg/pay','https://api.freedompay.kg\\@evil.example'])
def test_checkout_cannot_redirect_to_arbitrary_sites(url):
    assert not fp.safe_checkout_url(url)


def test_api_request_signs_kg_endpoint_checks_reply_and_disallows_redirect(monkeypatch):
    cfg=config();calls=[]
    class Reply:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,limit): return fp.response_xml('init_payment','ok','test-secret')
    def opener(handler):
        assert handler is fp.NoRedirect
        def open_request(request,timeout):
            assert timeout==12 and request.full_url=='https://api.freedompay.kg/init_payment'
            values={key:value[0] for key,value in parse_qs(request.data.decode()).items()}
            assert fp.verify('init_payment',values,'test-secret') and values['pg_currency']=='KGS'
            calls.append(values);return Reply()
        return SimpleNamespace(open=open_request)
    monkeypatch.setattr(fp,'build_opener',opener)
    assert fp.request_api(cfg,'/init_payment',{'pg_currency':'KGS'})['pg_status']=='ok'
    assert len(calls)==1 and fp.NoRedirect().redirect_request(None,None,None,None,None,None) is None
    monkeypatch.setattr(fp,'build_opener',lambda *args:SimpleNamespace(open=lambda *a,**kw:(_ for _ in ()).throw(URLError('test'))))
    with pytest.raises(fp.ProviderError): fp.request_api(cfg,'/init_payment',{})
    cfg.freedompay_api_base='https://api.freedompay.kz'
    with pytest.raises(fp.ProviderError): fp.request_api(cfg,'/init_payment',{})


def test_payment_matches_amount_currency_order_mode_and_bound_id():
    order={'id':'o1','merchant_id':'123','amount':Decimal('100'),'currency':'KGS','testing':False,'provider_payment_id':'99'}
    values={'pg_order_id':'o1','pg_amount':'100.00','pg_currency':'KGS','pg_testing_mode':'0','pg_payment_id':'99'}
    assert billing.validate_payment(order,values,config())=='99'
    for change in ({'pg_amount':'99.99'},{'pg_currency':'KZT'},{'pg_testing_mode':'1'},{'pg_payment_id':'98'},{'pg_order_id':'other'},{'pg_merchant_id':'124'},{'pg_amount':'NaN'}):
        with pytest.raises(ValueError): billing.validate_payment(order,{**values,**change},config())
    del values['pg_testing_mode']
    with pytest.raises(ValueError): billing.validate_payment(order,values,config())
    assert billing.validate_payment(order,values,config(),bound_status=True)=='99'
    with pytest.raises(ValueError): billing.validate_payment({**order,'provider_payment_id':None},values,config(),bound_status=True)


def test_calendar_month_and_expired_billing_access():
    assert billing.next_month(datetime(2028,1,31,tzinfo=timezone.utc))==datetime(2028,2,29,tzinfo=timezone.utc)
    assert billing.add_months(datetime(2028,2,29,13,45,tzinfo=timezone.utc),12)==datetime(2029,2,28,13,45,tzinfo=timezone.utc)
    assert billing.add_months(datetime(2026,12,31,tzinfo=timezone.utc),12)==datetime(2027,12,31,tzinfo=timezone.utc)
    user={'role':'owner','tenant_status':'active','subscription_status':'active','current_period_ends_at':datetime(2020,1,1,tzinfo=timezone.utc)}
    with pytest.raises(HTTPException): main._validate_tenant_access(user)
    main._validate_tenant_access(user,allow_billing=True)
    with pytest.raises(HTTPException): main._validate_tenant_access({**user,'role':'branch'},allow_billing=True)
    with pytest.raises(HTTPException): main._validate_tenant_access({**user,'tenant_status':'suspended'},allow_billing=True)
    main._validate_tenant_access({**user,'current_period_ends_at':None})


def test_incomplete_seller_disables_checkout_and_legal_routes_escape_identity(monkeypatch):
    cfg=config();assert 'SELLER_LEGAL_NAME' in billing.readiness(cfg)
    assert not cfg.freedompay_enabled and cfg.freedompay_test_mode
    assert 'test-secret' not in repr(cfg)
    monkeypatch.setattr(legal,'get_settings',lambda:cfg)
    client=TestClient(main.app)
    response=client.get('/legal/offer?kind=unknown')
    assert response.status_code==200 and 'Проект документа' in response.text and response.headers['cache-control']=='no-store'
    cfg.seller_legal_name='<script>alert(1)</script>'
    assert '<script>alert' not in client.get('/legal/contacts').text
    before=legal.version(cfg);cfg.seller_address='Changed';assert legal.version(cfg)!=before


def test_published_profile_fills_blank_environment_but_keeps_explicit_overrides(monkeypatch):
    from app import config as config_module
    monkeypatch.setattr(config_module,'_SELLER',{'seller_legal_name':'Test seller','seller_bank_details':'Test bank account','seller_phone':'','seller_support_email':'profile@example.com'})
    monkeypatch.setenv('DATABASE_URL','')
    monkeypatch.setenv('SELLER_LEGAL_NAME','')
    monkeypatch.setenv('SELLER_BANK_DETAILS','')
    monkeypatch.setenv('SELLER_PHONE','')
    monkeypatch.delenv('SELLER_SUPPORT_EMAIL',raising=False)
    config_module.get_settings.cache_clear()
    try:
        settings=config_module.get_settings()
        assert settings.seller_legal_name=='Test seller'
        assert settings.seller_bank_details=='Test bank account'
        assert settings.seller_phone==''
        assert settings.seller_support_email=='profile@example.com'
        monkeypatch.setenv('SELLER_LEGAL_NAME','Explicit seller')
        monkeypatch.setenv('SELLER_SUPPORT_EMAIL','override@example.com')
        config_module.get_settings.cache_clear()
        assert config_module.get_settings().seller_legal_name=='Explicit seller'
        assert config_module.get_settings().seller_support_email=='override@example.com'
    finally:
        config_module.get_settings.cache_clear()


def test_legal_pages_publish_requisites_and_only_missing_phone_keeps_draft(monkeypatch):
    cfg=config(seller_legal_name='Test seller',seller_tax_id='Test INN',seller_address='Test address',
               seller_bank_details='Recipient INN: Test INN\nBank INN: Different bank INN\nAccount: test',
               seller_support_email='support@example.com',seller_backup_email='backup@example.com',
               seller_registration_number='Test registration',seller_registration_date='20.10.2026',seller_okpo='Test OKPO')
    assert legal.missing(cfg)==['SELLER_PHONE']
    monkeypatch.setattr(legal,'get_settings',lambda:cfg)
    client=TestClient(main.app)
    for kind in ['offer','privacy','refunds','contacts','payment']:
        response=client.get('/legal/'+kind)
        assert response.status_code==200
        assert 'Test seller' in response.text and 'Test registration' in response.text
        assert 'Different bank INN' in response.text and 'backup@example.com' in response.text
        assert 'Для публикации осталось заполнить: рабочий телефон' in response.text
    cfg.seller_phone='+996555000000'
    assert not legal.missing(cfg) and 'Проект документа' not in client.get('/legal/offer').text
    assert 'FREEDOMPAY_ENABLED' in billing.readiness(cfg)
