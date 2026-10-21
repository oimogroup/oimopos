/* Pass the current admin.js source to runAdminAnalyticsTests in a JS runtime. */
function runAdminAnalyticsTests(source) {
  const passed = [];
  const assert = (condition, name) => {
    if (!condition) throw new Error(name);
    passed.push(name);
  };
  const names = ["saleCost", "isExternalSale", "analyticsUnit", "saleLineUnit", "saleLineRevenue", "salesMetrics", "itemAnalyticsRows", "paymentMethodLabel", "renderPaymentBreakdown", "assignAbcGroups", "abcRecommendation", "renderABC", "exportAnalyticsCsv"];
  const definitions = names.map((name) => {
    const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
    if (start < 0) throw new Error(`Missing function ${name}`);
    const next = source.slice(start + 1).search(/\n(?:async )?function /);
    return next < 0 ? source.slice(start) : source.slice(start, start + 1 + next);
  }).join("\n");
  const recipes = [{ id: 101, name: "Soup", category: "Soup", price: 40 }, { id: 102, name: "Unsold", category: "Soup", price: 50 }];
  const products = [{ id: "p-1", name: "Water", category: "Drinks", unit: "шт", price: 10 }];
  const sale = { total: 110, paymentMethod: "cash", items: [{ id: 101, quantity: 2, unit: "порция", price: 40, unitCost: 10 }, { id: "p-1", quantity: 3, unit: "шт.", price: 10, unitCost: 2 }] };
  const imported = { total: 100, paymentMethod: "external", items: [{ id: 101, quantity: 3, unit: "КГ.", price: 33.33, total: 100, unitCost: 5 }] };
  const weighted = { total: 20, paymentMethod: "card", items: [{ id: 101, quantity: .5, unit: "порции", price: 40, unitCost: 10 }] };
  const allSales = [sale, imported, weighted];
  const elements = {};
  const element = (selector) => elements[selector] ||= { value: selector.includes("Filter") ? "all" : "", textContent: "", innerHTML: "" };
  let exported;
  const dependencies = {
    recipes, products, saleUnitCost: (sale, line) => Number(line.unitCost || 0),
    salePaymentAmount: (sale, method) => sale.paymentMethod === method ? sale.total : 0,
    $: element, money: String, decimal: String, escapeHtml: String,
    reportContext: () => ({ sales: allSales }), pluralRu: () => "позиции",
    document: { querySelector: element, createElement: () => ({ click() {} }) },
    activeAnalyticsTab: "abc", Blob: function (parts) { this.parts = parts; },
    URL: { createObjectURL: (blob) => { exported = blob.parts.join(""); return "blob:test"; }, revokeObjectURL() {} }
  };
  const api = new Function(...Object.keys(dependencies), definitions + `\nreturn {${names.join(",")}};`)(...Object.values(dependencies));
  const metrics = api.salesMetrics(allSales);
  assert(metrics.revenue === 230 && metrics.receipts === 2 && metrics.imports === 1 && metrics.average === 65, "external-revenue-does-not-inflate-receipt-average");
  const onlyExternal = api.salesMetrics([imported]);
  assert(onlyExternal.revenue === 100 && onlyExternal.receipts === 0 && onlyExternal.average === 0, "external-only-has-no-invented-receipts");
  assert(metrics.quantities.find(row => row.unit === "порция").quantity === 2.5 && metrics.quantities.find(row => row.unit === "кг").quantity === 3, "summary-separates-units-and-preserves-weighted-portions");
  const rows = api.itemAnalyticsRows(allSales, true);
  const portions = rows.find(row => row.item.id === 101 && row.unit === "порция");
  const kilos = rows.find(row => row.item.id === 101 && row.unit === "кг");
  assert(portions.quantity === 2.5 && portions.revenue === 100 && kilos.quantity === 3 && kilos.revenue === 100, "same-dish-units-remain-separate-and-line-total-is-authoritative");
  assert(portions.item.catalogKey !== kilos.item.catalogKey && rows.some(row => row.item.id === 102 && row.quantity === 0), "abc-keys-distinguish-units-and-keep-unsold-catalog");
  assert(api.itemAnalyticsRows([imported], true).filter(row => row.item.id === 101).length === 1, "external-only-unit-does-not-add-empty-portion-duplicate");
  assert(api.saleLineRevenue({ quantity: 3, price: 33.33, total: 0 }) === 0 && api.saleLineRevenue({ quantity: .5, price: 40 }) === 20, "zero-total-and-regular-price-fallback");
  api.renderPaymentBreakdown(allSales);
  assert(element("#reportPayments").innerHTML.includes("Внешняя касса") && element("#reportPayments").innerHTML.includes("100"), "payment-breakdown-shows-external-revenue");
  api.renderABC();
  assert(element("#abcTable").innerHTML.includes("3 кг") && element("#abcTable").innerHTML.includes("2.5 порция") && element("#abcTable").innerHTML.includes('Доля среди позиций в кг">100%'), "abc-labels-units-and-compares-quantities-within-unit");
  api.exportAnalyticsCsv();
  assert(exported.includes('"Единица"') && exported.includes('"3";"кг";"100"') && exported.includes('"2.5";"порция";"100"'), "csv-preserves-units-and-exact-line-amounts");
  const receiptDependencies = { ...dependencies, activeAnalyticsTab: "receipts", visibleReceipts: () => [imported], branchById: () => null, salePaymentSummary: () => "Внешняя касса" };
  const receiptApi = new Function(...Object.keys(receiptDependencies), definitions + "\nreturn {exportAnalyticsCsv};")(...Object.values(receiptDependencies));
  receiptApi.exportAnalyticsCsv();
  assert(exported.includes('"Единица"') && exported.includes('"3";"кг";"33.33";"100"'), "receipt-csv-uses-exact-import-total");
  return passed;
}
