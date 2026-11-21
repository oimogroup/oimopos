/* Virtual preparations are expanded proportionally; only raw ingredients move. */
(function(global) {
  'use strict';
  function flatten(item, state, initialPath = [], stock = false) {
    const preparations = new Map((state.preparations || []).map(row=>[String(row.id),row]));
    const totals = new Map();
    function expand(components, factor, path) {
      if(path.length>20)throw new Error('Слишком много уровней вложенности полуфабрикатов');
      for(const component of components || []) {
        const gross=Number(component.gross ?? component.net ?? 0);
        if(!Number.isFinite(gross)||gross<0)throw new Error('Проверьте брутто компонента');
        if(!gross)continue;
        if(component.preparationId!=null) {
          const id=String(component.preparationId), preparation=preparations.get(id);
          if(!preparation)throw new Error('Полуфабрикат не найден: '+id);
          if(path.includes(id))throw new Error('Цикл в составе полуфабрикатов: '+[...path,id].map(key=>preparations.get(key)?.name||key).join(' → '));
          if(stock && preparation.stockMode==='produced'){
            const key='preparation:'+id,total=(totals.get(key)||0)+gross*factor;
            if(!Number.isFinite(total))throw new Error('Слишком большое количество компонента');
            totals.set(key,total);continue;
          }
          const output=Number(preparation.yield);
          if(!Number.isFinite(output)||output<=0||!preparation.components?.length)throw new Error('Проверьте состав и выход полуфабриката «'+preparation.name+'»');
          expand(preparation.components,factor*gross/output,[...path,id]);
        }else{
          const id=String(component.ingredientId||'');
          if(!id)throw new Error('Не указан ингредиент');
          const amount=gross*factor;
          if(!Number.isFinite(amount))throw new Error('Слишком большое количество компонента');
          const total=(totals.get(id)||0)+amount;
          if(!Number.isFinite(total))throw new Error('Слишком большое количество компонента');
          totals.set(id,total);
        }
      }
    }
    // POS receives this server snapshot even when preparation details are hidden.
    const missing=(components,path=[]) => (components||[]).some(component=>{
      if(component.preparationId==null)return false;
      const id=String(component.preparationId), p=preparations.get(id);
      return !p || (!path.includes(id)&&missing(p.components,[...path,id]));
    });
    const components=missing(item.components)&&Array.isArray(item.rawComponents)?item.rawComponents:item.components;
    if(item.compositionError&&components===item.rawComponents)throw new Error(item.compositionError);
    expand(components,1,initialPath);
    return [...totals].map(([ingredientId,gross])=>({ingredientId,gross,net:gross}));
  }
  function cost(item,state,unitCost) {return flatten(item,state).reduce((sum,row)=>sum+Number(unitCost(row.ingredientId)||0)*row.gross/1000,0);}
  global.CatalogComposition={flatten,cost};
})(window);
