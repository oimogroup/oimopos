from types import SimpleNamespace
from http.cookies import SimpleCookie
import pytest
from fastapi import Request, Response, HTTPException
from app import main
from app.schemas import LoginInput

REQUEST=Request({'type':'http','headers':[(b'origin',b'http://127.0.0.1:8000'),(b'x-ashkana-client',b'pos')]})

class Connection:
    def __init__(self, employee, terminal): self.employee=employee; self.terminal=terminal; self.calls=[]
    def execute(self, sql, params):
        self.calls.append((sql,params))
        value=None
        if 'WHERE lower(u.login)' in sql: value=self.employee
        elif 'SELECT u.id' in sql: value=self.terminal
        elif 'INSERT INTO auth_sessions' in sql: value={'id':77}
        return SimpleNamespace(fetchone=lambda:value,fetchall=lambda:[self.terminal])

@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(main,'verify_password',lambda password,hashed:password=='test-password')
    monkeypatch.setattr(main,'_validate_tenant_access',lambda user, **kw:None)
    monkeypatch.setattr(main,'_workspace_row',lambda conn,tenant:{'payload':{}})
    monkeypatch.setattr(main,'_user_session',lambda user,state:{'staffRole':user['staff_role'],'route':'index.html'})
    common={'role':'branch','tenant_id':'t1','branch_id':'b1','is_active':True,'password_hash':'hash','account_version':1,'access_permissions':{}}
    return ({**common,'id':42,'login':'person','display_name':'Person','staff_role':'branch_manager'}, {**common,'id':9,'login':'register','display_name':'Касса','staff_role':'pos_terminal'})

@pytest.mark.parametrize('role',['branch_manager','cashier','waiter','hall_admin','production'])
def test_personal_password_binds_the_authenticated_employee_without_pin(setup,role):
    employee,terminal=setup;employee['staff_role']=role
    if role == 'production': employee['access_permissions']={'posAccess':True,'production':True}
    connection=Connection(employee,terminal);response=Response()
    result=main.login(LoginInput(login='person',password='test-password'),response,REQUEST,connection)
    assert result['session']['staffRole']=='pos_terminal'
    binding=next(params for sql,params in connection.calls if 'INSERT INTO pos_operator_sessions' in sql)
    assert binding[1:4]==(77,42,'b1')
    headers=response.headers.getlist('set-cookie')
    cookie=SimpleCookie();[cookie.load(value) for value in headers]
    assert cookie[main.POS_OPERATOR_COOKIE].value and cookie[main.POS_OPERATOR_COOKIE]['httponly']
    query,params=next((sql,params) for sql,params in connection.calls if 'LIMIT 1' in sql)
    assert 'u.branch_id = %s' in query and params==('t1','b1')


def test_shared_terminal_login_does_not_guess_an_employee(setup):
    employee,terminal=setup;connection=Connection(None,terminal)
    main.login(LoginInput(login='company',password='test-password'),Response(),REQUEST,connection)
    assert not any('INSERT INTO pos_operator_sessions' in sql for sql,_ in connection.calls)


def test_wrong_password_cannot_bind_employee(setup):
    connection=Connection(*setup)
    with pytest.raises(HTTPException) as denied:
        main.login(LoginInput(login='person',password='incorrect'),Response(),REQUEST,connection)
    assert denied.value.status_code==401
    assert not any('INSERT INTO' in sql for sql,_ in connection.calls)
