(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const api = window.AshkanaApi;
  const labels = {creating:'Ожидаем подтверждение создания',pending:'Ожидает оплаты или подтверждения',paid:'Оплачено',failed:'Оплата не завершена',review:'Проверяется поддержкой',refunded:'Возвращено'};
  const date = value => value ? new Date(value).toLocaleString('ru-RU', {dateStyle:'medium',timeStyle:'short'}) : '—';
  const amount = value => new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(Number(value)) + ' сом';
  let data, session, busy = false, refundOrder;
  const period=()=>$('#billingPeriod').value;
  const selectedPrice=()=>data.plan?.[period()==='annual'?'annual_price':'monthly_price'];
  const canPay=()=>data.canPay && Number.isFinite(Number(selectedPrice())) && Number(selectedPrice())>0;
  const requestKey=(value=period())=> 'oimo-subscription-request-'+session.tenantId+(value==='annual'?'-annual':'');
  function clearCompletedRequest() {
    try {
      for(const value of ['monthly','annual']) {
        const key=requestKey(value),orderId=sessionStorage.getItem(key+'-order');
        if(data.orders.some(order=>order.id===orderId && ['paid','failed','refunded'].includes(order.status))) {
          sessionStorage.removeItem(key);sessionStorage.removeItem(key+'-order');
        }
      }
    }catch{}
  }
  const message = value => { $('#statusMessage').textContent = value; };
  function element(tag, text, className) { const node=document.createElement(tag); node.textContent=text; if(className) node.className=className; return node; }
  function safeCheckout(value) {
    try {const url=new URL(value); return url.protocol==='https:' && !url.username && !url.password && (!url.port || url.port==='443') && url.hostname.endsWith('.freedompay.kg') && !/[\s\\]/.test(value); } catch {return false;}
  }
  function action(text, callback) { const button=element('button',text,'text-button'); button.type='button'; button.addEventListener('click',async()=>{button.disabled=true;try{await callback();}catch(error){message(error.message);}finally{button.disabled=false;}}); return button; }
  function renderOrders() {
    const list=$('#orders'); list.replaceChildren();
    if (!data.orders.length) {list.append(element('p','Платежей пока нет.','muted'));return;}
    for (const order of data.orders) {
      const row=element('article','','order'); row.dataset.order=order.id;
      row.append(element('b',(labels[order.status] || order.status)+(order.testing?' · тест':' '),'order-status'),element('b',amount(order.amount),'amount'));
      const details=element('div',''); details.append(element('p',`${order.period_months===12?'За год':'За месяц'} · ${date(order.created_at)}`),element('small',order.id));
      if(order.service_ends_at) details.append(element('p',`Период: ${date(order.service_starts_at)} — ${date(order.service_ends_at)}`));
      if(Number(order.refund_amount)>0) details.append(element('p',`Подтверждён возврат: ${amount(order.refund_amount)}`));
      if(order.review_reason) details.append(element('small',order.review_reason));
      row.append(details);
      const actions=element('div','','actions');
      if(order.status==='pending' && new Date(order.expires_at)>new Date() && safeCheckout(order.checkout_url)) {
        const link=element('a','Продолжить оплату'); link.href=order.checkout_url; link.rel='noreferrer'; actions.append(link);
      }
      if(!['failed','refunded'].includes(order.status)) actions.append(action('Проверить оплату',async()=>{await api.refreshSubscriptionPayment(order.id); await load(); message('Статус проверен.');}));
      const refund=data.refundRequests.find(request=>request.order_id===order.id);
      if(refund) actions.append(element('span',({new:'Запрос возврата рассматривается',approved:'Возврат подтверждён',rejected:'По возврату принято решение. Подробности — в поддержке'})[refund.status],'muted'));
      else if(order.applied_at && !order.testing && order.status!=='refunded') actions.append(action('Запросить возврат',async()=>{refundOrder=order.id;$('#refundReason').value='';$('#refundMessage').textContent='';$('#refundDialog').showModal();}));
      row.append(actions); list.append(row);
    }
  }
  function render() {
    const sub=data.subscription;
    $('#billingContent').hidden=false; $('#testNotice').hidden=!data.testing;
    $('#emailNotice').hidden=data.emailVerified!==false;
    $('#companyName').textContent=session.tenantName || 'Ваш аккаунт';
    $('#planName').textContent=data.plan?.name || sub.plan_code;
    $('#planPrice').textContent=selectedPrice()!=null && Number(selectedPrice())>0 ? amount(selectedPrice()) : 'Уточните стоимость';
    $('#periodDescription').textContent=period()==='annual'?'За 12 календарных месяцев · одним платежом':'За один календарный месяц · одним платежом';
    $('#branchLimit').textContent=`Лимит заведений: ${sub.max_branches}`;
    const expired=sub.status==='trialing' ? new Date(sub.trial_ends_at)<=new Date(data.serverTime) : sub.current_period_ends_at && new Date(sub.current_period_ends_at)<=new Date(data.serverTime);
    $('#accessStatus').textContent=sub.status==='trialing' ? `${expired?'Пробный период завершён':'Пробный доступ до'} ${date(sub.trial_ends_at)}` : sub.status==='active' ? (sub.current_period_ends_at ? `${expired?'Оплаченный период завершён':'Доступ оплачен до'} ${date(sub.current_period_ends_at)}` : 'Доступ включён без даты окончания') : 'Для продолжения работы продлите подписку';
    $('#workspaceLink').hidden=Boolean(expired || ['past_due','canceled'].includes(sub.status));
    $('#availability').textContent=data.message;
    $('#checkoutForm').hidden=!data.canPay;
    $('#payButton').disabled=!canPay() || busy;
    $('#billingPeriod').disabled=busy;
    $('#payButton').textContent=(data.testing?'Тест: оплатить ':'Оплатить ')+(period()==='annual'?'год':'месяц');
    const email=data.supportEmail;
    if(/^[^\s@<>]+@[^\s@<>]+$/.test(email)) $('#supportLink').href='mailto:'+email;
    renderOrders();
  }
  async function load() {data=await api.billing();clearCompletedRequest();render();}
  $('#billingPeriod').addEventListener('change',()=>{$('#termsAccepted').checked=false;render();message('');});
  $('#reload').addEventListener('click',async()=>{try{await load();message('Информация обновлена.');}catch(error){message(error.message);}});
  $('#logout').addEventListener('click',async()=>{try{await api.logout();sessionStorage.removeItem('ashkana-auth-session-v1');location.replace('/login');}catch(error){message(error.message);}});
  $('#checkoutForm').addEventListener('submit',async event=>{
    event.preventDefault();if(busy || !canPay() || !$('#termsAccepted').checked)return;
    busy=true;$('#payButton').disabled=true;$('#billingPeriod').disabled=true;
    const key=requestKey();
    try {
      let id;try{id=sessionStorage.getItem(key);}catch{}
      id ||= crypto.randomUUID();
      try{sessionStorage.setItem(key,id);}catch{}
      const order=await api.subscriptionCheckout({request_id:id,terms_accepted:true,terms_version:data.termsVersion,billing_period:period(),...(data.plan.updated_at?{price_version:data.plan.updated_at}:{})});
      try{sessionStorage.setItem(key+'-order',order.id);}catch{}
      if(['paid','failed','refunded'].includes(order.status)) {try{sessionStorage.removeItem(key);sessionStorage.removeItem(key+'-order');}catch{}}
      if(order.status==='pending' && safeCheckout(order.checkout_url)) {location.assign(order.checkout_url);return;}
      await load();message(order.review_reason || 'Заказ создан. Проверьте его статус в истории оплат.');
    }catch(error){message(error.message);}
    finally{busy=false;$('#payButton').disabled=!canPay();$('#billingPeriod').disabled=false;}
  });
  $('#refundCancel').addEventListener('click',()=>$('#refundDialog').close());
  $('#refundForm').addEventListener('submit',async event=>{
    event.preventDefault();const button=event.submitter;button.disabled=true;
    try{await api.requestSubscriptionRefund(refundOrder,$('#refundReason').value.trim());$('#refundDialog').close();await load();message('Запрос на возврат отправлен. Ответим по email.');}
    catch(error){$('#refundMessage').textContent=error.message;}finally{button.disabled=false;}
  });
  (async()=>{
    try {
      const auth=await api.me();session=auth.session;
      if(session.role!=='owner'){location.replace(session.route || '/login');return;}
      sessionStorage.setItem('ashkana-auth-session-v1',JSON.stringify(session));
      await load();
      message(new URLSearchParams(location.search).has('order')?'Вы вернулись с платёжной страницы. Проверьте статус заказа в истории ниже.':'');
    }catch(error){if(error.status===401){location.replace('/login');return;}message(error.message);}
  })();
})();
