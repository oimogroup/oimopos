"""Back up local Compose PostgreSQL and verify it in a disposable PostgreSQL.

Never restores over the source database. Dumps contain private data and stay in
ignored backups/. The employee PIN key must be retained separately.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
TABLES={'tenants':'id','auth_users':'id','operational_state':'tenant_id','tenant_subscriptions':'tenant_id',
        'subscription_payments':'id','auth_action_tokens':'token_hash'}


def run(args,**options):
    return subprocess.run(args,check=True,stderr=subprocess.PIPE,**options)


def fingerprint(container,user,database):
    output={}
    for table,key in TABLES.items():
        # Deterministic hashes compare data without exposing names, passwords,
        # account numbers, token hashes or the workspace itself in the report.
        sql=f"SELECT count(*) || ':' || md5(coalesce(string_agg(md5(to_jsonb(r)::text),'' ORDER BY {key}),'')) FROM {table} r"
        result=run(['docker','exec','-e','PGTZ=UTC','-e','PGOPTIONS=-c timezone=UTC',container,'psql','-X','-At','-v','ON_ERROR_STOP=1','-U',user,'-d',database,'-c',sql],stdout=subprocess.PIPE,text=True).stdout.strip()
        count,digest=result.split(':');output[table]={'rows':int(count),'digest':digest}
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'backups')
    args=parser.parse_args()
    os.umask(0o077)
    args.output.mkdir(parents=True,exist_ok=True)
    container=run(['docker','compose','ps','-q','db'],cwd=ROOT,stdout=subprocess.PIPE,text=True).stdout.strip()
    if not container: raise RuntimeError('Local Compose database is not running')
    user=run(['docker','exec',container,'printenv','POSTGRES_USER'],stdout=subprocess.PIPE,text=True).stdout.strip()
    database=run(['docker','exec',container,'printenv','POSTGRES_DB'],stdout=subprocess.PIPE,text=True).stdout.strip()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target=args.output/('oimo-'+stamp+'.dump')
    before=fingerprint(container,user,database)
    with tempfile.NamedTemporaryFile(dir=args.output,prefix='.backup-',delete=False) as temp:
        temporary=Path(temp.name)
        try:
            run(['docker','exec',container,'pg_dump','-U',user,'-d',database,'--format=custom','--no-owner','--no-acl'],stdout=temp)
            temp.flush();os.fsync(temp.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    after=fingerprint(container,user,database)
    name='oimo-restore-'+secrets.token_hex(5)
    password=secrets.token_hex(24)
    environment={**os.environ,'POSTGRES_PASSWORD':password}
    try:
        run(['docker','run','-d','--name',name,'--network','none','-e','POSTGRES_PASSWORD','postgres:17-alpine'],env=environment,stdout=subprocess.DEVNULL)
        for _ in range(40):
            command=subprocess.run(['docker','exec',name,'cat','/proc/1/comm'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            # The entrypoint also starts a temporary server while initializing.
            # Wait for PID 1 to become the final PostgreSQL process first.
            if command.stdout.strip()==b'postgres' and subprocess.run(['docker','exec',name,'pg_isready','-U','postgres'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
            time.sleep(1)
        else: raise RuntimeError('Disposable PostgreSQL did not finish initialization')
        with target.open('rb') as stream:
            run(['docker','exec','-i',name,'pg_restore','-U','postgres','-d','postgres','--no-owner','--no-acl','--exit-on-error'],stdin=stream,stdout=subprocess.DEVNULL)
        restored=fingerprint(name,'postgres','postgres')
        matched=before==after==restored
        report={'checkedAt':datetime.now(timezone.utc).isoformat(),'scope':'local-compose','restoreTarget':'disposable PostgreSQL 17',
                'sourceUnchanged':before==after,'restoredDataMatches':matched,
                'dumpSha256':hashlib.file_digest(target.open('rb'),'sha256').hexdigest() if hasattr(hashlib,'file_digest') else hashlib.sha256(target.read_bytes()).hexdigest(),
                'tables':restored,'employeePinKey':'retain separately; not included in dump'}
        target.with_suffix('.verification.json').write_text(json.dumps(report,indent=2)+'\n')
        if not matched: raise RuntimeError('Backup restored, but the source changed during the check or data differs; see verification report')
        print(json.dumps({'backup':str(target),'verified':True,'scope':'local-compose','tablesChecked':len(TABLES)}))
    finally:
        subprocess.run(['docker','rm','-f','-v',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__': main()
