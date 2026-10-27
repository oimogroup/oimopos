(function (global) {
  let expanded = null, pendingImport = [], hiddenColumns = new Set(["category", "unit", "usage"]);
  const columns = { category: "Категория", unit: "Ед. измерения", cost: "Себестоимость", stock: "Остаток", usage: "В составе" };
  const el = id => document.getElementById(id);
  const links = item => [
    ...recipes.filter(row => (row.components || []).some(c => String(c.ingredientId) === String(item.id))).map(row => ({ ...row, kind: "recipe", label: "Техкарта" })),
    ...preparations.filter(row => (row.components || []).some(c => String(c.ingredientId) === String(item.id))).map(row => ({ ...row, kind: "preparation", label: "Полуфабрикат" }))
  ];
  function choices(select, entries, first = "") {
    const previous = select.value;
    select.innerHTML = first + entries.map(([id, name]) => `<option value="${escapeHtml(id)}">${escapeHtml(name)}</option>`).join("");
    if (entries.some(([id]) => String(id) === previous)) select.value = previous;
  }
  function rows() {
    const query = el("ingredientSearch").value.trim().toLocaleLowerCase("ru");
    const branch = el("ingredientBranchFilter").value;
    const category = el("ingredientCategoryFilter").value;
    const unit = el("ingredientUnitFilter").value;
    const stock = el("ingredientStockFilter").value;
    const usage = el("ingredientUsageFilter").value;
    const result = ingredients.map(item => ({ item, stock: branchStock(branch, item.id), cost: branchUnitCost(branch, item.id), links: links(item) })).filter(row => {
      const item = row.item;
      return (!query || [item.name, item.id, item.barcode].some(value => String(value || "").toLocaleLowerCase("ru").includes(query))) && (!category || (item.category || "Без категории") === category) && (!unit || item.unit === unit) && (!stock || (stock === "positive" ? row.stock > 0 : stock === "zero" ? row.stock === 0 : row.stock < Number(item.limit || 0))) && (!usage || (usage === "used" ? row.links.length > 0 : !row.links.length));
    });
    const sort = el("ingredientSort").value, key = sort.split("-")[0], direction = sort.endsWith("-desc") ? -1 : 1;
    return result.sort((a, b) => direction * (key === "name" ? a.item.name.localeCompare(b.item.name, "ru", { numeric: true }) : a[key] - b[key]) || String(a.item.id).localeCompare(String(b.item.id)));
  }
  function applyColumns() {
    document.querySelectorAll("[data-ingredient-column]").forEach(cell => cell.classList.toggle("hidden", hiddenColumns.has(cell.dataset.ingredientColumn)));
  }
  function render() {
    const branchSelect = el("ingredientBranchFilter"), hadBranch = branchSelect.value;
    choices(branchSelect, branches.filter(b => currentRole === "owner" || b.id === currentSession.branchId).map(b => [b.id, `Склад · ${b.name}`]));
    if (!hadBranch && [...branchSelect.options].some(o => o.value === currentSession.branchId)) branchSelect.value = currentSession.branchId;
    choices(el("ingredientCategoryFilter"), [...new Set(ingredients.map(i => i.category || "Без категории"))].sort((a,b) => a.localeCompare(b,"ru")).map(c => [c,c]), '<option value="">Все категории</option>');
    const visible = rows();
    el("ingredientCount").textContent = ingredients.length;
    el("ingredientFilteredCount").textContent = `· показано ${visible.length}`;
    el("ingredientsTable").innerHTML = visible.length ? visible.map(row => {
      const { item, stock, cost } = row, id = escapeHtml(item.id);
      const main = `<tr><td><div class="dish-cell">${CatalogCover.thumb(item)}<div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(CatalogUnits.label(item.unit))}${item.category ? ` · ${escapeHtml(item.category)}` : ""}</small></div></div></td><td data-ingredient-column="category">${escapeHtml(item.category || "Без категории")}</td><td data-ingredient-column="unit">${escapeHtml(CatalogUnits.label(item.unit))}</td><td data-ingredient-column="cost"><strong>${money(item.unit === "шт" ? cost : cost/10)} / ${item.unit === "шт" ? "шт" : `100 ${escapeHtml(CatalogUnits.label(item.unit))}`}</strong></td><td data-ingredient-column="stock">${decimal(CatalogUnits.quantity(stock,item.unit), 3)} ${escapeHtml(CatalogUnits.label(item.unit))}${stock < Number(item.limit || 0) ? '<small class="negative">Ниже лимита</small>' : ""}</td><td data-ingredient-column="usage">${row.links.filter(r => r.kind === "recipe").length} тех. карт · ${row.links.filter(r => r.kind === "preparation").length} п/ф</td><td><div class="ingredient-row-actions catalog-row-actions"><button class="poster-action secondary-action" data-ingredient-edit="${id}" type="button">Изменить</button><button class="poster-action secondary-action" data-ingredient-details="${id}" aria-expanded="${expanded === String(item.id)}" type="button">Детали</button><button class="icon-button danger-button ingredient-delete-action" type="button" data-ingredient-delete="${id}" title="Удалить ингредиент" aria-label="Удалить ингредиент ${escapeHtml(item.name)}"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/></svg></button></div></td></tr>`;
      return main + (expanded === String(item.id) ? `<tr class="ingredient-usage-row"><td colspan="7"><strong>В составе: ${escapeHtml(item.name)}</strong>${row.links.length ? `<ul>${row.links.map(link => `<li><span>${link.label}</span><button type="button" data-ingredient-link-kind="${link.kind}" data-ingredient-link-id="${escapeHtml(link.id)}">${escapeHtml(link.name)}</button></li>`).join("")}</ul>` : '<p>Не используется в техкартах и полуфабрикатах.</p>'}</td></tr>` : "");
    }).join("") : '<tr class="table-empty"><td colspan="7">Ингредиенты не найдены. Измените поиск или сбросьте фильтры.</td></tr>';
    applyColumns();
  }
  function csvText() {
    const escapeCell = value => `"${String(value ?? "").replace(/^[=+@-]/, "'$&").replaceAll('"', '""')}"`;
    return '\ufeff' + [["Название", "Категория", "Ед. измерения", "Штрихкод", "Лимит остатка", "Себестоимость", "Потери варки", "Потери жарки", "Потери выпекания", "Потери очистки", "Масса штуки г"], ...rows().map(({item,cost}) => [item.name, item.category, CatalogUnits.label(item.unit), item.barcode || "", CatalogUnits.quantity(item.limit,item.unit), CatalogUnits.price(cost,item.unit), item.losses?.boil || 0, item.losses?.fry || 0, item.losses?.bake || 0, item.losses?.clean || 0, item.pieceWeightGrams || ""])].map(row => row.map(escapeCell).join(";")).join("\r\n");
  }
  function parseCsv(text) {
    text = text.replace(/^\ufeff/, "");
    const delimiter = text.slice(0, text.indexOf("\n") === -1 ? text.length : text.indexOf("\n")).includes(";") ? ";" : ",";
    const data = []; let row = [], cell = "", quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === '"') { if (quoted && text[i + 1] === '"') { cell += '"'; i++; } else quoted = !quoted; }
      else if (!quoted && c === delimiter) { row.push(cell); cell = ""; }
      else if (!quoted && (c === "\n" || c === "\r")) { if (c === "\r" && text[i + 1] === "\n") i++; row.push(cell); if (row.some(x => x.trim())) data.push(row); row = []; cell = ""; }
      else cell += c;
    }
    if (quoted) throw new Error("В CSV не закрыты кавычки");
    row.push(cell); if (row.some(x => x.trim())) data.push(row);
    const headers = data.shift()?.map(x => x.trim());
    if (!headers || !["Название", "Категория", "Ед. измерения"].every(h => headers.includes(h))) throw new Error("Нужны колонки: Название, Категория, Ед. измерения. Используйте файл экспорта как образец.");
    if (!data.length || data.length > 500) throw new Error("В файле должно быть от 1 до 500 ингредиентов");
    const names = new Set(ingredients.map(item => item.name.trim().toLocaleLowerCase("ru")));
    return data.map((values, index) => {
      const value = key => (values[headers.indexOf(key)] || "").trim();
      const item = { name: value("Название"), category: value("Категория") || "Без категории", unit: value("Ед. измерения"), barcode: value("Штрихкод"), limit: Number(value("Лимит остатка").replace(",", ".") || 0) };
      if (['г','мл'].includes(item.unit)) {item.unit = item.unit === 'г' ? 'кг' : 'л';item.limit /= 1000;}
      if (!item.name || !["кг", "л", "шт"].includes(item.unit) || !Number.isFinite(item.limit) || item.limit < 0) throw new Error(`Строка ${index + 2}: проверьте название, единицу и лимит`);
      const name = item.name.toLocaleLowerCase("ru");
      if (names.has(name)) throw new Error(`Строка ${index + 2}: ингредиент «${item.name}» уже существует или повторяется`);
      names.add(name); return item;
    });
  }
  async function importFile(file) {
    if (!file) return;
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error("Максимальный размер CSV — 2 МБ");
      pendingImport = parseCsv(await file.text());
      el("ingredientImportPreview").innerHTML = `<p>Будет добавлено: <strong>${pendingImport.length}</strong></p><ul>${pendingImport.map(item => `<li>${escapeHtml(item.name)} · ${escapeHtml(item.category)} · ${escapeHtml(item.unit)}</li>`).join("")}</ul>`;
      el("ingredientImportModal").classList.remove("hidden");
    } catch (error) { pendingImport = []; showToast(error.message); }
    el("ingredientImportFile").value = "";
  }
  function mount() {
    try { hiddenColumns = new Set(JSON.parse(sessionStorage.getItem("ashkana-ingredient-columns-v2") || '["category","unit","usage"]').filter(key => key in columns)); } catch {}
    el("ingredientColumnOptions").innerHTML = Object.entries(columns).map(([key,label]) => `<label><input type="checkbox" data-ingredient-column-toggle="${key}" ${hiddenColumns.has(key) ? "" : "checked"}>${label}</label>`).join("");
    el("ingredientColumnOptions").addEventListener("change", event => { const key = event.target.dataset.ingredientColumnToggle; if (!key) return; if (event.target.checked) hiddenColumns.delete(key); else hiddenColumns.add(key); try { sessionStorage.setItem("ashkana-ingredient-columns-v2", JSON.stringify([...hiddenColumns])); } catch {} applyColumns(); });
    for (const id of ["ingredientCategoryFilter", "ingredientUnitFilter", "ingredientBranchFilter", "ingredientStockFilter", "ingredientUsageFilter", "ingredientSort"]) el(id).addEventListener("change", render);
    el("resetIngredientFilters").addEventListener("click", () => { ["ingredientSearch", "ingredientCategoryFilter", "ingredientUnitFilter", "ingredientStockFilter", "ingredientUsageFilter"].forEach(id => { el(id).value = ""; }); el("ingredientSort").value = "name"; expanded = null; render(); });
    el("ingredientsTable").addEventListener("click", event => {
      const detail = event.target.closest("[data-ingredient-details]");
      if (detail) { expanded = expanded === detail.dataset.ingredientDetails ? null : detail.dataset.ingredientDetails; render(); }
      const remove = event.target.closest("[data-ingredient-delete]");
      if (remove) { const item = ingredientById(remove.dataset.ingredientDelete); if (item) { requestCatalogDelete("ingredient", item.id, item.name); } }
      const link = event.target.closest("[data-ingredient-link-id]");
      if (link) { if (link.dataset.ingredientLinkKind === "recipe") openRecipeForm(Number(link.dataset.ingredientLinkId)); else openPreparationForm(link.dataset.ingredientLinkId); }
    });
    el("confirmIngredientImport").addEventListener("click", async () => {
      if (!pendingImport.length) return;
      const button = el("confirmIngredientImport"); button.disabled = true;
      try {
        if (serverMode) { if (!await runServerAction("ingredient.import", { items: pendingImport })) return; }
        else { pendingImport.forEach(item => ingredients.push({ ...item, id: ingredientIdFromName(item.name), stock: 0, averageCost: 0, losses: {} })); saveIngredients(); renderAll(); }
        el("ingredientImportModal").classList.add("hidden"); showToast(`Добавлено ингредиентов: ${pendingImport.length}`); pendingImport = [];
      } finally { button.disabled = false; }
    });
  }
  global.IngredientsList = { render, mount, rows, csvText, parseCsv, importFile };
})(window);
