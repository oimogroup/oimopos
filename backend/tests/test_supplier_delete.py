from copy import deepcopy

import pytest

from app.workspace import apply_action, default_state, visible_state, WorkspaceError

OWNER={'id':1,'role':'owner','display_name':'Owner','login':'owner'}


def supplier(state):
    return state['suppliers'][0]


def delete(state, user=OWNER):
    return apply_action(state,user,'catalog.delete',{'kind':'supplier','id':supplier(state)['id']})


def test_supplier_is_hidden_from_new_operations_but_history_is_retained():
    state=default_state(); entry=supplier(state); identity=entry['id']
    state['logisticsState']['supplies']=[{'id':'old','supplierId':identity,'supplier':entry['name'],'total':100,'debt':0,'status':'posted'}]
    history=deepcopy(state['logisticsState']['supplies'])
    result=delete(state)
    assert entry['deletedAt'] and entry['status']=='inactive'
    assert state['logisticsState']['supplies']==history
    assert all(row['id']!=identity for row in visible_state(state,OWNER)['suppliers'])
    before=deepcopy(state)
    assert delete(state)==result and state==before
    with pytest.raises(WorkspaceError):
        apply_action(state,OWNER,'supplier.upsert',{'id':identity,'name':'Восстановить случайно'})
    apply_action(state,OWNER,'supplier.upsert',{'name':entry['name']})
    assert len([row for row in state['suppliers'] if row['name']==entry['name'] and not row.get('deletedAt')])==1


def test_supplier_with_debt_cannot_be_deleted():
    state=default_state();entry=supplier(state)
    state['logisticsState']['supplies']=[{'id':'unpaid','supplierId':entry['id'],'debt':50}]
    before=deepcopy(state)
    with pytest.raises(WorkspaceError,match='задолженность') as error:
        delete(state)
    assert error.value.status_code==409
    assert state['suppliers']==before['suppliers'] and state['logisticsState']==before['logisticsState']


@pytest.mark.parametrize('status',['submitted','approved','shipped'])
def test_supplier_with_open_order_cannot_be_deleted(status):
    state=default_state();entry=supplier(state)
    state['logisticsState']['directOrders']=[{'id':'open','supplierId':entry['id'],'status':status}]
    with pytest.raises(WorkspaceError,match='открытые заказы'):
        delete(state)
    assert not entry.get('deletedAt')


def test_branch_cannot_delete_account_wide_supplier_even_with_catalog_write():
    state=default_state()
    with pytest.raises(WorkspaceError) as error:
        delete(state,{'id':2,'role':'branch','branch_id':'b1','display_name':'Manager','_company_write':True})
    assert error.value.status_code==403
