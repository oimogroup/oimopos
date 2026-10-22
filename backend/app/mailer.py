"""Durable transactional email with bounded SMTP retries and TLS only."""
import hashlib
import logging
import os
import smtplib
import ssl
import threading
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Depends, HTTPException, Request

from .config import get_settings

log = logging.getLogger(__name__)


def configured(settings):
    return bool(settings.smtp_host and settings.smtp_username and settings.smtp_password.get_secret_value() and sender(settings))


def sender(settings):
    value = settings.smtp_from or settings.smtp_username
    try:
        address = Address(addr_spec=value)
        return value if address.username and address.domain else ''
    except ValueError:
        return ''


def login_url(settings):
    base = (settings.public_app_url or os.environ.get('RENDER_EXTERNAL_URL', '')).strip().rstrip('/')
    url = urlsplit(base)
    if url.username or url.password or url.query or url.fragment or url.path:
        return ''
    if url.scheme == 'https' and url.hostname:
        return base + '/login'
    if url.scheme == 'http' and url.hostname in {'localhost', '127.0.0.1'}:
        return base + '/login'
    return ''


def enqueue(connection, *, dedup_key, recipient, subject, body, tenant_id=None, expires_at=None):
    connection.execute(
        '''INSERT INTO email_outbox (tenant_id, dedup_key, recipient, subject, body, expires_at)
           VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (dedup_key) DO NOTHING''',
        (tenant_id, dedup_key, recipient, subject, body, expires_at),
    )


def enqueue_welcome(connection, tenant, name, email):
    settings = get_settings()
    end = tenant['trial_ends_at'].strftime('%d.%m.%Y')
    body = (f'Здравствуйте, {name}!\n\n'
            f'Ваш аккаунт Oimo для «{tenant["name"]}» создан.\n'
            f'Пробный доступ для одного заведения действует до {end}.\n'
            f'Логин: {email}\n'
            'Используйте пароль, который вы указали при регистрации.\n\n'
            'Начните с настройки меню, склада, сотрудников и кассы в админке.\n'
            'Автоматических списаний нет. Для продолжения после пробного периода свяжитесь с командой Oimo.\n')
    if url := login_url(settings):
        body += '\nВойти в Oimo: ' + url + '\n'
    body += '\nКоманда Oimo\n'
    enqueue(connection, dedup_key='welcome:'+tenant['id'], tenant_id=tenant['id'],
            recipient=email, subject='Добро пожаловать в Oimo — 14 дней пробного доступа', body=body)


def send_message(row, settings):
    if not configured(settings):
        raise RuntimeError('SMTP is not configured')
    message = EmailMessage()
    from_address = sender(settings)
    message['From'] = Address(settings.smtp_from_name, addr_spec=from_address)
    message['To'] = Address(addr_spec=row['recipient'])
    message['Subject'] = row['subject']
    digest = hashlib.sha256(row['dedup_key'].encode()).hexdigest()
    message['Message-ID'] = f'<oimo-{digest}@{from_address.rsplit("@", 1)[-1]}>'
    message['Date'] = formatdate(localtime=False)
    message.set_content(row['body'])
    context = ssl.create_default_context()
    if settings.smtp_port == 465:
        smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15, context=context)
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
    with smtp:
        if settings.smtp_port != 465:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        # Google's UI groups the app password in blocks of four characters.
        password = settings.smtp_password.get_secret_value()
        if settings.smtp_host == 'smtp.gmail.com':
            password = password.replace(' ', '')
        smtp.login(settings.smtp_username, password)
        rejected = smtp.send_message(message)
        if rejected:
            raise smtplib.SMTPRecipientsRefused(rejected)


