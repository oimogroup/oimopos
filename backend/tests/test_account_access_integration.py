"""Isolated PostgreSQL only; the mail transport and payment provider are mocked."""
from concurrent.futures import ThreadPoolExecutor
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException, Request
from uuid import uuid4

from app import main
from app.schemas import TenantCreate, TenantOwnerAccessUpdate
from app.security import verify_password
from test_billing_integration import system, DSN, checkout

pytestmark=pytest.mark.skipif(not DSN,reason='isolated billing database required')


def queued_token(system, purpose):
    subject='Oimo — восстановление пароля' if purpose=='reset' else 'Oimo — подтвердите email'
    with system.connect() as connection:
        row=connection.execute('SELECT body FROM email_outbox WHERE recipient=%s AND subject=%s ORDER BY id DESC LIMIT 1',(system.user['login'],subject)).fetchone()
    assert row
    url=re.search(r'https://[^\s]+',row['body']).group()
    assert urlsplit(url).netloc=='oimo.example' and not urlsplit(url).query
    return parse_qs(urlsplit(url).fragment)['token'][0]


def set_unverified(system):
    with system.connect() as connection:
        connection.execute('UPDATE auth_users SET email_verified_at=NULL WHERE id=%s',(system.user['id'],))


def signup_data(**changes):
    return {'request_id':str(uuid4()),'name':'Same Owner','company':'Same Cafe',
            'phone':'996'+str(uuid4().int)[:10],'email':uuid4().hex[:16]+'@example.com',
            'password':'abcde','plan':'restaurant','consent':True,**changes}


def owner_access(system, **changes):
    payload=TenantOwnerAccessUpdate(owner_name='Same Owner',owner_login=changes.pop('owner_login','shared-owner'),
                                   owner_email=changes.pop('owner_email',system.user['email']),**changes)
    request=Request({'type':'http','headers':[(b'origin',b'https://oimo.example')]})
    with system.connect() as connection:
        return main.update_tenant_owner_access(system.tenant,payload,request,{'id':None,'role':'platform_owner','login':'test'},connection)


def test_signup_allows_same_names_and_five_characters_but_email_is_unique(system):
    first=signup_data()
    assert system.client.post('/api/v1/public/register',json={**first,'password':'abcd'}).status_code==422
    result=system.client.post('/api/v1/public/register',json=first)
    assert result.status_code==201
    first_tenant=result.json()['session']['tenantId']
    second=system.client.post('/api/v1/public/register',json=signup_data())
    assert second.status_code==201 and second.json()['session']['tenantId']!=first_tenant
    duplicate=system.client.post('/api/v1/public/register',json=signup_data(email=first['email'].upper()))
    assert duplicate.status_code==409 and 'email' in duplicate.json()['detail']
    logged=system.client.post('/api/v1/auth/login',json={'login':first['email'].upper(),'password':'abcde'})
    assert logged.status_code==200 and logged.json()['session']['tenantId']==first_tenant


def test_concurrent_signup_reserves_one_account_per_email(system):
    email=uuid4().hex[:16]+'@example.com'
    payloads=[signup_data(email=email),signup_data(email=email.upper())]
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses=list(executor.map(lambda payload:system.client.post('/api/v1/public/register',json=payload),payloads))
    assert sorted(response.status_code for response in responses)==[201,409]
    with system.connect() as connection:
        assert connection.execute('SELECT count(*) AS n FROM auth_users WHERE lower(email)=%s AND deleted_at IS NULL',(email,)).fetchone()['n']==1
        assert connection.execute('SELECT count(*) AS n FROM trial_registrations WHERE email=%s',(email,)).fetchone()['n']==1


