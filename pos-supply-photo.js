/* Photo attachments and reviewed invoice drafts. Stock changes only in supply.create. */
(function () {
  let state = null, busy = false, generation = 0;
  const q = id => document.getElementById(id);
  const path = id => `/api/v1/pos/supplies/photos/${encodeURIComponent(id)}?client=pos`;
  const validId = id => /^(?:photo-)?[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(String(id || ''));
  const amount = value => value === '' || value == null ? null : Number(value);
  const normal = value => String(value || '').trim().toLocaleLowerCase('ru-RU').replace(/ё/g, 'е').replace(/\s+/g, ' ');
  function message(text, error = false) {
    q('posSupplyPhotoMessage').textContent = text;
    q('posSupplyPhotoMessage').classList.toggle('pos-supply-import-error', error);
  }
  function links(photo) {
    if (!validId(photo?.id)) return '';
    return `<a class="secondary-button" target="_blank" rel="noopener" href="${path(photo.id)}">Фото накладной</a><a class="secondary-button" href="${path(photo.id)}&download=true" download aria-label="Скачать фото накладной"><svg class="ui-icon" aria-hidden="true"><use href="#pos-download"/></svg></a>`;
  }
  function blocksSave() { return busy || Boolean(state?.documents?.length && state.appliedIndex == null); }
  function updateControls() {
    const locked = busy || posSupplySaving || posSupplyImportBusy || Boolean(posSupplyImportData);
    q('posSupplyPhotoButton').disabled = locked;
    q('posSupplyPhotoFile').disabled = locked;
    q('posSupplyPhotoRemove').disabled = busy || posSupplySaving;
    q('posSupplyPhotoRecognize').disabled = locked || !posSupplyContext.photoImport?.enabled || state?.appliedIndex != null;
    q('posSupplyPhotoDocument').disabled = busy || posSupplySaving;
    q('posSupplyPhotoApply').disabled = locked || !state?.documents?.length || state?.appliedIndex != null;
    if (state?.documents?.length && state.appliedIndex == null && !locked) checkDocument();
  }
  function reset() {
    generation++;
    busy = false;
    state = null;
    q('posSupplyPhotoFile').value = '';
    q('posSupplyPhotoPanel').classList.add('hidden');
    q('posSupplyPhotoImage').removeAttribute('src');
    q('posSupplyPhotoReview').classList.add('hidden');
    q('posSupplyPhotoRows').innerHTML = '';
    message('');
  }
  function render() {
    if (!state) return;
    q('posSupplyPhotoPanel').classList.remove('hidden');
    q('posSupplyPhotoName').textContent = state.fileName;
    q('posSupplyPhotoImage').src = path(state.id);
    q('posSupplyPhotoOpen').href = path(state.id);
    q('posSupplyPhotoDownload').href = path(state.id) + '&download=true';
    const enabled = Boolean(posSupplyContext.photoImport?.enabled);
    q('posSupplyPhotoSetup').textContent = enabled ? 'Проверьте распознанные позиции перед приёмкой.' : (posSupplyContext.photoImport?.reason || 'Распознавание ещё не подключено. Фото сохранится с поставкой; позиции можно заполнить вручную.');
    const review = Boolean(state.documents?.length && state.appliedIndex == null);
    q('posSupplyPhotoReview').classList.toggle('hidden', !review);
    q('posSupplyPhotoRecognize').classList.toggle('hidden', Boolean(state.documents?.length));
    if (review) renderDocument();
    updatePosSupplyImportControls();
  }
  function readDocument() {
    if (!state?.documents?.length || state.appliedIndex != null || q('posSupplyPhotoReview').classList.contains('hidden')) return;
    const doc = state.documents[state.index];
    doc.supplierId = q('posSupplyPhotoSupplier').value;
    doc.invoiceNumber = q('posSupplyPhotoInvoice').value;
    doc.receivedAt = q('posSupplyPhotoDate').value;
    doc.total = amount(q('posSupplyPhotoTotal').value);
    doc.rows.forEach((row, index) => {
      const element = q('posSupplyPhotoRows').querySelector(`[data-photo-row="${index}"]`);
      row.itemId = element.querySelector('[data-photo-item]').value;
      row.quantity = amount(element.querySelector('[data-photo-quantity]').value);
      row.price = amount(element.querySelector('[data-photo-price]').value);
      row.unit = element.querySelector('[data-photo-unit]').value;
    });
  }
  function renderDocument() {
    const doc = state.documents[state.index];
    q('posSupplyPhotoDocument').innerHTML = state.documents.map((entry, index) => `<option value="${index}" ${state.used.includes(index) ? 'disabled' : ''}>${escapeHtml(entry.invoiceNumber ? `№ ${entry.invoiceNumber}` : `Накладная ${index + 1}`)}${entry.supplierName ? ' · ' + escapeHtml(entry.supplierName) : ''}${state.used.includes(index) ? ' · Принята' : ''}</option>`).join('');
    q('posSupplyPhotoDocument').value = String(state.index);
    q('posSupplyPhotoWarnings').textContent = [...new Set([...(doc.warnings || []), ...doc.rows.flatMap(row => row.warnings || [])])].join(' ');
    q('posSupplyPhotoSupplier').innerHTML = '<option value="">Выберите поставщика…</option>' + posSupplyContext.suppliers.map(supplier => `<option value="${escapeHtml(supplier.id)}">${escapeHtml(supplier.name)}</option>`).join('');
    q('posSupplyPhotoSupplier').value = doc.supplierId || '';
    q('posSupplyPhotoInvoice').value = doc.invoiceNumber || '';
    q('posSupplyPhotoDate').value = doc.receivedAt || (doc.date ? `${doc.date}T00:00` : localDateTimeValue());
    q('posSupplyPhotoTotal').value = doc.total ?? '';
    q('posSupplyPhotoRows').innerHTML = doc.rows.map((row, index) => {
      const units = [...new Set(['', 'кг', 'г', 'л', 'мл', 'шт', row.unit || ''])];
      return `<article class="supply-photo-row" data-photo-row="${index}"><strong>${escapeHtml(row.name)}</strong><label>Позиция в Oimo<select data-photo-item>${supplyImportItemOptions(row.itemId)}</select></label><div class="supply-photo-numbers"><label>Количество<input type="number" min="0" step="any" inputmode="decimal" data-photo-quantity value="${escapeHtml(row.quantity ?? '')}"></label><label>Единица<select data-photo-unit>${units.map(unit => `<option value="${escapeHtml(unit)}" ${unit === (row.unit || '') ? 'selected' : ''}>${escapeHtml(unit || 'Выберите…')}</option>`).join('')}</select></label><label>Цена, сом<input type="number" min="0" step="any" inputmode="decimal" data-photo-price value="${escapeHtml(row.price ?? '')}"></label></div><small data-photo-row-check></small></article>`;
    }).join('');
    checkDocument();
  }
  function checkDocument() {
    readDocument();
    if (!state?.documents?.length || state.appliedIndex != null) return null;
    const doc = state.documents[state.index];
    const rows = doc.rows.map(row => row.unit ? supplyImportValues(row, row.itemId) : {error: 'Выберите единицу по накладной'});
    let invalid = rows.some(row => row.error);
    rows.forEach((item, index) => {
      const row = doc.rows[index], element = q('posSupplyPhotoRows').querySelector(`[data-photo-row="${index}"]`);
      const sum = Number(row.quantity) * Number(row.price);
      element.classList.toggle('needs-mapping', Boolean(item.error));
      element.querySelector('[data-photo-row-check]').textContent = item.error || `Сумма: ${money(sum)}${row.total != null && Math.abs(sum - Number(row.total)) > .011 ? ` · На фото распознано ${money(row.total)} — проверьте` : ''}`;
    });
    const total = supplyMoney(rows.filter(row => !row.error).reduce((sum, row) => sum + row.quantity * row.price, 0));
    const totalMissing = doc.total == null || !Number.isFinite(doc.total) || doc.total <= 0;
    const mismatch = !totalMissing && Math.abs(total - doc.total) > .011;
    const supplier = posSupplyContext.suppliers.some(s => String(s.id) === doc.supplierId);
    invalid ||= !rows.length || !supplier || !doc.receivedAt || !Number.isFinite(new Date(doc.receivedAt).getTime()) || totalMissing || mismatch;
    q('posSupplyPhotoCheck').textContent = `${rows.length} поз. · По позициям: ${money(total)}${totalMissing ? ' · Укажите итог по накладной' : mismatch ? ' · Итог не совпадает с позициями' : ''}${!supplier ? ' · Выберите поставщика' : ''}`;
    q('posSupplyPhotoApply').disabled = busy || posSupplySaving || invalid;
    return invalid ? null : {rows, doc, total};
  }
  async function upload(file) {
    if (!file || busy || posSupplySaving || posSupplyImportBusy || posSupplyImportData || !operatorCan('posSupply')) return;
    if (state) { message('Уберите прикреплённое фото перед загрузкой другого. Данные поставки сохранятся.', true); return; }
    if (!/\.(jpe?g|png|webp)$/i.test(file.name) || !file.size || file.size > 6000000) { message('Выберите фото JPG, PNG или WebP до 6 МБ.', true); return; }
    const token = ++generation, actor = activeOperator?.id, scope = supplyDraftKey();
    const current = () => generation === token && actor === activeOperator?.id && scope === supplyDraftKey() && !q('supplyDrawer').classList.contains('hidden');
    busy = true; message('Загружаем фото…'); updatePosSupplyImportControls();
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      if (!current()) return;
      const result = await window.AshkanaApi.uploadSupplyPhoto({file: btoa(binary), fileName: file.name});
      if (!current()) return;
      if (!validId(result.id)) throw new Error('Сервер не подтвердил сохранение фото');
      state = {id: result.id, fileName: result.fileName || file.name, documents: [], index: 0, used: result.usedDocumentIndexes || [], appliedIndex: null};
      render(); persistSupplyDraft(); message('Фото прикреплено.');
    } catch (error) { if (current()) message(error.message || 'Не удалось загрузить фото', true); }
    finally { if (generation === token) { busy = false; updatePosSupplyImportControls(); } }
  }
  async function recognize() {
    if (!state || busy || posSupplySaving || !operatorCan('posSupply') || !posSupplyContext.photoImport?.enabled) return;
    const token = ++generation, actor = activeOperator?.id, scope = supplyDraftKey(), id = state.id;
    const current = () => generation === token && actor === activeOperator?.id && scope === supplyDraftKey() && state?.id === id && !q('supplyDrawer').classList.contains('hidden');
    busy = true; message('Распознаём накладную…'); updatePosSupplyImportControls();
    try {
      const data = await window.AshkanaApi.recognizeSupplyPhoto(id);
      if (!current()) return;
      if (!Array.isArray(data.documents) || !data.documents.length) throw new Error('На фото не найдена накладная');
      state.documents = data.documents;
      state.used = [...new Set([...state.used, ...(data.usedDocumentIndexes || [])])];
      state.index = state.documents.findIndex((_, index) => !state.used.includes(index));
      if (state.index < 0) { state.documents = []; throw new Error('Все накладные с этого фото уже приняты. Проверьте историю поставок.'); }
      for (const doc of state.documents) {
        if (!doc.supplierId) {
          const matches = posSupplyContext.suppliers.filter(supplier => normal(supplier.name) === normal(doc.supplierName));
          doc.supplierId = matches.length === 1 ? String(matches[0].id) : '';
        }
      }
      message(data.documents.length > 1 ? 'На фото несколько накладных. Принимайте каждую отдельно.' : 'Проверьте позиции и итог по фото.');
      render(); persistSupplyDraft();
    } catch (error) { if (current()) message(error.message || 'Не удалось распознать накладную', true); }
    finally { if (generation === token) { busy = false; updatePosSupplyImportControls(); checkDocument(); } }
  }
  function apply() {
    if (busy || posSupplySaving || posSupplyImportBusy || posSupplyImportData || !operatorCan('posSupply')) return;
    const checked = checkDocument();
    if (!checked) return;
    const existing = [...q('posSupplyLines').querySelectorAll('.supply-line')].some(row => row.querySelector('[data-supply-item]').value || Number(row.querySelector('[data-supply-quantity]').value) || Number(row.querySelector('[data-supply-price]').value));
    if (existing) { message('В поставке уже есть позиции. Примите текущую поставку или уберите её позиции перед добавлением накладной.', true); return; }
    const merged = new Map();
    for (const item of checked.rows) {
      const old = merged.get(item.itemId);
      if (!old) merged.set(item.itemId, {...item});
      else { const total = old.quantity * old.price + item.quantity * item.price; old.quantity += item.quantity; old.price = total / old.quantity; }
    }
    q('posSupplySupplier').value = checked.doc.supplierId;
    q('posSupplyInvoice').value = checked.doc.invoiceNumber || '';
    q('posSupplyDate').value = checked.doc.receivedAt;
    q('posSupplyLines').innerHTML = '';
    merged.forEach(addPosSupplyLine);
    state.appliedIndex = state.index;
    render(); persistSupplyDraft();
    message('Позиции добавлены. Нажмите «Принять поставку» для зачисления на склад.');
  }
  window.SupplyPhotos = {
    reset, updateControls, blocksSave, upload, recognize, apply, links,
    isBusy: () => busy,
    snapshot: () => { readDocument(); return state; },
    payload: () => state ? {photoId: state.id, photoDocumentIndex: state.appliedIndex ?? 0} : {},
    restore(saved) { if (saved && validId(saved.id)) { state = saved; state.used ||= []; render(); checkDocument(); } },
    close() { readDocument(); generation++; busy = false; persistSupplyDraft(); updatePosSupplyImportControls(); },
    afterSaved(saved = state) {
      if (!saved?.documents?.length) return null;
      saved.used = [...new Set([...saved.used, saved.appliedIndex ?? 0])];
      saved.appliedIndex = null;
      saved.index = saved.documents.findIndex((_, index) => !saved.used.includes(index));
      return saved.index < 0 ? null : JSON.parse(JSON.stringify(saved));
    }
  };
  q('posSupplyPhotoButton').addEventListener('click', () => q('posSupplyPhotoFile').click());
  q('posSupplyPhotoFile').addEventListener('change', event => upload(event.target.files[0]));
  q('posSupplyPhotoRemove').addEventListener('click', () => { reset(); updatePosSupplyImportControls(); persistSupplyDraft(); });
  q('posSupplyPhotoRecognize').addEventListener('click', recognize);
  q('posSupplyPhotoApply').addEventListener('click', apply);
  q('posSupplyPhotoDocument').addEventListener('change', event => { readDocument(); state.index = Number(event.target.value); renderDocument(); persistSupplyDraft(); });
  q('posSupplyPhotoReview').addEventListener('input', () => { checkDocument(); persistSupplyDraft(); });
  q('posSupplyPhotoReview').addEventListener('change', event => { if (event.target.id !== 'posSupplyPhotoDocument') { checkDocument(); persistSupplyDraft(); } });
  const expand = event => {
    const select = event.target.closest('[data-photo-item]');
    if (!select || select.dataset.optionsLoaded) return;
    const selected = select.value; select.innerHTML = supplyItemOptions(selected); select.dataset.optionsLoaded = 'true';
  };
  q('posSupplyPhotoRows').addEventListener('focusin', expand);
  q('posSupplyPhotoRows').addEventListener('pointerdown', expand);
})();
