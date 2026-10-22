"""Create and destroy an isolated PostgreSQL 17 for billing integration tests.

Uses the locally built API Compose image and oimo-render-check (migrations).
No live provider calls, real credentials, emails or changes to the user's DB.
"""
import os
from pathlib import Path
import secrets
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
suffix=secrets.token_hex(5);network='oimo-billing-'+suffix;database=network+'-db'
password=secrets.token_hex(24)
environment={**os.environ,'POSTGRES_PASSWORD':password,'DATABASE_URL':f'postgresql://postgres:{password}@{database}:5432/postgres'}
def run(args,**options):
    return subprocess.run(args,check=True,**options)
try:
    run(['docker','network','create',network],stdout=subprocess.DEVNULL)
    run(['docker','run','-d','--name',database,'--network',network,'-e','POSTGRES_PASSWORD','postgres:17-alpine'],env=environment,stdout=subprocess.DEVNULL)
    for _ in range(40):
        if subprocess.run(['docker','exec',database,'pg_isready','-U','postgres'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
        time.sleep(1)
    for _ in range(2): run(['docker','run','--rm','--network',network,'-e','DATABASE_URL','oimo-render-check','python','/app/render_migrate.py'],env=environment,stdout=subprocess.DEVNULL)
    print('PASS fresh and repeated billing migrations',flush=True)
    image=subprocess.check_output(['docker','compose','images','-q','api'],cwd=ROOT,text=True).strip()
    environment['BILLING_TEST_DATABASE_URL']=environment['DATABASE_URL'];environment['DATABASE_URL']=''
    run(['docker','run','--rm','--network',network,'-e','DATABASE_URL','-e','BILLING_TEST_DATABASE_URL','-v',str(ROOT/'backend')+':/app:ro',image,'python','-m','pytest','tests/test_billing_integration.py','-q','-p','no:cacheprovider'],env=environment)
finally:
    subprocess.run(['docker','rm','-f','-v',database],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['docker','network','rm',network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
