/* Durable per-register outbox. No session cookies or plaintext PINs are cached.
   Offline grants are scoped to the authenticated register and stored with its queue. */
(function(global){
 'use strict';
 const api=global.AshkanaApi,core=global.OfflinePosCore,raw={...api},q=s=>document.querySelector(s);
 const copy=v=>JSON.parse(JSON.stringify(v));
 let dbPromise,key=null,actorId=null,offline=false,swReady=false,initializing=null,flushing=false,leaseBusy=false,message='',device=null;
 const networkError=e=>!e.status||e.status>=500;
 const fail=text=>new api.ApiError(text,409);
 function database(){
  return dbPromise||=(new Promise((resolve,reject)=>{
   const request=indexedDB.open('oimo-offline-pos-v1',1);
   request.onupgradeneeded=()=>request.result.createObjectStore('records',{keyPath:'key'});
   request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
  }));
 }
 async function read(recordKey){const db=await database();return new Promise((resolve,reject)=>{const t=db.transaction('records','readonly'),r=t.objectStore('records').get(recordKey);r.onsuccess=()=>resolve(r.result?.value);r.onerror=()=>reject(r.error);});}
 async function write(recordKey,value){const db=await database();return new Promise((resolve,reject)=>{const t=db.transaction('records','readwrite');t.objectStore('records').put({key:recordKey,value});t.oncomplete=()=>resolve(value);t.onabort=()=>reject(t.error||new Error('Не удалось сохранить данные устройства.'));});}
 async function mutate(fn){
  if(!key)throw fail('Касса не подготовлена для автономной работы.');
  const recordKey=key;
  const db=await database();return new Promise((resolve,reject)=>{
   const t=db.transaction('records','readwrite'),store=t.objectStore('records'),r=store.get(recordKey);let result,error,updated;
   r.onsuccess=()=>{try{updated=r.result?.value;if(!updated)throw fail('Нет сохранённых данных кассы.');result=fn(updated);store.put({key:recordKey,value:updated});}catch(e){error=e;t.abort();}};
   t.oncomplete=()=>{if(key===recordKey)device=updated;resolve(result)};t.onabort=()=>reject(error||t.error||new Error('Хранилище недоступно. Чек не сохранён.'));
  });
 }
 async function init(){
  return initializing||=(async()=>{
   if(!global.isSecureContext||!indexedDB||!crypto.subtle){message='Для автономной кассы нужен HTTPS или localhost.';render();return false;}
   key=await read('active');if(key)device=await read(key);
   if('serviceWorker' in navigator){
    try{
     await navigator.serviceWorker.register('/pos-worker.js',{scope:'/pos'});
     await navigator.serviceWorker.ready;
     if(!navigator.serviceWorker.controller)await new Promise((resolve,reject)=>{
      const listener=()=>{if(navigator.serviceWorker.controller){clearTimeout(timer);navigator.serviceWorker.removeEventListener('controllerchange',listener);resolve();}};
      const timer=setTimeout(()=>{navigator.serviceWorker.removeEventListener('controllerchange',listener);reject(new Error('Обновите страницу кассы для завершения подготовки.'));},10000);
      navigator.serviceWorker.addEventListener('controllerchange',listener);listener();
     });swReady=true;
    }catch(e){message='Не удалось подготовить загрузку кассы без интернета.';}
   }
   render();return true;
  })().catch(e=>{message='Автономное хранилище недоступно: '+e.message;render();return false;});
 }
 function render(){
  const button=q('#offlineStatusButton');if(!button)return;
  const count=core.pending(device||{}).length,actor=device?.operators?.[actorId];
  const ready=capability(device);
  button.dataset.offline=String(offline);button.textContent=offline?`Нет связи · ${count} чеков к отправке`:count?`Отправка чеков: ${count}`:ready?'Онлайн · автономная касса готова':'Онлайн · автономная касса не готова';
  if(device?.legacyPayments?.length)button.textContent+=' · Есть оплата старой версии';
  if(q('#offlineDetails').open)renderDetails();
 }
 async function terminal(session){
  if(!await init())return;
  if(session.role!=='branch'||!session.registerId)return;
  const next='terminal:'+String(session.tenantId||session.tenantSlug)+'|'+session.registerId;
  if(key!==next){if(core.pending(device||{}).length)message='На прежней кассе остались неотправленные чеки. Вернитесь в неё для синхронизации; очередь сохранена отдельно.';actorId=null;key=next;device=await read(key);}
  device||={session,workspace:null,operators:{},receipts:[]};
  await write(key,{...device,session:copy(session),blocked:false});device=await read(key);await write('active',key);
 }
 async function cacheWorkspace(response,scope=key){
  if(!key||!response?.state)return;
  const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(catalog(response.state)));
  const catalogKey=Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('');
  if(key!==scope)throw fail('Активная касса изменилась. Вернитесь в исходное рабочее место.');
  await mutate(d=>{if(!d.workspace||Number(response.version||0)>=Number(d.workspace.version||0)){d.workspace=copy(response);d.catalogKey=catalogKey;}});
 }
 async function blocked(){if(key)await mutate(d=>{d.blocked=true;});actorId=null;render();}
 async function pinDigest(pin,salt){
  const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(pin),'PBKDF2',false,['deriveBits']);
  const value=await crypto.subtle.deriveBits({name:'PBKDF2',salt:Uint8Array.from(salt),iterations:150000,hash:'SHA-256'},key,256);
  return Array.from(new Uint8Array(value),b=>b.toString(16).padStart(2,'0')).join('');
 }
 async function rememberOperator(response,pin){
  if(!key||!response.operator)return;
  const id=String(response.operator.id),salt=pin?Array.from(crypto.getRandomValues(new Uint8Array(16))):null;
  const verifier=pin?await pinDigest(pin,salt):null;
  await mutate(d=>{const old=d.operators[id]||{};if(!pin&&old.operator?.accountVersion!==response.operator.accountVersion){delete old.verifier;delete old.salt;delete old.lease;}if(!response.shift||String(old.shift?.id)!==String(response.shift.id))delete old.lease;d.closing=false;d.operators[id]={...old,operator:copy(response.operator),shift:copy(response.shift),...pin?{salt,verifier}:{}};});
  actorId=id;api.setOperationActor?.(id);await prepare();
 }
 async function prepare(){
  if(leaseBusy||offline||!key||!actorId||!swReady)return;
  const id=actorId,scope=key,actor=device?.operators?.[id];if(!actor?.shift||actor.operator.staffRole==='production')return;
  if(!actor.verifier){message='Для автономной кассы один раз повторно войдите по личному PIN при работающей связи.';render();return;}
  leaseBusy=true;
  try{
   let lease,catalogAtGrant=device.catalogKey;
   try{lease=await raw.offlineLease(actor.lease?.token||'',device.workspace.version);}
   catch(e){
    if(e.status!==409)throw e;
    const previousKey=device.catalogKey;await cacheWorkspace(await raw.workspace(),scope);
    if(previousKey!==device.catalogKey&&typeof closePayment==='function'){closePayment();if(typeof showToast==='function')showToast('Меню обновилось. Проверьте заказ перед оплатой.');}
    await refreshUi();catalogAtGrant=device.catalogKey;lease=await raw.offlineLease(actor.lease?.token||'',device.workspace.version);
   }
   if(key!==scope||String(lease.operatorId)!==id||String(lease.registerId)!==String(device.session.registerId))throw fail('Сотрудник или касса изменились. Войдите по PIN повторно.');
   await mutate(d=>{d.operators[id].lease=lease;d.operators[id].catalog=catalogAtGrant;if(Number(lease.version)>=Number(d.workspace.version))d.workspace.version=lease.version;});
   await navigator.storage?.persist?.();message='';
  }catch(e){if(e.status>=400&&e.status<500&&key===scope)await mutate(d=>{if(d.operators[id])d.operators[id].lease=null;});message='Автономная касса не готова: '+e.message;}
  finally{leaseBusy=false;render();}
 }
 function catalog(state){return JSON.stringify([state.products,state.recipes?.map(({availableLots,availableToOrder,...r})=>r),state.preparations,state.ingredients?.map(({stock,averageCost,...r})=>r),state.companySettings]);}
 function capability(d){const a=d?.operators?.[actorId];return Boolean(swReady&&a?.shift&&!a.shift.closedAt&&a?.verifier&&a?.lease&&typeof d.catalogKey==='string'&&a.catalog===d.catalogKey&&Date.now()<=Date.parse(a.lease.expiresAt)&&!d.blocked&&!d.closing);}
 function projected(){return core.project(device);}
 async function offlineUnlock(pin){
  await init();if(!device||device.blocked)throw fail('Для входа в кассу нужна связь с сервером.');
  if(Date.now()<(device.pinLockedUntil||0))throw new api.ApiError('Слишком много попыток. Повторите через 5 минут.',429);
  let selected;
  for(const [id,a] of Object.entries(device.operators))if(a.verifier&&a.lease&&Date.now()<=Date.parse(a.lease.expiresAt)&&await pinDigest(pin,a.salt)===a.verifier){selected={id,a};break;}
  if(!selected){await mutate(d=>{d.pinFailures=(d.pinFailures||0)+1;if(d.pinFailures>=5){d.pinLockedUntil=Date.now()+300000;d.pinFailures=0;}});throw new api.ApiError('PIN не найден в автономном доступе. Введите PIN, проверенный онлайн на этой кассе.',403);}
  await mutate(d=>{d.pinFailures=0;});actorId=selected.id;offline=true;render();return {operator:selected.a.operator,shift:selected.a.shift};
 }
 async function refreshUi(){
  if(typeof hydrateWorkspace==='function'&&device?.workspace&&typeof currentSession!=='undefined'&&String(currentSession?.registerId)===String(device.session.registerId)){
   hydrateWorkspace(projected());if(typeof renderWorkspace==='function')renderWorkspace();
  }
  render();
 }
 api.me=async()=>{
  await init();try{const result=await raw.me();offline=false;await terminal(result.session);return result;}
  catch(e){if(!networkError(e)){if([401,403].includes(e.status))await blocked();throw e;}if(device?.workspace&&!device.blocked){offline=true;render();return {session:copy(device.session)};}throw e;}
 };
 api.workspace=async()=>{
  await init();const scope=key;try{const result=await raw.workspace();offline=false;await cacheWorkspace(result,scope);render();return device?.workspace?projected():result;}
  catch(e){if(!networkError(e)){if([401,403].includes(e.status))await blocked();throw e;}if(!device?.workspace||device.blocked)throw e;offline=true;render();return projected();}
 };
 api.posOperator=async()=>{
  try{const result=await raw.posOperator();offline=false;if(!result.operator)actorId=null;await rememberOperator(result);render();return result;}
  catch(e){if(!networkError(e)||!device?.workspace){if([401,403].includes(e.status))await blocked();throw e;}offline=true;actorId=null;render();return {operator:null,shift:null};}
 };
 api.posOperators=async()=>{try{return await raw.posOperators();}catch(e){if(!networkError(e))throw e;return Object.values(device?.operators||{}).filter(a=>a.verifier&&a.lease&&Date.parse(a.lease.expiresAt)>Date.now()).map(a=>a.operator);}};
 api.unlockPos=async pin=>{
  await init();try{const result=await raw.unlockPos(pin);offline=false;await rememberOperator(result,pin);return result;}
  catch(e){if(!networkError(e)){if(e.status===401)await blocked();if(e.status===429&&key)await mutate(d=>{d.pinLockedUntil=Date.now()+300000;});if(e.status===403&&device)for(const [id,a] of Object.entries(device.operators))if(a.verifier&&await pinDigest(pin,a.salt)===a.verifier)await mutate(d=>{delete d.operators[id].verifier;delete d.operators[id].lease;});throw e;}return offlineUnlock(pin);}
 };
 api.lockPos=async()=>{actorId=null;render();if(offline)return {};try{return await raw.lockPos();}catch(e){if(!networkError(e))throw e;offline=true;render();return {};}};
 api.logout=async()=>{if(core.pending(device||{}).length)throw fail('Сначала отправьте сохранённые чеки.');await blocked();return raw.logout();};
 api.action=async(action,payload)=>{
  await init();
  const scope=key;
  if(action==='sale.create'&&key&&typeof activeOperator!=='undefined'&&activeOperator&&String(activeOperator.id)!==String(actorId))throw new api.ApiError('Сотрудник изменился. Войдите по личному PIN повторно.',423);
  if(action!=='sale.create'){
   if(offline)throw fail('Эта операция требует связи с сервером. Автономно доступны новые продажи за наличные.');
   const result=await raw.action(action,payload);await cacheWorkspace(result,scope);prepare();return device?.workspace?{...projected(),entity:result.entity}:result;
  }
  const old=device?.receipts?.find(r=>r.requestId===payload.requestId);
  if(old){if(JSON.stringify(old.payload)!==JSON.stringify(payload))throw fail('Идентификатор оплаты уже использован с другим заказом.');if(old.status==='staged')await mutate(d=>{const r=d.receipts.find(r=>r.requestId===old.requestId);r.status='pending';r.acknowledged=true;});return {...projected(),entity:{type:'sale',id:old.saleId||old.sale.id}};}
  if(!core.eligible(payload)||!capability(device)){
   if(offline)throw fail(message||'Автономная продажа недоступна: нужен действующий доступ и новый заказ за наличные.');
   try{const response=await raw.action(action,payload);await cacheWorkspace(response,scope);prepare();return response;}
   catch(e){if(networkError(e)){offline=true;render();}throw e;}
  }
  let entry,existingRequest=false;
  await mutate(d=>{
   const existing=d.receipts.find(r=>r.requestId===payload.requestId);if(existing){if(JSON.stringify(existing.payload)!==JSON.stringify(payload))throw fail('Идентификатор уже используется другим заказом.');existingRequest=true;if(existing.status==='staged'){existing.status='pending';existing.acknowledged=true;}entry=existing;return;}
   if(!capability(d))throw fail('Автономный доступ изменился. Войдите онлайн.');
   const clock=Date.now();if(clock<(d.lastClock||0)-120000)throw fail('Часы устройства переведены назад. Восстановите правильное время.');
   entry=core.create(d,d.operators[actorId],payload,clock);entry.status='staged';entry.acknowledged=false;d.lastClock=clock;d.receipts.push(entry);
  });
  render();
  if(existingRequest)return {...projected(),entity:{type:'sale',id:entry.saleId||entry.sale.id}};
  if(!offline&&navigator.onLine){
   try{
    const response=await raw.action(action,payload);await cacheWorkspace(response,scope);await mutate(d=>{const r=d.receipts.find(r=>r.requestId===entry.requestId);r.status='synced';r.saleId=response.entity.id;});
    offline=false;render();prepare();return {...projected(),entity:response.entity};
   }catch(e){
    if(key!==scope)throw fail('Касса изменилась. Исходный чек сохранён в её очереди.');
    if(!networkError(e)){await mutate(d=>{const row=d.receipts.find(r=>r.requestId===entry.requestId);if(row.acknowledged){row.status='conflict';row.error=e.message;}else d.receipts=d.receipts.filter(r=>r.requestId!==entry.requestId);});if([401,403,423].includes(e.status)){await blocked();}render();throw e;}
   }
  }
  await mutate(d=>{const r=d.receipts.find(r=>r.requestId===entry.requestId);if(r.status!=='synced'){r.status='pending';r.acknowledged=true;}});
  offline=true;message='Чек сохранён на устройстве. Передача в облако ожидает связи.';render();return {...projected(),entity:{type:'sale',id:entry.sale.id},offline:true};
 };
 const wrapShift=(name)=>{api[name]=async(...args)=>{
  if(offline)throw fail('Открытие и закрытие кассовой смены требуют связи с сервером.');
  const id=actorId,shiftId=device?.operators?.[id]?.shift?.id;
  if(name==='closePosShift'&&key)await mutate(d=>{if(core.pending(d).length)throw fail('Сначала отправьте все автономные чеки и разберите ошибки.');d.closing=true;});
  try{
   const result=await raw[name](...args);if(id&&key)await mutate(d=>{d.closing=false;if(name==='closePosShift')for(const a of Object.values(d.operators))if(String(a.shift?.id)===String(shiftId)){a.shift=null;a.lease=null;}d.operators[id].shift=result.shift;d.operators[id].lease=null;});prepare();return result;
  }catch(e){if(name==='closePosShift'&&key&&!networkError(e))await mutate(d=>{d.closing=false;});throw e;}
 }};
 wrapShift('openPosShift');wrapShift('closePosShift');
 async function sync(){
  if(flushing||!key||!device||device.blocked||!navigator.onLine)return;
  flushing=true;
  const scope=key;
  const run=async()=>{
   const saved=await read(scope);if(key!==scope)return;device=saved;
   for(const entry of core.pending(device).filter(r=>r.status!=='staged'||Date.now()-Date.parse(r.createdAt)>30000).sort((a,b)=>a.createdAt.localeCompare(b.createdAt))){
    try{
     const response=await raw.syncOfflineReceipt({token:entry.token,payload:entry.payload,createdAt:entry.createdAt,total:entry.total});
     await cacheWorkspace(response,scope);await mutate(d=>{const row=d.receipts.find(r=>r.requestId===entry.requestId);Object.assign(row,{status:response.receipt.status,error:response.receipt.error||'',saleId:response.receipt.saleId});});offline=false;
    }catch(e){
     if(key!==scope)break;
     if(networkError(e)){offline=true;break;}
     if([401,403,423].includes(e.status)){await blocked();message='Войдите в эту кассу онлайн для отправки сохранённых чеков.';break;}
     await mutate(d=>{const row=d.receipts.find(r=>r.requestId===entry.requestId);row.status='conflict';row.error=e.message;});
    }
   }
   await refreshUi();
  };
  try{if(navigator.locks)await navigator.locks.request('oimo-offline-sync',run);else await run();}
  catch(e){message=e.message;render();}
  finally{flushing=false;render();if(!offline)prepare();}
 }
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function renderDetails(){
  const rows=core.pending(device||{});q('#offlineMessage').textContent=message||'Без облака работают новые продажи за наличные и локальная печать. Для работы после перезапуска введите PIN, ранее проверенный онлайн. Доступ действует до 24 часов; открытие/закрытие смены, возвраты и складские операции требуют связи.';
  q('#offlineQueue').innerHTML=rows.length?rows.map(r=>`<article><strong>${esc(r.sale.number)} · ${esc(r.total)} ${esc(r.sale.currency)}</strong><small>${esc(r.sale.cashier)} · ${esc(new Date(r.createdAt).toLocaleString('ru-RU'))}</small><p>${r.status==='conflict'?'Требуется проверка: '+esc(r.error):'Сохранён на устройстве, ожидает отправки'}</p></article>`).join(''):'<p>Неотправленных чеков нет.</p>';
  if(device?.legacyPayments?.length)q('#offlineQueue').insertAdjacentHTML('beforeend','<p>Сохранены неподтверждённые оплаты старой версии без привязки к кассе. Они не отправляются автоматически. Скачайте копию и передайте владельцу для сверки по исходным идентификаторам.</p>');
 }
 function exportQueue(){
  const rows=core.pending(device||{}).map(({token,...r})=>r);const data={format:'oimo-offline-receipts-v1',createdAt:new Date().toISOString(),tenantId:device?.session.tenantId,registerId:device?.session.registerId,receipts:rows,legacyPayments:device?.legacyPayments||[]};
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='Oimo-автономные-чеки-'+new Date().toISOString().slice(0,10)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 async function rememberLegacy(value){if(!key)return;await mutate(d=>{d.legacyPayments||=[];if(!d.legacyPayments.some(r=>r.payload?.requestId===value.payload?.requestId))d.legacyPayments.push(copy(value));});message='Есть неподтверждённая оплата старой версии. Откройте очередь и сохраните копию для ручной сверки владельцем.';render();}
 global.OfflinePos={init,sync,prepare,rememberLegacy,isOffline:()=>offline,hasPending:()=>core.pending(device||{}).length>0,canLeave:async()=>{await init();if(core.pending(device||{}).length){message='Перед выходом из кассы отправьте чеки или сохраните резервную копию очереди.';q('#offlineDetails').showModal();renderDetails();return false;}return true;},status:()=>({offline,swReady,count:core.pending(device||{}).length,ready:capability(device),message}),exportQueue};
 q('#offlineStatusButton')?.addEventListener('click',()=>{q('#offlineDetails').showModal();renderDetails();});
 q('#offlineDetailsClose')?.addEventListener('click',()=>q('#offlineDetails').close());
 q('#offlineSyncButton')?.addEventListener('click',async()=>{
  try{
   const auth=await api.me();if(typeof currentSession!=='undefined'&&String(auth.session.registerId)!==String(currentSession?.registerId))throw fail('Касса в браузере изменилась. Обновите страницу для входа в нужную кассу.');
   const response=await raw.workspace();await cacheWorkspace(response);offline=false;
   const operator=await raw.posOperator();
   if(operator.operator&&typeof activeOperator!=='undefined'&&activeOperator&&String(operator.operator.id)!==String(activeOperator.id)){actorId=null;throw new api.ApiError('Сотрудник в браузере изменился. Заблокируйте кассу и войдите по своему PIN.',423);}
   if(operator.operator)await rememberOperator(operator);else actorId=null;
   if(operator.operator&&typeof activateOperator==='function')activateOperator(operator.operator,operator.shift);
   await sync();await refreshUi();
  }catch(e){message=e.message;render();}
 });
 q('#offlineExportButton')?.addEventListener('click',exportQueue);
 global.addEventListener('online',()=>{sync();});global.addEventListener('offline',()=>{offline=true;render();});
 setInterval(()=>{if(key&&core.pending(device||{}).length)sync();},15000);
 global.addEventListener('beforeunload',e=>{if(core.pending(device||{}).length){e.preventDefault();e.returnValue='';}});
 init();
})(window);
