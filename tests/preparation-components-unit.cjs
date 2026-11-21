const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const context={window:{},structuredClone};
for(const file of ['composition-core.js','company-settings.js','offline-pos-core.js'])vm.runInNewContext(fs.readFileSync(path.join(__dirname,'..',file),'utf8'),context);
const C=context.window.CatalogComposition,core=context.window.OfflinePosCore;
const state={serviceMode:'restaurant',companySettings:{general:{serviceDefault:false,servicePercent:0}},
 branches:[{id:'b1',name:'Test'}],ingredients:[],products:[],sales:[],
 preparations:[{id:'dough',name:'Тесто',yield:1000,components:[{ingredientId:'flour',gross:600,net:600},{ingredientId:'water',gross:400,net:400}]}],
 recipes:[{id:1,name:'Манты',price:200,yield:300,availableToOrder:83,components:[{preparationId:'dough',gross:200,net:200},{ingredientId:'meat',gross:100,net:100}]}],
 logisticsState:{branchStocks:{b1:{flour:10,water:10,meat:10}},branchCosts:{b1:{flour:100,water:0,meat:500}},inventories:[]}};
const flat=C.flatten(state.recipes[0],state);
assert.deepEqual(JSON.parse(JSON.stringify(flat)),[{ingredientId:'flour',gross:120,net:120},{ingredientId:'water',gross:80,net:80},{ingredientId:'meat',gross:100,net:100}]);
assert.equal(C.cost(state.recipes[0],state,id=>state.logisticsState.branchCosts.b1[id]),62);
const duplicated={components:[...state.recipes[0].components,{ingredientId:'flour',gross:30,net:30}]};
assert.equal(C.flatten(duplicated,state).find(row=>row.ingredientId==='flour').gross,150);
const cycle=structuredClone(state);cycle.preparations[0].components=[{preparationId:'dough',gross:100,net:100}];
assert.throws(()=>C.flatten(cycle.recipes[0],cycle),/Цикл/);
const snapshot=structuredClone(state);snapshot.recipes[0].rawComponents=flat;snapshot.preparations=[];
assert.equal(C.flatten(snapshot.recipes[0],snapshot).find(row=>row.ingredientId==='flour').gross,120);
const now=Date.now(),actor={operator:{id:2,name:'Cashier'},shift:{id:20},lease:{token:'test',id:'grant',issuedAt:new Date(now-1000).toISOString(),expiresAt:new Date(now+3600000).toISOString()}};
const device={session:{branchId:'b1',registerId:1},receipts:[],workspace:{version:1,state:snapshot}};
const entry=core.create(device,actor,{requestId:'pf-offline-test-0001',orderType:'dine-in',items:[{id:1,quantity:2}],payments:[{method:'cash',amount:400}]},now);
assert.equal(entry.total,400);assert.equal(entry.sale.items[0].unitCost,62);
assert.equal(entry.deductions.length,3);assert.ok(!entry.deductions.some(row=>row.id==='dough'));
device.receipts.push(entry);
const projected=core.project(device);
assert.equal(projected.state.logisticsState.branchStocks.b1.flour,9.76);
assert.equal(device.workspace.state.logisticsState.branchStocks.b1.flour,10);
assert.equal(projected.state.recipes[0].availableToOrder,81);
console.log('Preparation expansion, costs, cycles, duplicate ingredients, authorized snapshots and offline deductions: passed');
const produced=structuredClone(state);produced.preparations[0].stockMode='produced';
produced.logisticsState.branchStocks.b1['preparation:dough']=1;
produced.logisticsState.branchCosts.b1['preparation:dough']=60;
assert.deepEqual(JSON.parse(JSON.stringify(C.flatten(produced.recipes[0],produced,[],true))),[
 {ingredientId:'preparation:dough',gross:200,net:200},{ingredientId:'meat',gross:100,net:100}]);
const producedDevice={session:{branchId:'b1',registerId:1},receipts:[],workspace:{version:1,state:produced}};
const producedEntry=core.create(producedDevice,actor,{requestId:'pf-produced-offline-test-0001',orderType:'dine-in',items:[{id:1,quantity:2}],payments:[{method:'cash',amount:400}]},now);
assert.equal(producedEntry.sale.items[0].unitCost,62);
assert.deepEqual(Array.from(producedEntry.deductions,row=>row.id),['preparation:dough','meat']);
producedDevice.receipts.push(producedEntry);
const producedProjection=core.project(producedDevice);
assert.equal(producedProjection.state.logisticsState.branchStocks.b1['preparation:dough'],.6);
assert.equal(producedProjection.state.logisticsState.branchStocks.b1.flour,10);
console.log('Manufactured preparations: frozen cost and offline consumption without double raw deductions passed');
