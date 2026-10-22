(() => {
  const $=selector=>document.querySelector(selector), api=window.AshkanaApi;
  const text=(tag,value)=>{const node=document.createElement(tag);node.textContent=value;return node;};
  const date=value=>value?new Date(value).toLocaleString('ru-RU'):'—';
  const labels={creating:'Создаётся',pending:'Ожидает оплаты',paid:'Оплачено',failed:'Не завершено',review:'Нужна проверка',refunded:'Возвращено'};
  let activeRefund;
  const status=value=>{$('#platformBillingMessage').textContent=value;};
  async function load() {
    try {
      const data=await api.platformBilling();
      $('#platformBillingStatus').textContent=`${data.testing?'Тестовый':'Боевой'} режим. ${data.ready?'Настройки заполнены. Реальную готовность подтвердите тестом с Freedom Pay.':'Не заполнено: '+data.missing.join(', ')+'.'} Секретный ключ задаётся только в Environment Render.`;
      const body=$('#platformPaymentRows');body.replaceChildren();
      for(const order of data.orders) {
        const row=document.createElement('tr');
        for(const value of [order.tenantName,order.id,`${order.amount} KGS${order.testing?' · тест':''}`,labels[order.status],date(order.service_ends_at),`${order.refund_amount} KGS`]) row.append(text('td',value));
        const cell=document.createElement('td'), button=text('button','Проверить');button.type='button';button.className='secondary-button';
        button.addEventListener('click',async()=>{button.disabled=true;try{await api.platformRefreshPayment(order.id);await load();status('Статус получен от провайдера.');}catch(error){status(error.message);}finally{button.disabled=false;}});
        cell.append(button);row.append(cell);body.append(row);
        if(order.review_reason){const note=document.createElement('tr'),td=text('td',order.review_reason);td.colSpan=7;note.append(td);body.append(note);}
      }
      if(!data.orders.length){const row=document.createElement('tr'),td=text('td','Платежей пока нет.');td.colSpan=7;row.append(td);body.append(row);}
      const requests=$('#platformRefunds');requests.replaceChildren();
      for(const refund of data.refundRequests) {
        const item=document.createElement('article');item.className='billing-refund';
        item.append(text('b',`${refund.tenant_name} · ${refund.amount} KGS`),text('p',`${refund.order_id} · ${refund.reason}`),text('p',`Подтверждено провайдером: ${refund.refund_amount} KGS. Доступ до ${date(refund.current_period_ends_at)}.`));
        if(refund.status==='new') {
          const button=text('button','Рассмотреть');button.type='button';button.className='secondary-button';
          button.addEventListener('click',()=>{activeRefund=refund;$('#resolveRefundForm').reset();$('#resolveRefundMessage').textContent='';$('#resolveRefundOrder').textContent=`${refund.order_id}. Подтверждён возврат ${refund.refund_amount} KGS.`;$('#resolveRefundDialog').showModal();});item.append(button);
        } else item.append(text('p',`${refund.status==='approved'?'Подтверждён':'Отклонён'} · ${refund.resolution}`));
        requests.append(item);
      }
      if(!data.refundRequests.length) requests.append(text('p','Запросов возврата пока нет.'));
    }catch(error){$('#platformBillingStatus').textContent='Не удалось загрузить оплату. '+error.message;}
  }
  $('#platformBillingRefresh').addEventListener('click',load);
  $('#resolveRefundCancel').addEventListener('click',()=>$('#resolveRefundDialog').close());
  $('#resolveRefundForm').addEventListener('submit',async event=>{
    event.preventDefault();const button=event.submitter;button.disabled=true;
    try{
      const decision=$('#refundDecision').value,raw=$('#refundAccessUntil').value;
      if(decision==='approved' && (!raw || Number(activeRefund.refund_amount)<=0)) throw new Error('Для подтверждения нужны возврат в Freedom Pay, проверка статуса и согласованная дата доступа.');
      await api.platformResolveRefund(activeRefund.id,{decision,reason:$('#refundResolution').value.trim(),access_until:decision==='approved'?new Date(raw).toISOString():null});
      $('#resolveRefundDialog').close();await load();status('Решение сохранено.');
    }catch(error){$('#resolveRefundMessage').textContent=error.message;}finally{button.disabled=false;}
  });
  window.OimoBillingPanel={load};
})();
