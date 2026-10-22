const sessionKey = "ashkana-auth-session-v1";
const $ = (selector) => document.querySelector(selector);
let tenants = [];
let plans = [];
let connectionRequests = [];
const planLabel = code => plans.find(plan => plan.code === code)?.name || ({canteen:"Столовая", restaurant:"Ресторан", starter:"Starter (архивный)", business:"Business (архивный)", enterprise:"Enterprise (архивный)"})[code] || code;
let currentCredentials = null;
const platformLoginUrl = new URL("/login", location.origin).href;
document.querySelector("#credentialsAdminUrl").textContent = platformLoginUrl;
let editingTenantId = null;
let tenantStep = 1;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (symbol) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[symbol]);
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(value));
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 3200);
}

function randomPassword() {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%";
  const values = new Uint32Array(18);
  crypto.getRandomValues(values);
  return [...values].map((value) => alphabet[value % alphabet.length]).join("");
}

function slugify(value) {
  const map = { а:"a",б:"b",в:"v",г:"g",д:"d",е:"e",ё:"e",ж:"zh",з:"z",и:"i",й:"y",к:"k",л:"l",м:"m",н:"n",о:"o",п:"p",р:"r",с:"s",т:"t",у:"u",ф:"f",х:"h",ц:"c",ч:"ch",ш:"sh",щ:"sch",ъ:"",ы:"y",ь:"",э:"e",ю:"yu",я:"ya" };
  return String(value || "").toLowerCase().split("").map((symbol) => map[symbol] ?? symbol).join("").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48);
}

function statusLabel(status) {
  return ({ active: "Активна", suspended: "Приостановлена", archived: "В архиве", trialing: "Пробный период", past_due: "Есть задолженность", canceled: "Завершена" })[status] || status;
}

function icon(name) {
  return `<svg class="icon" aria-hidden="true"><use href="#icon-${name}"></use></svg>`;
}

function initials(value) {
  const parts = String(value || "").trim().split(/\s+/).filter(Boolean);
  return parts.slice(0, 2).map((part) => part[0]).join("") || "—";
}

function recordLabel(count) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return `${count} запись`;
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return `${count} записи`;
  return `${count} записей`;
}

function tenantLoginUrl(tenant) {
  const url = new URL("/login", location.origin);
  url.searchParams.set("mode", "admin");
  if (tenant.owner_email || tenant.owner_login) url.searchParams.set("login", tenant.owner_email || tenant.owner_login);
  return url.href;
}

