(() => {
  const el = id => document.getElementById(id);
  let rows = [], active = 0;
  function capture() {
    syncRecipeDraftFromEditor();
    return {...rows[active], name:el('recipeVariantName').value.trim(), portionSize:el('recipeVariantSize').value === '' ? null : Number(el('recipeVariantSize').value), portionUnit:el('recipeVariantUnit').value, price:Number(el('recipePriceInput').value || 0), yield:Number(el('recipeYieldInput').value || 0), components:structuredClone(recipeDraftComponents), ...CatalogCover.read('recipe')};
  }
  function options() {
    el('recipeVariantSelect').innerHTML = rows.map((r,i)=>`<option value="${i}">${escapeHtml(r.name || `Модификация ${i+1}`)}</option>`).join('');
    el('recipeVariantSelect').value = String(active);
    el('removeRecipeVariant').disabled = rows.length < 2 || Boolean(rows[active].id);
  }
  function load() {
    const row=rows[active];
    el('recipeVariantName').value=row.name || '';
    el('recipeVariantSize').value=row.portionSize ?? '';
    el('recipeVariantUnit').value=row.portionUnit || 'мл';
    el('recipePriceInput').value=row.price || 0;
    el('recipeYieldInput').value=row.yield || 0;
    el('recipeYieldInput').dataset.auto=row.yield ? 'false' : 'true';
    recipeDraftComponents=structuredClone(row.components || []);
    CatalogCover.open('recipe',row);
    renderRecipeComponentsEditor();options();
  }
  function toggle() {el('recipeVariantsSection').classList.toggle('hidden',!el('recipeVariantsEnabled').checked);}
  function open(recipe) {
    const grouped=Boolean(recipe?.variantName);
    rows=grouped ? [recipe,...recipes.filter(r=>String(r.parentId)===String(recipe.id))].map(r=>({...structuredClone(r),name:r.variantName})) : [{...structuredClone(recipe || {}),id:recipe?.id || null,name:'',price:Number(el('recipePriceInput').value || 0),yield:Number(el('recipeYieldInput').value || 0),components:structuredClone(recipeDraftComponents),...CatalogCover.read('recipe')}];
    active=0;
    el('recipeVariantsEnabled').checked=grouped;
    el('recipeVariantsEnabled').disabled=grouped;
    if(grouped)el('recipeNameInput').value=recipe.groupName;
    if(grouped)load();else{el('recipeVariantName').value='';el('recipeVariantSize').value='';el('recipeVariantUnit').value='мл';options();}
    toggle();
  }
  async function save() {
    if(!el('recipeVariantsEnabled').checked)return false;
    rows[active]=capture();
    rows=rows.map(r=>({...r,name:r.name || (r.portionSize ? `${r.portionSize} ${r.portionUnit}` : '')}));
    const modifierData=window.CatalogModifiers.read();
    if(!modifierData)return true;
    const hasPaidModifier=modifierData.modifierSets.some(group=>group.options.some(option=>option.price>0));
    const name=el('recipeNameInput').value.trim(),station=el('recipeStationInput').value;
    if(!name || !station || !rows.length || rows.some(r=>!r.name || !Number.isFinite(r.price) || r.price<0 || !Number.isFinite(r.yield) || r.yield<=0 || !r.components.length || (r.portionSize!=null && (!Number.isFinite(r.portionSize) || r.portionSize<=0))) || (!rows.some(r=>r.price>0) && !hasPaidModifier) || new Set(rows.map(r=>r.name.toLocaleLowerCase('ru'))).size!==rows.length){showToast('Укажите разные названия модификаций, выход, состав и цену блюда или платного варианта');return true;}
    const payload={...modifierData,id:editingRecipeId,name,category:el('recipeCategoryInput').value,station,variants:rows.map(r=>({...r,modifierSetIds:modifierData.modifierSetIds,portionSize:r.portionSize ?? null,portionUnit:r.portionUnit || 'мл'}))};
    let response;
    if(serverMode){response=await runServerAction('recipe.group.upsert',payload);if(!response)return true;}
    else {
      let next=Math.max(100,...recipes.map(r=>Number(r.id)||0))+1;
      const rootId=editingRecipeId || next++;
      rows.forEach((row,i)=>{
        const id=i===0 ? rootId : row.id || next++;
        let item=recipes.find(r=>r.id===id);if(!item){item={id};recipes.push(item);}
        Object.assign(item,row,{id,name:`${name} — ${row.name}`,category:payload.category,station,groupName:name,variantName:row.name,parentId:i===0 ? null : rootId,modifierSetIds:modifierData.modifierSetIds});
      });saveRecipes();renderAll();
      window.CatalogModifiers.saveLocal(modifierData);
    }
    el('recipeModal').classList.add('hidden');switchMenuPage('recipes');if(!response?.refreshFailed)showToast('Техкарта с модификациями сохранена');return true;
  }
  function mount() {
    el('recipeVariantsEnabled').addEventListener('change',toggle);
    el('recipeVariantSelect').addEventListener('change',e=>{
      if(!CatalogCover.ready('recipe')){e.target.value=String(active);return;}
      rows[active]=capture();active=Number(e.target.value);load();
    });
    el('addRecipeVariant').addEventListener('click',()=>{
      if(!CatalogCover.ready('recipe'))return;
      if(rows.length>=50)return showToast('Не больше 50 модификаций');
      rows[active]=capture();rows.push({...structuredClone(rows[active]),id:null,name:'',portionSize:null});active=rows.length-1;load();el('recipeVariantName').focus();
    });
    el('removeRecipeVariant').addEventListener('click',()=>{
      if(rows.length<2 || rows[active].id || !CatalogCover.ready('recipe'))return;
      rows.splice(active,1);active=Math.max(0,active-1);load();
    });
    el('recipeVariantName').addEventListener('input',()=>{rows[active].name=el('recipeVariantName').value;options();});
  }
  window.RecipeVariants={open,save,mount};
})();
