import os
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import threading
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest
from fastapi import HTTPException
from app import telegram_stock as tg

DSN=os.environ.get('TELEGRAM_TEST_DATABASE_URL','')
pytestmark=pytest.mark.skipif(not DSN,reason='isolated Telegram PostgreSQL required')
SETTINGS=SimpleNamespace(employee_pin_key='test-integration-secret-key-123456789')
TOKEN='123456:abcdefghijklmnopqrstuv_test'


@pytest.fixture
def db(monkeypatch):
    schema='telegram_test_'+uuid4().hex
    def connect():
        c=psycopg.connect(DSN,row_factory=dict_row)
        c.execute(f'SET search_path TO {schema}, public')
        return c
    with psycopg.connect(DSN,autocommit=True) as c:
        c.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public')
        c.execute(f'CREATE SCHEMA {schema}')
        c.execute(f'SET search_path TO {schema}, public')
        c.execute('CREATE TABLE tenants(id text PRIMARY KEY,status text)')
        c.execute('CREATE TABLE schema_migrations(version text)')
        c.execute('CREATE TABLE operational_state(tenant_id text PRIMARY KEY,payload jsonb)')
        c.execute('CREATE TABLE audit_events(tenant_id text,actor text,action text,entity_type text,entity_id text,after_state jsonb)')
        c.execute((Path(__file__).resolve().parents[2]/'database/migrations/026_telegram_stock_alerts.sql').read_text())
    class Pool:
        active=0
        @contextmanager
        def connection(self,**kwargs):
            with connect() as c:
                self.active+=1
                try:yield c
                finally:self.active-=1
    pool=Pool()
    monkeypatch.setattr(tg,'bot_request',lambda token,method,payload=None:{'is_bot':True,'username':'oimo_test_bot','id':123456})
    for tenant in ['t1','t2']:
        with connect() as c:
            c.execute('INSERT INTO tenants VALUES (%s,%s)',(tenant,'active'))
            c.execute('INSERT INTO operational_state VALUES (%s,%s)',(tenant,Jsonb({'branches':[{'id':'b1','name':tenant+' North','status':'active'},{'id':'b2','name':tenant+' South','status':'active'}], 'ingredients':[{'id':'rice','name':'Rice','unit':'kg','limit':5}], 'products':[], 'logisticsState':{'branchStocks':{'b1':{'rice':2},'b2':{'rice':3}}}})))
    try:yield connect,pool
    finally:
        with psycopg.connect(DSN,autocommit=True) as c:c.execute(f'DROP SCHEMA {schema} CASCADE')


def user(tenant='t1'):
    return {'tenant_id':tenant,'role':'owner','display_name':'Owner'}


def configure(connect,tenant='t1',routes=None):
    with connect() as c:
        return tg.save(c,user(tenant),{'token':TOKEN,'enabled':True,'revision':0,'routes':routes or [{'branchId':'b1','chatId':'-1001','enabled':True},{'branchId':'b2','chatId':'-1002','enabled':True}]},SETTINGS)


def due(connect):
    with connect() as c:c.execute("UPDATE telegram_stock_routes SET next_attempt=now()-interval '1 second'")


def test_encryption_context_and_separate_branch_targets(db):
    connect,pool=db
    config=configure(connect)
    assert TOKEN not in str(config) and config['configured'] and config['revision']==1
    with connect() as c:
        stored=c.execute('SELECT bot_token FROM telegram_integrations').fetchone()['bot_token']
        assert TOKEN.encode() not in bytes(stored)
        assert tg.context(c,user('t2'))['configured'] is False
        assert TOKEN not in str(c.execute('SELECT after_state FROM audit_events').fetchall())
    sent=[]
    def send(token,method,payload):
        assert pool.active==0
        assert token==TOKEN
        sent.append(payload)
    assert tg.process_one(pool,SETTINGS,send)
    assert tg.process_one(pool,SETTINGS,send)
    assert {p['chat_id'] for p in sent}=={-1001,-1002}
    assert any('North' in p['text'] and '2 kg' in p['text'] for p in sent)


def test_no_duplicates_and_restock_rearms_alert(db):
    connect,pool=db;configure(connect,routes=[{'branchId':'b1','chatId':'-1001','enabled':True}]);sent=[]
    send=lambda *args:sent.append(args)
    tg.process_one(pool,SETTINGS,send);due(connect);tg.process_one(pool,SETTINGS,send)
    assert len(sent)==1
    with connect() as c:c.execute("UPDATE operational_state SET payload=jsonb_set(payload,'{logisticsState,branchStocks,b1,rice}','10') WHERE tenant_id='t1'")
    due(connect);tg.process_one(pool,SETTINGS,send)
    with connect() as c:c.execute("UPDATE operational_state SET payload=jsonb_set(payload,'{logisticsState,branchStocks,b1,rice}','1') WHERE tenant_id='t1'")
    due(connect);tg.process_one(pool,SETTINGS,send)
    assert len(sent)==2