function renderTenants() {
  const search = $("#tenantSearch").value.trim().toLowerCase();
  const status = $("#tenantStatusFilter").value;
  const filtered = tenants.filter((tenant) => {
    const matchesStatus = status === "all" || tenant.status === status;
    const haystack = [tenant.name, tenant.slug, tenant.owner_login, tenant.owner_email, tenant.contact_email, tenant.first_location_name, tenant.first_location_address, tenant.plan_code].join(" ").toLowerCase();
    return matchesStatus && haystack.includes(search);
  });
  $("#tenantTable").innerHTML = filtered.map((tenant) => {
    const branchCount = Number(tenant.branch_count || 0);
    const branchLimit = Number(tenant.max_branches || 0);
    const usage = branchLimit > 0 ? Math.min(100, Math.round(branchCount / branchLimit * 100)) : 0;
    const owner = tenant.owner_name || tenant.owner_login || "Не назначен";
    const nextStatus = tenant.status === "active" ? "suspended" : "active";
    const toggleLabel = tenant.status === "active" ? "Приостановить доступ" : "Возобновить доступ";
    return `
      <tr>
        <td class="company-cell"><b>${escapeHtml(tenant.name)}</b><small>${escapeHtml(tenant.slug)} · с ${formatDate(tenant.created_at)}</small>${tenant.first_location_name ? `<small>${escapeHtml(tenant.first_location_name)} · ${escapeHtml(tenant.first_location_address || "адрес не указан")}</small>` : ""}</td>
        <td><span class="plan-badge">${escapeHtml(planLabel(tenant.plan_code))}</span></td>
        <td><div class="usage-cell"><div class="usage-label"><span>${branchCount} из ${branchLimit} заведений</span><small>${usage}%</small></div><div class="usage-track"><i class="${usage >= 80 ? "near-limit" : ""}" style="width:${usage}%"></i></div></div></td>
        <td><div class="owner-cell"><span class="owner-avatar">${escapeHtml(initials(owner))}</span><div class="company-cell"><b>${escapeHtml(owner)}</b><small>${escapeHtml(tenant.owner_email || tenant.owner_login || "Email не назначен")}</small></div></div></td>
        <td><span class="status-badge ${escapeHtml(tenant.subscription_status)}">${escapeHtml(statusLabel(tenant.subscription_status))}</span>${tenant.trial_ends_at ? `<span class="subscription-date">до ${formatDate(tenant.trial_ends_at)}</span>` : ""}</td>
        <td><span class="status-badge ${escapeHtml(tenant.status)}">${escapeHtml(statusLabel(tenant.status))}</span></td>
        <td><div class="row-actions"><a class="row-action icon-button" href="${escapeHtml(tenantLoginUrl(tenant))}" target="_blank" rel="noopener noreferrer" title="Открыть вход в админку" aria-label="Открыть вход в админку">${icon("logout")}</a><button class="row-action icon-button" data-copy-login="${escapeHtml(tenant.id)}" type="button" title="Скопировать ссылку на вход" aria-label="Скопировать ссылку на вход">${icon("copy")}</button><button class="row-action icon-button" data-edit-tenant="${escapeHtml(tenant.id)}" type="button" title="Настроить клиента" aria-label="Настроить клиента">${icon("settings")}</button><button class="row-action icon-button${tenant.status === "active" ? " danger-button" : ""}" data-toggle-tenant="${escapeHtml(tenant.id)}" data-next-status="${nextStatus}" type="button" title="${toggleLabel}" aria-label="${toggleLabel}">${icon(tenant.status === "active" ? "pause" : "play")}</button><button class="row-action icon-button danger-button" data-delete-tenant="${escapeHtml(tenant.id)}" type="button" aria-label="Удалить аккаунт" title="Удалить аккаунт"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/></svg></button></div></td>
      </tr>`;
  }).join("");
  $("#tenantEmpty").classList.toggle("hidden", filtered.length > 0);
  $(".table-scroll").classList.toggle("hidden", filtered.length === 0);
  $("#tenantCount").textContent = tenants.length;
  $("#activeTenantCount").textContent = tenants.filter((tenant) => tenant.status === "active").length;
  $("#trialTenantCount").textContent = tenants.filter((tenant) => tenant.subscription_status === "trialing").length;
  $("#branchCount").textContent = tenants.reduce((sum, tenant) => sum + Number(tenant.branch_count || 0), 0);
  $("#tenantTableCount").textContent = recordLabel(filtered.length);
}

async function loadTenants() {
  tenants = await window.AshkanaApi.tenants();
  renderTenants();
}

function openTenantModal() {
  $("#tenantForm").reset();
  tenantStep = 1;
  $("#tenantSlug").dataset.edited = "";
  $("#tenantLocationName").dataset.edited = "";
  $("#tenantMaxBranches").value = "3";
  $("#tenantTrialDays").value = "14";
  $("#tenantLocationOpen").value = "08:00";
  $("#tenantLocationClose").value = "20:00";
  $("#tenantOwnerPassword").value = randomPassword();
  $("#tenantRegisterPassword").value = randomPassword();
  renderTenantStep();
  $("#tenantFormError").classList.add("hidden");
  $("#tenantModal").classList.remove("hidden");
  setTimeout(() => $("#tenantName").focus(), 20);
}

function renderTenantStep() {
  document.querySelectorAll("[data-tenant-step]").forEach((section) => section.classList.toggle("hidden", Number(section.dataset.tenantStep) !== tenantStep));
  document.querySelectorAll("[data-tenant-step-indicator]").forEach((item) => {
    const step = Number(item.dataset.tenantStepIndicator);
    item.classList.toggle("active", step === tenantStep);
    item.classList.toggle("complete", step < tenantStep);
  });
  $("#tenantBackButton").classList.toggle("hidden", tenantStep === 1);
  $("#tenantNextButton").classList.toggle("hidden", tenantStep === 3);
  $("#createTenantButton").classList.toggle("hidden", tenantStep !== 3);
}

