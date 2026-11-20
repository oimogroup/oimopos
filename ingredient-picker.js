(() => {
  let serial = 0;
  window.mountIngredientPickers = root => {
    root.querySelectorAll('select.component-ingredient, select.preparation-component-ingredient').forEach(select => {
      if (select.closest('.ingredient-picker')) return;
      const wrap = document.createElement('div'); wrap.className = 'ingredient-picker';
      select.before(wrap); wrap.append(select); select.hidden = true;
      const input = document.createElement('input'), list = document.createElement('div');
      list.id = `ingredient-options-${++serial}`; list.className = 'ingredient-picker-options'; list.hidden = true; list.setAttribute('role', 'listbox');
      input.type = 'text'; input.autocomplete = 'off'; input.placeholder = 'Поиск ингредиента или полуфабриката'; input.setAttribute('aria-label', 'Поиск ингредиента или полуфабриката'); input.setAttribute('role', 'combobox'); input.setAttribute('aria-autocomplete', 'list'); input.setAttribute('aria-controls', list.id); input.setAttribute('aria-expanded', 'false');
      wrap.append(input, list);
      let options = [], active = -1;
      const restore = () => { input.value = select.selectedOptions[0]?.textContent || ''; };
      const close = () => { list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); restore(); };
      const choose = option => { select.value = option.value; select.dispatchEvent(new Event('change', {bubbles:true})); close(); input.focus(); };
      const highlight = () => { [...list.children].forEach((node,i) => node.setAttribute('aria-selected', String(i === active))); if (options[active]) { input.setAttribute('aria-activedescendant', `${list.id}-${active}`); list.children[active].scrollIntoView({block:'nearest'}); } };
      const show = query => {
        options = [...select.options].filter(o => o.textContent.toLocaleLowerCase('ru').includes(query.trim().toLocaleLowerCase('ru'))); active = -1; list.replaceChildren();
        options.forEach((option,i) => { const row = document.createElement('div'); row.id = `${list.id}-${i}`; row.setAttribute('role','option'); row.textContent = option.textContent; row.addEventListener('mousedown', e => e.preventDefault()); row.addEventListener('click', () => choose(option)); list.append(row); });
        if (!options.length) { const empty = document.createElement('p'); empty.textContent = 'Компоненты не найдены'; list.append(empty); }
        list.hidden = false; input.setAttribute('aria-expanded','true'); input.removeAttribute('aria-activedescendant');
      };
      input.addEventListener('focus', () => { input.select(); });
      input.addEventListener('click', () => show(''));
      input.addEventListener('input', e => { e.stopPropagation(); show(input.value); });
      input.addEventListener('keydown', e => {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); if (list.hidden) show(''); active = Math.max(0, Math.min(options.length-1, active + (e.key === 'ArrowDown' ? 1 : -1))); highlight(); }
        if (e.key === 'Enter' && !list.hidden) { e.preventDefault(); if (options[active >= 0 ? active : 0]) choose(options[active >= 0 ? active : 0]); }
      });
      input.addEventListener('blur', close); select.addEventListener('change', restore); restore();
    });
  };
})();
