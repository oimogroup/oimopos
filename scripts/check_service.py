"""Read-only HTTPS health check for an external scheduler; exit 1 on outage.

Set OIMO_HEALTH_URL to the deployed /health endpoint. Optional SMTP settings
and OIMO_ALERT_RECIPIENT send an outage notification when explicitly configured.
No automatic scheduler or paid service is created by this script.
"""
import json
import os
from pathlib import Path
import ssl
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def probe(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('OIMO_HEALTH_URL must be an HTTPS URL without credentials')
    request=urllib.request.Request(url,headers={'Cache-Control':'no-cache','User-Agent':'Oimo-health-check/1'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs): return None
    opener=urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()),NoRedirect())
    with opener.open(request,timeout=10) as response:
        data=json.loads(response.read(8193))
        if response.status!=200 or data.get('status')!='ok': raise ValueError('Unhealthy service')
    return {'status':'ok','migration':data.get('migration')}


def main():
    try:
        result=probe(os.environ.get('OIMO_HEALTH_URL','https://oimopos.com/health'))
    except Exception as error:
        # Do not echo a URL containing credentials, response content or raw errors.
        result={'status':'failed','error':type(error).__name__}
        recipient=os.environ.get('OIMO_ALERT_RECIPIENT','')
        if recipient:
            sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
            from app.config import get_settings
            from app.mailer import send_message
            send_message({'dedup_key':'health-alert','recipient':recipient,'subject':'Oimo — сервер недоступен',
                          'body':'Внешняя проверка /health завершилась ошибкой. Проверьте сервис, базу и журнал Render.\n'},get_settings())
    print(json.dumps(result))
    return 0 if result['status']=='ok' else 1


if __name__=='__main__': sys.exit(main())