function validateTenantStep() {
  const section = document.querySelector(`[data-tenant-step="${tenantStep}"]`);
  const invalid = [...section.querySelectorAll("input, select")].find((control) => !control.checkValidity());
  if (invalid) { invalid.reportValidity(); return false; }
  if (tenantStep === 2 && !document.querySelector('input[name="tenantServiceMode"]:checked')) {
    const errorBox = $("#tenantFormError");
    errorBox.textContent = "Выберите хотя бы один способ обслуживания гостей";
    errorBox.classList.remove("hidden");
    return false;
  }
  $("#tenantFormError").classList.add("hidden");
  return true;
}

async function createTenant(event) {
  event.preventDefault();
  const button = $("#createTenantButton");
  const errorBox = $("#tenantFormError");
  const password = $("#tenantOwnerPassword").value;
  const registerPassword = $("#tenantRegisterPassword").value;
  const email = $("#tenantOwnerEmail").value.trim().toLowerCase();
  const payload = {
    name: $("#tenantName").value.trim(),
    slug: $("#tenantSlug").value.trim().toLowerCase(),
    owner_name: $("#tenantOwnerName").value.trim(),
    email,
    phone: $("#tenantPhone").value.trim(),
    owner_login: email,
    owner_password: password,
    business_status: $("#tenantBusinessStatus").value,
    business_type: $("#tenantBusinessType").value,
    service_modes: [...document.querySelectorAll('input[name="tenantServiceMode"]:checked')].map((input) => input.value),
    employee_range: $("#tenantEmployeeRange").value,
    location_name: $("#tenantLocationName").value.trim(),
    location_address: $("#tenantLocationAddress").value.trim(),
    location_open_time: $("#tenantLocationOpen").value,
    location_close_time: $("#tenantLocationClose").value,
    register_password: registerPassword,
    plan_code: $("#tenantPlan").value,
    max_branches: Number($("#tenantMaxBranches").value),
    trial_days: Number($("#tenantTrialDays").value),
  };
  button.disabled = true;
  button.textContent = "Создаём…";
  errorBox.classList.add("hidden");
  try {
    const tenant = await window.AshkanaApi.createTenant(payload);
    currentCredentials = { name: tenant.name, login: email, password, location: payload.location_name, registerLogin: payload.slug, registerPassword };
    $("#tenantModal").classList.add("hidden");
    $("#credentialsTitle").textContent = tenant.name;
    $("#credentialsLogin").textContent = email;
    $("#credentialsPassword").textContent = password;
    $("#credentialsLocation").textContent = payload.location_name;
    $("#credentialsRegisterLogin").textContent = payload.slug;
    $("#credentialsRegisterPassword").textContent = registerPassword;
    $("#credentialsModal").classList.remove("hidden");
    $("#tenantSearch").value = "";
    $("#tenantStatusFilter").value = "all";
    tenants = [tenant, ...tenants.filter(row => row.id !== tenant.id)];
    renderTenants();
    try { await loadTenants(); }
    catch (refreshError) { showToast("Аккаунт создан, но список не обновлён: " + refreshError.message); }
  } catch (error) {
    errorBox.textContent = error.message || "Не удалось создать аккаунт";
    errorBox.classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = "Создать аккаунт";
  }
}

async function toggleTenant(button) {
  const tenant = tenants.find((entry) => entry.id === button.dataset.toggleTenant);
  if (!tenant) return;
  const nextStatus = button.dataset.nextStatus;
  const question = nextStatus === "suspended"
    ? `Приостановить доступ компании «${tenant.name}»? Все её активные сеансы будут завершены.`
    : `Возобновить доступ компании «${tenant.name}»?`;
  if (!window.confirm(question)) return;
  button.disabled = true;
  try {
    const updated = await window.AshkanaApi.updateTenant(tenant.id, { status: nextStatus });
    tenants = tenants.map((entry) => entry.id === updated.id ? updated : entry);
    renderTenants();
    showToast(nextStatus === "active" ? "Доступ компании восстановлен" : "Доступ компании приостановлен");
  } catch (error) {
    showToast(error.message || "Не удалось изменить доступ");
  } finally {
    button.disabled = false;
  }
}