def test_failure_retries_without_marking_delivered_and_survives_restart(db):
    connect,pool=db;configure(connect,routes=[{'branchId':'b1','chatId':'-1001','enabled':True}])
    def fail(*args):raise tg.TelegramError('No access',123)
    tg.process_one(pool,SETTINGS,fail)
    with connect() as c:
        row=c.execute('SELECT attempts,last_error,notified_keys FROM telegram_stock_routes').fetchone()
        assert row['attempts']==1 and row['last_error']=='No access' and not row['notified_keys']
    sent=[];due(connect);tg.process_one(pool,SETTINGS,lambda *args:sent.append(args));due(connect);tg.process_one(pool,SETTINGS,lambda *args:sent.append(args))
    assert len(sent)==1


def test_concurrent_workers_do_not_send_same_claim(db):
    connect,pool=db;configure(connect,routes=[{'branchId':'b1','chatId':'-1001','enabled':True}]);started=threading.Event();finish=threading.Event();sent=[]
    def send(*args):started.set();finish.wait(5);sent.append(args)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first=workers.submit(tg.process_one,pool,SETTINGS,send)
        assert started.wait(5)
        try:assert tg.process_one(pool,SETTINGS,send) is False
        finally:finish.set()
        assert first.result(timeout=5)
    assert len(sent)==1


def test_stale_settings_and_foreign_branch_are_rejected(db):
    connect,pool=db;config=configure(connect)
    with connect() as c:
        with pytest.raises(HTTPException) as e:tg.save(c,user(),{'revision':0,'routes':[]},SETTINGS)
        assert e.value.status_code==409
    with connect() as c:
        with pytest.raises(HTTPException):tg.save(c,user(),{'revision':config['revision'],'routes':[{'branchId':'foreign'}]},SETTINGS)
    with connect() as c:assert tg.context(c,user())['revision']==1


def test_disabled_tenant_and_inactive_branch_do_not_send(db):
    connect,pool=db;configure(connect)
    with connect() as c:c.execute("UPDATE tenants SET status='suspended' WHERE id='t1'")
    assert tg.process_one(pool,SETTINGS,lambda *args:pytest.fail('disabled tenant sent')) is False
    with connect() as c:
        c.execute("UPDATE tenants SET status='active' WHERE id='t1'")
        c.execute("UPDATE operational_state SET payload=jsonb_set(payload,'{branches,0,status}','\"inactive\"') WHERE tenant_id='t1'")
    sent=[];tg.process_one(pool,SETTINGS,lambda *args:sent.append(args));assert sent==[]


def test_group_change_resets_episode_and_preserves_other_tenant(db):
    connect,pool=db;config=configure(connect);configure(connect,'t2')
    sent=[];tg.process_one(pool,SETTINGS,lambda *args:sent.append(args))
    with connect() as c:
        tg.save(c,user(),{'revision':config['revision'],'enabled':True,'routes':[{'branchId':'b1','chatId':'-9999','threadId':'7','enabled':True}]},SETTINGS)
        assert tg.context(c,user('t2'))['revision']==1
    due(connect)
    for _ in range(4):tg.process_one(pool,SETTINGS,lambda *args:sent.append(args))
    assert any(args[2]['chat_id']==-9999 and args[2]['message_thread_id']==7 for args in sent)


def test_manual_test_is_scoped_audited_and_clears_delivery_error(db,monkeypatch):
    connect,pool=db;configure(connect);sent=[]
    monkeypatch.setattr(tg,'bot_request',lambda token,method,payload:sent.append((token,method,payload)))
    with connect() as c:
        c.execute("UPDATE telegram_stock_routes SET last_error='Old error' WHERE tenant_id='t1' AND branch_id='b2'")
        assert tg.test_route(c,user(),'b2',SETTINGS)=={'sent':True}
        assert sent[0][2]['chat_id']=='-1002' and 'South' in sent[0][2]['text']
        assert c.execute("SELECT last_error FROM telegram_stock_routes WHERE tenant_id='t1' AND branch_id='b2'").fetchone()['last_error']==''
        assert TOKEN not in str(c.execute('SELECT after_state FROM audit_events').fetchall())
        with pytest.raises(HTTPException):tg.test_route(c,user(),'foreign',SETTINGS)
    assert len(sent)==1
