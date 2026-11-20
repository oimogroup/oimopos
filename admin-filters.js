/* Shared, client-side list filters. No extra API polling or changes to records. */
window.AdminFilters = (() => {
  const groups = new Map();
  let account = '';
  const text = value => String(value ?? '').toLocaleLowerCase('ru').trim();
  const contextOf = (group, context) => String(context ?? group.context?.() ?? 'default');
  const keyOf = (group, context) => `oimo-list-filters-v1:${account}:${group.scope}:${contextOf(group, context)}`;
  function values(group, context) {
    const key = keyOf(group, context);
    if (!group.saved.has(key)) {
      let saved = {};
      try { saved = JSON.parse(sessionStorage.getItem(key) || '{}'); } catch (_) {}
      group.saved.set(key, saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : {});
    }
    return group.saved.get(key);
  }
  function matchesFields(fields, selected, row, context) {
    return fields.every(field => {
      if (field.enabled && !field.enabled(context)) return true;
      const value = selected[field.key];
      if (value == null || value === '') return true;
      if (field.test) return field.test(value, row);
      const actual = field.get ? field.get(row) : row[field.key];
      if (field.type === 'number') {
        const expected = Number(String(value).replace(',', '.'));
        if (!Number.isFinite(expected) || actual == null || !Number.isFinite(Number(actual))) return false;
        return field.compare === 'max' ? Number(actual) <= expected : Number(actual) >= expected;
      }
      if (field.type === 'date') {
        const date = String(actual || '').slice(0, 10);
        return Boolean(date) && (field.compare === 'max' ? date <= value : date >= value);
      }
      return field.type === 'text' ? text(actual).includes(text(value)) : String(actual ?? '') === String(value);
    });
  }
  function matches(scope, row, context) {
    const group = groups.get(scope);
    return !group || matchesFields(group.fields, values(group, context), row, contextOf(group,context));
  }
  function optionsFor(field) {
    return typeof field.options === 'function' ? field.options() : field.options || [];
  }
  function sync(scope, context) {
    const group = groups.get(scope);
    if (!group) return;
    const selected = values(group, context);
    const contextKey = keyOf(group, context);
    if (group.lastContext !== contextKey) {
      group.lastContext = contextKey;
      group.pendingControls = new Set(Object.keys(selected._controls || {}));
    }
    for (const {id} of group.controls) {
      const input = document.getElementById(id);
      const saved = selected._controls?.[id];
      if (input && group.pendingControls.has(id) && (input.tagName !== 'SELECT' || [...input.options].some(option => option.value === saved))) {
        input.value = saved; group.pendingControls.delete(id);
      }
    }
    for (const field of group.fields) {
      const input = group.inputs.get(field.key);
      const enabled = !field.enabled || field.enabled(contextOf(group,context));
      input.parentElement.hidden = !enabled;
      input.disabled = !enabled;
      if (field.options) {
        const entries = optionsFor(field).map(value => Array.isArray(value) ? value : [value, value]);
        const signature = JSON.stringify(entries);
        if (input.dataset.options !== signature || ![...input.options].some(option => option.value === String(selected[field.key] || ''))) {
          input.replaceChildren(new Option('Все', ''), ...entries.map(([id, label]) => new Option(label, id)));
          const saved = String(selected[field.key] || '');
          if (saved && !entries.some(([id]) => String(id) === saved)) input.add(new Option(`${saved} (нет в списке)`, saved));
          input.dataset.options = signature;
        }
      }
      input.value = selected[field.key] ?? '';
    }
    const count = group.fields.filter(field => (!field.enabled || field.enabled(contextOf(group,context))) && selected[field.key] !== '' && selected[field.key] != null).length;
    group.summary.textContent = count ? `+ Фильтр · ${count}` : '+ Фильтр';
    group.reset.hidden = !count && !group.controls.some(({id, initial}) => {
      const input = document.getElementById(id);
      return input && input.value !== initial;
    });
  }
  function reset(scope) {
    const group = groups.get(scope);
    if (!group) return;
    const selected = values(group);
    for (const key of Object.keys(selected)) delete selected[key];
    group.pendingControls?.clear();
    try { sessionStorage.removeItem(keyOf(group)); } catch (_) {}
    for (const {id, initial} of group.controls) {
      const input = document.getElementById(id);
      if (input) input.value = initial;
    }
    sync(scope);
    group.render();
  }
  function register(config) {
    if (groups.has(config.scope)) return;
    let toolbar = document.querySelector(config.toolbar);
    if (toolbar?.matches('input, select')) toolbar = toolbar.closest('.table-toolbar');
    if (!toolbar && config.before) {
      const selected = document.querySelector(config.before);
      const anchor = selected?.closest('.table-scroll') || selected?.closest('table') || selected;
      if (anchor) { toolbar = document.createElement('div'); toolbar.className = 'table-toolbar'; anchor.before(toolbar); }
    }
    if (!toolbar) return;
    const group = {...config, fields: config.fields || [], saved: new Map(), inputs: new Map(), controls: []};
    const wrapper = document.createElement('div');
    wrapper.className = 'list-filter-tools'; wrapper.dataset.filterScope = config.scope;
    const details = document.createElement('details'); details.className = 'list-filter-disclosure';
    const summary = document.createElement('summary'); group.summary = summary; details.append(summary);
    const panel = document.createElement('div'); panel.className = 'list-filter-panel';
    if (config.legacy) {
      const legacy = document.querySelector(config.legacy);
      const fields = legacy?.querySelector('.ux-filter-fields');
      if (fields) { panel.append(fields); legacy.style.display = 'none'; fields.querySelector('#resetIngredientFilters').style.display = 'none'; }
    }
    for (const field of group.fields) {
      const label = document.createElement('label'); label.textContent = field.label;
      const input = document.createElement(field.options ? 'select' : 'input');
      input.id = `list-filter-${config.scope}-${field.key}`;
      input.dataset.filterKey = field.key;
      input.setAttribute('aria-label', field.label);
      if (!field.options) { input.type = field.type === 'date' ? 'date' : field.type === 'number' ? 'number' : 'search'; if (field.type === 'number') input.step = 'any'; }
      input.addEventListener(field.options ? 'change' : 'input', () => {
        const selected = values(group); selected[field.key] = input.value;
        try { sessionStorage.setItem(keyOf(group), JSON.stringify(selected)); } catch (_) {}
        sync(config.scope); config.render();
      });
      group.inputs.set(field.key, input); label.append(input); panel.append(label);
    }
    details.append(panel); details.hidden = !group.fields.length;
    const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary-action'; button.textContent = 'Сбросить';
    button.addEventListener('click', () => reset(config.scope)); group.reset = button;
    const result = document.createElement('span'); result.className = 'list-filter-result'; result.setAttribute('role', 'status'); group.result = result;
    for (const control of config.controls || []) {
      const {id, initial = ''} = typeof control === 'string' ? {id: control} : control;
      group.controls.push({id, initial});
      const input = document.getElementById(id);
      input?.addEventListener(input.tagName === 'SELECT' ? 'change' : 'input', () => {
        const selected = values(group); selected._controls ||= {}; selected._controls[id] = input.value;
        group.pendingControls?.delete(id);
        try { sessionStorage.setItem(keyOf(group), JSON.stringify(selected)); } catch (_) {}
        sync(config.scope);
      });
    }
    wrapper.append(details, button, result); toolbar.append(wrapper); groups.set(config.scope, group); sync(config.scope);
    if (config.hideReset) {
      const original = document.getElementById(config.hideReset);
      if (original) original.style.display = 'none';
    }
  }
  function result(scope, count, total) {
    const group = groups.get(scope);
    if (!group) return;
    sync(scope);
    group.result.textContent = `Показано ${count} из ${total}`;
    if (!count && group.table) {
      const body = document.querySelector(group.table);
      if (body && !body.children.length) {
        const row = body.insertRow(), cell = row.insertCell();
        row.className = 'table-empty'; cell.colSpan = group.columns || 10;
        cell.textContent = 'Ничего не найдено. Измените условия или сбросьте фильтры.';
      } else if (body && total > 0 && body.children.length === 1 && body.firstElementChild.classList.contains('table-empty')) {
        body.firstElementChild.cells[0].textContent = 'Ничего не найдено. Измените условия или сбросьте фильтры.';
      }
    }
  }
  document.addEventListener('click', event => {
    for (const group of groups.values()) {
      const details = group.summary.parentElement;
      if (details.open && !details.contains(event.target)) details.open = false;
    }
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') for (const group of groups.values()) group.summary.parentElement.open = false;
  });
  return {register, sync, reset, matches, result, matchesFields,
    setAccount: value => { account = String(value); },
    active: scope => { const group = groups.get(scope); return group ? group.fields.some(field => (!field.enabled || field.enabled(contextOf(group))) && values(group)[field.key] !== '' && values(group)[field.key] != null) : false; }};
})();