function openTenantSettings(tenantId) {
  const tenant = tenants.find((entry) => entry.id === tenantId);
  if (!tenant) return;
  editingTenantId = tenant.id;
  $("#tenantSettingsTitle").textContent = tenant.name;
  $("#settingsTenantName").value = tenant.name;
  $("#settingsTenantEmail").value = tenant.contact_email || tenant.owner_login || "";
  $("#settingsTenantPhone").value = tenant.phone || "";
  $("#settingsBusinessType").value = tenant.business_type || "canteen";
  const selector = $("#settingsTenantPlan");
  selector.querySelectorAll("[data-legacy-plan]").forEach(option => option.remove());
  if (![...selector.options].some(option => option.value === tenant.plan_code)) {
    const option = new Option(planLabel(tenant.plan_code), tenant.plan_code);
    option.dataset.legacyPlan = "true";
    selector.add(option);
  }
  selector.value = tenant.plan_code;
  $("#settingsTenantMaxBranches").value = tenant.max_branches;
  $("#settingsSubscriptionStatus").value = tenant.subscription_status;
  $("#settingsTenantStatus").value = tenant.status;
  $("#settingsOwnerName").value = tenant.owner_name || "Администратор компании";
  $("#settingsOwnerLogin").value = tenant.owner_login || "";
  $("#settingsOwnerEmail").value = tenant.owner_email || "";
  $("#settingsOwnerPassword").value = "";
  $("#tenantSettingsError").classList.add("hidden");
  $("#tenantSettingsModal").classList.remove("hidden");
}

async function saveTenantSettings(event) {
  event.preventDefault();
  if (!editingTenantId) return;
  const button = $("#saveTenantSettings");
  const errorBox = $("#tenantSettingsError");
  button.disabled = true;
  button.textContent = "Сохраняем…";
  errorBox.classList.add("hidden");
  try {
    const tenant = tenants.find((entry) => entry.id === editingTenantId);
    const ownerName = $("#settingsOwnerName").value.trim();
    const ownerLogin = $("#settingsOwnerLogin").value.trim().toLowerCase();
    const ownerEmail = $("#settingsOwnerEmail").value.trim().toLowerCase();
    const ownerPassword = $("#settingsOwnerPassword").value;
    const ownerChanged = ownerName !== tenant?.owner_name || ownerLogin !== tenant?.owner_login || ownerEmail !== tenant?.owner_email || Boolean(ownerPassword);
    const requests = [window.AshkanaApi.updateTenant(editingTenantId, {
        name: $("#settingsTenantName").value.trim(),
        email: $("#settingsTenantEmail").value.trim().toLowerCase(),
        phone: $("#settingsTenantPhone").value.trim(),
        business_type: $("#settingsBusinessType").value,
        plan_code: $("#settingsTenantPlan").value,
        max_branches: Number($("#settingsTenantMaxBranches").value),
        subscription_status: $("#settingsSubscriptionStatus").value,
        status: $("#settingsTenantStatus").value,
      })];
    if (ownerChanged) requests.push(window.AshkanaApi.updateTenantOwner(editingTenantId, {
      owner_name: ownerName,
      owner_login: ownerLogin,
      owner_email: ownerEmail,
      owner_password: ownerPassword || null,
    }));
    const [updated] = await Promise.all(requests);
    if (ownerChanged) {
      updated.owner_name = ownerName;
      updated.owner_login = ownerLogin;
      updated.owner_email = ownerEmail;
    }
    tenants = tenants.map((entry) => entry.id === updated.id ? updated : entry);
    renderTenants();
    $("#tenantSettingsModal").classList.add("hidden");
    editingTenantId = null;
    showToast("Настройки компании сохранены");
  } catch (error) {
    errorBox.textContent = error.message || "Не удалось сохранить настройки";
    errorBox.classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = "Сохранить";
  }
}

