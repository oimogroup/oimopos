"""Email ownership and one-use password recovery; no tokens in URLs sent to servers."""
import hashlib
import hmac
import secrets
import time
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from psycopg.types.json import Jsonb

from . import mailer
from .config import get_settings
from .schemas import ContactEmail, LoginInput
from .security import hash_password, token_hash


class EmailInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: ContactEmail


class TokenInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{43,128}$')]


class ResetInput(TokenInput):
    password: Annotated[str, StringConstraints(min_length=12, max_length=200)]


def bucket_key(kind, value):
    return hmac.new(get_settings().employee_pin_key.encode(), (kind+':'+value).encode(), hashlib.sha256).hexdigest()


def rate_limit(connection, request, action, identity='', *, pair_limit=10, peer_limit=60, seconds=900):
    """Commit counters before authentication; a later 401 must not roll them back.

    The ASGI peer is set by the trusted proxy configuration, never by a header
    supplied directly to this function. Avoid account-wide attacker lockouts.
    """
    peer=request.client.host if request.client else 'unknown'
    limits=[(bucket_key(action+':peer',peer),peer_limit)]
    if identity: limits.append((bucket_key(action+':pair',peer+':'+identity.lower()),pair_limit))
    blocked=False
    with connection.transaction():
        connection.execute('DELETE FROM auth_rate_limits WHERE resets_at < now() - interval \'1 day\'')
        for key, maximum in sorted(limits):
            row=connection.execute('''INSERT INTO auth_rate_limits (bucket,attempts,resets_at)
              VALUES (%s,1,now()+(%s * interval '1 second'))
              ON CONFLICT (bucket) DO UPDATE SET
                attempts=CASE WHEN auth_rate_limits.resets_at<=now() THEN 1 ELSE LEAST(auth_rate_limits.attempts+1,%s+1) END,
                resets_at=CASE WHEN auth_rate_limits.resets_at<=now() THEN EXCLUDED.resets_at ELSE auth_rate_limits.resets_at END
              RETURNING attempts''',(key,seconds,maximum)).fetchone()
            blocked=blocked or row['attempts']>maximum
    if blocked:
        raise HTTPException(429,'Слишком много попыток. Повторите через 15 минут.',headers={'Retry-After':str(seconds)})


def send_link(connection, user, purpose):
    """The outbox and token are committed atomically with account provisioning."""
    url=mailer.login_url(get_settings())
    if not url: return False
    email=user['login'].strip().lower()
    if '@' not in email or user.get('staff_role')=='pos_terminal': return False
    if purpose=='verify' and user.get('email_verified_at'): return False
    # Resends reuse an unexpired queued link for one minute instead of flooding.
    recent=connection.execute("SELECT token_hash FROM auth_action_tokens WHERE user_id=%s AND purpose=%s AND consumed_at IS NULL AND expires_at>now() AND created_at>now()-interval '1 minute'",(user['id'],purpose)).fetchone()
    if recent: return True
    sent=connection.execute("SELECT count(*) AS n FROM auth_action_tokens WHERE user_id=%s AND purpose=%s AND created_at>now()-interval '15 minutes'",(user['id'],purpose)).fetchone()
    if sent['n']>=3: return True
    raw=secrets.token_urlsafe(32)
    digest=token_hash(raw)
    lifetime=1800 if purpose=='reset' else 86400
    token=connection.execute('''INSERT INTO auth_action_tokens (token_hash,user_id,purpose,email,account_version,expires_at)
      VALUES (%s,%s,%s,%s,%s,now()+(%s * interval '1 second')) RETURNING expires_at''',(digest,user['id'],purpose,email,user['account_version'],lifetime)).fetchone()
    link=url.rsplit('/login',1)[0]+'/account#action='+purpose+'&token='+quote(raw,safe='')
    subject='Oimo — восстановление пароля' if purpose=='reset' else 'Oimo — подтвердите email'
    body=(('Для смены пароля откройте ссылку. Она действует 30 минут.\n' if purpose=='reset' else 'Подтвердите адрес вашего аккаунта Oimo. Ссылка действует 24 часа.\n')
          +link+'\n\nЕсли вы не запрашивали это действие, проигнорируйте письмо. Никому не передавайте ссылку.\nКоманда Oimo\n')
    mailer.enqueue(connection,dedup_key='account:'+digest,tenant_id=user.get('tenant_id'),recipient=email,subject=subject,body=body,expires_at=token['expires_at'])
    return True


