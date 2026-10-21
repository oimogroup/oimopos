/* Run with the current app.js source in a JavaScript runtime. */
function runSalesImportSummaryTests(source) {
  const passed = [];
  const assert = (condition, name) => {
    if (!condition) throw new Error(name);
    passed.push(name);
  };
  const start = source.indexOf('function salesImportSelectionSummary(');
  const end = source.indexOf("$('#salesImportButton').onclick", start);
  const elements = {
    '#salesImportSummary': {textContent: '', innerHTML: '', setAttribute() {}},
    '#salesImportError': {textContent: ''},
    '#salesImportRows': {querySelectorAll: () => []},
  };
  const data = {rows: [
    {row: '2', total: 100.1, posted: true},
    {row: '3', total: 200.2},
    {row: '4', total: 300.3},
    {row: '5', total: 400.4},
  ]};
  const api = new Function('salesImportData', '$', 'money', 'escapeHtml', source.slice(start, end) + ';return {salesImportSelectionSummary,renderSalesImportSummary};')(
    data, selector => elements[selector], amount => amount.toFixed(2) + ' сом', text => String(text)
  );
  const selections = [
    {row: '5', selected: false, mapped: true},
    {row: '3', selected: true, mapped: true},
    {row: '2', selected: true, mapped: false},
    {row: '4', selected: true, mapped: false},
  ];
  const totals = api.salesImportSelectionSummary(data, selections);
  assert(totals.file.count === 4 && totals.file.amount === 1001, 'file-total-includes-every-row');
  assert(totals.selected.count === 1 && totals.selected.amount === 200.2, 'selection-uses-source-row-key-not-dom-order');
  assert(totals.posted.count === 1 && totals.posted.amount === 100.1, 'posted-is-never-selected-or-unmapped');
  assert(totals.unmapped.count === 1 && totals.unmapped.amount === 300.3, 'checked-unmapped-is-not-ready-to-import');
  assert(totals.unchecked.count === 1 && totals.unchecked.amount === 400.4, 'mapped-unchecked-amount-is-separate');
  assert(['selected', 'posted', 'unmapped', 'unchecked'].reduce((sum, key) => sum + totals[key].count, 0) === totals.file.count, 'reconciliation-has-no-double-counting');
  const rounding = api.salesImportSelectionSummary({rows: [{row: 'a', total: .1}, {row: 'b', total: .2}, {row: 'c', total: 1.005}]}, []);
  assert(rounding.file.amount === 1.31, 'money-rounded-to-two-decimals-without-float-tail');
  const report = {rows: Array.from({length: 149}, (_, index) => ({row: String(index), total: index === 89 ? 158587 : index === 148 ? 120168 : 0}))};
  const reportSelections = report.rows.map((row, index) => ({row: row.row, selected: index < 90, mapped: index < 90}));
  const comparison = api.salesImportSelectionSummary(report, reportSelections);
  assert(comparison.file.amount === 278755 && comparison.selected.amount === 158587 && comparison.unmapped.amount === 120168 && comparison.unmapped.count === 59, 'partial-file-selection-shows-missing-amount');
  elements['#salesImportRows'].querySelectorAll = () => selections.map(choice => ({
    dataset: {importRow: choice.row},
    querySelector: selector => selector === '.import-select' ? {checked: choice.selected} : {value: choice.mapped ? 'dish' : ''},
  }));
  api.renderSalesImportSummary();
  assert(elements['#salesImportSummary'].innerHTML.includes('К импорту: 1 поз.') && elements['#salesImportSummary'].innerHTML.includes('200.20 сом'), 'summary-renders-selected-count-and-amount');
  elements['#salesImportError'].textContent = 'Ошибка чтения';
  api.renderSalesImportSummary();
  assert(elements['#salesImportSummary'].textContent === '', 'error-clears-stale-summary');
  elements['#salesImportError'].textContent = '';
  const noData = new Function('salesImportData', '$', 'money', 'escapeHtml', source.slice(start, end) + ';return renderSalesImportSummary;')(
    null, selector => elements[selector], String, String
  );
  elements['#salesImportSummary'].textContent = 'Предыдущий файл';
  noData();
  assert(elements['#salesImportSummary'].textContent === '', 'new-file-clears-stale-summary');
  return passed;
}
