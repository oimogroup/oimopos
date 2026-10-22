"""Concurrent real API/SQL sales, isolated tenants only; no working data touched."""
from concurrent.futures import ThreadPoolExecutor
import json
from statistics import median
from time import perf_counter
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
import pytest

from app import main
from app.schemas import TenantCreate
from app.workspace import default_state
from test_billing_integration import system, DSN

pytestmark=pytest.mark.skipif(not DSN,reason='isolated billing database required')


def test_four_registers_parallel_sales_retries_and_tenant_isolation(system):
    suffix=uuid4().hex[:12]
    with system.connect() as connection:
        second=main._provision_tenant(TenantCreate(name='Load test',slug='load-'+suffix,owner_name='Load Owner',email=suffix+'@example.com',
          phone='996555123457',owner_password='Load-owner-password-123',register_password='Load-register-password-123',
          plan_code='canteen',max_branches=1,trial_days=14,service_modes=['counter'],location_name='Test',location_address='Test'),{'id':None,'login':'load-test'},connection)
    owner2=TestClient(main.app,base_url='https://oimo.example',headers={'Origin':'https://oimo.example'})
    assert owner2.post('/api/v1/auth/login',json={'login':suffix+'@example.com','password':'Load-owner-password-123'}).status_code==200
    tenants=[(system.tenant,system.client,'Test-terminal-'+system.user['login'].split('@')[0]),(second['id'],owner2,'Load-register-password-123')]
    devices=[]
    try:
        for tenant,owner,register_password in tenants:
            with system.connect() as connection:
                state=default_state();state['sales']=[];state['logisticsState']['stockLedger']=[]
                state['logisticsState']['branchStocks']['b1']['p-1']=40
                connection.execute('UPDATE operational_state SET payload=%s WHERE tenant_id=%s',(Jsonb(state),tenant))
            employee=owner.post('/api/v1/employees',json={'display_name':'Load Cashier','branch_id':'b1','staff_role':'cashier','pin':'1234'})
            assert employee.status_code==201,employee.text
            first=owner.get('/api/v1/pos/registers').json()[0]
            added=owner.post('/api/v1/pos/registers',json={'name':'Second register','branch_id':'b1','password':'Second-register-'+tenant[-8:]})
            assert added.status_code==201,added.text
            for register,password in [(first,register_password),(added.json(),'Second-register-'+tenant[-8:])]:
                device=TestClient(main.app,base_url='https://oimo.example',headers={'Origin':'https://oimo.example','X-Ashkana-Client':'pos'})
                login=register.get('account_login') or register.get('login')
                result=device.post('/api/v1/auth/login',json={'login':login,'password':password})
                assert result.status_code==200,result.text
                assert device.post('/api/v1/pos/unlock',json={'pin':'1234'}).status_code==200
                opened=device.post('/api/v1/pos/shifts/open',json={'opening_cash':0})
                assert opened.status_code==200,opened.text
                devices.append(device)
        jobs=[]
        for tenant_index in range(2):
            for index in range(30):
                command={'action':'sale.create','payload':{'requestId':str(uuid4()),'items':[{'id':'p-1','quantity':1}],'payments':[{'method':'cash','amount':40}],'received':40,'orderType':'dine-in'}}
                job=(devices[tenant_index*2+index%2],command)
                jobs.extend([job,job])
        def sell(job):
            device,command=job;started=perf_counter()
            response=device.post('/api/v1/workspace/actions',json=command)
            assert response.status_code==200,response.text
            return response.json()['entity']['id'],perf_counter()-started
        started=perf_counter()
        with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(sell,jobs))
        elapsed=perf_counter()-started
        assert len({identifier for identifier,_ in results})==60
        for tenant,_,_ in tenants:
            with system.connect() as connection:
                saved=connection.execute('SELECT payload FROM operational_state WHERE tenant_id=%s',(tenant,)).fetchone()['payload']
            assert len(saved['sales'])==30
            assert saved['logisticsState']['branchStocks']['b1']['p-1']==10
            assert sum(sale['total'] for sale in saved['sales'])==1200
        oversell=devices[0].post('/api/v1/workspace/actions',json={'action':'sale.create','payload':{'requestId':str(uuid4()),'items':[{'id':'p-1','quantity':11}],'payments':[{'method':'cash','amount':440}],'received':440}})
        assert oversell.status_code==409
        times=sorted(latency for _,latency in results)
        print('\nLOCAL RELIABILITY '+json.dumps({'tenants':2,'registers':4,'workers':8,'requests':120,'uniqueSales':60,
          'elapsedSeconds':round(elapsed,2),'medianSeconds':round(median(times),3),'p95Seconds':round(times[int(len(times)*.95)-1],3),'duplicateSales':0}))
    finally:
        for device in devices: device.close()
        owner2.close()
