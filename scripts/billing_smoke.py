"""Create and destroy an isolated PostgreSQL 17 for billing integration tests.

Uses the locally built API Compose image and oimo-render-check (migrations).
No live provider calls, real credentials, emails or changes to the user's DB.
"""
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
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
    # Upgrade a real pre-annual database with an existing one-month quote.
    with tempfile.TemporaryDirectory(prefix='oimo-pre-annual-') as temporary:
        legacy=Path(temporary)/'database';shutil.copytree(ROOT/'database',legacy)
        apply=legacy/'migrations/apply.sql'
        prefix,marker,_=apply.read_text().partition("SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '021_annual_subscriptions')")
        assert marker
        apply.write_text(prefix)
        run(['docker','run','--rm','--network',network,'-e','DATABASE_URL','-v',str(legacy)+':/app/database:ro','oimo-render-check','python','/app/render_migrate.py'],env=environment,stdout=subprocess.DEVNULL)
    legacy_sql="""INSERT INTO subscription_payments
      (id,tenant_id,request_id,plan_code,amount,max_branches,merchant_id,testing,expires_at,terms_version,terms_snapshot)
      VALUES ('pre-annual-quote','tenant-ashkana','11111111-1111-4111-8111-111111111111','canteen',2000,1,'123',true,now()+interval '1 hour','legacy','{"period":"calendar-month"}');"""
    legacy_sql += """
      INSERT INTO tenants (id,slug,name,contact_email) VALUES
        ('email-migrate-1','email-migrate-1','Test only','other@example.com'),
        ('email-migrate-2','email-migrate-2','Test only','custom@example.com'),
        ('email-migrate-3','email-migrate-3','Test only','shared@example.com'),
        ('email-migrate-4','email-migrate-4','Test only','shared@example.com'),
        ('email-migrate-5','email-migrate-5','Test only','primary@example.com');
      INSERT INTO auth_users (login,password_hash,role,staff_role,tenant_id,display_name) VALUES
        ('primary@example.com','unused-test-hash','owner','company_admin','email-migrate-1','Same Owner'),
        ('custom-alias','unused-test-hash','owner','company_admin','email-migrate-2','Same Owner'),
        ('shared-alias-1','unused-test-hash','owner','company_admin','email-migrate-3','Same Owner'),
        ('shared-alias-2','unused-test-hash','owner','company_admin','email-migrate-4','Same Owner'),
        ('reserved-alias','unused-test-hash','owner','company_admin','email-migrate-5','Same Owner');
    """
    run(['docker','exec','-i',database,'psql','-U','postgres','-v','ON_ERROR_STOP=1'],input=legacy_sql,text=True,stdout=subprocess.DEVNULL)
    for _ in range(2): run(['docker','run','--rm','--network',network,'-e','DATABASE_URL','oimo-render-check','python','/app/render_migrate.py'],env=environment,stdout=subprocess.DEVNULL)
    preserved=run(['docker','exec',database,'psql','-U','postgres','-Atc',"SELECT amount || ':' || period_months FROM subscription_payments WHERE id='pre-annual-quote'"],text=True,stdout=subprocess.PIPE).stdout.strip()
    assert preserved=='2000.00:1',preserved
    print('PASS upgrade and repeated migrations preserve the original monthly quote',flush=True)
    identities=run(['docker','exec',database,'psql','-U','postgres','-Atc',"SELECT login || ':' || COALESCE(email,'UNASSIGNED') FROM auth_users WHERE tenant_id LIKE 'email-migrate-%' ORDER BY tenant_id"],text=True,stdout=subprocess.PIPE).stdout.splitlines()
    assert identities==['primary@example.com:primary@example.com','custom-alias:custom@example.com','shared-alias-1:UNASSIGNED','shared-alias-2:UNASSIGNED','reserved-alias:UNASSIGNED'],identities
    print('PASS legacy email identities migrate; shared or reserved contact addresses stay unassigned',flush=True)
    image=subprocess.check_output(['docker','compose','images','-q','api'],cwd=ROOT,text=True).strip()
    environment['BILLING_TEST_DATABASE_URL']=environment['DATABASE_URL'];environment['DATABASE_URL']=''
    run(['docker','run','--rm','--network',network,'-e','DATABASE_URL','-e','BILLING_TEST_DATABASE_URL','-v',str(ROOT/'backend')+':/app:ro',image,'python','-m','pytest','tests/test_billing_integration.py','tests/test_account_access_integration.py','tests/test_service_reliability_integration.py','-q','-s','-p','no:cacheprovider'],env=environment)
finally:
    subprocess.run(['docker','rm','-f','-v',database],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['docker','network','rm',network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
