"""Tenant-owned Telegram routing and bounded low-stock delivery outside HTTP writes."""
import hashlib
import json
import logging
import re
import threading
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4

from fastapi import HTTPException, Depends, Request as WebRequest
from .database import get_connection
from psycopg.types.json import Jsonb
from .config import get_settings

log = logging.getLogger(__name__)


class TelegramError(Exception):
    def __init__(self, message, retry_after=60):
        super().__init__(message)
        self.retry_after = max(30, min(int(retry_after), 3600))


def encryption_key(settings):
    if len(settings.employee_pin_key) < 32:
        raise HTTPException(503, 'Не настроен серверный ключ хранения интеграций')
    return hashlib.sha256(('telegram-stock:' + settings.employee_pin_key).encode()).hexdigest()


def bot_request(token, method, payload=None):
    if not re.fullmatch(r'\d{5,16}:[A-Za-z0-9_-]{20,100}', token or ''):
        raise TelegramError('Некорректный токен бота')
    request = Request('https://api.telegram.org/bot' + token + '/' + method,
                      data=json.dumps(payload or {}).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read(1024 * 1024 + 1)
    except HTTPError as exc:
        try:
            raw = exc.read(1024 * 1024 + 1)
        finally:
            exc.close()
    except Exception:
        raise TelegramError('Нет связи с Telegram. Повторная попытка запланирована') from None
    try:
        if len(raw) > 1024 * 1024:
            raise ValueError()
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError()
    except Exception:
        raise TelegramError('Telegram вернул некорректный ответ') from None
    if body.get('ok') is not True:
        code = body.get('error_code')
        messages = {401:'Telegram отклонил токен бота', 403:'Бот удалён из группы или ему запрещено отправлять сообщения',
                    409:'У бота настроен webhook. Укажите ID группы вручную', 429:'Telegram ограничил частоту отправки'}
        text = messages.get(code, 'Проверьте ID группы и разрешение бота отправлять сообщения')
        if body.get('parameters', {}).get('migrate_to_chat_id'):
            text = 'Группа преобразована в супергруппу. Обновите ID группы в интеграции'
        retry = body.get('parameters', {}).get('retry_after', 60)
        try:
            retry = int(retry)
        except (ValueError, TypeError):
            retry = 60
        raise TelegramError(text, retry)
    return body.get('result')


def owner(user):
    if user.get('role') != 'owner' or not user.get('tenant_id'):
        raise HTTPException(403, 'Интеграциями управляет администратор компании')


def context(connection, user):
    owner(user)
    tenant = user['tenant_id']
    integration = connection.execute('SELECT enabled, bot_username, bot_token IS NOT NULL AS configured, revision FROM telegram_integrations WHERE tenant_id=%s', (tenant,)).fetchone()
    branches = connection.execute("SELECT payload->'branches' AS branches FROM operational_state WHERE tenant_id=%s", (tenant,)).fetchone()
    routes = {r['branch_id']: r for r in connection.execute('SELECT branch_id,chat_id,thread_id,enabled,last_sent_at,last_checked_at,last_error FROM telegram_stock_routes WHERE tenant_id=%s', (tenant,)).fetchall()}
    return {**(integration or {'enabled':False, 'bot_username':'', 'configured':False, 'revision':0}),
            'routes':[{'branchId': b['id'], 'branchName':b['name'], **{
                'chatId':str(routes.get(b['id'], {}).get('chat_id') or ''),
                'threadId':str(routes.get(b['id'], {}).get('thread_id') or ''),
                'enabled':routes.get(b['id'], {}).get('enabled', False),
                'lastSentAt':routes.get(b['id'], {}).get('last_sent_at'),
                'lastCheckedAt':routes.get(b['id'], {}).get('last_checked_at'),
                'lastError':routes.get(b['id'], {}).get('last_error', ''),
            }} for b in (branches or {}).get('branches', []) if b.get('status') == 'active']}


def valid_routes(raw, branches):
    if not isinstance(raw, list) or len(raw) > 100:
        raise HTTPException(422, 'Укажите не более 100 точек')
    result, seen = [], set()
    for route in raw:
        if not isinstance(route, dict):
            raise HTTPException(422, 'Проверьте настройки точки')
        branch = str(route.get('branchId', ''))
        if branch not in branches or branch in seen:
            raise HTTPException(422, 'Выберите действующую точку без повторов')
        seen.add(branch)
        enabled = route.get('enabled') is True
        chat = str(route.get('chatId') or '').strip()
        thread = str(route.get('threadId') or '').strip()
        if (chat and not re.fullmatch(r'-[1-9]\d{0,17}', chat)) or (enabled and not chat):
            raise HTTPException(422, 'Укажите отрицательный числовой ID группы для точки ' + branches[branch])
        if thread and not re.fullmatch(r'[1-9]\d{0,9}', thread):
            raise HTTPException(422, 'Номер темы должен быть положительным числом')
        result.append((branch, int(chat) if chat else None, int(thread) if thread else None, enabled))
    return result


def save(connection, user, payload, settings):
    owner(user)
    key = encryption_key(settings)
    tenant = user['tenant_id']
    token = str(payload.get('token') or '').strip()
    bot = None
    if token:
        try:
            bot = bot_request(token, 'getMe')
        except TelegramError as exc:
            raise HTTPException(422, str(exc)) from None
        if not isinstance(bot, dict) or bot.get('is_bot') is not True or not bot.get('username'):
            raise HTTPException(422, 'Telegram не подтвердил учётную запись бота')
    with connection.transaction():
        connection.execute('INSERT INTO telegram_integrations(tenant_id) VALUES (%s) ON CONFLICT DO NOTHING', (tenant,))
        previous = connection.execute('SELECT enabled, revision, bot_token IS NOT NULL AS configured FROM telegram_integrations WHERE tenant_id=%s FOR UPDATE', (tenant,)).fetchone()
        if payload.get('revision') != previous['revision']:
            raise HTTPException(409, 'Настройки изменены в другой вкладке. Обновите страницу')
        branches = connection.execute("SELECT payload->'branches' AS branches FROM operational_state WHERE tenant_id=%s", (tenant,)).fetchone()
        active = {str(b['id']):b['name'] for b in (branches or {}).get('branches', []) if b.get('status') == 'active'}
        routes = valid_routes(payload.get('routes'), active)
        enabled = payload.get('enabled') is True
        if enabled and not (token or previous['configured']):
            raise HTTPException(422, 'Сначала укажите токен Telegram-бота')
        if token:
            connection.execute("UPDATE telegram_integrations SET bot_token=pgp_sym_encrypt(%s,%s),bot_username=%s WHERE tenant_id=%s", (token,key,bot['username'],tenant))
        connection.execute('UPDATE telegram_integrations SET enabled=%s,revision=revision+1,updated_at=now() WHERE tenant_id=%s', (enabled,tenant))
        # Invalidates in-flight claims; unchanged targets retain their notified state.
        reset_all = bool(token) or (enabled and not previous['enabled'])
        for branch, chat, thread, on in routes:
            old = connection.execute('SELECT chat_id,thread_id,enabled FROM telegram_stock_routes WHERE tenant_id=%s AND branch_id=%s', (tenant,branch)).fetchone()
            reset = reset_all or not old or (old['chat_id'],old['thread_id'],old['enabled']) != (chat,thread,on)
            connection.execute("""INSERT INTO telegram_stock_routes(tenant_id,branch_id,chat_id,thread_id,enabled)
              VALUES (%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,branch_id) DO UPDATE SET
              chat_id=EXCLUDED.chat_id,thread_id=EXCLUDED.thread_id,enabled=EXCLUDED.enabled,
              revision=telegram_stock_routes.revision+1,
              notified_keys=CASE WHEN %s THEN '{}'::text[] ELSE telegram_stock_routes.notified_keys END,
              lease_id=NULL,lease_until=NULL,next_attempt=now(),last_error='',attempts=0""", (tenant,branch,chat,thread,on,reset))
        selected = [r[0] for r in routes]
        connection.execute('UPDATE telegram_stock_routes SET enabled=false,revision=revision+1,lease_id=NULL,lease_until=NULL WHERE tenant_id=%s AND NOT(branch_id=ANY(%s))', (tenant,selected))
        connection.execute("INSERT INTO audit_events(tenant_id,actor,action,entity_type,entity_id,after_state) VALUES (%s,%s,'integration.telegram.update','integration','telegram',%s)", (tenant,user['display_name'],Jsonb({'enabled':enabled,'tokenChanged':bool(token),'branches':[r[0] for r in routes]})))
    return context(connection,user)


def token_for(connection, tenant, settings):
    row = connection.execute('SELECT pgp_sym_decrypt(bot_token,%s) AS token FROM telegram_integrations WHERE tenant_id=%s AND bot_token IS NOT NULL', (encryption_key(settings),tenant)).fetchone()
    if not row:
        raise HTTPException(409, 'Сначала сохраните токен бота')
    return row['token']


def discover(connection, user, settings):
    owner(user)
    token = token_for(connection,user['tenant_id'],settings)
    try:
        updates = bot_request(token,'getUpdates',{'limit':100,'timeout':0})
    except TelegramError as exc:
        raise HTTPException(422,str(exc)) from None
    chats = {}
    for update in updates if isinstance(updates,list) else []:
        message = update.get('message') or update.get('my_chat_member') or {}
        chat = message.get('chat') or {}
        if chat.get('type') in {'group','supergroup'} and isinstance(chat.get('id'),int) and chat['id'] < 0:
            chats[str(chat['id'])] = {'id':str(chat['id']), 'title':str(chat.get('title') or chat['id'])}
    return {'chats':list(chats.values())}


def test_route(connection, user, branch_id, settings):
    owner(user)
    config = context(connection,user)
    route = next((r for r in config['routes'] if r['branchId'] == branch_id),None)
    if not route or not route['chatId']:
        raise HTTPException(422,'Сначала сохраните ID группы для этой точки')
    token = token_for(connection,user['tenant_id'],settings)
    payload = {'chat_id':route['chatId'],'text':'Oimo · Проверка уведомлений\nТочка: '+route['branchName']+'\nСообщения о низких остатках будут приходить в эту группу.'}
    if route['threadId']:
        payload['message_thread_id'] = int(route['threadId'])
    try:
        bot_request(token,'sendMessage',payload)
    except TelegramError as exc:
        raise HTTPException(422,str(exc)) from None
    connection.execute('UPDATE telegram_stock_routes SET last_error=\'\' WHERE tenant_id=%s AND branch_id=%s AND chat_id=%s', (user['tenant_id'],branch_id,int(route['chatId'])))
    connection.execute("INSERT INTO audit_events(tenant_id,actor,action,entity_type,entity_id,after_state) VALUES (%s,%s,'integration.telegram.test','integration',%s,%s)", (user['tenant_id'],user['display_name'],branch_id,Jsonb({'branchId':branch_id,'chatId':route['chatId']})))
    return {'sent':True}


def shortages(snapshot):
    result = []
    stocks = snapshot.get('stocks') or {}
    for kind in ('ingredients','products'):
        for item in snapshot.get(kind) or []:
            if item.get('is_active') is False:
                continue
            try:
                minimum = Decimal(str(item.get('limit') or 0))
                current = Decimal(str(stocks.get(str(item['id']),0)))
            except (InvalidOperation,ValueError,TypeError):
                continue
            if not minimum.is_finite() or not current.is_finite() or minimum <= 0 or current > minimum:
                continue
            result.append({'key':kind+':'+str(item['id']), 'name':str(item['name']), 'unit':str(item.get('unit') or 'шт'), 'quantity':current, 'minimum':minimum})
    return sorted(result,key=lambda row:(row['name'],row['key']))


def plan_alert(items, notified):
    current = {row['key'] for row in items}
    known = set(notified or []) & current
    return sorted(known), [row for row in items if row['key'] not in known][:20]


def format_message(branch, items):
    def number(value):
        try:
            text = format(value.quantize(Decimal('.001')), 'f').rstrip('0').rstrip('.')
        except InvalidOperation:
            text = format(value,'.6g')
        if len(text) > 24:
            text = format(value,'.6g')
        return text.replace('.',',')
    lines = ['⚠️ Oimo · Заканчиваются запасы', 'Точка: '+str(branch)[:150], '']
    for item in items:
        lines.append(f"• {item['name'][:100]}: {number(item['quantity'])} {item['unit'][:10]} · минимум {number(item['minimum'])}")
    lines.extend(['','Проверьте склад и запланируйте поставку.'])
    return '\n'.join(lines)


def process_one(pool, settings, sender=bot_request):
    key = encryption_key(settings)
    lease = str(uuid4())
    with pool.connection(timeout=1) as connection:
        with connection.transaction():
            connection.execute("SET LOCAL statement_timeout='5s'")
            route = connection.execute("""SELECT r.*,pgp_sym_decrypt(i.bot_token,%s) AS token
              FROM telegram_stock_routes r JOIN telegram_integrations i USING(tenant_id)
              JOIN tenants t ON t.id=r.tenant_id
              WHERE r.enabled AND i.enabled AND i.bot_token IS NOT NULL AND t.status='active'
              AND r.next_attempt<=now() AND (r.lease_until IS NULL OR r.lease_until<now())
              ORDER BY r.next_attempt,r.tenant_id,r.branch_id LIMIT 1 FOR UPDATE OF r SKIP LOCKED""", (key,)).fetchone()
            if not route:
                return False
            row = connection.execute("""SELECT
              (SELECT jsonb_build_object('name',b->>'name','status',b->>'status') FROM jsonb_array_elements(payload->'branches') b WHERE b->>'id'=%s) AS branch,
              (SELECT jsonb_agg(jsonb_build_object('id',i->'id','name',i->'name','unit',i->'unit','limit',i->'limit','is_active',i->'is_active')) FROM jsonb_array_elements(coalesce(payload->'ingredients','[]')) i) AS ingredients,
              (SELECT jsonb_agg(jsonb_build_object('id',i->'id','name',i->'name','unit',i->'unit','limit',i->'limit','is_active',i->'is_active')) FROM jsonb_array_elements(coalesce(payload->'products','[]')) i) AS products,
              payload#>ARRAY['logisticsState','branchStocks',%s] AS stocks
              FROM operational_state WHERE tenant_id=%s""", (route['branch_id'],route['branch_id'],route['tenant_id'])).fetchone()
            branch = (row or {}).get('branch') or {}
            items = shortages(row or {}) if branch.get('status') == 'active' else []
            known, pending = plan_alert(items,route['notified_keys'])
            if not pending:
                connection.execute("UPDATE telegram_stock_routes SET notified_keys=%s,lease_id=NULL,lease_until=NULL,last_checked_at=now(),next_attempt=now()+interval '60 seconds' WHERE tenant_id=%s AND branch_id=%s", (known,route['tenant_id'],route['branch_id']))
                return True
            connection.execute("UPDATE telegram_stock_routes SET lease_id=%s,lease_until=now()+interval '30 seconds',last_checked_at=now() WHERE tenant_id=%s AND branch_id=%s", (lease,route['tenant_id'],route['branch_id']))
    # Telegram is contacted after returning the database connection to the pool.
    payload = {'chat_id':route['chat_id'],'text':format_message(branch.get('name',route['branch_id']),pending)}
    if route['thread_id']:
        payload['message_thread_id'] = route['thread_id']
    error = None
    try:
        sender(route['token'],'sendMessage',payload)
    except TelegramError as exc:
        error = exc
    except Exception:
        error = TelegramError('Не удалось подтвердить доставку в Telegram')
    with pool.connection(timeout=1) as connection:
        with connection.transaction():
            if error:
                delay = max(error.retry_after, min(3600,60*2**min(route['attempts'],6)))
                connection.execute("""UPDATE telegram_stock_routes SET lease_id=NULL,lease_until=NULL,attempts=attempts+1,
                  last_error=%s,next_attempt=now()+(%s*interval '1 second')
                  WHERE tenant_id=%s AND branch_id=%s AND lease_id=%s AND revision=%s""", (str(error),delay,route['tenant_id'],route['branch_id'],lease,route['revision']))
            else:
                connection.execute("""UPDATE telegram_stock_routes SET lease_id=NULL,lease_until=NULL,attempts=0,last_error='',last_sent_at=now(),
                  notified_keys=%s,next_attempt=now()+interval '60 seconds'
                  WHERE tenant_id=%s AND branch_id=%s AND lease_id=%s AND revision=%s""", (sorted(set(known)|{row['key'] for row in pending}),route['tenant_id'],route['branch_id'],lease,route['revision']))
    return True


def start_worker(pool):
    stop = threading.Event()
    def run():
        while not stop.is_set():
            delay = 30
            try:
                if len(get_settings().employee_pin_key) >= 32 and process_one(pool,get_settings()):
                    delay = 1
            except Exception as exc:
                log.warning('Telegram stock notifications temporarily unavailable (%s)',type(exc).__name__)
            stop.wait(delay)
    thread = threading.Thread(target=run,name='telegram-stock-alerts',daemon=True)
    thread.start()
    return stop,thread


def install(app):
    from .main import current_user, _check_origin

    @app.get('/api/v1/integrations/telegram', tags=['integrations'])
    def read(user: dict = Depends(current_user), connection=Depends(get_connection)):
        return context(connection,user)

    @app.put('/api/v1/integrations/telegram', tags=['integrations'])
    def update(payload: dict, request: WebRequest, user: dict = Depends(current_user), connection=Depends(get_connection)):
        owner(user)
        _check_origin(request)
        return save(connection,user,payload,get_settings())

    @app.post('/api/v1/integrations/telegram/groups', tags=['integrations'])
    def groups(request: WebRequest, user: dict = Depends(current_user), connection=Depends(get_connection)):
        owner(user)
        _check_origin(request)
        return discover(connection,user,get_settings())

    @app.post('/api/v1/integrations/telegram/test/{branch_id}', tags=['integrations'])
    def test(branch_id: str, request: WebRequest, user: dict = Depends(current_user), connection=Depends(get_connection)):
        owner(user)
        _check_origin(request)
        return test_route(connection,user,branch_id,get_settings())
