"""One-off SaaS subscription payments; restaurant operational ledgers are untouched."""
import calendar
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import os
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb
from psycopg.errors import UniqueViolation

from . import freedompay, legal
from .config import get_settings

logger=logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


def money(value):
    try:
        result=Decimal(str(value))
        if not result.is_finite() or abs(result)>Decimal('9999999999.99'):
            raise ValueError()
        return result
    except (ValueError,InvalidOperation) as exc:
        raise ValueError('Некорректная сумма') from exc


def add_months(value, months):
    year, month = divmod(value.year * 12 + value.month - 1 + months, 12)
    month += 1
    return value.replace(year=year,month=month,day=min(value.day,calendar.monthrange(year,month)[1]))


def next_month(value):
    return add_months(value, 1)


def base_url(settings):
    value=(settings.public_app_url or os.environ.get('RENDER_EXTERNAL_URL','')).rstrip('/')
    try:
        parsed=urlsplit(value)
        return value if parsed.scheme=='https' and parsed.hostname and parsed.port in (None,443) and not parsed.path and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment else ''
    except ValueError:
        return ''


def readiness(settings):
    absent=legal.missing(settings)
    if not settings.freedompay_enabled: absent.append('FREEDOMPAY_ENABLED')
    if not re.fullmatch('[0-9]+',settings.freedompay_merchant_id): absent.append('FREEDOMPAY_MERCHANT_ID')
    if not settings.freedompay_secret_key.get_secret_value(): absent.append('FREEDOMPAY_SECRET_KEY')
    if not base_url(settings): absent.append('PUBLIC_APP_URL')
    if settings.freedompay_init_path not in {'/init_payment','/init_payment.php'}: absent.append('FREEDOMPAY_INIT_PATH')
    try: freedompay.api_base(settings)
    except freedompay.ProviderError: absent.append('FREEDOMPAY_API_BASE')
    return absent


def event(connection,order_id,kind,details=None):
    connection.execute('INSERT INTO subscription_payment_events (order_id,kind,payload) VALUES (%s,%s,%s)',(order_id,kind,Jsonb(details or {})))


def public_order(row):
    return {key:row.get(key) for key in ('id','plan_code','period_months','amount','currency','testing','status','provider_payment_id','checkout_url','created_at','expires_at','applied_at','service_starts_at','service_ends_at','refund_amount','review_reason','terms_version')}


def validate_payment(order,values,settings,*,bound_status=False):
    if order['merchant_id']!=settings.freedompay_merchant_id:
        raise ValueError('Магазин платежа изменился')
    if values.get('pg_merchant_id',order['merchant_id'])!=order['merchant_id']:
        raise ValueError('Неверный магазин')
    if values.get('pg_order_id',order['id'])!=order['id']:
        raise ValueError('Неверный номер заказа')
    if money(values.get('pg_amount'))!=order['amount'] or values.get('pg_currency')!=order['currency']:
        raise ValueError('Сумма или валюта платежа отличается от заказа')
    mode=values.get('pg_testing_mode')
    # Signed status responses may omit mode. Only a payment ID already bound by a
    # signed initialization/result is trusted in that case; the frozen order
    # mode remains authoritative. Test orders can never extend live access.
    if mode!=('1' if order['testing'] else '0') and not (mode is None and bound_status and order.get('provider_payment_id')==values.get('pg_payment_id')):
        raise ValueError('Провайдер не подтвердил режим платежа')
    payment_id=values.get('pg_payment_id','')
    if not re.fullmatch('[1-9][0-9]{0,30}',payment_id):
        raise ValueError('Неверный идентификатор платежа')
    if order.get('provider_payment_id') and payment_id!=order['provider_payment_id']:
        raise ValueError('У заказа уже другой платёж')
    return payment_id