def test_shared_owner_alias_and_password_never_mix_tenants_or_recovery(system):
    first=owner_access(system,owner_password='abcde')
    assert first['owner_login']=='shared-owner' and first['owner_email']==system.user['email']
    assert system.client.get('/api/v1/auth/me').status_code==401
    second_email=uuid4().hex[:16]+'@example.com'
    with system.connect() as connection:
        second=main._provision_tenant(TenantCreate(name='Same Cafe',slug='same-'+uuid4().hex[:16],owner_name='Same Owner',
          owner_login='shared-owner',email=second_email,phone='996555123456',owner_password='abcde',register_password='vwxyz',
          service_modes=['counter'],location_name='Test',location_address='Test'),{'id':None,'login':'test'},connection)
    denied=system.client.post('/api/v1/auth/login',json={'login':'shared-owner','password':'abcde'})
    assert denied.status_code==401 and 'email' in denied.json()['detail']
    for email,tenant in [(system.user['email'],system.tenant),(second_email,second['id'])]:
        result=system.client.post('/api/v1/auth/login',json={'login':email.upper(),'password':'abcde'})
        assert result.status_code==200 and result.json()['session']['tenantId']==tenant
        assert system.client.get('/api/v1/auth/email').json()['email']==email
        assert system.client.post('/api/v1/auth/password/forgot',json={'email':email}).status_code==200
    with system.connect() as connection:
        recipients=connection.execute("SELECT recipient,tenant_id FROM email_outbox WHERE tenant_id IN (%s,%s) AND subject=%s",(system.tenant,second['id'],'Oimo — восстановление пароля')).fetchall()
    assert {(row['recipient'],row['tenant_id']) for row in recipients}=={(system.user['email'],system.tenant),(second_email,second['id'])}
    # A duplicate address is rejected even when the alias is different.
    with pytest.raises(HTTPException) as duplicate:
        owner_access(system,owner_login='different-alias',owner_email=second_email.upper())
    assert duplicate.value.status_code==409
    # Even an alias that looks like another owner's email cannot shadow them.
    owner_access(system,owner_login=second_email,owner_password='fghij')
    result=system.client.post('/api/v1/auth/login',json={'login':second_email,'password':'abcde'})
    assert result.status_code==200 and result.json()['session']['tenantId']==second['id']
    assert system.client.post('/api/v1/auth/login',json={'login':second_email,'password':'fghij'}).status_code==401
    terminal=system.client.post('/api/v1/auth/login',json={'login':second['slug'],'password':'vwxyz'},headers={'X-Ashkana-Client':'pos'})
    assert terminal.status_code==200 and terminal.json()['session']['tenantId']==second['id']


def test_email_change_revokes_access_and_links_without_touching_other_accounts(system):
    assert system.client.post('/api/v1/auth/password/forgot',json={'email':system.user['email']}).status_code==200
    token=queued_token(system,'reset')
    changed=uuid4().hex[:16]+'@example.com'
    owner_access(system,owner_login=system.user['login'],owner_email=changed,owner_password='abcde')
    assert system.client.get('/api/v1/auth/me').status_code==401
    assert system.client.post('/api/v1/auth/password/reset',json={'token':token,'password':'vwxyz'}).status_code==400
    assert system.client.post('/api/v1/auth/login',json={'login':system.user['email'],'password':'abcde'}).status_code==401
    assert system.client.post('/api/v1/auth/login',json={'login':changed,'password':'abcde'}).status_code==200
    assert system.client.get('/api/v1/auth/email').json()=={'email':changed,'verified':False,'canVerify':True}


def test_email_confirmation_is_explicit_one_use_and_unlocks_billing(system):
    set_unverified(system)
    assert system.client.get('/api/v1/workspace').status_code==200
    assert system.client.get('/api/v1/auth/email').json()['verified'] is False
    assert checkout(system).status_code==403 and not system.calls
    assert system.client.get('/api/v1/billing').json()['canPay'] is False
    assert system.client.post('/api/v1/auth/email/send',json={}).status_code==200
    token=queued_token(system,'verify')
    assert system.client.get('/api/v1/auth/email').json()['verified'] is False
    # Neither a GET nor using a verification token for password recovery changes access.
    assert system.client.get('/api/v1/auth/email/verify?token='+token).status_code==405
    assert system.client.post('/api/v1/auth/password/reset',json={'token':token,'password':'New-test-password-123'}).status_code==400
    assert system.client.post('/api/v1/auth/email/verify',json={'token':token}).status_code==200
    assert system.client.get('/api/v1/auth/email').json()['verified'] is True
    assert system.client.post('/api/v1/auth/email/verify',json={'token':token}).status_code==400
    assert checkout(system).status_code==200


