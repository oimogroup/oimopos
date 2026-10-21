(()=>{
 'use strict';
 const q=s=>document.querySelector(s),sections=[...document.querySelectorAll('.guide-section')],links=[...document.querySelectorAll('.contents a')];
 const normalize=text=>text.toLocaleLowerCase('ru').replaceAll('ё','е').trim();
 let role='all';
 function filter(){
  const terms=normalize(q('#guideSearch').value).split(/\s+/).filter(Boolean);
  let count=0;
  for(const section of sections){const text=normalize(section.textContent);const match=(role==='all'||section.dataset.roles.split(',').includes(role))&&terms.every(t=>text.includes(t));section.hidden=!match;if(match)count++;links.find(l=>l.hash==='#'+section.id).hidden=!match;}
  q('#searchCount').textContent=`Разделов: ${count} из ${sections.length}`;q('#noResults').hidden=count>0;
  document.querySelectorAll('.contents h2').forEach(h=>{let n=h.nextElementSibling,visible=false;while(n&&n.tagName!=='H2'){if(!n.hidden)visible=true;n=n.nextElementSibling;}h.hidden=!visible;});
 }
 q('#guideSearch').addEventListener('input',filter);
 document.querySelectorAll('[data-role-filter]').forEach(button=>button.onclick=()=>{role=button.dataset.roleFilter;document.querySelectorAll('[data-role-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));filter();});
 function revealAnchor(){const section=document.getElementById(location.hash.slice(1));if(section?.classList.contains('guide-section')&&section.hidden){role='all';q('#guideSearch').value='';document.querySelectorAll('[data-role-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.roleFilter==='all')));filter();}links.forEach(l=>l.setAttribute('aria-current',String(l.hash===location.hash)));}
 window.addEventListener('hashchange',revealAnchor);revealAnchor();filter();
 document.addEventListener('keydown',event=>{if(event.key==='/'&&!/INPUT|TEXTAREA/.test(document.activeElement.tagName)){event.preventDefault();q('#guideSearch').focus();}});
 const dialog=q('#imageDialog');let trigger;
 document.querySelectorAll('[data-zoom]').forEach(button=>button.onclick=()=>{trigger=button;const img=button.querySelector('img');q('#zoomImage').src=img.src;q('#zoomImage').alt=img.alt;q('#zoomCaption').textContent=img.alt;dialog.showModal();});
 q('#closeImage').onclick=()=>dialog.close();dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});dialog.addEventListener('close',()=>trigger?.focus());
 q('#printGuide').onclick=async()=>{
  const button=q('#printGuide');button.disabled=true;
  try{
   sections.forEach(s=>s.hidden=false);
   const images=[...document.querySelectorAll('figure img')];images.forEach(i=>i.loading='eager');
   await Promise.all(images.map(i=>i.complete?Promise.resolve():new Promise(r=>{i.addEventListener('load',r,{once:true});i.addEventListener('error',r,{once:true});})));
   window.print();
  }finally{button.disabled=false;filter();}
 };
 window.addEventListener('beforeprint',()=>sections.forEach(s=>s.hidden=false));window.addEventListener('afterprint',filter);
 document.body.dataset.ready='true';
})();
