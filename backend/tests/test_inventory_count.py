from copy import deepcopy
from datetime import datetime, timezone, timedelta
import pytest
from app.workspace import default_state, apply_action, WorkspaceError, _set_stock
from app.inventory_count import build, adjust, current
OWNER={'id':1,'role':'owner','display_name':'Owner'}
USER={'id':2,'role':'branch','branch_id':'b1','display_name':'Cashier'}

def test_selected_inventory_only_changes_selected_product():
 s=default_state();_,iid=apply_action(s,USER,'inventory.start',{'scope':'selected','itemIds':['p-1']})
 i=next(i for i in s['logisticsState']['inventories'] if i['id']==iid)
 assert len(i['items'])==1
 apply_action(s,USER,'inventory.submit',{'id':iid,'items':[{'itemId':'p-1','actual':3}]})
 apply_action(s,OWNER,'inventory.post',{'id':iid})
 assert s['logisticsState']['branchStocks']['b1']['p-1']==3

def test_historical_count_preserves_later_movements():
 s=default_state();_set_stock(s,'b1','p-1',15)
 now=datetime.now(timezone.utc)
 s['logisticsState']['stockLedger']=[{'branchId':'b1','itemId':'p-1','quantity':10,'createdAt':(now-timedelta(days=2)).isoformat()},{'branchId':'b1','itemId':'p-1','quantity':5,'createdAt':now.isoformat()}]
 items,_=build(s,'b1',{'scope':'selected','itemIds':['p-1'],'countedAt':(now-timedelta(days=1)).isoformat()},s['products'])
 assert items[0]['book']==10
 adjust(s,'b1',items[0],-2)
 assert current(s,'b1',items[0])==13

def test_serving_count_does_not_touch_ingredients():
 s=default_state();s['logisticsState']['batches']=[{'id':'b','branchId':'b1','recipeId':101,'actualWeight':5,'cost':100,'servingLots':[{'id':'l','acceptedAt':'now','responsibleId':2,'acceptedWeight':5,'soldWeight':1}]}]
 stocks=deepcopy(s['logisticsState']['branchStocks'])
 items,_=build(s,'b1',{'scope':'serving'},[])
 assert items[0]['book']==4
 adjust(s,'b1',items[0],-1)
 assert current(s,'b1',items[0])==3 and s['logisticsState']['branchStocks']==stocks
 with pytest.raises(WorkspaceError):build(s,'b1',{'scope':'serving','countedAt':datetime.now(timezone.utc).isoformat()},[])


def test_owner_can_create_count_and_submit_for_selected_branch():
 s=default_state()
 _,iid=apply_action(s,OWNER,'inventory.start',{'branchId':'b1','scope':'selected','itemIds':['p-1']})
 apply_action(s,OWNER,'inventory.submit',{'id':iid,'items':[{'itemId':'p-1','actual':7}]})
 apply_action(s,OWNER,'inventory.post',{'id':iid})
 assert s['logisticsState']['branchStocks']['b1']['p-1']==7
