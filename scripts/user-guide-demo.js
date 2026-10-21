/* Used only by capture_user_guide.py in its isolated Chrome profile. */
(()=>{
 const state=window.__GUIDE_STATE__,stamp='2026-10-22T09:00:00+05:00';
 const employee={id:2,display_name:'Анна Смирнова',name:'Анна Смирнова',login:'anna',staff_role:'cashier',staffRole:'cashier',roleLabel:'Кассир',initials:'АС',branch_id:'b1',branchId:'b1',is_active:true,permissions:{posAccess:true,posCash:true,posRefunds:true,posSupplies:true,inventory:true,production:true,finance:true}};
 window.__GUIDE_EMPLOYEES__=[employee,{...employee,id:3,display_name:'Айбек · Повар',name:'Айбек · Повар',login:'cook',staff_role:'production',staffRole:'production',permissions:{posAccess:true,production:true,inventory:true}}];
 window.__GUIDE_REGISTERS__=[{id:1,name:'Основная касса',account_login:'demo-cafe',branch_id:'b1',is_active:true,online:true,device_label:'Windows',last_seen_at:stamp}];
 state.companySettings={general:{currency:'KGS',timezone:'Asia/Almaty',serviceMode:'canteen'}};
 state.branches.push({...state.branches[0],id:'b2',number:2,login:'second',address:'Демонстрационный адрес'});
 state.branches.forEach((b,i)=>{b.name=i?'Кафе · Вторая точка':'Демо-кафе · Центральная';b.short=i?'Вторая точка':'Центральная';b.managerName='Демо · Руководитель'});
 for(const b of state.branches){state.logisticsState.branchStocks[b.id]=Object.fromEntries([...state.ingredients,...state.products].map(i=>[i.id,50]));state.logisticsState.branchCosts[b.id]=Object.fromEntries([...state.ingredients,...state.products].map(i=>[i.id,i.averageCost||30]));}
 state.recipes.forEach(r=>r.availableLots=[{id:'demo-lot-'+r.id,line:'Основная',batchNumber:'ВП-001',responsibleName:employee.name,available:20}]);
 state.logisticsState.batches=state.recipes.map((r,i)=>({id:'demo-batch-'+r.id,number:'ВП-00'+(i+1),branchId:'b1',recipeId:r.id,actualWeight:r.yield/1000*20,transferredWeight:r.yield/1000*20,portionWeight:r.yield,soldPortions:0,status:'serving',createdAt:stamp,createdBy:'Айбек · Повар',cost:20*80}));
 state.sales=[{id:'demo-sale',number:1001,branchId:'b1',branch:'Демо-кафе · Центральная',createdAt:'2026-10-22T10:30:00+05:00',paymentMethod:'card',cashier:employee.name,cashierId:2,total:500,subtotal:500,discountAmount:0,items:[{id:201,name:'Плов праздничный',category:'Горячее',price:230,unitCost:90,quantity:2},{id:'p-1',name:'Вода 0,5 л',category:'Напитки',price:40,unitCost:28,quantity:1}]}];
 const row={employeeId:'2',employeeName:employee.name,staffRole:'cashier',branchId:'b1',hours:120,shifts:15,fixed:21000,commission:1200,adjustment:0,total:22200};
 const policy={id:'policy1',sequence:1,employeeId:'2',employeeName:employee.name,effectiveFrom:'2026-10-01',fixedMode:'month',fixedAmount:31000,personalPercent:2,shiftPercent:0,servicePercent:0,categoryRates:{}};
 const bank={id:'finance-bank',name:'Расчётный счёт',type:'bank',status:'active'};
 const payroll={start:'2026-10-01',end:'2026-10-21',companyToday:'2026-10-22',version:1,currency:'KGS',timezone:'Asia/Almaty',total:22200,rows:[row],employees:[employee],policies:[policy],runs:[{id:'run1',start:'2026-10-01',end:'2026-10-21',createdAt:stamp,total:22200,rows:[{...row,paid:5000}]}],payments:[{id:'salary-pay',employeeId:'2',employeeName:employee.name,amount:5000,occurredAt:stamp,reason:'Аванс за октябрь'}],events:[],workShifts:[{id:'work1',employeeId:'2',employeeName:employee.name,openedAt:'2026-10-21T04:00:00Z',closedAt:'2026-10-21T12:00:00Z',source:'employee'}],openShifts:[],balances:{2:17200},accounts:[bank],categories:['Горячее','Напитки','Салаты']};
 const pnl={start:'2026-10-01',end:'2026-10-21',branchId:'all',companyToday:'2026-10-22',currency:'KGS',revenue:150000,cost:60000,gross:90000,otherIncome:0,expenses:48200,net:41800,margin:27.87,expenseGroups:[{id:'finance-expense-payroll',name:'Зарплата',amount:22200},{id:'finance-expense-rent',name:'Аренда',amount:21000},{id:'finance-expense-utilities',name:'Коммунальные услуги',amount:3500},{id:'finance-expense-fees',name:'Банковские комиссии',amount:1500}],documents:[{id:'rent1',start:'2026-10-01',end:'2026-10-31',amount:31000,paid:10000,recognized:21000,categoryId:'finance-expense-rent',reason:'Аренда помещения за октябрь',branchId:'b1'}],payments:[],warnings:[],categories:[{id:'finance-expense-rent',name:'Аренда'},{id:'finance-expense-utilities',name:'Коммунальные услуги'},{id:'finance-expense-taxes',name:'Налоги'},{id:'finance-expense-fees',name:'Банковские комиссии'}],accounts:[bank]};
 const shift={id:1,openingCash:5000,openedAt:stamp,registerId:1};
 window.__GUIDE_PAYROLL__=payroll;window.__GUIDE_PNL__=pnl;
 const original=window.fetch.bind(window);
 window.fetch=async (url,options={})=>{
  const u=new URL(typeof url==='string'?url:url.url,location.href);
  if(!u.pathname.startsWith('/api/'))return original(url,options);
  if(u.pathname==='/api/v1/pos/offline/lease')return new Response(JSON.stringify({token:'guide-synthetic-token',id:'guide-grant',issuedAt:new Date().toISOString(),expiresAt:new Date(Date.now()+86400000).toISOString(),shiftId:1,registerId:1,operatorId:2,version:1}),{headers:{'Content-Type':'application/json'}});
  if(u.pathname==='/api/v1/pos/unlock')return new Response(JSON.stringify({operator:employee,shift}),{headers:{'Content-Type':'application/json'}});
  if((options.method||'GET').toUpperCase()!=='GET')return new Response(JSON.stringify({detail:'Документация: запись в базу отключена'}),{status:403,headers:{'Content-Type':'application/json'}});
  let body={};const path=u.pathname.replace('/api/v1','');
  if(path==='/auth/me'){
   if(location.pathname==='/login')return new Response('{"detail":"Demo"}',{status:401,headers:{'Content-Type':'application/json'}});
   body={session:{role:'branch',staffRole:'pos_terminal',branchId:'b1',registerId:1,registerName:'Основная касса',tenantSlug:'demo-cafe'}};
  }
  else if(path==='/workspace')body={version:1,state};
  else if(path==='/pos/operator')body={operator:employee,shift};
  else if(path==='/pos/operators')body=[employee];
  else if(path==='/pos/work-shift')body={shift:{id:'today',openedAt:stamp}};
  else if(path==='/payroll')body=payroll;
  else if(path==='/pnl')body={...pnl,start:u.searchParams.get('start')||pnl.start,end:u.searchParams.get('end')||pnl.end};
  else if(path==='/employees')body=window.__GUIDE_EMPLOYEES__;
  else if(path==='/pos/registers')body=window.__GUIDE_REGISTERS__;
  return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
 };
})();
