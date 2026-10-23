(function (global) {
  const defaults = {
    general: { companyName: "", logo: "", timezone: "Asia/Almaty", shiftEnd: "00:00", currency: "KGS", language: "ru", floorPlan: false, fractional: false, roundTotal: false, servicePercent: 0, serviceDefault: false },
    orders: { dineIn: true, takeaway: true, defaultType: "dine-in", preparationMinutes: 20, requireCustomer: false, requireComment: false, tables: ["Стол 1", "Стол 2", "Стол 3", "Стол 4"] },
    delivery: { enabled: false, useReadyStatus: true, useDeliveredStatus: true, areas: [] },
    security: { deleteOrder: "never", discount: "never", reports: "never", closeReceipt: "never", addCustomer: "never", orderHistory: "never", addSupply: "never", refund: "never" },
    receipt: { autoPrint: false, showNumber: true, showCashier: true, showComment: false, showCustomer: false, showWifi: false, wifiName: "", wifiPassword: "", showAddress: false, city: "", address: "", phone: "", nameSource: "company", language: "ru", footer: "Спасибо за покупку!" }
  };
  const titles = { general: "Общие", billing: "Оплата подписки", orders: "Заказы", delivery: "Доставка", security: "Безопасность", receipt: "Чек" };
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const normalize = (data = {}) => Object.fromEntries(Object.entries(defaults).map(([section, values]) => [section, { ...structuredClone(values), ...data[section] }]));
  const symbols = { KGS: "сом", KZT: "₸", RUB: "₽", USD: "$", EUR: "€" };
  const currency = (value, code = "KGS") => `${Number(value || 0).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ${symbols[code] || code}`;
  function receiptHtml(sale, settings, branch = {}) {
    const { general: g, receipt: r } = normalize(settings);
    const en = r.language === "en";
    const money = value => currency(value, sale.currency || g.currency);
    const name = r.nameSource === "branch" ? branch.name || sale.branch : g.companyName || branch.name || sale.branch;
    const logo = /^data:image\/(png|jpeg|gif);base64,[A-Za-z0-9+/=]+$/.test(g.logo) ? `<img class="receipt-logo" src="${escape(g.logo)}" alt="" />` : "";
    return `${logo}<h1>${escape(name || "Oimo")}</h1>${r.showAddress ? `<p>${escape([r.city, r.address, r.phone].filter(Boolean).join(" · "))}</p>` : ""}${r.showNumber ? `<p>${en ? "Receipt" : "Чек"} №${escape(sale.number)}</p>` : ""}${sale.offlineNumber && sale.offlineNumber !== String(sale.number) ? `<small>${en ? "Offline reference" : "Автономный код"}: ${escape(sale.offlineNumber)}</small>` : ""}<p>${new Date(sale.createdAt).toLocaleString(en ? "en-GB" : "ru-RU", { timeZone: g.timezone })}</p>${r.showCashier ? `<p>${en ? "Cashier" : "Кассир"}<b>${escape(sale.cashier || "—")}</b></p>` : ""}<hr>${(sale.items || []).map(item => `<p><span>${escape(item.name)} × ${item.quantity}</span><b>${money(item.price * item.quantity)}</b></p>`).join("")}${sale.discountAmount ? `<p>${en ? "Discount" : "Скидка"}<b>−${money(sale.discountAmount)}</b></p>` : ""}${sale.serviceAmount ? `<p>${en ? "Service" : "Обслуживание"}<b>${money(sale.serviceAmount)}</b></p>` : ""}${sale.deliveryAmount ? `<p>${en ? "Delivery" : "Доставка"}<b>${money(sale.deliveryAmount)}</b></p>` : ""}${sale.rounding ? `<p>${en ? "Rounding" : "Округление"}<b>−${money(sale.rounding)}</b></p>` : ""}<hr><p><strong>${en ? "Total" : "Итого"}</strong><b>${money(sale.total)}</b></p>${(Array.isArray(sale.payments) ? sale.payments : [{method:sale.paymentMethod,amount:sale.total}]).map(part=>`<p>${escape((en ? {cash:"Cash",card:"Card",qr:"QR"} : {cash:"Наличные",card:"Карта",qr:"QR"})[part.method] || part.method)}<b>${money(part.amount)}</b></p>`).join("")}${sale.change ? `<p>${en ? "Change" : "Сдача"}<b>${money(sale.change)}</b></p>` : ""}${r.showCustomer && sale.customerName ? `<p>${escape(sale.customerName)}</p>` : ""}${sale.orderType === "delivery" ? `<p>${escape(sale.deliveryAddress)}<br>${escape(sale.deliveryPhone)}</p>` : ""}${r.showComment && sale.comment ? `<p>${escape(sale.comment)}</p>` : ""}${r.showWifi ? `<p>Wi-Fi: ${escape(r.wifiName)}<br>${en ? "Password" : "Пароль"}: ${escape(r.wifiPassword)}</p>` : ""}<small>${escape(r.footer).replace(/\n/g, "<br>")}</small>`;
  }
  let data = normalize(), draft = normalize(), session = {}, active = "general", dirty = false, options, mounted = false;
  const root = () => document.querySelector("#companySettings");
  const field = (key, label, type = "text", help = "", choices = null, extra = "") => {
    const value = draft[active]?.[key];
    const id = `setting-${active}-${key}`;
    const hint = help ? `<small id="${id}-help">${help}</small>` : "";
    const attrs = `id="${id}" name="${key}" ${help ? `aria-describedby="${id}-help"` : ""} ${extra}`;
    let input;
    if (type === "checkbox") return `<div class="settings-row settings-checkbox"><div></div><div><label><input ${attrs} type="checkbox" ${value ? "checked" : ""}>${label}</label>${hint}</div></div>`;
    if (type === "select") input = `<select ${attrs}>${choices.map(([v, title]) => `<option value="${escape(v)}" ${String(value) === String(v) ? "selected" : ""}>${title}</option>`).join("")}</select>`;
    else if (type === "textarea") input = `<textarea ${attrs} rows="3">${escape(Array.isArray(value) ? value.join("\n") : value)}</textarea>`;
    else input = `<input ${attrs} type="${type}" value="${escape(value)}">`;
    return `<div class="settings-row"><label for="${id}">${label}</label><div>${input}${hint}</div></div>`;
  };
  const group = (title, html) => `<section class="settings-group"><h2>${title}</h2>${html}</section>`;
  const unavailable = (label, reason, checked = false) => `<div class="settings-row settings-checkbox"><div></div><div><label class="settings-unavailable"><input type="checkbox" disabled ${checked ? "checked" : ""}>${label}</label><small>${reason}</small></div></div>`;
  const workspaceUrl = subdomain => {
    let domain = "oimopos.com";
    try { domain = new URL(session.workspaceUrl).hostname.split(".").slice(1).join(".") || domain; } catch (_) { /* Use the public production domain until the first session refresh. */ }
    return `https://${subdomain}.${domain}`;
  };
  function general() {
    const tz = ["Asia/Almaty", "Asia/Bishkek", "Asia/Tashkent", "Europe/Moscow", "Europe/Kyiv", "Europe/Berlin", "UTC"];
    if (!tz.includes(draft.general.timezone)) tz.push(draft.general.timezone);
    const address = session.role === "owner" ? `<div class="settings-row workspace-address-row"><label for="workspaceSubdomain">Адрес рабочего пространства</label><div><div class="workspace-address-input"><input id="workspaceSubdomain" value="${escape(session.workspaceSubdomain || "")}" maxlength="48" autocomplete="off" autocapitalize="none" spellcheck="false" aria-describedby="workspaceAddressHelp"><span>.${escape(new URL(workspaceUrl("oimo")).hostname.split(".").slice(1).join("."))}</span></div><small id="workspaceAddressHelp">По этому адресу вы и команда будете открывать кабинет компании.</small><a class="workspace-address-link" id="workspaceAddressLink" href="${escape(workspaceUrl(session.workspaceSubdomain || "oimo") + "/login")}" target="_blank" rel="noopener">${escape(workspaceUrl(session.workspaceSubdomain || "oimo"))}/login</a><div class="workspace-address-actions"><button class="secondary-action" type="button" data-save-workspace-address ${options?.saveWorkspaceAddress ? "" : "disabled"}>Сохранить адрес</button><span id="workspaceAddressStatus" role="status"></span></div></div></div>` : "";
    return group("Настройки компании", field("companyName", "Название компании", "text", "Будет печататься на чеке. Для разных названий точек выберите название заведения в настройках чека.", null, 'maxlength="120" required') + address + `<div class="settings-row"><label for="settingsLogo">Логотип</label><div><label class="settings-upload" for="settingsLogo">Загрузить…</label><input id="settingsLogo" type="file" accept="image/png,image/jpeg,image/gif" class="settings-file"><small>Будет печататься в шапке чека. JPEG, PNG или GIF, до 5 МБ.</small><div id="settingsLogoPreview">${draft.general.logo ? `<img src="${escape(draft.general.logo)}" alt="Логотип компании"><button class="danger-button" type="button" data-remove-logo>Удалить</button>` : ""}</div></div></div>`) +
      group("Общие настройки", field("timezone", "Часовой пояс", "select", "Используется при печати чеков и выборе периода в статистике.", tz.map(z => [z, z])) + field("shiftEnd", "Время окончания смены", "time", "Начало отчётного дня. Например, при 05:00 продажи после полуночи до 05:00 относятся к предыдущему дню. Смена автоматически не закрывается.") + field("currency", "Денежная единица", "select", "Меняется обозначение валюты. Суммы не конвертируются.", [["KGS", "Кыргызский сом, сом"], ["KZT", "Казахстанский тенге, ₸"], ["RUB", "Российский рубль, ₽"], ["USD", "Доллар США, $"], ["EUR", "Евро, €"]]) + field("language", "Язык", "select", "Язык интерфейса аккаунта.", [["ru", "русский"]])) +
      group("Настройки кассы", field("floorPlan", "Показывать карту зала", "checkbox", "На кассе можно выбрать стол. Список столов настраивается в разделе «Заказы».") + unavailable("Использовать быструю смену официантов на кассе", "Смена сотрудника выполняется по личному PIN.") + field("fractional", "Разрешить заказывать часть порции", "checkbox", "Количество блюда можно изменить, например, на 0,5 или 1,5. Цена и списание пересчитываются пропорционально.") + field("roundTotal", "Округлять сумму заказа", "checkbox", "Сумма заказа округляется до целого числа в меньшую сторону (например, 10,60 → 10).") + field("servicePercent", "Процент за обслуживание", "select", "", [[0, "Не использовать"], ...[5, 7, 10, 12, 15, 20, 25, 30].map(n => [n, `${n}%`])]) + field("serviceDefault", "Добавлять обслуживание по умолчанию", "checkbox", "На кассе обслуживание можно включить или выключить для отдельного заказа.")) +
      group("Настройки администрирования", unavailable("Использовать производство тех. карт и полуфабрикатов", "Производство включено: продажи блюд учитывают готовые партии на раздаче.", true) + unavailable("Использовать кассовые смены", "Смены включены для учёта продаж и наличных на кассе.", true) + unavailable("Учитывать налоги", "Расчёт налогов ещё не подключён.") + unavailable("Использовать фискализацию", "Требуется подключение фискального регистратора. Сейчас печатается обычный чек.") + unavailable("Учитывать рабочее время сотрудников", "Табель рабочего времени ещё не подключён."));
  }
  function orders() {
    return group("Заказы", field("dineIn", "В заведении", "checkbox") + field("takeaway", "С собой", "checkbox") + field("defaultType", "Тип заказа по умолчанию", "select", "Новый заказ на кассе открывается с этим типом.", [["dine-in", "В заведении"], ["takeaway", "С собой"]]) + field("preparationMinutes", "Норматив приготовления, мин", "number", "Для открытых заказов показывается время до готовности.", null, 'min="1" max="240" required') + field("requireCustomer", "Обязательно выбирать гостя", "checkbox") + field("requireComment", "Обязательно заполнять комментарий", "checkbox")) + group("Карта зала", field("tables", "Столы", "textarea", "Каждый стол с новой строки. Выбор столов включается в разделе «Общие»."));
  }
  function delivery() {
    return group("Доставка", field("enabled", "Использовать доставку", "checkbox", "На кассе появится тип заказа «Доставка», адрес и телефон получателя.") + field("useReadyStatus", "Использовать статус «Готов»", "checkbox") + field("useDeliveredStatus", "Использовать статус «Доставлен»", "checkbox")) + group("Районы и тарифы доставки", `<p class="settings-note">Стоимость доставки добавляется к сумме заказа. «Бесплатно от» = 0 означает, что бесплатная доставка не применяется.</p><div class="settings-table-scroll"><table class="settings-table"><thead><tr><th>Район</th><th>Стоимость</th><th>Бесплатно от</th><th>Время, мин</th><th></th></tr></thead><tbody>${draft.delivery.areas.map((area, index) => `<tr data-area="${index}"><td><input aria-label="Район" data-area-field="name" value="${escape(area.name)}" maxlength="80" required></td>${["cost", "freeFrom", "minutes"].map(key => `<td><input aria-label="${key === "cost" ? "Стоимость" : key === "minutes" ? "Время доставки" : "Бесплатно от"}" type="number" min="${key === "minutes" ? 1 : 0}" max="${key === "minutes" ? 1440 : 10000000}" step="${key === "minutes" ? 1 : 0.01}" data-area-field="${key}" value="${area[key]}" required></td>`).join("")}<td><button class="danger-button" type="button" data-remove-area="${index}" aria-label="Удалить район">Удалить</button></td></tr>`).join("") || '<tr><td colspan="5">Добавьте районы, в которые доставляете заказы.</td></tr>'}</tbody></table></div><button class="secondary-action settings-link" data-add-area type="button">+ Добавить район</button><p class="settings-note">Автоматическая отправка заказов курьерам и фискальные чеки требуют отдельного подключения.</p>`);
  }
  function security() {
    const labels = { deleteOrder: "При удалении отложенного заказа", discount: "При добавлении скидки", reports: "При просмотре X-отчёта", closeReceipt: "При закрытии чека", addCustomer: "При добавлении гостя на кассе", orderHistory: "При просмотре истории чеков", addSupply: "При добавлении поставки на кассе", refund: "При возврате чека" };
    return group("Безопасность", '<p class="settings-note">Для защищённых действий сотрудник входит под личным PIN управляющего или администратора зала. Права сотрудников настраиваются в разделе «Доступ».</p>') + group("Требовать подтверждение управляющего", Object.entries(labels).map(([key, label]) => field(key, label, "select", "", [["never", "Не требовать"], ["always", "Всегда"]])).join(""));
  }
  function receipt() {
    return `<div class="settings-receipt-layout"><div>${group("Настройки чека", field("autoPrint", "Печатать чек автоматически при закрытии заказа", "checkbox") + field("showNumber", "Печатать номер чека", "checkbox") + field("showCashier", "Печатать имя кассира", "checkbox") + field("showComment", "Печатать комментарий к чеку", "checkbox") + field("showCustomer", "Печатать имя гостя", "checkbox") + field("showWifi", "Печатать Wi-Fi", "checkbox") + field("wifiName", "Название сети Wi-Fi", "text", "", null, 'maxlength="120"') + field("wifiPassword", "Пароль Wi-Fi", "text", "Этот пароль будет виден гостям в чеке.", null, 'maxlength="120"') + field("showAddress", "Печатать адрес", "checkbox") + field("city", "Город") + field("address", "Адрес") + field("phone", "Телефон") + field("language", "Язык чека", "select", "", [["ru", "русский"], ["en", "English"]]) + field("nameSource", "Печатать на чеке", "select", "", [["company", "Название компании"], ["branch", "Название заведения"]]) + field("footer", "Текст в конце чека", "textarea", "Например, благодарность или приглашение вернуться."))}</div><aside class="receipt-preview"><h3>Предпросмотр чека</h3><div id="settingsReceiptPreview"></div><small>Образец, не фискальный документ</small></aside></div>`;
  }
  function billing() {
    const statuses = { trialing: "Пробный период", active: "Активна", past_due: "Ожидается оплата", canceled: "Отключена" };
    return group("Оплата подписки", `<div class="settings-row"><span>Аккаунт</span><strong>${escape(session.tenantName || session.tenantSlug || "Oimo")}</strong></div><div class="settings-row"><span>Тариф</span><strong>${escape(({canteen:"Столовая", restaurant:"Ресторан"})[session.planCode] || session.planCode || "Не указан")}</strong></div><div class="settings-row"><span>Состояние подписки</span><strong>${escape(statuses[session.subscriptionStatus] || "Не указано")}</strong></div><div class="settings-row"><span>Лимит заведений</span><strong>${escape(session.maxBranches || "—")}</strong></div>${session.trialEndsAt ? `<div class="settings-row"><span>Пробный период до</span><strong>${new Date(session.trialEndsAt).toLocaleDateString("ru-RU")}</strong></div>` : ""}<p class="settings-note">Разовая оплата месяца или года и история платежей доступны в отдельном разделе. Автоматических списаний нет.</p><p><a href="/billing">Открыть подписку и оплату →</a></p>`);
  }
  function preview() {
    const el = document.querySelector("#settingsReceiptPreview");
    if (el) el.innerHTML = receiptHtml({ number: 12, createdAt: new Date().toISOString(), cashier: "Кассир", items: [{ name: "Капучино", price: 180, quantity: 1 }, { name: "Круассан", price: 120, quantity: 1 }], total: 300, customerName: "Гость", comment: "Хорошего дня!" }, draft, { name: options.branchName() || "Заведение" });
  }
  function render() {
    if (!root()) return;
    root().innerHTML = `<form id="companySettingsForm"><div id="settingsFields">${({ general, orders, delivery, security, receipt, billing })[active]()}</div>${active !== "billing" ? '<footer class="settings-savebar"><button type="submit" class="primary-button" id="saveCompanySettings">Сохранить</button><button type="button" class="secondary-action" data-reset-settings>Отменить</button><span id="settingsSaveStatus" role="status"></span></footer>' : ""}</form>`;
    document.querySelectorAll("[data-settings-tab]").forEach(el => el.classList.toggle("active", el.dataset.settingsTab === active));
    preview();
  }
  function readDraft() {
    if (active === "billing") return;
    root().querySelectorAll("[name]").forEach(el => {
      draft[active][el.name] = el.type === "checkbox" ? el.checked : el.name === "tables" ? el.value.split("\n").map(x => x.trim()).filter(Boolean) : el.type === "number" || el.name === "servicePercent" ? Number(el.value) : el.value;
    });
    if (active === "delivery") root().querySelectorAll("[data-area]").forEach(row => row.querySelectorAll("[data-area-field]").forEach(el => { draft.delivery.areas[Number(row.dataset.area)][el.dataset.areaField] = el.type === "number" ? Number(el.value) : el.value; }));
  }
  function markDirty(message = "Есть несохранённые изменения") { dirty = true; const status = document.querySelector("#settingsSaveStatus"); if (status) status.textContent = message; }
  function open(tab = "general") {
    if (!titles[tab]) tab = "general";
    if (active !== tab) readDraft();
    active = tab;
    render();
    history.replaceState(null, "", `#settings/${tab}`);
    const crumb = document.querySelector("#breadcrumbTitle");
    if (crumb) crumb.textContent = `Настройки / ${titles[tab]}`;
    document.querySelector("#settingsNavSubmenu")?.classList.add("visible");
  }
  async function save(event) {
    event.preventDefault();
    readDraft();
    const form = event.currentTarget;
    const button = form.querySelector("#saveCompanySettings");
    const status = form.querySelector("#settingsSaveStatus");
    if (button) button.disabled = true;
    const section = active;
    const values = structuredClone(draft[section]);
    try {
      const result = await options.save(section, values);
      if (!result) throw new Error("Не удалось сохранить настройки");
      data[section] = structuredClone(values);
      dirty = JSON.stringify(data) !== JSON.stringify(draft);
      if (status?.isConnected) status.textContent = "Сохранено. Обновите кассу, чтобы применить настройки.";
    } catch (error) {
      if (status?.isConnected) status.textContent = error.message || "Не удалось сохранить настройки";
    } finally { if (button?.isConnected) button.disabled = false; }
  }
  function mount(config) {
    options = config; session = config.session;
    if (mounted) return;
    mounted = true;
    root().addEventListener("submit", save);
    root().addEventListener("input", () => { readDraft(); markDirty(); preview(); });
    root().addEventListener("input", event => {
      if (event.target.id !== "workspaceSubdomain") return;
      const value = event.target.value.trim().toLowerCase();
      const link = document.querySelector("#workspaceAddressLink");
      if (!link || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value)) return;
      const url = workspaceUrl(value);
      link.href = `${url}/login`;
      link.textContent = `${url}/login`;
    });
    root().addEventListener("change", async event => {
      if (event.target.id !== "settingsLogo") return;
      const file = event.target.files[0];
      if (!file) return;
      if (!["image/png", "image/jpeg", "image/gif"].includes(file.type) || file.size > 5 * 1024 * 1024) { options.notify("Выберите JPEG, PNG или GIF размером до 5 МБ"); return; }
      const reader = new FileReader();
      reader.onload = () => { draft.general.logo = reader.result; render(); markDirty("Логотип выбран. Нажмите «Сохранить», чтобы применить его."); };
      reader.onerror = () => options.notify("Не удалось прочитать логотип");
      reader.readAsDataURL(file);
    });
    root().addEventListener("click", event => {
      const saveAddress = event.target.closest("[data-save-workspace-address]");
      if (saveAddress) {
        const input = document.querySelector("#workspaceSubdomain");
        const status = document.querySelector("#workspaceAddressStatus");
        const previous = session.workspaceSubdomain;
        const value = input?.value.trim();
        if (!value) { if (status) status.textContent = "Укажите адрес пространства"; input?.focus(); return; }
        saveAddress.disabled = true;
        if (status) status.textContent = "Сохраняем…";
        Promise.resolve(options.saveWorkspaceAddress(value)).then(result => {
          session.workspaceSubdomain = result.workspaceSubdomain;
          session.workspaceUrl = result.workspaceUrl;
          if (status) status.textContent = "Адрес сохранён";
          const url = `${result.workspaceUrl}/login`;
          const link = document.querySelector("#workspaceAddressLink");
          if (link) { link.href = url; link.textContent = url; }
          input.value = result.workspaceSubdomain;
          if (previous && location.hostname.toLowerCase().startsWith(`${previous.toLowerCase()}.`)) location.assign(url);
        }).catch(error => { if (status) status.textContent = error.message || "Не удалось сохранить адрес"; })
          .finally(() => { if (saveAddress.isConnected) saveAddress.disabled = false; });
        return;
      }
      if (event.target.closest("[data-add-area]")) { readDraft(); draft.delivery.areas.push({ name: "", cost: 0, freeFrom: 0, minutes: 60 }); markDirty(); render(); }
      const remove = event.target.closest("[data-remove-area]");
      if (remove) { readDraft(); draft.delivery.areas.splice(Number(remove.dataset.removeArea), 1); markDirty(); render(); }
      if (event.target.closest("[data-remove-logo]")) { draft.general.logo = ""; render(); markDirty("Логотип удалён. Нажмите «Сохранить», чтобы применить изменение."); }
      if (event.target.closest("[data-reset-settings]")) { draft[active] = structuredClone(data[active]); dirty = JSON.stringify(data) !== JSON.stringify(draft); render(); }
    });
    window.addEventListener("beforeunload", event => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
    render();
  }
  function receive(settings, currentSession = session) {
    data = normalize(settings); session = currentSession;
    if (!data.general.companyName) data.general.companyName = session.tenantName || "Oimo";
    if (!dirty) { draft = structuredClone(data); if (mounted) render(); }
  }
  global.CompanySettings = { defaults, normalize, receiptHtml, currency, mount, receive, open, get currentTab() { return active; } };
})(window);