async function openEvents() {
  $("#eventsModal").classList.remove("hidden");
  $("#eventsList").innerHTML = '<div class="empty-state"><p>Загружаем журнал…</p></div>';
  try {
    const events = await window.AshkanaApi.platformEvents(100);
    $("#eventsList").innerHTML = events.length ? events.map((event) => {
      const tenant = tenants.find((entry) => entry.id === event.tenant_id);
      return `<div class="event-row"><time>${new Date(event.created_at).toLocaleString("ru-RU")}</time><div><b>${escapeHtml(event.actor_login)}</b><small>${escapeHtml(tenant?.name || event.payload?.name || event.tenant_id || "Платформа")}</small></div><small>${escapeHtml(event.action === "tenant.delete" ? "Аккаунт удалён" : event.action)}</small></div>`;
    }).join("") : '<div class="empty-state"><h3>Событий пока нет</h3><p>Действия владельца платформы появятся здесь.</p></div>';
  } catch (error) {
    $("#eventsList").innerHTML = `<div class="empty-state"><h3>Не удалось загрузить журнал</h3><p>${escapeHtml(error.message)}</p></div>`;
  }
}

async function signOut() {
  try { await window.AshkanaApi.logout(); } catch (_) { /* local session is cleared below */ }
  sessionStorage.removeItem(sessionKey);
  location.replace("/login");
}

async function bootstrap() {
  try {
    const response = await window.AshkanaApi.me();
    if (response.session.role !== "platform_owner") {
      location.replace(response.session.route || "/admin");
      return;
    }
    sessionStorage.setItem(sessionKey, JSON.stringify(response.session));
    $("#sessionName").textContent = response.session.name;
    $("#sessionInitials").textContent = response.session.initials;
    await loadTenants();
    await loadPlans();
    await loadConnectionRequests();
    await loadMailStatus();
    await window.OimoBillingPanel?.load();
    await loadOperations();
  } catch (error) {
    if (error.status === 401 || error.status === 403) {
      sessionStorage.removeItem(sessionKey);
      location.replace("/login");
      return;
    }
    showToast(error.message || "Сервер недоступен");
  }
}

$("#openTenantModal").addEventListener("click", openTenantModal);
$("#tenantForm").addEventListener("submit", createTenant);
$("#tenantName").addEventListener("input", () => {
  if (!$("#tenantSlug").dataset.edited) $("#tenantSlug").value = slugify($("#tenantName").value);
  if (!$("#tenantLocationName").dataset.edited) $("#tenantLocationName").value = $("#tenantName").value.trim();
});
$("#tenantSlug").addEventListener("input", () => { $("#tenantSlug").dataset.edited = "true"; });
$("#tenantLocationName").addEventListener("input", () => { $("#tenantLocationName").dataset.edited = "true"; });
$("#generateTenantPassword").addEventListener("click", () => { $("#tenantOwnerPassword").value = randomPassword(); });
$("#generateRegisterPassword").addEventListener("click", () => { $("#tenantRegisterPassword").value = randomPassword(); });
$("#tenantNextButton").addEventListener("click", () => { if (validateTenantStep()) { tenantStep += 1; renderTenantStep(); } });
$("#tenantBackButton").addEventListener("click", () => { tenantStep = Math.max(1, tenantStep - 1); renderTenantStep(); });
$("#tenantSearch").addEventListener("input", renderTenants);
$("#tenantStatusFilter").addEventListener("change", renderTenants);
$("#tenantTable").addEventListener("click", (event) => {
  const copyButton = event.target.closest("[data-copy-login]");
  if (copyButton) {
    const tenant = tenants.find(item => item.id === copyButton.dataset.copyLogin);
    if (tenant) navigator.clipboard.writeText(tenantLoginUrl(tenant)).then(() => showToast("Ссылка скопирована"), () => showToast("Не удалось скопировать ссылку. Откройте её соседней кнопкой."));
    return;
  }
  const deleteButton = event.target.closest("[data-delete-tenant]");
  if (deleteButton) { openDeleteTenant(deleteButton.dataset.deleteTenant); return; }
  const editButton = event.target.closest("[data-edit-tenant]");
  if (editButton) { openTenantSettings(editButton.dataset.editTenant); return; }
  const toggleButton = event.target.closest("[data-toggle-tenant]");
  if (toggleButton) toggleTenant(toggleButton);
});
document.querySelectorAll("[data-close-modal]").forEach((button) => button.addEventListener("click", () => $("#tenantModal").classList.add("hidden")));
document.querySelectorAll("[data-close-credentials]").forEach((button) => button.addEventListener("click", () => { currentCredentials = null; $("#credentialsModal").classList.add("hidden"); }));
document.querySelectorAll("[data-close-settings]").forEach((button) => button.addEventListener("click", () => { editingTenantId = null; $("#tenantSettingsModal").classList.add("hidden"); }));
document.querySelectorAll("[data-close-events]").forEach((button) => button.addEventListener("click", () => $("#eventsModal").classList.add("hidden")));
$("#tenantSettingsForm").addEventListener("submit", saveTenantSettings);
$("#copyCredentialsButton").addEventListener("click", async () => {
  if (!currentCredentials) return;
  const text = `Oimo — ${currentCredentials.name}\nАдмин-панель: ${platformLoginUrl}\nEmail владельца: ${currentCredentials.login}\nПароль владельца: ${currentCredentials.password}\nЗаведение: ${currentCredentials.location}\nЛогин терминала: ${currentCredentials.registerLogin}\nПароль кассы: ${currentCredentials.registerPassword}`;
  try { await navigator.clipboard.writeText(text); showToast("Данные доступа скопированы"); } catch (_) { showToast("Не удалось скопировать автоматически"); }
});
$("#openEventsButton").addEventListener("click", openEvents);
$("#signOutButton").addEventListener("click", signOut);

