from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
import smtplib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import main, mailer
from app.config import Settings


def settings(**changes):
    return Settings(database_url='', smtp_password=SecretStr('abcd efgh ijkl mnop'), **changes)


class SMTP:
    def __init__(self, *args, **kwargs):
        self.calls=[('connect', args, kwargs)]
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def ehlo(self): self.calls.append(('ehlo',))
    def starttls(self, **kwargs): self.calls.append(('tls', kwargs))
    def login(self, username, password): self.calls.append(('login', username, password))
    def send_message(self, message):
        self.calls.append(('send', message))
        return {}


ROW=dict(id=1, dedup_key='welcome:tenant-1',recipient='client@example.com',
         subject='Привет Oimo', body='Здравствуйте!', attempts=0)


@pytest.mark.parametrize('port', [465,587])
def test_smtp_uses_verified_tls_before_login_and_app_password(monkeypatch, port):
    client=SMTP()
    monkeypatch.setattr(mailer.smtplib, 'SMTP_SSL' if port==465 else 'SMTP',lambda *a,**kw: (client.calls.append(('create',a,kw)),client)[1])
    mailer.send_message(ROW, settings(smtp_port=port))
    create=next(c for c in client.calls if c[0]=='create')
    assert create[1]==('smtp.gmail.com',port) and create[2]['timeout']==15
    if port==465:
        assert create[2]['context'].check_hostname
    else:
        tls=next(i for i,c in enumerate(client.calls) if c[0]=='tls')
        login=next(i for i,c in enumerate(client.calls) if c[0]=='login')
        assert tls<login and client.calls[tls][1]['context'].check_hostname
    assert ('login','oimogroup2027@gmail.com','abcdefghijklmnop') in client.calls
    message=next(c[1] for c in client.calls if c[0]=='send')
    assert str(message['From'])=='Oimo <oimogroup2027@gmail.com>'
    assert str(message['To'])=='client@example.com' and message.get_content().strip()=='Здравствуйте!'
    assert 'abcdefghijklmnop' not in message.as_string()
    assert message['Date'] and message['Message-ID']


def test_secret_is_redacted_and_unconfigured_transport_does_not_connect(monkeypatch):
    cfg=settings()
    assert 'abcd efgh' not in repr(cfg)
    cfg.smtp_password=SecretStr('')
    monkeypatch.setattr(mailer.smtplib,'SMTP_SSL',lambda *a,**kw: pytest.fail('SMTP without credentials'))
    with pytest.raises(RuntimeError): mailer.send_message(ROW,cfg)


@pytest.mark.parametrize('url,expected', [
    ('https://oimo.example','https://oimo.example/login'),
    ('http://127.0.0.1:8000','http://127.0.0.1:8000/login'),
    ('http://evil.example',''),('https://user:password@oimo.example',''),
    ('https://oimo.example/other',''),('javascript:alert(1)',''),
])
def test_email_login_links_use_only_configured_safe_origin(monkeypatch,url,expected):
    monkeypatch.delenv('RENDER_EXTERNAL_URL',raising=False)
    assert mailer.login_url(settings(public_app_url=url))==expected


class Connection:
    def __init__(self,row=None): self.row=row;self.calls=[]
    def transaction(self): return nullcontext()
    def execute(self,sql,params=()):
        self.calls.append((sql,params))
        row=self.row if 'SELECT * FROM email_outbox' in sql else None
        return SimpleNamespace(fetchone=lambda:row,fetchall=lambda:[])


@pytest.mark.parametrize('attempt,error,expected',[(0,None,'sent'),(0,smtplib.SMTPAuthenticationError(535,b'secret'), 'pending'),(5,TimeoutError('password-leak'),'failed')])
def test_queue_claim_retry_and_error_do_not_leak_secrets(monkeypatch,attempt,error,expected):
    connection=Connection({**ROW,'attempts':attempt})
    pool=SimpleNamespace(connection=lambda:nullcontext(connection))
    def send(*args):
        if error: raise error
    monkeypatch.setattr(mailer,'send_message',send)
    assert mailer.deliver_one(pool,settings())
    claim=next(p for sql,p in connection.calls if "SET status='sending'" in sql)
    sql,result=connection.calls[-1]
    assert 'lock_token=%s' in sql and result[-1]==claim[0]
    assert result[0]==expected and result[3]==min(3600,30*2**attempt)
    assert result[1]==(type(error).__name__ if error else '')
    assert 'password-leak' not in repr(connection.calls)
    assert any('FOR UPDATE SKIP LOCKED' in sql for sql,_ in connection.calls)


def test_welcome_has_date_login_safe_link_and_no_password(monkeypatch):
    monkeypatch.setattr(mailer,'get_settings',lambda:settings(public_app_url='https://oimo.example'))
    connection=Connection()
    tenant=dict(id='tenant-1',name='Cafe',trial_ends_at=datetime(2026,11,5,tzinfo=timezone.utc))
    mailer.enqueue_welcome(connection,tenant,'Owner','client@example.com')
    sql,params=connection.calls[-1]
    assert 'ON CONFLICT (dedup_key) DO NOTHING' in sql
    assert params[:3]==('tenant-1','welcome:tenant-1','client@example.com')
    assert '05.11.2026' in params[4] and 'https://oimo.example/login' in params[4]
    assert 'client@example.com' in params[4] and 'abcd efgh' not in repr(params)


def test_mail_controls_are_platform_only_and_never_expose_password(monkeypatch):
    cfg=settings()
    monkeypatch.setattr(mailer,'get_settings',lambda:cfg)
    app=FastAPI();mailer.install(app)
    connection=Connection()
    user=dict(role='owner',id=2)
    app.dependency_overrides[main.current_user]=lambda:user
    app.dependency_overrides[main.get_connection]=lambda:connection
    client=TestClient(app)
    assert client.get('/api/v1/platform/mail').status_code==403
    user['role']='platform_owner'
    response=client.get('/api/v1/platform/mail')
    assert response.status_code==200 and response.json()['configured']
    assert 'password' not in response.text and 'abcd efgh' not in response.text
    assert client.post('/api/v1/platform/mail/test').status_code==403
    headers={'Origin':'http://127.0.0.1:8000'}
    assert client.post('/api/v1/platform/mail/test',headers=headers).json()=={'queued':True}
    insert=next(p for sql,p in connection.calls if 'INSERT INTO email_outbox' in sql)
    assert insert[2]=='oimogroup2027@gmail.com'
    cfg.smtp_password=SecretStr('')
    assert client.post('/api/v1/platform/mail/test',headers=headers).status_code==409