def test_password_recovery_is_generic_and_one_use_under_concurrency(system):
    email=system.user['login']
    known=system.client.post('/api/v1/auth/password/forgot',json={'email':email})
    unknown=system.client.post('/api/v1/auth/password/forgot',json={'email':'unknown@example.com'})
    assert known.status_code==unknown.status_code==200 and known.json()==unknown.json()
    token=queued_token(system,'reset')
    assert system.client.post('/api/v1/auth/email/verify',json={'token':token}).status_code==400
    # The minimum works through reset, hashing and subsequent real login.
    assert system.client.post('/api/v1/auth/password/reset',json={'token':token,'password':'abcd'}).status_code==422
    password='abcde'
    with ThreadPoolExecutor(max_workers=3) as executor:
        results=list(executor.map(lambda _:system.client.post('/api/v1/auth/password/reset',json={'token':token,'password':password}),range(3)))
    assert sorted(result.status_code for result in results)==[200,400,400]
    assert system.client.get('/api/v1/auth/me').status_code==401  # Existing browser session revoked.
    with system.connect() as connection:
        user=connection.execute('SELECT * FROM auth_users WHERE id=%s',(system.user['id'],)).fetchone()
        assert verify_password(password,user['password_hash']) and user['account_version']==system.user['account_version']+1
        assert user['email_verified_at']
        assert connection.execute("SELECT count(*) AS n FROM email_outbox WHERE dedup_key LIKE 'password-changed:%%' AND tenant_id=%s",(system.tenant,)).fetchone()['n']==1
        assert token not in str(connection.execute('SELECT * FROM auth_action_tokens WHERE user_id=%s',(user['id'],)).fetchall())
    logged=system.client.post('/api/v1/auth/login',json={'login':email,'password':password})
    assert logged.status_code==200
    assert system.client.get('/api/v1/workspace').status_code==200
    assert system.client.post('/api/v1/auth/password/reset',json={'token':token,'password':password}).status_code==400


@pytest.mark.parametrize('change',['expired','account-version','email','inactive','deleted'])
def test_stale_or_invalidated_reset_token_cannot_change_account(system,change):
    assert system.client.post('/api/v1/auth/password/forgot',json={'email':system.user['login']}).status_code==200
    token=queued_token(system,'reset')
    with system.connect() as connection:
        if change=='expired': connection.execute("UPDATE auth_action_tokens SET expires_at=now()-interval '1 second' WHERE user_id=%s",(system.user['id'],))
        elif change=='account-version': connection.execute('UPDATE auth_users SET account_version=account_version+1 WHERE id=%s',(system.user['id'],))
        elif change=='email': connection.execute("UPDATE auth_users SET email='changed-'||email WHERE id=%s",(system.user['id'],))
        elif change=='inactive': connection.execute('UPDATE auth_users SET is_active=false WHERE id=%s',(system.user['id'],))
        elif change=='deleted': connection.execute('UPDATE auth_users SET deleted_at=now(),is_active=false WHERE id=%s',(system.user['id'],))
    response=system.client.post('/api/v1/auth/password/reset',json={'token':token,'password':'Should-not-be-saved-123'})
    assert response.status_code==400
    with system.connect() as connection:
        user=connection.execute('SELECT password_hash FROM auth_users WHERE id=%s',(system.user['id'],)).fetchone()
    assert user['password_hash']==system.user['password_hash']


