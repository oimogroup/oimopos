(() => {
  'use strict';
  const tabs = [...document.querySelectorAll('[data-preview]')];
  const selectTab = (tab, focus = false) => {
    for (const item of tabs) {
      const selected = item === tab;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      document.getElementById(item.getAttribute('aria-controls')).hidden = !selected;
    }
    if (focus) tab.focus();
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectTab(tab));
    tab.addEventListener('keydown', event => {
      const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
      if (next !== null) { event.preventDefault(); selectTab(tabs[next], true); }
    });
  });
  const form = document.getElementById('connectionForm');
  const message = document.getElementById('formMessage');
  const submit = document.getElementById('connectionSubmit');
  document.querySelectorAll('[data-plan-choice]').forEach(link => link.addEventListener('click', () => { form.elements.plan.value = link.dataset.planChoice; }));
  document.getElementById('year').textContent = String(new Date().getFullYear());
  async function loadPlans() {
    try {
      const response = await fetch('/api/v1/public/plans', {credentials:'omit'});
      if (!response.ok) throw new Error();
      const plans = await response.json();
      for (const code of ['canteen','restaurant']) {
        const plan = plans.find(item => item.code === code);
        const price = Number(plan?.monthly_price);
        if (!plan || !Number.isFinite(price) || price < 0) throw new Error();
        document.querySelector(`[data-price="${code}"]`).textContent = new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(price);
        document.querySelector(`[data-price-unit="${code}"]`).textContent = 'сом / месяц';
      }
    } catch (_) {
      document.querySelectorAll('[data-price]').forEach(node => { node.textContent = 'По запросу'; node.classList.add('price-unavailable'); });
      document.querySelectorAll('[data-price-unit]').forEach(node => { node.textContent = ''; });
    }
  }
  loadPlans();
  let pending = null;
  let busy = false;
  const makeId = () => {
    if (crypto.randomUUID) return crypto.randomUUID();
    const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
    const hex=[...bytes].map(n=>n.toString(16).padStart(2,'0')).join('');
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  };
  try { pending = JSON.parse(sessionStorage.getItem('oimo-connection-pending') || 'null'); } catch (_) { /* Storage is optional. */ }
  // Recover only the request ID and fingerprint; contact details stay out of storage.
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    const payload = {name:form.elements.name.value.trim(),phone:form.elements.phone.value.trim(),company:form.elements.company.value.trim(),plan:form.elements.plan.value,consent:form.elements.consent.checked,website:form.elements.website.value};
    const digits=payload.phone.replace(/\D/g,'');
    if (!/^[+\d ()-]+$/.test(payload.phone) || digits.length<7 || digits.length>15) { message.textContent='Проверьте номер телефона: укажите от 7 до 15 цифр.';form.elements.phone.focus();return; }
    if (payload.name.length<2 || payload.company.length<2) { message.textContent='Укажите имя и название заведения — минимум 2 символа.';return; }
    // A lost response must never create a second request. A changed form starts a new one.
    busy=true;submit.disabled=true;submit.textContent='Отправляем…';message.textContent='';
    const text=JSON.stringify(payload);
    let fingerprint;
    try {
      const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text));
      fingerprint=[...new Uint8Array(hash)].map(n=>n.toString(16).padStart(2,'0')).join('');
    } catch (_) { fingerprint=text; }
    if (!pending || pending.fingerprint!==fingerprint) pending={id:makeId(),fingerprint};
    if (fingerprint!==text) { try { sessionStorage.setItem('oimo-connection-pending',JSON.stringify(pending)); } catch (_) {} }
    try {
      const response=await fetch('/api/v1/public/connection-requests',{method:'POST',credentials:'omit',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,request_id:pending.id})});
      const contentType=response.headers.get('Content-Type') || '';
      const body=contentType.includes('application/json') ? await response.json() : null;
      if(!response.ok) throw new Error(typeof body?.detail==='string' ? body.detail : response.status===422 ? 'Проверьте имя, телефон и название заведения.' : 'Не удалось отправить заявку. Повторите попытку.');
      if(body?.ok!==true) throw new Error('Нет подтверждения приёма заявки. Повторите отправку.');
      pending=null;try {sessionStorage.removeItem('oimo-connection-pending');}catch(_){}
      form.hidden=true;
      const success=document.getElementById('formSuccess');success.hidden=false;success.tabIndex=-1;success.focus();
    } catch(error) {message.textContent=error.message==='Failed to fetch' ? 'Нет связи с сервером. Проверьте интернет и повторите отправку.' : error.message;}
    finally {busy=false;submit.disabled=false;submit.innerHTML='Оставить заявку <span aria-hidden="true">↗</span>';}
  });
})();