def settle(connection,order_id,values,settings,*,source='result',ack=False):
    """Caller verified the signature; subscription and order serialize together."""
    initial=connection.execute('SELECT tenant_id FROM subscription_payments WHERE id=%s',(order_id,)).fetchone()
    if not initial: raise HTTPException(404,'Заказ не найден')
    with connection.transaction():
        subscription=connection.execute('''SELECT s.*,t.status AS tenant_status,t.name AS tenant_name,t.contact_email
          FROM tenant_subscriptions s JOIN tenants t ON t.id=s.tenant_id WHERE s.tenant_id=%s FOR UPDATE OF s''',(initial['tenant_id'],)).fetchone()
        order=connection.execute('SELECT * FROM subscription_payments WHERE id=%s FOR UPDATE',(order_id,)).fetchone()
        payment_id=validate_payment(order,values,settings,bound_status=source=='status')
        refunded=abs(money(values.get('pg_refund_amount','0')))
        if refunded>order['amount']: raise ValueError('Возврат превышает сумму заказа')
        status=order['status'];reason=order['review_reason'];start=end=None
        applied=False
        if refunded>order['refund_amount']:
            status='review';reason='Провайдер подтвердил возврат. Проверьте запрос и скорректируйте оплаченный доступ.'
            if order['applied_at'] and not order['testing']:
                connection.execute('''INSERT INTO subscription_refund_requests (id,order_id,reason) VALUES (%s,%s,%s)
                  ON CONFLICT (order_id) DO UPDATE SET status='new',resolved_at=NULL,resolved_by=NULL''',
                  (uuid4(),order_id,'Возврат подтверждён провайдером; требуется согласовать срок доступа.'))
        elif order['refund_amount']>0:
            refunded=order['refund_amount']
        elif order['applied_at']:
            pass
        elif values.get('pg_result')=='0' or values.get('pg_payment_status') in {'failed','error','canceled'}:
            status='failed'
        elif (values.get('pg_result')=='1' or values.get('pg_payment_status')=='success') and values.get('pg_captured')=='1':
            if subscription['tenant_status']!='active' or subscription['plan_code']!=order['plan_code'] or subscription['max_branches']!=order['max_branches']:
                status='review';reason='Оплата получена, но компания или тариф изменились. Требуется проверка владельца платформы.'
            else:
                status='paid';reason=''
                if not order['testing']:
                    candidates=[now()]
                    for key in ('trial_ends_at','current_period_ends_at'):
                        if subscription.get(key): candidates.append(subscription[key])
                    start=max(candidates);end=add_months(start,order['period_months'])
                    connection.execute("UPDATE tenant_subscriptions SET status='active',current_period_ends_at=%s,updated_at=now() WHERE tenant_id=%s",(end,order['tenant_id']))
                    applied=True
                    from .mailer import enqueue
                    enqueue(connection,dedup_key='subscription:'+order_id,tenant_id=order['tenant_id'],recipient=subscription['contact_email'],subject='Oimo — подписка оплачена',body=f'Оплата заказа {order_id}: {order["amount"]} KGS подтверждена.\nДоступ до {end.isoformat()}.\nАвтопродление не подключено.\n')
        elif status not in {'paid','review','refunded'}:
            status='pending'
        if status!=order['status'] or applied or refunded!=order['refund_amount'] or not order['provider_payment_id']:
            connection.execute('''UPDATE subscription_payments SET status=%s,provider_payment_id=%s,refund_amount=%s,review_reason=%s,
              applied_at=CASE WHEN %s THEN now() ELSE applied_at END,service_starts_at=COALESCE(service_starts_at,%s),service_ends_at=COALESCE(service_ends_at,%s),updated_at=now() WHERE id=%s''',
              (status,payment_id,refunded,reason,applied,start,end,order_id))
            event(connection,order_id,source,{'status':status,'paymentId':payment_id,'refundAmount':str(refunded),'accessApplied':applied})
        result_ack=bytes(order['result_ack']) if order.get('result_ack') else None
        if ack and not result_ack:
            result_ack=freedompay.response_xml('result','ok',settings.freedompay_secret_key.get_secret_value(),'Payment recorded')
            connection.execute('UPDATE subscription_payments SET result_ack=%s WHERE id=%s',(result_ack,order_id))
        saved=connection.execute('SELECT * FROM subscription_payments WHERE id=%s',(order_id,)).fetchone()
    return saved,result_ack


class CheckoutInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id: UUID
    terms_accepted: Literal[True]
    terms_version: str=Field(min_length=10,max_length=100)
    billing_period: Literal['monthly','annual']='monthly'
    price_version: datetime | None=None


