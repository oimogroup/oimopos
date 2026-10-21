(function(global){
 'use strict';
 const q=s=>document.querySelector(s),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let busy=false,rows=[];
 async function open(force=false){
  if(currentRole!=='owner'||(!serverMode&&!force))return;
  const section=q('#offlineReviewSection');section.hidden=false;q('#offlineReviewStatus').textContent='Проверяем очередь автономных чеков…';
  try{
   rows=await global.AshkanaApi.offlineConflicts();section.open=rows.length>0;
   q('#offlineReviewStatus').textContent=rows.length?'Чеков на проверке: '+rows.length:'Все полученные автономные чеки проведены.';
   q('#offlineReviewList').innerHTML=rows.map(r=>`<article class="payroll-record"><div><strong>Л-${esc(r.requestId)} · ${esc(r.total)}</strong><small>${esc(r.employeeName)} · ${esc(new Date(r.createdAt).toLocaleString('ru-RU'))}</small><small>${esc(r.error)}</small><small>${(r.payload.items||[]).map(i=>esc(i.id)+' × '+esc(i.quantity)).join(', ')}</small></div><form data-offline-request="${esc(r.requestId)}"><label><input name="useCurrentShift" type="checkbox"> Провести в текущую открытую смену этой кассы, если исходная закрыта</label>${r.serverTotal!==undefined?`<label><input name="acceptServer" type="checkbox"> Серверный чек уже есть (${esc(r.serverTotal)}). Деньги и расхождение проверены; принять его без повторного списания.</label>`:''}<input name="reason" required minlength="3" maxlength="1000" placeholder="Основание решения владельца"><button type="submit" class="secondary-action">Повторить проведение</button><p role="alert"></p></form></article>`).join('');
  }catch(e){q('#offlineReviewStatus').textContent=e.message;}
 }
 q('#offlineReviewList').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.target;if(busy||!form.reportValidity())return;busy=true;form.querySelector('button').disabled=true;form.querySelector('p').textContent='';
  try{await global.AshkanaApi.resolveOfflineReceipt({requestId:form.dataset.offlineRequest,reason:form.elements.reason.value,useCurrentShift:form.elements.useCurrentShift.checked,acceptServer:Boolean(form.elements.acceptServer?.checked)});await open(true);if(typeof refreshServerWorkspace==='function'&&serverMode)await refreshServerWorkspace({silent:true});}
  catch(e){form.querySelector('p').textContent=e.message;}
  finally{busy=false;form.querySelector('button').disabled=false;}
 });
 global.OimoOfflineReview={open};
})(window);
