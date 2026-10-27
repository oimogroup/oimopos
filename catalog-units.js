(function (global) {
  'use strict';
  const factor = unit => ['кг', 'л'].includes(unit) ? 1000 : 1;
  const label = unit => ({'кг':'г','л':'мл'})[unit] || unit;
  function pieceWeight(item) { return Number(item?.pieceWeightGrams || 0); }
  function netWeight(component, item) {
    if (component.netWeightGrams != null) return Number(component.netWeightGrams);
    const net = Number(component.net ?? component.gross ?? 0);
    if (item?.unit !== 'шт') return net;
    const weight = Number(component.pieceWeightGrams || pieceWeight(item));
    return weight > 0 ? net / 1000 * weight : null;
  }
  function output(components, find) {
    let total = 0;
    for (const component of components) {
      const weight = netWeight(component, find(component.ingredientId));
      if (weight == null) return null;
      total += weight;
    }
    return Math.round(total * 1e6) / 1e6;
  }
  global.CatalogUnits = {factor, label, pieceWeight, netWeight, output,
    quantity: (value, unit) => Number(value || 0) * factor(unit),
    stockQuantity: (value, unit) => Number(value || 0) / factor(unit),
    price: (value, unit) => Number(value || 0) / factor(unit),
    stockPrice: (value, unit) => Number(value || 0) * factor(unit)};
})(window);
