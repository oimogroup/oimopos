(() => {
  const U = window.CatalogUnits;
  const check = (value, name) => {if (!value) throw new Error(name);};
  check(U.label('кг') === 'г' && U.label('л') === 'мл' && U.label('шт') === 'шт', 'only catalog units');
  check(U.quantity(2,'кг') === 2000 && U.price(200,'кг') === .2, 'quantity and unit cost scale together');
  check(U.stockQuantity(2000,'кг') === 2 && U.stockPrice(.2,'кг') === 200, 'stock conversions are reversible');
  check(U.quantity(3,'шт') === 3 && U.price(10,'шт') === 10, 'pieces unchanged');
  check(U.output([20,112,550,50,13,175,460,110].map(net=>({net,ingredientId:'g'})),()=>({unit:'кг'})) === 1490, 'Poster screenshot example totals 1490g');
  const egg = {id:'egg',unit:'шт',pieceWeightGrams:55};
  check(U.netWeight({gross:2000,net:2000},egg) === 110, 'two eggs have mass 110g');
  check(U.netWeight({net:2000},{unit:'шт'}) === null, 'unknown piece weight is not invented');
  check(U.netWeight({net:2000,netWeightGrams:105},egg) === 105, 'explicit output mass preserved');
  const items = {egg,flour:{unit:'кг'},water:{unit:'л'}};
  check(U.output([{ingredientId:'flour',net:550},{ingredientId:'water',net:175},{ingredientId:'egg',net:2000}],id=>items[id]) === 835, 'output sums grams, volume default and piece weights');
})();