bootstrap();

async function loadOperations() {
  if(typeof window.AshkanaApi.operationsStatus!=='function')return;
  const root=$('#operationsStatus'),state=$('#serviceState span');
  try{
    const data=await window.AshkanaApi.operationsStatus();root.replaceChildren();
    const rows=[['База данных',data.database?'Доступна':'Недоступна'],
      ['Доступ к аккаунтам','Восстановление пароля, подтверждение email и лимит входа включены'],
      ['Почта',data.email.configured?'SMTP настроен. Доставку подтвердите тестовым письмом.':'SMTP не настроен. Письма ожидают в очереди.'],
      ['Очередь писем',`Ожидают: ${data.email.counts.pending || 0}; ошибки: ${data.email.counts.failed || 0}`],
      ['Реквизиты продавца',data.seller.complete?'Заполнены':'Заполните реквизиты в Environment Render'],
      ['Freedom Pay',data.payments.configured?(data.payments.testing?'Тестовый режим. Нужна проверка с провайдером.':'Боевые настройки заполнены. Подтвердите контрольную оплату и возврат.'):'Подключение не завершено'],
      ['Заказы на сверку',String(data.payments.needsReview)],
      ['Проверки на рабочем сервере','Восстановление базы, нагрузка и физическое оборудование требуют отдельного подтверждения.']];
    for(const [label,value] of rows){const row=document.createElement('p'),b=document.createElement('b');b.textContent=label+': ';row.append(b,document.createTextNode(value));root.append(row);}
    state.textContent=data.email.configured&&data.seller.complete&&data.payments.configured?'Сервер доступен':'Требуется настройка';
  }catch(error){root.textContent='Не удалось проверить состояние. '+error.message;state.textContent='Состояние не проверено';}
}
$('#operationsRefresh').addEventListener('click',loadOperations);