def install(app):
    from . import main

    @app.post('/api/v1/auth/login',tags=['auth'])
    def login(payload:LoginInput,response:Response,request:Request,connection=Depends(main.get_connection)):
        main._check_origin(request)
        rate_limit(connection,request,'login',payload.login,pair_limit=10,peer_limit=100)
        return main.login(payload,response,request,connection)

    @app.post('/api/v1/auth/password/forgot',tags=['auth'])
    def forgot(payload:EmailInput,request:Request,connection=Depends(main.get_connection)):
        started=time.monotonic()
        main._check_origin(request)
        rate_limit(connection,request,'recovery',payload.email,pair_limit=3,peer_limit=20)
        # The response does not reveal whether an account exists or SMTP is enabled.
        with connection.transaction():
            user=connection.execute("SELECT * FROM auth_users WHERE lower(login)=%s AND is_active AND deleted_at IS NULL AND staff_role<>'pos_terminal' FOR UPDATE",(payload.email,)).fetchone()
            if user: send_link(connection,user,'reset')
        time.sleep(max(0,0.25-time.monotonic()+started))
        return {'ok':True,'message':'Если аккаунт с этим email существует, письмо для восстановления будет отправлено. Проверьте входящие и спам.'}

    @app.get('/api/v1/auth/email',tags=['auth'])
    def email_status(user=Depends(main.current_user),connection=Depends(main.get_connection)):
        row=connection.execute('SELECT login,email_verified_at FROM auth_users WHERE id=%s',(user['id'],)).fetchone()
        return {'email':row['login'],'verified':bool(row['email_verified_at']),'canVerify':'@' in row['login'] and user.get('staff_role')!='pos_terminal'}

    @app.post('/api/v1/auth/email/send',tags=['auth'])
    def resend(request:Request,user=Depends(main.current_user),connection=Depends(main.get_connection)):
        main._check_origin(request)
        # current_user opened a transaction; finish its last_seen update before
        # independently committing the limiter, then lock the account for issuance.
        connection.commit()
        rate_limit(connection,request,'verify',str(user['id']),pair_limit=3,peer_limit=20)
        with connection.transaction():
            row=connection.execute('SELECT * FROM auth_users WHERE id=%s FOR UPDATE',(user['id'],)).fetchone()
            if row['email_verified_at']: return {'ok':True,'verified':True}
            if '@' not in row['login'] or row['staff_role']=='pos_terminal': raise HTTPException(409,'Укажите email для этой учётной записи через администратора.')
            send_link(connection,row,'verify')
        return {'ok':True,'verified':False,'message':'Письмо подтверждения поставлено в очередь. Проверьте входящие и спам.'}

    def consume(payload, request, connection, purpose):
        main._check_origin(request)
        rate_limit(connection,request,'token',pair_limit=30,peer_limit=30)
        digest=token_hash(payload.token)
        with connection.transaction():
            initial=connection.execute('SELECT user_id FROM auth_action_tokens WHERE token_hash=%s AND purpose=%s',(digest,purpose)).fetchone()
            if not initial: raise HTTPException(400,'Ссылка недействительна или срок её действия истёк. Запросите новое письмо.')
            user=connection.execute('SELECT * FROM auth_users WHERE id=%s FOR UPDATE',(initial['user_id'],)).fetchone()
            token=connection.execute('SELECT *,expires_at>now() AS valid FROM auth_action_tokens WHERE token_hash=%s FOR UPDATE',(digest,)).fetchone()
            if not user or not user['is_active'] or user['deleted_at'] or token['consumed_at'] or not token['valid'] or token['account_version']!=user['account_version'] or token['email']!=user['login'].lower():
                raise HTTPException(400,'Ссылка недействительна или срок её действия истёк. Запросите новое письмо.')
            if purpose=='reset':
                connection.execute('''UPDATE auth_users SET password_hash=%s,account_version=account_version+1,email_verified_at=COALESCE(email_verified_at,now()),updated_at=now() WHERE id=%s''',(hash_password(payload.password),user['id']))
                connection.execute('UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL',(user['id'],))
                connection.execute('UPDATE pos_operator_sessions SET revoked_at=now() WHERE employee_user_id=%s AND revoked_at IS NULL',(user['id'],))
                connection.execute('UPDATE auth_action_tokens SET consumed_at=now() WHERE user_id=%s AND consumed_at IS NULL',(user['id'],))
                mailer.enqueue(connection,dedup_key='password-changed:'+digest,tenant_id=user['tenant_id'],recipient=user['login'],subject='Oimo — пароль изменён',body='Пароль аккаунта Oimo изменён. Все прежние сеансы завершены. Если это были не вы, восстановите доступ и обратитесь в поддержку.\n')
            else:
                connection.execute('UPDATE auth_users SET email_verified_at=COALESCE(email_verified_at,now()),updated_at=now() WHERE id=%s',(user['id'],))
                connection.execute("UPDATE auth_action_tokens SET consumed_at=now() WHERE user_id=%s AND purpose='verify' AND consumed_at IS NULL",(user['id'],))
            connection.execute('INSERT INTO platform_events (actor_user_id,actor_login,action,tenant_id,payload) VALUES (%s,%s,%s,%s,%s)',(user['id'],user['login'],'account.password_reset' if purpose=='reset' else 'account.email_verified',user['tenant_id'],Jsonb({})))
        return {'ok':True}

    @app.post('/api/v1/auth/password/reset',tags=['auth'])
    def reset(payload:ResetInput,request:Request,connection=Depends(main.get_connection)):
        return consume(payload,request,connection,'reset')

    @app.post('/api/v1/auth/email/verify',tags=['auth'])
    def verify(payload:TokenInput,request:Request,connection=Depends(main.get_connection)):
        return consume(payload,request,connection,'verify')
