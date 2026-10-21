/* Pure offline receipt calculation; server recomputes from its frozen catalog. */
(function(global){
 'use strict';
 const copy=value=>JSON.parse(JSON.stringify(value));
 const round=value=>Math.round((value+Number.EPSILON)*100)/100;
 const require=(ok,message)=>{if(!ok){const error=new Error(message);error.status=422;throw error;}};
 function pending(device){return (device.receipts||[]).filter(r=>r.status!=='synced');}
 function project(device){
  const result=copy(device.workspace),state=result.state,branch=device.session.branchId;
  state.sales ||= [];
  const stocks=state.logisticsState?.branchStocks?.[branch]||{};
  for(const entry of pending(device)){
   if(state.sales.some(s=>s.requestId===entry.payload.requestId||s.id===entry.saleId))continue;
   const sale=copy(entry.sale);sale.offlineStatus=entry.status;state.sales.unshift(sale);
   for(const deduction of entry.deductions||[]){
    if(deduction.kind==='stock')stocks[deduction.id]=Math.max(0,Number(stocks[deduction.id]||0)-deduction.quantity);
    if(deduction.kind==='lot'){
     const recipe=state.recipes.find(r=>String(r.id)===String(deduction.id));
     const lot=recipe?.availableLots?.find(l=>l.id===deduction.lotId);
     if(lot)lot.available=Math.max(0,Number(lot.available)-deduction.quantity);
    }
   }
  }
  if(state.serviceMode==='restaurant')for(const recipe of state.recipes){
   const capacities=(recipe.components||[]).map(c=>({amount:Number(c.gross??c.net)/1000,id:c.ingredientId})).filter(c=>c.amount>0).map(c=>Number(stocks[c.id]||0)/c.amount);
   const fractional=global.CompanySettings.normalize(state.companySettings).general.fractional;
   const scale=fractional?100:1;recipe.availableToOrder=Math.max(0,Math.floor((Math.min(...capacities,Number(recipe.availableToOrder||0))+1e-9)*scale)/scale);
  }
  return result;
 }
 function eligible(payload){return !payload.openOrderId&&!payload.customerId&&!payload.discountPercent&&['dine-in','takeaway'].includes(payload.orderType||'dine-in')&&payload.payments?.length===1&&payload.payments[0].method==='cash';}
 function create(device,actor,payload,at){
  require(eligible(payload),'Без связи доступны новые заказы за наличные, без персональных скидок и доставки.');
  require(actor?.lease&&actor.shift&&!actor.shift.closedAt,'Сначала войдите по PIN и откройте смену при работающем интернете.');
  require(at>=new Date(actor.lease.issuedAt).getTime()-120000&&at<=new Date(actor.lease.expiresAt).getTime(),'Автономный доступ истёк или часы устройства изменились. Нужна связь с сервером.');
  require(!device.blocked,'Доступ кассы изменился. Войдите онлайн.');
  require(!device.closing,'Результат закрытия смены ещё не подтверждён. Восстановите связь с сервером.');
  require((device.receipts||[]).filter(r=>r.status!=='synced').length<2000,'Очередь заполнена. Восстановите связь для отправки чеков.');
  const state=project(device).state,branch=device.session.branchId;
  require(!(state.logisticsState?.inventories||[]).some(i=>i.branchId===branch&&['counting','submitted','returned'].includes(i.status)),'На складе идёт инвентаризация. Автономная продажа недоступна.');
  const settings=global.CompanySettings.normalize(state.companySettings),stocks=state.logisticsState?.branchStocks?.[branch]||{};
  const costs=state.logisticsState?.branchCosts?.[branch]||{};
  const deductions=[],items=[],used=new Set();let subtotal=0;
  require(payload.items?.length>0&&payload.items.length<=100,'Проверьте состав чека.');
  for(const raw of payload.items){
   const qty=Number(raw.quantity),id=String(raw.id),key=id+'|'+(raw.lotId||'');
   require(Number.isFinite(qty)&&qty>0&&!used.has(key),'Проверьте количество позиций.');used.add(key);
   const product=state.products.find(i=>String(i.id)===id),recipe=state.recipes.find(i=>String(i.id)===id),item=product||recipe;
   require(item,'Позиция не найдена в сохранённом меню.');
   if(recipe&&!settings.general.fractional)require(Number.isInteger(qty),'Это блюдо продаётся целыми порциями.');
   let unitCost=Number(costs[id]||0);
   if(product){require(!raw.lotId,'Для товара не выбирается партия.');stocks[id]=Number(stocks[id]||0)-qty;require(stocks[id]>=-1e-6,'Недостаточно товара: '+item.name);deductions.push({kind:'stock',id,quantity:qty});}
   else if(state.serviceMode==='restaurant'){
    require(!raw.lotId&&recipe.components?.length,'Проверьте техкарту блюда.');unitCost=0;
    for(const c of recipe.components){const required=Number(c.gross??c.net)/1000*qty,ingredient=String(c.ingredientId);stocks[ingredient]=Number(stocks[ingredient]||0)-required;require(stocks[ingredient]>=-1e-6,'Недостаточно сырья: '+item.name);deductions.push({kind:'stock',id:ingredient,quantity:required});unitCost+=required*Number(costs[ingredient]||0)/qty;}
   }else{
    const lot=recipe.availableLots?.find(l=>l.id===raw.lotId);require(lot&&Number(lot.available)>=qty,'Недостаточно принятых порций: '+item.name);lot.available-=qty;deductions.push({kind:'lot',id,lotId:raw.lotId,quantity:qty});
   }
   const price=Number(item.price);require(Number.isFinite(price)&&price>=0,'Некорректная цена.');subtotal+=price*qty;
   items.push({id:item.id,name:item.name,category:item.category,unit:product?(item.unit||'шт'):'порция',quantity:qty,price,unitCost,noDiscount:!!item.noDiscount});
  }
  subtotal=round(subtotal);const service=round(subtotal*(payload.applyService??settings.general.serviceDefault?settings.general.servicePercent:0)/100);
  const before=round(subtotal+service),total=settings.general.roundTotal?Math.floor(before):before;
  const received=Number(payload.payments[0].amount);require(Number.isFinite(received)&&received>=total&&total>0,'Недостаточно наличных для оплаты.');
  const id=payload.requestId;require(typeof id==='string'&&id.length>=8&&id.length<=80,'Некорректный идентификатор чека.');
  const sale={id:'offline-'+id,number:'Л-'+id,offlineNumber:'Л-'+id,requestId:id,offline:true,offlineStatus:'pending',createdAt:new Date(at).toISOString(),branchId:branch,branch:state.branches.find(b=>b.id===branch)?.name||'',cashier:actor.operator.name,cashierId:actor.operator.id,registerId:device.session.registerId,shiftId:actor.shift.id,currency:settings.general.currency,orderType:payload.orderType||'dine-in',table:payload.table||'',items,subtotal,discountPercent:0,discountAmount:0,serviceAmount:service,deliveryAmount:0,rounding:round(before-total),total,received,change:round(received-total),paymentMethod:'cash',payments:[{method:'cash',amount:total}],comment:payload.comment||''};
  return {requestId:id,payload:copy(payload),token:actor.lease.token,leaseId:actor.lease.id,createdAt:sale.createdAt,total,status:'pending',sale,deductions};
 }
 global.OfflinePosCore={project,create,eligible,pending};
})(window);