async function loadPlans() {
  plans = await window.AshkanaApi.plans();
  $("#planCards").innerHTML = plans.map(plan => `<form class="plan-card" data-plan="${escapeHtml(plan.code)}">
    <h3>${escapeHtml(plan.name)}</h3>
    <p>${plan.code === "canteen" ? "Приготовление партиями → передача на раздачу → продажа порций. Учёт выпуска и остатков." : "Заказы по столам, печать по цехам. Приготовление по заказу, списание ингредиентов по техкарте при оплате."}</p>
    <label>Цена в месяц, сом<input name="price" type="number" min="0" max="9999999999" step="0.01" value="${Number(plan.monthly_price)}" required></label>
    <label>Цена за год, сом<input name="annualPrice" type="number" min="0" max="9999999999" step="0.01" value="${Number(plan.annual_price)}" required></label>
    <button type="submit" class="primary-button">Сохранить цену</button><span class="plan-save-status" role="status"></span>
  </form>`).join("");
  ["#tenantPlan", "#settingsTenantPlan"].forEach(id => {
    $(id).querySelectorAll("option").forEach(option => {
      const plan = plans.find(item => item.code === option.value);
      if (plan) option.textContent = `${plan.name} · ${Number(plan.monthly_price).toLocaleString("ru-RU")} сом/мес.`;
    });
  });
}
$("#planCards").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.target.closest("[data-plan]");
  if (!form || !form.reportValidity()) return;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const result = await window.AshkanaApi.updatePlan(form.dataset.plan, {monthly_price: form.elements.price.value, annual_price: form.elements.annualPrice.value});
    plans = plans.map(plan => plan.code === result.code ? result : plan);
    form.querySelector(".plan-save-status").textContent = "Цена сохранена";
    await loadPlans();
    await loadConnectionRequests();
    showToast("Цена тарифа сохранена");
  } catch (error) { form.querySelector(".plan-save-status").textContent = error.message; }
  finally { button.disabled = false; }
});

let deletingTenant = null;
let deletingBusy = false;
function openDeleteTenant(id) {
  deletingTenant = tenants.find(tenant => tenant.id === id);
  if (!deletingTenant) return;
  $("#deleteTenantName").textContent = deletingTenant.name;
  $("#deleteTenantConfirmation").value = "";
  $("#deleteTenantError").textContent = "";
  $("#confirmDeleteTenant").disabled = true;
  $("#deleteTenantDialog").showModal();
  $("#deleteTenantConfirmation").focus();
}
$("#deleteTenantConfirmation").addEventListener("input", () => {
  $("#confirmDeleteTenant").disabled = deletingBusy || $("#deleteTenantConfirmation").value !== deletingTenant?.name;
});
$("#cancelDeleteTenant").addEventListener("click", () => $("#deleteTenantDialog").close());
$("#deleteTenantDialog").addEventListener("cancel", event => { if (deletingBusy) event.preventDefault(); });
$("#deleteTenantForm").addEventListener("submit", async event => {
  event.preventDefault();
  if (deletingBusy || !deletingTenant) return;
  deletingBusy = true;
  $("#confirmDeleteTenant").disabled = true;
  $("#cancelDeleteTenant").disabled = true;
  try {
    await window.AshkanaApi.deleteTenant(deletingTenant.id, $("#deleteTenantConfirmation").value);
    tenants = tenants.filter(tenant => tenant.id !== deletingTenant.id);
    currentCredentials = null;
    renderTenants();
    $("#deleteTenantDialog").close();
    showToast("Аккаунт полностью удалён");
  } catch (error) {
    $("#deleteTenantError").textContent = error.message || "Не удалось удалить аккаунт";
  } finally {
    deletingBusy = false;
    $("#cancelDeleteTenant").disabled = false;
    $("#confirmDeleteTenant").disabled = $("#deleteTenantConfirmation").value !== deletingTenant?.name;
  }
});

