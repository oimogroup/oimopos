(() => {
  'use strict';
  const $=selector=>document.querySelector(selector),api=window.AshkanaApi;
  api.setClientMode('admin');
  const fragment=new URLSearchParams(location.hash.slice(1));
  const action=fragment.get('action'),token=fragment.get('token');
  // Keep bearer tokens in memory, outside URLs, history, storage and referrers.
  if(location.hash)history.replaceState(null,'',location.pathname+location.search);
  // A mail app may reuse an already-open /account tab for the next link.
  window.addEventListener('hashchange',()=>{if(location.hash)location.reload();});
  let busy=false;
  const say=text=>{$('#accountMessage').textContent=text;};
  const hideForms=()=>document.querySelectorAll('form').forEach(form=>form.hidden=true);
  async function submit(event,work) {
    event.preventDefault();if(busy)return;
    busy=true;const button=event.currentTarget.querySelector('button');button.disabled=true;say('');
    try{await work();}catch(error){say(error.message);}
    finally{busy=false;button.disabled=false;}
  }
  $('#forgotForm').addEventListener('submit',event=>submit(event,async()=>{
    const result=await api.forgotPassword($('#forgotForm').elements.email.value.trim());say(result.message);
  }));
  $('#resetForm').addEventListener('submit',event=>submit(event,async()=>{
    const form=$('#resetForm');if(form.elements.password.value!==form.elements.confirmation.value){say('Пароли не совпадают.');return;}
    await api.resetPassword(token,form.elements.password.value);form.reset();hideForms();
    try{sessionStorage.removeItem('ashkana-auth-session-v1');}catch{}
    say('Пароль изменён. Войдите с новым паролем.');
  }));
  $('#verifyForm').addEventListener('submit',event=>submit(event,async()=>{
    await api.verifyEmail(token);hideForms();say('Email подтверждён. Можно вернуться в аккаунт.');$('#workspaceLink').hidden=false;
  }));
  $('#resendForm').addEventListener('submit',event=>submit(event,async()=>{
    const result=await api.sendVerificationEmail();say(result.message || 'Email уже подтверждён.');
  }));
  if(action==='reset' || action==='verify') {
    hideForms();
    $('#accountTitle').textContent=action==='reset'?'Новый пароль':'Подтверждение email';
    $('#accountDescription').textContent=action==='reset'?'Задайте новый пароль для вашего аккаунта.':'Нажмите кнопку, чтобы подтвердить адрес. Открытие ссылки само по себе его не подтверждает.';
    $('#requestNewLink').hidden=false;$('#requestNewLink').href=action==='verify'?'/account?verify=1':'/account';
    if(/^[A-Za-z0-9_-]{43,128}$/.test(token || ''))$(action==='reset'?'#resetForm':'#verifyForm').hidden=false;
    else say('Ссылка неполная. Запросите новое письмо.');
  } else if(new URLSearchParams(location.search).has('verify')) {
    hideForms();$('#accountTitle').textContent='Email аккаунта';$('#accountDescription').textContent='Подтвердите email для оплаты подписки и восстановления доступа.';
    (async()=>{try{const result=await api.emailStatus();$('#verificationAddress').textContent=result.email;$('#resendForm').hidden=result.verified || !result.canVerify;$('#workspaceLink').hidden=false;if(result.verified)say('Email уже подтверждён.');else if(!result.canVerify)say('Для этой учётной записи нужен email. Обратитесь к администратору.');}catch(error){say(error.status===401?'Войдите в аккаунт, затем откройте подтверждение email.':error.message);}})();
  }
})();
