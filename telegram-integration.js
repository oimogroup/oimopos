(() => {
  'use strict';
  const root=document.querySelector('#view-integrations');
  if(!root || currentRole!=='owner')return;
  const q=selector=>root.querySelector(selector),esc=escapeHtml;
  let config=null,busy=false,dirty=false,generation=0,chats=[];
  const status=(message,error=false)=>{q('#telegramStatus').textContent=message;q('#telegramStatus').classList.toggle('telegram-error',error);};
  function controls(){
    root.querySelectorAll('input,select,button').forEach(el=>el.disabled=busy);
    q('#telegramDiscover').disabled=busy||!config?.configured||Boolean(q('#telegramToken').value);
    q('#telegramSave').disabled=busy||!config;
    root.querySelectorAll('[data-telegram-test]').forEach(button=>button.disabled=busy||dirty||!config?.configured||!config.routes.find(r=>r.branchId===button.dataset.telegramTest)?.chatId);
  }
  function readRoutes(){
    return [...root.querySelectorAll('[data-telegram-branch]')].map(row=>({branchId:row.dataset.telegramBranch,branchName:config.routes.find(r=>r.branchId===row.dataset.telegramBranch).branchName,enabled:row.querySelector('[data-route-enabled]').checked,chatId:row.querySelector('[data-route-chat]').value.trim(),threadId:row.querySelector('[data-route-thread]').value.trim()}));
  }
  function renderRoutes(rows=config.routes){
    q('#telegramRoutes').innerHTML=rows.map(route=>{
      const stored=config.routes.find(r=>r.branchId===route.branchId);
      return `<article class="telegram-route" data-telegram-branch="${esc(route.branchId)}"><header><h3>${esc(route.branchName)}</h3><label class="telegram-enabled"><input type="checkbox" data-route-enabled ${route.enabled?'checked':''}> Уведомлять</label></header><div class="telegram-route-fields"><label>ID группы<input data-route-chat value="${esc(route.chatId)}" placeholder="-100…" autocomplete="off" spellcheck="false" maxlength="20"></label><label>Тема, если нужна<input data-route-thread value="${esc(route.threadId)}" placeholder="Необязательно" inputmode="numeric" maxlength="10"></label>${chats.length?`<label>Найденная группа<select data-route-found><option value="">Выбрать группу</option>${chats.map(chat=>`<option value="${esc(chat.id)}">${esc(chat.title)} · ${esc(chat.id)}</option>`).join('')}</select></label>`:''}</div><div class="telegram-route-status"><span>${stored.lastError?`<strong class="telegram-error">${esc(stored.lastError)}</strong>`:stored.lastSentAt?'Последняя отправка: '+esc(new Date(stored.lastSentAt).toLocaleString('ru-RU')):'Уведомлений пока не было'}${stored.lastCheckedAt?'<small>Проверка: '+esc(new Date(stored.lastCheckedAt).toLocaleString('ru-RU'))+'</small>':''}</span><button type="button" class="secondary-action" data-telegram-test="${esc(route.branchId)}">Тест в группу</button></div></article>`;
    }).join('')||'<p>Сначала добавьте действующее заведение.</p>';
    controls();
  }
  function render(){
    q('#telegramEnabled').checked=config.enabled;q('#telegramToken').value='';
    q('#telegramToken').placeholder=config.configured?'Токен сохранён · введите только для замены':'Токен от @BotFather';
    q('#telegramBotStatus').textContent=config.configured?'Подключён бот @'+config.bot_username:'Бот ещё не подключён';
    q('#telegramChatCommand').textContent='/oimo_chat@'+(config.bot_username||'имя_бота');
    renderRoutes();
  }
  async function load(){
    if(busy)return;
    const request=++generation;busy=true;controls();status('Загружаем интеграцию…');
    try{const response=await window.AshkanaApi.telegramIntegration();if(request!==generation)return;config=response;dirty=false;render();status('');}
    catch(error){status(error.message||'Не удалось загрузить интеграцию',true);}
    finally{if(request===generation){busy=false;controls();}}
  }
  q('#telegramReload').onclick=()=>{if(dirty&&!confirm('Обновить настройки? Несохранённые изменения будут потеряны.'))return;load();};
  q('#telegramForm').addEventListener('input',()=>{dirty=true;controls();});
  q('#telegramForm').addEventListener('change',event=>{
    const select=event.target.closest('[data-route-found]');
    if(select?.value)select.closest('[data-telegram-branch]').querySelector('[data-route-chat]').value=select.value;
    dirty=true;controls();
  });
  q('#telegramForm').onsubmit=async event=>{
    event.preventDefault();if(busy||!config)return;
    const payload={revision:config.revision,enabled:q('#telegramEnabled').checked,token:q('#telegramToken').value.trim(),routes:readRoutes()};
    busy=true;controls();q('#telegramSaveStatus').textContent='Сохраняем…';status('');
    try{config=await window.AshkanaApi.saveTelegramIntegration(payload);dirty=false;render();q('#telegramSaveStatus').textContent='Сохранено';}
    catch(error){status(error.message||'Не удалось сохранить интеграцию',true);q('#telegramSaveStatus').textContent='Не сохранено';}
    finally{busy=false;controls();}
  };
  q('#telegramDiscover').onclick=async()=>{
    if(busy||!config?.configured)return;
    const draft=readRoutes();busy=true;controls();status('Ищем группы бота…');
    try{const result=await window.AshkanaApi.telegramGroups();chats=result.chats;renderRoutes(draft);status(chats.length?'Найдено групп: '+chats.length+'. Выберите группу для каждой точки.':'Групп не найдено. Добавьте бота в группу, отправьте команду из инструкции и повторите поиск.');}
    catch(error){status(error.message||'Не удалось найти группы',true);}
    finally{busy=false;controls();}
  };
  q('#telegramRoutes').onclick=async event=>{
    const button=event.target.closest('[data-telegram-test]');if(!button||button.disabled||busy)return;
    busy=true;controls();status('Отправляем тестовое сообщение…');
    try{await window.AshkanaApi.testTelegramGroup(button.dataset.telegramTest);const draft=readRoutes();config.routes.find(r=>r.branchId===button.dataset.telegramTest).lastError='';renderRoutes(draft);status('Тестовое сообщение отправлено. Проверьте группу выбранной точки.');}
    catch(error){status(error.message||'Telegram не подтвердил отправку',true);}
    finally{busy=false;controls();}
  };
  window.TelegramIntegration={open:()=>{if(!config)load();}};
  if(startupWorkspaceRoute==='integrations')window.TelegramIntegration.open();
  controls();
})();