def test_login_limits_survive_failed_request_rollback_and_cannot_be_bypassed_by_header(system):
    with system.connect() as connection: connection.execute('DELETE FROM auth_rate_limits')
    body={'login':system.user['login'],'password':'wrong-password'}
    results=[system.client.post('/api/v1/auth/login',json=body,headers={'X-Forwarded-For':f'192.0.2.{index}'}) for index in range(11)]
    assert [result.status_code for result in results]==[401]*10+[429]
    assert int(results[-1].headers['Retry-After'])>0
    # A different account on the same network remains usable below the peer cap.
    assert system.client.post('/api/v1/auth/login',json={**body,'login':'other@example.com'}).status_code==401
    with system.connect() as connection:
        connection.execute("UPDATE auth_rate_limits SET resets_at=now()-interval '1 second'")
    assert system.client.post('/api/v1/auth/login',json=body).status_code==401


def test_expired_owner_can_confirm_email_without_extending_trial(system):
    set_unverified(system)
    with system.connect() as connection:
        connection.execute("UPDATE tenant_subscriptions SET trial_ends_at=now()-interval '1 day' WHERE tenant_id=%s",(system.tenant,))
        before=connection.execute('SELECT trial_ends_at FROM tenant_subscriptions WHERE tenant_id=%s',(system.tenant,)).fetchone()
    assert system.client.get('/api/v1/workspace').status_code==403
    assert system.client.post('/api/v1/auth/email/send',json={}).status_code==200
    assert system.client.post('/api/v1/auth/email/verify',json={'token':queued_token(system,'verify')}).status_code==200
    with system.connect() as connection:
        assert connection.execute('SELECT trial_ends_at FROM tenant_subscriptions WHERE tenant_id=%s',(system.tenant,)).fetchone()==before


def test_new_signup_queues_verification_once_without_delaying_trial(system):
    from uuid import uuid4
    suffix=uuid4().hex[:16]
    payload={'request_id':str(uuid4()),'name':'New Owner','company':'New Company','phone':'996'+str(uuid4().int)[:10],
             'email':suffix+'@example.com','password':'New-company-password-123','plan':'restaurant','consent':True}
    first=system.client.post('/api/v1/public/register',json=payload)
    again=system.client.post('/api/v1/public/register',json=payload)
    assert first.status_code==again.status_code==201
    assert first.json()['session']['emailVerified'] is False
    assert system.client.get('/api/v1/workspace').status_code==200
    with system.connect() as connection:
        assert connection.execute('SELECT count(*) AS n FROM email_outbox WHERE recipient=%s',(payload['email'],)).fetchone()['n']==2
        assert connection.execute("SELECT count(*) AS n FROM auth_action_tokens WHERE email=%s AND purpose='verify'",(payload['email'],)).fetchone()['n']==1


def test_operations_readiness_is_platform_only_and_never_exposes_credentials(system):
    assert system.client.get('/api/v1/platform/operations').status_code==403
    main.app.dependency_overrides[main.current_user]=lambda:{'id':system.user['id'],'role':'platform_owner'}
    response=system.client.get('/api/v1/platform/operations')
    assert response.status_code==200
    assert response.json()['account']['recovery'] is True
    assert response.json()['productionRestoreVerified'] is None
    assert 'test-secret' not in response.text and system.user['password_hash'] not in response.text


def test_expired_reset_email_is_not_delivered_late(system,monkeypatch):
    from types import SimpleNamespace
    from pydantic import SecretStr
    from app import mailer
    # All rows belong to this disposable test database.
    with system.connect() as connection: connection.execute("UPDATE email_outbox SET status='sent'")
    assert system.client.post('/api/v1/auth/password/forgot',json={'email':system.user['login']}).status_code==200
    with system.connect() as connection:
        connection.execute("UPDATE email_outbox SET expires_at=now()-interval '1 second' WHERE tenant_id=%s AND status='pending'",(system.tenant,))
    system.cfg.smtp_password=SecretStr('mock-only')
    monkeypatch.setattr(mailer,'send_message',lambda *args:pytest.fail('Expired link sent'))
    assert mailer.deliver_one(SimpleNamespace(connection=system.connect),system.cfg) is False
    with system.connect() as connection:
        assert connection.execute("SELECT last_error FROM email_outbox WHERE tenant_id=%s AND dedup_key LIKE 'account:%%'",(system.tenant,)).fetchone()['last_error']=='LinkExpired'
