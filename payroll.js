/* Owner payroll workspace. All calculation and financial writes run on the server. */
(function(global){
 'use strict';
 const q=s=>document.querySelector(s),esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let context=null,loading=0,busy=false,command=null;
 if(typeof currentRole!=='undefined'&&currentRole!=='owner')document.querySelectorAll('[data-finance-tab="payroll"],[data-owner-finance-tab="payroll"]').forEach(button=>{button.hidden=true;});
 const fmt=value=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(Number(value||0));
 const cash=value=>fmt(value)+' '+(context?.currency||'');
 const employee=id=>context?.employees.find(e=>String(e.id)===String(id));
 const name=id=>employee(id)?.display_name||context?.policies.find(p=>String(p.employeeId)===String(id))?.employeeName||String(id);
 const active=()=>context.employees.filter(e=>e.is_active&&!e.deleted_at);
 const currentPolicy=id=>context.policies.filter(p=>String(p.employeeId)===String(id)&&p.effectiveFrom<=context.companyToday).sort((a,b)=>b.effectiveFrom.localeCompare(a.effectiveFrom)||b.sequence-a.sequence)[0];
 const roleLabels={waiter:'Официант',cashier:'Кассир',production:'Производство',branch_manager:'Руководитель',hall_admin:'Администратор зала',storekeeper:'Кладовщик',marketer:'Маркетолог'};
 function empty(text){return `<p class="payroll-empty">${esc(text)}</p>`;}
 function latestOverlaps(){return context.runs.some(r=>r.start<=context.end&&r.end>=context.start);}
 async function open(){
  if(typeof currentRole!=='undefined'&&currentRole!=='owner'){q('#payrollStatus').textContent='Зарплата доступна только владельцу компании.';return;}
  const generation=++loading;q('#payrollStatus').textContent='Загружаем расчёт…';q('#payrollApprove').disabled=true;
  try{
   const result=await global.AshkanaApi.payroll(q('#payrollFrom').value,q('#payrollTo').value);
   if(generation!==loading)return;
   context=result;q('#payrollFrom').value=result.start;q('#payrollTo').value=result.end;
   render();q('#payrollStatus').textContent=result.openShifts.length?'Есть незакрытые рабочие смены. Их нужно завершить перед начислением.':'';
  }catch(error){if(generation===loading)q('#payrollStatus').textContent=error.message||'Не удалось загрузить расчёт. Нажмите «Обновить».';}
 }
 function render(){
  q('#payrollApprove').disabled=latestOverlaps()||context.end>=context.companyToday||context.openShifts.length>0||!context.rows.some(row=>row.total);
  q('#payrollExport').disabled=false;
  q('#payrollSummary').innerHTML=[['Рассчитано за период',cash(context.total)],['Начислено во всех ведомостях',cash(context.runs.reduce((s,r)=>s+r.total,0))],['Общий долг сотрудникам',cash(Object.values(context.balances).reduce((s,v)=>s+Math.max(0,v),0))]].map(([label,value])=>`<article><span>${label}</span><strong>${value}</strong></article>`).join('');
  q('#payrollRows').innerHTML=context.rows.length?context.rows.map(row=>`<tr><td><strong>${esc(row.employeeName)}</strong><small>${esc(roleLabels[row.staffRole]||'Сотрудник')}</small></td><td>${fmt(row.hours)} ч / ${row.shifts}</td><td>${cash(row.fixed)}</td><td>${cash(row.commission)}</td><td>${cash(row.adjustment)}</td><td><strong>${cash(row.total)}</strong></td><td>${cash(context.balances[row.employeeId]||0)}</td><td>${employee(row.employeeId)?.is_active&&!employee(row.employeeId)?.deleted_at?`<div class="payroll-row-actions"><button type="button" data-payroll-policy="${esc(row.employeeId)}">Ставка</button><button type="button" data-payroll-adjust="${esc(row.employeeId)}">Корректировка</button><button type="button" data-payroll-advance="${esc(row.employeeId)}">Аванс</button></div>`:''}</td></tr>`).join(''):'<tr><td colspan="8">Сначала добавьте сотрудников.</td></tr>';
  q('#payrollPolicies').innerHTML=active().length?active().map(e=>{
   const p=currentPolicy(e.id),fixed=p&&p.fixedMode!=='none'?`${cash(p.fixedAmount)} / ${{hour:'час',shift:'смену',month:'месяц'}[p.fixedMode]}`:'Без фиксированной ставки';
   const percent=p?`Личные продажи: ${fmt(p.personalPercent)}% · Продажи в рабочее время: ${fmt(p.shiftPercent)}% · Обслуживание: ${fmt(p.servicePercent)}%`:'Расчёт ещё не настроен';
   return `<div class="payroll-record"><div><strong>${esc(e.display_name)}</strong><small>${fixed}</small><small>${percent}${p?' · с '+p.effectiveFrom:''}</small></div><button type="button" class="secondary-action" data-payroll-policy="${e.id}">Настроить</button></div>`;
  }).join(''):empty('Добавьте сотрудников в разделе «Доступ».');
  q('#payrollTime').innerHTML=[...context.workShifts].reverse().map(s=>`<div class="payroll-record"><div><strong>${esc(s.employeeName)}</strong><small>${esc(dateTime(s.openedAt))} → ${s.closedAt?esc(dateTime(s.closedAt)):'Смена открыта'}</small><small>${s.source==='employee'?'Отмечено сотрудником':'Внесено владельцем'}${s.corrections?.length?' · есть история исправлений':''}</small></div>${employee(s.employeeId)?.is_active?`<button class="secondary-action" type="button" data-payroll-time="${esc(s.id)}">Исправить время</button>`:''}</div>`).join('')||empty('Рабочие смены ещё не отмечены. Они учитываются отдельно от кассовых смен.');
  q('#payrollRuns').innerHTML=[...context.runs].reverse().map(run=>`<article class="payroll-run"><header><div><strong>${run.start} — ${run.end}</strong><small>${cash(run.total)} · Начислено ${esc(dateTime(run.createdAt))}</small></div><button type="button" class="secondary-action" data-payroll-export-run="${esc(run.id)}">CSV</button></header>${run.rows.filter(r=>r.total||r.paid).map(r=>{const due=Math.max(0,Math.min(r.total-r.paid,context.balances[r.employeeId]||0));return `<div class="payroll-record"><div><strong>${esc(r.employeeName)}</strong><small>Начислено ${cash(r.total)} · Зачтено и выплачено ${cash(r.paid)} · Можно выплатить ${cash(due)}</small></div>${due>0?`<button type="button" class="secondary-action" data-payroll-pay="${esc(run.id)}" data-employee="${esc(r.employeeId)}">Выплатить</button>`:''}</div>`;}).join('')}</article>`).join('')||empty('После проверки расчёта нажмите «Начислить за период».');
  q('#payrollPayments').innerHTML=[...context.payments].reverse().map(p=>`<div class="payroll-record"><div><strong>${esc(p.employeeName)} · ${cash(p.amount)}</strong><small>${esc(dateTime(p.occurredAt))} · ${esc(p.reason)}${p.unallocatedAmount?' · Незачтённый аванс '+cash(p.unallocatedAmount):''}</small><small>${p.reversedAt?'Отменено: '+esc(p.reversalReason):'Проведено в финансах'}</small></div>${!p.reversedAt?`<button type="button" class="secondary-action" data-payroll-reverse="${esc(p.id)}">Отменить выплату</button>`:''}</div>`).join('')||empty('Выплат и авансов пока нет.');
  q('#payrollEvents').innerHTML=[...context.events].reverse().map(e=>`<div class="payroll-record"><div><strong>${esc(e.employeeName)} · ${cash(e.amount)}</strong><small>${e.date} · ${esc({sales:'Процент от продажи',refund:'Возврат чека',adjustment:'Корректировка'}[e.type]||e.type)}${e.saleId?' · '+esc(e.saleId):''}</small>${e.reason?`<small>${esc(e.reason)}</small>`:''}</div></div>`).join('')||empty('Проценты начнут фиксироваться после настройки ставок и новых продаж. Старые продажи автоматически не пересчитываются.');
 }
 function dateTime(value){return new Date(value).toLocaleString('ru-RU',{timeZone:context.timezone});}
 const hidden=(name,value)=>`<input name="${name}" type="hidden" value="${esc(value)}">`;
 const input=(name,label,value='',extra='')=>`<label>${label}<input name="${name}" value="${esc(value)}" ${extra}></label>`;
 const reason=label=>input('reason',label,'','required minlength="3" maxlength="1000"');
 const accounts=()=>`<label>Откуда / куда деньги<select name="accountId" required><option value="">Выберите счёт</option>${context.accounts.map(a=>`<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('')}</select></label>`;
 const employees=selected=>`<label>Сотрудник<select name="employeeId" required>${active().map(e=>`<option value="${e.id}" ${String(e.id)===String(selected)?'selected':''}>${esc(e.display_name)}</option>`).join('')}</select></label>`;
 const localDate=value=>{if(!value)return '';const d=new Date(value);d.setMinutes(d.getMinutes()-d.getTimezoneOffset());return d.toISOString().slice(0,16);};
 function dialog(action,title,fields,submit='Сохранить'){
  command=action;q('#payrollDialogTitle').textContent=title;q('#payrollFormFields').innerHTML=fields;q('#payrollFormError').textContent='';q('#payrollDialogSubmit').textContent=submit;q('#payrollDialog').showModal();
 }
 function policyDialog(id){
  const p=currentPolicy(id)||{fixedMode:'none',fixedAmount:0,personalPercent:0,shiftPercent:0,servicePercent:0,categoryRates:{}};
  const rate=(key,label)=>input(key,label,p[key],'type="number" min="0" max="100" step="0.01" required');
  dialog('payroll.policy','Ставка: '+name(id),hidden('employeeId',id)+`<p class="payroll-note">Можно сочетать фиксированную оплату и проценты. За личные продажи получает сотрудник, открывший заказ.</p>`+input('effectiveFrom','Действует с',context.companyToday,`type="date" min="${context.companyToday}" required`)+`<label>Фиксированная оплата<select name="fixedMode">${[['none','Без фиксированной ставки'],['hour','За час'],['shift','За рабочую смену'],['month','За месяц']].map(([v,l])=>`<option value="${v}" ${p.fixedMode===v?'selected':''}>${l}</option>`).join('')}</select></label>`+input('fixedAmount','Размер ставки',p.fixedAmount,'type="number" min="0" step="0.01" required')+rate('personalPercent','Процент от личных продаж после скидок')+`<details><summary>Дополнительные проценты и категории</summary>${rate('shiftPercent','Процент от всех продаж во время рабочей смены')}${rate('servicePercent','Процент от суммы обслуживания своих заказов')}<p class="payroll-note">Процент по категориям заменяет общий процент. Пустое поле — общий процент, 0 — исключить категорию.</p><div class="payroll-category-head"><span>Категория</span><span>Личные, %</span><span>За смену, %</span></div>${context.categories.slice(0,100).map((cat,i)=>`<div class="payroll-category-row"><span>${esc(cat)}</span><input aria-label="Личные продажи: ${esc(cat)}" name="cat${i}personal" type="number" min="0" max="100" step="0.01" value="${p.categoryRates?.[cat]?.personal??''}" placeholder="Общий"><input aria-label="Продажи за смену: ${esc(cat)}" name="cat${i}shift" type="number" min="0" max="100" step="0.01" value="${p.categoryRates?.[cat]?.shift??''}" placeholder="Общий"></div>`).join('')}</details>`);
 }
 q('#finance-pane-payroll').addEventListener('click',event=>{
  if(!context)return;
  const button=event.target.closest('button');if(!button)return;
  const d=button.dataset;
  if(d.payrollPolicy){policyDialog(d.payrollPolicy);return;}
  if(d.payrollAdjust){dialog('payroll.adjust','Корректировка: '+name(d.payrollAdjust),hidden('employeeId',d.payrollAdjust)+input('date','Дата',context.companyToday,'type="date" required')+input('amount','Сумма: доплата со знаком +, уменьшение со знаком −','','type="number" step="0.01" required')+reason('Основание корректировки'));return;}
  if(d.payrollAdvance){dialog('payroll.advance','Аванс: '+name(d.payrollAdvance),hidden('employeeId',d.payrollAdvance)+input('amount','Сумма аванса','','type="number" min="0.01" step="0.01" required')+accounts()+reason('Основание аванса'),'Провести аванс');return;}
  if(d.payrollPay){const run=context.runs.find(r=>r.id===d.payrollPay),row=run.rows.find(r=>String(r.employeeId)===d.employee);const due=Math.max(0,Math.min(row.total-row.paid,context.balances[d.employee]||0));dialog('payroll.pay','Выплата: '+row.employeeName,hidden('employeeId',d.employee)+hidden('runId',run.id)+`<p class="payroll-note">Ведомость ${run.start} — ${run.end}. Доступно к выплате: ${cash(due)}.</p>`+input('amount','Сумма выплаты',due,`type="number" min="0.01" max="${due}" step="0.01" required`)+accounts()+input('reason','Основание','Зарплата за '+run.start+' — '+run.end,'required minlength="3" maxlength="1000"'),'Провести выплату');return;}
  if(d.payrollReverse){const p=context.payments.find(p=>p.id===d.payrollReverse);dialog('payroll.reverse','Отмена выплаты',hidden('paymentId',p.id)+`<p class="payroll-note">${esc(p.employeeName)} · ${cash(p.amount)}. Деньги должны фактически вернуться. Операция создаст приход и восстановит задолженность.</p>`+accounts()+reason('Причина возврата денег'),'Отменить выплату');return;}
  if(d.payrollTime){timeDialog(context.workShifts.find(s=>s.id===d.payrollTime));return;}
  if(d.payrollExportRun){exportRows(context.runs.find(r=>r.id===d.payrollExportRun));return;}
 });
 function timeDialog(shift){
  dialog('payroll.time',shift?'Исправить рабочее время':'Рабочая смена',(shift?hidden('id',shift.id)+hidden('employeeId',shift.employeeId)+hidden('expectedVersion',context.version)+`<p>${esc(shift.employeeName)}</p>`:employees())+input('openedAt','Начало (по часовому поясу этого устройства)',localDate(shift?.openedAt),'type="datetime-local" required')+input('closedAt','Окончание (по часовому поясу этого устройства)',localDate(shift?.closedAt),'type="datetime-local" required')+reason('Основание отметки времени'));
 }
 q('#payrollAddTime').onclick=()=>{if(context)timeDialog();};
 q('#payrollApprove').onclick=()=>{if(context&&!q('#payrollApprove').disabled)dialog('payroll.approve','Начислить зарплату за период',hidden('start',context.start)+hidden('end',context.end)+hidden('expectedVersion',context.version)+`<p class="payroll-note">${context.start} — ${context.end}. Сумма ${cash(context.total)}. Начисление закрепит ведомость и закроет период для изменения рабочего времени и корректировок. Деньги списываются только при выплате.</p>`,'Начислить');};
 q('#payrollForm').addEventListener('submit',async event=>{
  event.preventDefault();if(busy||!context||!event.target.reportValidity())return;
  const payload=Object.fromEntries(new FormData(event.target));
  for(const key of ['fixedAmount','personalPercent','shiftPercent','servicePercent','amount','expectedVersion'])if(key in payload)payload[key]=Number(payload[key]);
  if(command==='payroll.policy'){
   const overrides={};context.categories.slice(0,100).forEach((cat,i)=>{const rates={};for(const kind of ['personal','shift']){const key=`cat${i}${kind}`;if(payload[key]!=='')rates[kind]=Number(payload[key]);delete payload[key];}if(Object.keys(rates).length)overrides[cat]=rates;});payload.categoryRates=overrides;
  }
  if(command==='payroll.time'){payload.openedAt=new Date(payload.openedAt).toISOString();payload.closedAt=new Date(payload.closedAt).toISOString();}
  busy=true;q('#payrollDialogSubmit').disabled=true;q('#payrollDialogCancel').disabled=true;q('#payrollDialogClose').disabled=true;q('#payrollFormError').textContent='';
  try{const response=await global.AshkanaApi.action(command,payload);if(typeof hydrateServerWorkspace==='function'){hydrateServerWorkspace(response);renderAll();}q('#payrollDialog').close();await open();}
  catch(error){q('#payrollFormError').textContent=error.message||'Операция не подтверждена. Проверьте историю перед повтором.';}
  finally{busy=false;q('#payrollDialogSubmit').disabled=false;q('#payrollDialogCancel').disabled=false;q('#payrollDialogClose').disabled=false;}
 });
 ['payrollDialogClose','payrollDialogCancel'].forEach(id=>q('#'+id).onclick=()=>{if(!busy)q('#payrollDialog').close();});
 q('#payrollDialog').addEventListener('cancel',event=>{if(busy)event.preventDefault();});
 ['payrollRefresh','payrollCalculate'].forEach(id=>q('#'+id).onclick=open);
 ['payrollFrom','payrollTo'].forEach(id=>q('#'+id).addEventListener('change',()=>{q('#payrollApprove').disabled=true;q('#payrollExport').disabled=true;q('#payrollStatus').textContent='Период изменён. Нажмите «Рассчитать».';}));
 function exportRows(report){const cell=value=>'"'+String(value??'').replace(/^[=+@-]/,"'$&").replaceAll('"','""')+'"';const rows=[['Период',report.start,report.end],['Сотрудник','Часы','Смены','Ставка','Проценты и возвраты','Корректировки','Начислено'],...report.rows.map(r=>[r.employeeName,r.hours,r.shifts,r.fixed,r.commission,r.adjustment,r.total])];const blob=new Blob(['\ufeff'+rows.map(r=>r.map(cell).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`Зарплата-${report.start}-${report.end}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 q('#payrollExport').onclick=()=>{if(context&&!q('#payrollExport').disabled)exportRows(context);};
 global.OimoPayroll={open};
 if(location.hash==='#finance/payroll')open();
})(window);
