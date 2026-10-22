import subprocess, secrets, os, time, urllib.request, json
from uuid import uuid4
suffix=secrets.token_hex(4); network='oimo-check-'+suffix; db=network+'-db'; web=network+'-web'
def run(args,**kwargs): return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,**kwargs)
password=secrets.token_hex(24)
env={**os.environ,'POSTGRES_PASSWORD':password,'DATABASE_URL':f'postgresql://postgres:{password}@{db}:5432/postgres','EMPLOYEE_PIN_KEY':secrets.token_hex(32),'PLATFORM_INITIAL_PASSWORD':secrets.token_hex(24),'SESSION_COOKIE_SECURE':'true','RENDER_EXTERNAL_URL':'https://oimo-check.example'}
try:
 run(['docker','network','create',network])
 run(['docker','run','-d','--name',db,'--network',network,'-e','POSTGRES_PASSWORD','postgres:17-alpine'],env=env)
 for _ in range(40):
  if subprocess.run(['docker','exec',db,'pg_isready','-U','postgres'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0: break
  time.sleep(1)
 for _ in range(2):
  run(['docker','run','--rm','--network',network,'-e','DATABASE_URL','oimo-render-check','python','/app/render_migrate.py'],env=env)
 print('PASS fresh database + repeat migrations')
 args=['docker','run','-d','--name',web,'--network',network,'-p','127.0.0.1:18080:10000']
 for key in ['DATABASE_URL','EMPLOYEE_PIN_KEY','PLATFORM_INITIAL_PASSWORD','SESSION_COOKIE_SECURE','RENDER_EXTERNAL_URL']: args+=['-e',key]
 run(args+['oimo-render-check'],env=env)
 for _ in range(40):
  try:
   with urllib.request.urlopen('http://127.0.0.1:18080/health') as r: assert json.load(r)['status']=='ok'
   break
  except Exception: time.sleep(1)
 else: raise RuntimeError('health failed')
 for path in ['/','/login','/admin','/pos','/platform','/billing','/legal/offer','/legal/privacy','/legal/refunds','/legal/payment','/legal/contacts','/login.html','/admin.html','/index.html','/platform.html','/oimo.css','/app.js']:
  with urllib.request.urlopen('http://127.0.0.1:18080'+path) as r: assert r.status==200
 for path in ['/.env','/database/init/002_seed.sql','/tests/pos-ui-smoke.html','/app/main.py']:
  try: urllib.request.urlopen('http://127.0.0.1:18080'+path); raise AssertionError(path)
  except urllib.error.HTTPError as e: assert e.code==404
 payload=json.dumps({'login':'platform','password':env['PLATFORM_INITIAL_PASSWORD']}).encode()
 request=urllib.request.Request('http://127.0.0.1:18080/api/v1/auth/login',data=payload,headers={'Content-Type':'application/json','Origin':env['RENDER_EXTERNAL_URL']})
 with urllib.request.urlopen(request) as r:
  assert r.status==200
  assert 'Secure' in r.headers.get('Set-Cookie','')
  cookie=r.headers['Set-Cookie'].split(';')[0]
 headers={'Content-Type':'application/json','Origin':env['RENDER_EXTERNAL_URL'],'Cookie':cookie}
 def api(path, data=None, method=None):
  request=urllib.request.Request('http://127.0.0.1:18080/api/v1'+path, data=json.dumps(data).encode() if data is not None else None,headers=headers,method=method)
  with urllib.request.urlopen(request) as response:return json.load(response)
 initial=api('/platform/tenants')
 created=[]
 owner_passwords=[]
 for index in range(2):
  owner_passwords.append(secrets.token_hex(16))
  tenant=api('/platform/tenants',{'name':'Demo '+str(index),'slug':'demo-'+str(index),'owner_name':'Demo Owner','email':f'demo{index}@example.com','phone':'+996555123456','owner_password':owner_passwords[-1],'service_modes':['counter'],'location_name':'Demo','location_address':'Demo street','register_password':secrets.token_hex(16)})
  created.append(tenant['id'])
 listed=api('/platform/tenants')
 assert all(any(row['id']==identifier for row in listed) for identifier in created)
 assert len(listed)==len(initial)+2
 print('PASS fresh tenant list and two created accounts remain visible')
 owner_request=urllib.request.Request('http://127.0.0.1:18080/api/v1/auth/login',data=json.dumps({'login':'demo0@example.com','password':owner_passwords[0]}).encode(),headers={'Content-Type':'application/json','Origin':env['RENDER_EXTERNAL_URL']})
 with urllib.request.urlopen(owner_request) as response: owner_cookie=response.headers['Set-Cookie'].split(';')[0]
 platform_cookie=headers['Cookie']
 headers['Cookie']=owner_cookie
 try:
  api('/platform/tenants/'+created[1], {'confirmation_name':'Demo 1'}, 'DELETE')
  raise AssertionError('company owner allowed to delete tenant')
 except urllib.error.HTTPError as error: assert error.code==403
 headers['Cookie']=platform_cookie
 try:
  api('/platform/tenants/'+created[0], {'confirmation_name':'wrong'}, 'DELETE')
  raise AssertionError('wrong confirmation accepted')
 except urllib.error.HTTPError as error: assert error.code==400
 assert len(api('/platform/tenants'))==len(listed)
 result=api('/platform/tenants/'+created[0], {'confirmation_name':'Demo 0'}, 'DELETE')
 assert result['deleted']
 remaining=api('/platform/tenants')
 assert created[0] not in [row['id'] for row in remaining]
 assert created[1] in [row['id'] for row in remaining]
 assert len(remaining)==len(listed)-1
 counts=run(['docker','exec',db,'psql','-U','postgres','-Atc',
  "SELECT count(*) FROM auth_users WHERE tenant_id = '"+created[0]+"'"]).stdout.strip()
 assert counts=='0'
 assert any(event['action']=='tenant.delete' for event in api('/platform/events'))
 headers['Cookie']=owner_cookie
 try:
  api('/auth/me')
  raise AssertionError('deleted session still valid')
 except urllib.error.HTTPError as error: assert error.code==401
 headers['Cookie']=platform_cookie
 print('PASS deletion confirmation, complete account removal, second tenant isolation and audit')
 print('PASS startup, health, frontend, private files not served, login and Secure cookie')
 public_plans=api('/public/plans')
 assert {row['code']:(float(row['monthly_price']),float(row['annual_price'])) for row in public_plans}=={'canteen':(3500,42000),'restaurant':(4000,48000)}
 updated=api('/platform/plans/canteen',{'monthly_price':'3501.50','annual_price':'42001.50'},'PUT')
 assert float(updated['monthly_price'])==3501.50 and float(updated['annual_price'])==42001.50
 assert any(event['action']=='plan.update' for event in api('/platform/events'))
 api('/platform/plans/canteen',{'monthly_price':'3500','annual_price':'42000'},'PUT')
 print('PASS monthly and annual public prices, platform price editing and audit')
 # Public registrations must create isolated trials and authenticated owner sessions.
 public_headers={'Content-Type':'application/json','Origin':env['RENDER_EXTERNAL_URL']}
 def signup(data, expected=201):
  req=urllib.request.Request('http://127.0.0.1:18080/api/v1/public/register',data=json.dumps(data).encode(),headers=public_headers)
  try:
   with urllib.request.urlopen(req) as response:
    assert response.status==expected
    assert 'HttpOnly' in response.headers['Set-Cookie'] and 'Secure' in response.headers['Set-Cookie']
    return json.load(response),response.headers['Set-Cookie'].split(';')[0]
  except urllib.error.HTTPError as error:
   assert error.code==expected,(error.code,error.read())
 trials=[]
 for index,plan in enumerate(['canteen','restaurant']):
  data={'request_id':str(uuid4()),'name':'Trial Owner','company':'Trial '+plan,'phone':'99655522233'+str(index),'email':f'trial{index}@example.com','password':secrets.token_hex(16),'plan':plan,'consent':True}
  result,trial_cookie=signup(data)
  assert result['redirect']=='/admin' and result['session']['role']=='owner'
  assert result['session']['subscriptionStatus']=='trialing' and result['session']['maxBranches']==1
  repeated,_=signup(data)
  assert repeated['session']['tenantId']==result['session']['tenantId']
  assert repeated['session']['trialEndsAt']==result['session']['trialEndsAt']
  signup({**data,'company':'Changed'},409)
  signup({**data,'request_id':str(uuid4())},429)
  signup({**data,'request_id':str(uuid4()),'trial_days':365},422)
  signup({**data,'request_id':str(uuid4()),'plan':'enterprise'},422)
  headers['Cookie']=trial_cookie
  workspace=api('/workspace')['state']
  assert not workspace['sales'] and not workspace['products'] and len(workspace['branches'])==1
  assert workspace['serviceMode']==plan
  registers=api('/pos/registers')
  terminal=registers[0]
  assert terminal['company_login']==result['session']['tenantSlug']
  assert terminal['account_login']!=terminal['company_login']
  terminal_password=secrets.token_hex(16)
  first_login='public-'+plan+'-main'
  changed=api('/pos/registers/'+str(terminal['id']),{'name':terminal['name'],'branch_id':terminal['branch_id'],'login':first_login,'password':terminal_password},'PUT')
  assert changed['account_login']==first_login
  def terminal_login(login_value,expected=200):
   req=urllib.request.Request('http://127.0.0.1:18080/api/v1/auth/login',data=json.dumps({'login':login_value,'password':terminal_password}).encode(),headers={**public_headers,'X-Ashkana-Client':'pos'})
   try:
    with urllib.request.urlopen(req) as r:
     assert r.status==expected
     return r.headers['Set-Cookie'].split(';')[0]
   except urllib.error.HTTPError as error: assert error.code==expected
  terminal_cookie=terminal_login(first_login)
  second_login=first_login+'-renamed'
  changed=api('/pos/registers/'+str(terminal['id']),{'name':terminal['name'],'branch_id':terminal['branch_id'],'login':second_login},'PUT')
  assert changed['account_login']==second_login
  req=urllib.request.Request('http://127.0.0.1:18080/api/v1/auth/me',headers={'Cookie':terminal_cookie,'X-Ashkana-Client':'pos'})
  with urllib.request.urlopen(req) as r: assert json.load(r)['session']['registerId']==terminal['id']
  terminal_login(first_login,401)
  terminal_login(second_login)
  terminal_login(terminal['company_login'])
  assert api('/workspace')['state']==workspace
  other_email='demo1@example.com'
  try:
   api('/pos/registers/'+str(terminal['id']),{'name':terminal['name'],'branch_id':terminal['branch_id'],'login':other_email},'PUT')
   raise AssertionError('existing owner login accepted as terminal login')
  except urllib.error.HTTPError as error: assert error.code==409
  assert api('/pos/registers')[0]['account_login']==second_login
  trials.append((data,result,trial_cookie))
 headers['Cookie']=platform_cookie
 listed=api('/platform/tenants')
 for data,result,_ in trials:
  trial=next(t for t in listed if t['id']==result['session']['tenantId'])
  assert trial['subscription_status']=='trialing' and trial['max_branches']==1
  assert trial['branch_count']==1
 print('PASS both public trial formats, automatic secure login, empty isolated workspace, retry without duplicate or trial extension, fixed server limits')
 print('PASS terminal login rename, new login works, previous login rejected, company-code fallback and live terminal sessions preserved; workspace unchanged and duplicate login rejected')
 counts=run(['docker','exec',db,'psql','-U','postgres','-Atc',"SELECT count(*) FROM email_outbox WHERE status='pending' AND attempts=0"]).stdout.strip()
 assert counts=='2',counts
 assert api('/platform/mail')['configured'] is False
 assert api('/platform/mail')['counts']['pending']==2
 try:
  api('/platform/mail/test',{})
  raise AssertionError('SMTP test accepted without a configured password')
 except urllib.error.HTTPError as error: assert error.code==409
 probe='''from app.database import pool
from app import mailer
from pydantic import SecretStr
pool.open(wait=True)
cfg=mailer.get_settings().model_copy(update={'smtp_password':SecretStr('test-only-not-a-real-password')})
sent=[]
mailer.send_message=lambda row,settings: sent.append(row['dedup_key'])
assert mailer.deliver_one(pool,cfg)
assert mailer.deliver_one(pool,cfg)
assert not mailer.deliver_one(pool,cfg)
assert len(sent)==2 and len(set(sent))==2
with pool.connection() as c:
 assert c.execute("SELECT count(*) AS total FROM email_outbox WHERE status='sent' AND attempts=1").fetchone()['total']==2
pool.close()
'''
 run(['docker','exec',web,'python','-c',probe])
 assert api('/platform/mail')['counts']['sent']==2
 print('PASS welcome emails queued atomically without retry duplicates; disabled SMTP keeps queue; real database claims and completion with mocked transport (no external mail)')
 # Expiry blocks existing sessions as well as replayed signup requests.
 run(['docker','exec',db,'psql','-U','postgres','-c',"UPDATE tenant_subscriptions SET trial_ends_at = now() - interval '1 day' WHERE tenant_id IN (SELECT tenant_id FROM trial_registrations)"])
 for data,result,trial_cookie in trials:
  headers['Cookie']=trial_cookie
  try:
   api('/workspace')
   raise AssertionError('expired trial still has access')
  except urllib.error.HTTPError as error: assert error.code==403
  assert api('/auth/me')['session']['billingRequired']
  assert api('/billing')['canPay'] is False
  replay,_=signup(data)
  assert replay['session']['route']=='/billing'
 headers['Cookie']=platform_cookie
 print('PASS trial expiry enforced for existing sessions and registration retries')
except subprocess.CalledProcessError as e:
 print(e.stderr.replace(password,'[redacted]')); raise SystemExit(1)
finally:
 for name in [web,db]: subprocess.run(['docker','rm','-f','-v',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 subprocess.run(['docker','network','rm',network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
