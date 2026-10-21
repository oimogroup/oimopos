/* Oimo printer transport. A completed sale is never retried by this module. */
(function(global) {
  'use strict';
  const defaults={receiptPrinterMode:'browser',receiptPrinterName:'',receiptPaperWidth:80,receiptDots:0,receiptCutPaper:false,autoPrintReceipt:false,printKitchenTicket:false};
  let connecting=null,loading=null,queue=Promise.resolve();
  function normalize(raw={}) {
    if(!raw || typeof raw!=='object')raw={};
    return {...defaults,receiptPrinterMode:['browser','qz','escpos','none'].includes(raw.receiptPrinterMode)?raw.receiptPrinterMode:'browser',receiptPrinterName:String(raw.receiptPrinterName||'').trim().slice(0,200),receiptPaperWidth:Number(raw.receiptPaperWidth)===58?58:80,receiptDots:[384,512,576,640,832].includes(Number(raw.receiptDots))?Number(raw.receiptDots):0,receiptCutPaper:raw.receiptCutPaper===true,autoPrintReceipt:raw.autoPrintReceipt===true,printKitchenTicket:raw.printKitchenTicket===true};
  }
  function loadQz() {
    if(global.qz)return Promise.resolve(global.qz);
    if(!loading)loading=new Promise((resolve,reject)=>{
      const script=document.createElement('script');script.src='/vendor/qz-tray-2.3.0.js';
      script.onload=()=>global.qz?resolve(global.qz):reject(new Error('Не удалось загрузить модуль печати. Обновите страницу.'));
      script.onerror=()=>{script.remove();reject(new Error('Модуль печати недоступен. Проверьте соединение и обновите страницу.'));};
      document.head.append(script);
    }).catch(error=>{loading=null;throw error;});
    return loading;
  }
  async function connect() {
    const qz=await loadQz();
    if(qz.websocket.isActive())return qz;
    if(!connecting)connecting=qz.websocket.connect({retries:0,delay:0}).catch(()=>{throw new Error('Не удалось подключиться к QZ Tray. Установите и запустите QZ Tray на кассе, затем разрешите подключение Oimo.');}).finally(()=>{connecting=null;});
    await connecting;return qz;
  }
  async function findPrinters() {
    const qz=await connect();
    const names=await qz.printers.find();
    return [...new Set((Array.isArray(names)?names:[names]).filter(name=>typeof name==='string'&&name))].sort((a,b)=>a.localeCompare(b,'ru'));
  }
  const textOf=node=>{
    const clone=node.cloneNode(true);clone.querySelectorAll('br').forEach(br=>br.replaceWith('\n'));
    return clone.textContent.replace(/\r/g,'').trim();
  };
  // Render characters in the browser, so ESC/POS does not depend on code pages.
  async function rasterize(html,settings) {
    settings=normalize(settings);
    const width=settings.receiptDots||(settings.receiptPaperWidth===58?384:576);
    const scale=width/384,pad=Math.round(12*scale),available=width-pad*2;
    const measure=document.createElement('canvas').getContext('2d');
    const doc=new DOMParser().parseFromString('<body>'+html+'</body>','text/html');
    const ops=[];let y=pad;
    const font=(size,bold)=>`${bold?'600':'400'} ${Math.round(size*scale)}px Arial, sans-serif`;
    function wrap(text,maxWidth,size,bold=false) {
      measure.font=font(size,bold);
      const result=[];
      for(const paragraph of String(text).split('\n')) {
        let line='';
        for(const word of paragraph.split(/\s+/)) {
          if(!word)continue;
          if(measure.measureText(line?line+' '+word:word).width<=maxWidth){line=line?line+' '+word:word;continue;}
          if(line){result.push(line);line='';}
          for(const char of Array.from(word)) {
            if(line&&measure.measureText(line+char).width>maxWidth){result.push(line);line='';}
            line+=char;
          }
        }
        result.push(line);
      }
      return result;
    }
    function lines(text,size=20,bold=false,align='left',maxWidth=available) {
      const height=Math.ceil(size*scale*1.35);
      for(const line of wrap(text,maxWidth,size,bold)) {
        ops.push({type:'text',text:line,font:font(size,bold),x:align==='center'?width/2:align==='right'?width-pad:pad,y,align});y+=height;
      }
    }
    async function visit(node) {
      if(node.nodeType===Node.TEXT_NODE){if(node.textContent.trim())lines(node.textContent);return;}
      if(node.nodeType!==Node.ELEMENT_NODE)return;
      const tag=node.tagName;
      if(['SCRIPT','STYLE','IFRAME','OBJECT'].includes(tag))return;
      if(tag==='IMG') {
        const src=node.getAttribute('src')||'';
        if(!/^data:image\/(png|jpeg|gif);base64,/i.test(src))return;
        const img=new Image();img.src=src;
        try{await img.decode();}catch(_){throw new Error('Не удалось подготовить логотип чека. Проверьте изображение в настройках компании.');}
        const ratio=Math.min(available/img.width,120*scale/img.height,1);
        const w=Math.round(img.width*ratio),h=Math.round(img.height*ratio);
        ops.push({type:'image',img,x:(width-w)/2,y,w,h});y+=h+10*scale;return;
      }
      if(tag==='HR'){y+=7*scale;ops.push({type:'rule',y});y+=10*scale;return;}
      if(tag==='H1'||tag==='H2'){lines(textOf(node),tag==='H1'?26:23,true,'center');y+=8*scale;return;}
      if(tag==='P') {
        const right=[...node.children].find(child=>child.tagName==='B');
        if(right) {
          const clone=node.cloneNode(true);[...clone.children].find(child=>child.tagName==='B').remove();
          const rightText=textOf(right);measure.font=font(20,true);
          const rightWidth=measure.measureText(rightText).width;
          if(rightWidth<=available*.45) {
            const top=y,leftWidth=available-rightWidth-12*scale;
            lines(textOf(clone),20,!!clone.querySelector('strong'),'left',leftWidth);
            ops.push({type:'text',text:rightText,font:font(20,true),x:width-pad,y:top,align:'right'});
          }else{lines(textOf(clone));lines(rightText,20,true,'right');}
        }else lines(textOf(node));
        y+=5*scale;return;
      }
      if(tag==='SMALL'){lines(textOf(node),16,false,'center');y+=5*scale;return;}
      if(tag==='BR'){y+=24*scale;return;}
      for(const child of node.childNodes)await visit(child);
    }
    for(const child of doc.body.childNodes)await visit(child);
    y=Math.ceil(y+pad);
    if(y>30000)throw new Error('Чек слишком длинный для изображения. Выберите системную печать для этого документа.');
    const canvas=document.createElement('canvas');canvas.width=width;canvas.height=Math.max(y,32);
    const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,width,canvas.height);ctx.fillStyle='black';ctx.textBaseline='top';
    for(const op of ops) {
      if(op.type==='text'){ctx.font=op.font;ctx.textAlign=op.align;ctx.fillText(op.text,op.x,op.y);}
      else if(op.type==='image')ctx.drawImage(op.img,op.x,op.y,op.w,op.h);
      else {ctx.beginPath();ctx.setLineDash([4*scale,3*scale]);ctx.strokeStyle='black';ctx.lineWidth=scale;ctx.moveTo(pad,op.y);ctx.lineTo(width-pad,op.y);ctx.stroke();}
    }
    return {base64:canvas.toDataURL('image/png').split(',')[1],width,height:canvas.height};
  }
  async function browserPrint(html,settings) {
    const area=document.createElement('section');area.id='posPrintArea';area.innerHTML=html;
    const paper=document.createElement('style');paper.textContent=`@media print{@page{margin:0}body>\u0023posPrintArea{width:${settings.receiptPaperWidth}mm!important;padding:3mm!important;box-sizing:border-box;font:12px Arial,sans-serif;overflow-wrap:anywhere}#posPrintArea p{display:flex;gap:3mm;justify-content:space-between;align-items:flex-start;margin:2mm 0}#posPrintArea p>b{flex-shrink:0}#posPrintArea h1{font-size:18px}#posPrintArea img{max-width:100%}}`;
    document.head.append(paper);document.body.append(area);
    try { await Promise.all([...area.querySelectorAll('img')].map(img=>img.decode())); }
    catch (_) { area.remove();paper.remove();throw new Error('Не удалось подготовить изображение чека. Проверьте логотип.'); }
    return new Promise((resolve,reject)=>{
      const cleanup=()=>{area.remove();paper.remove();global.removeEventListener('afterprint',done);};
      const done=()=>{cleanup();resolve({status:'dialog'});};
      global.addEventListener('afterprint',done,{once:true});
      try{global.print();}catch(error){cleanup();reject(error);}
    });
  }
  async function perform(html,raw,title) {
    const settings=normalize(raw);
    if(settings.receiptPrinterMode==='none')throw new Error('Печать отключена. Выберите способ печати в настройках кассы.');
    if(settings.receiptPrinterMode==='browser')return browserPrint(html,settings);
    if(!settings.receiptPrinterName)throw new Error('Сначала найдите и выберите принтер в настройках кассы.');
    const qz=await connect();
    const names=await qz.printers.find();
    if(!(Array.isArray(names)?names:[names]).includes(settings.receiptPrinterName))throw new Error('Выбранный принтер не найден. Обновите список принтеров в настройках кассы.');
    const image=await rasterize(html,settings);
    if(settings.receiptPrinterMode==='escpos') {
      const config=qz.configs.create(settings.receiptPrinterName,{jobName:title,copies:1});
      const data=['\x1b@',{type:'raw',format:'image',flavor:'base64',data:image.base64,options:{language:'ESCPOS',dotDensity:'double'}},'\n\n\n'];
      if(settings.receiptCutPaper)data.push('\x1dV\x01');
      await qz.print(config,data);
    } else {
      const printable=settings.receiptPaperWidth-6;
      const config=qz.configs.create(settings.receiptPrinterName,{units:'mm',margins:{top:0,bottom:0,left:3,right:3},size:{width:settings.receiptPaperWidth,height:Math.ceil(image.height/image.width*printable+6)},scaleContent:true,copies:1,jobName:title});
      await qz.print(config,[{type:'pixel',format:'image',flavor:'base64',data:image.base64}]);
    }
    return {status:'queued',printer:settings.receiptPrinterName};
  }
  function print(html,settings,title='Oimo — чек') {
    // Serialize jobs. A failure is reported; it never triggers an automatic replay.
    const snapshot=normalize(settings);
    const pending=queue.catch(()=>{}).then(()=>perform(html,snapshot,title));queue=pending;return pending;
  }
  global.OimoPrinting={normalize,findPrinters,print,rasterize};
})(window);
