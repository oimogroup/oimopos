(function (global) {
  'use strict';
  const q = selector => document.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let report = null, generation = 0, timer, busy = false, command, force = false;
  const enabled = () => currentRole === 'owner' && (serverMode || force);
  const amount = value => new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 2}).format(Number(value || 0)) + ' ' + (report?.currency || '');
  const key = () => [q('#financeDateFrom').value, q('#financeDateTo').value, q('#financeBranchFilter').value].join('|');
  let reportKey = '';
  const dialog = document.createElement('dialog');
  dialog.id = 'pnlDialog'; dialog.className = 'payroll-dialog';
  dialog.innerHTML = '<form id="pnlForm"><header><div><p>P&L</p><h2 id="pnlDialogTitle"></h2></div><button type="button" id="pnlClose" class="icon-button" aria-label="Закрыть">×</button></header><div id="pnlFields"></div><p id="pnlError" role="alert"></p><footer><button type="button" class="secondary-action" id="pnlCancel">Отмена</button><button type="submit" class="primary-button" id="pnlSubmit">Сохранить</button></footer></form>';
  document.body.append(dialog);
  function refresh() {
    if (!enabled()) return;
    const token = ++generation;
    clearTimeout(timer); report = null;
    q('#pnlAddExpense').hidden = false; q('#pnlAddExpense').disabled = true;
    q('#pnlMethod').hidden = false; q('#pnlExpenseSection').hidden = false;
    q('#pnlStatus').textContent = 'Рассчитываем P&L…';
    q('#financePnlRows').textContent = ''; q('#pnlWarnings').textContent = ''; q('#pnlExpenseList').textContent = '';
    q('#financeNetProfit').textContent = '…'; q('#financeExpenses').textContent = '…'; q('#financeRevenue').textContent = '…';
    if (activeFinanceTab === 'pnl') q('#exportFinanceButton').disabled = true;
    const requestKey = key();
    timer = setTimeout(async () => {
      try {
        const data = await global.AshkanaApi.pnl(q('#financeDateFrom').value, q('#financeDateTo').value, q('#financeBranchFilter').value);
        if (token !== generation || requestKey !== key()) return;
        report = data; reportKey = requestKey; render();
      } catch (error) {
        if (token !== generation) return;
        q('#pnlStatus').textContent = error.message || 'Не удалось рассчитать P&L. Обновите период.';
        q('#financeNetProfit').textContent = '—'; q('#financeExpenses').textContent = '—'; q('#financeRevenue').textContent = '—';
      }
    }, 80);
  }
  function render() {
    q('#pnlStatus').textContent = 'По начислению · ' + report.start + ' — ' + report.end;
    q('#pnlAddExpense').disabled = false; q('#exportFinanceButton').disabled = false;
    q('#financeNetProfit').textContent = amount(report.net); q('#financeNetProfit').classList.toggle('negative', report.net < 0);
    q('#financeExpenses').textContent = amount(report.expenses); q('#financeRevenue').textContent = amount(report.revenue);
    const row = (label, value, cls = '') => `<div class="pnl-row ${cls}"><span>${esc(label)}</span><strong class="${value < 0 ? 'negative' : ''}">${esc(amount(value))}</strong></div>`;
    q('#financePnlRows').innerHTML = row('Выручка с учётом возвратов', report.revenue, 'main') + row('Себестоимость проданного', -report.cost) + row('Валовая прибыль', report.gross, 'subtotal') + (report.otherIncome ? row('Прочие доходы', report.otherIncome) : '') + report.expenseGroups.map(g => row(g.name, -g.amount)).join('') + row('Всего расходов', -report.expenses, 'subtotal') + row('Чистая прибыль', report.net, 'total') + `<div class="pnl-row"><span>Рентабельность</span><strong>${report.margin === null ? '—' : esc(report.margin) + '%'}</strong></div>`;
    q('#pnlWarnings').innerHTML = report.warnings.map(w => `<p class="pnl-warning">${esc(w)}</p>`).join('');
    const category = id => report.categories.find(c => c.id === id)?.name || financeCategory(id)?.name || 'Расход';
    q('#pnlExpenseList').innerHTML = report.documents.map(e => {
      const remaining = Math.round((e.amount-e.paid)*100)/100;
      const payments = report.payments.filter(p => p.expenseId === e.id && !p.reversedAt);
      return `<article class="pnl-expense"><div class="payroll-record"><div><strong>${esc(category(e.categoryId))} · ${esc(amount(e.amount))}</strong><small>${esc(e.reason)} · ${esc(branchById(e.branchId)?.name || 'Вся компания')}</small><small>${esc(e.start)} — ${esc(e.end)} · В этом отчёте: ${esc(amount(e.recognized))}</small><small>${e.voidedAt ? 'Отменён: ' + esc(e.voidReason) : 'Оплачено: ' + esc(amount(e.paid)) + ' · Остаток: ' + esc(amount(remaining))}</small></div>${!e.voidedAt ? `<div class="payroll-row-actions">${remaining > 0 ? `<button type="button" data-pnl-pay="${esc(e.id)}">Оплатить</button>` : ''}${!e.paid ? `<button type="button" data-pnl-void="${esc(e.id)}">Отменить расход</button>` : ''}</div>` : ''}</div>${payments.length ? `<details><summary>Оплаты (${payments.length})</summary>${payments.map(p => `<div class="payroll-record"><span>${esc(amount(p.amount))} · ${esc(p.reason)}</span><button type="button" class="secondary-action" data-pnl-reverse="${esc(p.id)}">Отменить оплату</button></div>`).join('')}</details>` : ''}</article>`;
    }).join('') || '<p class="payroll-empty">За этот период расходов по начислению ещё нет. Оплаченные обычные операции тоже включены в P&L.</p>';
  }
  const input = (name, label, value = '', extra = '') => `<label>${esc(label)}<input name="${name}" value="${esc(value)}" ${extra}></label>`;
  const hidden = (name, value) => `<input type="hidden" name="${name}" value="${esc(value)}">`;
  const reason = () => input('reason', 'Основание', '', 'required minlength="3" maxlength="1000"');
  const accountField = () => `<label>Счёт<select name="accountId" required><option value="">Выберите счёт</option>${report.accounts.map(a => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('')}</select></label>`;
  function show(action, title, fields, button = 'Сохранить') {
    if (!report || reportKey !== key() || busy) return;
    command = action; q('#pnlDialogTitle').textContent = title; q('#pnlFields').innerHTML = fields; q('#pnlSubmit').textContent = button; q('#pnlError').textContent = ''; dialog.showModal();
  }
  q('#pnlAddExpense').onclick = () => {
    if (!report) return;
    const start = report.companyToday.slice(0, 8) + '01';
    const d = new Date(report.companyToday + 'T12:00:00Z'); const end = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth()+1, 0)).toISOString().slice(0, 10);
    show('pnl.expense.create', 'Расход за период', `<p class="payroll-note">Внесите полную сумму за указанный период, например аренду за месяц. Система распределит её по календарным дням. Оплату можно провести после сохранения.</p><label>Статья расхода<select name="categoryId" required>${report.categories.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}</select></label>` + input('amount', 'Сумма за весь период', '', 'type="number" min="0.01" step="0.01" required') + input('start', 'За период с', start, 'type="date" required') + input('end', 'По', end, 'type="date" required') + `<label>Заведение<select name="branchId"><option value="">Вся компания</option>${branches.map(b => `<option value="${esc(b.id)}" ${String(report.branchId) === String(b.id) ? 'selected' : ''}>${esc(b.name)}</option>`).join('')}</select></label>` + reason());
  };
  q('#pnlExpenseList').onclick = event => {
    if (!report) return;
    const d = event.target.closest('button')?.dataset; if (!d) return;
    if (d.pnlPay) {
      const e = report.documents.find(e => e.id === d.pnlPay), due = Math.round((e.amount-e.paid)*100)/100;
      show('pnl.pay', 'Оплатить расход', hidden('expenseId', e.id) + `<p>${esc(e.reason)} · Остаток ${esc(amount(due))}. Эта оплата не уменьшит прибыль повторно.</p>` + input('amount', 'Сумма оплаты', due, `type="number" min="0.01" max="${due}" step="0.01" required`) + accountField() + reason(), 'Провести оплату');
    }
    if (d.pnlVoid) show('pnl.expense.void', 'Отменить расход', hidden('expenseId', d.pnlVoid) + '<p>Начисление будет исключено из P&L. Запись останется в истории.</p>' + reason(), 'Отменить расход');
    if (d.pnlReverse) {
      const p = report.payments.find(p => p.id === d.pnlReverse);
      show('pnl.reverse', 'Возврат оплаты', hidden('expenseId', p.expenseId) + hidden('paymentId', p.id) + `<p>Деньги (${esc(amount(p.amount))}) должны фактически вернуться на выбранный счёт. Задолженность по расходу восстановится.</p>` + accountField() + reason(), 'Провести возврат');
    }
  };
  q('#pnlForm').onsubmit = async event => {
    event.preventDefault(); if (busy || !event.target.reportValidity()) return;
    const payload = Object.fromEntries(new FormData(event.target)); if ('amount' in payload) payload.amount = Number(payload.amount);
    busy = true; q('#pnlSubmit').disabled = true; q('#pnlError').textContent = '';
    try {
      const response = await global.AshkanaApi.action(command, payload);
      hydrateServerWorkspace(response); renderAll(); dialog.close(); refresh();
    } catch (error) { q('#pnlError').textContent = error.message || 'Операция не подтверждена. Проверьте историю.'; }
    finally { busy = false; q('#pnlSubmit').disabled = false; }
  };
  ['pnlClose', 'pnlCancel'].forEach(id => q('#'+id).onclick = () => { if (!busy) dialog.close(); });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  function exportCsv() {
    if (!report || reportKey !== key()) { q('#pnlStatus').textContent = 'Дождитесь расчёта выбранного периода.'; return; }
    const rows = [['P&L', report.start, report.end], ['Валюта', report.currency], ['Выручка', report.revenue], ['Себестоимость', report.cost], ['Валовая прибыль', report.gross], ['Прочие доходы', report.otherIncome], ...report.expenseGroups.map(g => [g.name, g.amount]), ['Всего расходов', report.expenses], ['Чистая прибыль', report.net], ['Рентабельность, %', report.margin ?? ''], ...report.warnings.map(w => ['Примечание', w])];
    const cell = value => '"' + String(value ?? '').replace(/^[=+@-]/, "'$&").replaceAll('"', '""') + '"';
    const url = URL.createObjectURL(new Blob(['\ufeff' + rows.map(row => row.map(cell).join(';')).join('\r\n')], {type:'text/csv;charset=utf-8'}));
    const a = document.createElement('a'); a.href = url; a.download = `P&L-${report.start}-${report.end}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function exportXlsx() {
    if (!report || reportKey !== key()) { q('#pnlStatus').textContent = 'Дождитесь расчёта выбранного периода.'; return; }
    global.AshkanaApi.exportPnl(report.start, report.end, report.branchId).then(({xlsx, filename}) => {
      const bytes = Uint8Array.from(atob(xlsx), character => character.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
      const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }).catch(error => { q('#pnlStatus').textContent = error.message || 'Не удалось выгрузить P&L.'; });
  }
  global.OimoPnl = {refresh, exportCsv, exportXlsx, enabled, ready: () => Boolean(report && reportKey === key()), enableForTest() { force = true; refresh(); }};
  refresh();
})(window);
