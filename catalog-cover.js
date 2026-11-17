/* Shared catalogue appearance editor. Persisted data is plain {image, color}. */
window.CatalogCover = (() => {
  const drafts = new Map();
  const safeColor = value => /^#[0-9a-f]{6}$/i.test(value || '') ? value : '#633d60';
  const safeImage = value => /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(value || '') ? value : '';
  const esc = value => String(value || '').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');
  function thumb(item, name=item?.name || '') {
    return `<span class="catalog-thumb" style="background:${safeColor(item?.color)};color:${parseInt(safeColor(item?.color).slice(1,3),16)*0.299+parseInt(safeColor(item?.color).slice(3,5),16)*0.587+parseInt(safeColor(item?.color).slice(5,7),16)*0.114>150?'#302b32':'#ffffff'}">${safeImage(item?.image) ? `<img src="${esc(item.image)}" alt="">` : `<span>${esc(name.slice(0,1))}</span>`}</span>`;
  }
  function loading(preview, status, busy, message='Сжимаем фото…') {
    preview?.classList.toggle('catalog-photo-loading',busy);
    preview?.setAttribute('aria-busy',String(busy));
    if(status){
      status.textContent=busy?message:'';
      status.classList.toggle('catalog-photo-status',busy);
      status.setAttribute('aria-busy',String(busy));
    }
  }
  const dataUrlBytes = value => Math.ceil((value.length - value.indexOf(',') - 1) * 3 / 4);
  async function load(file, {maxDimension=640,maxBytes=220*1024,maxInputBytes=2*1024*1024}={}) {
    if (!file || !['image/png','image/jpeg','image/webp','image/gif'].includes(file.type) || file.size>maxInputBytes) throw new Error(`Выберите JPG, PNG, WebP или GIF размером до ${Math.round(maxInputBytes/1024/1024)} МБ`);
    const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
    const img=await new Promise((resolve,reject)=>{
      const image=new Image();
      image.onload=()=>resolve(image);
      image.onerror=()=>reject(new Error('Не удалось открыть изображение'));
      image.src=data;
      if(image.complete){if(image.naturalWidth)resolve(image);else reject(new Error('Не удалось открыть изображение'));}
    });
    if (!img.naturalWidth || !img.naturalHeight || img.naturalWidth*img.naturalHeight>40000000) throw new Error('Слишком большое разрешение изображения');
    const canvas=document.createElement('canvas');
    const scale=Math.min(1, maxDimension/Math.max(img.width,img.height));
    canvas.width=Math.max(1,Math.round(img.width*scale));
    canvas.height=Math.max(1,Math.round(img.height*scale));
    const ctx=canvas.getContext('2d');
    const draw = (whiteBackground=false) => {
      ctx.clearRect(0,0,canvas.width,canvas.height);
      if(whiteBackground){ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);}
      ctx.drawImage(img,0,0,canvas.width,canvas.height);
    };
    const encode = (mime,quality) => {
      const value=canvas.toDataURL(mime,quality);
      return {value,mime:value.slice(5,value.indexOf(';'))};
    };
    const photo = file.type !== 'image/png';
    draw(photo);
    let output, mime, quality=0.76;
    if(!photo){
      ({value:output,mime}=encode('image/png'));
      if(dataUrlBytes(output)>maxBytes){quality=0.82;({value:output,mime}=encode('image/webp',quality));}
    }else{
      ({value:output,mime}=encode('image/jpeg',quality));
    }
    if(mime==='image/png' && dataUrlBytes(output)>maxBytes){
      quality=0.76;draw(true);({value:output,mime}=encode('image/jpeg',quality));
    }
    for(let i=0;i<6 && dataUrlBytes(output)>maxBytes;i++){
      quality=Math.max(0.35,quality-0.1);
      ({value:output,mime}=encode(mime==='image/webp'?'image/webp':'image/jpeg',quality));
      if(mime==='image/png'){draw(true);({value:output,mime}=encode('image/jpeg',quality));}
    }
    for(let i=0;i<5 && dataUrlBytes(output)>maxBytes && Math.max(canvas.width,canvas.height)>320;i++){
      canvas.width=Math.max(1,Math.round(canvas.width*0.8));
      canvas.height=Math.max(1,Math.round(canvas.height*0.8));
      draw(mime!=='image/webp');
      ({value:output,mime}=encode(mime==='image/webp'?'image/webp':'image/jpeg',quality));
      if(mime==='image/png'){draw(true);({value:output,mime}=encode('image/jpeg',quality));}
    }
    return output;
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
    const setLoading=busy=>loading(root.querySelector('[data-cover-preview]'),root.querySelector('[data-cover-status]'),busy);
    const render=()=>{draft.color=safeColor(color.value);root.querySelector('[data-cover-preview]').innerHTML=thumb(draft,name.value);root.querySelector('[data-cover-remove]').hidden=!draft.image;};
    color.addEventListener('input',render,{signal:controller.signal});
    if(externalColorId)document.getElementById(externalColorId.replace('Input','Text'))?.addEventListener('input',render,{signal:controller.signal});name.addEventListener('input',render,{signal:controller.signal});
    root.querySelector('[data-cover-remove]').onclick=()=>{draft.token++;draft.image='';draft.busy=false;root.querySelector('[data-cover-file]').value='';setLoading(false);render();};
    root.querySelector('[data-cover-file]').onchange=async event=>{
      const file=event.target.files[0];if(!file)return;
      const token=++draft.token;draft.busy=true;setLoading(true);
      try {const image=await load(file);if(drafts.get(prefix)!==draft||token!==draft.token)return;draft.image=image;render();}
      catch(error){if(drafts.get(prefix)===draft&&token===draft.token)showToast(error.message || 'Не удалось открыть изображение');}
      finally {if(drafts.get(prefix)===draft&&token===draft.token){draft.busy=false;setLoading(false);event.target.value='';}}
    };
    draft.read=()=>({image:draft.image,color:safeColor(color.value)});render();
  }
  return {open,load,loading,thumb,safeColor,safeImage,read:prefix=>drafts.get(prefix)?.read() || {image:'',color:'#633d60'},ready:prefix=>{if(drafts.get(prefix)?.busy){showToast('Дождитесь загрузки фото');return false;}return true;}};
})();
