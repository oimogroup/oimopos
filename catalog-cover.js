/* Shared catalogue appearance editor. Persisted data is plain {image, color}. */
window.CatalogCover = (() => {
  const drafts = new Map();
  const safeColor = value => /^#[0-9a-f]{6}$/i.test(value || '') ? value : '#633d60';
  const safeImage = value => /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(value || '') ? value : '';
  const esc = value => String(value || '').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');
  function thumb(item, name=item?.name || '') {
    return `<span class="catalog-thumb" style="background:${safeColor(item?.color)};color:${parseInt(safeColor(item?.color).slice(1,3),16)*0.299+parseInt(safeColor(item?.color).slice(3,5),16)*0.587+parseInt(safeColor(item?.color).slice(5,7),16)*0.114>150?'#302b32':'#ffffff'}">${safeImage(item?.image) ? `<img src="${esc(item.image)}" alt="">` : `<span>${esc(name.slice(0,1))}</span>`}</span>`;
  }
  async function load(file) {
    if (!file || !['image/png','image/jpeg','image/webp'].includes(file.type) || file.size>2*1024*1024) throw new Error('Выберите JPG, PNG или WebP размером до 2 МБ');
    const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
    const img=new Image();img.src=data;await img.decode();
    const canvas=document.createElement('canvas'),scale=Math.min(1,640/Math.max(img.width,img.height));
    canvas.width=Math.max(1,Math.round(img.width*scale));canvas.height=Math.max(1,Math.round(img.height*scale));
    canvas.getContext('2d').drawImage(img,0,0,canvas.width,canvas.height);
    return canvas.toDataURL('image/png');
  }
  function open(prefix, item={}, externalColorId='') {
    const modal=document.getElementById(prefix+'Modal');
    let root=document.getElementById(prefix+'CoverEditor');
    if (!root) {root=document.createElement('div');root.id=prefix+'CoverEditor';root.className='catalog-cover-editor';modal.querySelector('.catalog-form-section').append(root);}
    if (['ingredient','preparation','recipe'].includes(prefix) && !root.closest('details')) {
      const details=document.createElement('details');details.className='catalog-disclosure catalog-appearance';
      const summary=document.createElement('summary');summary.textContent='Фото и цвет';
      root.replaceWith(details);details.append(summary,root);
    }
    drafts.get(prefix)?.controller.abort();
    const controller=new AbortController();
    const draft={controller,image:safeImage(item?.image),color:safeColor(item?.color),busy:false,token:0};drafts.set(prefix,draft);
    root.innerHTML=`<div data-cover-preview></div><div class="catalog-cover-actions"><label class="secondary-action">Загрузить фото<input data-cover-file type="file" accept="image/jpeg,image/png,image/webp"></label><small>JPG, PNG, WebP · до 2 МБ</small><button type="button" data-cover-remove class="danger-button">Удалить фото</button><small data-cover-status role="status"></small></div>${externalColorId?'':`<label class="catalog-color-label">Цвет<input data-cover-color type="color" value="${draft.color}"></label>`}`;
    const color=externalColorId?document.getElementById(externalColorId):root.querySelector('[data-cover-color]');
    const name=document.getElementById(prefix+'NameInput');
    const render=()=>{draft.color=safeColor(color.value);root.querySelector('[data-cover-preview]').innerHTML=thumb(draft,name.value);root.querySelector('[data-cover-remove]').hidden=!draft.image;};
    color.addEventListener('input',render,{signal:controller.signal});
    if(externalColorId)document.getElementById(externalColorId.replace('Input','Text'))?.addEventListener('input',render,{signal:controller.signal});name.addEventListener('input',render,{signal:controller.signal});
    root.querySelector('[data-cover-remove]').onclick=()=>{draft.token++;draft.image='';draft.busy=false;root.querySelector('[data-cover-file]').value='';root.querySelector('[data-cover-status]').textContent='';render();};
    root.querySelector('[data-cover-file]').onchange=async event=>{
      const file=event.target.files[0];if(!file)return;
      const token=++draft.token;draft.busy=true;root.querySelector('[data-cover-status]').textContent='Загрузка…';
      try {const image=await load(file);if(drafts.get(prefix)!==draft||token!==draft.token)return;draft.image=image;render();}
      catch(error){if(drafts.get(prefix)===draft&&token===draft.token)showToast(error.message || 'Не удалось открыть изображение');}
      finally {if(drafts.get(prefix)===draft&&token===draft.token){draft.busy=false;root.querySelector('[data-cover-status]').textContent='';}}
    };
    draft.read=()=>({image:draft.image,color:safeColor(color.value)});render();
  }
  return {open,load,thumb,safeColor,safeImage,read:prefix=>drafts.get(prefix)?.read() || {image:'',color:'#633d60'},ready:prefix=>{if(drafts.get(prefix)?.busy){showToast('Дождитесь загрузки фото');return false;}return true;}};
})();