def deliver_one(pool, settings):
    if not configured(settings):
        return False
    lock_token = uuid4()
    with pool.connection() as connection, connection.transaction():
        connection.execute("UPDATE email_outbox SET status='failed',attempts=6,last_error='LinkExpired',lock_token=NULL,locked_until=NULL WHERE (status='pending' OR (status='sending' AND locked_until<now())) AND expires_at<=now()")
        connection.execute("UPDATE email_outbox SET status='failed', lock_token=NULL, locked_until=NULL, last_error='DeliveryInterrupted' WHERE status='sending' AND locked_until < now() AND attempts >= 6")
        row = connection.execute(
            '''SELECT * FROM email_outbox WHERE attempts < 6 AND
               ((status = 'pending' AND next_attempt_at <= now()) OR
                (status = 'sending' AND locked_until < now()))
               AND (expires_at IS NULL OR expires_at>now())
               ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED''',
        ).fetchone()
        if not row:
            return False
        connection.execute(
            "UPDATE email_outbox SET status='sending', attempts=attempts+1, lock_token=%s, locked_until=now()+interval '2 minutes' WHERE id=%s",
            (lock_token, row['id']),
        )
    error = ''
    try:
        send_message(row, settings)
    except Exception as exc:
        # Never store raw SMTP errors: providers can include addresses or credentials.
        error = type(exc).__name__
    attempts = row['attempts'] + 1
    state = 'failed' if error and attempts >= 6 else 'pending' if error else 'sent'
    with pool.connection() as connection, connection.transaction():
        connection.execute(
            '''UPDATE email_outbox SET status=%s, last_error=%s, lock_token=NULL, locked_until=NULL,
               sent_at=CASE WHEN %s='sent' THEN now() ELSE sent_at END,
               next_attempt_at=now()+(%s * interval '1 second') WHERE id=%s AND lock_token=%s''',
            (state, error, state, min(3600, 30 * 2 ** (attempts - 1)), row['id'], lock_token),
        )
    return True


def start_worker(pool):
    stop = threading.Event()

    def run():
        while not stop.is_set():
            delay = 15
            try:
                if deliver_one(pool, get_settings()):
                    delay = 1
            except Exception as exc:
                log.warning('Email queue temporarily unavailable (%s)', type(exc).__name__)
            stop.wait(delay)

    thread = threading.Thread(target=run, name='oimo-email', daemon=True)
    thread.start()
    return stop, thread


def install(app):
    from . import main

    @app.get('/api/v1/platform/mail', tags=['platform'])
    def mail_status(user=Depends(main.current_user), connection=Depends(main.get_connection)):
        main._platform_owner(user)
        settings = get_settings()
        counts = connection.execute('SELECT status, count(*) AS total FROM email_outbox GROUP BY status').fetchall()
        recent = connection.execute(
            'SELECT id, status, attempts, last_error, created_at, sent_at FROM email_outbox ORDER BY id DESC LIMIT 10'
        ).fetchall()
        return dict(configured=configured(settings), sender=sender(settings), testRecipient=settings.smtp_test_recipient,
                    counts={row['status']: row['total'] for row in counts}, recent=[dict(row) for row in recent])

    @app.post('/api/v1/platform/mail/test', tags=['platform'])
    def test_mail(request: Request, user=Depends(main.current_user), connection=Depends(main.get_connection)):
        main._check_origin(request)
        main._platform_owner(user)
        settings = get_settings()
        if not configured(settings):
            raise HTTPException(409, 'Проверьте SMTP_HOST, SMTP_USERNAME, SMTP_FROM и SMTP_PASSWORD в Environment сервиса Render.')
        with connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('mail-test',0))")
            recent = connection.execute("SELECT id FROM email_outbox WHERE dedup_key LIKE 'test:%' AND created_at > now()-interval '1 minute' LIMIT 1").fetchone()
            if recent:
                raise HTTPException(429, 'Тестовое письмо уже в очереди. Подождите минуту.')
            enqueue(connection, dedup_key='test:'+str(uuid4()), recipient=settings.smtp_test_recipient,
                    subject='Oimo — проверка системной почты', body=f'Это тестовое письмо от Oimo.\nОтправитель: {sender(settings)}\n')
        return {'queued': True}

    @app.post('/api/v1/platform/mail/retry', tags=['platform'])
    def retry_mail(request: Request, user=Depends(main.current_user), connection=Depends(main.get_connection)):
        main._check_origin(request)
        main._platform_owner(user)
        with connection.transaction():
            connection.execute("UPDATE email_outbox SET status='pending', attempts=0, next_attempt_at=now(), last_error='' WHERE status='failed' AND (expires_at IS NULL OR expires_at>now())")
        return {'ok': True}
