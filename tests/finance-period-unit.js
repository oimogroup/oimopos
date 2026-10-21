/* Pure source-level regression suite: no DOM storage, API, or database writes. */
function runFinancePeriodTests(source) {
  const passed = [];
  const assert = (condition, name) => { if (!condition) throw new Error(name); passed.push(name); };
  const names = ["analyticsInputDate", "analyticsDateValue", "saleReportingDate", "filterSalesByRange",
    "saleRefundUnitCost", "salesPeriodEvents", "saleCost", "isExternalSale", "analyticsUnit", "saleLineUnit",
    "saleLineRevenue", "salesMetrics", "itemAnalyticsRows", "analyticsBuckets", "renderSalesLine", "compactAmount",
    "reportContext", "visibleReceipts", "paymentMethodLabel", "renderPaymentBreakdown", "exportAnalyticsCsv",
    "financeContext", "financeMetrics", "financeSaleAccountId", "financeAccount", "financeCategory", "financeAccountBalance",
    "financeTransactionRows", "financeDate", "financeTypeLabel", "exportFinanceCsv", "salePaymentParts", "salePaymentAmount", "salePaymentSummary"];
  const definitions = names.map(name => {
    const start = source.search(new RegExp(`function ${name}\\(`));
    if (start < 0) throw new Error(`Missing ${name}`);
    const next = source.slice(start + 1).search(/\n(?:async )?function /);
    return next < 0 ? source.slice(start) : source.slice(start, start + next + 1);
  }).join("\n");
  const product = { id: "p-1", name: "Water", category: "Goods", unit: "шт", price: 50 };
  const recipe = { id: 101, name: "Soup", category: "Meals", price: 50 };
  const sold = { id: "original", number: 7, branchId: "b1", cashier: "Cashier", refundedBy: "Manager",
    createdAt: "2026-10-05T12:00:00Z", refundedAt: "2026-10-06T12:00:00Z",
    paymentMethod: "mixed", payments: [{method:"cash", amount:30}, {method:"card", amount:60}],
    total:90, subtotal:100, discountAmount:10,
    items:[{id:"p-1", name:"Water", unit:"шт", price:50, quantity:2, unitCost:20}] };
  let sales = [sold], exported = "", activeTab = "sales";
  const accounts = [
    {id:"bank-b1", name:"Bank One", type:"bank", branchId:"b1", status:"active", openingBalance:0},
    {id:"bank-b2", name:"Bank Two", type:"bank", branchId:"b2", status:"active", openingBalance:0},
    {id:"finance-bank", name:"Company Bank", type:"bank", branchId:null, status:"active", openingBalance:0},
    {id:"finance-cash-b1", name:"Cash One", type:"cash", branchId:"b1", status:"active", openingBalance:0}
  ];
  const financeState = {accounts, transactions:[], categories:[]};
  const companyGeneralSettings = {timezone:"UTC", shiftEnd:"00:00"};
  const elements = {};
  const element = selector => elements[selector] ||= {value:selector.includes("Filter") ? "all" : "", textContent:"", innerHTML:"", style:{}};
  const dependencies = {
    recipes:[recipe], products:[product], financeState, companyGeneralSettings, getSales:()=>sales,
    saleUnitCost:(_sale,item)=>Number(item.unitCost || 0),
    initializeFinanceFilters(){}, initializeReportFilters(){}, $:element,
    money:String, decimal:String, escapeHtml:String, branchById:id=>({name:id}),
    document:{body:{append(){}},createElement:()=>({click(){},remove(){}})},
    Blob:function(parts){this.parts=parts;}, URL:{createObjectURL:blob=>{exported=blob.parts.join("");return "blob:test";},revokeObjectURL(){}},
  };
  const api = new Function(...Object.keys(dependencies), definitions + `\nlet activeAnalyticsTab='sales';return {${names.join(",")},setTab:tab=>activeAnalyticsTab=tab};`)(...Object.values(dependencies));
  const period = (from, to=from, branch="b1") => {
    for (const prefix of ["finance", "report"]) {
      element(`#${prefix}DateFrom`).value=from; element(`#${prefix}DateTo`).value=to;
      element(`#${prefix}BranchFilter`).value=branch;
    }
  };
  const sum = (rows, field) => rows.reduce((value,row)=>value+Number(row[field] || 0),0);
  const snapshot = JSON.stringify(sold);
  period("2026-10-05");
  let context = api.reportContext(), metrics = api.salesMetrics(context.sales);
  assert(metrics.revenue===90 && metrics.cost===40 && metrics.profit===50, "later-refund-does-not-rewrite-sale-day");
  assert(metrics.receipts===1 && metrics.refunds===0 && metrics.imports===0 && metrics.quantities[0].quantity===2, "sale-day-count-and-quantity");
  assert(api.financeMetrics(api.financeContext()).revenue===90 && api.financeMetrics(api.financeContext()).cost===40, "finance-and-analytics-sale-day-agree");
  assert(context.allSales.length===1 && context.allSales[0]===sold && api.visibleReceipts(context)[0]===sold, "archive-keeps-original-receipt");
  assert(sum(context.sales,"discountAmount")===10 && context.sales.reduce((s,row)=>s+api.salePaymentAmount(row,"cash"),0)===30, "sale-discounts-and-payments");

  period("2026-10-06"); context=api.reportContext(); metrics=api.salesMetrics(context.sales);
  assert(metrics.revenue===-90 && metrics.cost===-40 && metrics.profit===-50, "refund-day-reverses-returned-goods-cost-and-revenue");
  assert(metrics.receipts===0 && metrics.refunds===1 && metrics.imports===0 && metrics.quantities[0].quantity===-2, "refund-is-not-an-extra-receipt");
  assert(context.allSales.length===0 && api.visibleReceipts(context).length===0, "refund-event-does-not-enter-receipt-archive");
  assert(api.salesMetrics(context.previousSales).revenue===90, "previous-period-keeps-original-sale");
  assert(sum(context.sales,"discountAmount")===-10 && sum(context.sales,"subtotal")===-100 && api.salePaymentAmount(context.sales[0],"cash")===-30 && api.salePaymentAmount(context.sales[0],"card")===-60, "refund-discounts-subtotal-and-split-payments-have-correct-sign");
  const refundRows=api.financeTransactionRows(api.financeContext());
  assert(refundRows.length===2 && refundRows.every(row=>row.type==="expense" && row.occurredAt===sold.refundedAt && row.number==="Возврат чека №7") && sum(refundRows,"amount")===90, "finance-register-shows-refund-at-its-own-date");
  assert(api.financeMetrics(api.financeContext()).net===-50, "finance-refund-is-not-double-counted-as-expense");
  api.exportFinanceCsv(); assert(exported.includes('"-30"') && exported.includes('"-60"') && exported.includes("Возврат чека №7"), "finance-csv-matches-negative-refund-payments");
  api.setTab("sales");api.exportAnalyticsCsv();assert(exported.includes('"-2";"шт";"-100";"-40";"-60"'), "analytics-csv-keeps-returned-line-quantity-gross-value-and-cost");
  api.renderPaymentBreakdown(context.sales);assert(element("#reportPayments").innerHTML.includes("-60") && !element("#reportPayments").innerHTML.includes("width:-"), "negative-payment-values-have-valid-progress-bars");
  const buckets=api.analyticsBuckets(context.sales,context.from,context.to);
  const axis={innerHTML:""}, chart={innerHTML:"",style:{}};api.renderSalesLine(axis,chart,buckets);
  assert(buckets[0].revenue===-90 && buckets[0].receipts===0 && axis.innerHTML.includes("-") && !chart.innerHTML.includes("NaN"), "refund-chart-has-negative-axis-and-no-fake-receipt");

  period("2026-10-05","2026-10-06");context=api.reportContext();metrics=api.salesMetrics(context.sales);
  assert(metrics.revenue===0 && metrics.cost===0 && metrics.quantities[0].quantity===0 && metrics.receipts===1 && metrics.refunds===1, "both-days-cancel-value-and-quantity-with-one-original-receipt");
  assert(sum(context.sales,"discountAmount")===0 && context.sales.reduce((s,row)=>s+api.salePaymentAmount(row,"card"),0)===0, "both-days-cancel-discounts-and-payments");
  const rows=api.financeTransactionRows(api.financeContext());assert(rows.length===4 && rows.reduce((s,row)=>s+(row.type==="expense"?-1:1)*row.amount,0)===0, "finance-register-keeps-sale-and-refund-with-zero-net");
  api.setTab("receipts");api.exportAnalyticsCsv();assert(exported.includes('"2";"шт";"50";"100";"40";"60"') && !exported.includes('"-2"'), "receipt-export-keeps-original-lines");
  assert(JSON.stringify(sold)===snapshot, "all-calculations-leave-source-history-unchanged");

  for (const allocations of [{ingredientAllocations:[{itemId:"rice"}]},{batchAllocations:[{lotId:"accepted-lot"}]}]) {
    sales=[{...sold,items:[{...sold.items[0],id:101,unit:"порция",...allocations}]}];
    period("2026-10-06");metrics=api.salesMetrics(api.reportContext().sales);
    assert(metrics.revenue===-90 && metrics.cost===0 && metrics.profit===-90, "prepared-refund-does-not-restore-consumed-cost-"+Object.keys(allocations)[0]);
    period("2026-10-05","2026-10-06");metrics=api.salesMetrics(api.reportContext().sales);
    assert(metrics.revenue===0 && metrics.cost===40 && metrics.profit===-40, "prepared-refund-keeps-original-food-cost-"+Object.keys(allocations)[0]);
    const foodRows = api.itemAnalyticsRows(api.reportContext().sales);
    assert(foodRows.length===1 && foodRows[0].cost===40 && foodRows[0].profit===-40, "prepared-refund-remains-visible-in-item-costs-"+Object.keys(allocations)[0]);
  }
  sales=[{...sold,items:[{...sold.items[0],id:101,batchAllocations:[{lotId:"legacy-old"}]}]}];period("2026-10-06");
  assert(api.salesMetrics(api.reportContext().sales).cost===-40,"legacy-batch-return-reverses-restored-cost");
  sales=[{...sold,refundedAt:sold.createdAt}];period("2026-10-05");
  assert(api.salesMetrics(api.reportContext().sales).revenue===0 && api.salesMetrics(api.reportContext().sales).receipts===1,"same-day-refund-keeps-one-receipt-with-zero-net");
  sales=[{...sold,branchId:"b2"}];period("2026-10-05","2026-10-06","b1");assert(api.reportContext().sales.length===0 && api.financeContext().sales.length===0,"both-event-dates-obey-branch-filter");
  sales=[{...sold,paymentMethod:"external",source:"external",refundedAt:null,payments:[{method:"external",amount:90}]}];period("2026-10-05");
  metrics=api.salesMetrics(api.reportContext().sales);assert(metrics.revenue===90 && metrics.imports===1 && metrics.receipts===0 && api.financeTransactionRows(api.financeContext()).length===0,"external-import-contributes-to-revenue-without-inventing-bank-money");
  companyGeneralSettings.timezone="Asia/Almaty";companyGeneralSettings.shiftEnd="04:00";
  sales=[{...sold,createdAt:"2026-10-05T22:00:00Z",refundedAt:"2026-10-06T00:00:00Z"}];period("2026-10-05");
  assert(api.salesMetrics(api.reportContext().sales).revenue===90,"sale-time-obeys-company-business-day");period("2026-10-06");
  assert(api.salesMetrics(api.reportContext().sales).revenue===-90,"refund-time-obeys-same-company-business-day");
  companyGeneralSettings.timezone="UTC";companyGeneralSettings.shiftEnd="00:00";

  sales=[{...sold,branchId:"b2",refundedAt:null,paymentMethod:"card",payments:[{method:"card",amount:90}]}];
  assert(api.financeSaleAccountId(sales[0])==="bank-b2" && api.financeAccountBalance("bank-b1")===0 && api.financeAccountBalance("bank-b2")===90,"sale-bank-and-balance-never-use-another-branch");
  accounts.unshift(accounts.splice(2,1)[0]);assert(api.financeSaleAccountId(sales[0])==="bank-b2","branch-bank-takes-precedence-over-company-bank");
  accounts.find(row=>row.id==="bank-b2").status="inactive";assert(api.financeSaleAccountId(sales[0])==="finance-bank","missing-active-branch-bank-falls-back-only-to-company-bank");
  accounts.find(row=>row.id==="finance-bank").status="inactive";assert(api.financeSaleAccountId(sales[0])===null && api.financeAccountBalance("bank-b1")===0,"no-bank-fallback-to-another-branch");
  assert(api.financeSaleAccountId({...sold,paymentMethod:"cash"})==="finance-cash-b1","cash-routing-keeps-own-branch");
  return passed;
}
