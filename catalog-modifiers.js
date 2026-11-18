(() => {
  const el = (id) => document.getElementById(id);
  let groups = new Map(), attached = [], sources = [], root = null, scope = "default", itemLabel = "товара";

  const id = (prefix) => `${prefix}-${crypto.randomUUID()}`;
  const copy = (value) => structuredClone(value);
  const sourceKey = (type, sourceId) => type === "none" ? "none" : `${type}:${sourceId}`;

  function sourceOptions(selected) {
    const options = ['<option value="none">Без списания со склада</option>'];
    for (const type of ["ingredient", "product"]) {
      const title = type === "ingredient" ? "Ингредиенты" : "Товары";
      const rows = sources.filter((row) => row.type === type);
      if (!rows.length) continue;
      options.push(`<optgroup label="${title}">${rows.map((row) => `<option value="${escapeHtml(sourceKey(type, row.id))}" ${sourceKey(type, row.id) === selected ? "selected" : ""}>${escapeHtml(row.name)} · ${escapeHtml(row.unit)}</option>`).join("")}</optgroup>`);
    }
    return options.join("");
  }

  function render() {
    if (!root) return;
    const attachedGroups = attached.map((groupId) => groups.get(groupId)).filter(Boolean);
    const available = [...groups.values()].filter((group) => !attached.includes(group.id));
    root.innerHTML = `<div class="modifier-set-toolbar"><button type="button" class="secondary-action" data-modifier-create>+ Новая группа</button>${available.length ? `<label><span>Добавить готовую группу</span><select data-modifier-attach><option value="">Выберите группу…</option>${available.map((group) => `<option value="${escapeHtml(group.id)}">${escapeHtml(group.name)}</option>`).join("")}</select></label>` : ""}</div>${attachedGroups.map((group) => `
      <section class="modifier-set-card" data-modifier-group="${escapeHtml(group.id)}">
        <header><label><span>Название группы</span><input data-group-name maxlength="80" value="${escapeHtml(group.name)}"></label><label><span>Выбор</span><select data-group-mode><option value="single" ${group.selectionMode === "single" ? "selected" : ""}>Один вариант</option><option value="multiple" ${group.selectionMode === "multiple" ? "selected" : ""}>Несколько вариантов</option></select></label><label class="modifier-required"><input data-group-required type="checkbox" ${group.required ? "checked" : ""}> Обязательный выбор</label>${group.selectionMode === "multiple" ? `<label class="modifier-max"><span>Максимум вариантов</span><input data-group-max type="number" min="1" max="30" step="1" value="${group.maxSelections}"></label>` : ""}<button type="button" class="danger-button" data-modifier-detach="${escapeHtml(group.id)}" title="Снять группу только с этого ${itemLabel}">Убрать из ${itemLabel}</button></header>
        <p>Группа общая: изменения сохранятся во всех блюдах и товарах, где она используется.</p>
        <div class="modifier-options">${group.options.map((option) => `<div class="modifier-option-row" data-modifier-option="${escapeHtml(option.id)}"><label><span>Название варианта</span><input data-option-name maxlength="80" value="${escapeHtml(option.name)}"></label><label><span>Списание</span><select data-option-source>${sourceOptions(sourceKey(option.sourceType, option.sourceId))}</select></label><label class="modifier-quantity"><span>Кол-во на порцию</span><div><input data-option-quantity type="number" min="0.001" step="any" value="${option.sourceType === "none" ? "" : option.quantity}" ${option.sourceType === "none" ? "disabled" : ""}><small>${escapeHtml(sources.find((row) => row.type === option.sourceType && String(row.id) === String(option.sourceId))?.unit || "")}</small></div></label><label><span>Доплата</span><div><input data-option-price type="number" min="0" step="0.01" value="${option.price}"><small>сом</small></div></label><button type="button" class="danger-button" data-modifier-option-remove="${escapeHtml(option.id)}" ${group.options.length < 2 ? "disabled" : ""}>×</button></div>`).join("")}</div>
        <button type="button" class="secondary-action" data-modifier-option-add="${escapeHtml(group.id)}">+ Добавить вариант</button>
      </section>`).join("") || '<p class="modifier-empty">Добавьте группу, например «Добавки» или «Степень прожарки».</p>'}`;
  }

  function open(item, catalog) {
    const serverMode = Boolean(catalog.serverMode);
    scope = String(catalog.scope || "default");
    itemLabel = catalog.kind === "recipe" ? "блюда" : "товара";
    let existingSets = Array.isArray(catalog.modifierSets) ? catalog.modifierSets : [];
    if (!serverMode) {
      try {
        const stored = localStorage.getItem(`oimo-modifier-sets-v1-${scope}`);
        if (stored) existingSets = JSON.parse(stored);
      } catch {
        showToast("Не удалось прочитать сохранённые группы модификаторов");
      }
    }
    groups = new Map(existingSets.map((group) => [String(group.id), copy(group)]));
    attached = [...new Set((item?.modifierSetIds || []).map(String))].filter((groupId) => groups.has(groupId));
    sources = [
      ...(catalog.ingredients || []).map((row) => ({...row, type: "ingredient"})),
      ...(catalog.products || []).map((row) => ({...row, type: "product"})),
    ];
    root = el(catalog.kind === "recipe" ? "recipeModifierEditor" : "productModifierEditor");
    render();
  }

  function capture() {
    for (const groupElement of root.querySelectorAll("[data-modifier-group]")) {
      const group = groups.get(groupElement.dataset.modifierGroup);
      if (!group) continue;
      group.name = groupElement.querySelector("[data-group-name]").value.trim();
      group.selectionMode = groupElement.querySelector("[data-group-mode]").value;
      group.required = groupElement.querySelector("[data-group-required]").checked;
      const maxInput = groupElement.querySelector("[data-group-max]");
      group.maxSelections = group.selectionMode === "single" ? 1 : Number(maxInput?.value || group.maxSelections || 1);
      group.options = [...groupElement.querySelectorAll("[data-modifier-option]")].map((row) => {
        const selectedSource = row.querySelector("[data-option-source]").value;
        const separator = selectedSource.indexOf(":");
        const type = separator < 0 ? selectedSource : selectedSource.slice(0, separator);
        const sourceId = separator < 0 ? "" : selectedSource.slice(separator + 1);
        return {
          id: row.dataset.modifierOption,
          name: row.querySelector("[data-option-name]").value.trim(),
          sourceType: type,
          sourceId: type === "none" ? "" : sourceId,
          quantity: type === "none" ? 0 : Number(row.querySelector("[data-option-quantity]").value),
          price: Number(row.querySelector("[data-option-price]").value),
        };
      });
    }
  }

  function read() {
    capture();
    const modifierSets = attached.map((groupId) => groups.get(groupId)).filter(Boolean).map(copy);
    for (const group of modifierSets) {
      const names = group.options.map((option) => option.name.toLocaleLowerCase("ru"));
      if (!group.name || !group.options.length || group.options.some((option) => !option.name || !Number.isFinite(option.price) || option.price < 0 || (option.sourceType !== "none" && (!option.sourceId || !Number.isFinite(option.quantity) || option.quantity <= 0))) || new Set(names).size !== names.length || (group.selectionMode === "multiple" && (!Number.isInteger(group.maxSelections) || group.maxSelections < 1 || group.maxSelections > 30))) {
        showToast("Проверьте название группы, варианты, количество списания и доплаты");
        return null;
      }
    }
    return {modifierSetIds: modifierSets.map((group) => group.id), modifierSets};
  }

  function saveLocal(data) {
    const merged = new Map([...groups].map(([key, value]) => [key, copy(value)]));
    data.modifierSets.forEach((group) => merged.set(group.id, copy(group)));
    localStorage.setItem(`oimo-modifier-sets-v1-${scope}`, JSON.stringify([...merged.values()]));
  }

  function usesSource(type, sourceId) {
    let stored = [];
    try {
      stored = JSON.parse(localStorage.getItem(`oimo-modifier-sets-v1-${scope}`) || "[]");
    } catch {
      showToast("Не удалось проверить источники списания модификаторов");
      return true;
    }
    return [...groups.values(), ...(Array.isArray(stored) ? stored : [])].some(group =>
      group.options?.some(option => option.sourceType === type && String(option.sourceId) === String(sourceId))
    );
  }

  function mount() {
    document.addEventListener("click", (event) => {
      if (!root?.contains(event.target)) return;
      const create = event.target.closest("[data-modifier-create]");
      if (create) {
        const group = {id: id("modifier-set"), name: "", selectionMode: "single", required: true, maxSelections: 1, options: [{id: id("modifier"), name: "", sourceType: "none", sourceId: "", quantity: 0, price: 0}]};
        groups.set(group.id, group); attached.push(group.id); render(); return;
      }
      const detach = event.target.closest("[data-modifier-detach]");
      if (detach) { attached = attached.filter((groupId) => groupId !== detach.dataset.modifierDetach); render(); return; }
      const add = event.target.closest("[data-modifier-option-add]");
      if (add) {
        capture();
        groups.get(add.dataset.modifierOptionAdd).options.push({id: id("modifier"), name: "", sourceType: "none", sourceId: "", quantity: 0, price: 0});
        render(); return;
      }
      const remove = event.target.closest("[data-modifier-option-remove]");
      if (remove) {
        capture();
        for (const groupId of attached) {
          const group = groups.get(groupId);
          if (group.options.length > 1) group.options = group.options.filter((option) => option.id !== remove.dataset.modifierOptionRemove);
        }
        render();
      }
    });
    document.addEventListener("change", (event) => {
      if (!root?.contains(event.target)) return;
      if (event.target.matches("[data-modifier-attach]")) {
        capture();
        const groupId = event.target.value;
        if (groupId && !attached.includes(groupId)) attached.push(groupId);
        render(); return;
      }
      if (event.target.matches("[data-group-mode]")) {
        capture(); render(); return;
      }
      if (event.target.matches("[data-option-source]")) {
        capture(); render();
      }
    });
  }

  window.CatalogModifiers = {open, read, saveLocal, usesSource, mount};
})();
