"""Bounded reconciliation of unfinished subscription orders; never creates charges."""
import logging
import threading

from . import billing, freedompay
from .config import get_settings

log=logging.getLogger(__name__)


def reconcile_one(pool,settings):
    if not settings.freedompay_enabled or not settings.freedompay_merchant_id or not settings.freedompay_secret_key.get_secret_value():
        return False
    with pool.connection() as connection:
        with connection.transaction():
            order=connection.execute("""SELECT * FROM subscription_payments
              WHERE merchant_id=%s AND status IN ('creating','pending','review')
                AND (checked_at IS NULL OR checked_at<now()-interval '5 minutes')
              ORDER BY COALESCE(checked_at,created_at),created_at LIMIT 1 FOR UPDATE SKIP LOCKED""",(settings.freedompay_merchant_id,)).fetchone()
            if not order: return False
            connection.execute('UPDATE subscription_payments SET checked_at=now() WHERE id=%s',(order['id'],))
        try:
            values=freedompay.request_api(settings,'/get_status3.php',{'pg_order_id':order['id'],**({'pg_payment_id':order['provider_payment_id']} if order['provider_payment_id'] else {})})
            if values.get('pg_status')=='ok' and values.get('pg_payment_id')!='0':
                with connection.transaction(): billing.settle(connection,order['id'],values,settings,source='status')
        except (freedompay.ProviderError,ValueError):
            # An unknown status never turns into a failed order or a new charge.
            log.warning('Subscription reconciliation pending')
    return True


def start_worker(pool):
    stop=threading.Event()
    def run():
        while not stop.is_set():
            delay=60
            try:
                if reconcile_one(pool,get_settings()): delay=5
            except Exception as exc:
                log.warning('Subscription reconciliation temporarily unavailable (%s)',type(exc).__name__)
            stop.wait(delay)
    worker=threading.Thread(target=run,name='subscription-reconciliation',daemon=True)
    worker.start()
    return stop,worker