class RefundInput(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    reason: str=Field(min_length=8,max_length=2000)


class RefundResolution(RefundInput):
    decision: Literal['approved','rejected']
    access_until: datetime | None=None


def install(app):
    from . import main

    def owner(user):
        if user['role']!='owner': raise HTTPException(403,'Подпиской управляет владелец компании')

    def subscription(connection,tenant_id,lock=False):
        row=connection.execute('SELECT * FROM tenant_subscriptions WHERE tenant_id=%s'+(' FOR UPDATE' if lock else ''),(tenant_id,)).fetchone()
        if not row: raise HTTPException(404,'Подписка не найдена')
        return row

    @app.get('/api/v1/billing',tags=['billing'])
    def overview(user=Depends(main.current_user),connection=Depends(main.get_connection)):
        owner(user);settings=get_settings();sub=subscription(connection,user['tenant_id'])
        plan=connection.execute('SELECT * FROM platform_plans WHERE code=%s',(sub['plan_code'],)).fetchone()
        orders=connection.execute('SELECT * FROM subscription_payments WHERE tenant_id=%s ORDER BY created_at DESC LIMIT 50',(user['tenant_id'],)).fetchall()
        refund_requests=connection.execute('''SELECT r.order_id,r.status,r.created_at FROM subscription_refund_requests r JOIN subscription_payments p ON p.id=r.order_id WHERE p.tenant_id=%s''',(user['tenant_id'],)).fetchall()
        unlimited=sub['status']=='active' and not sub['current_period_ends_at']
        return {'subscription':dict(sub),'plan':dict(plan) if plan else None,'orders':[public_order(row) for row in orders],
                'refundRequests':[dict(row) for row in refund_requests],'serverTime':now(),'termsVersion':legal.version(settings),'testing':settings.freedompay_test_mode,
                'emailVerified':bool(user.get('email_verified_at')),
                'canPay':not readiness(settings) and bool(user.get('email_verified_at')) and bool(plan and (plan['monthly_price']>0 or plan['annual_price']>0)) and not unlimited,
                'message':'Доступ включён администратором без даты окончания. Для изменения подписки свяжитесь с поддержкой.' if unlimited else 'Онлайн-оплата пока недоступна. Свяжитесь с поддержкой.' if readiness(settings) else 'Подтвердите email перед оплатой подписки.' if not user.get('email_verified_at') else '',
                'supportEmail':settings.seller_support_email}

    @app.post('/api/v1/billing/checkout',tags=['billing'])
    def checkout(payload:CheckoutInput,request:Request,user=Depends(main.current_user),connection=Depends(main.get_connection)):
        main._check_origin(request);owner(user);settings=get_settings()
        if readiness(settings): raise HTTPException(503,'Онлайн-оплата пока недоступна. Свяжитесь с поддержкой.')
        if not user.get('email_verified_at'): raise HTTPException(403,'Подтвердите email аккаунта перед оплатой подписки.')
        if payload.terms_version!=legal.version(settings): raise HTTPException(409,'Условия обновились. Обновите страницу и ознакомьтесь с ними перед оплатой.')
        months=12 if payload.billing_period=='annual' else 1
        with connection.transaction():
            sub=subscription(connection,user['tenant_id'],True)
            previous=connection.execute('SELECT * FROM subscription_payments WHERE tenant_id=%s AND request_id=%s',(user['tenant_id'],payload.request_id)).fetchone()
            if previous:
                if previous['period_months']!=months: raise HTTPException(409,'Этот запрос уже использован для другого срока подписки. Обновите страницу.')
                return public_order(previous)
            if sub['status']=='active' and not sub['current_period_ends_at']: raise HTTPException(409,'Доступ уже включён без ограничения срока. Обратитесь в поддержку.')
            active=connection.execute("SELECT * FROM subscription_payments WHERE tenant_id=%s AND status IN ('creating','pending','review') ORDER BY created_at DESC LIMIT 1",(user['tenant_id'],)).fetchone()
            if active:
                if active['period_months']!=months:
                    period='год' if active['period_months']==12 else 'месяц'
                    raise HTTPException(409,f'У вас есть незавершённый заказ на {period}. Проверьте его статус в истории оплат перед выбором другого срока.')
                return public_order(active)
            plan=connection.execute('SELECT * FROM platform_plans WHERE code=%s FOR SHARE',(sub['plan_code'],)).fetchone()
            price=plan['annual_price' if months==12 else 'monthly_price'] if plan else 0
            if price<=0: raise HTTPException(409,'Оплата за выбранный срок недоступна. Уточните тариф у владельца платформы')
            if payload.price_version is not None and payload.price_version!=plan['updated_at']:
                raise HTTPException(409,'Цена тарифа обновилась. Обновите страницу и проверьте сумму перед оплатой.')
            order_id='oimo-'+uuid4().hex
            connection.execute('''INSERT INTO subscription_payments
              (id,tenant_id,owner_user_id,request_id,plan_code,amount,currency,max_branches,merchant_id,testing,expires_at,terms_version,terms_snapshot,period_months)
              VALUES (%s,%s,%s,%s,%s,%s,'KGS',%s,%s,%s,now()+interval '30 minutes',%s,%s,%s)''',
              (order_id,user['tenant_id'],user['id'],payload.request_id,sub['plan_code'],price,sub['max_branches'],settings.freedompay_merchant_id,settings.freedompay_test_mode,legal.version(settings),Jsonb(legal.snapshot(settings,months)),months))
            event(connection,order_id,'created',{'actor':user['id'],'termsVersion':legal.version(settings),'periodMonths':months})
        # Persist the order BEFORE the external call. Unknown responses must be reconciled, never recharged.
        order=connection.execute('SELECT * FROM subscription_payments WHERE id=%s',(order_id,)).fetchone()
        contact=connection.execute('SELECT contact_email FROM tenants WHERE id=%s',(user['tenant_id'],)).fetchone()
        connection.commit()
        values={'pg_order_id':order_id,'pg_amount':format(order['amount'],'.2f'),'pg_currency':'KGS','pg_description':f'Oimo subscription {order["period_months"]} months',
                'pg_user_id':user['tenant_id'],'pg_user_contact_email':contact['contact_email'],'pg_testing_mode':'1' if order['testing'] else '0',
                'pg_lifetime':'1800','pg_postpone_payment':'0','pg_request_method':'POST','pg_language':'ru',
                'pg_result_url':base_url(settings)+'/api/v1/billing/freedompay/result','pg_check_url':base_url(settings)+'/api/v1/billing/freedompay/check',
                'pg_success_url':base_url(settings)+'/billing?order='+order_id,'pg_failure_url':base_url(settings)+'/billing?order='+order_id,
                'pg_success_url_method':'GET','pg_failure_url_method':'GET'}
        try:
            result=freedompay.request_api(settings,settings.freedompay_init_path,values)
            if result.get('pg_status')!='ok':
                with connection.transaction():
                    connection.execute("UPDATE subscription_payments SET status='failed',review_reason='Провайдер отклонил создание платежа',updated_at=now() WHERE id=%s AND status='creating'",(order_id,))
                    event(connection,order_id,'init_rejected')
            else:
                if not re.fullmatch('[1-9][0-9]{0,30}',result.get('pg_payment_id','')) or not freedompay.safe_checkout_url(result.get('pg_redirect_url')):
                    raise freedompay.ProviderError('Invalid checkout response')
                with connection.transaction():
                    locked=connection.execute('SELECT * FROM subscription_payments WHERE id=%s FOR UPDATE',(order_id,)).fetchone()
                    if locked['provider_payment_id'] and locked['provider_payment_id']!=result['pg_payment_id']:
                        raise freedompay.ProviderError('Payment binding mismatch')
                    connection.execute("UPDATE subscription_payments SET provider_payment_id=%s,checkout_url=%s,status=CASE WHEN status='creating' THEN 'pending' ELSE status END,updated_at=now() WHERE id=%s",(result['pg_payment_id'],result['pg_redirect_url'],order_id))
                    event(connection,order_id,'initialized')
        except (freedompay.ProviderError,UniqueViolation):
            with connection.transaction():
                connection.execute("UPDATE subscription_payments SET review_reason='Подтверждение создания не получено. Проверьте оплату; повторный платёж не создаётся.',updated_at=now() WHERE id=%s AND status='creating'",(order_id,))
                event(connection,order_id,'init_unknown')
        return public_order(connection.execute('SELECT * FROM subscription_payments WHERE id=%s',(order_id,)).fetchone())

    async def callback_values(request,script):
        settings=get_settings()
        if not settings.freedompay_secret_key.get_secret_value(): raise HTTPException(503,'Payment notifications are not configured')
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>65536: raise HTTPException(413,'Request too large')
        try: values=freedompay.form_values(bytes(data),request.headers.get('content-type',''))
        except (ValueError,UnicodeError): raise HTTPException(400,'Invalid payment form')
        if not freedompay.verify(script,values,settings.freedompay_secret_key.get_secret_value()): raise HTTPException(403,'Invalid payment signature')
        return values,settings

    @app.post('/api/v1/billing/freedompay/result',tags=['billing'])
    async def result(request:Request,connection=Depends(main.get_connection)):
        values,settings=await callback_values(request,'result')
        try: _,ack=settle(connection,values.get('pg_order_id',''),values,settings,ack=True)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
        except UniqueViolation as exc: raise HTTPException(409,'Payment already belongs to another order') from exc
        return Response(ack,media_type='application/xml')

    @app.post('/api/v1/billing/freedompay/check',tags=['billing'])
    async def check(request:Request,connection=Depends(main.get_connection)):
        values,settings=await callback_values(request,'check')
        order=connection.execute('SELECT * FROM subscription_payments WHERE id=%s',(values.get('pg_order_id',''),)).fetchone()
        accepted=False
        if order:
            try:
                # Check can omit testing mode; it never grants service or acknowledges a payment.
                validate_payment(order,{**values,'pg_testing_mode':values.get('pg_testing_mode','1' if order['testing'] else '0')},settings)
                tenant=connection.execute('SELECT status FROM tenants WHERE id=%s',(order['tenant_id'],)).fetchone()
                accepted=order['status'] in {'creating','pending'} and order['expires_at']>now() and tenant and tenant['status']=='active'
            except ValueError: pass
        return Response(freedompay.response_xml('check','ok' if accepted else 'rejected',settings.freedompay_secret_key.get_secret_value(),'Payment allowed' if accepted else 'Order unavailable'),media_type='application/xml')

    def refresh_order(order_id,user,connection):
        settings=get_settings()
        order=connection.execute('SELECT * FROM subscription_payments WHERE id=%s',(order_id,)).fetchone()
        if not order or (user['role']!='platform_owner' and order['tenant_id']!=user['tenant_id']): raise HTTPException(404,'Заказ не найден')
        if not settings.freedompay_secret_key.get_secret_value() or settings.freedompay_merchant_id!=order['merchant_id']: raise HTTPException(503,'Проверка оплаты пока недоступна')
        with connection.transaction():
            claimed=connection.execute("UPDATE subscription_payments SET checked_at=now() WHERE id=%s AND (checked_at IS NULL OR checked_at<now()-interval '10 seconds') RETURNING id",(order_id,)).fetchone()
            if not claimed: raise HTTPException(429,'Статус уже проверяется. Подождите 10 секунд.')
        connection.commit()
        try:
            values=freedompay.request_api(settings,'/get_status3.php',{'pg_order_id':order_id,**({'pg_payment_id':order['provider_payment_id']} if order['provider_payment_id'] else {})})
            if values.get('pg_status')!='ok' or values.get('pg_payment_id')=='0':
                return public_order(order)
            saved,_=settle(connection,order_id,values,settings,source='status')
            return public_order(saved)
        except (freedompay.ProviderError,ValueError,UniqueViolation) as exc:
            logger.warning('Subscription payment refresh failed: order=%s method=get_status3.php reason=%s',order_id,freedompay.diagnostic(exc))
            raise HTTPException(502,'Не удалось подтвердить статус оплаты. Повторно оплачивать этот заказ не нужно; попробуйте проверить статус позже или свяжитесь с поддержкой.') from exc

    @app.post('/api/v1/billing/orders/{order_id}/refresh',tags=['billing'])
    def refresh(order_id:str,request:Request,user=Depends(main.current_user),connection=Depends(main.get_connection)):
        main._check_origin(request);owner(user)
        return refresh_order(order_id,user,connection)

    @app.post('/api/v1/billing/orders/{order_id}/refund-request',tags=['billing'])
    def refund_request(order_id:str,payload:RefundInput,request:Request,user=Depends(main.current_user),connection=Depends(main.get_connection)):
        main._check_origin(request);owner(user)
        with connection.transaction():
            order=connection.execute('SELECT * FROM subscription_payments WHERE id=%s AND tenant_id=%s FOR UPDATE',(order_id,user['tenant_id'])).fetchone()
            if not order or not order['applied_at'] or order['testing']: raise HTTPException(404,'Оплаченный заказ не найден')
            row=connection.execute('SELECT * FROM subscription_refund_requests WHERE order_id=%s',(order_id,)).fetchone()
            if not row:
                identifier=uuid4()
                connection.execute('INSERT INTO subscription_refund_requests (id,order_id,reason) VALUES (%s,%s,%s)',(identifier,order_id,payload.reason))
                event(connection,order_id,'refund_requested',{'requestId':str(identifier),'actor':user['id']})
                from .mailer import enqueue
                enqueue(connection,dedup_key='refund-request:'+order_id,recipient=get_settings().seller_support_email,subject='Oimo — запрос возврата',body=f'Компания: {user["tenant_id"]}\nЗаказ: {order_id}\nКонтакт: {user["login"]}\nПричина: {payload.reason}\nПроверьте обращение в панели платформы.\n',tenant_id=user['tenant_id'])
        return {'ok':True}

    @app.get('/api/v1/platform/billing',tags=['platform'])
    def platform_overview(user=Depends(main.current_user),connection=Depends(main.get_connection)):
        main._platform_owner(user);settings=get_settings()
        orders=connection.execute('''SELECT p.*,t.name AS tenant_name FROM subscription_payments p JOIN tenants t ON t.id=p.tenant_id ORDER BY p.created_at DESC LIMIT 100''').fetchall()
        requests=connection.execute('''SELECT r.*,p.tenant_id,p.amount,p.currency,p.refund_amount,t.name AS tenant_name,s.current_period_ends_at,s.trial_ends_at FROM subscription_refund_requests r JOIN subscription_payments p ON p.id=r.order_id JOIN tenants t ON t.id=p.tenant_id JOIN tenant_subscriptions s ON s.tenant_id=p.tenant_id ORDER BY r.created_at DESC LIMIT 100''').fetchall()
        return {'ready':not readiness(settings),'missing':readiness(settings),'testing':settings.freedompay_test_mode,'orders':[{**public_order(row),'tenantName':row['tenant_name'],'tenantId':row['tenant_id']} for row in orders],'refundRequests':[dict(row) for row in requests]}

    @app.post('/api/v1/platform/billing/orders/{order_id}/refresh',tags=['platform'])
    def platform_refresh(order_id:str,request:Request,user=Depends(main.current_user),connection=Depends(main.get_connection)):
        main._check_origin(request);main._platform_owner(user)
        return refresh_order(order_id,user,connection)

    @app.post('/api/v1/platform/billing/refunds/{refund_id}/resolve',tags=['platform'])
    def resolve_refund(refund_id:UUID,payload:RefundResolution,request:Request,user=Depends(main.current_user),connection=Depends(main.get_connection)):
        main._check_origin(request);main._platform_owner(user)
        initial=connection.execute('SELECT p.tenant_id FROM subscription_refund_requests r JOIN subscription_payments p ON p.id=r.order_id WHERE r.id=%s',(refund_id,)).fetchone()
        if not initial: raise HTTPException(404,'Запрос не найден')
        with connection.transaction():
            sub=subscription(connection,initial['tenant_id'],True)
            refund=connection.execute('SELECT * FROM subscription_refund_requests WHERE id=%s FOR UPDATE',(refund_id,)).fetchone()
            order=connection.execute('SELECT * FROM subscription_payments WHERE id=%s FOR UPDATE',(refund['order_id'],)).fetchone()
            if refund['status']!='new': return {'ok':True}
            if payload.decision=='approved':
                if order['refund_amount']<=0: raise HTTPException(409,'Сначала выполните возврат в Freedom Pay и проверьте статус заказа. Система должна получить подтверждённую сумму возврата.')
                if not payload.access_until or payload.access_until.tzinfo is None: raise HTTPException(422,'Укажите согласованную дату окончания доступа с часовым поясом')
                end=max(payload.access_until,sub['trial_ends_at']) if sub['trial_ends_at'] else payload.access_until
                if sub['current_period_ends_at'] and end>sub['current_period_ends_at']: raise HTTPException(422,'Согласованный срок не может превышать текущий оплаченный период')
                connection.execute("UPDATE tenant_subscriptions SET current_period_ends_at=%s,status=%s,updated_at=now() WHERE tenant_id=%s",(end,'active' if end>now() else 'past_due',initial['tenant_id']))
                connection.execute('UPDATE subscription_payments SET status=%s,review_reason=%s,updated_at=now() WHERE id=%s',('refunded' if order['refund_amount']>=order['amount'] else 'paid',payload.reason,order['id']))
            connection.execute('UPDATE subscription_refund_requests SET status=%s,resolution=%s,resolved_at=now(),resolved_by=%s WHERE id=%s',(payload.decision,payload.reason,user['id'],refund_id))
            event(connection,order['id'],'refund_resolved',{'decision':payload.decision,'reason':payload.reason,'actor':user['id'],'accessUntil':payload.access_until.isoformat() if payload.access_until else None})
        return {'ok':True}

    legal.install(app)
