(() => {
  'use strict';
  const q = selector => document.querySelector(selector), esc = escapeHtml;
  const titles = {customers:'Клиенты', groups:'Группы клиентов', statistics:'Статистика клиентов', exclusions:'Исключения'};
  let tab = 'customers', busy = false, editing = null;
  const state = () => serverWorkspaceState || {};
  const customers = () => state().posState?.customers || [];
  const groups = () => state().posState?.customerGroups || [];
  const groupName = id => groups().find(g => g.id === id)?.name || 'Без группы';
  const effective = c => c.personalDiscountPercent === null ? Number(groups().find(g => g.id === c.groupId && !g.archivedAt)?.discountPercent || 0) : Number(c.personalDiscountPercent ?? c.discountPercent ?? 0);
  const input = (name, label, value = '', extra = '') => `<label>${label}<input name="${name}" value="${esc(value)}" ${extra}></label>`;
  const dialog = document.createElement('dialog');
  dialog.className = 'marketing-dialog'; dialog.id = 'marketingDialog'; dialog.setAttribute('aria-labelledby', 'marketingDialogTitle');
  dialog.innerHTML = '<form id="marketingForm"><header><h2 id="marketingDialogTitle"></h2><button type="button" class="icon-button" aria-label="Закрыть">×</button></header><div id="marketingFields"></div><p id="marketingError" role="alert"></p><footer><button type="button" class="secondary-action">Отмена</button><button type="submit" class="primary-button">Сохранить</button></footer></form>';
  document.body.append(dialog);
  const close = () => { if (!busy) dialog.close(); };
  dialog.querySelector('header button').onclick = close; dialog.querySelector('footer button').onclick = close;
  dialog.addEventListener('cancel', e => { if (busy) e.preventDefault(); });
  function open(next = tab) {
    if (currentRole !== 'owner') return;
    tab = Object.hasOwn(titles, next) ? next : 'customers';
    history.replaceState(null, '', '#marketing/' + tab);
    q('#breadcrumbTitle').textContent = 'Маркетинг / ' + titles[tab];
    document.querySelectorAll('[data-marketing-tab]').forEach(b => b.classList.toggle('active', b.dataset.marketingTab === tab));
    render(); renderMobileWorkspaceNavigation();
  }
  function render() {
    if (currentRole !== 'owner') return;
    q('#marketingTitle').textContent = titles[tab];
    const search = q('#marketingSearch').value.trim().toLocaleLowerCase('ru');
    const groupFilter = q('#marketingGroupFilter'), selected = groupFilter.value;
    groupFilter.innerHTML = '<option value="">Все группы</option><option value="none">Без группы</option>' + groups().filter(g=>!g.archivedAt).map(g=>`<option value="${esc(g.id)}">${esc(g.name)}</option>`).join('');
    if ([...groupFilter.options].some(o=>o.value===selected)) groupFilter.value=selected;
    groupFilter.hidden = !['customers','statistics'].includes(tab);
    q('#marketingStatusFilter').hidden = tab === 'exclusions' || tab === 'statistics';
    const archived = q('#marketingStatusFilter').value === 'archived';
    q('#marketingAdd').hidden = !['customers','groups'].includes(tab) || archived;
    q('#marketingAdd').textContent = tab === 'groups' ? 'Добавить группу' : 'Добавить клиента';
    q('#marketingHint').textContent = {customers:'Группа задаёт общую скидку. Персональная скидка заменяет групповую; пустое поле наследует скидку группы.',groups:'Изменение скидки группы применяется к следующим покупкам её клиентов. Проведённые чеки не пересчитываются.',statistics:'Покупки за всё время по текущим группам клиентов. Возвращённые чеки исключены из выручки.',exclusions:'На отмеченные товары и блюда персональные и групповые скидки не распространяются.'}[tab];
    let headers, rows;
    if (tab === 'groups') {
      headers = ['Группа','Скидка','Клиентов',''];
      rows = groups().filter(g=>Boolean(g.archivedAt)===archived && g.name.toLocaleLowerCase('ru').includes(search)).map(g=>`<tr><td>${esc(g.name)}</td><td>${g.discountPercent}%</td><td>${customers().filter(c=>c.groupId===g.id&&!c.archivedAt).length}</td><td>${archived?'Архив':actions(g.id)}</td></tr>`);
    } else if (tab === 'exclusions') {
      headers = ['Позиция','Тип','Категория','Без скидки'];
      rows = [['product',state().products||[]],['recipe',state().recipes||[]]].flatMap(([kind,items])=>items.filter(i=>i.is_active!==false && `${i.name} ${i.category}`.toLocaleLowerCase('ru').includes(search)).map(i=>`<tr><td>${esc(i.name)}</td><td>${kind==='recipe'?'Техкарта':'Товар'}</td><td>${esc(i.category||'Без категории')}</td><td><input type="checkbox" data-exclusion="${esc(i.id)}" data-kind="${kind}" aria-label="Не применять скидки: ${esc(i.name)}" ${i.noDiscount?'checked':''} ${busy?'disabled':''}></td></tr>`));
    } else {
      headers = ['Клиент','Телефон','Группа','Скидка','Покупок','Сумма покупок',''];
      rows = customers().filter(c=>(tab==='statistics' || Boolean(c.archivedAt) === archived) && `${c.name} ${c.phone}`.toLocaleLowerCase('ru').includes(search) && (!groupFilter.value || (groupFilter.value==='none' ? !c.groupId : c.groupId===groupFilter.value))).map(c=>{
        const sales = (state().sales||[]).filter(s=>s.customerId===c.id&&!s.refundedAt&&s.paymentMethod!=='external');
        return `<tr><td>${esc(c.name)}</td><td>${esc(c.phone)}</td><td>${esc(groupName(c.groupId))}</td><td>${effective(c)}%</td><td>${sales.length}</td><td>${money(sales.reduce((v,s)=>v+Number(s.total||0),0))}</td><td>${archived?'Архив':actions(c.id)}</td></tr>`;
      });
    }
    q('#marketingHead').innerHTML = '<tr>'+headers.map(h=>'<th>'+h+'</th>').join('')+'</tr>';
    q('#marketingRows').innerHTML = rows.join('') || `<tr><td colspan="${headers.length}">Ничего не найдено</td></tr>`;
  }
  function actions(id) { return `<div class="marketing-actions"><button type="button" class="secondary-action" data-marketing-edit="${esc(id)}">Изменить</button><button type="button" class="secondary-action" data-marketing-archive="${esc(id)}">В архив</button></div>`; }
  function edit(id) {
    const isGroup = tab==='groups', row = (isGroup?groups():customers()).find(c=>c.id===id);
    editing = {kind:isGroup?'group':'customer', id:row?.id || crypto.randomUUID(), expectedRevision:row?.editRevision ?? null};
    q('#marketingDialogTitle').textContent = isGroup ? (row?'Изменить группу':'Новая группа') : (row?'Изменить клиента':'Новый клиент');
    let fields = input('name',isGroup?'Название группы':'Имя',row?.name||'','required maxlength="150"');
    if (isGroup) fields += input('discountPercent','Скидка, %',row?.discountPercent??0,'type="number" min="0" max="100" step="0.01" required');
    else {
      fields += input('phone','Телефон',row?.phone||'','type="tel" required maxlength="40"');
      fields += '<label>Группа<select name="groupId"><option value="">Без группы</option>'+groups().filter(g=>!g.archivedAt).map(g=>`<option value="${esc(g.id)}" ${row?.groupId===g.id?'selected':''}>${esc(g.name)} · ${g.discountPercent}%</option>`).join('')+'</select></label>';
      const personal = row?.personalDiscountPercent===null ? '' : row?.personalDiscountPercent ?? row?.discountPercent ?? '';
      fields += input('personalDiscountPercent','Персональная скидка, % (пусто — скидка группы)',personal,'type="number" min="0" max="100" step="0.01"');
      fields += `<label>Комментарий<textarea name="comment" maxlength="1000">${esc(row?.comment||'')}</textarea></label>`;
    }
    q('#marketingFields').innerHTML=fields; q('#marketingError').textContent=''; dialog.showModal();
  }
  q('#marketingForm').onsubmit = async e => {
    e.preventDefault(); if(busy)return;
    const data=Object.fromEntries(new FormData(e.target)), command={...editing,...data};
    if(editing.kind==='group') command.discountPercent=Number(data.discountPercent);
    else command.personalDiscountPercent=data.personalDiscountPercent===''?(data.groupId?null:0):Number(data.personalDiscountPercent);
    busy=true; [...dialog.querySelectorAll('button,input,select,textarea')].forEach(el=>el.disabled=true);
    try { const result=await runServerAction('marketing.'+editing.kind+'.upsert',command,'Сохранено'); if(result)dialog.close(); else q('#marketingError').textContent='Не удалось подтвердить сохранение. Проверьте сообщение и попробуйте снова.'; }
    finally { busy=false; [...dialog.querySelectorAll('button,input,select,textarea')].forEach(el=>el.disabled=false); render(); }
  };
  q('#marketingAdd').onclick=()=>edit();
  q('#marketingSearch').oninput=render; q('#marketingGroupFilter').onchange=render; q('#marketingStatusFilter').onchange=render;
  q('#marketingRows').onclick=async e=>{
    if(busy)return;
    const editButton=e.target.closest('[data-marketing-edit]'); if(editButton){edit(editButton.dataset.marketingEdit);return;}
    const archive=e.target.closest('[data-marketing-archive]');
    if(archive){const kind=tab==='groups'?'group':'customer', row=(kind==='group'?groups():customers()).find(c=>c.id===archive.dataset.marketingArchive);if(!confirm(`Переместить «${row.name}» в архив? История покупок сохранится.`))return;busy=true;archive.disabled=true;try{await runServerAction('marketing.'+kind+'.archive',{id:row.id,expectedRevision:row.editRevision??null},'Перемещено в архив');}finally{busy=false;render();}}
  };
  q('#marketingRows').onchange=async e=>{
    const checkbox=e.target.closest('[data-exclusion]');if(!checkbox||busy)return;
    const kind=checkbox.dataset.kind,row=state()[kind+'s'].find(i=>String(i.id)===checkbox.dataset.exclusion);
    busy=true;checkbox.disabled=true;
    try{await runServerAction('marketing.exclusion.update',{kind,id:row.id,noDiscount:checkbox.checked,expectedRevision:row.editRevision??null},'Исключения обновлены');}finally{busy=false;render();}
  };
  q('#marketingNavSubmenu').onclick=e=>{const button=e.target.closest('[data-marketing-tab]');if(!button)return;switchView('marketing');open(button.dataset.marketingTab);};
  window.OimoMarketing={open,render};
  if(currentRole==='owner' && startupWorkspaceRoute.startsWith('marketing')) {switchView('marketing');open(startupWorkspaceRoute.split('/')[1]);}
})();
