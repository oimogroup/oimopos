(() => {
  const el = id => document.getElementById(id);
  let rows = [];
  let generation=0, uploads=0;
  const read = () => [...el('productVariantRows').children].map((row, i) => ({...rows[i], id: rows[i]?.id || '', name: row.querySelector('[data-variant-name]').value.trim(), portionSize: row.querySelector('[data-variant-size]').value === '' ? null : Number(row.querySelector('[data-variant-size]').value), portionUnit: row.querySelector('[data-variant-unit]').value, barcode: row.querySelector('[data-variant-barcode]').value.trim(), price: Number(row.querySelector('[data-variant-price]').value), markup: Number(row.querySelector('[data-variant-markup]').value), averageCost: rows[i]?.averageCost || 0}));
  function render() {
    el('productVariantRows').innerHTML = rows.map((row,i) => `<div class="product-variant-row"><label><span>Название</span><input data-variant-name maxlength="80" value="${escapeHtml(row.name)}" placeholder="Например, 250 мл"><span class="variant-portion-fields"><input data-variant-size type="number" min="0.001" step="any" value="${row.portionSize ?? ''}" placeholder="Объём / вес" aria-label="Объём или вес"><select data-variant-unit aria-label="Единица объёма или веса">${['мл','г','шт'].map(unit=>`<option ${unit === (row.portionUnit || 'мл') ? 'selected' : ''}>${unit}</option>`).join('')}</select></span></label><label><span>Штрихкод</span><input data-variant-barcode maxlength="64" value="${escapeHtml(row.barcode || '')}"></label><label><span>Наценка, %</span><input data-variant-markup type="number" min="-100" step="0.01" value="${row.markup || 0}"></label><label><span>Цена</span><input data-variant-price type="number" min="0.01" step="0.01" value="${row.price || 0}"></label><button class="icon-button danger-button" type="button" data-remove-variant="${i}" aria-label="Удалить модификацию" ${row.id ? 'disabled title="Сохранённая модификация имеет отдельную складскую историю"' : ''}>×</button><div class="variant-artwork">${CatalogCover.thumb({name:row.name,image:row.image ?? productPhotoDraft,color:row.color || el('productColorInput').value})}<label class="secondary-action">Фото<input type="file" accept="image/jpeg,image/png,image/webp" data-variant-photo="${i}"></label><input type="color" data-variant-color="${i}" value="${row.color || el('productColorInput').value}" aria-label="Цвет модификации"><button type="button" class="danger-button variant-reset" data-variant-clear="${i}">Удалить фото</button></div></div>`).join('');
  }
  function toggle() {
    const enabled = el('productVariantsEnabled').checked;
    el('productVariantsSection').classList.toggle('hidden', !enabled);
    el('productSinglePriceSection').classList.toggle('hidden', enabled);
    el('productBarcodeInput').closest('label').classList.toggle('hidden', enabled);
    el('productOpeningBlock').classList.toggle('hidden', enabled || Boolean(editingProductId) || serverMode);
  }
  function open(product) {
    generation++;uploads=0;
    el('productStationInput').innerHTML = '<option value="">Без цеха</option>' + stations.map(row => `<option value="${escapeHtml(row.name)}">${escapeHtml(row.name)} · ${escapeHtml(row.destination || 'Без печати')}</option>`).join('');
    el('productStationInput').value = product?.station || '';
    const hasVariants = Boolean(product?.variantName);
    el('productVariantsEnabled').checked = hasVariants;
    el('productVariantsEnabled').disabled = hasVariants;
    rows = hasVariants ? [product, ...products.filter(row => row.parentId === product.id)].map(row => ({id: row.id, image:row.image || "", color:row.color, name: row.variantName, portionSize: row.portionSize, portionUnit: row.portionUnit, price: row.price, barcode: row.barcode, markup: row.markup, averageCost: branchUnitCost(currentSession.branchId || pendingOwnerObjectScope || branches[0]?.id, row.id)})) : [{id: product?.id || '', name: '', price: product?.price || 0, barcode: product?.barcode || '', averageCost: product?.averageCost || 0}];
    if (hasVariants) el('productNameInput').value = product.groupName;
    render(); toggle();
  }
  async function save(createAnother) {
    if (!el('productVariantsEnabled').checked) return false;
    if(uploads){showToast('Дождитесь загрузки фото модификации');return true;}
    rows = read();
    const name = el('productNameInput').value.trim();
    if (!name || !rows.length || rows.some(r => !r.name || !Number.isFinite(r.price) || r.price <= 0 || !Number.isFinite(r.markup) || r.markup < -100 || (r.portionSize !== null && (!Number.isFinite(r.portionSize) || r.portionSize <= 0))) || new Set(rows.map(r=>r.name.toLocaleLowerCase('ru'))).size !== rows.length) { showToast('Укажите название товара, разные названия модификаций и их цены'); return true; }
    if (!await ensureProductCategory()) return true;
    const rootId = editingProductId || productIdFromName(name);
    const payload = {id: rootId, name, category: el('productCategoryInput').value, station: el('productStationInput').value, unit: el('productUnitInput').value, image: productPhotoDraft, color: el('productColorInput').value, weighted: el('productWeightedInput').checked, noDiscount: el('productNoDiscountInput').checked, limit: Number(el('productLimitInput').value || 0), variants: rows};
    if (serverMode) { if (!await runServerAction('product.group.upsert', payload)) return true; }
    else {
      rows.forEach((row,i) => {
        const id = i === 0 ? rootId : row.id || productIdFromName(`${name}-${row.name}`);
        let item = productById(id);
        if (!item) { item = {id, stock:0, averageCost:0}; products.push(item); }
        const {variants, ...common} = payload;
        Object.assign(item, common, row, {id, name:`${name} — ${row.name}`, groupName:name, variantName:row.name, parentId:i===0 ? null : rootId});
      });
      saveProducts(); renderAll();
    }
    el('productModal').classList.add('hidden'); switchMenuPage('products'); showToast('Товар с модификациями сохранён');
    if (createAnother === true) openProductForm();
    return true;
  }
  function mount() {
    el('productVariantsEnabled').addEventListener('change', toggle);
    el('addProductVariant').addEventListener('click', () => { generation++;uploads=0;rows = read(); if (rows.length >= 50) return showToast('Не больше 50 модификаций'); rows.push({name:'', price:0}); render(); });
    el('productVariantRows').addEventListener('click', e => { const button = e.target.closest('[data-remove-variant]'); if (!button || button.disabled) return; generation++;uploads=0;rows = read(); rows.splice(Number(button.dataset.removeVariant),1); render(); });
    el('productVariantRows').addEventListener('change', async e=>{
      const index=e.target.dataset.variantPhoto;if(index===undefined)return;
      const file=e.target.files[0];if(!file)return;
      rows=read();const row=rows[Number(index)],current= generation,token=(row._uploadToken || 0)+1;row._uploadToken=token;uploads++;
      try {const image=await CatalogCover.load(file);if(current!==generation)return;if(rows[Number(index)]?._uploadToken!==token)return;rows=read();rows[Number(index)].image=image;render();}
      catch(error){showToast(error.message || 'Не удалось загрузить фото');}
      finally {if(current===generation)uploads--;}
    });
    el('productVariantRows').addEventListener('click',e=>{const b=e.target.closest('[data-variant-clear]');if(!b)return;generation++;uploads=0;rows=read();rows[Number(b.dataset.variantClear)].image='';render();});
    el('productVariantRows').addEventListener('input', e => {
      if(e.target.dataset.variantColor!==undefined){rows=read();rows[Number(e.target.dataset.variantColor)].color=e.target.value;const preview=e.target.closest('.variant-artwork').querySelector('.catalog-thumb');preview.style.background=e.target.value;return;}
      const row = e.target.closest('.product-variant-row'); if (!row) return;
      const index = [...row.parentNode.children].indexOf(row), cost = rows[index]?.averageCost || 0;
      if (cost <= 0) return;
      const price = row.querySelector('[data-variant-price]'), markup = row.querySelector('[data-variant-markup]');
      if (e.target === markup) price.value = Math.round(cost*(1+Number(markup.value)/100)*100)/100;
      if (e.target === price) markup.value = Math.round((Number(price.value)/cost-1)*10000)/100;
    });
  }
  window.ProductVariants = {open,save,mount};
})();