async function loadConnectionRequests() {
  const list=$('#connectionRequestsList');
  try {
    connectionRequests=await window.AshkanaApi.connectionRequests();
    $('#connectionRequestCount').textContent=connectionRequests.filter(r=>r.status==='new').length || '';
    list.innerHTML=connectionRequests.length ? connectionRequests.map(row=>`<article class="connection-request-row"><div><strong>${escapeHtml(row.company)}</strong><small>${escapeHtml(row.name)} · ${escapeHtml(planLabel(row.plan))} · ${escapeHtml(formatDate(row.created_at))}</small></div><a href="tel:+${escapeHtml(row.phone)}">+${escapeHtml(row.phone)}</a><span class="request-status ${row.status==='new'?'request-new':''}">${row.status==='new'?'Новая':'Связались'}</span><div class="request-row-actions">${row.status==='new'?`<button class="secondary-button" type="button" data-contact-request="${escapeHtml(row.id)}">Связались</button>`:''}<button class="secondary-button" type="button" data-create-from-request="${escapeHtml(row.id)}">Создать аккаунт</button></div></article>`).join('') : '<p class="requests-empty">Пока нет заявок. Новые обращения с лендинга появятся здесь.</p>';
  } catch(error) {list.textContent='Не удалось загрузить заявки. '+error.message;}
}
$('#refreshConnectionRequests').addEventListener('click',async event=>{
  const button=event.currentTarget;button.disabled=true;
  try {await loadConnectionRequests();}finally{button.disabled=false;}
});
$('#connectionRequestsList').addEventListener('click',async event=>{
  const contacted=event.target.closest('[data-contact-request]');
  if(contacted){
    contacted.disabled=true;
    try{await window.AshkanaApi.markRequestContacted(contacted.dataset.contactRequest);await loadConnectionRequests();}
    catch(error){showToast(error.message);contacted.disabled=false;}
    return;
  }
  const create=event.target.closest('[data-create-from-request]');
  if(!create)return;
  const row=connectionRequests.find(item=>String(item.id)===create.dataset.createFromRequest);
  if(!row)return;
  openTenantModal();
  $('#tenantName').value=row.company;
  $('#tenantName').dispatchEvent(new Event('input',{bubbles:true}));
  $('#tenantOwnerName').value=row.name;
  $('#tenantPhone').value='+'+row.phone;
  $('#tenantPlan').value=row.plan;
});

async function loadMailStatus() {
  try {
    const data = await window.AshkanaApi.mailStatus();
    const counts = data.counts || {};
    $('#mailStatus').textContent = `${data.sender || 'Отправитель не задан'}. ${data.configured ? 'Параметры отправки заданы' : 'Проверьте SMTP_PASSWORD и SMTP_FROM в Environment сервиса Render'}. Тестовый получатель: ${data.testRecipient || 'не указан'}. В очереди: ${Number(counts.pending || 0) + Number(counts.sending || 0)}. Принято почтовым сервером: ${Number(counts.sent || 0)}. С ошибкой: ${Number(counts.failed || 0)}.`;
    $('#mailTest').disabled = !data.configured;
    $('#mailRetry').disabled = !data.configured || !Number(counts.failed || 0);
    const labels = {pending:'Ожидает отправки',sending:'Отправляется',sent:'Принято почтовым сервером',failed:'Не отправлено'};
    const errors = {SMTPAuthenticationError:'Проверьте SMTP_USERNAME и SMTP_PASSWORD',SMTPSenderRefused:'Проверьте подтверждение домена отправителя',SMTPRecipientsRefused:'Адрес получателя отклонён',TimeoutError:'Почтовый сервер не ответил',DeliveryInterrupted:'Отправка прервана'};
    $('#mailRecent').textContent = (data.recent || []).map(row => `#${row.id} · ${labels[row.status] || row.status} · попыток: ${row.attempts}${row.last_error ? ' · ' + (errors[row.last_error] || 'Ошибка соединения с почтой') : ''}`).join('\n');
  } catch (error) {
    $('#mailStatus').textContent = 'Не удалось проверить почту. ' + error.message;
  }
}
$('#mailRefresh').addEventListener('click', () => loadMailStatus());
for (const [selector, method, message] of [
  ['#mailTest','testMail','Тестовое письмо поставлено в очередь. Получатель указан в статусе почты. Обновите статус через 15 секунд.'],
  ['#mailRetry','retryMail','Письма с ошибками возвращены в очередь. Обновите статус через 15 секунд.'],
]) {
  $(selector).addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {await window.AshkanaApi[method](); $('#mailActionStatus').textContent = message;}
    catch (error) {$('#mailActionStatus').textContent = error.message;}
    finally {await loadMailStatus();}
  });
}
