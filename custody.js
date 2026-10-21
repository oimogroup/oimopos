(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const kg = value => Number(value || 0).toLocaleString('ru-RU',{maximumFractionDigits:3})+' кг';
  const kinds = {ingredient_count:'Пересчёт ингредиентов',opening_acceptance:'Приёмка начального остатка',rejection:'Отказ в приёмке',transfer:'Передача с кухни',acceptance:'Приёмка',handover:'Смена ответственного',writeoff:'Списание',surplus:'Излишек на раздаче',count:'Пересчёт',review:'Решение руководителя',cancel:'Отмена передачи',close:'Закрытие партии',sale:'Продажа'};
  const statuses = {pending:'Ожидает подтверждения',review:'Расхождение — на проверке',recorded:'Зафиксировано',accepted:'Принято',approved:'Подтверждено',rejected:'Отклонено',canceled:'Отменено',refunded:'Возврат оплаты'};
  function mount(root, options) {
    if (!root) return;
    root.classList.add('custody-panel');
    let data = {}, items = [], busy = false, pending = null, generation = 0, ready = false;
    root.innerHTML = `<header><h3>Приёмка, остатки и списание</h3><button class="secondary-button" type="button" data-refresh>Обновить</button></header>
      <p class="custody-note">Приёмку подтверждает получатель под своей учётной записью. Списание исключает блюдо из продажи до решения руководителя.</p>
      <form data-form><fieldset disabled><label>Операция<select data-operation><option value="accept">Принять передачу</option><option value="writeoff">Заявка на списание</option><option value="count">Пересчитать остаток</option><option value="handover">Передать другому сотруднику</option><option value="review">Рассмотреть документ</option><option value="cancel">Отменить передачу</option><option value="close">Закрыть партию</option></select></label>
      <label>Документ / остаток<select data-target required></select></label><p data-balance class="custody-note"></p>
      <label data-quantity-label><span data-quantity-caption>Фактически принято, кг</span><input data-quantity type="number" min="0" step="0.001" inputmode="decimal"></label>
      <label data-recipient-label>Новый ответственный<select data-recipient></select></label>
      <label data-decision-label>Решение<select data-decision><option value="approve">Подтвердить</option><option value="reject">Отклонить</option></select></label>
      <label>Причина / комментарий<textarea data-reason rows="2" maxlength="500" placeholder="Причина списания, расхождения или результат проверки"></textarea></label>
      <button class="primary-button" type="submit" data-submit>Зафиксировать</button></fieldset></form><p data-message role="status"></p>
      <h3>Остатки под ответственностью</h3><div class="custody-table"><table><thead><tr><th>Партия / витрина</th><th>Ответственный</th><th>Принято</th><th>Продано</th><th>Списано</th><th>На списании</th><th>Остаток</th></tr></thead><tbody data-lots></tbody></table></div><header><h3>Журнал операций</h3><button class="secondary-button" type="button" data-export>Скачать CSV</button></header>
      <input data-search type="search" placeholder="Номер, сотрудник, причина" aria-label="Поиск в журнале">
      <div class="custody-table"><table><thead><tr><th>Документ</th><th>Количество / расхождение</th><th>Сотрудники</th><th>Состояние</th></tr></thead><tbody data-journal></tbody></table></div>`;
    const $ = selector => root.querySelector(selector);
    const selected = () => items.find(item=>item.key===$('[data-target]').value);
    const setMessage = (message,error=false) => { $('[data-message]').textContent=message; $('[data-message]').classList.toggle('custody-error',error); };
    function targets() {
      const operation=$('[data-operation]').value;
      const old=$('[data-target]').value;
      const documents=data.documents || [];
      if (['accept','review','cancel'].includes(operation)) {
        items=documents.filter(doc => operation==='accept' ? doc.status==='pending'&&['transfer','handover'].includes(doc.kind)&&String(doc.recipient?.id)===String(data.actorId) : operation==='review' ? data.canReview&&((['writeoff','surplus'].includes(doc.kind)&&doc.status==='pending')||doc.status==='review') : doc.status==='pending'&&['transfer','handover'].includes(doc.kind)&&(data.canReview||String(doc.actor.id)===String(data.actorId)))
          .map(doc=>({key:doc.id,doc,label:`${doc.number} · ${doc.name || kinds[doc.kind]} · ${doc.batchNumber}${doc.weight!=null?' · '+kg(doc.weight):''}`}));
      } else {
        items=(data.lots||[]).filter(lot=>lot.canAct&&!lot.handoverId&&operation!=='close').map(lot=>({key:lot.id,lot,batchId:lot.batchId,balance:lot.balanceWeight,label:`${lot.name} · ${lot.line} · ${kg(lot.balanceWeight)} · ${lot.responsibleName}`}));
        if(operation!=='handover') items.push(...(data.kitchens||[]).filter(batch=>batch.canAct&&(operation!=='close'||data.canReview)).map(batch=>({key:batch.id,batchId:batch.id,balance:batch.availableWeight,label:`Кухня · ${batch.name} · ${batch.number} · ${kg(batch.availableWeight)}`})));
      }
      $('[data-target]').innerHTML=items.length ? '<option value="">Выберите запись</option>'+items.map(item=>`<option value="${esc(item.key)}">${esc(item.label)}</option>`).join('') : '<option value="">Нет доступных записей</option>';
      if(items.some(item=>item.key===old)) $('[data-target]').value=old;
      $('[data-recipient]').innerHTML='<option value="">Выберите сотрудника</option>'+(data.recipients||[]).map(person=>`<option value="${esc(person.id)}">${esc(person.name)}</option>`).join('');
      details();
    }
    function details() {
      const operation=$('[data-operation]').value,item=selected();
      const quantity=['accept','writeoff','count'].includes(operation);
      $('[data-quantity-label]').hidden=!quantity;
      $('[data-quantity]').required=quantity;
      $('[data-quantity]').min=operation==='writeoff'?'0.001':'0';
      $('[data-quantity-caption]').textContent=operation==='accept'?'Фактически принято, кг':operation==='count'?'Фактический остаток, кг':'Количество к списанию, кг';
      $('[data-recipient-label]').hidden=operation!=='handover';
      $('[data-recipient]').required=operation==='handover';
      $('[data-decision-label]').hidden=operation!=='review';
      $('[data-decision] option[value="reject"]').disabled=!['writeoff','surplus'].includes(item?.doc?.kind);
      if(!['writeoff','surplus'].includes(item?.doc?.kind)) $('[data-decision]').value='approve';
      $('[data-reason]').required=['writeoff','review','cancel','close'].includes(operation);
      $('[data-balance]').textContent=item ? item.doc ? `${item.doc.name ? item.doc.name+". " : ""}Отправитель: ${item.doc.actor.name}. ${item.doc.reason||''}${item.doc.weight!=null?' Передано: '+kg(item.doc.weight):''}${item.doc.variance!=null?' Расхождение: '+kg(item.doc.variance):''}` : `По учёту: ${kg(item.balance)}. ${operation==='handover'?'До приёмки новым сотрудником этот остаток будет недоступен для продажи.':''}` : '';
      $('[data-submit]').disabled=busy||!item;
    }
    function journal() {
      $('[data-lots]').innerHTML=(data.lots||[]).map(lot=>`<tr><td>${esc(lot.name)}<small>${esc(lot.batchNumber)} · ${esc(lot.line)}</small></td><td>${esc(lot.responsibleName)}${lot.handoverId?'<small>Передача ожидает приёмки</small>':''}</td><td>${kg(lot.acceptedWeight)}</td><td>${kg(lot.soldWeight)}</td><td>${kg(lot.writeoffWeight)}</td><td>${kg(lot.reservedWeight)}</td><td>${kg(lot.balanceWeight)}</td></tr>`).join('')||'<tr><td colspan="7">Принятых остатков нет</td></tr>';
      const query=$('[data-search]').value.trim().toLocaleLowerCase();
      const docs=(data.documents||[]).filter(doc=>JSON.stringify(doc).toLocaleLowerCase().includes(query));
      $('[data-journal]').innerHTML=docs.slice(0,300).map(doc=>`<tr><td><b>${esc(doc.number)} · ${esc(kinds[doc.kind]||doc.kind)}</b><small>${esc(doc.batchNumber)} · ${esc(new Date(doc.createdAt).toLocaleString('ru-RU'))}</small><details><summary>Причина и решение</summary><p>${esc(doc.reason||doc.rejectReason||'Без расхождений')}</p>${doc.items?.length?`<table><thead><tr><th>Ингредиент</th><th>Учёт</th><th>Факт</th><th>Разница</th></tr></thead><tbody>${doc.items.map(item=>`<tr><td>${esc(item.name)}</td><td>${esc(item.expectedQuantity)} ${esc(item.unit)}</td><td>${esc(item.actualQuantity)} ${esc(item.unit)}</td><td>${esc(item.variance)} ${esc(item.unit)}</td></tr>`).join('')}</tbody></table>`:''}${doc.reviewNote?`<p>Решение: ${esc(doc.reviewNote)} · ${esc(doc.reviewedBy?.name)}</p>`:''}${doc.sourceId?`<small>Связанный документ: ${esc((data.documents||[]).find(row=>row.id===doc.sourceId)?.number||doc.sourceId)}</small>`:''}</details></td><td>${doc.weight!=null?kg(doc.weight):''}${doc.expectedWeight!=null?`<small>Учёт: ${kg(doc.expectedWeight)}</small>`:''}${doc.actualWeight!=null?`<small>Факт: ${kg(doc.actualWeight)}</small>`:''}${doc.variance!=null?`<strong class="${doc.variance<0?'custody-error':''}">${doc.variance>0?'+':''}${kg(doc.variance)}</strong>`:''}</td><td>${esc(doc.actor.name)}${doc.responsible?`<small>Ответственный: ${esc(doc.responsible.name)}</small>`:''}${doc.recipient?`<small>Получатель: ${esc(doc.recipient.name)}</small>`:''}${doc.rejectedBy?`<small>Отклонил: ${esc(doc.rejectedBy.name)}</small>`:''}${doc.acceptedBy?`<small>Принял: ${esc(doc.acceptedBy.name)}</small>`:''}</td><td>${esc(statuses[doc.status]||doc.status)}</td></tr>`).join('') || '<tr><td colspan="4">Операций пока нет</td></tr>';
    }
    async function reload() {
      const sequence=++generation; ready=false; $('[data-form] fieldset').disabled=true;
      try { const result=await options.load(); if(sequence!==generation)return; data=result; ready=true; $('[data-form] fieldset').disabled=false; targets(); journal(); }
      catch(error) { if(sequence!==generation)return; $('[data-form] fieldset').disabled=true; setMessage(error.message,true); }
    }
    $('[data-form]').addEventListener('submit',async event=>{
      event.preventDefault(); if(busy||!event.target.reportValidity())return;
      const operation=$('[data-operation]').value,item=selected();if(!item)return;
      const payload={reason:$('[data-reason]').value.trim()};
      if(item.doc) payload.documentId=item.doc.id;
      else {payload.batchId=item.batchId; if(item.lot)payload.lotId=item.lot.id;}
      if(['accept','count'].includes(operation))payload.actualWeight=Number($('[data-quantity]').value);
      if(operation==='writeoff')payload.weight=Number($('[data-quantity]').value);
      if(['count','handover'].includes(operation))payload.expectedWeight=item.balance;
      if(operation==='handover')payload.recipientId=$('[data-recipient]').value;
      if(operation==='review')payload.decision=$('[data-decision]').value;
      const signature=JSON.stringify({operation,payload});
      if(pending?.signature!==signature)pending={signature,id:crypto.randomUUID()};payload.requestId=pending.id;
      busy=true;$('[data-form] fieldset').disabled=true;setMessage('Сохранение…');
      try {
        const response=await options.action('custody.'+operation,payload);
        if(!response)throw new Error('Операция не сохранена');
        pending=null;$('[data-quantity]').value='';$('[data-reason]').value='';
        setMessage(operation==='writeoff'?'Заявка сохранена. Количество исключено из продажи до решения руководителя.':'Операция зафиксирована.');
        if(options.after)await options.after(response);
        await reload();
      } catch(error) {setMessage(error.message,true);}
      finally {busy=false;$('[data-form] fieldset').disabled=!ready;details();}
    });
    $('[data-operation]').addEventListener('change',()=>{$('[data-quantity]').value='';targets();});
    $('[data-target]').addEventListener('change',()=>{$('[data-quantity]').value='';details();});
    $('[data-search]').addEventListener('input',journal);
    $('[data-refresh]').addEventListener('click',()=>{if(!busy)reload();});
    $('[data-export]').addEventListener('click',()=>{
      const cell=value=>'"'+String(value??'').replace(/^[=+@-]/,"'$&").replace(/"/g,'""')+'"';
      const rows=[['Документ','Дата','Операция','Партия','Автор','Ответственный','Получатель','Передано/списано кг','Учёт кг','Факт кг','Расхождение кг','Причина','Статус','Руководитель','Решение','Себестоимость'],...(data.documents||[]).map(d=>[d.number,d.createdAt,kinds[d.kind],d.batchNumber,d.actor.name,d.responsible?.name,d.recipient?.name,d.weight,d.expectedWeight,d.actualWeight,d.variance,d.reason,statuses[d.status],d.reviewedBy?.name,d.reviewNote,d.costAmount])];
      const url=URL.createObjectURL(new Blob(['\ufeff'+rows.map(row=>row.map(cell).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='uchet-vitriny.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });
    async function reviewDocument(id) {
      await reload();
      if(!ready)return;
      $('[data-operation]').value='review';targets();
      if(!items.some(item=>item.key===id)) { setMessage('Заявка уже рассмотрена или недоступна. Обновлённый статус — в журнале.',true);return; }
      $('[data-target]').value=id;details();$('[data-reason]').focus();
    }
    reload();return {reload,reviewDocument};
  }
  window.Custody={mount};
})();
