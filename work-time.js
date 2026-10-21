(function(global){
 'use strict';
 const q=s=>document.querySelector(s);let shift=null,busy=false,actor=null,generation=0;
 const identity=()=>typeof activeOperator!=='undefined'?activeOperator?.id:null;
 async function load(){
  const token=++generation;q('#workTimeAction').disabled=true;q('#workTimeError').textContent='';
  actor=identity();q('#workTimeEmployee').textContent=typeof activeOperator!=='undefined'?activeOperator?.name||'Войдите по личному PIN':'';
  try{
   const result=await global.AshkanaApi.currentWorkShift();
   if(token!==generation)return;
   if(actor!==identity())throw new Error('Сотрудник сменился. Закройте окно и откройте рабочее время повторно.');
   shift=result.shift;q('#workTimeState').textContent=shift?'Рабочий день начат: '+new Date(shift.openedAt).toLocaleString('ru-RU'):'Рабочий день не начат';q('#workTimeAction').textContent=shift?'Закончить рабочий день':'Начать рабочий день';q('#workTimeAction').disabled=!actor;
  }catch(error){q('#workTimeError').textContent=error.message||'Не удалось загрузить рабочую смену';q('#workTimeState').textContent='Нет подтверждённых данных';}
 }
 q('#workShiftButton').addEventListener('click',()=>{q('#workTimeDialog').showModal();load();});
 q('#workTimeClose').onclick=()=>{if(!busy){generation++;q('#workTimeDialog').close();}};
 q('#workTimeDialog').addEventListener('cancel',event=>{if(busy)event.preventDefault();else generation++;});
 q('#workTimeRefresh').onclick=()=>{if(!busy)load();};
 q('#workTimeAction').onclick=async()=>{
  if(busy||!actor||actor!==identity()){q('#workTimeError').textContent='Сначала войдите по личному PIN и обновите окно.';return;}
  busy=true;q('#workTimeAction').disabled=true;q('#workTimeClose').disabled=true;q('#workTimeError').textContent='';
  try{await global.AshkanaApi.action(shift?'work.shift.close':'work.shift.open',{});await load();}
  catch(error){q('#workTimeError').textContent=error.message||'Изменение не подтверждено. Проверьте состояние перед повтором.';}
  finally{busy=false;q('#workTimeClose').disabled=false;}
 };
})(window);
