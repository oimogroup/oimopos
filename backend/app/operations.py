"""Operator-only readiness: configuration is distinct from a verified live test."""
from fastapi import Depends

from . import billing, legal, mailer
from .config import get_settings


def install(app):
    from . import main

    @app.get('/api/v1/platform/operations',tags=['platform'])
    def status(user=Depends(main.current_user),connection=Depends(main.get_connection)):
        main._platform_owner(user)
        cfg=get_settings()
        migration=connection.execute('SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1').fetchone()
        queues=connection.execute('SELECT status,count(*) AS n FROM email_outbox GROUP BY status').fetchall()
        stale=connection.execute("SELECT count(*) AS n FROM subscription_payments WHERE status IN ('creating','pending','review') AND created_at<now()-interval '1 hour'").fetchone()
        return {'database':True,'migration':migration['version'],'email':{'configured':mailer.configured(cfg),'sender':mailer.sender(cfg),'counts':{row['status']:row['n'] for row in queues},'deliveryVerified':None},
                'seller':{'complete':not legal.missing(cfg),'missing':legal.missing(cfg)},
                'payments':{'configured':not billing.readiness(cfg),'testing':cfg.freedompay_test_mode,'needsReview':stale['n'],'missing':billing.readiness(cfg)},
                'account':{'recovery':True,'verification':True,'loginRateLimit':True},
                'physicalEquipmentVerified':None,'productionRestoreVerified':None,'productionLoadVerified':None}
