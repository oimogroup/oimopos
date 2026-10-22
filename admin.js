const authSessionKey = "ashkana-auth-session-v1";
const pageParams = new URLSearchParams(location.search);
const testMode = pageParams.get("test") === "1";

function loadAuthSession() {
  if (testMode && pageParams.get("role") === "branch") {
    return { login: "test-branch", role: "branch", staffRole: "branch_manager", name: "Столовая №1", roleLabel: "Управляющий точки", scope: "Столовая №1 — Манаса", initials: "М1", branchId: "b1", tenantSlug: "ashkana" };
  }
  if (testMode) return { login: "test", role: "owner", name: "Тест", roleLabel: "Главный администратор", scope: "Все точки", initials: "Т" };
  try {
    const savedSession = JSON.parse(sessionStorage.getItem(authSessionKey));
    return ["owner", "branch"].includes(savedSession?.role) ? savedSession : null;
  } catch {
    return null;
  }
}

const authSession = loadAuthSession();
if (!authSession && !testMode) location.replace("/login");
const currentSession = authSession || { role: "owner", name: "Дастан", roleLabel: "Главный администратор", scope: "Все точки", initials: "ДА" };
const currentRole = currentSession.role;
const hasRole = (...roles) => roles.includes(currentRole);

window.addEventListener("pageshow", (event) => {
  if (!event.persisted || testMode) return;
  if (serverMode) { refreshServerWorkspace({ silent: false }); return; }
  let liveSession = null;
  try { liveSession = JSON.parse(sessionStorage.getItem(authSessionKey)); } catch {}
  if (!liveSession || liveSession.role !== currentRole) location.reload();
});

function signOutRevokedBranch() {
  sessionStorage.removeItem(authSessionKey);
  location.replace("/login?access=changed");
}

function checkCurrentBranchAccess() {
  if (currentRole !== "branch" || testMode) return true;
  if (serverMode) return true;
  const managedAccount = loadManagedAccounts()[currentSession.login];
  if (!managedAccount) return true;
  const revoked = managedAccount.isActive === false
    || managedAccount.branchId !== currentSession.branchId
    || Number(managedAccount.accountVersion || 1) !== Number(currentSession.accountVersion || 1);
  if (revoked) signOutRevokedBranch();
  else {
    const { password, route, ...updatedSession } = managedAccount;
    Object.assign(currentSession, updatedSession);
    sessionStorage.setItem(authSessionKey, JSON.stringify({ ...currentSession, login: currentSession.login }));
    if (document.querySelector("#sessionName")) $("#sessionName").textContent = currentSession.name;
    if (document.querySelector("#sessionInitials")) $("#sessionInitials").textContent = currentSession.initials;
    if (document.querySelector("#branchNavLabel")) $("#branchNavLabel").textContent = currentSession.scope;
    if (document.querySelector("#workspaceLabel")) $("#workspaceLabel").textContent = currentSession.scope.toLowerCase();
  }
  return !revoked;
}

const baseIngredients = [
  { id: "rice", name: "Рис лазер", category: "Крупы", unit: "кг", stock: 68, averageCost: 96, limit: 25 },
  { id: "beef", name: "Говядина", category: "Мясо", unit: "кг", stock: 32, averageCost: 520, limit: 20 },
  { id: "carrot", name: "Морковь", category: "Овощи", unit: "кг", stock: 25, averageCost: 55, limit: 10 },
  { id: "onion", name: "Лук репчатый", category: "Овощи", unit: "кг", stock: 18, averageCost: 45, limit: 10 },
  { id: "oil", name: "Масло растительное", category: "Бакалея", unit: "л", stock: 12, averageCost: 145, limit: 10 },
  { id: "salt", name: "Соль", category: "Бакалея", unit: "кг", stock: 8, averageCost: 30, limit: 3 },
  { id: "spices", name: "Специи для плова", category: "Бакалея", unit: "кг", stock: 2, averageCost: 760, limit: 1 },
  { id: "potato", name: "Картофель", category: "Овощи", unit: "кг", stock: 52, averageCost: 48, limit: 20 },
  { id: "flour", name: "Мука высший сорт", category: "Бакалея", unit: "кг", stock: 76, averageCost: 54, limit: 25 },
  { id: "chicken", name: "Курица", category: "Мясо", unit: "кг", stock: 24, averageCost: 260, limit: 15 },
  { id: "tomato", name: "Помидоры", category: "Овощи", unit: "кг", stock: 15, averageCost: 130, limit: 8 },
  { id: "tea", name: "Чай чёрный", category: "Напитки", unit: "кг", stock: 1.2, averageCost: 680, limit: 1.5 }
];

const baseRecipes = [
  { id: 201, name: "Плов праздничный", category: "Горячее", price: 230, color: "#e39a3d", yield: 380, components: [
    { ingredientId: "rice", gross: 150, net: 150 }, { ingredientId: "beef", gross: 115, net: 100 },
    { ingredientId: "carrot", gross: 82, net: 70 }, { ingredientId: "onion", gross: 35, net: 30 },
    { ingredientId: "oil", gross: 25, net: 25, measure: "мл" }, { ingredientId: "salt", gross: 3, net: 3 },
    { ingredientId: "spices", gross: 2, net: 2 }
  ]},
  { id: 203, name: "Лагман", category: "Горячее", price: 250, color: "#bd6557", yield: 450, components: [
    { ingredientId: "beef", gross: 130, net: 110 }, { ingredientId: "flour", gross: 150, net: 150 },
    { ingredientId: "onion", gross: 45, net: 40 }, { ingredientId: "tomato", gross: 90, net: 80 },
    { ingredientId: "oil", gross: 18, net: 18, measure: "мл" }, { ingredientId: "spices", gross: 2, net: 2 }
  ]},
  { id: 101, name: "Шорпо с говядиной", category: "Первые", price: 210, color: "#62a56f", yield: 420, components: [
    { ingredientId: "beef", gross: 120, net: 100 }, { ingredientId: "potato", gross: 150, net: 125 },
    { ingredientId: "carrot", gross: 35, net: 30 }, { ingredientId: "onion", gross: 30, net: 26 },
    { ingredientId: "salt", gross: 3, net: 3 }, { ingredientId: "spices", gross: 1, net: 1 }
  ]},
  { id: 205, name: "Курица запечённая", category: "Горячее", price: 180, color: "#cc7c58", yield: 210, components: [
    { ingredientId: "chicken", gross: 260, net: 200 }, { ingredientId: "oil", gross: 7, net: 7, measure: "мл" },
    { ingredientId: "salt", gross: 3, net: 3 }, { ingredientId: "spices", gross: 2, net: 2 }
  ]},
  { id: 401, name: "Салат Ачичук", category: "Салаты", price: 85, color: "#4e9b8d", yield: 160, components: [
    { ingredientId: "tomato", gross: 130, net: 120 }, { ingredientId: "onion", gross: 45, net: 38 },
    { ingredientId: "salt", gross: 2, net: 2 }
  ]}
];

const baseProducts = [
  { id: "p-1", name: "Вода 0,5 л", category: "Напитки", barcode: "4860001123456", averageCost: 28, price: 40, stock: 86, unit: "шт", limit: 20 },
  { id: "p-2", name: "Coca-Cola 0,5 л", category: "Напитки", barcode: "5449000054227", averageCost: 52, price: 80, stock: 48, unit: "шт", limit: 12 },
  { id: "p-3", name: "Сок яблочный 0,2 л", category: "Напитки", barcode: "4860012345678", averageCost: 36, price: 60, stock: 34, unit: "шт", limit: 10 },
  { id: "p-4", name: "Шоколад молочный", category: "Сладости", barcode: "4607065000781", averageCost: 45, price: 70, stock: 22, unit: "шт", limit: 8 },
  { id: "p-5", name: "Салфетки влажные", category: "Дополнительно", barcode: "4860098765432", averageCost: 12, price: 20, stock: 120, unit: "шт", limit: 25 }
];

const basePreparations = [
  { id: "pf-1", name: "Тесто для лагмана", category: "Заготовки кухни", station: "Кухня", yield: 1000, cost: 62, usedIn: "Лагман" },
  { id: "pf-2", name: "Бульон говяжий", category: "Заготовки кухни", station: "Кухня", yield: 5000, cost: 310, usedIn: "Шорпо, супы" },
  { id: "pf-3", name: "Заправка для салата", category: "Холодный цех", station: "Холодный цех", yield: 800, cost: 145, usedIn: "Салаты" }
];

const baseStations = [
  { name: "Кухня", warehouse: "Склад точки Манаса", recipes: 4, destination: "Экран кухни №1" },
  { name: "Холодный цех", warehouse: "Склад точки Манаса", recipes: 1, destination: "Принтер холодного цеха" },
  { name: "Бар", warehouse: "Склад точки Манаса", recipes: 0, destination: "Без печати" }
];

const branchesKey = "ashkana-branches-v1";
const accessAccountsKey = "ashkana-access-accounts-v1";
const baseBranches = [
  { id: "b1", number: 1, short: "Манаса", name: "Столовая №1 — Манаса", address: "Бишкек, ул. Манаса", phone: "", managerName: "Управляющий точки", login: "manasa", status: "active", route: "Поставщики → Манаса" }
];
let branches = loadBranches();

const baseSuppliers = [
  { id: "supplier-frunze", name: "Фрунзе Маркет", inn: "", contact: "Отдел поставок", phone: "+996 555 120 120", email: "", address: "Бишкек", comment: "", status: "active", locations: ["b1"] },
  { id: "supplier-alamedin", name: "Аламедин Агро", inn: "", contact: "Бакыт", phone: "+996 700 240 240", email: "", address: "Бишкек, Аламединский рынок", comment: "Овощи и бакалея", status: "active", locations: ["b1"] },
  { id: "supplier-meat", name: "Мясной двор", inn: "", contact: "Отдел продаж", phone: "+996 777 310 310", email: "", address: "Бишкек", comment: "Мясная продукция", status: "active", locations: ["b1"] }
];

const stateKey = "ashkana-admin-ingredients-v1";
const recipesKey = "ashkana-admin-recipes-v1";
const preparationsKey = "ashkana-admin-preparations-v1";
const productsKey = "ashkana-admin-products-v1";
const menuCategoriesKey = "ashkana-menu-categories-v1";
const ingredientCategoriesKey = "ashkana-ingredient-categories-v1";
const stationsKey = "ashkana-stations-v1";
const documentsKey = "ashkana-stock-documents-v1";
const logisticsKey = "ashkana-production-logistics-v3";
const suppliersKey = "ashkana-stock-suppliers-v1";
const financeKey = "ashkana-finance-v1";
const notificationReadKey = `ashkana-notifications-read-v1-${currentSession.login || currentRole}`;
const categoryPalette = ["#e39a3d", "#62a56f", "#4e9b8d", "#5b8fbd", "#bd6557", "#7b69d4"];
const $ = (selector) => document.querySelector(selector);
let companyCurrency = "KGS";
let companyGeneralSettings = {};
const money = (value) => window.CompanySettings.currency(value, companyCurrency);
const decimal = (value, digits = 1) => Number(value).toLocaleString("ru-RU", { maximumFractionDigits: digits });
const pluralRu = (value, one, few, many) => {
  const number = Math.abs(Number(value)) % 100;
  const last = number % 10;
  if (number > 10 && number < 20) return many;
  if (last === 1) return one;
  if (last > 1 && last < 5) return few;
  return many;
};
let ingredients = loadIngredients();
let recipes = loadRecipes();
let preparations = loadPreparations();
let products = loadProducts();
let menuCategories = loadMenuCategories();
let ingredientCategories = loadIngredientCategories();
let ingredientCategoryCovers = (()=>{try{return JSON.parse(localStorage.getItem("oimo-ingredient-category-covers") || "{}");}catch{return {};}})();
let stations = loadStations();
let stockDocuments = loadDocuments();
let logisticsState = loadLogisticsState();
let suppliers = loadSuppliers();
let financeState = loadFinanceState();
let currentRecipeId = null;
let currentPreparationId = null;
let editingRecipeId = null;
let editingPreparationId = null;
let editingCategoryKind = null;
let editingCategoryName = null;
let editingStationName = null;
let editingIngredientId = null;
let editingProductId = null;
let pendingCatalogDelete = null;
let editingSupplierId = null;
let supplierReturnToSupply = false;
let editingBranchId = null;
let branchLoginEdited = false;
let lastBranchAccessText = "";
let employees = [];
let posRegisters = [];
let posShifts = [];
let editingRegisterId = null;
let lastRegisterAccessText = "";
let editingEmployeeId = null;
let pendingEmployeeDeleteId = null;
let deletingEmployee = false;
let employeeDeleteTrigger = null;
let employeeLoginEdited = false;
let lastEmployeeAccessText = "";
let recipeDraftComponents = [];
let preparationDraftComponents = [];
let requestDraftItems = [];
let supplyDraftItems = [];
let supplyDraftPayments = [];
let directOrderDraftItems = [];
let pointTransferDraftItems = [];
let currentReceivingId = null;
let currentDirectReceivingId = null;
let currentDirectSendId = null;
let currentPointTransferReceivingId = null;
let currentInventoryId = null;
let currentServingBatchId = null;
let currentServingCloseId = null;
let stockDisplayScope = "branch";
let pendingOwnerObjectScope = branches[0]?.id || "b1";
let readNotificationIds = loadReadNotificationIds();
let activeDocumentFilterTab = null;
let activeAnalyticsTab = "sales";
let activeFinanceTab = "pnl";
let financeFiltersInitialized = false;
let editingFinanceAccountId = null;
let editingFinanceCategoryId = null;
let reportFiltersInitialized = false;
let serverMode = false;
let serverSales = [];
let workspaceVersion = 0;
let workspaceRefreshTimer = null;

function hydrateServerWorkspace(response) {
  const state = response?.state;
  if (!state) return false;
  document.body.dataset.serviceMode = state.serviceMode || "canteen";
  workspaceVersion = Number(response.version || workspaceVersion || 0);
  branches = Array.isArray(state.branches) ? state.branches : [];
  suppliers = Array.isArray(state.suppliers) ? state.suppliers : [];
  ingredients = Array.isArray(state.ingredients) ? state.ingredients : [];
  recipes = Array.isArray(state.recipes) ? state.recipes : [];
  products = Array.isArray(state.products) ? state.products : [];
  preparations = Array.isArray(state.preparations) ? state.preparations : [];
  menuCategories = normalizeMenuCategories(state.menuCategories);
  ingredientCategories = normalizeIngredientCategories(state.ingredientCategories);
  ingredientCategoryCovers = state.ingredientCategoryCovers || {};
  stations = normalizeStations(state.stations, false);
  logisticsState = state.logisticsState || defaultLogisticsState();
  logisticsState.stockLedger ||= [];
  logisticsState.supplies ||= [];
  serverSales = Array.isArray(state.sales) ? state.sales : [];
  financeState = normalizeFinanceState(state.financeState);
  companyGeneralSettings = state.companySettings?.general || {};
  companyCurrency = companyGeneralSettings.currency || "KGS";
  window.CompanySettings.receive(state.companySettings, currentSession);
  pendingOwnerObjectScope = currentSession.branchId || branches[0]?.id;
  return true;
}

async function runServerAction(action, payload, successMessage = "") {
  try {
    const response = await window.AshkanaApi.action(action, payload);
    hydrateServerWorkspace(response);
    renderAll();
    if (successMessage) showToast(typeof successMessage === "function" ? successMessage(response) : successMessage);
    return response;
  } catch (error) {
    if (error.status === 401) {
      sessionStorage.removeItem(authSessionKey);
      location.replace("/login?access=changed");
      return null;
    }
    showToast(error.message || "Не удалось сохранить данные на сервере");
    return null;
  }
}

async function refreshServerWorkspace({ silent = true } = {}) {
  if (!serverMode || document.querySelector(".modal-backdrop:not(.hidden), .side-drawer-backdrop:not(.hidden)")) return;
  try {
    const response = await window.AshkanaApi.workspace();
    if (Number(response.version) !== workspaceVersion) {
      hydrateServerWorkspace(response);
      renderAll();
      if (!silent) showToast("Данные обновлены с сервера");
    }
  } catch (error) {
    if (error.status === 401) {
      sessionStorage.removeItem(authSessionKey);
      location.replace("/login?access=changed");
    } else if (!silent) showToast(error.message);
  }
}

function initialPointStock() {
  return Object.fromEntries([...baseIngredients, ...baseProducts].map((entity) => [entity.id, Number(entity.stock || 0)]));
}

function initialPointCosts() {
  return Object.fromEntries([...baseIngredients, ...baseProducts].map((entity) => [entity.id, Number(entity.averageCost || 0)]));
}

function defaultLogisticsState() {
  const branchStocks = {};
  const branchCosts = {};
  branches.forEach((branch) => {
    const isSeedPoint = branch.id === "b1";
    branchStocks[branch.id] = Object.fromEntries([...baseIngredients, ...baseProducts].map((entity) => [entity.id, isSeedPoint ? Number(entity.stock || 0) : 0]));
    branchCosts[branch.id] = Object.fromEntries([...baseIngredients, ...baseProducts].map((entity) => [entity.id, isSeedPoint ? Number(entity.averageCost || 0) : 0]));
  });
  return {
    requests: [],
    branchStocks,
    branchCosts,
    directOrders: [],
    supplies: [],
    pointTransfers: [],
    inventories: [],
    batches: [],
    supplyModel: "poster"
  };
}

function loadLogisticsState() {
  try {
    const saved = JSON.parse(localStorage.getItem(logisticsKey));
    if (!saved?.requests || !saved?.branchStocks || !saved?.batches) return defaultLogisticsState();
    saved.branchCosts ||= { b1: {} };
    saved.directOrders ||= [];
    saved.supplies ||= [];
    saved.pointTransfers ||= [];
    saved.inventories ||= [];
    saved.supplyModel = "poster";
    branches.forEach((branch) => {
      saved.branchStocks[branch.id] ||= {};
      saved.branchCosts[branch.id] ||= {};
      [...ingredients, ...products].forEach((entity) => {
        if (!(entity.id in saved.branchStocks[branch.id])) saved.branchStocks[branch.id][entity.id] = branch.id === "b1" ? Number(entity.stock || 0) : 0;
        if (saved.branchCosts[branch.id][entity.id] == null) saved.branchCosts[branch.id][entity.id] = branch.id === "b1" ? Number(entity.averageCost || 0) : 0;
      });
    });
    return saved;
  } catch {
    return defaultLogisticsState();
  }
}

function saveLogisticsState() {
  if (serverMode) return;
  localStorage.setItem(logisticsKey, JSON.stringify(logisticsState));
}

function defaultFinanceState() {
  return normalizeFinanceState({ transactions: [] });
}

function normalizeFinanceState(raw = {}) {
  const finance = {
    transactions: Array.isArray(raw?.transactions) ? raw.transactions : [],
    accounts: Array.isArray(raw?.accounts) ? raw.accounts : [
      { id: "finance-bank", name: "Расчётный счёт", type: "bank", branchId: null, openingBalance: 0, status: "active" },
      { id: "finance-safe", name: "Сейф", type: "safe", branchId: null, openingBalance: 0, status: "active" }
    ],
    categories: Array.isArray(raw?.categories) ? raw.categories : [
      { id: "finance-income-other", name: "Прочие доходы", kind: "income", status: "active" },
      { id: "finance-expense-payroll", name: "Заработная плата", kind: "expense", status: "active" },
      { id: "finance-expense-rent", name: "Аренда и коммунальные", kind: "expense", status: "active" },
      { id: "finance-expense-supplies", name: "Хозяйственные расходы", kind: "expense", status: "active" },
      { id: "finance-expense-marketing", name: "Маркетинг", kind: "expense", status: "active" },
      { id: "finance-expense-tax", name: "Налоги и комиссии", kind: "expense", status: "active" },
      { id: "finance-expense-other", name: "Прочие расходы", kind: "expense", status: "active" }
    ]
  };
  branches.forEach((branch) => {
    if (!finance.accounts.some((account) => account.id === `finance-cash-${branch.id}`)) {
      finance.accounts.push({ id: `finance-cash-${branch.id}`, name: `Касса · ${branch.short}`, type: "cash", branchId: branch.id, openingBalance: 0, status: "active" });
    }
  });
  return finance;
}

function loadFinanceState() {
  try { return normalizeFinanceState(JSON.parse(localStorage.getItem(financeKey)) || {}); }
  catch { return defaultFinanceState(); }
}

function saveFinanceState() {
  if (!serverMode) localStorage.setItem(financeKey, JSON.stringify(financeState));
}

function loadIngredients() {
  try {
    const saved = JSON.parse(localStorage.getItem(stateKey));
    return Array.isArray(saved) && saved.length ? saved : structuredClone(baseIngredients);
  } catch {
    return JSON.parse(JSON.stringify(baseIngredients));
  }
}

function saveIngredients() {
  if (serverMode) return;
  localStorage.setItem(stateKey, JSON.stringify(ingredients));
}

function loadRecipes() {
  try {
    const saved = JSON.parse(localStorage.getItem(recipesKey));
    return Array.isArray(saved) && saved.length ? saved : structuredClone(baseRecipes);
  } catch {
    return JSON.parse(JSON.stringify(baseRecipes));
  }
}

function saveRecipes() {
  if (serverMode) return;
  localStorage.setItem(recipesKey, JSON.stringify(recipes));
}

function loadPreparations() {
  try {
    const saved = JSON.parse(localStorage.getItem(preparationsKey));
    return Array.isArray(saved) && saved.length ? saved : structuredClone(basePreparations);
  } catch {
    return JSON.parse(JSON.stringify(basePreparations));
  }
}

function savePreparations() {
  if (serverMode) return;
  localStorage.setItem(preparationsKey, JSON.stringify(preparations));
}

function loadProducts() {
  try {
    const saved = JSON.parse(localStorage.getItem(productsKey));
    return Array.isArray(saved) && saved.length ? saved : structuredClone(baseProducts);
  } catch {
    return JSON.parse(JSON.stringify(baseProducts));
  }
}

function saveProducts() {
  if (serverMode) return;
  localStorage.setItem(productsKey, JSON.stringify(products));
}

function normalizeMenuCategories(saved) {
  const normalized = Array.isArray(saved) ? saved.map((entry, index) => {
    const name = String(typeof entry === "string" ? entry : entry?.name || "").trim();
    const color = String(typeof entry === "object" ? entry?.color || "" : "");
    return name ? { name, image: typeof entry === "object" ? entry.image || "" : "", color: /^#[0-9a-f]{6}$/i.test(color) ? color.toLowerCase() : categoryPalette[index % categoryPalette.length] } : null;
  }).filter(Boolean) : [];
  [...recipes, ...products].forEach((entry) => {
    const name = String(entry.category || "Без категории").trim() || "Без категории";
    if (normalized.some((category) => category.name.toLowerCase() === name.toLowerCase())) return;
    const recipeColor = recipes.find((recipe) => recipe.category === name)?.color;
    normalized.push({ name, color: /^#[0-9a-f]{6}$/i.test(recipeColor || "") ? recipeColor : categoryPalette[normalized.length % categoryPalette.length] });
  });
  return normalized;
}

function normalizeIngredientCategories(saved) {
  const normalized = Array.isArray(saved) ? saved.map((entry) => String(typeof entry === "string" ? entry : entry?.name || "").trim()).filter(Boolean) : [];
  ingredients.forEach((ingredient) => {
    const name = String(ingredient.category || "Без категории").trim() || "Без категории";
    if (!normalized.some((category) => category.toLowerCase() === name.toLowerCase())) normalized.push(name);
  });
  return normalized;
}

function loadMenuCategories() {
  try {
    return normalizeMenuCategories(JSON.parse(localStorage.getItem(menuCategoriesKey)));
  } catch {
    return normalizeMenuCategories([]);
  }
}

function loadIngredientCategories() {
  try {
    return normalizeIngredientCategories(JSON.parse(localStorage.getItem(ingredientCategoriesKey)));
  } catch {
    return normalizeIngredientCategories([]);
  }
}

function saveCategoryRegistries() {
  if (serverMode) return;
  localStorage.setItem(menuCategoriesKey, JSON.stringify(menuCategories));
  localStorage.setItem(ingredientCategoriesKey, JSON.stringify(ingredientCategories));
  localStorage.setItem("oimo-ingredient-category-covers", JSON.stringify(ingredientCategoryCovers));
}

function normalizeStations(saved, useDefaults = true) {
  const source = Array.isArray(saved) && saved.length ? saved : useDefaults ? baseStations : [];
  const normalized = [];
  source.forEach((raw) => {
    const name = String(raw?.name || "").trim();
    if (!name || normalized.some((station) => station.name.toLowerCase() === name.toLowerCase())) return;
    const matchedBranch = branches.find((branch) => String(raw?.warehouse || "").includes(branch.short) || String(raw?.warehouse || "").includes(branch.name));
    const branchId = branchById(raw?.branchId)?.id || matchedBranch?.id || branches[0]?.id || "";
    normalized.push({
      name,
      branchId,
      warehouse: String(raw?.warehouse || stationWarehouseLabel({ branchId })),
      destination: String(raw?.destination || "Без печати")
    });
  });
  return normalized;
}

function loadStations() {
  try {
    return normalizeStations(JSON.parse(localStorage.getItem(stationsKey)));
  } catch {
    return normalizeStations([]);
  }
}

function saveStations() {
  if (serverMode) return;
  localStorage.setItem(stationsKey, JSON.stringify(stations));
}

function stationWarehouseLabel(station) {
  const branch = branchById(station?.branchId);
  return branch ? `Склад · ${branch.name}` : String(station?.warehouse || "Склад точки");
}

function stationNamesWithLegacy() {
  const names = stations.map((station) => station.name).filter(Boolean);
  [...recipes.map(recipeStation), ...preparations.map((preparation) => preparation.station)].filter(Boolean).forEach((name) => {
    if (!names.some((entry) => entry.toLowerCase() === String(name).toLowerCase())) names.push(String(name));
  });
  return names;
}

function loadDocuments() {
  try {
    const saved = JSON.parse(localStorage.getItem(documentsKey));
    return Array.isArray(saved) ? saved : [];
  } catch {
    return [];
  }
}

function saveDocuments() {
  if (serverMode) return;
  localStorage.setItem(documentsKey, JSON.stringify(stockDocuments));
}

function loadSuppliers() {
  try {
    const saved = JSON.parse(localStorage.getItem(suppliersKey));
    if (!Array.isArray(saved)) return baseSuppliers.map((supplier) => ({ ...supplier, locations: [...supplier.locations] }));
    return saved.map((supplier) => {
      const seeded = baseSuppliers.find((entry) => entry.id === supplier.id);
      const pointLocations = (Array.isArray(supplier.locations) ? supplier.locations : []).filter((location) => branches.some((branch) => branch.id === location));
      return { ...supplier, locations: pointLocations.length ? pointLocations : [...(seeded?.locations || (branches[0]?.id ? [branches[0].id] : []))] };
    });
  } catch {
    return baseSuppliers.map((supplier) => ({ ...supplier, locations: [...supplier.locations] }));
  }
}

function saveSuppliers() {
  if (serverMode) return;
  localStorage.setItem(suppliersKey, JSON.stringify(suppliers));
}

function loadBranches() {
  try {
    const saved = JSON.parse(localStorage.getItem(branchesKey));
    if (!Array.isArray(saved) || !saved.length) return structuredClone(baseBranches);
    const valid = saved.filter((branch) => branch?.id && branch?.name).map((branch, index) => ({
      number: index + 1,
      short: branch.name,
      address: "Бишкек",
      phone: "",
      managerName: "Управляющий точки",
      login: "",
      status: "active",
      route: `Поставщики → ${branch.short || branch.name}`,
      ...branch
    }));
    return valid.length ? valid : structuredClone(baseBranches);
  } catch {
    return structuredClone(baseBranches);
  }
}

function saveBranches() {
  if (serverMode) return;
  localStorage.setItem(branchesKey, JSON.stringify(branches));
}

function loadManagedAccounts() {
  return {};
}

function saveBranchAccount() { return true; }

function loadReadNotificationIds() {
  try {
    const saved = JSON.parse(localStorage.getItem(notificationReadKey));
    return new Set(Array.isArray(saved) ? saved : []);
  } catch {
    return new Set();
  }
}

function saveReadNotificationIds() {
  localStorage.setItem(notificationReadKey, JSON.stringify([...readNotificationIds]));
}

function supplierById(id) {
  return suppliers.find((supplier) => String(supplier.id) === String(id));
}

function addDocument(type, details) {
  const typeCount = stockDocuments.filter((document) => document.type === type).length + 1;
  const prefixes = { supply: "ПСТ", writeoff: "СПС", production: "ПРД", inventory: "ИНВ", transfer: "ПРМ" };
  const document = {
    id: `${type}-${Date.now()}`,
    type,
    number: `${prefixes[type] || "ДОК"}-${String(typeCount).padStart(4, "0")}`,
    createdAt: new Date().toISOString(),
    actor: currentSession.login || currentSession.name,
    actorName: currentSession.name,
    actorRole: currentSession.roleLabel,
    status: "Проведён",
    ...details
  };
  stockDocuments.unshift(document);
  saveDocuments();
  return document;
}

function getSales() {
  if (serverMode) return serverSales;
  try { return JSON.parse(localStorage.getItem("ashkana-pos-sales")) || []; } catch { return []; }
}

function ingredientById(id) { return ingredients.find((ingredient) => ingredient.id === id); }
function componentGross(component) { return Math.max(0, Number(component.gross ?? component.net ?? 0)); }
function componentCost(component) {
  const ingredient = ingredientById(component.ingredientId);
  return ingredient ? ingredient.averageCost * componentGross(component) / 1000 : 0;
}
function recipeCost(recipe) { return recipe.components.reduce((sum, component) => sum + componentCost(component), 0); }
function foodCost(recipe) { return recipe.price ? recipeCost(recipe) / recipe.price * 100 : 0; }
function markup(recipe) { const cost = recipeCost(recipe); return cost ? (recipe.price - cost) / cost * 100 : 0; }
function recipeStation(recipe) { return recipe.station || (recipe.category === "Салаты" ? "Холодный цех" : recipe.category === "Напитки" ? "Бар" : "Кухня"); }

function soldQuantity(productId, branchId = null) {
  return getSales()
    .filter((sale) => !branchId || sale.branchId === branchId)
    .flatMap((sale) => sale.items || [])
    .filter((item) => String(item.id) === String(productId))
    .reduce((sum, item) => sum + Number(item.quantity || 0), 0);
}

function producedQuantity(productId) {
  return stockDocuments.filter((document) => document.type === "production" && document.recipeId === productId).reduce((sum, document) => sum + document.quantity, 0);
}

function finishedStock(productId) {
  return Math.max(0, producedQuantity(productId) - soldQuantity(productId));
}

function consumedQuantity(ingredientId) {
  return recipes.reduce((sum, recipe) => {
    const component = recipe.components.find((entry) => entry.ingredientId === ingredientId);
    const salesWithoutProduction = Math.max(0, soldQuantity(recipe.id) - producedQuantity(recipe.id));
    return sum + (component ? componentGross(component) / 1000 * salesWithoutProduction : 0);
  }, 0);
}

function availableStock(ingredient) { return Math.max(0, ingredient.stock - consumedQuantity(ingredient.id)); }
function availableProductStock(product) { return Math.max(0, product.stock - soldQuantity(product.id)); }
function stockEntityById(id) { return ingredientById(id) || productById(id); }
function isProductEntity(entity) { return products.some((product) => product.id === entity?.id); }
function availableEntityStock(entity) { return isProductEntity(entity) ? availableProductStock(entity) : availableStock(entity); }

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character]));
}

function uiIcon(name) {
  return `<svg class="ui-icon" aria-hidden="true"><use href="#ui-${name}"></use></svg>`;
}

function branchById(id) { return branches.find((branch) => branch.id === id); }
function personInitials(name, fallbackNumber = "") {
  const value = String(name || "").trim().split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  return value || `Т${fallbackNumber}`;
}
function nextBranchNumber() { return Math.max(0, ...branches.map((branch) => Number(branch.number) || 0)) + 1; }
function nextBranchId() {
  let number = nextBranchNumber();
  while (branchById(`b${number}`)) number += 1;
  return `b${number}`;
}
function slugifyBranchLogin(value) {
  const map = { а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z", и: "i", й: "i", к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "c", ч: "ch", ш: "sh", щ: "sch", ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya" };
  return String(value || "").toLowerCase().split("").map((character) => map[character] ?? character).join("").replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32);
}
function generateTemporaryPassword() {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
  const values = new Uint32Array(10);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(values);
  else values.forEach((_, index) => { values[index] = Math.floor(Math.random() * 100000); });
  return [...values].map((value) => alphabet[value % alphabet.length]).join("");
}
function addConfiguredBranch(branch, openingStock = {}, openingCosts = {}) {
  if (!branch?.id || !branch?.name || branchById(branch.id)) return false;
  branches.push({ number: nextBranchNumber(), short: branch.name, address: "Бишкек", phone: "", managerName: "Управляющий точки", login: "", status: "active", route: "Поставщики → точка", ...branch });
  logisticsState.branchStocks[branch.id] = Object.fromEntries([...ingredients, ...products].map((entity) => [entity.id, Number(openingStock[entity.id] || 0)]));
  logisticsState.branchCosts[branch.id] = Object.fromEntries([...ingredients, ...products].map((entity) => [entity.id, Number(openingCosts[entity.id] ?? 0)]));
  saveBranches();
  saveLogisticsState();
  return true;
}
function logisticsRequestById(id) { return logisticsState.requests.find((request) => request.id === id); }
function logisticsBatchById(id) { return logisticsState.batches.find((batch) => batch.id === id); }
function directOrderById(id) { return logisticsState.directOrders.find((order) => order.id === id); }
function pointTransferById(id) { return logisticsState.pointTransfers.find((transfer) => transfer.id === id); }
function inventoryById(id) { return logisticsState.inventories.find((inventory) => inventory.id === id); }
function logisticsItem(itemId) { return stockEntityById(itemId); }
function branchStock(branchId, itemId) { return Number(logisticsState.branchStocks[branchId]?.[itemId] || 0); }
function branchUnitCost(branchId, itemId) { return Number(logisticsState.branchCosts?.[branchId]?.[itemId] ?? stockEntityById(itemId)?.averageCost ?? 0); }
function recipeCostForBranch(recipe, branchId) { return recipe.components.reduce((sum, component) => sum + branchUnitCost(branchId, component.ingredientId) * componentGross(component) / 1000, 0); }
function requestItemQuantity(item, field = "requested") { return Number(item[field] ?? item.requested ?? 0); }
function requestTotalQuantity(request, field = "requested") { return request.items.reduce((sum, item) => sum + requestItemQuantity(item, field), 0); }
function requestStatusLabel(status) { return ({ submitted: "Подана", approved: "К комплектации", shipped: "В пути", received: "Принята" })[status] || status; }
function directOrderStatusLabel(status) { return ({ submitted: "На согласовании", approved: "Согласован", ordered: "Отправлен поставщику", received: "Принят точкой", cancelled: "Отменён" })[status] || status; }
function supplyPaymentStatusLabel(status) { return ({ paid: "Оплачена", partial: "Частично оплачена", unpaid: "Не оплачена" })[status] || status; }
function pointTransferStatusLabel(status) { return ({ submitted: "На согласовании", approved: "К отгрузке", shipped: "В пути", received: "Принято", cancelled: "Отменено" })[status] || status; }
function inventoryStatusLabel(status) { return ({ counting: "Идёт подсчёт", submitted: "На проверке", returned: "На пересчёте", posted: "Проведена", cancelled: "Отменена" })[status] || status; }
function inventoryScopeLabel(inventory) { return inventory.scope === "category" ? inventory.category : ({selected:"Выбранные позиции",serving:"Раздача"}[inventory.scope] || "Полная"); }
function inventoryTotals(inventory) {
  return (inventory?.items || []).reduce((totals, item) => {
    if (item.actual == null) return totals;
    const difference = Math.round(Number(item.actual) * 1000) === Math.round(Number(item.book || 0) * 1000) ? 0 : Number(item.actual) - Number(item.book || 0);
    const amount = difference * Number(item.unitCost || 0);
    if (amount > 0) totals.surplus += amount;
    else totals.shortage += Math.abs(amount);
    totals.net += amount;
    totals.counted += 1;
    return totals;
  }, { surplus: 0, shortage: 0, net: 0, counted: 0 });
}
function inventoryLockForBranch(branchId) {
  return logisticsState.inventories.find((inventory) => inventory.branchId === branchId && ["counting", "submitted", "returned"].includes(inventory.status));
}
function ensureBranchStockUnlocked(branchId) {
  const inventory = inventoryLockForBranch(branchId);
  if (!inventory) return true;
  showToast(`${inventory.number}: складские движения приостановлены до завершения инвентаризации`);
  return false;
}
function pointTransferQuantity(transfer, field = "requested") { return transfer.items.reduce((sum, item) => sum + Number(item[field] ?? item.requested ?? 0), 0); }
function nextDocumentNumber(prefix, collection) { return `${prefix}-${String(collection.length + 1).padStart(4, "0")}`; }

function buildNotifications() {
  const notifications = [];
  if (document.body.dataset.serviceMode !== "restaurant" && (currentRole === "owner" || currentSession.staffRole === "branch_manager")) {
    (logisticsState.custodyDocuments || []).filter(doc => ((["writeoff","surplus"].includes(doc.kind) && doc.status === "pending") || doc.status === "review") && (currentRole === "owner" || doc.branchId === currentSession.branchId)).forEach(doc => {
      const recipe = recipes.find(recipe => String(recipe.id) === String(doc.recipeId));
      const amount = Number(doc.weight || 0);
      const portions = recipe?.yield > 0 ? amount * 1000 / recipe.yield : null;
      const quantity = portions && Math.abs(portions - Math.round(portions)) < .000001 ? `${Math.round(portions)} порц. · ${decimal(amount,3)} кг` : `${decimal(amount,3)} кг`;
      notifications.push({id:`custody-${doc.kind}-${doc.id}`,icon:"alert",tone:"warning",title:doc.status === "review" ? `Расхождение: ${doc.name || recipe?.name || "Остатки"}` : `${doc.kind === "surplus" ? "Излишек" : "Списание"}: ${recipe?.name || "Блюдо"} — ${quantity}`,text:`${branchById(doc.branchId)?.name || "Заведение"} · ${doc.actor?.name || "Сотрудник"}. ${doc.reason || "Причина не указана"}. Ожидает подтверждения.`,time:doc.createdAt,route:"logistics",custodyId:doc.id,branchId:doc.branchId});
    });
  }

  (logisticsState.supplies || []).forEach((supply) => {
    if (currentRole === "branch" && supply.branchId !== currentSession.branchId) return;
    if (Number(supply.debt || 0) <= 0) return;
    const branch = branchById(supply.branchId);
    notifications.push({ id: `${supply.id}-debt-${supply.debt}`, icon: "alert", tone: "warning", title: `Не оплачена поставка ${supply.number}`, text: `${supply.supplier} · ${branch?.short || "Заведение"} · долг ${money(supply.debt)}.`, time: supply.receivedAt || supply.createdAt, route: "inventory/supplies" });
  });

  logisticsState.pointTransfers.forEach((transfer) => {
    const source = branchById(transfer.sourceBranchId);
    const destination = branchById(transfer.destinationBranchId);
    if (transfer.status === "submitted" && currentRole === "owner") {
      notifications.push({ id: `${transfer.id}-submitted`, icon: "transfer", title: `${transfer.number} ждёт согласования`, text: `${destination?.short || "Точка"} запрашивает продукты у ${source?.short || "другой точки"}.`, time: transfer.createdAt, route: "inventory/point-transfers" });
    }
    if (transfer.status === "approved" && currentRole === "branch" && currentSession.branchId === transfer.sourceBranchId) {
      notifications.push({ id: `${transfer.id}-approved`, icon: "transfer", title: `${transfer.number} готово к отгрузке`, text: `${destination?.name || "Точка-получатель"}: подтвердите передачу товара.`, time: transfer.approvedAt, route: "inventory/point-transfers" });
    }
    if (transfer.status === "shipped" && currentRole === "branch" && currentSession.branchId === transfer.destinationBranchId) {
      notifications.push({ id: `${transfer.id}-shipped`, icon: "receive", title: `${transfer.number} отправлено на вашу точку`, text: `${source?.name || "Точка-отправитель"}: проведите фактическую приёмку.`, time: transfer.shippedAt, route: "inventory/point-transfers" });
    }
    if (transfer.status === "received" && Number(transfer.variance || 0) && currentRole === "owner") {
      notifications.push({ id: `${transfer.id}-variance-${transfer.variance}`, icon: "alert", tone: "danger", title: `Расхождение по ${transfer.number}`, text: `${destination?.short || "Точка"}: ${Number(transfer.variance) > 0 ? "+" : ""}${decimal(transfer.variance, 3)} ед.`, time: transfer.receivedAt, route: "inventory/point-transfers" });
    }
  });

  logisticsState.inventories.forEach((inventory) => {
    const branch = branchById(inventory.branchId);
    const totals = inventoryTotals(inventory);
    if (inventory.status === "submitted" && currentRole === "owner") {
      notifications.push({ id: `${inventory.id}-submitted`, icon: "checklist", title: `${inventory.number} ждёт проверки`, text: `${branch?.name || "Точка"}: расхождение ${totals.net >= 0 ? "+" : "−"}${money(Math.abs(totals.net))}.`, time: inventory.submittedAt, route: "inventory/inventories" });
    }
    if (inventory.status === "returned" && currentRole === "branch" && currentSession.branchId === inventory.branchId) {
      notifications.push({ id: `${inventory.id}-returned-${inventory.returnedAt}`, icon: "checklist", tone: "warning", title: `${inventory.number} возвращена на пересчёт`, text: inventory.reviewComment || "Главный администратор запросил повторный подсчёт.", time: inventory.returnedAt, route: "inventory/inventories" });
    }
    if (inventory.status === "posted" && currentRole === "branch" && currentSession.branchId === inventory.branchId) {
      notifications.push({ id: `${inventory.id}-posted`, icon: "checklist", title: `${inventory.number} проведена`, text: `Остатки точки скорректированы. Итог: ${totals.net >= 0 ? "+" : "−"}${money(Math.abs(totals.net))}.`, time: inventory.postedAt, route: "inventory/inventories" });
    }
  });

  const branchId = currentSession.branchId || pendingOwnerObjectScope || branches[0]?.id;
  const lowStock = [...ingredients, ...products].filter((entity) => branchStock(branchId, entity.id) <= Number(entity.limit || 0));
  if (lowStock.length) notifications.push({ id: `branch-low-${branchId}-${lowStock.map((entity) => entity.id).sort().join("-")}`, icon: "alert", tone: "warning", title: `На точке заканчиваются продукты`, text: `${lowStock.length} ${pluralRu(lowStock.length, "позиция", "позиции", "позиций")} ниже минимального остатка.`, route: "inventory/overview" });

  return notifications.sort((a, b) => new Date(b.time || 0) - new Date(a.time || 0));
}

function notificationTimeLabel(value) {
  if (!value) return "Требует внимания";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  return sameDay ? `Сегодня, ${date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}` : date.toLocaleString("ru-RU", { day: "2-digit", month: "long", hour: "2-digit", minute: "2-digit" });
}

function renderNotifications() {
  const notifications = buildNotifications();
  const unread = notifications.filter((notification) => !readNotificationIds.has(notification.id));
  const badge = $("#notificationBadge");
  badge.textContent = unread.length > 99 ? "99+" : unread.length;
  badge.classList.toggle("hidden", unread.length === 0);
  $("#notificationSummary").textContent = unread.length ? `${unread.length} ${pluralRu(unread.length, "непрочитанное", "непрочитанных", "непрочитанных")}` : "Новых нет";
  $("#markNotificationsRead").classList.toggle("hidden", unread.length === 0);
  $("#notificationList").innerHTML = notifications.length ? notifications.map((notification) => `<button class="notification-item ${notification.tone || ""} ${readNotificationIds.has(notification.id) ? "" : "unread"}" data-notification-id="${escapeHtml(notification.id)}" data-notification-route="${escapeHtml(notification.route)}" type="button"><span class="notification-item-icon">${uiIcon(notification.icon)}</span><strong>${escapeHtml(notification.title)}</strong><small>${escapeHtml(notification.text)}</small><time>${notificationTimeLabel(notification.time)}</time></button>`).join("") : `<div class="notification-empty"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18M10 21h4" /></svg><strong>Всё спокойно</strong><small>Новых событий пока нет</small></div>`;
}

function closeNotifications() {
  $("#notificationPanel").classList.add("hidden");
  $("#notificationButton").setAttribute("aria-expanded", "false");
}
function plannedRecipePortions(recipe, branchId) {
  if (serverMode) return soldQuantity(recipe.id, branchId);
  const branchIndex = Math.max(0, branches.findIndex((branch) => branch.id === branchId));
  const recipeIndex = Math.max(0, recipes.findIndex((entry) => entry.id === recipe.id));
  return Math.max(24, 92 - branchIndex * 5 - recipeIndex * 9);
}

function reservedQuantity(itemId, excludedRequestId = null) {
  return logisticsState.requests
    .filter((request) => request.id !== excludedRequestId && request.status === "approved")
    .flatMap((request) => request.items)
    .filter((item) => item.itemId === itemId)
    .reduce((sum, item) => sum + requestItemQuantity(item, "approved"), 0);
}

function populateBranchSelect(select, includeAll = false) {
  if (!select) return;
  const current = select.value;
  const availableBranches = currentRole === "branch" ? branches.filter((branch) => branch.id === currentSession.branchId) : branches;
  select.innerHTML = `${includeAll && currentRole === "owner" ? '<option value="all">Все точки</option>' : ""}${availableBranches.map((branch) => `<option value="${branch.id}">${branch.name}</option>`).join("")}`;
  if ([...select.options].some((option) => option.value === current)) select.value = current;
  else if (currentRole === "branch" && [...select.options].some((option) => option.value === currentSession.branchId)) select.value = currentSession.branchId;
}

function renderProductionRecord() {
  populateBranchSelect($("#productionBranchSelect"));
  const branchId = $("#productionBranchSelect").value || branches[0]?.id;
  if (!branchId) {
    $("#productionRecordTable").innerHTML = '<tr class="table-empty"><td colspan="10">Сначала создайте точку в разделе «Точки»</td></tr>';
    $("#productionPlanWeight").textContent = "0 кг";
    $("#productionPlanPortions").textContent = "расчёт на 0 порц.";
    $("#productionMadeWeight").textContent = "0 кг";
    $("#productionMadePercent").textContent = "0% от плана";
    $("#productionServingWeight").textContent = "0 кг";
    $("#productionServedPortions").textContent = "0 порц.";
    $("#productionLeftoverWeight").textContent = "остаток 0 кг";
    return;
  }
  const query = $("#productionSearch").value.trim().toLowerCase();
  const station = $("#productionStationFilter").value;
  const visibleRecipes = recipes.filter((recipe) => (!query || recipe.name.toLowerCase().includes(query)) && (station === "Все цеха" || recipeStation(recipe) === station));
  let totalPlanPortions = 0;
  let totalPlanWeight = 0;
  let totalMade = 0;
  let totalTransferred = 0;
  let totalServed = 0;
  let totalLeftover = 0;

  $("#productionRecordTable").innerHTML = visibleRecipes.map((recipe) => {
    const planPortions = plannedRecipePortions(recipe, branchId);
    const planWeight = planPortions * recipe.yield / 1000;
    const batches = logisticsState.batches.filter((batch) => batch.branchId === branchId && Number(batch.recipeId) === Number(recipe.id));
    const made = batches.reduce((sum, batch) => sum + Number(batch.actualWeight || 0), 0);
    const transferred = batches.reduce((sum, batch) => sum + Number(batch.transferredWeight || 0), 0);
    const served = batches.reduce((sum, batch) => sum + Number(batch.servedPortions || 0), 0);
    const leftover = batches.reduce((sum, batch) => sum + Number(batch.availableWeight ?? batch.remainingWeight ?? 0), 0);
    const activeBatch = batches.find((batch) => batch.status !== "closed");
    let status = "К приготовлению";
    let statusClass = "submitted";
    let action = currentRole === "branch" || testMode ? `<button class="operation-action secondary-action" data-plan-batch="${recipe.id}" type="button">Выпустить</button>` : "—";
    if (activeBatch) {
      const remainingToTransfer = Math.max(0, activeBatch.kitchenAvailableWeight != null ? Number(activeBatch.kitchenAvailableWeight) : Number(activeBatch.actualWeight) - Number(activeBatch.transferredWeight || 0));
      if (remainingToTransfer > .001) {
        status = activeBatch.transferredWeight ? "Передаётся" : "Готово на кухне";
        statusClass = "approved";
        action = currentRole === "branch" || testMode ? `<button class="operation-action primary primary-action" data-serving-transfer="${activeBatch.id}" type="button">На раздачу</button>` : "—";
      } else {
        status = "На раздаче";
        statusClass = "serving";
        action = currentRole === "branch" || testMode ? `<button class="operation-action secondary-action" data-serving-close="${activeBatch.id}" type="button">Закрыть</button>` : "—";
      }
    } else if (batches.length) {
      status = made >= planWeight ? "Завершено" : "Нужен довыпуск";
      statusClass = made >= planWeight ? "received" : "shipped";
    }
    totalPlanPortions += planPortions;
    totalPlanWeight += planWeight;
    totalMade += made;
    totalTransferred += transferred;
    totalServed += served;
    totalLeftover += leftover;
    return `<tr><td><strong>${escapeHtml(recipe.name)}</strong><small>${recipeStation(recipe)}</small></td><td><strong>${decimal(planWeight, 2)} кг</strong></td><td>${planPortions} порц.</td><td>${recipe.yield} г</td><td><span class="production-value ${made ? "good" : "pending"}">${made ? `${decimal(made, 2)} кг` : "—"}</span></td><td><span class="production-value ${transferred ? "good" : "pending"}">${transferred ? `${decimal(transferred, 2)} кг` : "—"}</span></td><td>${served ? `<strong>${served} порц.</strong>` : "—"}</td><td>${leftover ? `<span class="production-leftover">${decimal(leftover, 2)} кг</span>` : "—"}</td><td><span class="operation-status ${statusClass}">${status}</span></td><td>${action}</td></tr>`;
  }).join("");

  $("#productionPlanWeight").textContent = `${decimal(totalPlanWeight, 1)} кг`;
  $("#productionPlanPortions").textContent = `расчёт на ${totalPlanPortions} порц.`;
  $("#productionMadeWeight").textContent = `${decimal(totalMade, 1)} кг`;
  $("#productionMadePercent").textContent = `${decimal(totalPlanWeight ? totalMade / totalPlanWeight * 100 : 0)}% от плана`;
  $("#productionServingWeight").textContent = `${decimal(totalTransferred, 1)} кг`;
  $("#productionServedPortions").textContent = `${totalServed} порц.`;
  $("#productionLeftoverWeight").textContent = `остаток ${decimal(totalLeftover, 1)} кг`;
}

function renderProductionJournal() {
  const branchId = $("#productionBranchSelect").value || branches[0]?.id;
  if (!branchId) {
    $("#productionJournalTable").innerHTML = '<tr class="table-empty"><td colspan="7">Сначала создайте точку</td></tr>';
    return;
  }
  const batches = logisticsState.batches.filter((batch) => batch.branchId === branchId);
  $("#productionJournalTable").innerHTML = batches.length ? batches.map((batch) => {
    const recipe = recipes.find((entry) => Number(entry.id) === Number(batch.recipeId));
    const status = batch.status === "closed" ? "Закрыт" : batch.transferredWeight ? "На раздаче" : "На кухне";
    return `<tr><td><span class="document-number">${batch.number}</span><small>акт приготовления</small></td><td>${new Date(batch.createdAt).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</td><td><strong>${escapeHtml(recipe?.name || "Блюдо")}</strong><small>${recipeStation(recipe || {})}</small></td><td>${decimal(batch.actualWeight, 3)} кг</td><td>${decimal(batch.transferredWeight || 0, 3)} кг</td><td>${batch.servingTemperature != null ? `${decimal(batch.servingTemperature, 1)} °C` : "—"}</td><td><span class="operation-status ${batch.status === "closed" ? "received" : batch.transferredWeight ? "serving" : "approved"}">${status}</span></td></tr>`;
  }).join("") : '<tr class="table-empty"><td colspan="7">На выбранную дату выпусков пока нет</td></tr>';
}

function renderLogistics() {
  [$("#requestBranch"), $("#batchBranch"), $("#productionBranchSelect")].forEach((select) => populateBranchSelect(select));
  renderProductionRecord();
  renderProductionJournal();
}

function switchProductionTab(tab) {
  document.querySelectorAll("[data-production-tab]").forEach((button) => button.classList.toggle("active", button.dataset.productionTab === tab));
  document.querySelectorAll(".production-pane").forEach((pane) => pane.classList.toggle("active", pane.id === `production-pane-${tab}`));
  if (tab === "journal") renderProductionJournal();
}

function approveRequest(requestId, silent = false) {
  if (!hasRole("owner", "warehouse")) { showToast("Внутренние заявки больше не используются"); return false; }
  const request = logisticsRequestById(requestId);
  if (!request || request.status !== "submitted") return false;
  let hasShortage = false;
  request.items.forEach((item) => {
    const entity = logisticsItem(item.itemId);
    const free = Math.max(0, (entity ? availableStock(entity) : 0) - reservedQuantity(item.itemId, request.id));
    item.approved = Math.min(requestItemQuantity(item), free);
    if (item.approved + .0001 < requestItemQuantity(item)) hasShortage = true;
  });
  request.status = "approved";
  request.approvedAt = new Date().toISOString();
  request.approvedBy = currentSession.name;
  saveLogisticsState();
  if (!silent) {
    renderAll();
    showToast(hasShortage ? `${request.number}: комплектация сформирована с дефицитом` : `${request.number}: количество подтверждено складом`);
  }
  return hasShortage;
}

function approveAllRequests() {
  const pending = logisticsState.requests.filter((request) => request.status === "submitted");
  if (!pending.length) { showToast("Нет новых заявок для комплектации"); return; }
  let hasShortage = false;
  pending.forEach((request) => { if (approveRequest(request.id, true)) hasShortage = true; });
  renderAll();
  switchView("inventory");
  switchStockTab("requests");
  showToast(hasShortage ? "Комплектация сформирована, дефицит отмечен в строках" : `Сформирована комплектация по ${pending.length} заявкам`);
}

function dispatchRequest(requestId) {
  if (!hasRole("owner", "warehouse")) { showToast("Внутренние перемещения больше не используются"); return; }
  const request = logisticsRequestById(requestId);
  if (!request || request.status !== "approved") return;
  const shippedTotal = requestTotalQuantity(request, "approved");
  if (!shippedTotal) { showToast("По заявке нечего отгружать: все позиции в дефиците"); return; }
  request.items.forEach((item) => {
    const quantity = requestItemQuantity(item, "approved");
    const entity = logisticsItem(item.itemId);
    if (entity) entity.stock = Math.max(0, entity.stock - quantity);
    item.shipped = quantity;
  });
  saveIngredients();
  request.status = "shipped";
  request.shippedAt = new Date().toISOString();
  request.shippedBy = currentSession.name;
  request.transferNumber = nextDocumentNumber("ВП", logisticsState.requests.filter((entry) => entry.transferNumber));
  addDocument("transfer", { warehouse: `Архивный маршрут → ${branchById(request.branchId)?.name}`, total: request.items.reduce((sum, item) => sum + requestItemQuantity(item, "shipped") * (logisticsItem(item.itemId)?.averageCost || 0), 0), description: `${request.transferNumber} · ${decimal(shippedTotal, 2)} кг · ${request.items.length} позиций`, items: request.items.map((item) => ({ itemId: item.itemId, quantity: requestItemQuantity(item, "shipped") })) });
  saveLogisticsState();
  renderAll();
  switchView("inventory");
  switchStockTab("transfer");
  showToast(`${request.transferNumber}: архивное перемещение проведено`);
}

function openReceiving(requestId) {
  if (!hasRole("owner", "branch")) { showToast("Приёмку подтверждает сотрудник точки"); return; }
  const request = logisticsRequestById(requestId);
  if (!request || request.status !== "shipped") return;
  currentReceivingId = request.id;
  const branch = branchById(request.branchId);
  $("#receivingModalTitle").textContent = `Приёмка ${request.transferNumber}`;
  $("#receivingMeta").innerHTML = `<div><span>Отправитель</span><strong>Архивный маршрут</strong></div><div><span>Получатель</span><strong>${escapeHtml(branch?.name)}</strong></div><div><span>Отгружено</span><strong>${new Date(request.shippedAt).toLocaleString("ru-RU")}</strong></div>`;
  $("#receivingItemsEditor").innerHTML = `<div class="receiving-item-head"><span>Продукт</span><span>Отправлено</span><span>Фактически</span><span>Разница</span><span>Температура</span></div>${request.items.map((item) => {
    const entity = logisticsItem(item.itemId);
    const shipped = requestItemQuantity(item, "shipped");
    const defaultTemperature = ["Мясо", "Молочные продукты"].includes(entity?.category) ? 4 : 18;
    return `<div class="receiving-item-row" data-receiving-item="${item.itemId}" data-shipped="${shipped}"><div><strong>${escapeHtml(entity?.name || item.itemId)}</strong><small>${escapeHtml(entity?.category || "")}</small></div><span>${decimal(shipped, 3)} ${entity?.unit || "ед."}</span><input class="receiving-actual" type="number" min="0" step="0.001" value="${shipped}" /><strong class="receiving-row-variance">0</strong><div class="unit-input"><input class="receiving-temperature" type="number" step="0.1" value="${defaultTemperature}" /><b>°C</b></div></div>`;
  }).join("")}`;
  $("#receivingComment").value = "";
  updateReceivingVariance();
  $("#receivingModal").classList.remove("hidden");
}

function updateReceivingVariance() {
  let totalVariance = 0;
  let problems = 0;
  document.querySelectorAll(".receiving-item-row").forEach((row) => {
    const shipped = Number(row.dataset.shipped);
    const actual = Math.max(0, Number(row.querySelector(".receiving-actual").value || 0));
    const variance = actual - shipped;
    const output = row.querySelector(".receiving-row-variance");
    output.textContent = `${variance > 0 ? "+" : ""}${decimal(variance, 3)}`;
    output.className = `receiving-row-variance ${variance ? "deficit-value" : "available-value"}`;
    totalVariance += variance;
    if (Math.abs(variance) > .0001) problems += 1;
  });
  $("#receivingVariance").textContent = `${totalVariance > 0 ? "+" : ""}${decimal(totalVariance, 3)} кг`;
  $("#receivingVariance").className = totalVariance ? "deficit-value" : "available-value";
  $("#receivingProblemCount").textContent = problems;
}

function saveReceiving() {
  if (!hasRole("owner", "branch")) return;
  const request = logisticsRequestById(currentReceivingId);
  if (!request || request.status !== "shipped") return;
  if (!ensureBranchStockUnlocked(request.branchId)) return;
  logisticsState.branchStocks[request.branchId] ||= {};
  logisticsState.branchCosts[request.branchId] ||= {};
  let variance = 0;
  document.querySelectorAll(".receiving-item-row").forEach((row) => {
    const item = request.items.find((entry) => entry.itemId === row.dataset.receivingItem);
    const shipped = Number(row.dataset.shipped);
    const received = Math.max(0, Number(row.querySelector(".receiving-actual").value || 0));
    const oldQuantity = branchStock(request.branchId, item.itemId);
    const oldCost = branchUnitCost(request.branchId, item.itemId);
    const incomingCost = logisticsItem(item.itemId)?.averageCost || oldCost;
    item.received = received;
    item.temperature = Number(row.querySelector(".receiving-temperature").value || 0);
    logisticsState.branchStocks[request.branchId][item.itemId] = oldQuantity + received;
    if (received > 0) logisticsState.branchCosts[request.branchId][item.itemId] = (oldQuantity * oldCost + received * incomingCost) / (oldQuantity + received);
    variance += received - shipped;
  });
  request.status = "received";
  request.receivedAt = new Date().toISOString();
  request.receivedBy = currentSession.name;
  request.variance = variance;
  request.receivingComment = $("#receivingComment").value.trim();
  saveLogisticsState();
  $("#receivingModal").classList.add("hidden");
  renderAll();
  switchView("inventory");
  switchStockTab("transfer");
  showToast(`${request.transferNumber}: приёмка проведена${variance ? `, расхождение ${decimal(variance, 3)} кг` : " без расхождений"}`);
}

function openRequestForm() {
  showToast("Создайте заказ непосредственно поставщику");
  if (currentRole === "branch" || testMode) {
    switchView("inventory");
    switchStockTab("direct-orders");
    openDirectOrderForm();
  }
  return;
  populateBranchSelect($("#requestBranch"));
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  $("#requestNeededAt").value = tomorrow.toISOString().slice(0, 10);
  $("#requestComment").value = "";
  requestDraftItems = [{ itemId: ingredients[0]?.id, quantity: 5 }, { itemId: ingredients[1]?.id, quantity: 3 }];
  renderRequestItemsEditor();
  $("#requestModal").classList.remove("hidden");
}

function renderRequestItemsEditor() {
  $("#requestItemsEditor").innerHTML = `<div class="request-item-head"><span>Продукт</span><span>Количество</span><span>Ед.</span><span></span></div>${requestDraftItems.map((item, index) => {
    const entity = logisticsItem(item.itemId) || ingredients[0];
    return `<div class="request-item-row" data-request-item-index="${index}"><select class="request-item-product">${ingredients.map((ingredient) => `<option value="${ingredient.id}" ${ingredient.id === entity?.id ? "selected" : ""}>${escapeHtml(ingredient.name)}</option>`).join("")}</select><input class="request-item-quantity" type="number" min="0.001" step="0.001" value="${item.quantity}" /><b>${entity?.unit || "ед."}</b><button class="icon-button danger-button" data-remove-request-item="${index}" type="button" aria-label="Удалить позицию">${uiIcon("close")}</button></div>`;
  }).join("")}`;
}

function syncRequestDraft() {
  requestDraftItems = [...document.querySelectorAll(".request-item-row")].map((row) => ({ itemId: row.querySelector(".request-item-product").value, quantity: Math.max(0, Number(row.querySelector(".request-item-quantity").value || 0)) }));
}

function saveRequest() {
  if (!hasRole("owner", "branch")) return;
  syncRequestDraft();
  const itemsById = new Map();
  requestDraftItems.filter((item) => item.quantity > 0).forEach((item) => itemsById.set(item.itemId, (itemsById.get(item.itemId) || 0) + item.quantity));
  if (!itemsById.size) { showToast("Добавьте хотя бы один продукт и количество"); return; }
  const number = nextDocumentNumber("ЗТ", logisticsState.requests);
  logisticsState.requests.unshift({ id: `request-${Date.now()}`, number, branchId: $("#requestBranch").value, neededAt: $("#requestNeededAt").value, status: "submitted", createdAt: new Date().toISOString(), createdBy: currentSession.name, comment: $("#requestComment").value.trim(), items: [...itemsById].map(([itemId, requested]) => ({ itemId, requested })) });
  saveLogisticsState();
  $("#requestModal").classList.add("hidden");
  renderAll();
  switchView("inventory");
  switchStockTab("requests");
  showToast(`${number}: архивная заявка сохранена`);
}

function eligibleDirectSuppliers(branchId) {
  return suppliers.filter((supplier) => supplier.status === "active" && supplier.locations?.includes(branchId));
}

function directSupplierPrice(supplier, branchId, itemId) {
  return Number(supplier?.prices?.[branchId]?.[itemId] ?? branchUnitCost(branchId, itemId));
}

function populateDirectOrderSuppliers(branchId, selectedId = null) {
  const available = eligibleDirectSuppliers(branchId);
  $("#directOrderSupplier").innerHTML = available.length
    ? available.map((supplier) => `<option value="${supplier.id}">${escapeHtml(supplier.name)}</option>`).join("")
    : '<option value="">Нет поставщиков для этой точки</option>';
  if (available.some((supplier) => supplier.id === selectedId)) $("#directOrderSupplier").value = selectedId;
  return available;
}

function openDirectOrderForm() {
  if (currentRole !== "branch" && !testMode) { showToast("Прямой заказ создаёт сотрудник точки"); return; }
  populateBranchSelect($("#directOrderBranch"));
  const branchId = currentSession.branchId || branches[0]?.id;
  $("#directOrderBranch").value = branchId;
  const availableSuppliers = populateDirectOrderSuppliers(branchId);
  if (!availableSuppliers.length) { showToast("Главный администратор должен разрешить поставщика для этой точки"); return; }
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  $("#directOrderNeededAt").value = tomorrow.toISOString().slice(0, 10);
  $("#directOrderComment").value = "";
  const supplier = supplierById($("#directOrderSupplier").value);
  const firstStockItem = [...ingredients, ...products][0];
  directOrderDraftItems = firstStockItem ? [{ itemId: firstStockItem.id, quantity: 1, price: directSupplierPrice(supplier, branchId, firstStockItem.id) }] : [];
  renderDirectOrderItemsEditor();
  updateDirectOrderCalculation();
  $("#directOrderModal").classList.remove("hidden");
}

function directOrderItemOptions(selectedId) {
  return `<optgroup label="Ингредиенты">${ingredients.map((ingredient) => `<option value="${ingredient.id}" ${ingredient.id === selectedId ? "selected" : ""}>${escapeHtml(ingredient.name)}</option>`).join("")}</optgroup><optgroup label="Готовые товары">${products.map((product) => `<option value="${product.id}" ${product.id === selectedId ? "selected" : ""}>${escapeHtml(product.name)}</option>`).join("")}</optgroup>`;
}

function syncDirectOrderDraft() {
  directOrderDraftItems = [...document.querySelectorAll(".direct-order-item-row")].map((row) => ({
    itemId: row.querySelector(".direct-order-item-product").value,
    quantity: Math.max(0, Number(row.querySelector(".direct-order-item-quantity").value || 0)),
    price: Math.max(0, Number(row.querySelector(".direct-order-item-price").value || 0))
  }));
}

function renderDirectOrderItemsEditor() {
  $("#directOrderItemsEditor").innerHTML = `<div class="direct-order-item-head"><span>Продукт</span><span>Количество</span><span>Ед.</span><span>Ожидаемая цена</span><span>Сумма</span><span></span></div>${directOrderDraftItems.map((item, index) => {
    const entity = logisticsItem(item.itemId) || ingredients[0];
    return `<div class="direct-order-item-row" data-direct-order-item-index="${index}"><select class="direct-order-item-product">${directOrderItemOptions(entity?.id)}</select><input class="direct-order-item-quantity" type="number" min="0.001" step="0.001" value="${item.quantity}" /><b>${entity?.unit || "ед."}</b><input class="direct-order-item-price" type="number" min="0.01" step="0.01" value="${item.price}" /><strong class="direct-order-item-total">${money(item.quantity * item.price)}</strong><button class="icon-button danger-button" data-remove-direct-order-item="${index}" type="button" aria-label="Удалить позицию">${uiIcon("close")}</button></div>`;
  }).join("")}`;
}

function updateDirectOrderCalculation() {
  let total = 0;
  document.querySelectorAll(".direct-order-item-row").forEach((row) => {
    const entity = logisticsItem(row.querySelector(".direct-order-item-product").value);
    const quantity = Math.max(0, Number(row.querySelector(".direct-order-item-quantity").value || 0));
    const price = Math.max(0, Number(row.querySelector(".direct-order-item-price").value || 0));
    row.querySelector("b").textContent = entity?.unit || "ед.";
    row.querySelector(".direct-order-item-total").textContent = money(quantity * price);
    total += quantity * price;
  });
  $("#directOrderPositionsCount").textContent = document.querySelectorAll(".direct-order-item-row").length;
  $("#directOrderEstimatedTotal").textContent = money(total);
}

async function saveDirectOrder() {
  if (currentRole !== "branch" && !testMode) return;
  syncDirectOrderDraft();
  const branchId = $("#directOrderBranch").value;
  const supplier = supplierById($("#directOrderSupplier").value);
  const items = directOrderDraftItems.filter((item) => logisticsItem(item.itemId) && item.quantity > 0 && item.price >= 0);
  if (!supplier || !supplier.locations?.includes(branchId)) { showToast("Поставщик не обслуживает выбранную точку"); return; }
  if (!items.length || items.length !== directOrderDraftItems.length) { showToast("Заполните количество у каждой позиции"); return; }
  if (new Set(items.map((item) => item.itemId)).size !== items.length) { showToast("Одна позиция добавлена дважды — объедините количество"); return; }
  if (serverMode) {
    const response = await runServerAction("order.create", {
      supplierId: supplier.id,
      neededAt: $("#directOrderNeededAt").value,
      comment: $("#directOrderComment").value.trim(),
      items: items.map((item) => ({ itemId: item.itemId, requested: item.quantity, estimatedPrice: item.price })),
    });
    if (!response) return;
    $("#directOrderModal").classList.add("hidden");
    switchView("inventory");
    switchStockTab("direct-orders");
    showToast("Заказ отправлен главному администратору");
    return;
  }
  const number = nextDocumentNumber("ЗП", logisticsState.directOrders);
  logisticsState.directOrders.unshift({
    id: `direct-order-${Date.now()}`,
    number,
    branchId,
    supplierId: supplier.id,
    supplier: supplier.name,
    neededAt: $("#directOrderNeededAt").value,
    comment: $("#directOrderComment").value.trim(),
    items: items.map((item) => ({ itemId: item.itemId, requested: item.quantity, estimatedPrice: item.price })),
    total: items.reduce((sum, item) => sum + item.quantity * item.price, 0),
    status: "submitted",
    createdAt: new Date().toISOString(),
    createdBy: currentSession.name
  });
  saveLogisticsState();
  $("#directOrderModal").classList.add("hidden");
  renderAll();
  switchView("inventory");
  switchStockTab("direct-orders");
  showToast(`${number}: заказ отправлен на согласование`);
}

async function approveDirectOrder(orderId) {
  if (currentRole !== "owner" && !testMode) { showToast("Согласование доступно главному администратору"); return; }
  const order = directOrderById(orderId);
  if (!order || order.status !== "submitted") return;
  if (serverMode) {
    const response = await runServerAction("order.approve", { id: orderId });
    if (!response) return;
    switchView("inventory");
    switchStockTab("direct-orders");
    showToast(`${order.number}: заказ согласован`);
    return;
  }
  order.status = "approved";
  order.approvedAt = new Date().toISOString();
  order.approvedBy = currentSession.name;
  saveLogisticsState();
  renderAll();
  switchView("inventory");
  switchStockTab("direct-orders");
  showToast(`${order.number}: заказ согласован`);
}

function directOrderSendMethodLabel(method) {
  return { whatsapp: "WhatsApp", email: "Email", manual: "PDF / вручную" }[method] || "Вручную";
}

function directOrderShareText(order) {
  const branch = branchById(order.branchId);
  const lines = order.items.map((item, index) => {
    const entity = logisticsItem(item.itemId);
    return `${index + 1}. ${entity?.name || item.itemId} — ${decimal(item.requested, 3)} ${entity?.unit || "ед."} × ${money(item.estimatedPrice)} = ${money(item.requested * item.estimatedPrice)}`;
  });
  return [
    `ЗАКАЗ ПОСТАВЩИКУ ${order.number}`,
    `Получатель: ${branch?.name || "Точка"}`,
    `Поставщик: ${order.supplier}`,
    `Доставить к: ${new Date(order.neededAt).toLocaleDateString("ru-RU")}`,
    "",
    ...lines,
    "",
    `ИТОГО: ${money(order.total || 0)}`,
    order.comment ? `Условия: ${order.comment}` : "",
    `Согласовал: ${order.approvedBy || "Главный администратор"}`
  ].filter((line) => line !== "").join("\n");
}

function buildDirectOrderPrintHtml(order) {
  const supplier = supplierById(order.supplierId) || {};
  const branch = branchById(order.branchId);
  const rows = order.items.map((item, index) => {
    const entity = logisticsItem(item.itemId);
    return `<tr><td>${index + 1}</td><td><strong>${escapeHtml(entity?.name || item.itemId)}</strong></td><td>${escapeHtml(entity?.unit || "ед.")}</td><td>${decimal(item.requested, 3)}</td><td>${money(item.estimatedPrice)}</td><td><strong>${money(item.requested * item.estimatedPrice)}</strong></td></tr>`;
  }).join("");
  const supplierContacts = [supplier.contact, supplier.phone, supplier.email].filter(Boolean).map(escapeHtml).join(" · ") || "Не указаны";
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>${escapeHtml(order.number)} — заказ поставщику</title><style>
    @page{size:A4;margin:14mm}*{box-sizing:border-box}body{margin:0;color:#26363d;font-family:Arial,sans-serif;font-size:11px}header{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:18px;border-bottom:2px solid #6549d5}.brand{display:flex;align-items:center;gap:10px}.logo{width:38px;height:38px;display:grid;place-items:center;border-radius:9px;color:white;background:#6549d5;font-size:18px;font-weight:900}.brand strong{display:block;font-size:18px}.brand span{display:block;margin-top:3px;color:#78868c;font-size:10px}.number{text-align:right}.number b{display:block;color:#6549d5;font-size:18px}.number span{display:block;margin-top:4px;color:#78868c}.parties{margin-top:18px;display:grid;grid-template-columns:1fr 1fr;gap:12px}.party{padding:13px;border:1px solid #dfe5e7;border-radius:8px}.party small,.party strong,.party span{display:block}.party small{color:#7b888e;font-size:9px;text-transform:uppercase}.party strong{margin-top:7px;font-size:13px}.party span{margin-top:5px;color:#65747b;line-height:1.45}h1{margin:24px 0 5px;font-size:21px}.subtitle{color:#718087}table{width:100%;margin-top:15px;border-collapse:collapse}th{padding:10px 8px;color:#66757c;background:#f1f3f5;font-size:9px;text-align:left;text-transform:uppercase}td{padding:11px 8px;border-bottom:1px solid #e4e9eb}th:nth-child(n+3),td:nth-child(n+3){text-align:right}.total{margin-top:14px;display:flex;justify-content:flex-end;align-items:center;gap:18px}.total span{color:#718087}.total strong{color:#6549d5;font-size:20px}.conditions{margin-top:18px;padding:12px;border:1px solid #eadbad;border-radius:8px;background:#fff9ea}.conditions strong{display:block;color:#94611e}.conditions p{margin:6px 0 0;line-height:1.5}.approval{margin-top:28px;display:grid;grid-template-columns:1fr 1fr;gap:35px}.signature{padding-top:22px;border-bottom:1px solid #7d898e}.signature span{display:block;margin-bottom:6px;color:#6e7c82;font-size:9px}.notice{margin-top:24px;padding-top:10px;border-top:1px solid #e3e8ea;color:#879399;font-size:9px;line-height:1.45}@media print{body{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
  </style></head><body><header><div class="brand"><div class="logo">o</div><div><strong>Oimo</strong><span>Заказ на поставку продуктов</span></div></div><div class="number"><b>${escapeHtml(order.number)}</b><span>Создан ${new Date(order.createdAt).toLocaleDateString("ru-RU")}</span></div></header><div class="parties"><div class="party"><small>Поставщик</small><strong>${escapeHtml(order.supplier)}</strong><span>${supplier.inn ? `ИНН ${escapeHtml(supplier.inn)}<br>` : ""}${supplierContacts}${supplier.address ? `<br>${escapeHtml(supplier.address)}` : ""}</span></div><div class="party"><small>Получатель и место доставки</small><strong>${escapeHtml(branch?.name || "Точка")}</strong><span>Желаемая дата поставки: ${new Date(order.neededAt).toLocaleDateString("ru-RU")}<br>Заказ создал: ${escapeHtml(order.createdBy)}</span></div></div><h1>Заказ поставщику</h1><div class="subtitle">Пожалуйста, подтвердите наличие, окончательную цену и время доставки.</div><table><thead><tr><th>№</th><th>Продукт</th><th>Ед.</th><th>Количество</th><th>Цена</th><th>Сумма</th></tr></thead><tbody>${rows}</tbody></table><div class="total"><span>Ожидаемая сумма заказа</span><strong>${money(order.total || 0)}</strong></div>${order.comment ? `<div class="conditions"><strong>Условия и комментарий</strong><p>${escapeHtml(order.comment)}</p></div>` : ""}<div class="approval"><div><span>Согласовал: <strong>${escapeHtml(order.approvedBy || "Главный администратор")}</strong></span><div class="signature"></div></div><div><span>Подтверждение поставщика</span><div class="signature"></div></div></div><div class="notice">Это заказ покупателя, а не счёт поставщика. Итоговые цены, налоги и номер накладной подтверждает поставщик. При приёмке программа сравнит заказ с фактической поставкой.</div></body></html>`;
}

function openDirectOrderPrint(orderId = currentDirectSendId) {
  const order = directOrderById(orderId);
  if (!order) return "";
  const documentHtml = buildDirectOrderPrintHtml(order);
  if (testMode) return documentHtml;
  const printWindow = window.open("", "_blank", "width=1000,height=820");
  if (!printWindow) { showToast("Браузер заблокировал окно печати"); return ""; }
  printWindow.opener = null;
  printWindow.document.open();
  printWindow.document.write(documentHtml);
  printWindow.document.close();
  order.documentGeneratedAt = new Date().toISOString();
  order.documentGeneratedBy = currentSession.name;
  saveLogisticsState();
  setTimeout(() => { printWindow.focus(); printWindow.print(); }, 250);
  return documentHtml;
}

function openDirectOrderSend(orderId) {
  if (currentRole !== "branch" && !testMode) { showToast("Заказ поставщику отправляет точка"); return; }
  const order = directOrderById(orderId);
  if (!order || order.status !== "approved") return;
  const supplier = supplierById(order.supplierId) || {};
  const branch = branchById(order.branchId);
  const phoneDigits = String(supplier.phone || "").replace(/\D/g, "");
  const email = String(supplier.email || "").trim();
  currentDirectSendId = order.id;
  $("#directOrderSendTitle").textContent = `${order.number} · ${order.supplier}`;
  $("#directSendMeta").innerHTML = `<div><span>Поставщик</span><strong>${escapeHtml(order.supplier)}</strong><small>${escapeHtml([supplier.contact, supplier.phone, supplier.email].filter(Boolean).join(" · ") || "Контакты не указаны")}</small></div><div><span>Получатель</span><strong>${escapeHtml(branch?.name || "Точка")}</strong><small>${order.items.length} позиций</small></div><div><span>Доставить к</span><strong>${new Date(order.neededAt).toLocaleDateString("ru-RU")}</strong><small>Согласовал: ${escapeHtml(order.approvedBy || "—")}</small></div>`;
  $("#directSendDocumentTotal").textContent = money(order.total || 0);
  $("#directSendLines").innerHTML = '<div class="direct-send-line direct-send-line-head"><i>№</i><span>Продукт</span><span>Кол-во</span><span>Цена</span><b>Сумма</b></div>' + order.items.map((item, index) => {
    const entity = logisticsItem(item.itemId);
    return `<div class="direct-send-line"><i>${index + 1}</i><strong>${escapeHtml(entity?.name || item.itemId)}</strong><span>${decimal(item.requested, 3)} ${entity?.unit || "ед."}</span><span>${money(item.estimatedPrice)}</span><b>${money(item.requested * item.estimatedPrice)}</b></div>`;
  }).join("");
  const whatsappInput = document.querySelector('input[name="directSendChannel"][value="whatsapp"]');
  const emailInput = document.querySelector('input[name="directSendChannel"][value="email"]');
  const manualInput = document.querySelector('input[name="directSendChannel"][value="manual"]');
  whatsappInput.disabled = phoneDigits.length < 9;
  emailInput.disabled = !email;
  $("#directSendWhatsappRecipient").textContent = supplier.phone || "Телефон не указан";
  $("#directSendEmailRecipient").textContent = email || "Email не указан";
  (whatsappInput.disabled ? emailInput.disabled ? manualInput : emailInput : whatsappInput).checked = true;
  $("#directOrderSendModal").classList.remove("hidden");
}

async function sendDirectOrderToSupplier(orderId, sendMethod = "manual", sentTo = "") {
  if (currentRole !== "branch" && !testMode) { showToast("Заказ поставщику отправляет точка"); return; }
  const order = directOrderById(orderId);
  if (!order || order.status !== "approved") return;
  if (serverMode) {
    const response = await runServerAction("order.send", { id: orderId, method: sendMethod, recipient: sentTo });
    if (!response) return;
    switchView("inventory");
    switchStockTab("direct-orders");
    showToast(`${order.number}: отправлен через ${directOrderSendMethodLabel(sendMethod)}`);
    return;
  }
  order.status = "ordered";
  order.orderedAt = new Date().toISOString();
  order.orderedBy = currentSession.name;
  order.sentVia = sendMethod;
  order.sentTo = sentTo || directOrderSendMethodLabel(sendMethod);
  saveLogisticsState();
  renderAll();
  switchView("inventory");
  switchStockTab("direct-orders");
  showToast(`${order.number}: отправлен через ${directOrderSendMethodLabel(sendMethod)}`);
}

async function confirmDirectOrderSend() {
  const order = directOrderById(currentDirectSendId);
  const supplier = supplierById(order?.supplierId) || {};
  const channel = document.querySelector('input[name="directSendChannel"]:checked')?.value;
  if (!order || !channel) { showToast("Выберите способ отправки"); return; }
  let recipient = "Передан вручную";
  if (channel === "whatsapp") {
    const phone = String(supplier.phone || "").replace(/\D/g, "");
    if (phone.length < 9) { showToast("У поставщика не указан телефон"); return; }
    recipient = supplier.phone;
    if (!testMode) window.open(`https://wa.me/${phone}?text=${encodeURIComponent(directOrderShareText(order))}`, "_blank", "noopener,noreferrer");
  } else if (channel === "email") {
    if (!supplier.email) { showToast("У поставщика не указан email"); return; }
    recipient = supplier.email;
    const subject = encodeURIComponent(`Заказ поставщику ${order.number}`);
    const body = encodeURIComponent(directOrderShareText(order));
    if (!testMode) window.open(`mailto:${supplier.email}?subject=${subject}&body=${body}`, "_blank", "noopener,noreferrer");
  }
  $("#directOrderSendModal").classList.add("hidden");
  await sendDirectOrderToSupplier(order.id, channel, recipient);
  currentDirectSendId = null;
}

function openDirectReceiving(orderId) {
  if (currentRole !== "branch" && !testMode) { showToast("Прямую поставку принимает сотрудник точки"); return; }
  const order = directOrderById(orderId);
  if (!order || order.status !== "ordered") return;
  if (!ensureBranchStockUnlocked(order.branchId)) return;
  currentDirectReceivingId = order.id;
  const branch = branchById(order.branchId);
  $("#directReceivingTitle").textContent = `${order.number} · ${order.supplier}`;
  $("#directReceivingMeta").innerHTML = `<div><span>Поставщик</span><strong>${escapeHtml(order.supplier)}</strong></div><div><span>Получатель</span><strong>${escapeHtml(branch?.name || "Точка")}</strong></div><div><span>Заказано к дате</span><strong>${new Date(order.neededAt).toLocaleDateString("ru-RU")}</strong></div>`;
  const now = new Date();
  $("#directReceivingAt").value = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  $("#directReceivingInvoice").value = "";
  $("#directReceivingComment").value = "";
  $("#directReceivingItemsEditor").innerHTML = `<div class="direct-receiving-item-head"><span>Продукт</span><span>Заказано</span><span>Фактически</span><span>Цена</span><span>Температура</span><span>Сумма</span></div>${order.items.map((item) => {
    const entity = logisticsItem(item.itemId);
    return `<div class="direct-receiving-item-row" data-direct-receiving-item="${item.itemId}" data-requested="${item.requested}"><div><strong>${escapeHtml(entity?.name || item.itemId)}</strong><small>${escapeHtml(entity?.category || "")}</small></div><span>${decimal(item.requested, 3)} ${entity?.unit || "ед."}</span><input class="direct-receiving-actual" type="number" min="0" step="0.001" value="${item.requested}" /><input class="direct-receiving-price" type="number" min="0.01" step="0.01" value="${item.estimatedPrice}" /><div class="unit-input"><input class="direct-receiving-temperature" type="number" step="0.1" value="${["Мясо", "Молочные продукты"].includes(entity?.category) ? 4 : 18}" /><b>°C</b></div><strong class="direct-receiving-line-total">${money(item.requested * item.estimatedPrice)}</strong></div>`;
  }).join("")}`;
  updateDirectReceivingCalculation();
  $("#directReceivingModal").classList.remove("hidden");
}

function updateDirectReceivingCalculation() {
  let total = 0;
  let variance = 0;
  document.querySelectorAll(".direct-receiving-item-row").forEach((row) => {
    const actual = Math.max(0, Number(row.querySelector(".direct-receiving-actual").value || 0));
    const price = Math.max(0, Number(row.querySelector(".direct-receiving-price").value || 0));
    variance += actual - Number(row.dataset.requested);
    total += actual * price;
    row.querySelector(".direct-receiving-line-total").textContent = money(actual * price);
  });
  $("#directReceivingTotal").textContent = money(total);
  $("#directReceivingVariance").textContent = `${variance > 0 ? "+" : ""}${decimal(variance, 3)} ед.`;
  $("#directReceivingVariance").className = Math.abs(variance) > .0001 ? "deficit-value" : "available-value";
}

async function saveDirectReceiving() {
  if (currentRole !== "branch" && !testMode) return;
  const order = directOrderById(currentDirectReceivingId);
  if (!order || order.status !== "ordered") return;
  const branchId = order.branchId;
  if (!ensureBranchStockUnlocked(branchId)) return;
  const supplier = supplierById(order.supplierId);
  logisticsState.branchStocks[branchId] ||= {};
  logisticsState.branchCosts[branchId] ||= {};
  supplier.prices ||= {};
  supplier.prices[branchId] ||= {};
  const receivingRows = [...document.querySelectorAll(".direct-receiving-item-row")];
  if (receivingRows.some((row) => Number(row.querySelector(".direct-receiving-actual").value || 0) > 0 && Number(row.querySelector(".direct-receiving-price").value || 0) <= 0)) {
    showToast("Укажите фактическую цену у каждой принятой позиции");
    return;
  }
  const invoiceNumber = $("#directReceivingInvoice").value.trim();
  if (serverMode && !invoiceNumber) { showToast("Укажите номер накладной поставщика"); return; }
  if (serverMode) {
    const response = await runServerAction("order.receive", {
      id: order.id,
      invoiceNumber,
      receivedAt: $("#directReceivingAt").value ? new Date($("#directReceivingAt").value).toISOString() : null,
      comment: $("#directReceivingComment").value.trim(),
      items: receivingRows.map((row) => ({
        itemId: row.dataset.directReceivingItem,
        received: Number(row.querySelector(".direct-receiving-actual").value || 0),
        receivedPrice: Number(row.querySelector(".direct-receiving-price").value || 0),
        temperature: Number(row.querySelector(".direct-receiving-temperature").value || 0),
      })),
    });
    if (!response) return;
    $("#directReceivingModal").classList.add("hidden");
    switchView("inventory");
    switchStockTab("direct-receipts");
    showToast(`${order.number}: поставка принята и записана в журнал`);
    return;
  }
  let total = 0;
  let variance = 0;
  let acceptedPositions = 0;
  receivingRows.forEach((row) => {
    const item = order.items.find((entry) => entry.itemId === row.dataset.directReceivingItem);
    const actual = Math.max(0, Number(row.querySelector(".direct-receiving-actual").value || 0));
    const price = Math.max(0, Number(row.querySelector(".direct-receiving-price").value || 0));
    const oldQuantity = branchStock(branchId, item.itemId);
    const oldCost = branchUnitCost(branchId, item.itemId);
    item.received = actual;
    item.receivedPrice = price;
    item.temperature = Number(row.querySelector(".direct-receiving-temperature").value || 0);
    logisticsState.branchStocks[branchId][item.itemId] = oldQuantity + actual;
    if (actual > 0) {
      logisticsState.branchCosts[branchId][item.itemId] = (oldQuantity * oldCost + actual * price) / (oldQuantity + actual);
      supplier.prices[branchId][item.itemId] = price;
      acceptedPositions += 1;
    }
    total += actual * price;
    variance += actual - Number(item.requested || 0);
  });
  if (!acceptedPositions) { showToast("Укажите фактически принятое количество"); return; }
  const receivedAt = new Date($("#directReceivingAt").value);
  order.status = "received";
  order.receivedAt = Number.isNaN(receivedAt.getTime()) ? new Date().toISOString() : receivedAt.toISOString();
  order.receivedBy = currentSession.name;
  order.invoiceNumber = invoiceNumber;
  order.receivingComment = $("#directReceivingComment").value.trim();
  order.total = total;
  order.variance = variance;
  saveLogisticsState();
  saveSuppliers();
  $("#directReceivingModal").classList.add("hidden");
  renderAll();
  switchView("inventory");
  switchStockTab("direct-receipts");
  showToast(`${order.number}: поставка принята на ${money(total)}`);
}

function pointTransferSources(destinationBranchId) {
  return branches.filter((branch) => branch.id !== destinationBranchId);
}

function pointTransferItemOptions(selectedId, sourceBranchId) {
  const entities = [...ingredients, ...products];
  const option = (entity) => `<option value="${entity.id}" ${entity.id === selectedId ? "selected" : ""}>${escapeHtml(entity.name)}${serverMode ? "" : ` · ${decimal(branchStock(sourceBranchId, entity.id), 3)} ${entity.unit}`}</option>`;
  return `<optgroup label="Ингредиенты">${ingredients.map(option).join("")}</optgroup><optgroup label="Готовые товары">${products.map(option).join("")}</optgroup>`;
}

function syncPointTransferDraft() {
  pointTransferDraftItems = [...document.querySelectorAll(".point-transfer-item-row")].map((row) => ({
    itemId: row.querySelector(".point-transfer-item-product").value,
    quantity: Math.max(0, Number(row.querySelector(".point-transfer-item-quantity").value || 0))
  }));
}

function renderPointTransferItemsEditor() {
  const sourceBranchId = $("#pointTransferSource").value;
  $("#pointTransferItemsEditor").innerHTML = `<div class="point-transfer-item-head"><span>Продукт</span><span>Запросить</span><span>Ед.</span><span></span></div>${pointTransferDraftItems.map((item, index) => {
    const entity = logisticsItem(item.itemId) || ingredients[0] || products[0];
    return `<div class="point-transfer-item-row" data-point-transfer-item="${index}"><select class="point-transfer-item-product">${pointTransferItemOptions(entity?.id, sourceBranchId)}</select><input class="point-transfer-item-quantity" type="number" min="0.001" step="0.001" value="${item.quantity}" /><b>${entity?.unit || "ед."}</b><button class="icon-button danger-button" data-remove-point-transfer-item="${index}" type="button" aria-label="Удалить позицию">${uiIcon("close")}</button></div>`;
  }).join("")}`;
}

function updatePointTransferCalculation() {
  let quantity = 0;
  document.querySelectorAll(".point-transfer-item-row").forEach((row) => {
    const entity = logisticsItem(row.querySelector(".point-transfer-item-product").value);
    const requested = Math.max(0, Number(row.querySelector(".point-transfer-item-quantity").value || 0));
    row.querySelector("b").textContent = entity?.unit || "ед.";
    quantity += requested;
  });
  $("#pointTransferPositionsCount").textContent = document.querySelectorAll(".point-transfer-item-row").length;
  $("#pointTransferQuantityTotal").textContent = `${decimal(quantity, 3)} ед.`;
}

function openPointTransferForm() {
  if (currentRole !== "branch" && !testMode) { showToast("Запрос на перемещение создаёт точка-получатель"); return; }
  const destinationBranchId = currentSession.branchId || pendingOwnerObjectScope || branches[0]?.id;
  const sources = pointTransferSources(destinationBranchId);
  switchView("inventory");
  switchStockTab("point-transfers");
  if (!sources.length) { showToast("Для перемещения добавьте в систему вторую точку"); return; }
  $("#pointTransferDestination").innerHTML = `<option value="${destinationBranchId}">${escapeHtml(branchById(destinationBranchId)?.name || "Точка")}</option>`;
  $("#pointTransferSource").innerHTML = sources.map((branch) => `<option value="${branch.id}">${escapeHtml(branch.name)}</option>`).join("");
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  $("#pointTransferNeededAt").value = tomorrow.toISOString().slice(0, 10);
  $("#pointTransferComment").value = "";
  const sourceBranchId = $("#pointTransferSource").value;
  const firstEntity = serverMode ? ingredients[0] || products[0] : [...ingredients, ...products].find((entity) => branchStock(sourceBranchId, entity.id) > 0) || ingredients[0] || products[0];
  pointTransferDraftItems = firstEntity ? [{ itemId: firstEntity.id, quantity: 1 }] : [];
  renderPointTransferItemsEditor();
  updatePointTransferCalculation();
  $("#pointTransferModal").classList.remove("hidden");
}

async function savePointTransfer() {
  if (currentRole !== "branch" && !testMode) return;
  syncPointTransferDraft();
  const sourceBranchId = $("#pointTransferSource").value;
  const destinationBranchId = $("#pointTransferDestination").value;
  const items = pointTransferDraftItems.filter((item) => logisticsItem(item.itemId) && item.quantity > 0);
  if (!branchById(sourceBranchId) || !branchById(destinationBranchId) || sourceBranchId === destinationBranchId) { showToast("Выберите другую точку-отправителя"); return; }
  if (!items.length || items.length !== pointTransferDraftItems.length) { showToast("Укажите количество каждой позиции"); return; }
  if (new Set(items.map((item) => item.itemId)).size !== items.length) { showToast("Одна позиция добавлена дважды — объедините количество"); return; }
  if (serverMode) {
    const response = await runServerAction("transfer.create", {
      sourceBranchId,
      neededAt: $("#pointTransferNeededAt").value,
      comment: $("#pointTransferComment").value.trim(),
      items: items.map((item) => ({ itemId: item.itemId, requested: item.quantity }))
    });
    if (!response) return;
    $("#pointTransferModal").classList.add("hidden");
    switchView("inventory");
    switchStockTab("point-transfers");
    showToast("Запрос на перемещение отправлен на согласование");
    return;
  }
  const number = nextDocumentNumber("МТ", logisticsState.pointTransfers);
  logisticsState.pointTransfers.unshift({
    id: `point-transfer-${Date.now()}`,
    number,
    sourceBranchId,
    destinationBranchId,
    neededAt: $("#pointTransferNeededAt").value,
    comment: $("#pointTransferComment").value.trim(),
    items: items.map((item) => ({ itemId: item.itemId, requested: item.quantity })),
    status: "submitted",
    createdAt: new Date().toISOString(),
    createdBy: currentSession.name
  });
  saveLogisticsState();
  $("#pointTransferModal").classList.add("hidden");
  renderAll();
  switchView("inventory");
  switchStockTab("point-transfers");
  showToast(`${number}: запрос на перемещение отправлен на согласование`);
}

function reservedPointTransferQuantity(sourceBranchId, itemId, excludedTransferId = null) {
  return logisticsState.pointTransfers
    .filter((transfer) => transfer.id !== excludedTransferId && transfer.sourceBranchId === sourceBranchId && transfer.status === "approved")
    .flatMap((transfer) => transfer.items)
    .filter((item) => item.itemId === itemId)
    .reduce((sum, item) => sum + Number(item.approved || 0), 0);
}

async function approvePointTransfer(transferId) {
  if (currentRole !== "owner" && !testMode) { showToast("Перемещение согласует главный администратор"); return; }
  const transfer = pointTransferById(transferId);
  if (!transfer || transfer.status !== "submitted") return;
  if (serverMode) {
    const response = await runServerAction("transfer.approve", { id: transferId });
    if (!response) return;
    switchView("inventory");
    switchStockTab("point-transfers");
    showToast(`${transfer.number}: перемещение согласовано по доступному остатку`);
    return;
  }
  let approvedTotal = 0;
  let hasShortage = false;
  transfer.items.forEach((item) => {
    const free = Math.max(0, branchStock(transfer.sourceBranchId, item.itemId) - reservedPointTransferQuantity(transfer.sourceBranchId, item.itemId, transfer.id));
    item.approved = Math.min(Number(item.requested || 0), free);
    approvedTotal += item.approved;
    if (item.approved + .0001 < Number(item.requested || 0)) hasShortage = true;
  });
  if (!approvedTotal) { showToast("На точке-отправителе нет доступного остатка"); return; }
  transfer.status = "approved";
  transfer.approvedAt = new Date().toISOString();
  transfer.approvedBy = currentSession.name;
  transfer.hasShortage = hasShortage;
  saveLogisticsState();
  renderAll();
  switchView("inventory");
  switchStockTab("point-transfers");
  showToast(hasShortage ? `${transfer.number}: согласовано частично из-за остатка` : `${transfer.number}: перемещение согласовано`);
}

async function dispatchPointTransfer(transferId) {
  const transfer = pointTransferById(transferId);
  if (!transfer || transfer.status !== "approved") return;
  if (!testMode && (currentRole !== "branch" || currentSession.branchId !== transfer.sourceBranchId)) { showToast("Отгрузку подтверждает точка-отправитель"); return; }
  if (!ensureBranchStockUnlocked(transfer.sourceBranchId)) return;
  if (serverMode) {
    const response = await runServerAction("transfer.dispatch", { id: transferId });
    if (!response) return;
    switchView("inventory");
    switchStockTab("point-transfers");
    showToast(`${transfer.number}: товар отгружен на точку-получатель`);
    return;
  }
  let shippedTotal = 0;
  let totalCost = 0;
  transfer.items.forEach((item) => {
    const shipped = Math.min(Number(item.approved || 0), branchStock(transfer.sourceBranchId, item.itemId));
    const unitCost = branchUnitCost(transfer.sourceBranchId, item.itemId);
    item.shipped = shipped;
    item.unitCost = unitCost;
    logisticsState.branchStocks[transfer.sourceBranchId][item.itemId] = Math.max(0, branchStock(transfer.sourceBranchId, item.itemId) - shipped);
    shippedTotal += shipped;
    totalCost += shipped * unitCost;
  });
  if (!shippedTotal) { showToast("Нет доступного остатка для отгрузки"); return; }
  transfer.status = "shipped";
  transfer.shippedAt = new Date().toISOString();
  transfer.shippedBy = currentSession.name;
  transfer.totalCost = totalCost;
  saveLogisticsState();
  renderAll();
  switchView("inventory");
  switchStockTab("point-transfers");
  showToast(`${transfer.number}: товар отгружен на ${branchById(transfer.destinationBranchId)?.short || "точку"}`);
}

function openPointTransferReceiving(transferId) {
  const transfer = pointTransferById(transferId);
  if (!transfer || transfer.status !== "shipped") return;
  if (!testMode && (currentRole !== "branch" || currentSession.branchId !== transfer.destinationBranchId)) { showToast("Приёмку подтверждает точка-получатель"); return; }
  if (!ensureBranchStockUnlocked(transfer.destinationBranchId)) return;
  currentPointTransferReceivingId = transfer.id;
  const source = branchById(transfer.sourceBranchId);
  const destination = branchById(transfer.destinationBranchId);
  $("#pointTransferReceivingTitle").textContent = `${transfer.number} · приёмка`;
  $("#pointTransferReceivingMeta").innerHTML = `<div><span>Отправитель</span><strong>${escapeHtml(source?.name || "Точка")}</strong></div><div><span>Получатель</span><strong>${escapeHtml(destination?.name || "Точка")}</strong></div><div><span>Отгружено</span><strong>${new Date(transfer.shippedAt).toLocaleString("ru-RU")}</strong></div>`;
  $("#pointTransferReceivingComment").value = "";
  $("#pointTransferReceivingItems").innerHTML = `<div class="point-transfer-receiving-head"><span>Продукт</span><span>Отгружено</span><span>Фактически</span><span>Ед.</span><span>Разница</span></div>${transfer.items.filter((item) => Number(item.shipped || 0) > 0).map((item) => {
    const entity = logisticsItem(item.itemId);
    return `<div class="point-transfer-receiving-row" data-point-transfer-receiving-item="${item.itemId}" data-shipped="${item.shipped}"><div><strong>${escapeHtml(entity?.name || item.itemId)}</strong><small>${money(item.unitCost || 0)} / ${entity?.unit || "ед."}</small></div><span>${decimal(item.shipped, 3)}</span><input class="point-transfer-receiving-actual" type="number" min="0" max="${item.shipped}" step="0.001" value="${item.shipped}" /><b>${entity?.unit || "ед."}</b><strong class="point-transfer-row-variance available-value">0</strong></div>`;
  }).join("")}`;
  updatePointTransferReceivingCalculation();
  $("#pointTransferReceivingModal").classList.remove("hidden");
}

function updatePointTransferReceivingCalculation() {
  let acceptedPositions = 0;
  let variance = 0;
  document.querySelectorAll(".point-transfer-receiving-row").forEach((row) => {
    const shipped = Number(row.dataset.shipped || 0);
    const actual = Math.max(0, Number(row.querySelector(".point-transfer-receiving-actual").value || 0));
    const difference = actual - shipped;
    if (actual > 0) acceptedPositions += 1;
    variance += difference;
    const output = row.querySelector(".point-transfer-row-variance");
    output.textContent = `${difference > 0 ? "+" : ""}${decimal(difference, 3)}`;
    output.className = `point-transfer-row-variance ${difference ? "deficit-value" : "available-value"}`;
  });
  $("#pointTransferAcceptedPositions").textContent = acceptedPositions;
  $("#pointTransferReceivingVariance").textContent = `${variance > 0 ? "+" : ""}${decimal(variance, 3)} ед.`;
  $("#pointTransferReceivingVariance").className = variance ? "deficit-value" : "available-value";
}

async function savePointTransferReceiving() {
  const transfer = pointTransferById(currentPointTransferReceivingId);
  if (!transfer || transfer.status !== "shipped") return;
  if (!testMode && (currentRole !== "branch" || currentSession.branchId !== transfer.destinationBranchId)) return;
  const rows = [...document.querySelectorAll(".point-transfer-receiving-row")];
  if (rows.some((row) => Number(row.querySelector(".point-transfer-receiving-actual").value || 0) > Number(row.dataset.shipped || 0) + .0001)) { showToast("Принятое количество не может быть больше отгруженного"); return; }
  if (!rows.some((row) => Number(row.querySelector(".point-transfer-receiving-actual").value || 0) > 0)) { showToast("Укажите фактически принятое количество"); return; }
  if (serverMode) {
    const response = await runServerAction("transfer.receive", {
      id: transfer.id,
      comment: $("#pointTransferReceivingComment").value.trim(),
      items: rows.map((row) => ({
        itemId: row.dataset.pointTransferReceivingItem,
        received: Math.max(0, Number(row.querySelector(".point-transfer-receiving-actual").value || 0))
      }))
    });
    if (!response) return;
    currentPointTransferReceivingId = null;
    $("#pointTransferReceivingModal").classList.add("hidden");
    switchView("inventory");
    switchStockTab("point-transfers");
    showToast(`${transfer.number}: перемещение принято`);
    return;
  }
  const branchId = transfer.destinationBranchId;
  if (!ensureBranchStockUnlocked(branchId)) return;
  logisticsState.branchStocks[branchId] ||= {};
  logisticsState.branchCosts[branchId] ||= {};
  let variance = 0;
  let acceptedCost = 0;
  rows.forEach((row) => {
    const item = transfer.items.find((entry) => entry.itemId === row.dataset.pointTransferReceivingItem);
    const shipped = Number(item.shipped || 0);
    const actual = Math.max(0, Number(row.querySelector(".point-transfer-receiving-actual").value || 0));
    const incomingCost = Number(item.unitCost || 0);
    const oldQuantity = branchStock(branchId, item.itemId);
    const oldCost = branchUnitCost(branchId, item.itemId);
    item.received = actual;
    logisticsState.branchStocks[branchId][item.itemId] = oldQuantity + actual;
    if (actual > 0) logisticsState.branchCosts[branchId][item.itemId] = (oldQuantity * oldCost + actual * incomingCost) / (oldQuantity + actual);
    variance += actual - shipped;
    acceptedCost += actual * incomingCost;
  });
  transfer.status = "received";
  transfer.receivedAt = new Date().toISOString();
  transfer.receivedBy = currentSession.name;
  transfer.receivingComment = $("#pointTransferReceivingComment").value.trim();
  transfer.variance = variance;
  transfer.acceptedCost = acceptedCost;
  saveLogisticsState();
  currentPointTransferReceivingId = null;
  $("#pointTransferReceivingModal").classList.add("hidden");
  renderAll();
  switchView("inventory");
  switchStockTab("point-transfers");
  showToast(`${transfer.number}: перемещение принято${variance ? `, расхождение ${decimal(variance, 3)} ед.` : " без расхождений"}`);
}

function openBatchForm(recipeId = null, branchId = null) {
  if (serverMode && currentRole !== "branch") { showToast("Выпуск продукции подтверждает только управляющий точки"); return; }
  if (!hasRole("owner", "branch")) { showToast("Выпуск продукции доступен только точке"); return; }
  populateBranchSelect($("#batchBranch"));
  if (branchId) $("#batchBranch").value = branchId;
  else if ($("#productionBranchSelect")?.value) $("#batchBranch").value = $("#productionBranchSelect").value;
  if (!ensureBranchStockUnlocked($("#batchBranch").value)) return;
  $("#batchRecipe").innerHTML = recipes.map((recipe) => `<option value="${recipe.id}">${escapeHtml(recipe.name)} · выход ${recipe.yield} г</option>`).join("");
  if (recipeId) $("#batchRecipe").value = String(recipeId);
  const recipe = recipes.find((entry) => Number(entry.id) === Number($("#batchRecipe").value)) || recipes[0];
  const suggestedPortions = recipe ? plannedRecipePortions(recipe, $("#batchBranch").value) : 0;
  $("#batchWeight").value = recipe ? Number(((suggestedPortions || 1) * recipe.yield / 1000).toFixed(3)) : 1;
  updateBatchCalculation();
  $("#batchModal").classList.remove("hidden");
}

function updateBatchCalculation() {
  const recipe = recipes.find((entry) => Number(entry.id) === Number($("#batchRecipe").value));
  const branchId = $("#batchBranch").value;
  const weight = Math.max(0, Number($("#batchWeight").value || 0));
  if (!recipe) return;
  const equivalent = weight * 1000 / recipe.yield;
  $("#batchPortions").textContent = `${decimal(equivalent, 1)} порций`;
  $("#batchCost").textContent = money(recipeCostForBranch(recipe, branchId) * equivalent);
  $("#batchRequirements").innerHTML = recipe.components.map((component) => {
    const entity = logisticsItem(component.ingredientId);
    const required = componentGross(component) / 1000 * equivalent;
    const available = branchStock(branchId, component.ingredientId);
    return `<div><span>${escapeHtml(entity?.name || component.ingredientId)}</span><b class="${required > available + .0001 ? "low" : ""}">${decimal(required, 3)} ${entity?.unit || "ед."} <small>из ${decimal(available, 3)}</small></b></div>`;
  }).join("");
}

async function saveBatch() {
  if ($("#saveBatchButton").disabled) return;
  if (!hasRole("owner", "branch")) return;
  const recipe = recipes.find((entry) => Number(entry.id) === Number($("#batchRecipe").value));
  const branchId = $("#batchBranch").value;
  const weight = Math.max(0, Number($("#batchWeight").value || 0));
  if (!recipe || !weight) return;
  if (!ensureBranchStockUnlocked(branchId)) return;
  const equivalent = weight * 1000 / recipe.yield;
  const shortage = recipe.components.find((component) => componentGross(component) / 1000 * equivalent > branchStock(branchId, component.ingredientId) + .0001);
  if (shortage) { showToast(`На точке недостаточно «${logisticsItem(shortage.ingredientId)?.name || "сырья"}»`); return; }
  if (serverMode) {
    $("#saveBatchButton").disabled = true;
    let response;
    try { response = await runServerAction("batch.create", { recipeId: recipe.id, weight }); }
    finally { $("#saveBatchButton").disabled = false; }
    if (!response) return;
    $("#batchModal").classList.add("hidden");
    switchView("logistics");
    switchProductionTab("record");
    showToast(`Выпущено ${decimal(weight, 3)} кг «${recipe.name}»`);
    return;
  }
  recipe.components.forEach((component) => {
    const required = componentGross(component) / 1000 * equivalent;
    logisticsState.branchStocks[branchId][component.ingredientId] = Math.max(0, branchStock(branchId, component.ingredientId) - required);
  });
  const number = nextDocumentNumber("АП", logisticsState.batches);
  logisticsState.batches.unshift({ id: `batch-${Date.now()}`, number, branchId, recipeId: recipe.id, actualWeight: weight, transferredWeight: 0, status: "kitchen", createdAt: new Date().toISOString(), createdBy: currentSession.name, cost: recipeCostForBranch(recipe, branchId) * equivalent });
  saveLogisticsState();
  $("#batchModal").classList.add("hidden");
  renderAll();
  $("#productionBranchSelect").value = branchId;
  switchView("logistics");
  switchProductionTab("record");
  renderProductionRecord();
  showToast(`${number}: выпущено ${decimal(weight, 2)} кг «${recipe.name}»`);
}

async function openServingTransfer(batchId) {
  const batch = logisticsBatchById(batchId);
  if (!batch) return;
  currentServingBatchId = batch.id;
  if (serverMode) {
    try {
      const data = await window.AshkanaApi.productionContext(batch.branchId);
      $("#servingReceiver").innerHTML = '<option value="">Выберите получателя</option>'+(data.recipients||[]).map(person=>`<option value="${escapeHtml(person.id)}">${escapeHtml(person.name)}</option>`).join('');
      $("#servingTransferModal").dataset.requestId = crypto.randomUUID();
    } catch(error) { showToast(error.message); return; }
  }
  const recipe = recipes.find((entry) => Number(entry.id) === Number(batch.recipeId));
  const remaining = Math.max(0, (batch.kitchenAvailableWeight != null ? Number(batch.kitchenAvailableWeight) : Number(batch.actualWeight) - Number(batch.transferredWeight || 0)));
  $("#servingTransferTitle").textContent = `${recipe?.name || "Блюдо"} · ${batch.number}`;
  $("#servingTransferWeight").value = Number(remaining.toFixed(3));
  $("#servingTransferWeight").max = remaining;
  $("#servingTransferTemperature").value = recipe?.category === "Салаты" ? 7 : 65;
  $("#servingLine").value = recipe?.category === "Салаты" ? "Холодная витрина · салаты" : recipe?.category === "Первые" ? "Линия №2 · супы" : "Линия №1 · горячие блюда";
  updateServingTransferCalculation();
  $("#servingTransferModal").classList.remove("hidden");
}

function updateServingTransferCalculation() {
  const batch = logisticsBatchById(currentServingBatchId);
  const recipe = recipes.find((entry) => Number(entry.id) === Number(batch?.recipeId));
  const weight = Math.max(0, Number($("#servingTransferWeight").value || 0));
  $("#servingTransferPortions").textContent = `${recipe ? Math.floor(weight * 1000 / recipe.yield) : 0} порций`;
}

async function saveServingTransfer() {
  const batch = logisticsBatchById(currentServingBatchId);
  if (!batch) return;
  const remaining = Math.max(0, (batch.kitchenAvailableWeight != null ? Number(batch.kitchenAvailableWeight) : Number(batch.actualWeight) - Number(batch.transferredWeight || 0)));
  const weight = Math.min(remaining, Math.max(0, Number($("#servingTransferWeight").value || 0)));
  if (!weight) return;
  if (serverMode) {
    const response = await runServerAction("batch.transfer", {
      id: batch.id,
      weight,
      temperature: Number($("#servingTransferTemperature").value || 0),
      line: $("#servingLine").value,
      recipientId: $("#servingReceiver").value,
      requestId: $("#servingTransferModal").dataset.requestId
    });
    if (!response) return;
    $("#servingTransferModal").classList.add("hidden");
    switchView("logistics");
    switchProductionTab("record");
    showToast(`${batch.number}: отправлено на приёмку ${decimal(weight, 3)} кг`);
    return;
  }
  batch.transferredWeight = Number(batch.transferredWeight || 0) + weight;
  batch.status = batch.transferredWeight + .001 >= Number(batch.actualWeight) ? "serving" : "partial";
  batch.servingTemperature = Number($("#servingTransferTemperature").value || 0);
  batch.servingLine = $("#servingLine").value;
  batch.servingReceiver = $("#servingReceiver").value.trim();
  batch.transferredAt = new Date().toISOString();
  saveLogisticsState();
  $("#servingTransferModal").classList.add("hidden");
  renderAll();
  switchView("logistics");
  switchProductionTab("record");
  showToast(`${batch.number}: на раздачу передано ${decimal(weight, 2)} кг`);
}

function openServingClose(batchId) {
  const batch = logisticsBatchById(batchId);
  if (!batch || !batch.transferredWeight) return;
  if (serverMode && batch.custodyVersion) { openCustodyJournal(); showToast("Оформите пересчёт, списание остатков и закрытие в журнале витрины"); return; }
  currentServingCloseId = batch.id;
  const recipe = recipes.find((entry) => Number(entry.id) === Number(batch.recipeId));
  const theoreticalPortions = recipe ? Math.floor(Number(batch.transferredWeight) * 1000 / recipe.yield) : 0;
  const suggestedSold = serverMode ? Number(batch.soldPortions || 0) : Math.floor(theoreticalPortions * .88);
  const suggestedRemainder = recipe ? Math.max(0, Number(batch.transferredWeight) - suggestedSold * recipe.yield / 1000) : 0;
  $("#servingCloseTitle").textContent = `${recipe?.name || "Блюдо"} · ${batch.number}`;
  $("#servingSoldPortions").value = suggestedSold;
  $("#servingSoldPortions").readOnly = serverMode;
  $("#servingRemainingWeight").value = Number(suggestedRemainder.toFixed(3));
  updateServingCloseBalance();
  $("#servingCloseModal").classList.remove("hidden");
}

function updateServingCloseBalance() {
  const batch = logisticsBatchById(currentServingCloseId);
  const recipe = recipes.find((entry) => Number(entry.id) === Number(batch?.recipeId));
  if (!batch || !recipe) return;
  const transferred = Number(batch.transferredWeight || 0);
  const portions = Math.max(0, Number($("#servingSoldPortions").value || 0));
  const remaining = Math.max(0, Number($("#servingRemainingWeight").value || 0));
  const used = portions * recipe.yield / 1000;
  const variance = transferred - used - remaining;
  $("#servingCloseTransferred").textContent = `${decimal(transferred, 3)} кг`;
  $("#servingCloseUsed").textContent = `${decimal(used, 3)} кг`;
  $("#servingCloseVariance").textContent = `${variance > 0 ? "+" : ""}${decimal(variance, 3)} кг`;
  $("#servingCloseVariance").className = Math.abs(variance) > .01 ? "deficit-value" : "available-value";
}

async function saveServingClose() {
  const batch = logisticsBatchById(currentServingCloseId);
  const recipe = recipes.find((entry) => Number(entry.id) === Number(batch?.recipeId));
  if (!batch || !recipe) return;
  const portions = Math.max(0, Number($("#servingSoldPortions").value || 0));
  const remaining = Math.max(0, Number($("#servingRemainingWeight").value || 0));
  if (remaining > Number(batch.transferredWeight) + .001) { showToast("Остаток не может быть больше переданного веса"); return; }
  if (serverMode) {
    const response = await runServerAction("batch.close", {
      id: batch.id,
      remainingWeight: remaining,
      remainderAction: $("#servingRemainderAction").value
    });
    if (!response) return;
    $("#servingCloseModal").classList.add("hidden");
    switchView("logistics");
    switchProductionTab("record");
    showToast(`${batch.number}: выдача закрыта, по кассе ${portions} порций`);
    return;
  }
  batch.servedPortions = portions;
  batch.remainingWeight = remaining;
  batch.remainderAction = $("#servingRemainderAction").value;
  batch.massVariance = Number(batch.transferredWeight) - portions * recipe.yield / 1000 - remaining;
  batch.status = "closed";
  batch.closedAt = new Date().toISOString();
  saveLogisticsState();
  $("#servingCloseModal").classList.add("hidden");
  renderAll();
  switchView("logistics");
  switchProductionTab("record");
  showToast(`${batch.number}: выдача закрыта, по кассе ${portions} порций`);
}

function analyticsDateValue(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function analyticsInputDate(value, endOfDay = false) {
  const date = new Date(`${value}T${endOfDay ? "23:59:59.999" : "00:00:00"}`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function saleUnitCost(sale, item) {
  if (Number.isFinite(Number(item.unitCost))) return Math.max(0, Number(item.unitCost));
  const recipe = recipes.find((entry) => String(entry.id) === String(item.id));
  if (recipe) return recipeCostForBranch(recipe, sale.branchId);
  const product = products.find((entry) => String(entry.id) === String(item.id));
  return product ? branchUnitCost(sale.branchId, product.id) : 0;
}

function saleCost(sale) {
  return (sale.items || []).reduce((sum, item) => sum + saleUnitCost(sale, item) * Number(item.quantity || 0), 0);
}

function isExternalSale(sale) {
  return sale.paymentMethod === "external" || sale.source === "external";
}

function analyticsUnit(value, fallback = "шт") {
  const unit = (String(value ?? "").trim() || fallback).toLocaleLowerCase("ru").replace(/\.$/, "");
  return ({ "пор": "порция", "порц": "порция", "порции": "порция", "порций": "порция", "штука": "шт", "штуки": "шт", "штук": "шт" })[unit] || unit;
}

function saleLineUnit(line) {
  const recipe = recipes.find((item) => String(item.id) === String(line.id));
  const product = products.find((item) => String(item.id) === String(line.id));
  return analyticsUnit(line.unit, recipe ? "порция" : product?.unit || "шт");
}

function saleLineRevenue(line, fallbackPrice = 0) {
  if (line.total != null && line.total !== "" && Number.isFinite(Number(line.total))) return Number(line.total);
  return Number(line.price ?? fallbackPrice) * Number(line.quantity || 0);
}

function salesMetrics(sales) {
  const revenue = sales.reduce((sum, sale) => sum + Number(sale.total || 0), 0);
  const cost = sales.reduce((sum, sale) => sum + saleCost(sale), 0);
  const receipts = sales.filter((sale) => !sale._reportRefund && !isExternalSale(sale));
  const receiptRevenue = receipts.reduce((sum, sale) => sum + Number(sale.total || 0), 0);
  const quantities = new Map();
  sales.forEach((sale) => (sale.items || []).forEach((item) => {
    const unit = saleLineUnit(item);
    quantities.set(unit, (quantities.get(unit) || 0) + Number(item.quantity || 0));
  }));
  return { revenue, cost, profit: revenue - cost, receipts: receipts.length,
    refunds: sales.filter((sale) => sale._reportRefund).length,
    imports: sales.filter((sale) => !sale._reportRefund && isExternalSale(sale)).length,
    quantities: [...quantities].map(([unit, quantity]) => ({ unit, quantity })), average: receipts.length ? receiptRevenue / receipts.length : 0 };
}

function saleReportingDate(value) {
  const original = new Date(value);
  if (Number.isNaN(original.getTime()) || !companyGeneralSettings.timezone) return original;
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: companyGeneralSettings.timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).formatToParts(original).map(p => [p.type, p.value]));
  const date = new Date(Number(parts.year), Number(parts.month) - 1, Number(parts.day), Number(parts.hour), Number(parts.minute), Number(parts.second));
  const [hours, minutes] = (companyGeneralSettings.shiftEnd || "00:00").split(":").map(Number);
  date.setMinutes(date.getMinutes() - hours * 60 - minutes);
  return date;
}
function filterSalesByRange(sales, from, to, branchId = "all", dateField = "createdAt") {
  return sales.filter((sale) => {
    const date = saleReportingDate(sale[dateField]);
    return !Number.isNaN(date.getTime()) && date >= from && date <= to && (branchId === "all" || String(sale.branchId) === String(branchId));
  });
}

function saleRefundUnitCost(sale, item) {
  // Match the stock restored by sale.refund; prepared food stays consumed.
  if (products.some((product) => String(product.id) === String(item.id))) return Math.max(0, Number(item.unitCost || 0));
  if (item.ingredientAllocations?.length || (item.batchAllocations || []).some((row) => row.lotId && !String(row.lotId).startsWith("legacy-"))) return 0;
  return saleUnitCost(sale, item);
}

function salesPeriodEvents(sales, from, to, branchId = "all") {
  const sold = filterSalesByRange(sales, from, to, branchId);
  const refunds = filterSalesByRange(sales.filter((sale) => sale.refundedAt), from, to, branchId, "refundedAt");
  // These copies are used only in aggregates. The receipt archive keeps the
  // original records and never receives a second, invented receipt.
  return [...sold, ...refunds.map((sale) => ({
    ...sale, id: `refund:${sale.id}`, originalSaleId: sale.id, _reportRefund: true,
    createdAt: sale.refundedAt, total: -Number(sale.total || 0), subtotal: -Number(sale.subtotal || 0),
    discountAmount: -Number(sale.discountAmount || 0), serviceAmount: -Number(sale.serviceAmount || 0),
    deliveryAmount: -Number(sale.deliveryAmount || 0), rounding: -Number(sale.rounding || 0),
    payments: salePaymentParts(sale).map((part) => ({ ...part, amount: -Number(part.amount || 0) })),
    items: (sale.items || []).map((item) => ({ ...item, quantity: -Number(item.quantity || 0),
      total: -saleLineRevenue(item), unitCost: saleRefundUnitCost(sale, item) }))
  }))];
}

function itemAnalyticsRows(sales, includeEmpty = false) {
  const catalog = [
    ...recipes.map((item) => ({ ...item, itemType: "recipe", catalogKey: `recipe:${item.id}` })),
    ...products.map((item) => ({ ...item, itemType: "product", catalogKey: `product:${item.id}` }))
  ];
  const rows = new Map();
  const soldCatalogKeys = new Set();
  sales.forEach((sale) => (sale.items || []).forEach((line) => {
    const recipe = recipes.find((item) => String(item.id) === String(line.id));
    const product = products.find((item) => String(item.id) === String(line.id));
    const item = recipe || product;
    if (!item) return;
    const catalogKey = `${recipe ? "recipe" : "product"}:${item.id}`;
    const unit = analyticsUnit(line.unit, recipe ? "порция" : item.unit || "шт");
    const key = `${catalogKey}:${unit}`;
    if (!rows.has(key)) rows.set(key, { item: { ...item, itemType: recipe ? "recipe" : "product", catalogKey: key }, unit, quantity: 0, revenue: 0, cost: 0, profit: 0 });
    soldCatalogKeys.add(catalogKey);
    const row = rows.get(key);
    const quantity = Number(line.quantity || 0);
    const revenue = saleLineRevenue(line, item.price || 0);
    row.quantity += quantity;
    row.revenue += revenue;
    row.cost += saleUnitCost(sale, line) * quantity;
    row.profit = row.revenue - row.cost;
  }));
  if (includeEmpty) catalog.forEach((item) => {
    if (soldCatalogKeys.has(item.catalogKey)) return;
    const unit = analyticsUnit(item.itemType === "recipe" ? "порция" : item.unit);
    const key = `${item.catalogKey}:${unit}`;
    rows.set(key, { item: { ...item, catalogKey: key }, unit, quantity: 0, revenue: 0, cost: 0, profit: 0 });
  });
  return [...rows.values()].filter((row) => includeEmpty || row.quantity || row.revenue || row.cost).sort((left, right) => right.revenue - left.revenue);
}

function percentageDelta(current, previous) {
  if (!previous) return current ? 100 : 0;
  return (current - previous) / Math.abs(previous) * 100;
}

function setDeltaBadge(element, current, previous) {
  const delta = percentageDelta(current, previous);
  element.textContent = `${delta > 0 ? "+" : ""}${decimal(delta)}%`;
  element.classList.toggle("up", delta > 0);
  element.classList.toggle("down", delta < 0);
}

function renderSparkline(element, values) {
  const max = Math.max(...values, 0);
  element.innerHTML = values.map((value) => `<i style="height:${max ? Math.max(8, value / max * 100) : 8}%"></i>`).join("");
}

function compactAmount(value) {
  const number = Number(value || 0);
  if (number >= 1000000) return `${decimal(number / 1000000, 1)} млн`;
  if (number >= 1000) return `${decimal(number / 1000, 1)} тыс.`;
  return decimal(number, 0);
}

function analyticsBuckets(sales, from, to, grouping = "day") {
  const buckets = [];
  if (grouping === "month") {
    const cursor = new Date(from.getFullYear(), from.getMonth(), 1);
    while (cursor <= to) {
      const start = new Date(cursor);
      const end = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0, 23, 59, 59, 999);
      buckets.push({ start, end, label: cursor.toLocaleDateString("ru-RU", { month: "short", year: from.getFullYear() === to.getFullYear() ? undefined : "2-digit" }), revenue: 0, profit: 0, receipts: 0 });
      cursor.setMonth(cursor.getMonth() + 1);
    }
  } else {
    const step = grouping === "week" ? 7 : 1;
    const cursor = new Date(from.getFullYear(), from.getMonth(), from.getDate());
    while (cursor <= to) {
      const start = new Date(cursor);
      const end = new Date(cursor);
      end.setDate(end.getDate() + step - 1);
      end.setHours(23, 59, 59, 999);
      if (end > to) end.setTime(to.getTime());
      const label = grouping === "week"
        ? `${start.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" })}–${end.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" })}`
        : start.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
      buckets.push({ start, end, label, revenue: 0, profit: 0, receipts: 0 });
      cursor.setDate(cursor.getDate() + step);
    }
  }
  sales.forEach((sale) => {
    const date = saleReportingDate(sale.createdAt);
    const bucket = buckets.find((entry) => date >= entry.start && date <= entry.end);
    if (!bucket) return;
    const revenue = Number(sale.total || 0);
    bucket.revenue += revenue;
    bucket.profit += revenue - saleCost(sale);
    if (!sale._reportRefund && !isExternalSale(sale)) bucket.receipts += 1;
  });
  return buckets;
}

function renderSalesBars(axis, chart, buckets) {
  const maximum = Math.max(...buckets.map((bucket) => bucket.revenue), 0);
  const magnitude = 10 ** Math.max(0, Math.floor(Math.log10(maximum || 1)) - 1);
  const axisMaximum = maximum ? Math.ceil(maximum / magnitude / 4) * magnitude * 4 : 0;
  axis.innerHTML = [axisMaximum, axisMaximum * .66, axisMaximum * .33, 0].map((value) => `<span>${compactAmount(value)}</span>`).join("");
  chart.style.gridTemplateColumns = `repeat(${Math.max(1, buckets.length)}, minmax(30px, 1fr))`;
  chart.style.minWidth = `${Math.max(0, buckets.length * 43)}px`;
  chart.innerHTML = buckets.map((bucket) => {
    const revenueHeight = axisMaximum ? bucket.revenue / axisMaximum * 100 : 0;
    const profitHeight = axisMaximum ? Math.max(0, bucket.profit) / axisMaximum * 100 : 0;
    return `<div class="chart-day" title="${escapeHtml(bucket.label)} · выручка ${money(bucket.revenue)} · прибыль ${money(bucket.profit)}"><div><i style="height:${revenueHeight}%"></i><b style="height:${profitHeight}%"></b></div><span>${escapeHtml(bucket.label)}</span></div>`;
  }).join("");
  return maximum > 0;
}

function renderSalesLine(axis, chart, buckets) {
  const values = buckets.flatMap((bucket) => [bucket.revenue, bucket.profit]);
  const maximum = Math.max(...values, 0), minimum = Math.min(...values, 0);
  const magnitude = 10 ** Math.max(0, Math.floor(Math.log10(Math.max(maximum, -minimum) || 1)) - 1);
  const axisMaximum = maximum ? Math.ceil(maximum / magnitude / 4) * magnitude * 4 : minimum ? 0 : 1;
  const axisMinimum = minimum ? Math.floor(minimum / magnitude / 4) * magnitude * 4 : 0;
  const axisRange = axisMaximum - axisMinimum;
  axis.innerHTML = [axisMaximum, axisMaximum - axisRange / 3, axisMaximum - axisRange * 2 / 3, axisMinimum].map((value) => `<span>${compactAmount(value)}</span>`).join("");
  const width = Math.max(760, buckets.length * 42);
  const plotTop = 14;
  const plotBottom = 184;
  const labelY = 218;
  const xAt = (index) => buckets.length <= 1 ? width / 2 : 16 + index * (width - 32) / (buckets.length - 1);
  const yAt = (value) => plotBottom - (Number(value || 0) - axisMinimum) / axisRange * (plotBottom - plotTop);
  const revenuePoints = buckets.map((bucket, index) => `${xAt(index)},${yAt(bucket.revenue)}`).join(" ");
  const profitPoints = buckets.map((bucket, index) => `${xAt(index)},${yAt(bucket.profit)}`).join(" ");
  const labelStep = Math.max(1, Math.ceil(buckets.length / 7));
  const labels = buckets.map((bucket, index) => index % labelStep === 0 || index === buckets.length - 1
    ? `<text x="${xAt(index)}" y="${labelY}" text-anchor="middle">${escapeHtml(bucket.label)}</text>`
    : "").join("");
  const guides = [plotTop, plotTop + (plotBottom - plotTop) / 3, plotTop + (plotBottom - plotTop) * 2 / 3, plotBottom]
    .map((y) => `<line x1="0" y1="${y}" x2="${width}" y2="${y}" />`).join("");
  const pointTitles = buckets.map((bucket, index) => `<g><circle class="revenue-point" cx="${xAt(index)}" cy="${yAt(bucket.revenue)}" r="3.5"><title>${escapeHtml(bucket.label)} · выручка ${money(bucket.revenue)}</title></circle><circle class="profit-point" cx="${xAt(index)}" cy="${yAt(bucket.profit)}" r="3"><title>${escapeHtml(bucket.label)} · прибыль ${money(bucket.profit)}</title></circle></g>`).join("");
  chart.style.minWidth = `${width}px`;
  chart.innerHTML = `<svg class="analytics-line-svg" viewBox="0 0 ${width} 230" preserveAspectRatio="none" role="img" aria-label="График выручки и прибыли"><g class="line-guides">${guides}</g><polyline class="profit-line" points="${profitPoints}"/><polyline class="revenue-line" points="${revenuePoints}"/>${pointTitles}<g class="line-labels">${labels}</g></svg>${buckets.map(() => '<div class="chart-day" aria-hidden="true"></div>').join("")}`;
  return buckets.length > 0;
}

function renderSetupGuide() {
  const completed = [
    recipes.length > 0 || products.length > 0,
    (logisticsState.supplies || []).length > 0 || branches.some((branch) =>
      [...ingredients, ...products].some((item) => branchStock(branch.id, item.id) > 0)),
    employees.some((employee) => employee.is_active),
    posRegisters.some((register) => register.is_active),
    getSales().some((sale) => !sale.refundedAt)
  ];
  const buttons = [...document.querySelectorAll("#setupGuide [data-setup-route]")];
  const nextStep = completed.indexOf(false);
  buttons.forEach((button, index) => {
    const ready = completed[index];
    button.classList.toggle("complete", ready);
    button.classList.toggle("next-step", index === nextStep);
    button.querySelector("i").innerHTML = ready ? uiIcon("check") : String(index + 1);
    button.querySelector("b").innerHTML = `${ready ? "Готово" : button.dataset.setupRoute === "pos" ? "Открыть кассу" : "Настроить"}${uiIcon("arrow")}`;
  });
  const count = completed.filter(Boolean).length;
  $("#setupProgress").textContent = `${count} из ${completed.length} шагов выполнено`;
  $("#setupProgressBar").value = count;
  $("#setupNextStep").textContent = nextStep === -1
    ? "Всё готово! Продолжайте работу на кассе, а результаты смотрите в статистике."
    : "Ваш прогресс обновляется автоматически по мере настройки аккаунта.";
}

function renderDashboard() {
  $("#dashboardGreeting").textContent = currentSession.name
    ? `Добро пожаловать, ${currentSession.name}!`
    : "Добро пожаловать в Oimo!";
  renderSetupGuide();
}

function branchCountText(count) {
  return `${count} ${pluralRu(count, "действующее заведение", "действующих заведения", "действующих заведений")}`;
}

function renderBranchSupplierOptions(branchId = null) {
  const activeSuppliers = suppliers.filter((supplier) => supplier.status === "active");
  $("#branchSupplierOptions").innerHTML = activeSuppliers.length
    ? activeSuppliers.map((supplier) => `<label><input type="checkbox" value="${escapeHtml(supplier.id)}" data-branch-supplier ${branchId && supplier.locations?.includes(branchId) ? "checked" : ""} /> <span><strong>${escapeHtml(supplier.name)}</strong><small>${escapeHtml(supplier.phone || supplier.contact || "Контакты не указаны")}</small></span></label>`).join("")
    : '<div class="branch-supplier-empty"><strong>Поставщиков пока нет</strong><small>Заведение можно создать сейчас, а поставщиков назначить позже в разделе «Склад → Поставщики».</small></div>';
}

function openBranchForm(branchId = null) {
  if (currentRole !== "owner") return;
  const branch = branchById(branchId);
  editingBranchId = branch?.id || null;
  branchLoginEdited = Boolean(branch);
  const number = branch?.number || nextBranchNumber();
  $("#branchModalEyebrow").textContent = branch ? "Настройки заведения" : "Новое заведение";
  $("#branchModalTitle").textContent = branch ? branch.name : "Добавить заведение";
  $("#branchNumberPreview").textContent = String(number).padStart(2, "0");
  $(".branch-number-line strong").textContent = branch ? "Действующее заведение" : "Новое заведение";
  $(".branch-number-line small").textContent = branch ? "Изменения применятся ко всем документам заведения" : "Склад откроется с нулевыми остатками";
  $("#branchShortInput").value = branch?.short || "";
  $("#branchAddressInput").value = branch?.address || "";
  $("#branchPhoneInput").value = branch?.phone || "";
  $("#branchOpenInput").value = branch?.workHours?.open || "08:00";
  $("#branchCloseInput").value = branch?.workHours?.close || "20:00";
  $("#branchManagerInput").value = branch?.managerName || "Не назначен";
  $("#branchLoginInput").value = currentSession.tenantSlug || branch?.login || "";
  $("#branchPasswordInput").value = branch ? "" : generateTemporaryPassword();
  $("#branchPasswordInput").placeholder = branch ? "Оставьте пустым, чтобы не менять" : "Не менее 8 символов";
  $("#branchPasswordLabel").textContent = branch ? "Новый пароль основной кассы" : "Пароль основной кассы *";
  $("#branchPasswordHint").classList.toggle("hidden", !branch);
  $("#branchAccessSectionHint").textContent = branch ? "Кассы и сотрудники настраиваются отдельно в разделе «Доступ»" : "Основная касса будет создана вместе с заведением";
  $("#branchFormNote").textContent = branch ? "Остатки и документы сохраняются. Поставщики, кассы и сотрудники настраиваются в своих разделах." : "После создания добавьте поставщиков и сотрудников. Права сотрудников действуют в рамках аккаунта.";
  $("#saveBranchButton").textContent = branch ? "Сохранить изменения" : "Создать и активировать";
  $("#branchModal").classList.remove("hidden");
  setTimeout(() => $("#branchShortInput").focus(), 20);
}

async function saveBranch() {
  if (currentRole !== "owner") return;
  const short = $("#branchShortInput").value.trim();
  const address = $("#branchAddressInput").value.trim();
  const phone = $("#branchPhoneInput").value.trim();
  const openTime = $("#branchOpenInput").value || "08:00";
  const closeTime = $("#branchCloseInput").value || "20:00";
  const managerName = $("#branchManagerInput").value.trim();
  const login = $("#branchLoginInput").value.trim().toLowerCase();
  const password = $("#branchPasswordInput").value.trim();
  const existing = branchById(editingBranchId);
  if (!short) { showToast("Укажите название заведения"); $("#branchShortInput").focus(); return; }
  if (!address) { showToast("Укажите адрес заведения"); $("#branchAddressInput").focus(); return; }
  if (!managerName) { showToast("Не удалось подготовить данные заведения"); return; }
  if (!/^[a-z0-9._-]{3,48}$/.test(login)) { showToast("Проверьте адрес аккаунта компании"); return; }
  if ((!existing || password) && password.length < 8) { showToast("Пароль должен содержать не менее 8 символов"); $("#branchPasswordInput").focus(); return; }
  if (branches.some((branch) => branch.id !== existing?.id && branch.short.toLowerCase() === short.toLowerCase())) { showToast("Заведение с таким названием уже существует"); return; }
  const accounts = serverMode ? {} : loadManagedAccounts();
  const belongsToAnotherPoint = !serverMode && branches.some((branch) => branch.id !== existing?.id && branch.login === login);
  const reservedManagedAccount = accounts[login] && accounts[login].branchId !== existing?.id && accounts[login].isActive !== false;
  const reservedBaseLogin = !serverMode && (login === "admin" || (login === "manasa" && existing?.id !== "b1"));
  if (belongsToAnotherPoint || reservedManagedAccount || reservedBaseLogin) { showToast("Этот логин уже используется"); $("#branchLoginInput").focus(); return; }

  const previousLogin = existing?.login || null;
  const number = existing?.number || nextBranchNumber();
  const branch = {
    ...(existing || {}),
    id: existing?.id || nextBranchId(),
    number,
    short,
    name: short,
    address,
    phone,
    workHours: { open: openTime, close: closeTime },
    managerName,
    login,
    status: "active",
    route: `Поставщики → ${short}`,
    createdAt: existing?.createdAt || new Date().toISOString(),
    createdBy: existing?.createdBy || currentSession.login || currentSession.name,
    updatedAt: existing ? new Date().toISOString() : undefined,
    updatedBy: existing ? currentSession.login || currentSession.name : undefined
  };
  const selectedSupplierIds = existing ? suppliers.filter((supplier) => supplier.locations?.includes(existing.id)).map((supplier) => String(supplier.id)) : [];
  if (serverMode) {
    const response = await runServerAction("branch.upsert", {
      id: existing?.id || null,
      short,
      address,
      phone,
      openTime,
      closeTime,
      managerName,
      login,
      password,
      status: "active"
    });
    if (!response) return;
    try {
      [employees, posRegisters] = await Promise.all([
        window.AshkanaApi.employees(),
        window.AshkanaApi.posRegisters(),
      ]);
      renderEmployees();
      renderRegisters();
    } catch {}
    const savedBranch = branchById(response.entity?.id) || branch;
    $("#branchModal").classList.add("hidden");
    renderOwnerObjectSelector();
    const accessChanged = !existing || previousLogin !== login || Boolean(password);
    if (accessChanged) {
      $("#branchAccessEyebrow").textContent = existing ? "Доступ обновлён" : "Заведение создано";
      $("#branchAccessTitle").textContent = `Основная касса · ${savedBranch.short}`;
      $("#branchAccessCopy").textContent = existing ? "Старый сеанс кассы завершён. Введите обновлённые данные на её устройстве." : "Введите эти данные на устройстве кассы. Затем сотрудник вводит личный PIN — терминал определит его автоматически.";
      $("#createdBranchLogin").textContent = login;
      $("#createdBranchPassword").textContent = password || "Не изменён";
      $("#branchAccessModal .branch-access-hint p").textContent = existing ? "Остатки, поставщики и документы заведения сохранены." : "Склад заведения создан с нулевыми остатками. Добавьте сотрудников и назначьте PIN тем, кто работает на кассе.";
      lastBranchAccessText = `${savedBranch.name}\nЛогин: ${login}${password ? `\nПароль: ${password}` : "\nПароль не изменён"}`;
      $("#branchAccessModal").classList.remove("hidden");
    } else showToast("Настройки заведения сохранены");
    editingBranchId = null;
    return;
  }
  if (existing) {
    if (!saveBranchAccount(branch, password, previousLogin)) { showToast("Задайте новый пароль для восстановления доступа"); return; }
    Object.assign(existing, branch);
    saveBranches();
  } else {
    if (!addConfiguredBranch(branch)) { showToast("Не удалось создать заведение"); return; }
    saveBranchAccount(branch, password);
  }

  const selectedSupplierIdSet = new Set(selectedSupplierIds);
  suppliers.forEach((supplier) => {
    supplier.locations ||= [];
    if (selectedSupplierIdSet.has(String(supplier.id)) && !supplier.locations.includes(branch.id)) supplier.locations.push(branch.id);
    if (!selectedSupplierIdSet.has(String(supplier.id))) supplier.locations = supplier.locations.filter((location) => location !== branch.id);
  });
  saveSuppliers();
  renderAll();
  renderOwnerObjectSelector();
  $("#branchModal").classList.add("hidden");
  const accessChanged = !existing || previousLogin !== login || Boolean(password);
  if (accessChanged) {
    $("#branchAccessEyebrow").textContent = existing ? "Доступ обновлён" : "Заведение создано";
    $("#branchAccessTitle").textContent = branch.name;
    $("#branchAccessCopy").textContent = existing ? "Старый сеанс кассы завершён. Введите обновлённые данные на её устройстве." : "Введите эти данные на устройстве кассы. Затем сотрудник вводит личный PIN — терминал определит его автоматически.";
    $("#createdBranchLogin").textContent = login;
    $("#createdBranchPassword").textContent = password || "Не изменён";
    $("#branchAccessModal .branch-access-hint p").textContent = existing ? "Остатки, поставщики и документы заведения сохранены. Для следующего входа используется новый доступ." : "Склад заведения создан с нулевыми остатками. Добавьте сотрудников и назначьте PIN тем, кто работает на кассе.";
    lastBranchAccessText = `${branch.name}\nЛогин: ${login}${password ? `\nПароль: ${password}` : "\nПароль не изменён"}`;
    $("#branchAccessModal").classList.remove("hidden");
  } else showToast("Настройки заведения сохранены");
  editingBranchId = null;
}

function renderBranches() {
  const activeCount = branches.filter((branch) => branch.status === "active").length;
  $("#branchCountLabel").textContent = branchCountText(activeCount);
  $("#branchCards").innerHTML = branches.length ? branches.map((branch) => {
    const supplierCount = suppliers.filter((supplier) => supplier.status === "active").length;
    const stockPositions = [...ingredients, ...products].filter((entity) => branchStock(branch.id, entity.id) > 0).length;
    const supplierDebt = (logisticsState.supplies || []).filter((supply) => supply.branchId === branch.id).reduce((sum, supply) => sum + Number(supply.debt || 0), 0);
    const employeeCount = employees.filter((employee) => employee.branch_id === branch.id && employee.is_active).length;
    const registerCount = posRegisters.filter((register) => register.branch_id === branch.id && register.is_active).length;
    return `<article class="branch-card"><header><span>${branch.number}</span><div><strong>${escapeHtml(branch.name)}</strong><small>${escapeHtml(branch.address || "Адрес не указан")}</small></div><i class="${branch.status === "active" ? "" : "inactive"}" title="${branch.status === "active" ? "Активно" : "Неактивно"}"></i></header><div class="branch-card-details"><div><span>Кассы</span><strong>${registerCount}</strong><small>${registerCount ? "активных касс" : "нет активных касс"}</small></div><div><span>Поставщики</span><strong>${supplierCount}</strong><small>${supplierCount ? "доступно в аккаунте" : "нужно добавить"}</small></div><div><span>Остатки</span><strong>${stockPositions}</strong><small>${stockPositions ? "позиций на складе" : "склад пуст"}</small></div></div><footer><span>${employeeCount} ${pluralRu(employeeCount, "сотрудник", "сотрудника", "сотрудников")} · ${supplierDebt ? `долг поставщикам ${money(supplierDebt)}` : "долгов поставщикам нет"}</span><div class="branch-card-actions"><button class="secondary-action" data-edit-branch="${branch.id}" type="button">Настроить заведение</button><button class="secondary-action" data-manage-branch="${branch.id}" type="button">Добавить сотрудника${uiIcon("arrow")}</button></div></footer></article>`;
  }).join("") : '<article class="branch-card"><header><span>1</span><div><strong>Добавьте первое заведение</strong><small>Укажите название, адрес, график работы и создайте основную кассу.</small></div></header><footer><span>Остатки нового склада начнутся с нуля</span></footer></article>';
}

function registerById(id) {
  return posRegisters.find((register) => String(register.id) === String(id));
}

function registerDeviceLabel(userAgent) {
  const value = String(userAgent || "");
  if (!value) return "Устройство ещё не активировано";
  if (/iPad|iPhone/i.test(value)) return "iPad / iPhone";
  if (/Android/i.test(value)) return "Android";
  if (/Windows/i.test(value)) return "Windows";
  if (/Macintosh|Mac OS/i.test(value)) return "Mac";
  if (/Linux/i.test(value)) return "Linux";
  return "Браузерное устройство";
}

function renderRegisters() {
  const ownerMode = currentRole === "owner";
  if (!ownerMode && (currentRole !== "branch" || currentSession.staffRole !== "branch_manager")) return;
  const branch = branchById(currentSession.branchId);
  const pointRegisters = ownerMode ? posRegisters : branch ? posRegisters.filter((register) => register.branch_id === branch.id) : [];
  $("#registersContextBar").classList.toggle("hidden", ownerMode);
  $("#registersPointName").textContent = branch?.name || "Моё заведение";
  $("#registersPointAddress").textContent = branch?.address || "Адрес не указан";
  $("#registerAccountLogin").textContent = currentSession.tenantSlug || pointRegisters[0]?.company_login || "—";
  $("#registersTable").innerHTML = pointRegisters.map((register) => {
    const registerBranch = branchById(register.branch_id);
    const lastSeen = register.last_seen_at
      ? new Date(register.last_seen_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })
      : "Ещё не входили";
    const status = !register.is_active
      ? '<span class="status-badge warn">Отключена</span>'
      : register.online
        ? '<span class="status-badge good">В сети</span>'
        : '<span class="status-badge">Не в сети</span>';
    return `<tr><td><div class="register-name"><span>${uiIcon("cashier")}</span><div><strong>${escapeHtml(register.name)}</strong><small>Логин: ${escapeHtml(register.account_login)}</small></div></div></td><td><strong>${escapeHtml(registerBranch?.name || "Заведение удалено")}</strong><small>${escapeHtml(registerBranch?.address || "")}</small></td><td><strong>${escapeHtml(registerDeviceLabel(register.device_label))}</strong><small>${register.remote_address ? `IP: ${escapeHtml(register.remote_address)}` : ""}</small></td><td>${escapeHtml(lastSeen)}</td><td>${status}</td><td><div class="register-actions"><button class="register-open-action primary-action" data-open-register="${register.id}" type="button" ${register.is_active ? "" : "disabled"}>Открыть кассу</button>${register.online ? `<button class="danger-button" data-logout-register="${register.id}" type="button">Завершить сеанс</button>` : ""}<button class="secondary-action" data-edit-register="${register.id}" type="button">Настроить</button></div></td></tr>`;
  }).join("");
  $("#registersEmpty").classList.toggle("hidden", Boolean(pointRegisters.length));
  $("#registersTable").closest(".table-scroll").classList.toggle("hidden", !pointRegisters.length);
}

function openRegisterForm(registerId = null) {
  const ownerMode = currentRole === "owner";
  if (!ownerMode && (currentRole !== "branch" || currentSession.staffRole !== "branch_manager")) return;
  const register = registerById(registerId);
  const activeBranches = branches.filter((entry) => entry.status === "active");
  const activeBranch = branchById(register?.branch_id || (ownerMode ? activeBranches[0]?.id : currentSession.branchId));
  if (!activeBranch) { showToast("Сначала добавьте действующее заведение"); switchView("branches"); return; }
  if (!ownerMode && register && register.branch_id !== activeBranch.id) { showToast("Эта касса относится к другому заведению"); return; }
  editingRegisterId = register?.id || null;
  $("#registerModalTitle").textContent = register ? "Настроить кассу" : "Новая касса";
  $("#registerNameInput").value = register?.name || "";
  $("#registerBranchInput").innerHTML = ownerMode
    ? activeBranches.map((entry) => `<option value="${escapeHtml(entry.id)}">${escapeHtml(entry.name)}</option>`).join("")
    : `<option value="${escapeHtml(activeBranch.id)}">${escapeHtml(activeBranch.name)}</option>`;
  $("#registerBranchInput").value = activeBranch.id;
  $("#registerWarehouseInput").value = `Склад · ${activeBranch.name}`;
  $("#registerBranchInput").disabled = !ownerMode || Boolean(register);
  $("#registerLoginInput").value = register?.account_login || (ownerMode ? `kassa-${Date.now().toString(36)}${Math.random().toString(36).slice(2,6)}` : "");
  $("#registerLoginInput").readOnly = !ownerMode;
  $("#registerLoginHint").textContent = ownerMode
    ? "Логин для входа на эту кассу. От 3 до 64 символов: латинские буквы, цифры и . _ @ + -"
    : "Логин назначается автоматически. Изменять его может владелец компании.";
  $("#registerPasswordInput").value = register ? "" : generateTemporaryPassword();
  $("#registerPasswordLabel").textContent = register ? "Новый пароль кассы" : "Пароль кассы *";
  $("#registerPasswordHint").textContent = register ? "Оставьте пустым, если пароль менять не нужно. Новый пароль завершит текущий сеанс." : "Пароль должен отличаться от паролей других касс.";
  $("#registerActiveRow").classList.toggle("hidden", !register);
  $("#registerActiveInput").checked = register?.is_active !== false;
  $("#saveRegisterButton").textContent = register ? "Сохранить изменения" : "Создать кассу";
  $("#registerModal").classList.remove("hidden");
  setTimeout(() => $("#registerNameInput").focus(), 20);
}

function openRegisterTerminal(registerId = null, loginOverride = "") {
  const activeRegisters = posRegisters.filter((register) => register.is_active);
  const register = registerById(registerId) || (activeRegisters.length === 1 ? activeRegisters[0] : null);
  if (!register) {
    switchView("registers");
    showToast(activeRegisters.length ? "Выберите кассу и нажмите «Открыть кассу»" : "Сначала создайте и включите кассу");
    return;
  }
  const login = loginOverride || currentSession.login || currentSession.tenantSlug || register.account_login;
  const url = `/login?mode=pos&register=${encodeURIComponent(register.id)}&login=${encodeURIComponent(login)}`;
  window.open(url, "_blank", "noopener");
}

async function saveRegister() {
  const existing = registerById(editingRegisterId);
  const activeBranch = branchById(currentRole === "owner" ? $("#registerBranchInput").value : currentSession.branchId);
  if (!activeBranch || (currentRole !== "owner" && existing && existing.branch_id !== activeBranch.id)) { showToast("Касса относится к другому заведению"); return; }
  const name = $("#registerNameInput").value.trim();
  const password = $("#registerPasswordInput").value;
  const registerLogin = $("#registerLoginInput").value.trim().toLowerCase();
  if (currentRole === 'owner' && !/^[a-z0-9._@+-]{3,64}$/.test(registerLogin)) {
    showToast('Укажите логин кассы: от 3 до 64 символов, латинские буквы, цифры и . _ @ + -');
    $('#registerLoginInput').focus();
    return;
  }
  if (!name) { showToast("Укажите название кассы"); return; }
  if (!existing && password.length < 8) { showToast("Пароль кассы должен содержать не менее 8 символов"); return; }
  if (password && password.length < 8) { showToast("Новый пароль должен содержать не менее 8 символов"); return; }
  const payload = {
    name,
    branch_id: activeBranch.id,
    ...(currentRole === 'owner' && (!existing || registerLogin !== existing.account_login) ? {login:registerLogin} : {}),
    ...(password ? { password } : {}),
    ...(existing ? { is_active: $("#registerActiveInput").checked } : {}),
  };
  try {
    const saved = existing
      ? await window.AshkanaApi.updatePosRegister(existing.id, payload)
      : await window.AshkanaApi.createPosRegister(payload);
    if (existing) Object.assign(existing, saved);
    else posRegisters.push(saved);
    $("#registerModal").classList.add("hidden");
    renderRegisters();
    if (!existing) {
      const branch = branchById(saved.branch_id);
      $("#registerAccessTitle").textContent = saved.name;
      $("#createdRegisterLogin").textContent = saved.account_login;
      $("#createdRegisterPassword").textContent = password;
      $("#registerAccessHint").textContent = `${branch?.name || "Заведение"}. Повторный вход этой кассы на другом устройстве завершит предыдущий сеанс.`;
      $("#openCreatedRegisterButton").dataset.registerId = saved.id;
      $("#openCreatedRegisterButton").dataset.accountLogin = saved.account_login;
      lastRegisterAccessText = `${saved.name}\n${branch?.name || "Заведение"}\nЛогин: ${saved.account_login}\nПароль кассы: ${password}`;
      $("#registerAccessModal").classList.remove("hidden");
    } else showToast("Настройки кассы сохранены");
  } catch (error) {
    if (error.status === 401) { signOutRevokedBranch(); return; }
    showToast(error.message || "Не удалось сохранить кассу");
  }
}

async function forceRegisterLogout(registerId) {
  const register = registerById(registerId);
  if (!register || !confirm(`Завершить сеанс кассы «${register.name}»?`)) return;
  try {
    const updated = await window.AshkanaApi.logoutPosRegister(register.id);
    Object.assign(register, updated);
    renderRegisters();
    showToast("Сеанс кассы завершён");
  } catch (error) {
    showToast(error.message || "Не удалось завершить сеанс");
  }
}

const employeeRoleProfiles = {
  branch_manager: { label: "Руководитель", title: "Права руководителя", description: "Администрирование аккаунта, склад, производство, финансы и отчёты. PIN можно назначить для работы на кассе." },
  hall_admin: { label: "Администратор зала", title: "Права администратора зала", description: "Работа на кассе по личному PIN, обслуживание гостей и контроль смены." },
  waiter: { label: "Официант", title: "Права официанта", description: "Работа на кассе по личному PIN: заказы, чеки и обслуживание гостей." },
  storekeeper: { label: "Кладовщик", title: "Права кладовщика", description: "Поставки, поставщики, перемещения, остатки и инвентаризации." },
  production: { label: "Производство", title: "Права производства", description: "Выпуск блюд, передача продукции на раздачу и закрытие остатков." },
  marketer: { label: "Маркетолог", title: "Права маркетолога", description: "Меню, статистика продаж и отчёты без доступа к кассовым операциям." },
  cashier: { label: "Кассир", title: "Права кассира", description: "Входит на уже авторизованном терминале по личному PIN. Продажи и чеки записываются на его имя." }
};

const employeePermissionKeys = ["posAccess", "posRefunds", "posCash", "posSupply", "reports", "menu", "inventory", "production", "finance", "employees", "registers", "settings"];
const employeeAdminPermissionKeys = ["reports", "menu", "inventory", "production", "finance", "employees", "registers", "settings"];
const employeePermissionDefaults = {
  branch_manager: { posAccess: true, posRefunds: true, posCash: true, posSupply: true, reports: true, menu: true, inventory: true, production: true, finance: true, employees: true, registers: true, settings: true },
  hall_admin: { posAccess: true, posRefunds: true, posCash: true },
  waiter: { posAccess: true },
  cashier: { posAccess: true, posCash: true },
  storekeeper: { inventory: true },
  production: { production: true, posAccess: true, posSupply: true },
  marketer: { reports: true, menu: true },
};

function normalizeEmployeePermissions(value, role = "cashier") {
  const source = value && typeof value === "object" ? value : employeePermissionDefaults[role] || {};
  return Object.fromEntries(employeePermissionKeys.map((key) => [key, Boolean(source[key])]));
}

function readEmployeePermissions() {
  return Object.fromEntries([...document.querySelectorAll("[data-employee-permission]")].map((input) => [input.dataset.employeePermission, input.checked]));
}

function setEmployeePermissions(value, role = $("#employeeRoleInput").value) {
  const permissions = normalizeEmployeePermissions(value, role);
  document.querySelectorAll("[data-employee-permission]").forEach((input) => { input.checked = permissions[input.dataset.employeePermission]; });
}

function employeeHasAdminAccess(permissions) {
  return employeeAdminPermissionKeys.some((key) => permissions[key]);
}

function employeeRoleLabel(role) {
  return employeeRoleProfiles[role]?.label || "Сотрудник";
}

function employeeById(id) {
  return employees.find((employee) => String(employee.id) === String(id));
}

function canDeleteEmployee(employee) {
  if (!employee || employee.deleted_at || !canAccessView('employees')) return false;
  if (employee.login && String(employee.login).toLowerCase() === String(currentSession.login || '').toLowerCase()) return false;
  return currentRole === 'owner' || (employee.branch_id === currentSession.branchId && employee.staff_role !== 'branch_manager');
}

function openEmployeeDelete(employeeId, trigger = document.activeElement) {
  const employee = employeeById(employeeId);
  if (!canDeleteEmployee(employee) || deletingEmployee) return;
  pendingEmployeeDeleteId = employee.id;
  employeeDeleteTrigger = trigger;
  $('#employeeDeleteName').textContent = employee.display_name;
  $('#employeeDeleteError').textContent = '';
  $('#employeeDeleteError').hidden = true;
  $('#employeeDeleteDialog').showModal();
  $('#cancelEmployeeDelete').focus();
}

function closeEmployeeDelete() {
  if (!deletingEmployee) $('#employeeDeleteDialog').close();
}

async function confirmEmployeeDelete() {
  const employee = employeeById(pendingEmployeeDeleteId);
  if (!canDeleteEmployee(employee) || deletingEmployee) return;
  deletingEmployee = true;
  const dialog = $('#employeeDeleteDialog');
  dialog.setAttribute('aria-busy', 'true');
  dialog.querySelectorAll('button').forEach(button => { button.disabled = true; });
  $('#confirmEmployeeDelete').textContent = 'Удаление…';
  $('#employeeDeleteError').hidden = true;
  let deleted = false;
  try {
    if (serverMode) await window.AshkanaApi.deleteEmployee(employee.id);
    employees = employees.filter(row => String(row.id) !== String(employee.id));
    if (String(editingEmployeeId) === String(employee.id)) {
      $('#employeeModal').classList.add('hidden');
      editingEmployeeId = null;
    }
    renderAll();
    deleted = true;
  } catch (error) {
    $('#employeeDeleteError').textContent = error.message || 'Не удалось удалить сотрудника. Попробуйте ещё раз.';
    $('#employeeDeleteError').hidden = false;
  } finally {
    deletingEmployee = false;
    dialog.removeAttribute('aria-busy');
    dialog.querySelectorAll('button').forEach(button => { button.disabled = false; });
    $('#confirmEmployeeDelete').textContent = 'Удалить сотрудника';
  }
  if (deleted) {
    dialog.close();
    showToast('Сотрудник удалён. История действий сохранена.');
    await refreshServerWorkspace();
  }
}

function updateEmployeePermissionNote() {
  const role = $("#employeeRoleInput").value;
  const profile = employeeRoleProfiles[role] || employeeRoleProfiles.cashier;
  const permissions = readEmployeePermissions();
  $("#employeePermissionNote strong").textContent = profile.title;
  $("#employeePermissionNote p").textContent = profile.description;
  const adminAccess = employeeHasAdminAccess(permissions);
  const posAccess = permissions.posAccess;
  $("#employeeLoginField").classList.toggle("hidden", !adminAccess);
  $("#employeePasswordField").classList.toggle("hidden", !adminAccess);
  $("#employeePinField").classList.toggle("hidden", !posAccess);
  $("#employeePinLabel").textContent = posAccess ? "PIN сотрудника *" : "PIN сотрудника";
  $("#employeePinHint").textContent = editingEmployeeId
    ? "Оставьте пустым, если PIN менять не нужно."
    : "4 цифры для входа в терминал. По PIN система определит сотрудника и его права.";
  if (posAccess && !editingEmployeeId && !/^\d{4}$/.test($("#employeePinInput").value)) $("#employeePinInput").value = generateEmployeePin();
  if (adminAccess && !editingEmployeeId && !$("#employeePasswordInput").value) $("#employeePasswordInput").value = generateTemporaryPassword();
}

function generateEmployeePin() {
  const values = new Uint32Array(1);
  crypto.getRandomValues(values);
  return String(1000 + (values[0] % 9000));
}

function renderEmployees() {
  const ownerMode = currentRole === "owner";
  const branch = branchById(currentSession.branchId);
  const pointEmployees = ownerMode
    ? employees.filter(employee => !employee.deleted_at)
    : branch ? employees.filter((employee) => employee.branch_id === branch.id && !employee.deleted_at) : [];
  $("#employeesContextBar").classList.toggle("hidden", ownerMode);
  $("#employeesPageEyebrow").textContent = ownerMode ? "Команда аккаунта" : "Команда заведения";
  $("#employeesPageTitle").textContent = "Сотрудники";
  $("#addEmployeeButtonLabel").textContent = "Добавить сотрудника";
  $("#employeeRoleFilter").classList.remove("hidden");
  $("#employeeScopeHeading").textContent = "Должность";
  $("#employeesPointName").textContent = branch?.name || "Моё заведение";
  $("#employeesPointAddress").textContent = branch?.address || "Адрес не указан";

  const query = $("#employeeSearch").value.trim().toLowerCase();
  const role = $("#employeeRoleFilter").value;
  const status = $("#employeeStatusFilter").value;
  const visible = pointEmployees.filter((employee) => {
    const haystack = [employee.display_name, employee.phone, employee.login].join(" ").toLowerCase();
    return (!query || haystack.includes(query))
      && (role === "all" || employee.staff_role === role)
      && (status === "all" || (status === "active") === Boolean(employee.is_active));
  });
  const activeEmployees = pointEmployees.filter((employee) => employee.is_active);
  $("#employeeTotalLabel").textContent = ownerMode ? "Всего сотрудников" : "Сотрудников заведения";
  $("#employeeTotalCaption").textContent = "включая отключённые учётные записи";
  $("#employeeActiveLabel").textContent = "С активным доступом";
  $("#employeeActiveCaption").textContent = "могут войти в систему";
  $("#employeeCashierLabel").textContent = "С PIN для кассы";
  $("#employeeCashierCaption").textContent = "могут работать на кассах аккаунта";
  $("#employeeTotalCount").textContent = pointEmployees.length;
  $("#employeeActiveCount").textContent = activeEmployees.length;
  $("#employeeCashierCount").textContent = activeEmployees.filter((employee) => employee.has_pin).length;
  $("#employeesTable").innerHTML = visible.map((employee) => {
    const lastSeen = employee.last_seen_at
      ? new Date(employee.last_seen_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })
      : "Ещё не входил";
    const permissions = normalizeEmployeePermissions(employee.permissions, employee.staff_role);
    const adminAccess = employeeHasAdminAccess(permissions);
    const posAccess = permissions.posAccess;
    const accessLabel = employee.staff_role === "production" ? "Только терминал · PIN" : adminAccess && posAccess
      ? `${employee.login} · касса по PIN`
      : adminAccess ? employee.login : posAccess ? (employee.has_pin ? "Касса по PIN" : "PIN не задан") : "Без входа";
    const employeeBranch = branchById(employee.branch_id);
    const scopeCell = `${employeeRoleLabel(employee.staff_role)}${ownerMode && employeeBranch ? ` · ${employeeBranch.name}` : ""}`;
    const canEdit = ownerMode || employee.staff_role !== "branch_manager";
    return `<tr><td><div class="employee-person"><span class="employee-avatar">${escapeHtml(personInitials(employee.display_name))}</span><div><strong>${escapeHtml(employee.display_name)}</strong><small>${escapeHtml(employee.phone || "Телефон не указан")}</small></div></div></td><td><span class="employee-role-badge">${escapeHtml(scopeCell)}</span></td><td><span class="employee-login">${escapeHtml(accessLabel)}</span>${canEdit && posAccess ? `<div class="employee-pin-display"><button class="poster-action secondary-action" data-employee-pin="${employee.id}" type="button">${employee.can_reveal_pin ? "Показать PIN" : employee.has_pin ? "Задать PIN заново" : "Назначить PIN"}</button><span data-employee-pin-value="${employee.id}"></span></div>` : ""}</td><td>${escapeHtml(lastSeen)}</td><td><span class="status-badge ${employee.is_active ? "good" : "warn"}">${employee.is_active ? "Активен" : "Отключён"}</span></td><td><div class="employee-row-actions">${canEdit ? `<button class="poster-action secondary-action" data-edit-employee="${employee.id}" type="button">Настроить</button>` : ""}${canDeleteEmployee(employee) ? `<button class="danger-button icon-button employee-delete-icon" data-delete-employee="${escapeHtml(String(employee.id))}" type="button" title="Удалить сотрудника" aria-label="Удалить сотрудника: ${escapeHtml(employee.display_name)}">${uiIcon('trash')}</button>` : ""}</div></td></tr>`;
  }).join("");
  $("#employeesEmpty").classList.toggle("hidden", Boolean(visible.length));
  $("#employeesTable").closest(".table-scroll").classList.toggle("hidden", !visible.length);
}

function openEmployeeForm(employeeId = null, preferredBranchId = null) {
  if (!branches.length) {
    showToast("Сначала добавьте заведение");
    switchView("branches");
    return;
  }
  const ownerMode = currentRole === "owner";
  const employee = employeeById(employeeId);
  if (!ownerMode && employee?.staff_role === "branch_manager") { showToast("Доступ управляющего меняет администратор компании"); return; }
  const activeBranch = branchById(ownerMode ? (employee?.branch_id || preferredBranchId || branches[0]?.id) : currentSession.branchId);
  if (!activeBranch) {
    showToast("Сначала добавьте заведение");
    switchView("branches");
    return;
  }
  if (!ownerMode && employee && employee.branch_id !== activeBranch.id) { showToast("Этот сотрудник относится к другому заведению"); return; }
  editingEmployeeId = employee?.id || null;
  const initialPermissions = normalizeEmployeePermissions(employee?.permissions, employee?.staff_role || (ownerMode ? "branch_manager" : "cashier"));
  employeeLoginEdited = Boolean(employee && employeeHasAdminAccess(initialPermissions));
  $("#employeeModalTitle").textContent = employee ? "Настроить сотрудника" : "Новый сотрудник";
  $("#employeeNameInput").value = employee?.display_name || "";
  $("#employeePhoneInput").value = employee?.phone || "";
  $("#employeeBranchInput").innerHTML = ownerMode
    ? branches.map((entry) => `<option value="${escapeHtml(entry.id)}">${escapeHtml(entry.name)}</option>`).join("")
    : `<option value="${escapeHtml(activeBranch.id)}">${escapeHtml(activeBranch.name)}</option>`;
  $("#employeeBranchInput").value = activeBranch.id;
  $("#employeeBranchInput").disabled = !ownerMode;
  $("#employeeBranchHint").textContent = ownerMode ? "Основное заведение используется для смен и отчётов, но не ограничивает права внутри аккаунта." : "Основное заведение используется для смен и отчётов.";
  $("#employeeRoleInput").innerHTML = ownerMode
    ? '<option value="branch_manager">Руководитель</option><option value="hall_admin">Администратор зала</option><option value="waiter">Официант</option><option value="storekeeper">Кладовщик</option><option value="production">Производство</option><option value="marketer">Маркетолог</option><option value="cashier">Кассир</option>'
    : '<option value="hall_admin">Администратор зала</option><option value="waiter">Официант</option><option value="storekeeper">Кладовщик</option><option value="production">Производство</option><option value="marketer">Маркетолог</option><option value="cashier">Кассир</option>';
  $("#employeeRoleInput").value = employee?.staff_role || (ownerMode ? "branch_manager" : "cashier");
  $("#employeeRoleInput").disabled = false;
  setEmployeePermissions(initialPermissions, $("#employeeRoleInput").value);
  $("#employeeLoginInput").value = employeeHasAdminAccess(initialPermissions) ? employee?.login || "" : "";
  $("#employeePasswordInput").value = "";
  $("#employeePinInput").value = employee ? "" : generateEmployeePin();
  $("#employeePasswordLabel").textContent = employee ? "Новый пароль" : "Временный пароль";
  $("#employeePasswordHint").textContent = employee ? "Оставьте пустым, если пароль менять не нужно." : "Минимум 8 символов. Пароль будет показан только сейчас.";
  $("#employeeActiveRow").classList.toggle("hidden", !employee);
  $("#employeeActiveInput").checked = employee?.is_active !== false;
  $("#saveEmployeeButton").textContent = employee ? "Сохранить изменения" : "Создать сотрудника";
  $('#deleteEmployeeButton').classList.toggle('hidden', !canDeleteEmployee(employee));
  updateEmployeePermissionNote();
  $("#employeeModal").classList.remove("hidden");
  setTimeout(() => $("#employeeNameInput").focus(), 20);
}

async function saveEmployee() {
  const displayName = $("#employeeNameInput").value.trim();
  const role = $("#employeeRoleInput").value;
  const login = $("#employeeLoginInput").value.trim().toLowerCase();
  const password = $("#employeePasswordInput").value;
  const pin = $("#employeePinInput").value.trim();
  const existing = employeeById(editingEmployeeId);
  const activeBranch = branchById(currentRole === "owner" ? $("#employeeBranchInput").value : currentSession.branchId);
  if (!activeBranch || (currentRole !== "owner" && existing && existing.branch_id !== activeBranch.id)) { showToast("Сотрудник относится к другому заведению"); return; }
  if (!displayName) { showToast("Введите имя сотрудника"); return; }
  const permissions = readEmployeePermissions();
  const posAccess = permissions.posAccess;
  const adminAccess = employeeHasAdminAccess(permissions);
  if (posAccess) {
    if ((!existing?.has_pin || pin) && !/^\d{4}$/.test(pin)) { showToast("PIN для кассы должен состоять из 4 цифр"); return; }
  }
  if (adminAccess) {
    if (!/^[a-zA-Z0-9._@+-]{3,64}$/.test(login)) { showToast("Логин: 3–64 латинских символа, цифры, точка, дефис или подчёркивание"); return; }
    const existingAdminAccess = existing && employeeHasAdminAccess(normalizeEmployeePermissions(existing.permissions, existing.staff_role));
    if ((!existing || !existingAdminAccess) && password.length < 8) { showToast("Временный пароль должен содержать не менее 8 символов"); return; }
    if (existing && password && password.length < 8) { showToast("Новый пароль должен содержать не менее 8 символов"); return; }
  }
  if (pin && !/^\d{4}$/.test(pin)) { showToast("PIN должен состоять из 4 цифр"); return; }
  const payload = {
    display_name: displayName,
    phone: $("#employeePhoneInput").value.trim(),
    branch_id: activeBranch.id,
    staff_role: role,
    permissions,
    ...(adminAccess ? { login } : {}),
    ...(password ? { password } : {}),
    ...(pin ? { pin } : {}),
    ...(existing ? { is_active: $("#employeeActiveInput").checked } : {})
  };
  try {
    let saved;
    if (serverMode) saved = existing
      ? await window.AshkanaApi.updateEmployee(existing.id, payload)
      : await window.AshkanaApi.createEmployee(payload);
    else {
      saved = { ...existing, ...payload, login: adminAccess ? login : "", has_pin: Boolean(pin || existing?.has_pin), id: existing?.id || `employee-${Date.now()}`, is_active: existing ? payload.is_active : true, last_seen_at: existing?.last_seen_at || null };
    }
    if (existing) Object.assign(existing, saved);
    else employees.push(saved);
    $("#employeeModal").classList.add("hidden");
    if (serverMode) {
      const workspace = await window.AshkanaApi.workspace();
      hydrateServerWorkspace(workspace);
    }
    renderAll();
    if (!existing) {
      const branch = branchById(saved.branch_id);
      $("#employeeAccessTitle").textContent = saved.display_name;
      const savedPermissions = normalizeEmployeePermissions(saved.permissions, saved.staff_role);
      const posEmployee = savedPermissions.posAccess && !employeeHasAdminAccess(savedPermissions);
      $("#employeeAccessCopy").textContent = posEmployee ? "Передайте сотруднику личный PIN. Он используется для входа на уже авторизованном терминале." : "Сохраните данные и передайте сотруднику. После закрытия страницы пароль больше не отображается.";
      $("#employeeAccessPrimaryLabel").textContent = posEmployee ? "PIN сотрудника" : "Логин";
      $("#employeeAccessSecondaryLabel").textContent = posEmployee ? "Способ входа" : "Временный пароль";
      $("#createdEmployeeLogin").textContent = posEmployee ? pin : login;
      $("#createdEmployeePassword").textContent = posEmployee ? "Личный PIN в терминале" : password;
      $("#employeeAccessPinField").classList.toggle("hidden", posEmployee || !savedPermissions.posAccess || !pin);
      $("#createdEmployeePin").textContent = savedPermissions.posAccess ? pin : "—";
      const entryUrl = `${location.origin}/${posEmployee ? "pos" : "login"}`;
      $("#createdEmployeeLink").href = entryUrl;
      $("#createdEmployeeLink").textContent = entryUrl;
      $("#employeeAccessHint").textContent = `${employeeRoleLabel(saved.staff_role)} · ${branch?.name || "Заведение"}`;
      lastEmployeeAccessText = posEmployee
        ? `${saved.display_name}\n${employeeRoleLabel(saved.staff_role)} · ${branch?.name || "Заведение"}\nPIN сотрудника: ${pin}\nВход: ${entryUrl}\nВведите PIN на авторизованном терминале.`
        : `${saved.display_name}\n${employeeRoleLabel(saved.staff_role)} · ${branch?.name || "Заведение"}\nВход: ${entryUrl}\nЛогин: ${login}\nВременный пароль: ${password}${savedPermissions.posAccess ? `\nPIN сотрудника: ${pin}` : ""}`;
      $("#employeeAccessModal").classList.remove("hidden");
    } else showToast("Данные сотрудника сохранены");
  } catch (error) {
    if (error.status === 401) { signOutRevokedBranch(); return; }
    showToast(error.message || "Не удалось сохранить сотрудника");
  }
}

function renderRecipes() {
  const query = $("#recipeSearch").value.trim().toLowerCase();
  const category = $("#recipeCategory").value;
  const station = $("#recipeStationFilter").value;
  const visible = recipes.filter((recipe) => (!query || recipe.name.toLowerCase().includes(query)) && (category === "Все категории" || recipe.category === category) && (station === "Все цеха" || recipeStation(recipe) === station));
  $("#recipeCount").textContent = recipes.length;
  $("#ingredientCount").textContent = ingredients.length;
  $("#recipesTable").innerHTML = visible.map((recipe) => {
    const cost = recipeCost(recipe);
    return `<tr data-recipe-id="${recipe.id}"><td><div class="dish-cell">${CatalogCover.thumb(recipe)}<div><strong>${recipe.name}</strong><small>Код ${recipe.id}</small></div></div></td><td>${recipe.category}</td><td>${recipeStation(recipe)}</td><td>${decimal(recipe.yield / 1000, 3)} кг</td><td><strong>${money(cost)}</strong></td><td><strong>${money(recipe.price)}</strong></td><td><span class="margin-value">${decimal(markup(recipe))}%</span></td><td><button class="poster-action secondary-action" data-recipe-compose="${recipe.id}" type="button">Состав</button></td><td><button class="poster-action secondary-action" data-recipe-edit="${recipe.id}" type="button">Изменить</button></td></tr>`;
  }).join("");
}

function renderProducts() {
  const query = $("#productSearch").value.trim().toLowerCase();
  const visible = products.filter((product) => !product.parentId && (!query || [product, ...products.filter(item => item.parentId === product.id)].some(item => item.name.toLowerCase().includes(query) || (item.barcode || "").includes(query))));
  $("#productsCount").textContent = products.filter(product => !product.parentId).length;
  $("#productsTable").innerHTML = visible.map((product) => {
    const branchId = currentSession.branchId || pendingOwnerObjectScope || branches[0]?.id || "";
    const unitCost = branchUnitCost(branchId, product.id);
    const productMarkup = unitCost ? (product.price - unitCost) / unitCost * 100 : 0;
    const variants = product.variantName ? [product, ...products.filter(item => item.parentId === product.id)] : [];
    const priceLabel = variants.length ? `от ${money(Math.min(...variants.map(item => item.price)))}` : money(product.price);
    const stockTotal = variants.length ? variants.reduce((sum,item) => sum + branchStock(branchId, item.id), 0) : branchStock(branchId, product.id);
    return `<tr><td><div class="dish-cell"><span class="dish-color" style="background:${escapeHtml(product.color || "#5b8fbd")}">${product.image ? `<img src="${escapeHtml(product.image)}" alt="" />` : escapeHtml(product.name.slice(0, 1))}</span><div><strong>${escapeHtml(product.groupName || product.name)}</strong><small>${product.variantName ? `${1 + products.filter(row => row.parentId === product.id).length} модификаций` : "Готовый товар · без рецепта"}</small></div></div></td><td>${product.category}</td><td>${variants.length ? "По модификациям" : escapeHtml(product.barcode || "—")}</td><td>${variants.length ? "По модификациям" : money(unitCost)}</td><td><strong>${priceLabel}</strong></td><td><span class="margin-value">${variants.length ? "—" : `${decimal(productMarkup)}%`}</span></td><td>${decimal(stockTotal, 3)} ${product.unit}</td><td><button class="poster-action secondary-action" data-product-edit="${product.id}" type="button">Изменить</button></td></tr>`;
  }).join("");
}

function preparationById(id) {
  return preparations.find((preparation) => String(preparation.id) === String(id));
}

function preparationCost(preparation) {
  if (!Array.isArray(preparation?.components) || !preparation.components.length) return Number(preparation?.cost || 0);
  const branchId = currentSession.branchId || pendingOwnerObjectScope || branches[0]?.id || "";
  return preparation.components.reduce((total, component) => {
    const ingredient = ingredientById(component.ingredientId);
    const unitCost = ingredient ? branchUnitCost(branchId, ingredient.id) || Number(ingredient.averageCost || 0) : 0;
    return total + unitCost * componentGross(component) / 1000;
  }, 0);
}

function renderPreparations() {
  const query = $("#preparationSearch").value.trim().toLowerCase();
  const category = $("#preparationCategoryFilter").value;
  const visible = preparations.filter((preparation) => (!query || preparation.name.toLowerCase().includes(query) || String(preparation.usedIn || "").toLowerCase().includes(query)) && (category === "Все категории" || preparation.category === category));
  $("#preparationsCount").textContent = preparations.length;
  $("#preparationsTable").innerHTML = visible.length ? visible.map((preparation) => {
    const batchCost = preparationCost(preparation);
    const unitCost = Number(preparation.yield) > 0 ? batchCost / (Number(preparation.yield) / 1000) : 0;
    const id = escapeHtml(String(preparation.id));
    return `<tr data-preparation-id="${id}"><td><button class="dish-cell preparation-open" data-preparation-compose="${id}" type="button" aria-haspopup="dialog" aria-label="Состав: ${escapeHtml(preparation.name)}">${CatalogCover.thumb(preparation)}<span><strong>${escapeHtml(preparation.name)}</strong><small>${escapeHtml(String(preparation.id).toUpperCase())}</small></span></button></td><td>${escapeHtml(preparation.category || "Без категории")}</td><td>${escapeHtml(preparation.station || "Кухня")}</td><td>${decimal(preparation.yield / 1000, 3)} кг</td><td><strong>${money(batchCost)}</strong><small>${money(unitCost)} / кг</small></td><td>${escapeHtml(preparation.usedIn || "Не указано")}</td><td><div class="preparation-row-actions"><button class="poster-action secondary-action" data-preparation-compose="${id}" type="button" aria-haspopup="dialog">Состав</button><button class="poster-action secondary-action" data-preparation-edit="${id}" type="button">Изменить</button></div></td></tr>`;
  }).join("") : `<tr class="table-empty"><td colspan="7">${preparations.length ? "По заданным условиям полуфабрикаты не найдены" : "Полуфабрикаты ещё не настроены"}</td></tr>`;
}

function renderIngredientsMenu() { window.IngredientsList.render(); }

function renderMenuCategories() {
  menuCategories = normalizeMenuCategories(menuCategories);
  ingredientCategories = normalizeIngredientCategories(ingredientCategories);
  $("#menuCategoriesTable").innerHTML = menuCategories.map((category, index) => {
    const recipeCount = recipes.filter((recipe) => recipe.category === category.name).length;
    const productCount = products.filter((product) => product.category === category.name).length;
    const type = recipeCount && productCount ? "Товары и тех. карты" : recipeCount ? "Тех. карты" : "Товары";
    const resolvedType = recipeCount + productCount ? type : "Без позиций";
    return `<tr><td><div class="menu-category-cell">${CatalogCover.thumb(category)}<strong>${escapeHtml(category.name)}</strong></div></td><td>${resolvedType}</td><td>${recipeCount + productCount}</td><td><span class="visibility-badge">Все точки</span></td><td>${category.color.toUpperCase()}</td><td><button class="poster-action secondary-action" data-menu-category-edit="${index}" type="button">Изменить</button></td></tr>`;
  }).join("");

  $("#ingredientCategoriesTable").innerHTML = ingredientCategories.map((category, index) => {
    const branchId = currentSession.branchId || pendingOwnerObjectScope || branches[0]?.id || "";
    const group = ingredients.filter((ingredient) => ingredient.category === category);
    const value = group.reduce((sum, ingredient) => sum + branchStock(branchId, ingredient.id) * branchUnitCost(branchId, ingredient.id), 0);
    return `<tr><td><div class="dish-cell">${CatalogCover.thumb(ingredientCategoryCovers[category], category)}<strong>${escapeHtml(category)}</strong></div></td><td>${group.length}</td><td>${money(value)}</td><td><button class="poster-action secondary-action" data-ingredient-category-edit="${index}" type="button">Изменить</button></td></tr>`;
  }).join("");

  $("#stationsTable").innerHTML = stations.length ? stations.map((station) => {
    const linkedRecipes = recipes.filter((recipe) => recipeStation(recipe) === station.name).length;
    const linkedPreparations = preparations.filter((preparation) => preparation.station === station.name).length;
    return `<tr><td><strong>${escapeHtml(station.name)}</strong>${linkedPreparations ? `<small>${linkedPreparations} ${pluralRu(linkedPreparations, "полуфабрикат", "полуфабриката", "полуфабрикатов")}</small>` : ""}</td><td>${escapeHtml(stationWarehouseLabel(station))}</td><td>${linkedRecipes}</td><td>${escapeHtml(station.destination || "Без печати")}</td><td><button class="poster-action secondary-action" data-station-edit="${escapeHtml(station.name)}" type="button">Изменить</button></td></tr>`;
  }).join("") : '<tr class="table-empty"><td colspan="5">Цеха ещё не настроены. Добавьте первый цех.</td></tr>';
  refreshCategoryControls();
}

function refreshCategoryControls() {
  const selectedRecipeCategory = $("#recipeCategory").value;
  $("#recipeCategory").innerHTML = `<option>Все категории</option>${menuCategories.map((category) => `<option value="${escapeHtml(category.name)}">${escapeHtml(category.name)}</option>`).join("")}`;
  $("#recipeCategory").value = [...$("#recipeCategory").options].some((option) => option.value === selectedRecipeCategory) ? selectedRecipeCategory : "Все категории";
  const selectedStockCategory = $("#stockCategoryFilter").value;
  const stockCategories = [...new Set([...ingredientCategories, ...menuCategories.map((category) => category.name)])];
  $("#stockCategoryFilter").innerHTML = `<option>Все категории</option>${stockCategories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`).join("")}`;
  $("#stockCategoryFilter").value = [...$("#stockCategoryFilter").options].some((option) => option.value === selectedStockCategory) ? selectedStockCategory : "Все категории";
  const stationNames = stationNamesWithLegacy();
  [$("#recipeStationFilter"), $("#productionStationFilter")].forEach((select) => {
    const selected = select.value;
    select.innerHTML = `<option>Все цеха</option>${stationNames.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("")}`;
    select.value = [...select.options].some((option) => option.value === selected) ? selected : "Все цеха";
  });
}

function openCategoryForm(kind, index = null) {
  editingCategoryKind = kind;
  const isMenuCategory = kind === "menu";
  const entry = index == null ? null : (isMenuCategory ? menuCategories[Number(index)] : ingredientCategories[Number(index)]);
  editingCategoryName = isMenuCategory ? entry?.name || null : entry || null;
  const linkedCount = isMenuCategory
    ? [...recipes, ...products].filter((item) => item.category === editingCategoryName).length
    : ingredients.filter((item) => item.category === editingCategoryName).length;
  $("#categoryModalEyebrow").textContent = isMenuCategory ? "Меню / Категории товаров и тех. карт" : "Меню / Категории ингредиентов";
  $("#categoryModalTitle").textContent = entry ? "Редактировать категорию" : "Новая категория";
  $("#categoryModalDescription").textContent = isMenuCategory
    ? "Категория объединяет блюда и готовые товары и отображается на кассе."
    : "Категория используется в складском учёте, фильтрах и инвентаризации.";
  $("#categoryNameInput").value = editingCategoryName || "";
  $("#categoryColorField").classList.remove("hidden");
  const color = isMenuCategory ? entry?.color || categoryPalette[menuCategories.length % categoryPalette.length] : ingredientCategoryCovers[entry]?.color || "#633d60";
  $("#categoryColorInput").value = color;
  $("#categoryColorText").value = color.toUpperCase();
  CatalogCover.open("category", isMenuCategory ? entry : ingredientCategoryCovers[entry], "categoryColorInput");
  $("#categoryLinkedText").textContent = entry
    ? `${linkedCount} ${pluralRu(linkedCount, "связанная позиция будет обновлена", "связанные позиции будут обновлены", "связанных позиций будут обновлены")} автоматически.`
    : "Категорию можно создать заранее и затем выбрать в карточке позиции.";
  $("#deleteCategoryButton").classList.toggle("hidden", !entry);
  $("#saveCategoryButton").textContent = "Сохранить";
  $("#categoryModal").classList.remove("hidden");
  setTimeout(() => $("#categoryNameInput").focus(), 20);
}

async function saveCategoryForm() {
  if (!CatalogCover.ready("category")) return;
  const name = $("#categoryNameInput").value.trim();
  if (!name) {
    showToast("Введите название категории");
    return;
  }
  const isMenuCategory = editingCategoryKind === "menu";
  const duplicate = isMenuCategory
    ? menuCategories.some((category) => category.name.toLowerCase() === name.toLowerCase() && category.name !== editingCategoryName)
    : ingredientCategories.some((category) => category.toLowerCase() === name.toLowerCase() && category !== editingCategoryName);
  if (duplicate) {
    showToast("Категория с таким названием уже существует");
    return;
  }
  const colorText = $("#categoryColorText").value.trim();
  const color = /^#[0-9a-f]{6}$/i.test(colorText) ? colorText.toLowerCase() : $("#categoryColorInput").value.toLowerCase();
  const image = CatalogCover.read("category").image;
  const payload = { kind: editingCategoryKind, originalName: editingCategoryName, name, color, image };
  if (serverMode) {
    const response = await runServerAction("category.upsert", payload);
    if (!response) return;
    $("#categoryModal").classList.add("hidden");
    switchMenuPage(isMenuCategory ? "menu-categories" : "ingredient-categories");
    showToast(editingCategoryName ? "Категория и связанные позиции обновлены" : "Категория создана");
    return;
  }
  if (isMenuCategory) {
    if (editingCategoryName) {
      const category = menuCategories.find((item) => item.name === editingCategoryName);
      if (category) Object.assign(category, { name, color, image });
      recipes.forEach((recipe) => {
        if (recipe.category === editingCategoryName) Object.assign(recipe, { category: name });
      });
      products.forEach((product) => { if (product.category === editingCategoryName) product.category = name; });
    } else menuCategories.push({ name, color, image });
    saveRecipes();
    saveProducts();
  } else {
    if (editingCategoryName) {
      const categoryIndex = ingredientCategories.indexOf(editingCategoryName);
      if (categoryIndex >= 0) ingredientCategories[categoryIndex] = name;
      ingredients.forEach((ingredient) => { if (ingredient.category === editingCategoryName) ingredient.category = name; });
    } else ingredientCategories.push(name);
    saveIngredients();
  }
  if (!isMenuCategory) { if (editingCategoryName && editingCategoryName !== name) delete ingredientCategoryCovers[editingCategoryName]; ingredientCategoryCovers[name] = {color,image}; }
  saveCategoryRegistries();
  $("#categoryModal").classList.add("hidden");
  renderAll();
  switchMenuPage(isMenuCategory ? "menu-categories" : "ingredient-categories");
  showToast(editingCategoryName ? "Категория и связанные позиции обновлены" : "Категория создана");
}

function stationDestinationMode(destination) {
  const value = String(destination || "");
  if (!value || value === "Без печати") return "none";
  return value.toLowerCase().includes("принтер") ? "printer" : "screen";
}

function updateStationDestinationField() {
  const mode = $("#stationDestinationMode").value;
  $("#stationDestinationField").classList.toggle("hidden", mode === "none");
  const label = $("#stationDestinationField span");
  label.textContent = mode === "printer" ? "Название принтера" : "Название экрана кухни";
  $("#stationDestinationInput").placeholder = mode === "printer" ? "Например, Принтер горячего цеха" : "Например, Экран кухни №1";
}

function openStationForm(stationName = null) {
  const station = stations.find((entry) => entry.name === stationName);
  editingStationName = station?.name || null;
  $("#stationModalTitle").textContent = station ? "Редактировать цех" : "Новый цех";
  $("#stationNameInput").value = station?.name || "";
  $("#stationBranchInput").innerHTML = branches.length
    ? branches.map((branch) => `<option value="${escapeHtml(branch.id)}">${escapeHtml(branch.name)} · склад точки</option>`).join("")
    : '<option value="">Сначала создайте точку</option>';
  $("#stationBranchInput").value = station?.branchId || pendingOwnerObjectScope || branches[0]?.id || "";
  const mode = stationDestinationMode(station?.destination);
  $("#stationDestinationMode").value = mode;
  $("#stationDestinationInput").value = mode === "none" ? "" : station?.destination || "";
  updateStationDestinationField();
  const linkedRecipes = station ? recipes.filter((recipe) => recipeStation(recipe) === station.name).length : 0;
  const linkedPreparations = station ? preparations.filter((preparation) => preparation.station === station.name).length : 0;
  $("#stationLinkedText").textContent = station
    ? `${linkedRecipes} ${pluralRu(linkedRecipes, "техкарта", "техкарты", "техкарт")} и ${linkedPreparations} ${pluralRu(linkedPreparations, "полуфабрикат", "полуфабриката", "полуфабрикатов")} будут обновлены при переименовании.`
    : "После создания цех можно назначить технологическим картам и полуфабрикатам.";
  $("#deleteStationButton").classList.toggle("hidden", !station);
  $("#saveStationButton").textContent = "Сохранить";
  $("#stationModal").classList.remove("hidden");
  setTimeout(() => $("#stationNameInput").focus(), 20);
}

async function saveStationForm() {
  const name = $("#stationNameInput").value.trim();
  const branchId = $("#stationBranchInput").value;
  const mode = $("#stationDestinationMode").value;
  const destinationName = $("#stationDestinationInput").value.trim();
  if (!name) { showToast("Введите название цеха"); return; }
  if (!branchById(branchId)) { showToast("Выберите точку и склад списания"); return; }
  if (mode !== "none" && !destinationName) { showToast("Укажите название экрана или принтера"); return; }
  if (stations.some((station) => station.name.toLowerCase() === name.toLowerCase() && station.name !== editingStationName)) {
    showToast("Цех с таким названием уже существует");
    return;
  }
  const destination = mode === "none" ? "Без печати" : destinationName;
  const payload = { originalName: editingStationName, name, branchId, destination };
  if (serverMode) {
    const response = await runServerAction("station.upsert", payload);
    if (!response) return;
    $("#stationModal").classList.add("hidden");
    switchMenuPage("stations");
    showToast(editingStationName ? "Цех и связанные позиции обновлены" : "Цех создан");
    return;
  }
  const existing = stations.find((station) => station.name === editingStationName);
  if (existing) {
    const previousName = existing.name;
    recipes.forEach((recipe) => { if (recipeStation(recipe) === previousName) recipe.station = name; });
    preparations.forEach((preparation) => { if (preparation.station === previousName) preparation.station = name; });
    products.forEach(product => { if (product.station === previousName) product.station = name; });
    saveProducts();
    Object.assign(existing, { name, branchId, warehouse: stationWarehouseLabel({ branchId }), destination });
  } else stations.push({ name, branchId, warehouse: stationWarehouseLabel({ branchId }), destination });
  saveStations();
  saveRecipes();
  savePreparations();
  $("#stationModal").classList.add("hidden");
  renderAll();
  switchMenuPage("stations");
  showToast(editingStationName ? "Цех и связанные позиции обновлены" : "Цех создан");
}

function renderStock(scope = stockDisplayScope) {
  stockDisplayScope = currentRole === "owner" ? "network" : "branch";
  const query = $("#stockSearch").value.trim().toLowerCase();
  const category = $("#stockCategoryFilter").value;
  const branchId = currentSession.branchId;
  const branch = branchById(branchId);
  const networkMode = currentRole === "owner";
  $("#stockWarehouseFilter").innerHTML = `<option>${networkMode ? "Вся сеть" : escapeHtml(branch?.name || "Точка")}</option>`;
  const stockEntities = [...ingredients, ...products];
  const visible = stockEntities.filter((entity) => (!query || entity.name.toLowerCase().includes(query)) && (category === "Все категории" || entity.category === category));
  const quantityFor = (entity) => networkMode
    ? branches.reduce((sum, entry) => sum + branchStock(entry.id, entity.id), 0)
    : branchStock(branchId, entity.id);
  const costFor = (entity) => {
    if (!networkMode) return branchUnitCost(branchId, entity.id);
    const totals = branches.reduce((result, entry) => {
      const quantity = branchStock(entry.id, entity.id);
      result.quantity += quantity;
      result.value += quantity * branchUnitCost(entry.id, entity.id);
      return result;
    }, { quantity: 0, value: 0 });
    return totals.quantity ? totals.value / totals.quantity : 0;
  };
  const stockValue = stockEntities.reduce((sum, entity) => sum + quantityFor(entity) * costFor(entity), 0);
  const lowCount = stockEntities.filter((entity) => quantityFor(entity) <= Number(entity.limit || 0)).length;
  $("#stockValue").textContent = money(stockValue);
  $("#stockValueCaption").textContent = networkMode ? "суммарно по всем точкам" : `на складе ${branch?.short || "точки"}`;
  $("#stockPositions").textContent = stockEntities.filter((entity) => quantityFor(entity) > 0).length;
  $("#stockPositionsCaption").textContent = networkMode ? "есть хотя бы на одной точке" : "фактически есть на точке";
  $("#lowStockCount").textContent = lowCount;
  $("#lowStockLabel").textContent = "Ниже лимита";
  $("#lowStockCaption").textContent = "нужно заказать поставщику";
  $("#stockLimitHeading").textContent = "Лимит";
  const lastSupply = (logisticsState.supplies || []).filter((supply) => networkMode || supply.branchId === branchId).sort((a, b) => new Date(b.receivedAt || b.createdAt) - new Date(a.receivedAt || a.createdAt))[0];
  $("#lastSupplyLabel").textContent = "Последняя приёмка";
  $("#lastSupplyTotal").textContent = lastSupply ? money(lastSupply.total || 0) : "—";
  $("#lastSupplyCaption").textContent = lastSupply ? `${new Date(lastSupply.receivedAt || lastSupply.createdAt).toLocaleDateString("ru-RU")} · ${lastSupply.supplier}` : "поставок пока нет";
  $("#stockTable").innerHTML = visible.map((entity) => {
    const available = quantityFor(entity);
    const limit = Number(entity.limit || 0);
    const low = available <= limit;
    const critical = available <= limit * .6;
    const movement = networkMode ? "Суммарно по сети" : isProductEntity(entity) ? "Готовый товар точки" : "Сырьё кухни точки";
    const status = critical ? "Критично" : low ? "Заказать" : "В норме";
    const unitCost = costFor(entity);
    return `<tr><td><span class="stock-name">${escapeHtml(entity.name)}</span><small>${movement}</small></td><td>${escapeHtml(entity.category)}</td><td><span class="stock-value ${low ? "low" : ""}">${decimal(available, 3)} ${entity.unit}</span></td><td>${money(unitCost)} / ${entity.unit}</td><td><strong>${money(available * unitCost)}</strong></td><td>${decimal(limit, 3)} ${entity.unit}</td><td><span class="status-badge ${critical ? "bad" : low ? "warn" : "good"}">${status}</span></td></tr>`;
  }).join("");
}

function supplierDocuments(supplier) {
  return (logisticsState.supplies || []).filter((supply) => supply.supplierId === supplier.id).map((supply) => ({ ...supply, createdAt: supply.receivedAt || supply.createdAt }));
}

function supplierLocationLabels(supplier) {
  return (supplier.locations || (branches[0]?.id ? [branches[0].id] : [])).map((location) => branchById(location)?.name || location);
}

function renderSuppliers() {
  const query = $("#supplierSearch").value.trim().toLowerCase();
  const status = $("#supplierStatusFilter").value;
  const visible = suppliers.filter((supplier) => {
    const haystack = `${supplier.name} ${supplier.inn} ${supplier.phone} ${supplier.email || ""} ${supplier.contact}`.toLowerCase();
    return (!query || haystack.includes(query)) && (status === "all" || supplier.status === status);
  });
  $("#supplierCount").textContent = visible.length;
  $("#suppliersTable").innerHTML = visible.map((supplier) => {
    const documents = supplierDocuments(supplier);
    const total = documents.reduce((sum, document) => sum + Number(document.total || 0), 0);
    const lastDelivery = documents.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))[0];
    const debt = documents.reduce((sum, document) => sum + Number(document.debt || 0), 0);
    const action = `<button class="poster-action secondary-action" data-supplier-edit="${supplier.id}" type="button">Изменить</button>`;
    const contactDetails = [supplier.contact, supplier.email].filter(Boolean).join(" · ") || "Контакт не указан";
    return `<tr><td><strong>${escapeHtml(supplier.name)}</strong><small>${supplier.inn ? `ИНН ${escapeHtml(supplier.inn)}` : escapeHtml(supplier.comment || "Без комментария")}</small></td><td><div class="supplier-location-tags"><span>Весь аккаунт</span></div></td><td><strong>${escapeHtml(supplier.phone || "—")}</strong><small>${escapeHtml(contactDetails)}</small></td><td>${escapeHtml(supplier.address || "—")}</td><td><strong>${documents.length}</strong><small>${lastDelivery ? `последняя ${new Date(lastDelivery.createdAt).toLocaleDateString("ru-RU")}` : "поставок ещё нет"}</small></td><td><strong>${money(total)}</strong></td><td><strong class="${debt > 0 ? "deficit-value" : "available-value"}">${money(debt)}</strong></td><td><span class="status-badge ${supplier.status === "active" ? "good" : "warn"}">${supplier.status === "active" ? "Активный" : "Архивный"}</span></td><td>${action}</td></tr>`;
  }).join("");
  $("#suppliersEmpty").classList.toggle("hidden", visible.length > 0);
  $("#suppliersTable").parentElement.classList.toggle("hidden", visible.length === 0);
}

const stockTabConfig = {
  inventories: { title: "Инвентаризации", subtitle: "Подсчёты, расхождения и подтверждение корректировок", action: "Добавить инвентаризацию" },
  suppliers: { title: "Поставщики", subtitle: "Единый справочник поставщиков и задолженность по поставкам", action: "Добавить поставщика" },
  supplies: { title: "Поставки", subtitle: "Приходные накладные, оплаты и задолженность поставщикам", action: "Добавить поставку" },
  "point-transfers": { title: "Перемещения между точками", subtitle: "Запросы, отгрузки и приёмка продуктов между столовыми", action: "Создать перемещение" },
  writeoff: { title: "Списания", subtitle: "Порча, питание сотрудников и другие ручные списания продуктов", action: "Добавить списание" },
  movement: { title: "Отчёт по движению", subtitle: "Поставки, продажи, производство, списания и корректировки остатков", action: "" }
};

function documentTypeLabel(type) {
  return { supply: "Поставка", transfer: "Перемещение", writeoff: "Списание", production: "Производство", inventory: "Инвентаризация", sale: "Продажа" }[type] || "Документ";
}

function movementDocuments() {
  const documents = stockDocuments.map((document) => ({ ...document }));
  (logisticsState.supplies || []).forEach((supply) => documents.push({
    ...supply,
    type: "supply",
    createdAt: supply.receivedAt || supply.createdAt,
    warehouse: branchById(supply.branchId)?.name || "Заведение",
    description: `${supply.supplier} · ${(supply.items || []).length} позиций`,
    status: "Проведён",
    delta: 1
  }));
  getSales().forEach((sale) => documents.push({
    id: sale.id,
    type: "sale",
    number: `ЧЕК-${String(sale.number).padStart(4, "0")}`,
    createdAt: sale.createdAt,
    status: "Проведён",
    warehouse: sale.branch,
    total: sale.items.reduce((sum, item) => {
      const recipe = recipes.find((entry) => entry.id === item.id);
      return sum + (recipe ? recipeCost(recipe) * item.quantity : 0);
    }, 0),
    description: `${sale.items.length} позиций · продажа с кассы`
  }));
  return documents.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
}

function configureDocumentFilters(tab) {
  const changedTab = activeDocumentFilterTab !== tab;
  activeDocumentFilterTab = tab;
  if (changedTab) {
    $("#documentSearch").value = "";
    $("#documentDateFrom").value = "";
    $("#documentDateTo").value = "";
  }

  const partySelect = $("#documentPartyFilter");
  const statusSelect = $("#documentStatusFilter");
  const previousParty = changedTab ? "all" : partySelect.value;
  const previousStatus = changedTab ? "all" : statusSelect.value;
  let partyLabel = "Склад / контрагент";
  let partyAllLabel = "Все контрагенты";
  let partyOptions = [];
  let statusOptions = [];

  if (tab === "supplies") {
    partyLabel = "Компания / поставщик";
    partyAllLabel = "Все поставщики";
    partyOptions = suppliers.map((supplier) => ({ value: supplier.id, label: supplier.name }));
    statusOptions = [["paid", "Оплачена"], ["partial", "Частично оплачена"], ["unpaid", "Не оплачена"]].map(([value, label]) => ({ value, label }));
  } else if (tab === "point-transfers") {
    partyLabel = "Точка";
    partyAllLabel = "Все точки";
    partyOptions = branches.map((branch) => ({ value: branch.id, label: branch.name }));
    statusOptions = [["submitted", "На согласовании"], ["approved", "К отгрузке"], ["shipped", "В пути"], ["received", "Принято"], ["cancelled", "Отменено"]].map(([value, label]) => ({ value, label }));
  } else if (tab === "inventories") {
    partyLabel = "Точка";
    partyAllLabel = "Все точки";
    partyOptions = branches.map((branch) => ({ value: branch.id, label: branch.name }));
    statusOptions = [["counting", "Идёт подсчёт"], ["submitted", "На проверке"], ["returned", "На пересчёте"], ["posted", "Проведена"], ["cancelled", "Отменена"]].map(([value, label]) => ({ value, label }));
  } else if (["requests", "transfer"].includes(tab)) {
    partyLabel = "Столовая";
    partyAllLabel = "Все точки";
    partyOptions = branches.map((branch) => ({ value: branch.id, label: branch.name }));
    statusOptions = (tab === "requests"
      ? [["submitted", "Подана"], ["approved", "К комплектации"], ["shipped", "В пути"], ["received", "Принята"]]
      : [["shipped", "В пути"], ["received", "Принята"]]
    ).map(([value, label]) => ({ value, label }));
  } else if (tab === "movement") {
    partyLabel = "Тип операции";
    partyAllLabel = "Все операции";
    partyOptions = ["supply", "transfer", "writeoff", "production", "inventory", "sale"].map((type) => ({ value: type, label: documentTypeLabel(type) }));
  } else {
    const sources = stockDocuments.filter((document) => document.type === tab).map((document) => document.supplier || document.warehouse).filter(Boolean);
    partyOptions = [...new Set(sources)].map((source) => ({ value: source, label: source }));
  }

  if (!statusOptions.length) {
    const collection = tab === "movement" ? movementDocuments() : tab === "supplies" ? (logisticsState.supplies || []) : stockDocuments.filter((document) => document.type === tab);
    statusOptions = [...new Set(collection.map((document) => document.status).filter(Boolean))].map((status) => ({ value: status, label: status }));
  }

  $("#documentPartyLabel").textContent = partyLabel;
  partySelect.innerHTML = `<option value="all">${partyAllLabel}</option>${partyOptions.map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join("")}`;
  statusSelect.innerHTML = `<option value="all">Все статусы</option>${statusOptions.map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`).join("")}`;
  if ([...partySelect.options].some((option) => option.value === previousParty)) partySelect.value = previousParty;
  if ([...statusSelect.options].some((option) => option.value === previousStatus)) statusSelect.value = previousStatus;
  $("#documentSearch").placeholder = tab === "supplies" ? "Накладная, продукт или поставщик" : tab === "requests" ? "Заявка, точка или продукт" : tab === "point-transfers" ? "Перемещение, точка или продукт" : tab === "inventories" ? "Документ, сотрудник или продукт" : tab === "transfer" ? "Накладная, получатель или товар" : "Документ, товар или описание";
}

function filterWarehouseDocuments(tab, collection) {
  const query = $("#documentSearch").value.trim().toLowerCase();
  const dateFrom = $("#documentDateFrom").value;
  const dateTo = $("#documentDateTo").value;
  const party = $("#documentPartyFilter").value;
  const status = $("#documentStatusFilter").value;
  const fromTime = dateFrom ? new Date(`${dateFrom}T00:00:00`).getTime() : null;
  const toTime = dateTo ? new Date(`${dateTo}T23:59:59.999`).getTime() : null;

  return collection.filter((entry) => {
    const branch = branchById(entry.branchId);
    const sourceBranch = branchById(entry.sourceBranchId);
    const destinationBranch = branchById(entry.destinationBranchId);
    const itemNames = (entry.items || []).map((item) => stockEntityById(item.itemId)?.name || item.itemId).join(" ");
    const haystack = [entry.number, entry.transferNumber, entry.invoiceNumber, entry.supplier, entry.warehouse, entry.description, entry.reason, entry.comment, entry.reviewComment, entry.responsible, entry.createdBy, entry.shippedBy, branch?.name, branch?.short, sourceBranch?.name, sourceBranch?.short, destinationBranch?.name, destinationBranch?.short, itemNames, requestStatusLabel(entry.status), directOrderStatusLabel(entry.status), pointTransferStatusLabel(entry.status), inventoryStatusLabel(entry.status), documentTypeLabel(entry.type)].filter(Boolean).join(" ").toLowerCase();
    const eventDate = tab === "inventories" ? entry.postedAt || entry.submittedAt || entry.createdAt : tab === "point-transfers" ? entry.receivedAt || entry.shippedAt || entry.createdAt : tab === "transfer" ? entry.shippedAt || entry.createdAt : tab === "supplies" ? entry.receivedAt || entry.createdAt : entry.createdAt;
    const eventTime = new Date(eventDate || 0).getTime();
    let matchesParty = true;
    if (party !== "all") {
      if (tab === "point-transfers") matchesParty = entry.sourceBranchId === party || entry.destinationBranchId === party;
      else if (tab === "inventories") matchesParty = entry.branchId === party;
      else if (["requests", "transfer"].includes(tab)) matchesParty = entry.branchId === party;
      else if (tab === "movement") matchesParty = entry.type === party;
      else if (tab === "supplies") matchesParty = entry.supplierId === party || (!entry.supplierId && entry.supplier === supplierById(party)?.name);
      else matchesParty = (entry.supplier || entry.warehouse) === party;
    }
    return (!query || haystack.includes(query))
      && (fromTime === null || eventTime >= fromTime)
      && (toTime === null || eventTime <= toTime)
      && matchesParty
      && (status === "all" || (tab === "supplies" ? entry.paymentStatus === status : entry.status === status));
  });
}

function updateDocumentFilterResult(tab, allItems, visibleItems) {
  const hasActiveFilters = Boolean($("#documentSearch").value.trim() || $("#documentDateFrom").value || $("#documentDateTo").value || $("#documentPartyFilter").value !== "all" || $("#documentStatusFilter").value !== "all");
  const quantityTab = ["requests", "transfer", "point-transfers"].includes(tab);
  const inventoryTab = tab === "inventories";
  const amount = inventoryTab
    ? money(visibleItems.reduce((sum, inventory) => { const totals = inventoryTotals(inventory); return sum + totals.surplus + totals.shortage; }, 0))
    : quantityTab
    ? `${decimal(visibleItems.reduce((sum, entry) => sum + (tab === "point-transfers" ? pointTransferQuantity(entry, "requested") : requestTotalQuantity(entry, tab === "transfer" ? "shipped" : "requested")), 0), 2)} ед.`
    : money(visibleItems.reduce((sum, document) => sum + Number(document.total || 0), 0));
  $("#documentFilterSummary").innerHTML = `Показано <b>${visibleItems.length}</b> из ${allItems.length} · ${inventoryTab ? "Расхождения" : quantityTab ? "Количество" : "Сумма"}: <strong>${amount}</strong>`;
  $("#resetDocumentFilters").classList.toggle("active", hasActiveFilters);
  const filteredEmpty = allItems.length > 0 && visibleItems.length === 0;
  if (filteredEmpty) {
    $("#documentsEmpty strong").textContent = "По фильтрам ничего не найдено";
    $("#documentsEmpty p").textContent = "Измените период, компанию, статус или очистите поиск.";
    $("#createFirstRequestButton").classList.add("hidden");
  }
  $("#documentsEmpty").classList.toggle("hidden", visibleItems.length > 0);
  $("#documentsTableHead").parentElement.classList.toggle("hidden", visibleItems.length === 0);
}

function renderDocuments(tab = document.querySelector("[data-stock-tab].active")?.dataset.stockTab || "supplies") {
  configureDocumentFilters(tab);
  let config = stockTabConfig[tab] || stockTabConfig.supplies;
  if (tab === "point-transfers" && currentRole === "branch") config = { ...config, title: "Между точками", subtitle: "Запросы, отгрузки и приёмка продуктов между столовыми", action: "Создать перемещение" };
  if (tab === "inventories" && currentRole === "branch") config = { ...config, title: "Инвентаризации", subtitle: "Подсчёт фактических остатков и согласование расхождений", action: inventoryLockForBranch(currentSession.branchId) ? "Продолжить подсчёт" : "Начать инвентаризацию" };
  $("#documentPaneTitle").textContent = config.title;
  $("#stockPageTitle").textContent = config.title;
  $("#documentPaneSubtitle").textContent = config.subtitle;
  $("#documentActionButton").innerHTML = config.action ? `${uiIcon(config.action.includes("инвентаризац") || config.action.includes("подсчёт") ? "checklist" : "plus")}${escapeHtml(config.action)}` : "";
  $("#documentActionButton").dataset.action = tab;
  $("#documentsEmpty strong").textContent = "Документов пока нет";
  $("#documentsEmpty p").textContent = "Создайте первый документ, чтобы движение появилось в учёте.";

  if (tab === "supplies") {
    const branchId = currentSession.branchId || branches[0]?.id;
    const allSupplies = (logisticsState.supplies || []).filter((supply) => currentRole !== "branch" || supply.branchId === branchId);
    const supplies = filterWarehouseDocuments(tab, allSupplies);
    $("#documentActionButton").classList.remove("hidden");
    $("#createFirstRequestButton").classList.add("hidden");
    $("#documentsEmpty strong").textContent = "Поставок пока нет";
    $("#documentsEmpty p").textContent = "Добавьте приходную накладную — продукты сразу поступят на склад заведения.";
    $("#documentsTableHead").innerHTML = "<tr><th>Поставка</th><th>Дата приёмки</th><th>Поставщик</th><th>Склад</th><th>Состав</th><th>Сумма</th><th>Оплата</th><th>Долг</th></tr>";
    $("#documentsTableBody").innerHTML = supplies.map((supply) => {
      const branch = branchById(supply.branchId);
      const itemNames = (supply.items || []).slice(0, 2).map((item) => logisticsItem(item.itemId)?.name).filter(Boolean).join(", ");
      const paymentStatus = supply.paymentStatus || (Number(supply.debt || 0) > 0 ? Number(supply.paidTotal || 0) > 0 ? "partial" : "unpaid" : "paid");
      const statusClass = paymentStatus === "paid" ? "good" : paymentStatus === "partial" ? "warn" : "bad";
      const date = new Date(supply.receivedAt || supply.createdAt);
      return `<tr><td><button type="button" class="document-number" data-view-supply="${escapeHtml(supply.id)}">${escapeHtml(supply.number)}</button><small>${supply.invoiceNumber ? `Накладная ${escapeHtml(supply.invoiceNumber)}` : "Без номера накладной"}</small></td><td>${date.toLocaleDateString("ru-RU")}<small>${date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</small></td><td><strong>${escapeHtml(supply.supplier)}</strong><small>${escapeHtml(supply.receivedBy || supply.createdBy || "—")}</small></td><td>${escapeHtml(branch?.name || "Заведение")}</td><td>${escapeHtml(itemNames || "—")}${(supply.items || []).length > 2 ? `<small>и ещё ${supply.items.length - 2}</small>` : ""}</td><td><strong>${money(supply.total || 0)}</strong></td><td><button type="button" class="status-badge ${statusClass} supply-detail-link" data-view-supply="${escapeHtml(supply.id)}" aria-label="Открыть оплату поставки ${escapeHtml(supply.number)}">${supplyPaymentStatusLabel(paymentStatus)}</button><small>${money(supply.paidTotal || 0)}</small></td><td><button type="button" class="supply-detail-link ${Number(supply.debt || 0) > 0 ? "deficit-value" : "available-value"}" data-view-supply="${escapeHtml(supply.id)}" aria-label="Долг по поставке ${escapeHtml(supply.number)}">${money(supply.debt || 0)}</button></td></tr>`;
    }).join("");
    updateDocumentFilterResult(tab, allSupplies, supplies);
    return;
  }

  if (tab === "inventories") {
    const branchId = currentSession.branchId || branches[0]?.id;
    const allInventories = logisticsState.inventories.filter((inventory) => currentRole !== "branch" || inventory.branchId === branchId);
    const inventories = filterWarehouseDocuments(tab, allInventories);
    $("#documentActionButton").classList.toggle("hidden", !["branch","owner"].includes(currentRole));
    $("#createFirstRequestButton").classList.add("hidden");
    $("#documentsEmpty strong").textContent = "Инвентаризаций пока нет";
    $("#documentsEmpty p").textContent = currentRole === "branch" ? "Начните подсчёт, чтобы сверить учётный и фактический остаток точки." : "После отправки точкой документ появится здесь на проверке.";
    $("#documentsTableHead").innerHTML = "<tr><th>Документ</th><th>Дата</th><th>Точка</th><th>Проверка</th><th>Подсчёт</th><th>Расхождение</th><th>Статус</th><th></th></tr>";
    $("#documentsTableBody").innerHTML = inventories.map((inventory) => {
      const branch = branchById(inventory.branchId);
      const totals = inventoryTotals(inventory);
      const differenceAmount = totals.surplus + totals.shortage;
      const net = totals.net;
      let action = `<button class="operation-action secondary-action" data-open-inventory-document="${inventory.id}" type="button">Подробнее</button>`;
      if (["branch","owner"].includes(currentRole) && ["counting", "returned"].includes(inventory.status)) action = `<button class="operation-action primary primary-action" data-open-inventory-document="${inventory.id}" type="button">Продолжить</button>`;
      else if ((currentRole === "owner" || testMode) && inventory.status === "submitted") action = `<button class="operation-action primary primary-action" data-open-inventory-document="${inventory.id}" type="button">Проверить</button>`;
      const statusDetails = inventory.postedBy ? `Провёл: ${escapeHtml(inventory.postedBy)}` : inventory.returnedBy && inventory.status === "returned" ? `Вернул: ${escapeHtml(inventory.returnedBy)}` : inventory.submittedBy ? `Отправил: ${escapeHtml(inventory.submittedBy)}` : `Создал: ${escapeHtml(inventory.createdBy)}`;
      return `<tr><td><span class="document-number">${escapeHtml(inventory.number)}</span><small>${escapeHtml(inventory.responsible)}</small></td><td>${new Date(inventory.createdAt).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</td><td><strong>${escapeHtml(branch?.name || "Точка")}</strong></td><td><strong>${escapeHtml(inventoryScopeLabel(inventory))}</strong><small>${inventory.items.length} ${pluralRu(inventory.items.length, "позиция", "позиции", "позиций")}</small></td><td><strong>${totals.counted} из ${inventory.items.length}</strong><small>${totals.counted === inventory.items.length ? "все позиции" : "подсчёт не завершён"}</small></td><td><strong class="${differenceAmount ? "deficit-value" : "available-value"}">${money(differenceAmount)}</strong><small>${net > 0 ? "+" : net < 0 ? "−" : ""}${money(Math.abs(net))} итог</small></td><td><span class="operation-status ${inventory.status}">${inventoryStatusLabel(inventory.status)}</span><small>${statusDetails}</small></td><td>${action}</td></tr>`;
    }).join("");
    updateDocumentFilterResult(tab, allInventories, inventories);
    return;
  }

  if (tab === "point-transfers") {
    const branchId = currentSession.branchId || branches[0]?.id;
    const allTransfers = logisticsState.pointTransfers.filter((transfer) => currentRole !== "branch" || transfer.sourceBranchId === branchId || transfer.destinationBranchId === branchId);
    const transfers = filterWarehouseDocuments(tab, allTransfers);
    $("#documentActionButton").classList.toggle("hidden", currentRole !== "branch");
    $("#createFirstRequestButton").classList.add("hidden");
    $("#documentsEmpty strong").textContent = "Перемещений пока нет";
    $("#documentsEmpty p").textContent = branches.length < 2 ? "Для перемещения продуктов нужна как минимум вторая точка." : currentRole === "branch" ? "Создайте запрос, если нужный продукт есть на другой точке." : "После запроса точки перемещение появится здесь.";
    $("#documentsTableHead").innerHTML = "<tr><th>Перемещение</th><th>Нужно к дате</th><th>Маршрут</th><th>Состав</th><th>Количество</th><th>Учётная стоимость</th><th>Статус</th><th></th></tr>";
    $("#documentsTableBody").innerHTML = transfers.map((transfer) => {
      const source = branchById(transfer.sourceBranchId);
      const destination = branchById(transfer.destinationBranchId);
      const itemNames = transfer.items.slice(0, 2).map((item) => logisticsItem(item.itemId)?.name).filter(Boolean).join(", ");
      let action = "";
      if (transfer.status === "submitted" && currentRole === "owner") action = `<button class="operation-action secondary-action" data-approve-point-transfer="${transfer.id}" type="button">Согласовать</button>`;
      else if (transfer.status === "approved" && currentRole === "branch" && branchId === transfer.sourceBranchId) action = `<button class="operation-action primary primary-action" data-dispatch-point-transfer="${transfer.id}" type="button">Отгрузить</button>`;
      else if (transfer.status === "shipped" && currentRole === "branch" && branchId === transfer.destinationBranchId) action = `<button class="operation-action receive primary-action" data-receive-point-transfer="${transfer.id}" type="button">Принять</button>`;
      else if (transfer.status === "received") action = '<span class="operation-status received">Завершено</span>';
      const requested = pointTransferQuantity(transfer, "requested");
      const approved = pointTransferQuantity(transfer, "approved");
      const shipped = pointTransferQuantity(transfer, "shipped");
      const quantity = transfer.status === "submitted" ? requested : transfer.status === "approved" ? approved : shipped;
      const quantityDetails = transfer.status === "approved" && approved + .0001 < requested ? `из ${decimal(requested, 3)} запрошено` : transfer.status === "received" && Number(transfer.variance || 0) ? `расхождение ${Number(transfer.variance) > 0 ? "+" : ""}${decimal(transfer.variance, 3)}` : "";
      const statusDetails = transfer.shippedBy ? `Отгрузил: ${escapeHtml(transfer.shippedBy)}` : transfer.approvedBy ? `Согласовал: ${escapeHtml(transfer.approvedBy)}` : `Запросил: ${escapeHtml(transfer.createdBy)}`;
      return `<tr><td><span class="document-number">${escapeHtml(transfer.number)}</span><small>${new Date(transfer.createdAt).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</small></td><td><strong>${new Date(transfer.neededAt).toLocaleDateString("ru-RU")}</strong></td><td><strong>${escapeHtml(source?.short || "Точка")}</strong><small>→ ${escapeHtml(destination?.short || "Точка")}</small></td><td>${escapeHtml(itemNames)}${transfer.items.length > 2 ? `<small>и ещё ${transfer.items.length - 2}</small>` : ""}</td><td><strong>${decimal(quantity, 3)} ед.</strong>${quantityDetails ? `<small>${escapeHtml(quantityDetails)}</small>` : ""}</td><td><strong>${transfer.totalCost != null ? money(transfer.totalCost) : "—"}</strong></td><td><span class="operation-status ${transfer.status}">${pointTransferStatusLabel(transfer.status)}</span><small>${statusDetails}</small></td><td>${action}</td></tr>`;
    }).join("");
    updateDocumentFilterResult(tab, allTransfers, transfers);
    return;
  }

  if (tab === "direct-orders") {
    const branchId = currentSession.branchId || branches[0]?.id;
    const allOrders = logisticsState.directOrders.filter((order) => currentRole !== "branch" || order.branchId === branchId);
    const orders = filterWarehouseDocuments(tab, allOrders);
    $("#documentActionButton").classList.toggle("hidden", currentRole !== "branch");
    $("#createFirstRequestButton").classList.add("hidden");
    $("#documentsEmpty strong").textContent = "Заказов поставщикам пока нет";
    $("#documentsEmpty p").textContent = currentRole === "branch" ? "Создайте заказ разрешённому поставщику и отправьте его на согласование." : "После отправки точкой заказ появится здесь.";
    $("#documentsTableHead").innerHTML = "<tr><th>Заказ</th><th>Нужен к дате</th><th>Поставщик</th><th>Столовая</th><th>Состав</th><th>Сумма</th><th>Статус</th><th></th></tr>";
    $("#documentsTableBody").innerHTML = orders.map((order) => {
      const branch = branchById(order.branchId);
      const itemNames = order.items.slice(0, 2).map((item) => logisticsItem(item.itemId)?.name).filter(Boolean).join(", ");
      const actions = [];
      if (order.status !== "submitted") actions.push(`<button class="operation-action secondary-action" data-print-direct-order="${order.id}" type="button">PDF</button>`);
      if (order.status === "submitted" && currentRole === "owner") actions.push(`<button class="operation-action secondary-action" data-approve-direct-order="${order.id}" type="button">Согласовать</button>`);
      else if (order.status === "approved" && currentRole === "branch") actions.push(`<button class="operation-action primary primary-action" data-open-direct-send="${order.id}" type="button">Отправить поставщику</button>`);
      const action = actions.length ? `<div class="operation-actions">${actions.join("")}</div>` : "";
      const statusDetails = order.sentVia ? `Отправил: ${escapeHtml(order.orderedBy || "—")} · ${directOrderSendMethodLabel(order.sentVia)}` : order.approvedBy ? `Согласовал: ${escapeHtml(order.approvedBy)}` : "";
      return `<tr><td><span class="document-number">${escapeHtml(order.number)}</span><small>${new Date(order.createdAt).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} · ${escapeHtml(order.createdBy)}</small></td><td><strong>${new Date(order.neededAt).toLocaleDateString("ru-RU")}</strong></td><td><strong>${escapeHtml(order.supplier)}</strong><small>доставка на точку</small></td><td>${escapeHtml(branch?.name || "Точка")}</td><td>${escapeHtml(itemNames)}${order.items.length > 2 ? `<small>и ещё ${order.items.length - 2}</small>` : ""}</td><td><strong>${money(order.total || 0)}</strong></td><td><span class="operation-status ${order.status === "ordered" ? "shipped" : order.status}">${directOrderStatusLabel(order.status)}</span>${statusDetails ? `<small>${statusDetails}</small>` : ""}</td><td>${action}</td></tr>`;
    }).join("");
    updateDocumentFilterResult(tab, allOrders, orders);
    return;
  }

  if (tab === "direct-receipts") {
    const branchId = currentSession.branchId || branches[0]?.id;
    const allReceipts = logisticsState.directOrders.filter((order) => ["ordered", "received"].includes(order.status) && (currentRole !== "branch" || order.branchId === branchId));
    const receipts = filterWarehouseDocuments(tab, allReceipts);
    $("#documentActionButton").classList.add("hidden");
    $("#createFirstRequestButton").classList.add("hidden");
    $("#documentsEmpty strong").textContent = "Поставок пока нет";
    $("#documentsEmpty p").textContent = currentRole === "branch" ? "Сначала отправьте согласованный заказ поставщику." : "Здесь появятся ожидаемые и принятые точками поставки.";
    $("#documentsTableHead").innerHTML = "<tr><th>Заказ / накладная</th><th>Дата</th><th>Поставщик</th><th>Получатель</th><th>Позиций</th><th>Сумма</th><th>Результат</th><th></th></tr>";
    $("#documentsTableBody").innerHTML = receipts.map((order) => {
      const branch = branchById(order.branchId);
      const isReceived = order.status === "received";
      const action = !isReceived && currentRole === "branch" ? `<button class="operation-action receive primary-action" data-receive-direct-order="${order.id}" type="button">Принять поставку</button>` : isReceived ? '<span class="operation-status received">Принято</span>' : '<span class="operation-status shipped">Ожидается</span>';
      return `<tr><td><span class="document-number">${escapeHtml(order.number)}</span><small>${order.invoiceNumber ? `Накладная ${escapeHtml(order.invoiceNumber)}` : "Накладная не указана"}</small></td><td>${new Date(isReceived ? order.receivedAt : order.orderedAt).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</td><td><strong>${escapeHtml(order.supplier)}</strong><small>на точку</small></td><td>${escapeHtml(branch?.name || "Точка")}</td><td><strong>${order.items.length}</strong></td><td><strong>${money(order.total || 0)}</strong></td><td><span class="${isReceived && Number(order.variance) ? "deficit-value" : "available-value"}">${isReceived ? Number(order.variance) ? `${Number(order.variance) > 0 ? "+" : ""}${decimal(order.variance, 3)} ед.` : "без расхождений" : "ожидает приёмки"}</span>${order.receivedBy ? `<small>Принял: ${escapeHtml(order.receivedBy)}</small>` : ""}</td><td>${action}</td></tr>`;
    }).join("");
    updateDocumentFilterResult(tab, allReceipts, receipts);
    return;
  }

  if (tab === "requests") {
    const allRequests = logisticsState.requests;
    const requests = filterWarehouseDocuments(tab, allRequests);
    const canCreateRequest = hasRole("owner", "branch");
    $("#documentActionButton").classList.toggle("hidden", !canCreateRequest || allRequests.length === 0);
    $("#createFirstRequestButton").classList.toggle("hidden", !canCreateRequest || allRequests.length > 0);
    $("#documentsTableHead").innerHTML = "<tr><th>Заявка</th><th>Дата поставки</th><th>Столовая</th><th>Состав</th><th>Запрошено</th><th>Статус</th><th></th></tr>";
    $("#documentsTableBody").innerHTML = requests.map((request) => {
      const branch = branchById(request.branchId);
      const items = request.items.slice(0, 2).map((item) => logisticsItem(item.itemId)?.name).filter(Boolean).join(", ");
      let action = "";
      if (request.status === "submitted" && hasRole("owner", "warehouse")) action = `<button class="operation-action secondary-action" data-approve-request="${request.id}" type="button">Согласовать</button>`;
      else if (request.status === "approved" && hasRole("owner", "warehouse")) action = `<button class="operation-action primary primary-action" data-dispatch-request="${request.id}" type="button">Отгрузить</button>`;
      else if (request.status === "shipped" && hasRole("owner", "branch")) action = `<button class="operation-action receive primary-action" data-receive-request="${request.id}" type="button">Принять</button>`;
      return `<tr><td><span class="document-number">${request.number}</span><small>${new Date(request.createdAt).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} · ${escapeHtml(request.createdBy || "Столовая №1")}</small></td><td><strong>${new Date(request.neededAt).toLocaleDateString("ru-RU")}</strong></td><td><strong>${escapeHtml(branch?.name || "Точка")}</strong><small>${escapeHtml(branch?.route || "")}</small></td><td>${escapeHtml(items)}${request.items.length > 2 ? `<small>и ещё ${request.items.length - 2}</small>` : ""}</td><td><strong>${decimal(requestTotalQuantity(request), 2)} ед.</strong></td><td><span class="operation-status ${request.status}">${requestStatusLabel(request.status)}</span>${request.approvedBy ? `<small>Согласовал: ${escapeHtml(request.approvedBy)}</small>` : ""}</td><td>${action}</td></tr>`;
    }).join("");
    updateDocumentFilterResult(tab, allRequests, requests);
    return;
  }

  $("#documentActionButton").classList.toggle("hidden", !config.action || (currentRole === "branch" && tab === "transfer"));
  $("#createFirstRequestButton").classList.add("hidden");

  if (tab === "transfer") {
    const allTransfers = logisticsState.requests.filter((request) => ["shipped", "received"].includes(request.status));
    const transfers = filterWarehouseDocuments(tab, allTransfers);
    $("#documentsTableHead").innerHTML = "<tr><th>Накладная</th><th>Отгружено</th><th>Получатель</th><th>Позиций</th><th>Количество</th><th>Результат приёмки</th><th></th></tr>";
    $("#documentsTableBody").innerHTML = transfers.map((request) => {
      const branch = branchById(request.branchId);
      const variance = Number(request.variance || 0);
      const action = request.status === "shipped" && hasRole("owner", "branch") ? `<button class="operation-action receive primary-action" data-receive-request="${request.id}" type="button">Принять</button>` : request.status === "received" ? `<span class="operation-status received">Принято</span>` : `<span class="operation-status shipped">В пути</span>`;
      return `<tr><td><span class="document-number">${request.transferNumber || request.number}</span><small>Отгрузил: ${escapeHtml(request.shippedBy || "Архивный маршрут")}</small></td><td>${request.shippedAt ? new Date(request.shippedAt).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"}</td><td><strong>${escapeHtml(branch?.name || "Точка")}</strong></td><td>${request.items.length}</td><td><strong>${decimal(requestTotalQuantity(request, "shipped"), 2)} ед.</strong></td><td><span class="${request.status === "received" && variance ? "deficit-value" : "available-value"}">${request.status === "received" ? variance ? `${variance > 0 ? "+" : ""}${decimal(variance, 3)} ед.` : "без расхождений" : "ожидает приёмки"}</span>${request.receivedBy ? `<small>Принял: ${escapeHtml(request.receivedBy)}</small>` : ""}</td><td>${action}</td></tr>`;
    }).join("");
    updateDocumentFilterResult(tab, allTransfers, transfers);
    return;
  }

  const allDocuments = tab === "movement" ? movementDocuments() : stockDocuments.filter((document) => document.type === tab);
  const documents = filterWarehouseDocuments(tab, allDocuments);
  $("#documentsTableHead").innerHTML = `<tr><th>Документ</th><th>Дата и время</th><th>${tab === "production" ? "Блюдо" : tab === "inventory" ? "Результат" : "Склад / поставщик"}</th><th>${tab === "movement" ? "Тип движения" : "Содержание"}</th><th>Сумма</th><th>Статус</th></tr>`;
  $("#documentsTableBody").innerHTML = documents.map((document) => {
    const date = new Date(document.createdAt);
    const content = document.description || document.reason || document.recipeName || `${document.items?.length || 0} позиций`;
    const source = document.supplier || document.warehouse || "Точка";
    const movementClass = ["supply", "inventory"].includes(document.type) && document.delta >= 0 ? "movement-in" : ["writeoff", "production", "sale"].includes(document.type) ? "movement-out" : "";
    return `<tr><td><span class="document-number">${escapeHtml(document.number)}</span><small>${documentTypeLabel(document.type)}</small></td><td>${date.toLocaleDateString("ru-RU")}<small>${date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</small></td><td>${escapeHtml(source)}</td><td>${escapeHtml(content)}</td><td><strong class="${movementClass}">${["writeoff", "production", "sale"].includes(document.type) ? "−" : ""}${money(document.total || 0)}</strong></td><td><span class="status-badge good">${escapeHtml(document.status)}</span></td></tr>`;
  }).join("");
  updateDocumentFilterResult(tab, allDocuments, documents);
}

function switchStockTab(tab) {
  if (["direct-orders", "direct-receipts", "supply"].includes(tab)) tab = "supplies";
  if (!canAccessStockTab(tab)) tab = "overview";
  document.querySelectorAll("[data-stock-tab]").forEach((button) => button.classList.toggle("active", button.dataset.stockTab === tab));
  document.querySelectorAll("[data-owner-stock-tab]").forEach((button) => button.classList.toggle("active", button.dataset.ownerStockTab === tab));
  const isStockOverview = tab === "overview" || tab === "point-stock";
  const isSuppliers = tab === "suppliers";
  $("#stock-pane-overview").classList.toggle("active", isStockOverview);
  $("#stock-pane-documents").classList.toggle("active", !isStockOverview && !isSuppliers);
  $("#stock-pane-suppliers").classList.toggle("active", isSuppliers);
  const overviewTitle = currentRole === "branch" ? "Остатки точки" : "Остатки сети";
  $("#stockPageTitle").textContent = tab === "overview" ? overviewTitle : (stockTabConfig[tab]?.title || "Снабжение");
  if ($("#view-inventory").classList.contains("active")) $("#breadcrumbTitle").textContent = `Склад / ${tab === "overview" ? "Остатки" : stockTabConfig[tab]?.title || "Документы"}`;
  $("#stockAccessNote").classList.add("hidden");
  $("#inventoryHeadingActions").classList.add("hidden");
  document.querySelectorAll("[data-role-route]").forEach((button) => button.classList.toggle("active", button.dataset.roleRoute === `inventory/${tab}`));
  if ($("#view-inventory").classList.contains("active")) history.replaceState(null, "", tab === "overview" ? "#inventory" : `#inventory/${tab}`);
  if (tab === "overview") renderStock("branch");
  else if (tab === "suppliers") renderSuppliers();
  else renderDocuments(tab);
}

function initializeReportFilters() {
  if (reportFiltersInitialized) return;
  reportFiltersInitialized = true;
  $("#reportBranchFilter").innerHTML = `<option value="all">Вся сеть</option>${branches.map((branch) => `<option value="${escapeHtml(branch.id)}">${escapeHtml(branch.name)}</option>`).join("")}`;
  setReportPeriod("30");
}

function setReportPeriod(preset) {
  if (preset === "custom") {
    $("#reportDateFrom").disabled = false;
    $("#reportDateTo").disabled = false;
    return;
  }
  const sales = getSales();
  const today = new Date();
  let from = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  let to = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  if (preset === "7" || preset === "30") from.setDate(from.getDate() - Number(preset) + 1);
  else if (preset === "month") from = new Date(today.getFullYear(), today.getMonth(), 1);
  else if (preset === "all") {
    const dates = sales.map((sale) => new Date(sale.createdAt)).filter((date) => !Number.isNaN(date.getTime())).sort((left, right) => left - right);
    from = dates[0] ? new Date(dates[0].getFullYear(), dates[0].getMonth(), dates[0].getDate()) : from;
  }
  $("#reportDateFrom").value = analyticsDateValue(from);
  $("#reportDateTo").value = analyticsDateValue(to);
  $("#reportDateFrom").disabled = preset !== "custom";
  $("#reportDateTo").disabled = preset !== "custom";
  if (["7", "today"].includes(preset)) $("#reportGroupBy").value = "day";
  else if (preset === "all") $("#reportGroupBy").value = "month";
  else $("#reportGroupBy").value = "day";
}

function reportContext() {
  initializeReportFilters();
  const from = analyticsInputDate($("#reportDateFrom").value) || new Date(0);
  const to = analyticsInputDate($("#reportDateTo").value, true) || new Date();
  const branchId = $("#reportBranchFilter").value || "all";
  const allSales = filterSalesByRange(getSales(), from, to, branchId);
  const sales = salesPeriodEvents(getSales(), from, to, branchId);
  const duration = Math.max(1, to.getTime() - from.getTime() + 1);
  const previousTo = new Date(from.getTime() - 1);
  const previousFrom = new Date(previousTo.getTime() - duration + 1);
  const previousSales = salesPeriodEvents(getSales(), previousFrom, previousTo, branchId);
  return { from, to, branchId, sales, allSales, previousSales };
}

function formatReportPeriod(from, to) {
  const options = { day: "numeric", month: "short", year: from.getFullYear() === to.getFullYear() ? undefined : "numeric" };
  return `${from.toLocaleDateString("ru-RU", options)} — ${to.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" })}`;
}

function paymentMethodLabel(method) {
  return { cash: "Наличные", card: "Банковская карта", qr: "QR-оплата", mixed: "Смешанная оплата", external: "Внешняя касса" }[method] || "Другой способ";
}

function renderPaymentBreakdown(sales) {
  const labels = { cash: paymentMethodLabel("cash"), card: paymentMethodLabel("card"), qr: paymentMethodLabel("qr"), external: paymentMethodLabel("external") };
  const totals = Object.entries(labels).map(([method, label]) => ({ method, label, value: sales.reduce((sum, sale) => sum + salePaymentAmount(sale,method), 0) }));
  const total = totals.reduce((sum, row) => sum + Math.abs(row.value), 0);
  $("#reportPayments").innerHTML = totals.map((row) => {
    const share = total ? Math.abs(row.value) / total * 100 : 0;
    return `<div class="payment-breakdown-row"><div><span>${row.label}</span><strong>${money(row.value)}</strong></div><div class="payment-progress"><i style="width:${share}%"></i></div><small>${decimal(share)}%</small></div>`;
  }).join("");
}

function renderAnalyticsSales() {
  const context = reportContext();
  const metrics = salesMetrics(context.sales);
  const previous = salesMetrics(context.previousSales);
  $("#reportRevenue").textContent = money(metrics.revenue);
  $("#reportProfit").textContent = money(metrics.profit);
  $("#reportAverage").textContent = money(metrics.average);
  $("#reportReceiptCount").textContent = metrics.receipts;
  $("#reportItemsSold").textContent = metrics.quantities.map((row) => `${decimal(row.quantity, 3)} ${row.unit}`).join(" · ") || "0";
  const delta = percentageDelta(metrics.revenue, previous.revenue);
  $("#reportRevenueDelta").textContent = `${delta > 0 ? "+" : ""}${decimal(delta)}% к прошлому периоду`;
  $("#reportRevenueDelta").className = delta > 0 ? "positive" : delta < 0 ? "negative" : "";
  $("#reportMargin").textContent = `маржа ${decimal(metrics.revenue ? metrics.profit / metrics.revenue * 100 : 0)}%`;
  $("#reportFoodCost").textContent = `фудкост ${decimal(metrics.revenue ? metrics.cost / metrics.revenue * 100 : 0)}%`;
  const oneDay = context.from.toDateString() === context.to.toDateString();
  const today = analyticsDateValue(context.to) === analyticsDateValue(new Date());
  $("#reportSummaryDate").textContent = oneDay
    ? `${today ? "Сегодня, " : ""}${context.to.toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}`
    : formatReportPeriod(context.from, context.to);
  $("#reportChartCaption").textContent = `${formatReportPeriod(context.from, context.to)} · ${context.branchId === "all" ? "вся сеть" : branchById(context.branchId)?.name || "точка"}`;
  const buckets = analyticsBuckets(context.sales, context.from, context.to, $("#reportGroupBy").value);
  const hasData = renderSalesLine($("#reportChartAxis"), $("#reportSalesChart"), buckets);
  $("#reportChartEmpty").classList.toggle("hidden", hasData);
  $("#reportSalesChart").classList.toggle("hidden", !hasData);
  $("#reportChartAxis").classList.toggle("hidden", !hasData);
  renderPaymentBreakdown(context.sales);
  const items = itemAnalyticsRows(context.sales).slice(0, 5);
  $("#reportTopItems").innerHTML = items.length ? items.map((row, index) => `<div><span class="rank">${index + 1}</span><p><strong>${escapeHtml(row.item.name)}</strong><small>${row.item.itemType === "recipe" ? "Блюдо" : "Товар"} · ${decimal(row.quantity, 3)} ${escapeHtml(row.unit)} продано</small></p><b>${money(row.revenue)}</b></div>`).join("") : '<div class="analytics-list-empty">Нет продаж за выбранный период</div>';
}

function assignAbcGroups(rows, key) {
  const sorted = [...rows].sort((left, right) => Math.max(0, right[key]) - Math.max(0, left[key]));
  const total = sorted.reduce((sum, row) => sum + Math.max(0, row[key]), 0);
  let cumulative = 0;
  const groups = new Map();
  sorted.forEach((row) => {
    const value = Math.max(0, row[key]);
    const group = !total || !value ? "C" : cumulative / total < .8 ? "A" : cumulative / total < .95 ? "B" : "C";
    groups.set(row.item.catalogKey, group);
    cumulative += value;
  });
  return groups;
}

function abcRecommendation(row, code) {
  if (!row.quantity) return "Нет продаж — проверить наличие в меню";
  if (code === "AAA") return "Лидер — держать в наличии";
  if (code[0] === "A" && code[2] === "C") return "Высокий спрос — проверить себестоимость";
  if (code[0] === "C" && code[2] === "A") return "Прибыльная ниша — продвигать";
  if (code[1] === "C" && code[2] === "C") return "Пересмотреть цену, состав или ассортимент";
  if (code.includes("C")) return "Проверить показатели позиции";
  return "Стабильная позиция — контролировать";
}

function renderABC() {
  if (!document.querySelector("#abcTable")) return;
  const context = reportContext();
  const search = $("#abcSearch").value.trim().toLowerCase();
  const type = $("#abcTypeFilter").value;
  const selectedCategory = $("#abcCategoryFilter").value;
  const allRows = itemAnalyticsRows(context.sales, true);
  const categories = [...new Set(allRows.map((row) => row.item.category).filter(Boolean))].sort((left, right) => left.localeCompare(right, "ru"));
  const currentCategory = selectedCategory || "all";
  $("#abcCategoryFilter").innerHTML = `<option value="all">Все категории</option>${categories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`).join("")}`;
  $("#abcCategoryFilter").value = categories.includes(currentCategory) ? currentCategory : "all";
  const rows = allRows.filter((row) => (type === "all" || row.item.itemType === type) && ($("#abcCategoryFilter").value === "all" || row.item.category === $("#abcCategoryFilter").value));
  const units = [...new Set(rows.map((row) => row.unit))];
  const quantityGroups = new Map(units.flatMap((unit) => [...assignAbcGroups(rows.filter((row) => row.unit === unit), "quantity")]));
  const revenueGroups = assignAbcGroups(rows, "revenue");
  const profitGroups = assignAbcGroups(rows, "profit");
  const quantitiesByUnit = new Map(units.map((unit) => [unit, rows.filter((row) => row.unit === unit).reduce((sum, row) => sum + row.quantity, 0)]));
  const totalRevenue = rows.reduce((sum, row) => sum + row.revenue, 0);
  const totalProfit = rows.reduce((sum, row) => sum + Math.max(0, row.profit), 0);
  const visible = rows.filter((row) => !search || row.item.name.toLowerCase().includes(search) || String(row.item.category).toLowerCase().includes(search)).sort((left, right) => right.profit - left.profit);
  $("#abcResultCount").textContent = `${visible.length} ${pluralRu(visible.length, "позиция", "позиции", "позиций")}`;
  $("#abcTable").innerHTML = visible.length ? visible.map((row) => {
    const code = `${quantityGroups.get(row.item.catalogKey)}${revenueGroups.get(row.item.catalogKey)}${profitGroups.get(row.item.catalogKey)}`;
    const totalQuantity = quantitiesByUnit.get(row.unit);
    const quantityShare = totalQuantity ? row.quantity / totalQuantity * 100 : 0;
    const revenueShare = totalRevenue ? row.revenue / totalRevenue * 100 : 0;
    const profitShare = totalProfit ? Math.max(0, row.profit) / totalProfit * 100 : 0;
    return `<tr><td><span class="abc-badge abc-code" data-code="${code}">${code}</span></td><td><strong>${escapeHtml(row.item.name)}</strong><small>${row.item.itemType === "recipe" ? "Блюдо" : "Товар"} · ${escapeHtml(row.item.category)}</small></td><td>${decimal(row.quantity, 3)} ${escapeHtml(row.unit)}</td><td title="Доля среди позиций в ${escapeHtml(row.unit)}">${decimal(quantityShare)}%</td><td>${money(row.revenue)}</td><td>${decimal(revenueShare)}%</td><td><strong class="${row.profit < 0 ? "negative" : ""}">${money(row.profit)}</strong></td><td>${decimal(profitShare)}%</td><td><span class="abc-advice">${abcRecommendation(row, code)}</span></td></tr>`;
  }).join("") : '<tr class="table-empty"><td colspan="9">По выбранным условиям позиции не найдены</td></tr>';
}

function visibleReceipts(context = reportContext()) {
  const search = $("#receiptSearch").value.trim().toLowerCase().replace(/^№\s*/, "");
  const paymentMethod = $("#receiptPaymentFilter").value;
  return (context.allSales || context.sales).filter((sale) => {
    if (paymentMethod !== "all" && salePaymentAmount(sale,paymentMethod) <= 0) return false;
    const cashier = $("#receiptCashierFilter").value;
    const status = $("#receiptStatusFilter").value;
    if (cashier !== "all" && (sale.cashier || "Не указан") !== cashier) return false;
    if (status === "paid" && sale.refundedAt || status === "refunded" && !sale.refundedAt) return false;
    if (!search) return true;
    const searchable = [
      sale.number,
      sale.offlineNumber,
      sale.requestId,
      sale.id,
      sale.branch,
      branchById(sale.branchId)?.name,
      sale.cashier,
      paymentMethodLabel(sale.paymentMethod),
      ...(sale.items || []).flatMap((item) => [item.name, item.category])
    ].filter(Boolean).join(" ").toLowerCase();
    return searchable.includes(search);
  }).sort((left, right) => new Date(right.createdAt) - new Date(left.createdAt));
}

let expandedReceiptId = null;
let expandedReceiptTab = "bill";
function receiptConsumption(sale) {
  const ingredientRow = row => {
    const ingredient = ingredients.find(item=>String(item.id)===String(row.itemId));
    return `<tr class="receipt-ingredient-row"><td>— ${escapeHtml(row.name || ingredient?.name || "Удалённый ингредиент")}</td><td>${decimal(Number(row.quantity), 3)} ${escapeHtml(row.unit || ingredient?.unit || "—")}</td><td>${money(Number(row.quantity)*Number(row.unitCost || 0))}</td></tr>`;
  };
  const rows = (sale.items || []).map(item=> {
    const batches = item.batchAllocations || [];
    const raw = item.ingredientAllocations || [];
    const cost = Number.isFinite(Number(item.unitCost)) ? money(Number(item.unitCost)*Number(item.quantity)) : "—";
    let details = raw.map(ingredientRow).join("");
    if (batches.length) details += batches.map(allocation=> {
      const batch = (logisticsState.batches || []).find(row=>String(row.id)===String(allocation.batchId) && row.branchId===sale.branchId);
      let components = allocation.productionIngredients || [];
      if (!components.length && batch && Number(batch.actualWeight)>0 && Number(allocation.weight)>0) {
        const snapshot = batch.ingredientSnapshot?.length ? batch.ingredientSnapshot : (logisticsState.stockLedger || [])
          .filter(row=>row.branchId===sale.branchId && row.documentNumber===batch.number && row.movementType==='production_consumption' && Number(row.quantity)<0)
          .map(row=>({...row,quantity:-Number(row.quantity)}));
        components = snapshot.map(row=>({...row,quantity:Number(row.quantity)*Number(allocation.weight)/Number(batch.actualWeight)}));
      }
      const number = allocation.batchNumber || batch?.number;
      const label = number ? `Партия ${escapeHtml(number)} · ` : '';
      return `<tr class="receipt-consumption-note"><td colspan="3">${label}Списано при производстве${components.length ? '' : ' · детализация ингредиентов не сохранена'}</td></tr>${components.map(ingredientRow).join("")}`;
    }).join("");
    if (!raw.length && !batches.length && item.unit === "порция") details = '<tr class="receipt-consumption-note"><td colspan="3">Состав списания для этого чека не сохранён.</td></tr>';
    return `<tr><td><strong>${escapeHtml(item.name)}</strong></td><td>${decimal(Number(item.quantity),3)} ${escapeHtml(item.unit || "ед.")}</td><td><strong>${cost}</strong></td></tr>${details}`;
  }).join("");
  const knownCosts = (sale.items || []).every(item=>item.unitCost != null && Number.isFinite(Number(item.unitCost)));
  const total = (sale.items || []).reduce((sum,item)=>sum+Number(item.quantity)*Number(item.unitCost || 0),0);
  return `${sale.refundedAt ? '<div class="receipt-inline-total">Чек возвращён. Ниже показано исходное списание.</div>' : ''}<table class="data-table"><thead><tr><th>Товар и ингредиенты</th><th>Количество</th><th>Себестоимость</th></tr></thead><tbody>${rows}</tbody></table><div class="receipt-inline-total"><strong>Итоговая себестоимость</strong><strong>${knownCosts ? money(total) : "Не сохранена"}</strong></div>`;
}
function receiptInlineDetails(sale) {
  const time = value => new Date(value).toLocaleString("ru-RU", {day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"});
  const events = [{at:sale.createdAt, text:"Закрыли чек", actor:sale.cashier, kind:"closed"}];
  if (sale.refundedAt) events.unshift({at:sale.refundedAt,text:"Оформили возврат" + (sale.refundReason ? ": " + sale.refundReason : ""),actor:sale.refundedBy,kind:"refund"});
  const history = `<table class="data-table"><thead><tr><th>Время</th><th>Действие</th><th>Сотрудник</th></tr></thead><tbody>${events.map(event=>`<tr class="receipt-event-${event.kind}"><td>${escapeHtml(time(event.at))}</td><td>${escapeHtml(event.text)}</td><td>${escapeHtml(event.actor || "—")}</td></tr>`).join("")}</tbody></table>`;
  const bill = `<table class="data-table"><thead><tr><th>Наименование</th><th>Количество</th><th>Цена</th><th>Сумма</th></tr></thead><tbody>${(sale.items || []).map(item=>`<tr><td>${escapeHtml(item.name)}</td><td>${decimal(Number(item.quantity),3)} ${escapeHtml(item.unit || "ед.")}</td><td>${money(item.price)}</td><td>${money(saleLineRevenue(item))}</td></tr>`).join("")}</tbody></table><div class="receipt-inline-total"><span>${escapeHtml(salePaymentSummary(sale))}</span><span>Скидка: ${money(sale.discountAmount || 0)}</span><strong>Итого: ${money(sale.total)}</strong></div>`;
  return `<tr class="receipt-expanded"><td colspan="9"><div class="receipt-inline-tabs" role="tablist" aria-label="Детали чека"><button type="button" role="tab" data-receipt-tab="bill" aria-selected="${expandedReceiptTab==='bill'}">Счёт</button><button type="button" role="tab" data-receipt-tab="history" aria-selected="${expandedReceiptTab==='history'}">История</button><button type="button" role="tab" data-receipt-tab="consumption" aria-selected="${expandedReceiptTab==='consumption'}">Списания</button></div><div class="receipt-inline-content">${expandedReceiptTab==='consumption' ? receiptConsumption(sale) : expandedReceiptTab==='history' ? history : bill}</div></td></tr>`;
}
function renderReceipts() {
  if (!document.querySelector("#receiptsTable")) return;
  const context = reportContext();
  const cashierFilter = $("#receiptCashierFilter"), selectedCashier = cashierFilter.value;
  const cashiers = [...new Set(context.allSales.map(sale=>sale.cashier || "Не указан"))].sort((a,b)=>a.localeCompare(b,"ru"));
  cashierFilter.innerHTML = '<option value="all">Все кассиры</option>' + cashiers.map(name=>`<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
  cashierFilter.value = cashiers.includes(selectedCashier) ? selectedCashier : "all";
  const sales = visibleReceipts(context);
  const paidSales = sales.filter(sale=>!sale.refundedAt);
  const metrics = salesMetrics(paidSales);
  ["cash","card","qr"].forEach(method=>$("#receiptSummary"+({cash:"Cash",card:"Card",qr:"Qr"}[method])).textContent=money(paidSales.reduce((sum,sale)=>sum+salePaymentAmount(sale,method),0)));
  $("#receiptSummaryDiscount").textContent=money(paidSales.reduce((sum,sale)=>sum+Number(sale.discountAmount || 0),0));
  const receiptCount = sales.filter((sale) => !isExternalSale(sale)).length;
  const importCount = sales.length - receiptCount;
  $("#receiptSummaryCount").textContent = receiptCount;
  $("#receiptSummaryRevenue").textContent = money(metrics.revenue);
  $("#receiptSummaryAverage").textContent = money(metrics.average);
  $("#receiptSummaryProfit").textContent = money(metrics.profit);
  $("#receiptResultCount").textContent = `${receiptCount} ${pluralRu(receiptCount, "чек", "чека", "чеков")}${importCount ? ` · ${importCount} ${pluralRu(importCount, "реестр", "реестра", "реестров")}` : ""}`;
  $("#receiptsTable").innerHTML = sales.length ? sales.map((sale) => {
    const date = new Date(sale.createdAt);
    const quantity = (sale.items || []).reduce((sum, item) => sum + Number(item.quantity || 0), 0);
    const branchName = sale.branch || branchById(sale.branchId)?.name || "Точка не указана";
    return `<tr class="${String(sale.id)===expandedReceiptId ? "receipt-selected" : ""}"><td><span class="document-number">№ ${escapeHtml(sale.number)}</span></td><td>${date.toLocaleDateString("ru-RU")} ${date.toLocaleTimeString("ru-RU", {hour:"2-digit",minute:"2-digit"})}</td><td>${escapeHtml(branchName)}</td><td>${escapeHtml(sale.cashier || "Не указан")}</td><td>${money(sale.discountAmount || 0)}</td><td>${escapeHtml(salePaymentSummary(sale))}</td><td><strong>${money(sale.total)}</strong><small>${sale.refundedAt ? "—" : money(Number(sale.total)-saleCost(sale))}</small></td><td>${sale.refundedAt ? "Возврат" : "Закрыт"}</td><td><button class="receipt-open-action secondary-action" data-receipt-open="${escapeHtml(sale.id)}" aria-expanded="${String(sale.id)===expandedReceiptId}" type="button">${String(sale.id)===expandedReceiptId ? "Свернуть" : "Детали"}</button></td></tr>${String(sale.id)===expandedReceiptId ? receiptInlineDetails(sale) : ""}`;
  }).join("") : '<tr class="table-empty"><td colspan="9">По выбранным условиям чеки не найдены</td></tr>';
}

function openReceiptDetails(receiptId) {
  const sale = getSales().find((entry) => String(entry.id) === String(receiptId));
  if (!sale) { showToast("Чек не найден"); return; }
  const date = new Date(sale.createdAt);
  const branchName = sale.branch || branchById(sale.branchId)?.name || "Точка не указана";
  const cost = saleCost(sale);
  const profit = Number(sale.total || 0) - cost;
  const received = Number.isFinite(Number(sale.received)) ? Number(sale.received) : Number(sale.total || 0);
  const change = Number.isFinite(Number(sale.change)) ? Number(sale.change) : Math.max(0, received - Number(sale.total || 0));
  $("#receiptModalTitle").textContent = `Чек №${sale.number}`;
  $("#receiptDetailsMeta").innerHTML = `<div><span>Дата и время</span><strong>${date.toLocaleDateString("ru-RU")}</strong><small>${date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</small></div><div><span>Точка</span><strong>${escapeHtml(branchName)}</strong><small>${escapeHtml(sale.branchId || "—")}</small></div><div><span>Кассир</span><strong>${escapeHtml(sale.cashier || "Не указан")}</strong><small>закрыл чек</small></div><div><span>Способ оплаты</span><strong>${escapeHtml(salePaymentSummary(sale))}</strong><small>чек оплачен</small></div>`;
  $("#receiptItemsTable").innerHTML = (sale.items || []).map((item) => {
    const quantity = Number(item.quantity || 0);
    const revenue = saleLineRevenue(item);
    const lineCost = saleUnitCost(sale, item) * quantity;
    return `<tr><td><strong>${escapeHtml(item.name || "Без названия")}</strong><small>${escapeHtml(item.category || "Без категории")}</small></td><td>${decimal(quantity, 3)} ${escapeHtml(item.unit || "ед.")}</td><td>${money(item.price)}</td><td><strong>${money(revenue)}</strong></td><td>${money(lineCost)}</td><td><strong class="${revenue - lineCost < 0 ? "negative" : "positive"}">${money(revenue - lineCost)}</strong></td></tr>`;
  }).join("") || '<tr class="table-empty"><td colspan="6">В чеке нет позиций</td></tr>';
  $("#receiptDetailTotal").textContent = money(sale.total);
  $("#receiptDetailCost").textContent = money(cost);
  $("#receiptDetailProfit").textContent = money(profit);
  $("#receiptDetailPayment").textContent = `${money(received)} / ${money(change)}`;
  $("#receiptModal").classList.remove("hidden");
}

function switchAnalyticsTab(tab) {
  activeAnalyticsTab = ["sales", "receipts", "abc"].includes(tab) ? tab : "sales";
  document.querySelector(".analytics-page-heading h1").textContent = ({sales:"Статистика продаж",receipts:"Чеки",abc:"ABC-анализ"})[activeAnalyticsTab];
  document.querySelectorAll("[data-analytics-tab]").forEach((button) => button.classList.toggle("active", button.dataset.analyticsTab === activeAnalyticsTab));
  document.querySelectorAll("[data-owner-analytics-tab]").forEach((button) => button.classList.toggle("active", button.dataset.ownerAnalyticsTab === activeAnalyticsTab));
  document.querySelectorAll(".analytics-pane").forEach((pane) => pane.classList.toggle("active", pane.id === `analytics-pane-${activeAnalyticsTab}`));
  if (activeAnalyticsTab === "abc") renderABC();
  else if (activeAnalyticsTab === "receipts") renderReceipts();
  else renderAnalyticsSales();
  if ($("#view-reports").classList.contains("active")) history.replaceState(null, "", `#reports/${activeAnalyticsTab}`);
}

function renderReports() {
  initializeReportFilters();
  const selectedBranch = $("#reportBranchFilter").value || "all";
  $("#reportBranchFilter").innerHTML = `<option value="all">Вся сеть</option>${branches.map((branch) => `<option value="${escapeHtml(branch.id)}">${escapeHtml(branch.name)}</option>`).join("")}`;
  $("#reportBranchFilter").value = selectedBranch === "all" || branchById(selectedBranch) ? selectedBranch : "all";
  if (activeAnalyticsTab === "abc") renderABC();
  else if (activeAnalyticsTab === "receipts") renderReceipts();
  else renderAnalyticsSales();
}

function exportAnalyticsCsv() {
  const context = reportContext();
  let header;
  let csvRows;
  let filePrefix = "ashkana-statistics";
  if (activeAnalyticsTab === "receipts") {
    header = ["Чек / реестр", "Дата и время", "Точка", "Кассир", "Оплата", "Позиция", "Количество", "Единица", "Цена", "Сумма", "Себестоимость", "Прибыль"];
    csvRows = visibleReceipts(context).flatMap((sale) => (sale.items || []).map((item) => {
      const quantity = Number(item.quantity || 0);
      const revenue = saleLineRevenue(item);
      const cost = saleUnitCost(sale, item) * quantity;
      return [`${isExternalSale(sale) ? "Реестр " : ""}№ ${sale.number}`, new Date(sale.createdAt).toLocaleString("ru-RU"), sale.branch || branchById(sale.branchId)?.name || "", sale.cashier || "", salePaymentSummary(sale), item.name, quantity, saleLineUnit(item), item.price, revenue, cost, revenue - cost];
    }));
    filePrefix = "ashkana-receipts";
  } else {
    const rows = itemAnalyticsRows(context.sales, true);
    header = ["Тип", "Позиция", "Категория", "Продано", "Единица", "Выручка", "Себестоимость", "Прибыль"];
    csvRows = rows.map((row) => [row.item.itemType === "recipe" ? "Блюдо" : "Товар", row.item.name, row.item.category, row.quantity, row.unit, row.revenue, row.cost, row.profit]);
  }
  const csv = [header, ...csvRows].map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(";")).join("\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" }));
  link.download = `${filePrefix}-${$("#reportDateFrom").value}-${$("#reportDateTo").value}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function financeAccount(id) { return financeState.accounts.find((account) => String(account.id) === String(id)); }
function financeCategory(id) { return financeState.categories.find((category) => String(category.id) === String(id)); }
function financeAccountTypeLabel(type) { return ({ cash: "Наличные", bank: "Банковский счёт", card: "Эквайринг / карта", safe: "Сейф", other: "Другой" })[type] || "Другой"; }
function financeTypeLabel(type) { return ({ sale: "Продажа", income: "Поступление", expense: "Расход", transfer: "Перевод" })[type] || type; }

function financeDate(transaction) {
  const value = transaction.occurredAt || transaction.createdAt;
  const date = new Date(String(value).length === 10 ? `${value}T12:00:00` : value);
  return Number.isNaN(date.getTime()) ? new Date(0) : date;
}

function initializeFinanceFilters() {
  const selectedBranch = $("#financeBranchFilter").value || "all";
  $("#financeBranchFilter").innerHTML = `<option value="all">Вся сеть</option>${branches.map((branch) => `<option value="${escapeHtml(branch.id)}">${escapeHtml(branch.name)}</option>`).join("")}`;
  $("#financeBranchFilter").value = selectedBranch === "all" || branchById(selectedBranch) ? selectedBranch : "all";
  if (financeFiltersInitialized) return;
  financeFiltersInitialized = true;
  setFinancePeriod("30");
}

function setFinancePeriod(preset) {
  if (preset === "custom") {
    $("#financeDateFrom").disabled = false;
    $("#financeDateTo").disabled = false;
    return;
  }
  const today = new Date();
  let from = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const to = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  if (["7", "30"].includes(preset)) from.setDate(from.getDate() - Number(preset) + 1);
  else if (preset === "month") from = new Date(today.getFullYear(), today.getMonth(), 1);
  else if (preset === "all") {
    const dates = [...getSales().map((sale) => new Date(sale.createdAt)), ...financeState.transactions.map(financeDate)].filter((date) => !Number.isNaN(date.getTime())).sort((left, right) => left - right);
    from = dates[0] || from;
  }
  $("#financeDateFrom").value = analyticsDateValue(from);
  $("#financeDateTo").value = analyticsDateValue(to);
  $("#financeDateFrom").disabled = preset !== "custom";
  $("#financeDateTo").disabled = preset !== "custom";
}

function financeContext() {
  initializeFinanceFilters();
  const from = analyticsInputDate($("#financeDateFrom").value) || new Date(0);
  const to = analyticsInputDate($("#financeDateTo").value, true) || new Date();
  const branchId = $("#financeBranchFilter").value || "all";
  const sales = salesPeriodEvents(getSales(), from, to, branchId);
  const transactions = financeState.transactions.filter((transaction) => {
    const date = financeDate(transaction);
    return date >= from && date <= to && (branchId === "all" || String(transaction.branchId) === String(branchId));
  });
  return { from, to, branchId, sales, transactions };
}

function financeSaleAccountId(sale) {
  if (sale.paymentMethod === "cash") return `finance-cash-${sale.branchId}`;
  const accounts = financeState.accounts.filter((account) => account.status === "active" && ["bank", "card"].includes(account.type));
  return accounts.find((account) => String(account.branchId) === String(sale.branchId))?.id
    || accounts.find((account) => !account.branchId)?.id || null;
}

function financeAccountBalance(accountId) {
  const account = financeAccount(accountId);
  if (!account) return 0;
  let balance = Number(account.openingBalance || 0);
  getSales().filter((sale) => !sale.refundedAt && sale.paymentMethod !== "external").forEach((sale) => salePaymentParts(sale).forEach(part => { if (String(financeSaleAccountId({...sale,paymentMethod:part.method})) === String(accountId)) balance += Number(part.amount || 0); }));
  financeState.transactions.forEach((transaction) => {
    const amount = Number(transaction.amount || 0);
    if (transaction.type === "income" && String(transaction.accountId) === String(accountId)) balance += amount;
    if (transaction.type === "expense" && String(transaction.accountId) === String(accountId)) balance -= amount;
    if (transaction.type === "transfer") {
      if (String(transaction.accountId) === String(accountId)) balance -= amount;
      if (String(transaction.destinationAccountId) === String(accountId)) balance += amount;
    }
  });
  return balance;
}

function financeMetrics(context = financeContext()) {
  const revenue = context.sales.reduce((sum, sale) => sum + Number(sale.total || 0), 0);
  const cost = context.sales.reduce((sum, sale) => sum + saleCost(sale), 0);
  const otherIncome = context.transactions.filter((transaction) => transaction.type === "income" && transaction.affectsProfit !== false && transaction.categoryId !== "finance-income-supplier-refunds").reduce((sum, transaction) => sum + Number(transaction.amount || 0), 0);
  const expenses = context.transactions.filter((transaction) => transaction.type === "expense" && transaction.affectsProfit !== false && transaction.categoryId !== "finance-expense-purchases").reduce((sum, transaction) => sum + Number(transaction.amount || 0), 0);
  return { revenue, cost, gross: revenue - cost, otherIncome, expenses, net: revenue - cost + otherIncome - expenses };
}

function renderFinancePnl(context, metrics) {
  const expensesByCategory = new Map();
  context.transactions.filter((transaction) => transaction.type === "expense" && transaction.affectsProfit !== false && transaction.categoryId !== "finance-expense-purchases").forEach((transaction) => expensesByCategory.set(transaction.categoryId, (expensesByCategory.get(transaction.categoryId) || 0) + Number(transaction.amount || 0)));
  const expenseRows = [...expensesByCategory.entries()].sort((left, right) => right[1] - left[1]).map(([categoryId, amount]) => `<div class="pnl-row"><span>${escapeHtml(financeCategory(categoryId)?.name || "Без категории")}</span><strong class="negative">−${money(amount)}</strong></div>`).join("");
  $("#financePnlRows").innerHTML = `<div class="pnl-row main"><span>Выручка по чекам</span><strong>${money(metrics.revenue)}</strong></div><div class="pnl-row"><span>Себестоимость проданных блюд и товаров</span><strong class="${metrics.cost > 0 ? "negative" : metrics.cost < 0 ? "positive" : ""}">${metrics.cost > 0 ? "−" : metrics.cost < 0 ? "+" : ""}${money(Math.abs(metrics.cost))}</strong></div><div class="pnl-row subtotal"><span>Валовая прибыль</span><strong>${money(metrics.gross)}</strong></div>${metrics.otherIncome ? `<div class="pnl-row"><span>Прочие поступления</span><strong class="positive">+${money(metrics.otherIncome)}</strong></div>` : ""}${expenseRows || '<div class="pnl-row"><span>Операционные расходы</span><strong>0 сом</strong></div>'}<div class="pnl-row total"><span>Чистая прибыль</span><strong class="${metrics.net < 0 ? "negative" : ""}">${money(metrics.net)}</strong></div>`;
  $("#financePnlCaption").textContent = `${context.branchId === "all" ? "Вся сеть" : branchById(context.branchId)?.name || "Точка"} · ${formatReportPeriod(context.from, context.to)}`;
  const accounts = financeState.accounts.filter((account) => account.status === "active" && (context.branchId === "all" || !account.branchId || String(account.branchId) === String(context.branchId)));
  $("#financeBalanceList").innerHTML = accounts.length ? accounts.map((account) => `<div class="finance-balance-row"><i>${uiIcon(account.type === "cash" ? "cashier" : "wallet")}</i><div><span>${escapeHtml(account.name)}</span><small>${escapeHtml(financeAccountTypeLabel(account.type))}${account.branchId ? ` · ${escapeHtml(branchById(account.branchId)?.short || "Точка")}` : ""}</small></div><strong class="${financeAccountBalance(account.id) < 0 ? "negative" : ""}">${money(financeAccountBalance(account.id))}</strong></div>`).join("") : '<div class="analytics-list-empty">Активных счетов нет</div>';
}

function financeTransactionRows(context = financeContext()) {
  const sales = context.sales.filter(sale => sale.paymentMethod !== 'external').flatMap(sale => salePaymentParts(sale).map(part => ({
    id: `${sale.id}-${part.method}`, number: `${sale._reportRefund ? "Возврат чека" : "Чек"} №${sale.number}`, type: sale._reportRefund ? "expense" : "sale", occurredAt: sale.createdAt, branchId: sale.branchId,
    accountId: financeSaleAccountId({...sale,paymentMethod:part.method}), categoryName: sale._reportRefund ? "Возврат продажи" : "Выручка", counterparty: (sale._reportRefund ? sale.refundedBy : sale.cashier) || "Касса", comment: paymentMethodLabel(part.method), amount: Math.abs(Number(part.amount || 0)), automatic: true
  })));
  return [...sales, ...context.transactions].sort((left, right) => financeDate(right) - financeDate(left));
}

function renderFinanceTransactions(context) {
  const search = $("#financeTransactionSearch").value.trim().toLowerCase();
  const type = $("#financeTransactionTypeFilter").value;
  const accountId = $("#financeTransactionAccountFilter").value;
  const currentAccount = accountId || "all";
  $("#financeTransactionAccountFilter").innerHTML = `<option value="all">Все счета</option>${financeState.accounts.map((account) => `<option value="${escapeHtml(account.id)}">${escapeHtml(account.name)}</option>`).join("")}`;
  $("#financeTransactionAccountFilter").value = financeAccount(currentAccount) ? currentAccount : "all";
  const rows = financeTransactionRows(context).filter((row) => {
    if (type !== "all" && row.type !== type) return false;
    if ($("#financeTransactionAccountFilter").value !== "all" && ![row.accountId, row.destinationAccountId].map(String).includes($("#financeTransactionAccountFilter").value)) return false;
    const category = row.categoryName || financeCategory(row.categoryId)?.name || "Перевод между счетами";
    return !search || [row.number, row.counterparty, row.comment, category].filter(Boolean).join(" ").toLowerCase().includes(search);
  });
  $("#financeTransactionCount").textContent = `${rows.length} ${pluralRu(rows.length, "операция", "операции", "операций")}`;
  $("#financeTransactionsTable").innerHTML = rows.length ? rows.map((row) => {
    const source = financeAccount(row.accountId);
    const destination = financeAccount(row.destinationAccountId);
    const category = row.categoryName || financeCategory(row.categoryId)?.name || (row.type === "transfer" ? "Перевод между счетами" : "Без категории");
    const date = financeDate(row);
    const sign = row.type === "expense" ? "−" : row.type === "transfer" ? "" : "+";
    const amountClass = row.type === "expense" ? "negative" : row.type === "transfer" ? "" : "positive";
    return `<tr><td><span class="document-number">${escapeHtml(row.number || "Операция")}</span><small><span class="finance-type-badge ${escapeHtml(row.type)}">${escapeHtml(financeTypeLabel(row.type))}</span></small></td><td>${date.toLocaleDateString("ru-RU")}<small>${date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</small></td><td>${escapeHtml(branchById(row.branchId)?.name || "Вся компания")}</td><td>${escapeHtml(category)}</td><td><strong>${escapeHtml(source?.name || "Счёт не найден")}</strong>${destination ? `<small>→ ${escapeHtml(destination.name)}</small>` : ""}</td><td>${escapeHtml(row.counterparty || "—")}<small>${escapeHtml(row.comment || "")}</small></td><td><strong class="${amountClass}">${sign}${money(row.amount)}</strong></td><td>${row.automatic ? '<span title="Создано из чека">Авто</span>' : `<button class="finance-delete-action danger-button" data-delete-finance-transaction="${escapeHtml(row.id)}" type="button">Удалить</button>`}</td></tr>`;
  }).join("") : '<tr class="table-empty"><td colspan="8">По выбранным условиям операций нет</td></tr>';
}

function renderFinanceShifts(context) {
  const shifts = posShifts.filter((shift) => {
    const opened = new Date(shift.openedAt);
    return opened >= context.from && opened <= context.to && (context.branchId === "all" || String(shift.branchId) === String(context.branchId));
  });
  $("#financeShiftsTable").innerHTML = shifts.length ? shifts.map((shift) => {
    const cashSales = getSales().filter((sale) => String(sale.shiftId) === String(shift.id)).reduce((sum, sale) => sum + salePaymentAmount(sale,"cash"), 0);
    const cashRefunds = getSales().filter((sale) => String(sale.refundShiftId) === String(shift.id)).reduce((sum, sale) => sum + salePaymentAmount(sale,"cash"), 0);
    const expected = shift.expectedCash == null ? Number(shift.openingCash || 0) + cashSales - cashRefunds : Number(shift.expectedCash || 0);
    const variance = shift.variance == null ? null : Number(shift.variance || 0);
    const opened = new Date(shift.openedAt);
    return `<tr><td><span class="document-number">№ ${escapeHtml(shift.id)}</span><small>${opened.toLocaleDateString("ru-RU")} ${opened.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</small></td><td><strong>${escapeHtml(shift.registerName || "Касса")}</strong><small>${escapeHtml(branchById(shift.branchId)?.name || "Точка")}</small></td><td>${escapeHtml(shift.openedBy || "—")}</td><td>${money(shift.openingCash)}</td><td>${money(cashSales)}</td><td><strong>${money(expected)}</strong></td><td>${shift.closedAt ? money(shift.closingCash) : "—"}</td><td><strong class="${variance == null || variance === 0 ? "" : variance < 0 ? "negative" : "positive"}">${variance == null ? "—" : `${variance > 0 ? "+" : ""}${money(variance)}`}</strong></td><td><span class="status-badge ${shift.closedAt ? "good" : "pending"}">${shift.closedAt ? "Закрыта" : "Открыта"}</span>${shift.closedBy ? `<small>${escapeHtml(shift.closedBy)}</small>` : ""}</td></tr>`;
  }).join("") : '<tr class="table-empty"><td colspan="9">За выбранный период кассовых смен нет</td></tr>';
}

function renderFinanceAccounts() {
  $("#financeAccountsTable").innerHTML = financeState.accounts.length ? financeState.accounts.map((account) => `<tr><td><strong>${escapeHtml(account.name)}</strong></td><td>${escapeHtml(financeAccountTypeLabel(account.type))}</td><td>${escapeHtml(branchById(account.branchId)?.name || "Вся компания")}</td><td>${money(account.openingBalance)}</td><td><strong class="${financeAccountBalance(account.id) < 0 ? "negative" : ""}">${money(financeAccountBalance(account.id))}</strong></td><td><span class="status-badge ${account.status === "active" ? "good" : "neutral"}">${account.status === "active" ? "Активный" : "Архивный"}</span></td><td><button class="finance-edit-action secondary-action" data-edit-finance-account="${escapeHtml(account.id)}" type="button">Изменить</button></td></tr>`).join("") : '<tr class="table-empty"><td colspan="7">Счетов пока нет</td></tr>';
}

function renderFinanceCategories() {
  ["income", "expense"].forEach((kind) => {
    const target = kind === "income" ? $("#financeIncomeCategories") : $("#financeExpenseCategories");
    const categories = financeState.categories.filter((category) => category.kind === kind);
    target.innerHTML = categories.length ? categories.map((category) => `<div class="finance-category-row"><div><strong>${escapeHtml(category.name)}</strong><small>${category.status === "active" ? "Активная" : "Архивная"}</small></div><button class="finance-edit-action secondary-action" data-edit-finance-category="${escapeHtml(category.id)}" type="button">Изменить</button></div>`).join("") : '<div class="analytics-list-empty">Категорий нет</div>';
  });
}

function renderFinance() {
  if (!document.querySelector("#view-finance")) return;
  financeState = normalizeFinanceState(financeState);
  initializeFinanceFilters();
  const context = financeContext();
  const metrics = financeMetrics(context);
  const activeAccounts = financeState.accounts.filter((account) => account.status === "active" && (context.branchId === "all" || !account.branchId || String(account.branchId) === String(context.branchId)));
  $("#financeNetProfit").textContent = money(metrics.net);
  $("#financeNetProfit").classList.toggle("negative", metrics.net < 0);
  $("#financeRevenue").textContent = money(metrics.revenue);
  const counts = salesMetrics(context.sales);
  $("#financeReceiptsCount").textContent = `${counts.receipts} ${pluralRu(counts.receipts, "чек", "чека", "чеков")}${counts.refunds ? ` · ${counts.refunds} ${pluralRu(counts.refunds, "возврат", "возврата", "возвратов")}` : ""}${counts.imports ? ` · ${counts.imports} ${pluralRu(counts.imports, "реестр", "реестра", "реестров")}` : ""}`;
  $("#financeExpenses").textContent = money(metrics.expenses);
  $("#financeTotalBalance").textContent = money(activeAccounts.reduce((sum, account) => sum + financeAccountBalance(account.id), 0));
  $("#financeAccountsCount").textContent = `${activeAccounts.length} ${pluralRu(activeAccounts.length, "активный счёт", "активных счёта", "активных счетов")}`;
  $("#financeNetCaption").textContent = formatReportPeriod(context.from, context.to);
  renderFinancePnl(context, metrics);
  renderFinanceTransactions(context);
  renderFinanceShifts(context);
  renderFinanceAccounts();
  renderFinanceCategories();
  window.OimoPnl?.refresh();
}

function switchFinanceTab(tab) {
  $("#view-finance").classList.toggle("payroll-view", tab === "payroll" && currentRole === "owner");
  activeFinanceTab = ["pnl", "transactions", "shifts", "accounts", "categories", ...(currentRole === "owner" ? ["payroll"] : [])].includes(tab) ? tab : "pnl";
  document.querySelectorAll("[data-finance-tab]").forEach((button) => button.classList.toggle("active", button.dataset.financeTab === activeFinanceTab));
  document.querySelectorAll("[data-owner-finance-tab]").forEach((button) => button.classList.toggle("active", button.dataset.ownerFinanceTab === activeFinanceTab));
  document.querySelectorAll(".finance-pane").forEach((pane) => pane.classList.toggle("active", pane.id === `finance-pane-${activeFinanceTab}`));
  $("#openFinanceTransactionButton").classList.toggle("hidden", !["pnl", "transactions"].includes(activeFinanceTab));
  const title = { pnl: "Прибыль и убытки", transactions: "Транзакции", shifts: "Кассовые смены", accounts: "Счета", categories: "Категории", payroll: "Зарплата" }[activeFinanceTab];
  if ($("#view-finance").classList.contains("active")) $("#breadcrumbTitle").textContent = `Финансы / ${title}`;
  if ($("#view-finance").classList.contains("active")) history.replaceState(null, "", `#finance/${activeFinanceTab}`);
  if (activeFinanceTab === "payroll") window.OimoPayroll?.open();
  if (activeFinanceTab === "transactions") window.OimoOfflineReview?.open();
  $("#exportFinanceButton").disabled = activeFinanceTab === "pnl" && Boolean(window.OimoPnl?.enabled()) && !window.OimoPnl.ready();
}

function updateFinanceTransactionForm() {
  const type = $("#financeTransactionType").value;
  const activeAccounts = financeState.accounts.filter((account) => account.status === "active");
  const selectedAccount = $("#financeTransactionAccount").value;
  const selectedDestination = $("#financeTransactionDestination").value;
  $("#financeTransactionAccount").innerHTML = activeAccounts.map((account) => `<option value="${escapeHtml(account.id)}">${escapeHtml(account.name)}</option>`).join("");
  $("#financeTransactionDestination").innerHTML = activeAccounts.map((account) => `<option value="${escapeHtml(account.id)}">${escapeHtml(account.name)}</option>`).join("");
  if (financeAccount(selectedAccount)?.status === "active") $("#financeTransactionAccount").value = selectedAccount;
  if (financeAccount(selectedDestination)?.status === "active") $("#financeTransactionDestination").value = selectedDestination;
  $("#financeDestinationAccountField").classList.toggle("hidden", type !== "transfer");
  $("#financeCategoryField").classList.toggle("hidden", type === "transfer");
  $("#financeSourceAccountLabel").textContent = type === "transfer" ? "Счёт списания" : "Счёт";
  if (type !== "transfer") {
    const categories = financeState.categories.filter((category) => category.kind === type && category.status === "active");
    $("#financeTransactionCategory").innerHTML = categories.map((category) => `<option value="${escapeHtml(category.id)}">${escapeHtml(category.name)}</option>`).join("");
  }
}

function syncFinanceTransactionBranch() {
  const account = financeAccount($("#financeTransactionAccount").value);
  if (account?.branchId) $("#financeTransactionBranch").value = account.branchId;
}

function openFinanceTransactionForm() {
  $("#financeTransactionType").value = "expense";
  $("#financeTransactionDate").value = analyticsDateValue(new Date());
  $("#financeTransactionAmount").value = "";
  $("#financeTransactionCounterparty").value = "";
  $("#financeTransactionComment").value = "";
  $("#financeRecognitionDate").value = "";
  $("#financeAffectsProfit").value = "yes";
  $("#financeTransactionBranch").innerHTML = `<option value="">Вся компания</option>${branches.map((branch) => `<option value="${escapeHtml(branch.id)}">${escapeHtml(branch.name)}</option>`).join("")}`;
  $("#financeTransactionBranch").value = $("#financeBranchFilter").value === "all" ? "" : $("#financeBranchFilter").value;
  updateFinanceTransactionForm();
  syncFinanceTransactionBranch();
  if (!financeState.accounts.some((account) => account.status === "active")) { showToast("Сначала создайте активный финансовый счёт"); switchFinanceTab("accounts"); return; }
  $("#financeTransactionModal").classList.remove("hidden");
}

async function saveFinanceTransaction() {
  const type = $("#financeTransactionType").value;
  const payload = { type, occurredAt: $("#financeTransactionDate").value, accountId: $("#financeTransactionAccount").value, destinationAccountId: type === "transfer" ? $("#financeTransactionDestination").value : null, categoryId: type === "transfer" ? null : $("#financeTransactionCategory").value, branchId: $("#financeTransactionBranch").value || null, amount: Number($("#financeTransactionAmount").value), counterparty: $("#financeTransactionCounterparty").value.trim(), comment: $("#financeTransactionComment").value.trim() };
  if (!payload.occurredAt || !payload.accountId || !(payload.amount > 0) || (type !== "transfer" && !payload.categoryId) || (type === "transfer" && (!payload.destinationAccountId || payload.destinationAccountId === payload.accountId))) { showToast("Проверьте дату, счета, категорию и сумму"); return; }
  payload.recognitionDate = $("#financeRecognitionDate").value || null;
  payload.affectsProfit = $("#financeAffectsProfit").value !== "no";
  if (serverMode) {
    const response = await runServerAction("finance.transaction.create", payload);
    if (!response) return;
  } else {
    financeState.transactions.unshift({ id: `finance-transaction-${Date.now()}`, number: `ФО-${String(financeState.transactions.length + 1).padStart(4, "0")}`, ...payload, createdAt: new Date().toISOString(), createdBy: currentSession.name });
    saveFinanceState(); renderAll();
  }
  $("#financeTransactionModal").classList.add("hidden");
  switchFinanceTab("transactions");
  showToast("Финансовая операция проведена");
}

function openFinanceAccountForm(accountId = null) {
  const account = financeAccount(accountId);
  editingFinanceAccountId = account?.id || null;
  $("#financeAccountModalTitle").textContent = account ? "Изменить счёт" : "Новый счёт";
  $("#financeAccountName").value = account?.name || "";
  $("#financeAccountType").value = account?.type || "bank";
  $("#financeAccountBranch").innerHTML = `<option value="">Вся компания</option>${branches.map((branch) => `<option value="${escapeHtml(branch.id)}">${escapeHtml(branch.name)}</option>`).join("")}`;
  $("#financeAccountBranch").value = account?.branchId || "";
  $("#financeAccountOpening").value = Number(account?.openingBalance || 0);
  $("#financeAccountStatus").value = account?.status || "active";
  $("#financeAccountModal").classList.remove("hidden");
}

async function saveFinanceAccount() {
  const payload = { id: editingFinanceAccountId, name: $("#financeAccountName").value.trim(), type: $("#financeAccountType").value, branchId: $("#financeAccountBranch").value || null, openingBalance: Number($("#financeAccountOpening").value || 0), status: $("#financeAccountStatus").value };
  if (!payload.name) { showToast("Укажите название счёта"); return; }
  if (serverMode) {
    const response = await runServerAction("finance.account.upsert", payload);
    if (!response) return;
  } else {
    const account = financeAccount(payload.id) || { id: `finance-account-${Date.now()}` };
    Object.assign(account, payload); if (!financeAccount(account.id)) financeState.accounts.push(account); saveFinanceState(); renderAll();
  }
  $("#financeAccountModal").classList.add("hidden"); showToast("Финансовый счёт сохранён");
}

function openFinanceCategoryForm(kind, categoryId = null) {
  const category = financeCategory(categoryId);
  editingFinanceCategoryId = category?.id || null;
  $("#financeCategoryModalTitle").textContent = category ? "Изменить категорию" : "Новая категория";
  $("#financeCategoryName").value = category?.name || "";
  $("#financeCategoryKind").value = category?.kind || kind;
  $("#financeCategoryStatus").value = category?.status || "active";
  $("#financeCategoryModal").classList.remove("hidden");
}

async function saveFinanceCategory() {
  const payload = { id: editingFinanceCategoryId, name: $("#financeCategoryName").value.trim(), kind: $("#financeCategoryKind").value, status: $("#financeCategoryStatus").value };
  if (!payload.name) { showToast("Укажите название категории"); return; }
  if (serverMode) {
    const response = await runServerAction("finance.category.upsert", payload);
    if (!response) return;
  } else {
    const category = financeCategory(payload.id) || { id: `finance-category-${Date.now()}` };
    Object.assign(category, payload); if (!financeCategory(category.id)) financeState.categories.push(category); saveFinanceState(); renderAll();
  }
  $("#financeCategoryModal").classList.add("hidden"); showToast("Финансовая категория сохранена");
}

async function deleteFinanceTransaction(transactionId) {
  const transaction = financeState.transactions.find((entry) => String(entry.id) === String(transactionId));
  if (!transaction || !window.confirm(`Удалить операцию ${transaction.number}?`)) return;
  if (serverMode) {
    const response = await runServerAction("finance.transaction.delete", { id: transaction.id });
    if (!response) return;
  } else {
    financeState.transactions = financeState.transactions.filter((entry) => entry !== transaction); saveFinanceState(); renderAll();
  }
  showToast("Финансовая операция удалена");
}

function exportFinanceCsv() {
  if (typeof activeFinanceTab !== "undefined" && activeFinanceTab === "pnl" && window.OimoPnl?.enabled()) { window.OimoPnl.exportCsv(); return; }
  const context = financeContext();
  const rows = financeTransactionRows(context);
  const csvRows = [["Номер", "Дата", "Тип", "Точка", "Категория", "Счёт", "Контрагент", "Комментарий", "Сумма"], ...rows.map((row) => [row.number, financeDate(row).toLocaleString("ru-RU"), financeTypeLabel(row.type), branchById(row.branchId)?.name || "Вся компания", row.categoryName || financeCategory(row.categoryId)?.name || "Перевод", financeAccount(row.accountId)?.name || "", row.counterparty || "", row.comment || "", row.type === "expense" ? -Number(row.amount || 0) : Number(row.amount || 0)])];
  const csv = csvRows.map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(";")).join("\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" }));
  link.download = `ashkana-finance-${$("#financeDateFrom").value}-${$("#financeDateTo").value}.csv`;
  link.click(); URL.revokeObjectURL(link.href);
}

function openRecipe(recipeId) {
  const recipe = recipes.find((entry) => entry.id === recipeId);
  if (!recipe) return;
  currentRecipeId = recipeId;
  const cost = recipeCost(recipe);
  $("#drawerRecipeName").textContent = recipe.name;
  renderRecipeImportNotes("#drawerRecipeImportNotes", recipe);
  $("#drawerSalePrice").textContent = money(recipe.price);
  $("#drawerCost").textContent = money(cost);
  $("#drawerFoodCost").textContent = `${decimal(foodCost(recipe))}%`;
  $("#drawerYield").textContent = `${recipe.yield} г`;
  $("#drawerTotalCost").textContent = money(cost);
  $("#compositionTable").innerHTML = recipe.components.map((component) => {
    const ingredient = ingredientById(component.ingredientId);
    const scale = ingredient?.unit === "шт" ? 1000 : 1;
    const measure = ingredient?.unit === "шт" ? "шт" : ingredient?.unit === "л" ? "мл" : "г";
    return `<tr><td><strong>${ingredient?.name || "Не найден"}</strong><small>${money(ingredient?.averageCost || 0)} / ${ingredient?.unit || "ед."}</small></td><td>${decimal(component.gross / scale)} ${measure}</td><td>${decimal(component.net / scale)} ${measure}</td><td><strong>${money(componentCost(component))}</strong></td></tr>`;
  }).join("");
  $("#recipeDrawer").classList.remove("hidden");
}

function renderRecipeImportNotes(selector, recipe) {
  const target = $(selector);
  const notes = Array.isArray(recipe?.importReviewNotes) ? recipe.importReviewNotes : [];
  target.hidden = !notes.length;
  target.innerHTML = notes.length ? `<details class="catalog-form-section"><summary>Временная техкарта · проверить ${notes.length} замечаний</summary><ul>${notes.map((note) => `<li>${escapeHtml(String(note))}</li>`).join("")}</ul></details>` : "";
}

function ingredientOptions(selectedId) {
  return ingredients.map((ingredient) => `<option value="${ingredient.id}" ${ingredient.id === selectedId ? "selected" : ""}>${escapeHtml(ingredient.name)}</option>`).join("");
}

function renderRecipeComponentsEditor() {
  $("#recipeComponentsEditor").innerHTML = `<div class="component-editor-head"><span>Ингредиент</span><span>Брутто</span><span>Нетто</span><span>Стоимость</span><span></span></div>${recipeDraftComponents.map((component, index) => {
    const ingredient = ingredientById(component.ingredientId) || ingredients[0];
    const scale = ingredient?.unit === "шт" ? 1000 : 1;
    const measure = ingredient?.unit === "шт" ? "шт" : ingredient?.unit === "л" ? "мл" : "г";
    const cost = componentCost(component);
    return `<div class="component-editor-row" data-component-index="${index}" data-scale="${scale}"><select class="component-ingredient">${ingredientOptions(component.ingredientId)}</select><input class="component-gross" aria-label="Брутто, ${measure}" title="Брутто, ${measure}" type="number" min="0" step="0.000001" value="${Number(component.gross || 0) / scale}" /><input class="component-net" aria-label="Нетто, ${measure}" title="Нетто, ${measure}" type="number" min="0" step="0.000001" value="${Number(component.net || 0) / scale}" /><span class="component-cost">${money(cost)}<small>${measure}</small></span><button class="remove-component icon-button danger-button" type="button" aria-label="Удалить ингредиент">${uiIcon("close")}</button></div>`;
  }).join("")}`;
  window.mountIngredientPickers($("#recipeComponentsEditor"));
  updateRecipeLiveCalculation();
}

function syncRecipeDraftFromEditor() {
  recipeDraftComponents = [...document.querySelectorAll("#recipeComponentsEditor .component-editor-row")].map((row) => ({
    ingredientId: row.querySelector(".component-ingredient").value,
    gross: Math.max(0, Number(row.querySelector(".component-gross").value || 0)) * Number(row.dataset.scale || 1),
    net: Math.max(0, Number(row.querySelector(".component-net").value || 0)) * Number(row.dataset.scale || 1)
  }));
}

function calculateRecipeYield(components = recipeDraftComponents) {
  const total = (components || []).reduce((sum, component) => sum + Math.max(0, Number(component.net || 0)), 0);
  return Math.round(total * 1000) / 1000;
}

function updateRecipeLiveCalculation() {
  if (document.querySelector("#recipeComponentsEditor .component-editor-row")) syncRecipeDraftFromEditor();
  // Finished output is independent of the ingredient quantities.
  const price = Math.max(0, Number($("#recipePriceInput").value || 0));
  const cost = recipeDraftComponents.reduce((sum, component) => {
    const ingredient = ingredientById(component.ingredientId);
    return sum + (ingredient ? ingredient.averageCost * componentGross(component) / 1000 : 0);
  }, 0);
  $("#recipeLiveCost").textContent = money(cost);
  $("#recipeLiveFoodCost").textContent = `${decimal(price ? cost / price * 100 : 0)}%`;
  $("#recipeLiveMarkup").textContent = `${decimal(cost ? (price - cost) / cost * 100 : 0)}%`;
  document.querySelectorAll("#recipeComponentsEditor .component-editor-row").forEach((row, index) => {
    const component = recipeDraftComponents[index];
    const ingredient = ingredientById(component.ingredientId);
    const measure = ingredient?.unit === "шт" ? "шт" : ingredient?.unit === "л" ? "мл" : "г";
    row.querySelector(".component-cost").innerHTML = `${money(ingredient ? ingredient.averageCost * componentGross(component) / 1000 : 0)}<small>${measure}</small>`;
  });
}

function openRecipeForm(recipeId = null) {
  const recipe = recipes.find((entry) => entry.id === recipeId);
  editingRecipeId = recipe?.id || null;
  renderRecipeImportNotes("#recipeImportNotes", recipe);
  menuCategories = normalizeMenuCategories(menuCategories);
  $("#recipeCategoryInput").innerHTML = menuCategories.map((category) => `<option value="${escapeHtml(category.name)}">${escapeHtml(category.name)}</option>`).join("");
  const stationNames = stationNamesWithLegacy();
  $("#recipeStationInput").innerHTML = stationNames.length
    ? stationNames.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("")
    : '<option value="">Сначала добавьте цех</option>';
  $("#recipeModalTitle").textContent = recipe ? "Редактировать техкарту" : "Новая техкарта";
  $("#recipeNameInput").value = recipe?.name || "";
  CatalogCover.open("recipe", recipe);
  $("#recipeCategoryInput").value = recipe?.category || (menuCategories.some((category) => category.name === "Горячее") ? "Горячее" : menuCategories[0]?.name || "Без категории");
  $("#recipeStationInput").value = recipe ? recipeStation(recipe) : stationNames[0] || "";
  $("#recipePriceInput").value = recipe?.price || 0;
  $("#recipeYieldInput").value = recipe?.yield || 0;
  recipeDraftComponents = recipe ? structuredClone(recipe.components) : [{ ingredientId: ingredients[0]?.id, gross: 100, net: 100 }];
  $("#deleteRecipeButton").classList.toggle("hidden", !recipe);
  renderRecipeComponentsEditor();
  $("#recipeDrawer").classList.add("hidden");
  $("#recipeModal").classList.remove("hidden");
}

async function saveRecipeForm() {
  if (!CatalogCover.ready("recipe")) return;
  syncRecipeDraftFromEditor();
  const name = $("#recipeNameInput").value.trim();
  const price = Math.max(0, Number($("#recipePriceInput").value || 0));
  const recipeYield = Math.max(0, Number($("#recipeYieldInput").value || 0));
  const station = $("#recipeStationInput").value;
  if (!name || !station || !price || !recipeDraftComponents.length || recipeYield <= 0) {
    showToast("Заполните название, цех, цену и состав блюда с ненулевым нетто");
    return;
  }
  const existing = recipes.find((entry) => entry.id === editingRecipeId);
  const updated = {
    id: existing?.id || Math.max(500, ...recipes.map((entry) => Number(entry.id) || 0)) + 1,
    name,
    category: $("#recipeCategoryInput").value,
    station,
    price,
    yield: recipeYield,
    ...CatalogCover.read("recipe"),
    components: recipeDraftComponents
  };
  if (serverMode) {
    const response = await runServerAction("recipe.upsert", updated);
    if (!response) return;
    $("#recipeModal").classList.add("hidden");
    switchMenuPage("recipes");
    showToast(existing ? "Техкарта обновлена, себестоимость пересчитана" : "Новая техкарта создана");
    return;
  }
  if (existing) Object.assign(existing, updated);
  else recipes.push(updated);
  saveRecipes();
  $("#recipeModal").classList.add("hidden");
  renderAll();
  showToast(existing ? "Техкарта обновлена, себестоимость пересчитана" : "Новая техкарта создана");
}

function openPreparationComposition(preparationId) {
  const preparation = preparationById(preparationId);
  if (!preparation) return;
  currentPreparationId = preparation.id;
  const cost = preparationCost(preparation);
  $('#preparationCompositionName').textContent = preparation.name;
  $('#preparationCompositionYield').textContent = `${decimal(Number(preparation.yield || 0) / 1000, 3)} кг`;
  $('#preparationCompositionCost').textContent = money(cost);
  $('#preparationCompositionUnitCost').textContent = money(Number(preparation.yield) > 0 ? cost / (Number(preparation.yield) / 1000) : 0);
  const components = Array.isArray(preparation.components) ? preparation.components : [];
  $('#preparationCompositionTable').innerHTML = components.length ? components.map(component => {
    const ingredient = ingredientById(component.ingredientId);
    const unit = ingredient?.unit || 'кг';
    const scale = unit === 'шт' ? 1000 : 1;
    const measure = unit === 'шт' ? 'шт' : unit === 'л' ? 'мл' : 'г';
    return `<tr><td><strong>${escapeHtml(ingredient?.name || 'Ингредиент удалён')}</strong></td><td data-label="Брутто">${decimal(Number(component.gross || 0) / scale, 3)} ${measure}</td><td data-label="Нетто">${decimal(Number(component.net || 0) / scale, 3)} ${measure}</td><td data-label="Стоимость"><strong>${money(preparationIngredientCost(component))}</strong></td></tr>`;
  }).join('') : '<tr class="table-empty"><td colspan="4">Состав пока не заполнен</td></tr>';
  $('#preparationCompositionProcess').textContent = preparation.process || '';
  $('#preparationCompositionProcessSection').hidden = !preparation.process;
  $('#preparationCompositionDrawer').classList.remove('hidden');
  $('#closePreparationComposition').focus();
}

function closePreparationComposition() {
  $('#preparationCompositionDrawer').classList.add('hidden');
  const trigger = Array.from(document.querySelectorAll('[data-preparation-compose]')).find(button => button.dataset.preparationCompose === String(currentPreparationId));
  trigger?.focus({preventScroll:true});
}

function preparationIngredientCost(component) {
  const ingredient = ingredientById(component.ingredientId);
  if (!ingredient) return 0;
  const branchId = currentSession.branchId || pendingOwnerObjectScope || branches[0]?.id || "";
  const unitCost = branchUnitCost(branchId, ingredient.id) || Number(ingredient.averageCost || 0);
  return unitCost * componentGross(component) / 1000;
}

function renderPreparationComponentsEditor() {
  $("#preparationComponentsEditor").innerHTML = `<div class="component-editor-head"><span>Ингредиент</span><span>Брутто</span><span>Нетто</span><span>Стоимость</span><span></span></div>${preparationDraftComponents.map((component, index) => {
    const unit = ingredientById(component.ingredientId)?.unit || "кг";
    const scale = unit === "шт" ? 1000 : 1;
    const measure = unit === "шт" ? "шт" : unit === "л" ? "мл" : "г";
    return `<div class="component-editor-row preparation-component-row" data-preparation-component-index="${index}" data-scale="${scale}"><select class="preparation-component-ingredient">${ingredientOptions(component.ingredientId)}</select><input class="preparation-component-gross" aria-label="Брутто, ${measure}" title="Брутто, ${measure}" type="number" min="0" step="0.001" value="${Number(component.gross || 0) / scale}" /><input class="preparation-component-net" aria-label="Нетто, ${measure}" title="Нетто, ${measure}" type="number" min="0" step="0.001" value="${Number(component.net || 0) / scale}" /><span class="component-cost">${money(preparationIngredientCost(component))}<small>${measure}</small></span><button class="remove-component icon-button danger-button" data-remove-preparation-component="${index}" type="button" aria-label="Удалить ингредиент">${uiIcon("close")}</button></div>`;
  }).join("")}`;
  window.mountIngredientPickers($("#preparationComponentsEditor"));
  updatePreparationCalculation();
}

function syncPreparationDraftFromEditor() {
  // Stored quantities are thousandths of the ingredient's stock unit, including pieces.
  preparationDraftComponents = [...document.querySelectorAll(".preparation-component-row")].map((row) => ({
    ingredientId: row.querySelector(".preparation-component-ingredient").value,
    gross: Math.max(0, Number(row.querySelector(".preparation-component-gross").value || 0)) * Number(row.dataset.scale || 1),
    net: Math.max(0, Number(row.querySelector(".preparation-component-net").value || 0)) * Number(row.dataset.scale || 1)
  }));
}

function updatePreparationCalculation() {
  if (document.querySelector(".preparation-component-row")) syncPreparationDraftFromEditor();
  const outputWeight = Math.max(0, Number($("#preparationYieldInput").value || 0));
  const totals = {};
  preparationDraftComponents.forEach((component) => {
    const unit = ingredientById(component.ingredientId)?.unit || "кг";
    totals[unit] = (totals[unit] || 0) + Number(component.net || 0) / 1000;
  });
  const batchCost = preparationDraftComponents.reduce((total, component) => total + preparationIngredientCost(component), 0);
  $("#preparationNetWeight").textContent = Object.entries(totals).map(([unit, value]) => `${decimal(value, 3)} ${unit}`).join(" · ") || "0";
  $("#preparationBatchCost").textContent = money(batchCost);
  $("#preparationUnitCost").textContent = money(outputWeight ? batchCost / (outputWeight / 1000) : 0);
  document.querySelectorAll(".preparation-component-row").forEach((row, index) => {
    const unit = ingredientById(preparationDraftComponents[index].ingredientId)?.unit || "кг";
    const measure = unit === "шт" ? "шт" : unit === "л" ? "мл" : "г";
    row.querySelector(".component-cost").innerHTML = `${money(preparationIngredientCost(preparationDraftComponents[index]))}<small>${measure}</small>`;
  });
}

function openPreparationForm(preparationId = null) {
  $('#preparationCompositionDrawer').classList.add('hidden');
  if (!ingredients.length) {
    showToast("Сначала добавьте хотя бы один ингредиент");
    return;
  }
  const preparation = preparationById(preparationId);
  editingPreparationId = preparation?.id || null;
  const categories = [...new Set(["Заготовки кухни", "Холодный цех", "Соусы и заправки", "Выпечка", ...preparations.map((entry) => entry.category).filter(Boolean), "Без категории"] )];
  const stationNames = stationNamesWithLegacy();
  $("#preparationCategoryInput").innerHTML = categories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`).join("");
  $("#preparationStationInput").innerHTML = stationNames.map((station) => `<option value="${escapeHtml(station)}">${escapeHtml(station)}</option>`).join("");
  $("#preparationModalTitle").textContent = preparation ? "Редактировать полуфабрикат" : "Новый полуфабрикат";
  $("#preparationNameInput").value = preparation?.name || "";
  CatalogCover.open("preparation", preparation);
  $("#preparationCategoryInput").value = preparation?.category || "Заготовки кухни";
  $("#preparationStationInput").value = preparation?.station || stationNames[0] || "";
  $("#preparationYieldInput").value = preparation?.yield || 1000;
  $("#preparationProcessInput").value = preparation?.process || "";
  $("#preparationUsedInInput").value = preparation?.usedIn || "";
  preparationDraftComponents = preparation?.components?.length
    ? structuredClone(preparation.components)
    : [{ ingredientId: ingredients[0].id, gross: 1000, net: 1000 }];
  $("#deletePreparationButton").classList.toggle("hidden", !preparation);
  $("#savePreparationButton").textContent = "Сохранить";
  renderPreparationComponentsEditor();
  $("#preparationModal").classList.remove("hidden");
  setTimeout(() => $("#preparationNameInput").focus(), 20);
}

async function savePreparationForm() {
  if (!CatalogCover.ready("preparation")) return;
  syncPreparationDraftFromEditor();
  const name = $("#preparationNameInput").value.trim();
  const station = $("#preparationStationInput").value;
  const outputYield = Math.max(0, Number($("#preparationYieldInput").value || 0));
  if (!name || !station || outputYield <= 0 || !preparationDraftComponents.length) {
    showToast("Заполните название, цех, выход партии и состав");
    return;
  }
  if (preparationDraftComponents.some((component) => component.net <= 0 || component.gross <= 0 || component.net > component.gross)) {
    showToast("Проверьте брутто и нетто: значения должны быть больше нуля, нетто не больше брутто");
    return;
  }
  const ingredientIds = preparationDraftComponents.map((component) => component.ingredientId);
  if (new Set(ingredientIds).size !== ingredientIds.length) {
    showToast("Один ингредиент нельзя добавлять в состав дважды");
    return;
  }
  const existing = preparationById(editingPreparationId);
  const updated = {
    id: existing?.id || `pf-${Date.now().toString(36)}`,
    name,
    category: $("#preparationCategoryInput").value,
    station,
    yield: outputYield,
    process: $("#preparationProcessInput").value.trim(),
    usedIn: $("#preparationUsedInInput").value.trim(),
    ...CatalogCover.read("preparation"),
    components: preparationDraftComponents,
    cost: preparationDraftComponents.reduce((total, component) => total + preparationIngredientCost(component), 0)
  };
  if (serverMode) {
    const response = await runServerAction("preparation.upsert", updated);
    if (!response) return;
    $("#preparationModal").classList.add("hidden");
    switchMenuPage("preparations");
    showToast(existing ? "Полуфабрикат обновлён" : "Полуфабрикат создан и сохранён в техкартах");
    return;
  }
  if (existing) Object.assign(existing, updated);
  else preparations.push(updated);
  savePreparations();
  $("#preparationModal").classList.add("hidden");
  renderPreparations();
  switchMenuPage("preparations");
  showToast(existing ? "Полуфабрикат обновлён" : "Полуфабрикат создан и сохранён в техкартах");
}

function openIngredientForm(ingredientId = null) {
  const ingredient = ingredientById(ingredientId);
  editingIngredientId = ingredient?.id || null;
  populateBranchSelect($("#ingredientWarehouseInput"));
  $("#ingredientWarehouseInput").value = pendingOwnerObjectScope || branches[0]?.id;
  ingredientCategories = normalizeIngredientCategories(ingredientCategories);
  const categories = [...ingredientCategories];
  if (!categories.includes("Без категории")) categories.push("Без категории");
  $("#ingredientCategoryInput").innerHTML = categories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`).join("");
  $("#ingredientModalTitle").textContent = ingredient ? "Редактировать ингредиент" : "Новый ингредиент";
  $("#ingredientNameInput").value = ingredient?.name || "";
  CatalogCover.open("ingredient", ingredient);
  $("#ingredientBarcodeInput").value = ingredient?.barcode || "";
  $("#ingredientCategoryInput").value = ingredient?.category || categories[0];
  $("#ingredientUnitInput").value = ingredient?.unit || "кг";
  $("#ingredientLimitInput").value = ingredient?.limit || 0;
  $("#lossBoilInput").value = ingredient?.losses?.boil || 0;
  $("#lossFryInput").value = ingredient?.losses?.fry || 0;
  $("#lossBakeInput").value = ingredient?.losses?.bake || 0;
  $("#lossCleanInput").value = ingredient?.losses?.clean || 0;
  const ingredientDetails = $("#ingredientModal .catalog-disclosure");
  if (ingredientDetails) ingredientDetails.open = Boolean(ingredient && Object.values(ingredient.losses || {}).some((value) => Number(value) !== 0));
  $("#ingredientStockInput").value = 0;
  $("#ingredientCostInput").value = 0;
  $("#ingredientOpeningBlock").classList.toggle("hidden", Boolean(ingredient) || serverMode);
  $("#editIngredientStockNote").classList.toggle("hidden", !ingredient && !serverMode);
  if (serverMode) $("#editIngredientStockNote p").textContent = "Ингредиент создаётся с нулевым остатком. Фактическое количество появляется только через приёмку поставки или проведённую инвентаризацию точки.";
  $("#deleteIngredientButton").classList.toggle("hidden", !ingredient);
  $("#saveIngredientButton").textContent = "Сохранить";
  updateIngredientOpeningTotal();
  $("#ingredientModal").classList.remove("hidden");
  setTimeout(() => $("#ingredientNameInput").focus(), 20);
}

function updateIngredientOpeningTotal() {
  const stock = Math.max(0, Number($("#ingredientStockInput").value || 0));
  const cost = Math.max(0, Number($("#ingredientCostInput").value || 0));
  $("#ingredientOpeningTotal").textContent = money(stock * cost);
}

function ingredientIdFromName(name) {
  const normalized = name.toLowerCase().replace(/[^a-zа-яё0-9]+/gi, "-").replace(/^-|-$/g, "").slice(0, 24) || "ingredient";
  let id = normalized;
  let suffix = 2;
  while (ingredientById(id)) id = `${normalized}-${suffix++}`;
  return id;
}

async function saveIngredientForm() {
  if (!CatalogCover.ready("ingredient")) return;
  const name = $("#ingredientNameInput").value.trim();
  if (!name) {
    showToast("Введите название ингредиента");
    return;
  }
  const existing = ingredientById(editingIngredientId);
  const details = {
    name,
    category: $("#ingredientCategoryInput").value,
    ...CatalogCover.read("ingredient"),
    barcode: $("#ingredientBarcodeInput").value.trim(),
    unit: $("#ingredientUnitInput").value,
    limit: Math.max(0, Number($("#ingredientLimitInput").value || 0)),
    losses: {
      boil: Math.min(99, Math.max(0, Number($("#lossBoilInput").value || 0))),
      fry: Math.min(99, Math.max(0, Number($("#lossFryInput").value || 0))),
      bake: Math.min(99, Math.max(0, Number($("#lossBakeInput").value || 0))),
      clean: Math.min(99, Math.max(0, Number($("#lossCleanInput").value || 0)))
    }
  };

  if (serverMode) {
    const averageCost = Number(existing?.averageCost || 0);
    const response = await runServerAction("ingredient.upsert", {
      id: existing?.id || ingredientIdFromName(name),
      ...details,
      averageCost
    });
    if (!response) return;
    $("#ingredientModal").classList.add("hidden");
    switchMenuPage("ingredients");
    showToast(existing ? "Ингредиент обновлён" : "Ингредиент создан и доступен в техкартах и заказах");
    return;
  }

  if (existing) {
    Object.assign(existing, details);
  } else {
    const stock = Math.max(0, Number($("#ingredientStockInput").value || 0));
    const averageCost = Math.max(0, Number($("#ingredientCostInput").value || 0));
    const branchId = currentSession.branchId || pendingOwnerObjectScope || branches[0]?.id || "";
    if (stock > 0 && !ensureBranchStockUnlocked(branchId)) return;
    const ingredient = { id: ingredientIdFromName(name), ...details, stock: 0, averageCost };
    ingredients.push(ingredient);
    if (stock > 0) {
      logisticsState.branchStocks[branchId] ||= {};
      logisticsState.branchCosts[branchId] ||= {};
      logisticsState.branchStocks[branchId][ingredient.id] = stock;
      logisticsState.branchCosts[branchId][ingredient.id] = averageCost;
      saveLogisticsState();
    }
  }
  saveIngredients();
  $("#ingredientModal").classList.add("hidden");
  renderAll();
  switchMenuPage("ingredients");
  showToast(existing ? "Ингредиент обновлён" : "Ингредиент создан и доступен в техкартах и заказах");
}

function productById(id) { return products.find((product) => String(product.id) === String(id)); }

let productPhotoDraft = "";

function openProductForm(productId = null) {
  const product = productById(productId);
  editingProductId = product?.id || null;
  populateBranchSelect($("#productWarehouseInput"));
  $("#productWarehouseInput").value = pendingOwnerObjectScope || branches[0]?.id;
  menuCategories = normalizeMenuCategories(menuCategories);
  const categories = menuCategories.map((category) => category.name);
  if (!categories.includes("Без категории")) categories.push("Без категории");
  $("#productCategoryInput").innerHTML = categories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`).join("");
  $("#productModalTitle").textContent = product ? "Редактировать товар" : "Новый товар";
  $("#productNameInput").value = product?.name || "";
  $("#productCategoryInput").value = product?.category || categories[0];
  $("#productCategoryOptions").innerHTML = categories.map(category => `<option value="${escapeHtml(category)}"></option>`).join("");
  $("#productCategorySearch").value = $("#productCategoryInput").value;
  $("#productCategoryHint").textContent = "";
  $("#productBarcodeInput").value = product?.barcode || "";
  $("#productUnitInput").value = product?.unit || "шт";
  productPhotoDraft = product?.image || "";
  $("#productPhotoInput").value = "";
  $("#productColorInput").value = product?.color || "#5b8fbd";
  $("#productMarkupInput").value = product?.markup || 0;
  renderProductCover();
  $("#productCostInput").value = product?.averageCost || 0;
  $("#productPriceInput").value = product?.price || 0;
  $("#productStockInput").value = product?.stock || 0;
  $("#productLimitInput").value = product?.limit || 0;
  $("#productWeightedInput").checked = Boolean(product?.weighted);
  $("#productNoDiscountInput").checked = Boolean(product?.noDiscount);
  $("#productCostInput").disabled = Boolean(product) || serverMode;
  $("#productStockInput").disabled = Boolean(product);
  $("#productWarehouseInput").disabled = Boolean(product);
  $("#productOpeningBlock").classList.toggle("hidden", Boolean(product) || serverMode);
  $("#editProductStockNote").classList.toggle("hidden", !product && !serverMode);
  if (serverMode) $("#editProductStockNote p").textContent = "Товар создаётся с нулевым остатком и без закупочной цены. Они появляются только после приёмки поставки или проведённой инвентаризации точки.";
  $("#deleteProductButton").classList.toggle("hidden", !product);
  $("#saveProductButton").textContent = "Сохранить";
  window.ProductVariants.open(product);
  updateProductCalculation();
  $("#productModal").classList.remove("hidden");
  setTimeout(() => $("#productNameInput").focus(), 20);
}

function updateProductCalculation() {
  const cost = Math.max(0, Number($("#productCostInput").value || 0));
  const price = Math.max(0, Number($("#productPriceInput").value || 0));
  const stock = Math.max(0, Number($("#productStockInput").value || 0));
  if (cost > 0) $("#productMarkupInput").value = Math.round((price - cost) / cost * 10000) / 100;
  $("#productMarkupValue").textContent = cost > 0 ? "Цена = себестоимость + наценка" : "Себестоимость появится после поставки. Пока укажите цену вручную.";
  $("#productOpeningTotal").textContent = money(stock * cost);
}

function productIdFromName(name) {
  const base = `product-${name.toLowerCase().replace(/[^a-zа-яё0-9]+/gi, "-").replace(/^-|-$/g, "").slice(0, 20) || "item"}`;
  let id = base;
  let suffix = 2;
  while (productById(id)) id = `${base}-${suffix++}`;
  return id;
}

async function ensureProductCategory() {
  const name = $("#productCategorySearch").value.trim();
  if (!name || name.length > 80) { showToast("Введите название категории от 1 до 80 символов"); return false; }
  let category = menuCategories.find(item => item.name.toLocaleLowerCase("ru") === name.toLocaleLowerCase("ru"));
  if (!category && name !== "Без категории") {
    if (serverMode) {
      if (!await runServerAction("category.upsert", {kind: "menu", originalName: null, name, color: "#5b8fbd"})) return false;
    } else { menuCategories.push({name, color: "#5b8fbd"}); saveCategoryRegistries(); }
    category = menuCategories.find(item => item.name === name);
  }
  const selected = category?.name || name;
  const select = $("#productCategoryInput");
  if (![...select.options].some(option => option.value === selected)) select.add(new Option(selected, selected));
  select.value = selected;
  $("#productCategorySearch").value = selected;
  $("#productCategoryOptions").innerHTML = menuCategories.map(item => `<option value="${escapeHtml(item.name)}"></option>`).join("");
  $("#productCategoryHint").textContent = `Выбрана категория «${selected}»`;
  return true;
}

async function saveProductForm(createAnother = false) {
  if (await window.ProductVariants.save(createAnother)) return;
  const name = $("#productNameInput").value.trim();
  const price = Math.max(0, Number($("#productPriceInput").value || 0));
  if (!name || !price) {
    showToast("Введите название и цену продажи товара");
    return;
  }
  if (!await ensureProductCategory()) return;
  const existing = productById(editingProductId);
  const details = {
    name,
    category: $("#productCategoryInput").value,
    barcode: $("#productBarcodeInput").value.trim(),
    unit: $("#productUnitInput").value,
    price,
    limit: Math.max(0, Number($("#productLimitInput").value || 0)),
    weighted: $("#productWeightedInput").checked,
    station: $("#productStationInput").value,
    image: productPhotoDraft,
    color: $("#productColorInput").value,
    markup: Number($("#productMarkupInput").value || 0),
    noDiscount: $("#productNoDiscountInput").checked
  };
  if (serverMode) {
    const averageCost = Number(existing?.averageCost || 0);
    const response = await runServerAction("product.upsert", {
      id: existing?.id || productIdFromName(name),
      ...details,
      averageCost
    });
    if (!response) return;
    $("#productModal").classList.add("hidden");
    switchMenuPage("products");
    showToast(existing ? "Товар обновлён" : "Товар создан и добавлен в остатки точки");
    if (createAnother === true) openProductForm();
    return;
  }
  if (existing) {
    Object.assign(existing, details);
  } else {
    const stock = Math.max(0, Number($("#productStockInput").value || 0));
    const averageCost = Math.max(0, Number($("#productCostInput").value || 0));
    const branchId = currentSession.branchId || pendingOwnerObjectScope || branches[0]?.id || "";
    if (stock > 0 && !ensureBranchStockUnlocked(branchId)) return;
    const product = { id: productIdFromName(name), ...details, stock: 0, averageCost };
    products.push(product);
    if (stock > 0) {
      logisticsState.branchStocks[branchId] ||= {};
      logisticsState.branchCosts[branchId] ||= {};
      logisticsState.branchStocks[branchId][product.id] = stock;
      logisticsState.branchCosts[branchId][product.id] = averageCost;
      saveLogisticsState();
    }
  }
  saveProducts();
  $("#productModal").classList.add("hidden");
  renderAll();
  switchMenuPage("products");
  showToast(existing ? "Товар обновлён" : "Товар создан и добавлен в остатки точки");
  if (createAnother === true) openProductForm();
}

const catalogDeleteConfig = {
  recipe: { label: "Технологическая карта", deleted: "Техкарта удалена", modal: "recipeModal", page: "recipes" },
  preparation: { label: "Полуфабрикат", deleted: "Полуфабрикат удалён", modal: "preparationModal", page: "preparations" },
  ingredient: { label: "Ингредиент", deleted: "Ингредиент удалён", modal: "ingredientModal", page: "ingredients" },
  product: { label: "Товар", deleted: "Товар удалён", modal: "productModal", page: "products" },
  "menu-category": { label: "Категория меню", deleted: "Категория удалена", modal: "categoryModal", page: "menu-categories" },
  "ingredient-category": { label: "Категория ингредиентов", deleted: "Категория удалена", modal: "categoryModal", page: "ingredient-categories" },
  station: { label: "Цех", deleted: "Цех удалён", modal: "stationModal", page: "stations" }
};

function logisticsUsesCatalogItem(itemId) {
  const collections = [logisticsState.requests, logisticsState.directOrders, logisticsState.supplies || [], logisticsState.pointTransfers, logisticsState.inventories];
  const usedInDocument = collections.some((collection) => (collection || []).some((document) => (document.items || []).some((row) => String(row.itemId ?? row.ingredientId ?? row.productId ?? row.id) === String(itemId))));
  const usedInLedger = (logisticsState.stockLedger || []).some((row) => String(row.itemId) === String(itemId));
  const usedInLegacyDocument = stockDocuments.some((document) => (document.items || []).some((row) => String(row.itemId ?? row.ingredientId ?? row.productId ?? row.id) === String(itemId)));
  return usedInDocument || usedInLedger || usedInLegacyDocument;
}

function catalogDeleteConstraint(kind, id) {
  const key = String(id);
  if (kind === "product") {
    for (const child of products.filter(item => item.parentId === key)) {
      const reason = catalogDeleteConstraint("product", child.id);
      if (reason) return `${child.name}: ${reason}`;
    }
  }
  if (kind === "recipe") {
    const hasProduction = logisticsState.batches.some((batch) => String(batch.recipeId) === key) || stockDocuments.some((document) => document.type === "production" && String(document.recipeId) === key);
    if (hasProduction) return "По этой техкарте уже есть производство. Историю производства удалять нельзя.";
    if (getSales().some((sale) => (sale.items || []).some((item) => String(item.id) === key))) return "По этой техкарте уже есть продажи. История чеков должна сохраниться.";
  }
  if (["ingredient", "product"].includes(kind)) {
    const stockBranches = branches.filter((branch) => branchStock(branch.id, id) > .000001);
    if (stockBranches.length) return `Сначала обнулите остаток: ${stockBranches.slice(0, 3).map((branch) => branch.name).join(", ")}.`;
    if (logisticsUsesCatalogItem(id)) return "Позиция есть в складских документах. Удаление нарушит историю движения.";
    if (getSales().some((sale) => (sale.items || []).some((item) => String(item.id) === key))) return "По позиции уже есть продажи. История чеков должна сохраниться.";
  }
  if (kind === "menu-category") {
    const count = [...recipes, ...products].filter((item) => item.category === id).length;
    if (count) return `Сначала перенесите ${count} ${pluralRu(count, "позицию", "позиции", "позиций")} в другую категорию.`;
  }
  if (kind === "ingredient-category") {
    const count = ingredients.filter((item) => item.category === id).length;
    if (count) return `Сначала перенесите ${count} ${pluralRu(count, "ингредиент", "ингредиента", "ингредиентов")} в другую категорию.`;
  }
  if (kind === "station") {
    const linkedRecipes = recipes.filter((recipe) => recipeStation(recipe) === id).length;
    const linkedPreparations = preparations.filter((preparation) => preparation.station === id).length;
    if (products.some(product => product.station === id)) return "Сначала назначьте другой цех связанным товарам.";
    if (linkedRecipes || linkedPreparations) return `Сначала назначьте другой цех: ${linkedRecipes} ${pluralRu(linkedRecipes, "техкарта", "техкарты", "техкарт")} и ${linkedPreparations} ${pluralRu(linkedPreparations, "полуфабрикат", "полуфабриката", "полуфабрикатов")}.`;
  }
  return "";
}

function requestCatalogDelete(kind, id, name) {
  const config = catalogDeleteConfig[kind];
  if (!config || id == null) return;
  const reason = catalogDeleteConstraint(kind, id);
  pendingCatalogDelete = { kind, id, name, ...config };
  $("#catalogDeleteTitle").textContent = kind === "ingredient" ? "Удаление ингредиента" : reason ? "Удаление недоступно" : `Удалить «${name}»?`;
  $("#catalogDeleteKind").textContent = config.label;
  $("#catalogDeleteName").textContent = name;
  $("#catalogDeleteDescription").textContent = reason
    ? "Система защищает связанные данные и проведённые документы от повреждения."
    : "Позиция исчезнет из справочника и больше не будет доступна для новых операций. Отменить удаление после подтверждения нельзя.";
  $("#catalogDeleteStatus").classList.toggle("blocked", Boolean(reason));
  $("#catalogDeleteStatus p").textContent = reason || "Связей, остатков и проведённых документов не найдено. Позицию можно удалить.";
  $("#confirmCatalogDeleteButton").disabled = Boolean(reason);
  $("#confirmCatalogDeleteButton").textContent = reason ? "Сначала устраните связи" : "Удалить";
  const links = $("#catalogDeleteLinks");
  links.replaceChildren();
  if (kind === "ingredient") {
    const linked = [...recipes.map(item => ({ item, kind: "recipe" })), ...preparations.map(item => ({ item, kind: "preparation" }))].filter(({item}) => (item.components || []).some(component => String(component.ingredientId) === String(id)));
    $("#catalogDeleteDescription").textContent = linked.length
      ? `Если удалить ингредиент «${name}», изменится состав полуфабрикатов и тех. карт, в которые он входит:`
      : `Ингредиент «${name}» будет удалён из справочника.`;
    linked.forEach(({item, kind: linkedKind}) => {
      const li = document.createElement("li"), link = document.createElement("a");
      link.textContent = item.name;
      link.href = linkedKind === "recipe" ? "#menu/recipes" : "#menu/preparations";
      link.addEventListener("click", event => {
        event.preventDefault();
        $("#catalogDeleteModal").classList.add("hidden");
        if (linkedKind === "recipe") openRecipeForm(item.id); else openPreparationForm(item.id);
      });
      li.append(link); links.append(li);
    });
    $("#catalogDeleteStatus p").textContent = reason || "Уверены, что хотите удалить этот ингредиент?";
  }
  $("#catalogDeleteModal").classList.remove("hidden");
}

function deleteCatalogLocally({ kind, id }) {
  const removeById = (collection) => {
    const index = collection.findIndex((entry) => String(entry.id) === String(id));
    if (index >= 0) collection.splice(index, 1);
  };
  if (kind === "recipe") { removeById(recipes); saveRecipes(); }
  else if (kind === "preparation") { removeById(preparations); savePreparations(); }
  else if (kind === "ingredient") {
    [...recipes, ...preparations].forEach(item => { item.components = (item.components || []).filter(component => String(component.ingredientId) !== String(id)); });
    saveRecipes(); savePreparations(); removeById(ingredients); saveIngredients();
  }
  else if (kind === "product") { products.filter(item => item.parentId === String(id)).forEach(item => deleteCatalogLocally({kind:"product", id:item.id})); removeById(products); saveProducts(); }
  else if (kind === "menu-category") { menuCategories = menuCategories.filter((category) => category.name !== id); saveCategoryRegistries(); }
  else if (kind === "ingredient-category") { ingredientCategories = ingredientCategories.filter((category) => category !== id); saveCategoryRegistries(); }
  else if (kind === "station") { stations = stations.filter((station) => station.name !== id); saveStations(); }
  if (["ingredient", "product"].includes(kind)) {
    Object.values(logisticsState.branchStocks).forEach((stock) => delete stock[id]);
    Object.values(logisticsState.branchCosts).forEach((costs) => delete costs[id]);
    suppliers.forEach((supplier) => Object.values(supplier.prices || {}).forEach((prices) => { if (prices) delete prices[id]; }));
    saveLogisticsState();
    saveSuppliers();
  }
  renderAll();
}

async function confirmCatalogDelete() {
  if (!pendingCatalogDelete) return;
  const reason = catalogDeleteConstraint(pendingCatalogDelete.kind, pendingCatalogDelete.id);
  if (reason) {
    $("#catalogDeleteStatus").classList.add("blocked");
    $("#catalogDeleteStatus p").textContent = reason;
    $("#confirmCatalogDeleteButton").disabled = true;
    return;
  }
  const deletion = { ...pendingCatalogDelete };
  if (serverMode) {
    const response = await runServerAction("catalog.delete", { kind: deletion.kind, id: deletion.id });
    if (!response) return;
  } else deleteCatalogLocally(deletion);
  $("#catalogDeleteModal").classList.add("hidden");
  $(`#${deletion.modal}`).classList.add("hidden");
  pendingCatalogDelete = null;
  switchMenuPage(deletion.page);
  showToast(`${deletion.deleted}: «${deletion.name}»`);
}

function populateSupplySuppliers(selectedId = $("#supplySupplier").value) {
  const activeSuppliers = suppliers.filter((supplier) => supplier.status === "active");
  $("#supplySupplier").innerHTML = activeSuppliers.length
    ? activeSuppliers.map((supplier) => `<option value="${supplier.id}">${escapeHtml(supplier.name)}</option>`).join("")
    : '<option value="">Сначала добавьте поставщика</option>';
  if (activeSuppliers.some((supplier) => String(supplier.id) === String(selectedId))) $("#supplySupplier").value = selectedId;
}

function openSupplierForm(supplierId = null, returnToSupply = false) {
  if (!hasRole("owner", "branch")) return;
  const supplier = supplierById(supplierId);
  editingSupplierId = supplier?.id || null;
  supplierReturnToSupply = returnToSupply;
  $("#supplierModalTitle").textContent = supplier ? "Редактировать поставщика" : "Новый поставщик";
  $("#supplierNameInput").value = supplier?.name || "";
  $("#supplierInnInput").value = supplier?.inn || "";
  $("#supplierContactInput").value = supplier?.contact || "";
  $("#supplierPhoneInput").value = supplier?.phone || "";
  $("#supplierEmailInput").value = supplier?.email || "";
  $("#supplierAddressInput").value = supplier?.address || "";
  $("#supplierStatusInput").value = supplier?.status || "active";
  $("#supplierCommentInput").value = supplier?.comment || "";
  $("#supplierLocationOptions").innerHTML = "";
  $("#supplierLocationHint").textContent = "Поставщик доступен во всём аккаунте";
  $("#saveSupplierButton").textContent = supplier ? "Сохранить изменения" : "Добавить поставщика";
  $("#supplierModal").classList.remove("hidden");
  setTimeout(() => $("#supplierNameInput").focus(), 20);
}

async function saveSupplier() {
  if (!hasRole("owner", "branch")) return;
  const name = $("#supplierNameInput").value.trim();
  if (!name) { showToast("Укажите название поставщика"); return; }
  if (suppliers.some((supplier) => supplier.id !== editingSupplierId && supplier.name.toLowerCase() === name.toLowerCase())) { showToast("Поставщик с таким названием уже существует"); return; }
  const locations = currentRole === "branch" ? [currentSession.branchId] : branches.filter((branch) => branch.status === "active").map((branch) => branch.id);
  const existing = supplierById(editingSupplierId);
  const returnToSupply = supplierReturnToSupply;
  const supplier = {
    id: existing?.id || `supplier-${Date.now()}`,
    name,
    inn: $("#supplierInnInput").value.trim(),
    contact: $("#supplierContactInput").value.trim(),
    phone: $("#supplierPhoneInput").value.trim(),
    email: $("#supplierEmailInput").value.trim(),
    address: $("#supplierAddressInput").value.trim(),
    status: $("#supplierStatusInput").value,
    comment: $("#supplierCommentInput").value.trim(),
    locations,
    prices: existing?.prices || {}
  };
  if (serverMode) {
    const response = await runServerAction("supplier.upsert", supplier);
    if (!response) return;
    $("#supplierModal").classList.add("hidden");
    if (returnToSupply) {
      populateSupplySuppliers(response.entity?.id);
      supplierReturnToSupply = false;
      $("#supplyModal").classList.remove("hidden");
      showToast(existing ? "Карточка поставщика обновлена" : "Поставщик добавлен в поставку");
      return;
    }
    switchView("inventory");
    switchStockTab("suppliers");
    showToast(existing ? "Карточка поставщика обновлена" : "Поставщик добавлен");
    return;
  }
  if (existing) Object.assign(existing, supplier);
  else suppliers.unshift(supplier);
  saveSuppliers();
  $("#supplierModal").classList.add("hidden");
  if (returnToSupply) {
    populateSupplySuppliers(supplier.id);
    supplierReturnToSupply = false;
    $("#supplyModal").classList.remove("hidden");
    showToast(existing ? "Карточка поставщика обновлена" : "Поставщик добавлен в поставку");
    return;
  }
  renderSuppliers();
  switchView("inventory");
  switchStockTab("suppliers");
  showToast(existing ? "Карточка поставщика обновлена" : "Поставщик добавлен");
}

function populateSupplyIngredients() {
  populateBranchSelect($("#supplyWarehouse"));
  const branchId = currentRole === "branch" ? currentSession.branchId : $("#supplyWarehouse").value || branches[0]?.id;
  if (branchId) $("#supplyWarehouse").value = branchId;
  $("#supplyWarehouse").disabled = currentRole === "branch" || branches.length < 2;
  populateSupplySuppliers();
  const firstEntity = [...ingredients, ...products][0];
  supplyDraftItems = firstEntity ? [{ itemId: firstEntity.id, quantity: 1, price: branchUnitCost(branchId, firstEntity.id) }] : [];
  supplyDraftPayments = [];
  const now = new Date();
  const localNow = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  $("#supplyReceivedAt").value = localNow;
  $("#supplyInvoiceNumber").value = "";
  $("#supplyComment").value = "";
  renderSupplyItemsEditor();
  renderSupplyPayments();
  updateSupplyCalculation();
}

function supplyEntityOptions(selectedId) {
  return `<optgroup label="Ингредиенты">${ingredients.map((ingredient) => `<option value="${ingredient.id}" ${String(ingredient.id) === String(selectedId) ? "selected" : ""}>${escapeHtml(ingredient.name)}</option>`).join("")}</optgroup><optgroup label="Готовые товары">${products.map((product) => `<option value="${product.id}" ${String(product.id) === String(selectedId) ? "selected" : ""}>${escapeHtml(product.name)}</option>`).join("")}</optgroup>`;
}

function syncSupplyDraft() {
  supplyDraftItems = [...document.querySelectorAll(".supply-item-row")].map((row) => ({
    itemId: row.querySelector(".supply-item-product").value,
    quantity: Math.max(0, Number(row.querySelector(".supply-item-quantity").value || 0)),
    price: Math.max(0, Number(row.querySelector(".supply-item-price").value || 0))
  }));
}

function renderSupplyItemsEditor() {
  const branchId = $("#supplyWarehouse").value || currentSession.branchId || branches[0]?.id;
  $("#supplyItemsEditor").innerHTML = supplyDraftItems.map((item, index) => {
    const entity = stockEntityById(item.itemId) || ingredients[0] || products[0];
    if (!entity) return "";
    const quantity = Math.max(0, Number(item.quantity || 0));
    const currentCost = branchUnitCost(branchId, entity.id);
    const price = Math.max(0, Number(item.price ?? currentCost));
    const oldQuantity = branchStock(branchId, entity.id);
    const nextAverage = oldQuantity + quantity ? (oldQuantity * currentCost + quantity * price) / (oldQuantity + quantity) : price;
    return `<div class="supply-item-row" data-supply-item-index="${index}"><div class="supply-item-product-cell"><select class="supply-item-product">${supplyEntityOptions(entity.id)}</select><small class="supply-item-cost-preview">Учётная цена: ${money(currentCost)} → ${money(nextAverage)} / ${entity.unit}</small></div><span class="supply-item-unit">${entity.unit}</span><input class="supply-item-quantity" type="number" min="0.001" step="0.001" value="${quantity}" aria-label="Количество" /><input class="supply-item-price" type="number" min="0.01" step="0.01" value="${price}" aria-label="Цена за единицу" /><strong class="supply-item-total">${money(quantity * price)}</strong><button class="supply-remove-item icon-button danger-button" data-remove-supply-item="${index}" type="button" title="Удалить позицию">${uiIcon("close")}</button></div>`;
  }).join("");
}

function supplyMoney(value) {
  const [coefficient, exponent = '0'] = String(Math.abs(Number(value))).split('e');
  return Math.sign(Number(value)) * Math.round(Number(`${coefficient}e${Number(exponent) + 2}`)) / 100;
}

function supplyDocumentAmount() {
  return supplyMoney([...document.querySelectorAll(".supply-item-row")].reduce((total, row) => total + Math.max(0, Number(row.querySelector(".supply-item-quantity").value || 0)) * Math.max(0, Number(row.querySelector(".supply-item-price").value || 0)), 0));
}

function supplyPaymentAccounts() {
  const branchId = $("#supplyWarehouse").value || currentSession.branchId;
  return (financeState.accounts || []).filter((account) => account.status === "active" && account.type !== 'cash' && (!account.branchId || String(account.branchId) === String(branchId)));
}

function syncSupplyPayments() {
  supplyDraftPayments = [...document.querySelectorAll(".supply-payment-row")].map((row) => ({
    accountId: row.querySelector(".supply-payment-account").value,
    occurredAt: row.querySelector(".supply-payment-date").value,
    amount: Math.max(0, supplyMoney(row.querySelector(".supply-payment-amount").value || 0))
  }));
}

function renderSupplyPayments() {
  const accounts = supplyPaymentAccounts();
  $("#supplyPaymentEditor").innerHTML = supplyDraftPayments.length ? supplyDraftPayments.map((payment, index) => `<div class="supply-payment-row" data-supply-payment-index="${index}"><select class="supply-payment-account" aria-label="Финансовый счёт">${accounts.map((account) => `<option value="${escapeHtml(account.id)}" ${String(account.id) === String(payment.accountId) ? "selected" : ""}>${escapeHtml(account.name)}</option>`).join("")}</select><input class="supply-payment-date" type="datetime-local" value="${escapeHtml(payment.occurredAt || $("#supplyReceivedAt").value)}" aria-label="Дата оплаты" /><input class="supply-payment-amount" type="number" min="0.01" step="0.01" value="${Number(payment.amount || 0)}" aria-label="Сумма оплаты" /><button class="supply-remove-item icon-button danger-button" data-remove-supply-payment="${index}" type="button" title="Удалить платёж">${uiIcon("close")}</button></div>`).join("") : "";
  $(".supply-payment-section").classList.toggle("has-payments", supplyDraftPayments.length > 0);
  updateSupplyPaymentCalculation();
}

function updateSupplyPaymentCalculation() {
  const paid = supplyMoney([...document.querySelectorAll(".supply-payment-amount")].reduce((sum, input) => sum + Math.max(0, supplyMoney(input.value || 0)), 0));
  const total = supplyDocumentAmount();
  $("#supplyPaidTotal").textContent = money(paid);
  const debt = Math.max(0, supplyMoney(total - paid));
  $("#supplyDebtTotal").textContent = money(debt);
  $("#supplyDebtFooter").textContent = money(debt);
}

function updateSupplyCalculation() {
  const branchId = $("#supplyWarehouse").value || currentSession.branchId || branches[0]?.id;
  let total = 0;
  document.querySelectorAll(".supply-item-row").forEach((row) => {
    const entity = stockEntityById(row.querySelector(".supply-item-product").value);
    if (!entity) return;
    const quantity = Math.max(0, Number(row.querySelector(".supply-item-quantity").value || 0));
    const price = Math.max(0, Number(row.querySelector(".supply-item-price").value || 0));
    const lineTotal = quantity * price;
    const oldQuantity = branchStock(branchId, entity.id);
    const currentCost = branchUnitCost(branchId, entity.id);
    const nextAverage = oldQuantity + quantity ? (oldQuantity * currentCost + lineTotal) / (oldQuantity + quantity) : price;
    row.querySelector(".supply-item-unit").textContent = entity.unit;
    row.querySelector(".supply-item-total").textContent = money(lineTotal);
    row.querySelector(".supply-item-cost-preview").textContent = `Учётная цена: ${money(currentCost)} → ${money(nextAverage)} / ${entity.unit}`;
    total += lineTotal;
  });
  $("#supplyPositionsCount").textContent = document.querySelectorAll(".supply-item-row").length;
  $("#supplyDocumentTotal").textContent = money(supplyMoney(total));
  updateSupplyPaymentCalculation();
}

function parseSupplyCsvLine(line, delimiter) {
  const cells = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"' && quoted && line[index + 1] === '"') { value += '"'; index += 1; }
    else if (character === '"') quoted = !quoted;
    else if (character === delimiter && !quoted) { cells.push(value.trim()); value = ""; }
    else value += character;
  }
  cells.push(value.trim());
  return cells;
}

function supplyCsvNumber(value) {
  const normalized = String(value || "").replace(/\s/g, "").replace(",", ".").replace(/[^0-9.-]/g, "");
  return Number(normalized);
}

async function importSupplyCsv(file) {
  if (!file) return;
  if (!String(file.name || "").toLowerCase().endsWith(".csv")) { showToast("Для импорта выберите файл CSV"); return; }
  const text = (await file.text()).replace(/^\uFEFF/, "");
  const lines = text.split(/\r?\n/).filter((line) => line.trim());
  if (!lines.length) { showToast("Файл CSV пуст"); return; }
  const delimiter = [";", "\t", ","].sort((left, right) => (lines[0].split(right).length - lines[0].split(left).length))[0];
  const rows = lines.map((line) => parseSupplyCsvLine(line, delimiter));
  const header = rows[0].map((cell) => cell.toLowerCase());
  const nameIndex = header.findIndex((cell) => /наимен|товар|продукт|ингредиент|name/.test(cell));
  const quantityIndex = header.findIndex((cell) => /колич|quantity|qty/.test(cell));
  const priceIndex = header.findIndex((cell) => /цен|price|стоим/.test(cell));
  const hasHeader = nameIndex >= 0 && quantityIndex >= 0 && priceIndex >= 0;
  const indexes = hasHeader ? [nameIndex, quantityIndex, priceIndex] : [0, 1, 2];
  const catalog = [...ingredients, ...products];
  const imported = [];
  const missed = [];
  rows.slice(hasHeader ? 1 : 0).forEach((row) => {
    const rawName = String(row[indexes[0]] || "").trim();
    const normalizedName = rawName.toLocaleLowerCase("ru-RU");
    const entity = catalog.find((item) => item.name.trim().toLocaleLowerCase("ru-RU") === normalizedName);
    const quantity = supplyCsvNumber(row[indexes[1]]);
    const price = supplyCsvNumber(row[indexes[2]]);
    if (!entity || !(quantity > 0) || !(price > 0)) { if (rawName) missed.push(rawName); return; }
    const existing = imported.find((item) => String(item.itemId) === String(entity.id));
    if (existing) {
      const totalQuantity = existing.quantity + quantity;
      existing.price = (existing.quantity * existing.price + quantity * price) / totalQuantity;
      existing.quantity = totalQuantity;
    } else imported.push({ itemId: entity.id, quantity, price });
  });
  if (!imported.length) { showToast("Не удалось сопоставить строки с товарами и ингредиентами"); return; }
  supplyDraftItems = imported;
  renderSupplyItemsEditor();
  updateSupplyCalculation();
  showToast(missed.length ? `Импортировано ${imported.length}; не распознано ${missed.length}` : `Импортировано позиций: ${imported.length}`);
}

function printSupplyDraft() {
  document.body.classList.add("print-supply");
  window.print();
  setTimeout(() => document.body.classList.remove("print-supply"), 100);
}

async function saveSupply() {
  if ($("#saveSupplyButton").disabled) return;
  if (!hasRole("owner", "branch")) return;
  syncSupplyDraft();
  syncSupplyPayments();
  const items = supplyDraftItems.filter((item) => stockEntityById(item.itemId) && item.quantity > 0 && item.price > 0);
  if (!items.length || items.length !== supplyDraftItems.length) { showToast("Заполните количество и цену у каждой позиции"); return; }
  if (new Set(items.map((item) => item.itemId)).size !== items.length) { showToast("Одна позиция добавлена дважды — объедините количество в одной строке"); return; }
  const supplier = supplierById($("#supplySupplier").value);
  if (!supplier || supplier.status !== "active") { showToast("Выберите активного поставщика"); return; }
  const branchId = $("#supplyWarehouse").value || currentSession.branchId;
  if (!branchId || !ensureBranchStockUnlocked(branchId)) return;
  const invoiceNumber = $("#supplyInvoiceNumber").value.trim();
  const receivedAt = new Date($("#supplyReceivedAt").value);
  if (Number.isNaN(receivedAt.getTime())) { showToast("Укажите дату и время приёмки"); return; }
  const total = supplyMoney(items.reduce((sum, item) => sum + item.quantity * item.price, 0));
  const payments = supplyDraftPayments.filter((payment) => payment.amount > 0);
  if (payments.some((payment) => !supplyPaymentAccounts().some((account) => String(account.id) === String(payment.accountId)) || !payment.occurredAt)) { showToast("Проверьте счёт и дату каждого платежа"); return; }
  const paidTotal = supplyMoney(payments.reduce((sum, payment) => sum + payment.amount, 0));
  if (paidTotal > total) { showToast("Сумма оплаты не может быть больше суммы поставки"); return; }
  const payload = { branchId, supplierId: supplier.id, invoiceNumber, receivedAt: receivedAt.toISOString(), comment: $("#supplyComment").value.trim(), items, payments };
  if (serverMode) {
    $("#saveSupplyButton").disabled = true;
    let response;
    try { response = await runServerAction("supply.create", payload); }
    finally { $("#saveSupplyButton").disabled = false; }
    if (!response) return;
  } else {
    logisticsState.branchStocks[branchId] ||= {};
    logisticsState.branchCosts[branchId] ||= {};
    items.forEach((item) => {
      const oldQuantity = branchStock(branchId, item.itemId);
      const oldCost = branchUnitCost(branchId, item.itemId);
      logisticsState.branchStocks[branchId][item.itemId] = oldQuantity + item.quantity;
      logisticsState.branchCosts[branchId][item.itemId] = (oldQuantity * oldCost + item.quantity * item.price) / (oldQuantity + item.quantity);
      supplier.prices ||= {};
      supplier.prices[branchId] ||= {};
      supplier.prices[branchId][item.itemId] = item.price;
    });
    const debt = Math.max(0, supplyMoney(total - paidTotal));
    const supply = { id: `supply-${Date.now()}`, number: nextDocumentNumber("ПСТ", logisticsState.supplies), documentType: "supply", branchId, supplierId: supplier.id, supplier: supplier.name, invoiceNumber, receivedAt: receivedAt.toISOString(), createdAt: new Date().toISOString(), createdBy: currentSession.name, receivedBy: currentSession.name, comment: payload.comment, items, total, paidTotal, debt, payments, paymentStatus: debt <= .0001 ? "paid" : paidTotal > 0 ? "partial" : "unpaid", status: "received" };
    logisticsState.supplies.unshift(supply);
    let category = financeState.categories.find((entry) => entry.id === "finance-expense-purchases");
    if (!category) { category = { id: "finance-expense-purchases", name: "Поставки", kind: "expense", status: "active" }; financeState.categories.push(category); }
    payments.forEach((payment) => financeState.transactions.unshift({ id: `finance-transaction-${Date.now()}-${Math.random()}`, number: nextDocumentNumber("ФО", financeState.transactions), type: "expense", amount: payment.amount, occurredAt: payment.occurredAt, accountId: payment.accountId, categoryId: category.id, branchId, counterparty: supplier.name, comment: `Поставка ${supply.number}`, documentId: supply.id, automatic: true, createdAt: new Date().toISOString(), createdBy: currentSession.name }));
    saveLogisticsState();
    saveSuppliers();
    saveFinanceState();
    renderAll();
  }
  supplyDraftItems = [];
  supplyDraftPayments = [];
  $("#supplyModal").classList.add("hidden");
  switchView("inventory");
  switchStockTab("supplies");
  showToast(`Поставка проведена: ${items.length} позиций на ${money(total)}`);
}

function populateWriteoffForm() {
  $("#writeoffIngredient").innerHTML = `<optgroup label="Ингредиенты">${ingredients.map((ingredient) => `<option value="${ingredient.id}">${ingredient.name} · ${decimal(availableStock(ingredient), 3)} ${ingredient.unit}</option>`).join("")}</optgroup><optgroup label="Готовые товары">${products.map((product) => `<option value="${product.id}">${product.name} · ${decimal(availableProductStock(product), 3)} ${product.unit}</option>`).join("")}</optgroup>`;
  updateWriteoffCalculation();
}

function updateWriteoffCalculation() {
  const ingredient = stockEntityById($("#writeoffIngredient").value) || ingredients[0] || products[0];
  const quantity = Math.max(0, Number($("#writeoffQuantity").value || 0));
  if (!ingredient) return;
  $("#writeoffUnit").textContent = ingredient.unit;
  $("#writeoffCost").textContent = money(quantity * ingredient.averageCost);
}

function saveWriteoff() {
  if (!hasRole("owner", "warehouse")) return;
  const ingredient = stockEntityById($("#writeoffIngredient").value);
  const quantity = Math.max(0, Number($("#writeoffQuantity").value || 0));
  if (!ingredient || !quantity) return;
  if (quantity > availableEntityStock(ingredient)) {
    showToast(`Недостаточно остатка: доступно ${decimal(availableEntityStock(ingredient), 3)} ${ingredient.unit}`);
    return;
  }
  const total = quantity * ingredient.averageCost;
  ingredient.stock -= quantity;
  if (isProductEntity(ingredient)) saveProducts();
  else saveIngredients();
  addDocument("writeoff", {
    warehouse: "Склад точки Манаса",
    reason: $("#writeoffReason").value,
    description: `${ingredient.name} · ${decimal(quantity, 3)} ${ingredient.unit}`,
    total,
    items: [{ itemId: ingredient.id, itemType: isProductEntity(ingredient) ? "product" : "ingredient", quantity, price: ingredient.averageCost }]
  });
  $("#writeoffModal").classList.add("hidden");
  renderAll();
  switchStockTab("writeoff");
  showToast("Списание проведено и отражено в движении склада");
}

function populateProductionForm() {
  $("#productionRecipe").innerHTML = recipes.map((recipe) => `<option value="${recipe.id}">${recipe.name}</option>`).join("");
  updateProductionPreview();
}

function updateProductionPreview() {
  const recipe = recipes.find((entry) => entry.id === Number($("#productionRecipe").value)) || recipes[0];
  const quantity = Math.max(1, Number($("#productionQuantity").value || 1));
  if (!recipe) return;
  $("#productionCost").textContent = money(recipeCost(recipe) * quantity);
  $("#productionPreview").innerHTML = recipe.components.map((component) => {
    const ingredient = ingredientById(component.ingredientId);
    const required = componentGross(component) / 1000 * quantity;
    const available = ingredient ? availableStock(ingredient) : 0;
    return `<div><span>${ingredient?.name || "Не найден"}</span><b class="${required > available ? "low" : ""}">${decimal(required, 3)} ${ingredient?.unit || "ед."} <small>из ${decimal(available, 3)}</small></b></div>`;
  }).join("");
}

function saveProduction() {
  if (!hasRole("owner", "branch")) return;
  const recipe = recipes.find((entry) => entry.id === Number($("#productionRecipe").value));
  const quantity = Math.max(1, Math.round(Number($("#productionQuantity").value || 1)));
  if (!recipe) return;
  const shortage = recipe.components.find((component) => {
    const ingredient = ingredientById(component.ingredientId);
    return !ingredient || componentGross(component) / 1000 * quantity > availableStock(ingredient);
  });
  if (shortage) {
    showToast(`Недостаточно «${ingredientById(shortage.ingredientId)?.name || "ингредиента"}» для производства`);
    return;
  }
  const total = recipeCost(recipe) * quantity;
  recipe.components.forEach((component) => {
    const ingredient = ingredientById(component.ingredientId);
    ingredient.stock -= componentGross(component) / 1000 * quantity;
  });
  saveIngredients();
  addDocument("production", {
    warehouse: $("#productionWarehouse").value,
    recipeId: recipe.id,
    recipeName: recipe.name,
    quantity,
    total,
    description: `${recipe.name} · ${quantity} порц. · готово ${finishedStock(recipe.id) + quantity} порц.`,
    items: recipe.components.map((component) => ({ ingredientId: component.ingredientId, quantity: componentGross(component) / 1000 * quantity }))
  });
  $("#productionModal").classList.add("hidden");
  renderAll();
  switchStockTab("production");
  showToast(`Произведено ${quantity} порций «${recipe.name}»`);
}

function inventoryCategories() {
  return [...new Set([...ingredients, ...products].map((entity) => entity.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru"));
}

function inventorySnapshotItems(branchId, scope, category) {
  return [...ingredients, ...products]
    .filter((entity) => scope === "full" || entity.category === category)
    .map((entity) => ({ itemId: entity.id, book: branchStock(branchId, entity.id), actual: null, unitCost: branchUnitCost(branchId, entity.id) }));
}

function showInventorySetup() {
  if (!["branch","owner"].includes(currentRole) && !testMode) { showToast("Инвентаризацию начинает управляющий точки"); return; }
  const branchId = currentSession.branchId || pendingOwnerObjectScope || branches[0]?.id;
  const activeInventory = inventoryLockForBranch(branchId);
  if (activeInventory && currentRole !== "owner") { openInventoryDocument(activeInventory.id); return; }
  currentInventoryId = null;
  $("#inventoryModalEyebrow").textContent = "Контроль остатков точки";
  $("#inventoryModalTitle").textContent = "Новая инвентаризация";
  $("#inventoryWarehouse").disabled = currentRole !== "owner";
  $("#inventoryWarehouse").innerHTML = (currentRole === "owner" ? branches : branches.filter(b=>b.id===branchId)).map(b=>`<option value="${escapeHtml(b.id)}" ${b.id===branchId ? "selected" : ""}>${escapeHtml(b.name)}</option>`).join("");
  $("#inventoryScope").value = "full";
  $("#inventoryCountedAt").value = "";
  $("#inventoryCountedAt").disabled = false;
  $("#inventorySelection").classList.add("hidden");
  prepareInventorySelection();
  $("#inventoryCategory").innerHTML = inventoryCategories().map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`).join("");
  $("#inventoryCategory").disabled = true;
  $("#inventoryResponsible").value = currentSession.name;
  $("#inventorySetup").classList.remove("hidden");
  $("#inventoryCountWorkspace").classList.add("hidden");
  $("#startInventoryButton").classList.remove("hidden");
  ["#cancelInventoryButton", "#saveInventoryDraftButton", "#submitInventoryButton", "#returnInventoryButton", "#postInventoryButton"].forEach((selector) => $(selector).classList.add("hidden"));
  $("#inventoryModal").classList.remove("hidden");
}

function openInventoryForm(inventoryId = null) {
  switchView("inventory");
  switchStockTab("inventories");
  if (inventoryId) { openInventoryDocument(inventoryId); return; }
  showInventorySetup();
}

async function startInventoryCount() {
  if (!["branch","owner"].includes(currentRole) && !testMode) return;
  const branchId = $("#inventoryWarehouse").value;
  const existing = inventoryLockForBranch(branchId);
  if (existing) { openInventoryDocument(existing.id); return; }
  const responsible = $("#inventoryResponsible").value.trim();
  if (!responsible) { showToast("Укажите ответственного за подсчёт"); return; }
  const scope = $("#inventoryScope").value;
  const category = scope === "category" ? $("#inventoryCategory").value : "";
  const items = inventorySnapshotItems(branchId, scope === "category" ? scope : "full", category);
  if (!items.length) { showToast("В выбранной категории нет продуктов"); return; }
  if (serverMode) {
    const response = await runServerAction("inventory.start", { branchId, scope, category, responsible, itemIds:[...document.querySelectorAll("[data-inventory-select]:checked")].map(el=>el.value), countedAt:$("#inventoryCountedAt").value ? new Date($("#inventoryCountedAt").value).toISOString() : null });
    if (!response) return;
    openInventoryDocument(response.entity?.id);
    showToast("Подсчёт начат, движения по точке приостановлены");
    return;
  }
  const number = nextDocumentNumber("ИНВ", logisticsState.inventories);
  const inventory = {
    id: `inventory-${Date.now()}`,
    number,
    branchId,
    scope,
    category,
    responsible,
    status: "counting",
    items,
    comment: "",
    createdAt: new Date().toISOString(),
    createdBy: currentSession.name
  };
  logisticsState.inventories.unshift(inventory);
  saveLogisticsState();
  renderAll();
  openInventoryDocument(inventory.id);
  showToast(`${number}: подсчёт начат, движения по точке приостановлены`);
}

function openInventoryDocument(inventoryId) {
  const inventory = inventoryById(inventoryId);
  if (!inventory) return;
  if (currentRole === "branch" && currentSession.branchId !== inventory.branchId) { showToast("Документ относится к другой точке"); return; }
  currentInventoryId = inventory.id;
  const branch = branchById(inventory.branchId);
  const editable = (["branch","owner"].includes(currentRole) || testMode) && ["counting", "returned"].includes(inventory.status);
  const review = (currentRole === "owner" || testMode) && inventory.status === "submitted";
  const isLocked = ["counting", "submitted", "returned"].includes(inventory.status);
  $("#inventoryModalEyebrow").textContent = inventory.status === "submitted" ? "Проверка инвентаризации" : "Контроль остатков точки";
  $("#inventoryModalTitle").textContent = `${inventory.number} · ${inventoryStatusLabel(inventory.status)}`;
  $("#inventorySetup").classList.add("hidden");
  $("#inventoryCountWorkspace").classList.remove("hidden");
  $("#inventoryDocumentMeta").innerHTML = `<div><span>Точка</span><strong>${escapeHtml(branch?.name || "Точка")}</strong></div><div><span>Проверка</span><strong>${escapeHtml(inventoryScopeLabel(inventory))}</strong><small>${inventory.items.length} ${pluralRu(inventory.items.length, "позиция", "позиции", "позиций")}</small></div><div><span>Ответственный</span><strong>${escapeHtml(inventory.responsible)}</strong><small>${escapeHtml(inventory.createdBy)}</small></div><div><span>Начата</span><strong>${new Date(inventory.countedAt || inventory.createdAt).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</strong><small>${inventory.submittedAt ? `отправлена ${new Date(inventory.submittedAt).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}` : "черновик точки"}</small></div>`;
  $("#inventoryLockNote").classList.toggle("hidden", !isLocked);
  $("#inventoryLockNote").classList.toggle("returned", inventory.status === "returned");
  $("#inventoryLockNote").innerHTML = inventory.status === "returned"
    ? `${uiIcon("checklist")}<div><strong>Главный администратор вернул документ на пересчёт</strong><small>${escapeHtml(inventory.reviewComment || "Уточните фактические количества и отправьте повторно.")}</small></div>`
    : inventory.status === "submitted"
      ? `${uiIcon("alert")}<div><strong>Документ отправлен на проверку</strong><small>Складские движения точки приостановлены до решения главного администратора.</small></div>`
      : `${uiIcon("alert")}<div><strong>Остатки точки зафиксированы</strong><small>Поставки, перемещения и производство временно заблокированы.</small></div>`;
  $("#inventoryCountSearch").value = "";
  $("#inventoryCountFilter").value = "all";
  renderInventoryCountTable(inventory, editable);
  $("#inventoryCommentLabel").textContent = editable ? "Комментарий управляющего" : "Комментарий управляющего к подсчёту";
  $("#inventoryComment").value = inventory.comment || "";
  $("#inventoryComment").readOnly = !editable;
  $("#inventoryReviewField").classList.toggle("hidden", !review && !inventory.reviewComment);
  $("#inventoryReviewComment").value = inventory.reviewComment || "";
  $("#inventoryReviewComment").readOnly = !review;
  $("#startInventoryButton").classList.add("hidden");
  $("#cancelInventoryButton").classList.toggle("hidden", !editable);
  $("#saveInventoryDraftButton").classList.toggle("hidden", !editable);
  $("#submitInventoryButton").classList.toggle("hidden", !editable);
  $("#returnInventoryButton").classList.toggle("hidden", !review);
  $("#postInventoryButton").classList.toggle("hidden", !review);
  updateInventoryDifference();
  filterInventoryCount();
  $("#inventoryModal").classList.remove("hidden");
}

function inventoryItemInfo(item) {
  const entity = logisticsItem(item.itemId);
  return {
    name: item.name || entity?.name || "Позиция",
    unit: item.unit || entity?.unit || "ед.",
    category: item.lotId ? "Раздача" : item.category || entity?.category || ""
  };
}

function inventoryDateLabel(value) {
  const date = new Date(value);
  return value && Number.isFinite(date.getTime()) ? date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}

function inventoryVariance(actual, book) {
  return actual == null || !Number.isFinite(actual) ? null
    : Math.round(actual * 1000) === Math.round(Number(book || 0) * 1000) ? 0 : actual - Number(book || 0);
}

function inventoryMovementCell(item, index, field, bucket, monetary = false) {
  const summary = item.movementSummary;
  const value = summary?.available ? summary[field] : null;
  if (value == null) return '<span class="inventory-muted">—</span>';
  const label = monetary ? money(value) : decimal(value, 3);
  if (!summary.entries?.some(entry => entry.bucket === bucket)) return label;
  const titles = { incoming: "Поступления", outgoing: "Расход", writeoff: "Списания", adjustment: "Корректировки" };
  return `<button type="button" class="inventory-movement-link" data-inventory-movement="${index}" data-movement-bucket="${bucket}" aria-label="${escapeHtml(`${titles[bucket]}: ${inventoryItemInfo(item).name}`)}">${label}${uiIcon("chevron")}</button>`;
}

function renderInventoryCountTable(inventory, editable) {
  const serving = inventory.scope === "serving";
  const headings = ["Наименование", ...(!serving ? ["Последняя проверка", "Нач. остаток", "Поступления", "Расход", "Списано", "Списано, сом", "Корректировки"] : []), "Учётный остаток", "Факт. остаток", "Сумма факта", "Разница", "Разница, сом"];
  const cells = inventory.items.map((item, index) => {
    const entity = inventoryItemInfo(item);
    const summary = item.movementSummary;
    const actual = item.actual == null ? "" : Number(Number(item.actual).toFixed(3));
    const cell = (label, html, className = "") => `<td data-label="${label}" class="${className}">${html}</td>`;
    return `<tr class="inventory-count-row" data-inventory-item="${escapeHtml(String(item.itemId))}" data-book-stock="${Number(item.book || 0)}" data-unit-cost="${Number(item.unitCost || 0)}">
      <th scope="row" class="inventory-item-name"><strong>${escapeHtml(entity.name)}</strong><small>${escapeHtml(entity.category)} · ${escapeHtml(entity.unit)}</small></th>
      ${!serving ? cell("Последняя проверка", escapeHtml(inventoryDateLabel(summary?.lastCountAt)), "inventory-last-count")
        + cell("Нач. остаток", summary?.available ? decimal(summary.opening, 3) : "—")
        + cell("Поступления", inventoryMovementCell(item, index, "incoming", "incoming"))
        + cell("Расход", inventoryMovementCell(item, index, "outgoing", "outgoing"))
        + cell("Списано", inventoryMovementCell(item, index, "writtenOff", "writeoff"))
        + cell("Списано, сом", inventoryMovementCell(item, index, "writtenOffCost", "writeoff", true))
        + cell("Корректировки", inventoryMovementCell(item, index, "adjustments", "adjustment")) : ""}
      ${cell("Учётный остаток", `<strong>${decimal(item.book, 3)}</strong>`, "inventory-book-cell")}
      ${cell("Факт. остаток", `<input class="inventory-actual" type="number" inputmode="decimal" min="0" step="0.001" value="${actual}" placeholder="Введите" aria-label="${escapeHtml(`Фактический остаток: ${entity.name}, ${entity.unit}`)}" ${editable ? "" : "readonly"}>`, "inventory-actual-cell")}
      ${cell("Сумма факта", '<span class="inventory-actual-value">—</span>')}
      ${cell("Разница", '<strong class="inventory-diff">—</strong>')}
      ${cell("Разница, сом", '<strong class="inventory-diff-value">—</strong>')}
    </tr>`;
  }).join("");
  $("#inventoryCountList").innerHTML = `<table class="inventory-count-table ${serving ? "inventory-serving-table" : ""}"><thead><tr>${headings.map((heading) => `<th scope="col">${heading}</th>`).join("")}</tr></thead><tbody>${cells}</tbody></table>`;
  const missingHistory = !serving && inventory.items.some(item => !item.movementSummary?.available);
  const reconstructed = inventory.items.some(item => item.movementSummary?.available && item.movementSummary.openingBasis === "reconstructed");
  $("#inventoryHistoryNote").textContent = serving
    ? "Учёт принятой раздачи. Ингредиенты списаны при производстве и повторно не учитываются."
    : missingHistory ? "В этом документе часть расшифровок не сохранена. Полная история фиксируется для новых инвентаризаций."
    : reconstructed ? "Начальный остаток восстановлен по истории движений. Значения со стрелкой открывают расшифровку." : "Значения со стрелкой открывают расшифровку движений с предыдущей проверки.";
  $("#inventoryHistoryNote").classList.remove("hidden");
}

function filterInventoryCount(keepEditing = false) {
  const query = $("#inventoryCountSearch").value.trim().toLocaleLowerCase();
  const filter = $("#inventoryCountFilter").value;
  let visible = 0;
  let counted = 0;
  const rows = [...document.querySelectorAll("#inventoryCountList .inventory-count-row")];
  rows.forEach(row => {
    const input = row.querySelector(".inventory-actual");
    const actual = input.value === "" ? null : Number(input.value);
    const isCounted = actual != null && Number.isFinite(actual) && actual >= 0;
    if (isCounted) counted += 1;
    const difference = inventoryVariance(actual, Number(row.dataset.bookStock));
    const matches = filter === "all" || (filter === "uncounted" && !isCounted) || (filter === "counted" && isCounted) || (filter === "different" && isCounted && difference !== 0);
    const editing = keepEditing === true && row.contains(document.activeElement);
    row.hidden = !editing && (!matches || !row.querySelector(".inventory-item-name").textContent.toLocaleLowerCase().includes(query));
    if (!row.hidden) visible += 1;
  });
  $("#inventoryCountProgress").textContent = `Подсчитано: ${counted} из ${rows.length}`;
  $("#inventoryCountEmpty").classList.toggle("hidden", visible > 0);
}

function inventoryDocumentRows(inventory) {
  const inputs = currentInventoryId === inventory.id ? new Map([...document.querySelectorAll("#inventoryCountList .inventory-count-row")].map(row => [row.dataset.inventoryItem, row.querySelector(".inventory-actual").value])) : new Map();
  return inventory.items.map(item => {
    const raw = inputs.has(String(item.itemId)) ? inputs.get(String(item.itemId)) : item.actual;
    const actual = raw == null || raw === "" ? null : Number(raw);
    const difference = inventoryVariance(actual, item.book);
    return { ...item, ...inventoryItemInfo(item), actual, difference, actualValue: actual == null ? null : actual * Number(item.unitCost || 0), differenceValue: difference == null ? null : difference * Number(item.unitCost || 0) };
  });
}

function openInventoryMovement(index, bucket) {
  const inventory = inventoryById(currentInventoryId);
  const item = inventory?.items[Number(index)];
  const summary = item?.movementSummary;
  if (!summary?.available) return;
  const titles = { incoming: "Поступления", outgoing: "Расход", writeoff: "Списания", adjustment: "Корректировки" };
  if (!titles[bucket]) return;
  const types = { supplier_receipt: "Поставка", transfer_in: "Перемещение на точку", transfer_out: "Перемещение с точки", production_consumption: "Производство", sale: "Продажа товара", sale_consumption: "Продажа блюда", sale_refund: "Возврат продажи", sales_import: "Импорт продаж", external_sale: "Импорт продаж", writeoff: "Списание", inventory_adjustment: "Инвентаризация", ingredient_count: "Пересчёт смены" };
  const entries = (summary.entries || []).filter(entry => entry.bucket === bucket);
  const entity = inventoryItemInfo(item);
  $("#inventoryMovementTitle").textContent = `${titles[bucket]} · ${entity.name}`;
  $("#inventoryMovementSubtitle").textContent = `${summary.lastCountAt ? `После проверки ${inventoryDateLabel(summary.lastCountAt)}` : "По сохранённой истории"} · до ${inventoryDateLabel(summary.asOf || inventory.countedAt || inventory.createdAt)}`;
  let quantity = 0;
  let cost = 0;
  let knownCost = true;
  $("#inventoryMovementBody").innerHTML = `<div class="inventory-movement-table-wrap"><table><thead><tr><th>Дата</th><th>Операция</th><th>Количество</th><th>Стоимость</th><th>Сотрудник</th></tr></thead><tbody>${entries.map(entry => {
    quantity += Number(entry.quantity || 0);
    if (entry.cost == null) knownCost = false;
    else cost += Number(entry.cost);
    const document = entry.documentNumber && entry.documentNumber !== "POS" ? entry.documentNumber : "";
    return `<tr><td>${escapeHtml(inventoryDateLabel(entry.date))}</td><td><strong>${escapeHtml(types[entry.movementType] || titles[bucket])}${document ? ` · ${escapeHtml(document)}` : ""}</strong>${entry.dishName ? `<small>${escapeHtml(entry.dishName)}</small>` : ""}</td><td>${decimal(entry.quantity, 3)} ${escapeHtml(entity.unit)}</td><td>${entry.cost == null ? "—" : money(entry.cost)}</td><td>${escapeHtml(entry.actor || "—")}</td></tr>`;
  }).join("")}</tbody></table></div><footer><span>${entries.length} ${pluralRu(entries.length, "операция", "операции", "операций")}</span><strong>${decimal(quantity, 3)} ${escapeHtml(entity.unit)}</strong><strong>${knownCost ? money(cost) : "Стоимость не сохранена"}</strong></footer>`;
  const dialog = $("#inventoryMovementDialog");
  if (!dialog.open) dialog.showModal();
}

async function exportInventoryDocument() {
  const inventory = inventoryById(currentInventoryId);
  if (!inventory) return;
  if (!serverMode) { showToast("Экспорт доступен для сохранённых документов на сервере"); return; }
  const button = $("#exportInventoryButton");
  button.disabled = true;
  try {
    const items = inventoryDocumentRows(inventory).map(item => ({ itemId: item.itemId, actual: item.actual }));
    if (items.some(item => item.actual != null && (!Number.isFinite(item.actual) || item.actual < 0))) { showToast("Проверьте фактические остатки"); return; }
    const report = await AshkanaApi.exportInventory(inventory.id, ["counting", "returned"].includes(inventory.status) ? items : undefined);
    const bytes = Uint8Array.from(atob(report.xlsx), character => character.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = report.filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { showToast(error.message || "Не удалось выгрузить инвентаризацию"); }
  finally { button.disabled = false; }
}

function inventoryPrintHtml(inventory) {
  const rows = inventoryDocumentRows(inventory);
  const serving = inventory.scope === "serving";
  let surplus = 0, shortage = 0;
  rows.forEach(item => { if (item.differenceValue > 0) surplus += item.differenceValue; else if (item.differenceValue < 0) shortage -= item.differenceValue; });
  const quantity = value => value == null ? "—" : decimal(value, 3);
  const amount = value => value == null ? "—" : money(value);
  const heading = ["Наименование", "Ед.", ...(!serving ? ["Нач. остаток", "Приход", "Расход", "Списано", "Корректировки"] : []), "Учёт", "Факт", "Сумма факта", "Разница", "Разница, сом"];
  return `<!doctype html><html lang="ru"><meta charset="utf-8"><title>${escapeHtml(inventory.number)} · Oimo</title><style>@page{size:A4 landscape;margin:12mm}body{font:11px Arial,sans-serif;color:#302b32}h1{font-size:20px;margin-bottom:8px}p{line-height:1.5}table{width:100%;border-collapse:collapse;margin-top:20px}th,td{padding:7px 5px;border-bottom:1px solid #ded8dc;text-align:right}th:first-child,td:first-child{text-align:left}thead{display:table-header-group}th{background:#f1e9f0}tr{break-inside:avoid}footer{margin-top:20px;display:flex;gap:30px;justify-content:flex-end}.note{color:#716a73;font-size:10px}</style><body><h1>${escapeHtml(inventory.number)} · Инвентаризация</h1><p>${escapeHtml(branchById(inventory.branchId)?.name || "Точка")} · ${escapeHtml(inventoryDateLabel(inventory.countedAt || inventory.createdAt))}<br>Ответственный: ${escapeHtml(inventory.responsible || "—")} · ${escapeHtml(inventoryStatusLabel(inventory.status))}</p><table><thead><tr>${heading.map(text => `<th>${text}</th>`).join("")}</tr></thead><tbody>${rows.map(item => {
    const s = item.movementSummary?.available ? item.movementSummary : {};
    const values = [item.name, item.unit, ...(!serving ? [quantity(s.opening), quantity(s.incoming), quantity(s.outgoing), quantity(s.writtenOff), quantity(s.adjustments)] : []), quantity(item.book), quantity(item.actual), amount(item.actualValue), quantity(item.difference), amount(item.differenceValue)];
    return `<tr>${values.map(value => `<td>${escapeHtml(String(value))}</td>`).join("")}</tr>`;
  }).join("")}</tbody></table><p class="note">Подсчитано: ${rows.filter(item => item.actual != null).length} из ${rows.length}. ${escapeHtml($("#inventoryHistoryNote").textContent.replace("Значения со стрелкой открывают расшифровку.", ""))}</p><footer><span>Излишки: <b>${money(surplus)}</b></span><span>Недостача: <b>${money(shortage)}</b></span><span>Итого: <b>${money(surplus - shortage)}</b></span></footer></body></html>`;
}

function printInventoryDocument() {
  const inventory = inventoryById(currentInventoryId);
  if (!inventory) return;
  const printWindow = window.open("", "_blank", "width=1100,height=800");
  if (!printWindow) { showToast("Браузер заблокировал окно печати"); return; }
  printWindow.opener = null;
  printWindow.document.write(inventoryPrintHtml(inventory));
  printWindow.document.close();
  setTimeout(() => { printWindow.focus(); printWindow.print(); }, 250);
}

function syncInventoryCount(inventory) {
  document.querySelectorAll(".inventory-count-row").forEach((row) => {
    const item = inventory.items.find((entry) => String(entry.itemId) === row.dataset.inventoryItem);
    if (!item) return;
    const raw = row.querySelector(".inventory-actual").value.trim();
    item.actual = raw === "" ? null : Math.max(0, Number(raw));
  });
  inventory.comment = $("#inventoryComment").value.trim();
}

function updateInventoryDifference() {
  let surplus = 0;
  let shortage = 0;
  const inventory = inventoryById(currentInventoryId);
  document.querySelectorAll(".inventory-count-row").forEach((row) => {
    const item = inventory?.items.find((entry) => String(entry.itemId) === row.dataset.inventoryItem);
    const unit = item?.unit || stockEntityById(row.dataset.inventoryItem)?.unit || "";
    const book = Number(row.dataset.bookStock || 0);
    const raw = row.querySelector(".inventory-actual").value.trim();
    const differenceElement = row.querySelector(".inventory-diff");
    const actualValue = row.querySelector(".inventory-actual-value");
    const differenceValue = row.querySelector(".inventory-diff-value");
    if (raw === "") {
      differenceElement.textContent = "—";
      differenceElement.className = "inventory-diff";
      if (actualValue) actualValue.textContent = "—";
      if (differenceValue) { differenceValue.textContent = "—"; differenceValue.className = "inventory-diff-value"; }
      return;
    }
    const actual = Math.max(0, Number(raw));
    const difference = Math.round(actual * 1000) === Math.round(book * 1000) ? 0 : actual - book;
    differenceElement.textContent = `${difference > 0 ? "+" : ""}${decimal(difference, 3)}${unit ? ` ${unit}` : ""}`;
    differenceElement.className = `inventory-diff ${difference > 0 ? "positive" : difference < 0 ? "negative" : ""}`;
    const amount = difference * Number(row.dataset.unitCost || 0);
    if (actualValue) actualValue.textContent = money(actual * Number(row.dataset.unitCost || 0));
    if (differenceValue) {
      differenceValue.textContent = `${amount > 0 ? "+" : amount < 0 ? "−" : ""}${money(Math.abs(amount))}`;
      differenceValue.className = `inventory-diff-value ${amount > 0 ? "positive" : amount < 0 ? "negative" : ""}`;
    }
    if (amount > 0) surplus += amount;
    else shortage += Math.abs(amount);
  });
  const net = surplus - shortage;
  $("#inventorySurplus").textContent = money(surplus);
  $("#inventoryShortage").textContent = money(shortage);
  $("#inventoryNetDifference").textContent = `${net > 0 ? "+" : net < 0 ? "−" : ""}${money(Math.abs(net))}`;
  $("#inventoryNetDifference").className = net > 0 ? "positive" : net < 0 ? "negative" : "";
}

async function saveInventoryDraft() {
  const inventory = inventoryById(currentInventoryId);
  if (!inventory || !["counting", "returned"].includes(inventory.status) || (!["branch","owner"].includes(currentRole) && !testMode)) return;
  syncInventoryCount(inventory);
  if (serverMode) {
    const response = await runServerAction("inventory.save", {
      id: inventory.id,
      comment: inventory.comment,
      items: inventory.items.map((item) => ({ itemId: item.itemId, actual: item.actual }))
    });
    if (!response) return;
    $("#inventoryModal").classList.add("hidden");
    switchStockTab("inventories");
    showToast(`${inventory.number}: черновик подсчёта сохранён`);
    return;
  }
  inventory.savedAt = new Date().toISOString();
  inventory.savedBy = currentSession.name;
  saveLogisticsState();
  $("#inventoryModal").classList.add("hidden");
  renderAll();
  switchStockTab("inventories");
  showToast(`${inventory.number}: черновик подсчёта сохранён`);
}

async function submitInventory() {
  const inventory = inventoryById(currentInventoryId);
  if (!inventory || !["counting", "returned"].includes(inventory.status) || (!["branch","owner"].includes(currentRole) && !testMode)) return;
  syncInventoryCount(inventory);
  const missing = inventory.items.find((item) => item.actual == null || !Number.isFinite(Number(item.actual)));
  if (missing) { showToast(`Введите фактическое количество: ${logisticsItem(missing.itemId)?.name || "позиция"}`); return; }
  if (serverMode) {
    const response = await runServerAction("inventory.submit", {
      id: inventory.id,
      comment: inventory.comment,
      items: inventory.items.map((item) => ({ itemId: item.itemId, actual: item.actual }))
    });
    if (!response) return;
    $("#inventoryModal").classList.add("hidden");
    switchView("inventory");
    switchStockTab("inventories");
    showToast(`${inventory.number}: инвентаризация отправлена главному администратору`);
    return;
  }
  inventory.status = "submitted";
  inventory.submittedAt = new Date().toISOString();
  inventory.submittedBy = currentSession.name;
  inventory.reviewComment = "";
  const totals = inventoryTotals(inventory);
  inventory.surplus = totals.surplus;
  inventory.shortage = totals.shortage;
  inventory.delta = totals.net;
  saveLogisticsState();
  $("#inventoryModal").classList.add("hidden");
  renderAll();
  switchView("inventory");
  switchStockTab("inventories");
  showToast(`${inventory.number}: инвентаризация отправлена главному администратору`);
}

async function cancelInventory() {
  const inventory = inventoryById(currentInventoryId);
  if (!inventory || !["counting", "returned"].includes(inventory.status) || (!["branch","owner"].includes(currentRole) && !testMode)) return;
  if (serverMode) {
    const response = await runServerAction("inventory.cancel", { id: inventory.id });
    if (!response) return;
    $("#inventoryModal").classList.add("hidden");
    switchStockTab("inventories");
    showToast(`${inventory.number}: документ отменён, складские движения доступны`);
    return;
  }
  inventory.status = "cancelled";
  inventory.cancelledAt = new Date().toISOString();
  inventory.cancelledBy = currentSession.name;
  saveLogisticsState();
  $("#inventoryModal").classList.add("hidden");
  renderAll();
  switchStockTab("inventories");
  showToast(`${inventory.number}: документ отменён, складские движения доступны`);
}

async function returnInventory() {
  const inventory = inventoryById(currentInventoryId);
  if (!inventory || inventory.status !== "submitted" || (currentRole !== "owner" && !testMode)) return;
  const comment = $("#inventoryReviewComment").value.trim();
  if (!comment) { showToast("Укажите причину возврата на пересчёт"); return; }
  if (serverMode) {
    const response = await runServerAction("inventory.return", { id: inventory.id, comment });
    if (!response) return;
    $("#inventoryModal").classList.add("hidden");
    switchStockTab("inventories");
    showToast(`${inventory.number}: возвращена точке на пересчёт`);
    return;
  }
  inventory.status = "returned";
  inventory.reviewComment = comment;
  inventory.returnedAt = new Date().toISOString();
  inventory.returnedBy = currentSession.name;
  saveLogisticsState();
  $("#inventoryModal").classList.add("hidden");
  renderAll();
  switchStockTab("inventories");
  showToast(`${inventory.number}: возвращена точке на пересчёт`);
}

async function postInventory() {
  const inventory = inventoryById(currentInventoryId);
  if (!inventory || inventory.status !== "submitted" || (currentRole !== "owner" && !testMode)) return;
  if (serverMode) {
    const response = await runServerAction("inventory.post", {
      id: inventory.id,
      comment: $("#inventoryReviewComment").value.trim()
    });
    if (!response) return;
    $("#inventoryModal").classList.add("hidden");
    switchView("inventory");
    switchStockTab("inventories");
    showToast(`${inventory.number}: проведена, остатки точки скорректированы`);
    return;
  }
  const changedItem = inventory.items.find((item) => Math.abs(branchStock(inventory.branchId, item.itemId) - Number(item.book || 0)) > .0001);
  if (changedItem) { showToast(`Остаток «${logisticsItem(changedItem.itemId)?.name || "позиции"}» изменился после начала — нужен новый подсчёт`); return; }
  logisticsState.branchStocks[inventory.branchId] ||= {};
  inventory.items.forEach((item) => { logisticsState.branchStocks[inventory.branchId][item.itemId] = Number(item.actual || 0); });
  const totals = inventoryTotals(inventory);
  inventory.status = "posted";
  inventory.postedAt = new Date().toISOString();
  inventory.postedBy = currentSession.name;
  inventory.reviewComment = $("#inventoryReviewComment").value.trim();
  inventory.surplus = totals.surplus;
  inventory.shortage = totals.shortage;
  inventory.delta = totals.net;
  inventory.total = totals.surplus + totals.shortage;
  saveLogisticsState();
  $("#inventoryModal").classList.add("hidden");
  renderAll();
  switchView("inventory");
  switchStockTab("inventories");
  showToast(`${inventory.number}: проведена, остатки точки скорректированы`);
}

function canAccessView(view) {
  if (currentRole === "owner") return true;
  if (currentSession.permissions && typeof currentSession.permissions === "object") {
    const permissionByView = { reports: "reports", recipes: "menu", inventory: "inventory", logistics: "production", finance: "finance", employees: "employees", registers: "registers", settings: "settings" };
    return Boolean(currentSession.permissions[permissionByView[view]]);
  }
  const staffRole = currentSession.staffRole || "branch_manager";
  if (staffRole === "production") return view === "logistics";
  if (staffRole === "storekeeper") return view === "inventory";
  if (["cashier", "waiter", "hall_admin"].includes(staffRole)) return false;
  if (staffRole === "marketer") return ["reports", "recipes"].includes(view);
  return ["inventory", "logistics", "employees", "registers"].includes(view);
}

function canAccessStockTab(tab) {
  if (currentRole === "owner") return ["overview", "inventories", "suppliers", "supplies", "point-transfers", "writeoff", "movement"].includes(tab);
  if (currentSession.permissions && typeof currentSession.permissions === "object") return Boolean(currentSession.permissions.inventory);
  if ((currentSession.staffRole || "branch_manager") === "production") return false;
  return ["overview", "inventories", "suppliers", "supplies", "point-transfers", "writeoff", "movement"].includes(tab);
}

function defaultRoleRoute() {
  if (currentRole === "branch" && currentSession.permissions && typeof currentSession.permissions === "object") {
    const routes = [["reports", "reports"], ["menu", "recipes"], ["inventory", "inventory/supplies"], ["production", "logistics"], ["finance", "finance"], ["employees", "employees"], ["registers", "registers"], ["settings", "settings"]];
    return routes.find(([permission]) => currentSession.permissions[permission])?.[1] || "inventory/supplies";
  }
  if (currentRole === "branch" && currentSession.staffRole === "production") return "logistics";
  if (currentRole === "branch" && currentSession.staffRole === "marketer") return "reports";
  if (currentRole === "branch") return "inventory/supplies";
  return "dashboard";
}

function renderOwnerPointContext() {
  if (currentRole !== "owner") return;
  $("#ownerScopeNavLabel").textContent = "Доступ";
}

function renderOwnerObjectSelector() {
  if (currentRole !== "owner") return;
  pendingOwnerObjectScope = branches[0]?.id;
  renderOwnerPointContext();
}

function applyRoleWorkspace() {
  const sessionBranch = branchById(currentSession.branchId);
  document.querySelectorAll("[data-role-navigation]").forEach((navigation) => navigation.classList.toggle("hidden", navigation.dataset.roleNavigation !== currentRole));
  $("#sessionInitials").textContent = currentSession.initials;
  $("#sessionName").textContent = currentSession.name;
  $("#sessionRole").textContent = currentSession.roleLabel;
  $("#workspaceLabel").textContent = currentRole === "owner" ? (currentSession.tenantName || "аккаунт").toLowerCase() : sessionBranch?.name.toLowerCase() || currentSession.scope || "заведение";
  $("#branchNavLabel").textContent = sessionBranch?.name || currentSession.scope || "Заведение";
  const canOpenRegister = currentRole === "owner" || (currentRole === "branch" && (currentSession.permissions ? currentSession.permissions.posAccess : currentSession.staffRole === "branch_manager"));
  $("#cashierLink").classList.toggle("hidden", !canOpenRegister);
  $("#stockTabs").classList.toggle("hidden", currentRole !== "owner");
  if (currentRole === "branch") {
    $("#productionBranchSelect").disabled = true;
    $("#batchBranch").disabled = true;
    $("#requestBranch").disabled = true;
    document.querySelectorAll('[data-role-navigation="branch"] .nav-item').forEach((button) => {
      const [view, tab] = String(button.dataset.roleRoute || button.dataset.view || "").split("/");
      button.classList.toggle("hidden", !canAccessView(view) || (view === "inventory" && !canAccessStockTab(tab || "overview")));
    });
  }
  renderOwnerObjectSelector();
  if (currentRole !== "owner") {
    document.querySelectorAll(".admin-view").forEach((view) => {
      const viewName = view.id.replace("view-", "");
      if (!canAccessView(viewName)) view.remove();
    });
  }
}

function routeRoleWorkspace(route) {
  const [view, tab] = route.split("/");
  if (!canAccessView(view)) return routeRoleWorkspace(defaultRoleRoute());
  if (view === "inventory" && !canAccessStockTab(tab || "overview")) return routeRoleWorkspace(defaultRoleRoute());
  switchView(view);
  if (view === "inventory") switchStockTab(tab || "overview");
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.roleRoute === `${view}/${tab || "overview"}` || (!button.dataset.roleRoute && button.dataset.view === view)));
}

const ownerNavSectionByView = {
  reports: "analytics",
  recipes: "menu",
  inventory: "stock",
  logistics: "stock",
  finance: "finance",
  branches: "access",
  registers: "access",
  employees: "access",
  settings: "settings"
};

function mobileWorkspaceChoices() {
  const view = document.querySelector(".admin-view.active")?.id.replace("view-", "");
  const section = ownerNavSectionByView[view];
  const submenuId = { analytics: "analyticsNavSubmenu", menu: "menuSubnav", stock: "stockNavSubmenu", finance: "financeNavSubmenu", access: "accessNavSubmenu", settings: "settingsNavSubmenu" }[section];
  if (!submenuId) return [];
  const targets = { menuPage: "recipes", ownerAnalyticsTab: "reports", ownerStockTab: "inventory", ownerFinanceTab: "finance", settingsTab: "settings" };
  return [...document.querySelectorAll(`#${submenuId} button`)].flatMap((button) => {
    const key = Object.keys(targets).find((name) => button.dataset[name]) || (button.dataset.ownerAccessView ? "ownerAccessView" : "ownerView");
    const value = button.dataset[key];
    const targetView = targets[key] || value;
    if (!value || button.hidden || button.disabled || button.classList.contains("hidden") || !canAccessView(targetView)) return [];
    if (key === "ownerStockTab" && !canAccessStockTab(value)) return [];
    const selected = view === targetView && (["ownerView", "ownerAccessView"].includes(key) || button.classList.contains("active"));
    return [{ value: `${key}:${value}`, label: button.textContent.trim(), selected, button }];
  });
}

function renderMobileWorkspaceNavigation() {
  const container = $("#mobileWorkspaceNavigation");
  const select = $("#mobileWorkspaceSelect");
  const choices = mobileWorkspaceChoices();
  container.classList.toggle("hidden", choices.length < 2);
  select.innerHTML = choices.map((choice) => `<option value="${escapeHtml(choice.value)}"${choice.selected ? " selected" : ""}>${escapeHtml(choice.label)}</option>`).join("");
}

function setOwnerNavSection(section, open) {
  const submenuId = { analytics: "analyticsNavSubmenu", menu: "menuSubnav", stock: "stockNavSubmenu", finance: "financeNavSubmenu", access: "accessNavSubmenu", settings: "settingsNavSubmenu" }[section];
  const submenu = submenuId ? $(`#${submenuId}`) : null;
  const trigger = document.querySelector(`[data-nav-section="${section}"]`);
  if (!submenu || !trigger) return;
  submenu.classList.toggle("visible", open);
  trigger.setAttribute("aria-expanded", String(open));
}

function openOwnerNavSection(section) {
  ["analytics", "menu", "stock", "finance", "access", "settings"].forEach((name) => setOwnerNavSection(name, name === section));
}

function setMenuSubnav(open) {
  setOwnerNavSection("menu", open);
}

function syncOwnerNavigation(view) {
  if (currentRole !== "owner") return;
  const section = ownerNavSectionByView[view] || "";
  document.querySelectorAll("[data-nav-section]").forEach((button) => button.classList.toggle("active", button.dataset.navSection === section));
  document.querySelectorAll("[data-owner-access-view]").forEach((button) => button.classList.toggle("active", button.dataset.ownerAccessView === view));
  document.querySelectorAll("[data-owner-view]").forEach((button) => button.classList.toggle("active", button.dataset.ownerView === view));
  openOwnerNavSection(section);
}

function switchView(view) {
  if (!canAccessView(view)) view = defaultRoleRoute().split("/")[0];
  if (view === "dashboard") renderDashboard();
  document.querySelectorAll(".admin-view").forEach((section) => section.classList.toggle("active", section.id === `view-${view}`));
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  syncOwnerNavigation(view);
  const activeButton = document.querySelector(`.nav-item[data-view="${view}"]`);
  const viewTitle = {
    dashboard: "Главная",
    reports: "Статистика",
    logistics: "Склад / Производство",
    inventory: "Склад / Остатки",
    finance: "Финансы / Прибыль и убытки",
    branches: "Доступ / Заведения",
    registers: "Доступ / Кассы",
    employees: "Доступ / Сотрудники",
    settings: "Настройки"
  }[view];
  $("#breadcrumbTitle").textContent = viewTitle || activeButton?.textContent.trim() || "Главная";
  if (view === "recipes") {
    const menuPage = document.querySelector("[data-menu-page].active")?.dataset.menuPage || "recipes";
    history.replaceState(null, "", `#menu/${menuPage}`);
  } else if (view === "reports") history.replaceState(null, "", `#reports/${activeAnalyticsTab}`);
  else if (view === "finance") history.replaceState(null, "", `#finance/${activeFinanceTab}`);
  else history.replaceState(null, "", `#${view}`);
  if (view === "settings") window.CompanySettings.open(window.CompanySettings.currentTab);
  document.querySelector(".admin-content")?.scrollTo(0, 0);
}

const menuPageConfig = {
  products: { title: "Товары", description: "Готовые позиции, которые закупаются и продаются без приготовления", action: "Добавить товар" },
  recipes: { title: "Технологические карты", description: "Блюда, которые готовятся по рецепту и продаются гостям", action: "Добавить тех. карту" },
  preparations: { title: "Полуфабрикаты", description: "Заготовки из ингредиентов, которые используются в составе блюд", action: "Добавить полуфабрикат" },
  ingredients: { title: "Ингредиенты", description: "Сырьё, из которого готовятся блюда и полуфабрикаты", action: "Добавить ингредиент" },
  "menu-categories": { title: "Категории товаров и тех. карт", description: "Структура продаваемого меню, которую кассир видит на терминале", action: "Добавить категорию" },
  "ingredient-categories": { title: "Категории ингредиентов", description: "Группы сырья для складского учёта и инвентаризации", action: "Добавить категорию" },
  stations: { title: "Цеха", description: "Места приготовления, склады списания и печать заказов", action: "Добавить цех" }
};

function switchMenuPage(page) {
  const config = menuPageConfig[page] || menuPageConfig.recipes;
  if (!$("#view-recipes").classList.contains("active")) switchView("recipes");
  document.querySelectorAll(".menu-pane").forEach((pane) => pane.classList.toggle("active", pane.id === `menu-pane-${page}`));
  document.querySelectorAll("[data-menu-page]").forEach((button) => button.classList.toggle("active", button.dataset.menuPage === page));
  $("#menuPageTitle").textContent = config.title;
  $("#menuPageDescription").textContent = config.description;
  $("#menuPageActionButton").innerHTML = `${uiIcon("plus")}${escapeHtml(config.action)}`;
  $("#menuPageActionButton").dataset.menuAction = page;
  $("#breadcrumbTitle").textContent = `Меню / ${config.title}`;
  history.replaceState(null, "", `#menu/${page}`);
}

function showToast(message) {
  const toast = $("#adminToast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 2800);
}

function renderAll() {
  renderNotifications();
  if (currentRole === "branch") {
    if (canAccessView("reports")) renderReports();
    if (canAccessView("recipes")) {
      renderRecipes();
      renderProducts();
      renderPreparations();
      renderIngredientsMenu();
      renderMenuCategories();
    }
    if (canAccessView("inventory")) {
      renderStock("branch");
      const activeStockTab = document.querySelector("[data-stock-tab].active")?.dataset.stockTab;
      if (activeStockTab && activeStockTab !== "overview") renderDocuments(activeStockTab);
    }
    if (canAccessView("logistics")) renderLogistics();
    if (canAccessView("finance")) renderFinance();
    if (canAccessView("employees")) renderEmployees();
    if (canAccessView("registers")) renderRegisters();
    return;
  }
  renderDashboard();
  renderBranches();
  renderRegisters();
  renderEmployees();
  renderRecipes();
  renderProducts();
  renderPreparations();
  renderIngredientsMenu();
  renderMenuCategories();
  renderStock("branch");
  renderFinance();
  renderReports();
  renderLogistics();
  const activeStockTab = document.querySelector("[data-stock-tab].active")?.dataset.stockTab;
  if (activeStockTab === "suppliers") renderSuppliers();
  else if (activeStockTab && activeStockTab !== "overview") renderDocuments(activeStockTab);
}

$("#notificationButton").addEventListener("click", () => {
  const panel = $("#notificationPanel");
  const willOpen = panel.classList.contains("hidden");
  panel.classList.toggle("hidden", !willOpen);
  $("#notificationButton").setAttribute("aria-expanded", String(willOpen));
  if (willOpen) renderNotifications();
});
$("#markNotificationsRead").addEventListener("click", () => {
  buildNotifications().forEach((notification) => readNotificationIds.add(notification.id));
  saveReadNotificationIds();
  renderNotifications();
});
$("#notificationList").addEventListener("click", (event) => {
  const button = event.target.closest("[data-notification-id]");
  if (!button) return;
  readNotificationIds.add(button.dataset.notificationId);
  saveReadNotificationIds();
  closeNotifications();
  const notification = buildNotifications().find(entry => entry.id === button.dataset.notificationId);
  routeRoleWorkspace(button.dataset.notificationRoute);
  if (notification?.custodyId) {
    $("#productionBranchSelect").value = notification.branchId;
    openCustodyJournal(notification.custodyId);
  }
  renderNotifications();
});
document.addEventListener("click", (event) => {
  if (!$("#notificationCenter").contains(event.target)) closeNotifications();
});
window.addEventListener("storage", (event) => {
  if (serverMode) return;
  if (event.key === branchesKey) {
    branches = loadBranches();
    logisticsState = loadLogisticsState();
    suppliers = loadSuppliers();
    renderOwnerObjectSelector();
  } else if (event.key === accessAccountsKey) {
    if (!checkCurrentBranchAccess()) return;
  } else if (event.key === logisticsKey) logisticsState = loadLogisticsState();
  else if (event.key === stateKey) ingredients = loadIngredients();
  else if (event.key === productsKey) products = loadProducts();
  else if (event.key === documentsKey) stockDocuments = loadDocuments();
  else if (event.key === suppliersKey) suppliers = loadSuppliers();
  else if (event.key === financeKey) financeState = loadFinanceState();
  else if (event.key === notificationReadKey) readNotificationIds = loadReadNotificationIds();
  else return;
  renderAll();
});

// Close the previous workspace before submenu handlers change the section.
$("#mobileWorkspaceSelect").addEventListener("change", (event) => {
  // Reuse permitted navigation targets and their existing handlers, including
  // closing an editor before changing sections. Recheck access on every change.
  const choice = mobileWorkspaceChoices().find((entry) => entry.value === event.target.value);
  if (choice) choice.button.click();
  renderMobileWorkspaceNavigation();
});
new MutationObserver(renderMobileWorkspaceNavigation).observe($("#mainNav"), {
  subtree: true, attributes: true, attributeFilter: ["class", "hidden", "disabled"]
});

$("#mainNav").addEventListener("click", (event) => {
  if (!event.target.closest("button")) return;
  document.querySelectorAll(".modal-backdrop:not(.hidden), .side-drawer-backdrop:not(.hidden)").forEach((workspace) => workspace.classList.add("hidden"));
}, { capture: true });

$("#mainNav").addEventListener("click", (event) => {
  const roleButton = event.target.closest("[data-role-route]");
  if (roleButton) { routeRoleWorkspace(roleButton.dataset.roleRoute); return; }
  const sectionButton = event.target.closest("[data-nav-section]");
  if (sectionButton) {
    const section = sectionButton.dataset.navSection;
    const currentView = document.querySelector(".admin-view.active")?.id.replace("view-", "") || "dashboard";
    if (ownerNavSectionByView[currentView] === section) {
      const submenuId = { analytics: "analyticsNavSubmenu", menu: "menuSubnav", stock: "stockNavSubmenu", finance: "financeNavSubmenu", access: "accessNavSubmenu", settings: "settingsNavSubmenu" }[section];
      setOwnerNavSection(section, !sectionButton.closest(".role-navigation").querySelector(`#${submenuId}`).classList.contains("visible"));
      return;
    }
    if (section === "analytics") { switchView("reports"); switchAnalyticsTab(activeAnalyticsTab); }
    else if (section === "menu") switchMenuPage(document.querySelector("[data-menu-page].active")?.dataset.menuPage || "recipes");
    else if (section === "stock") { switchView("inventory"); switchStockTab(document.querySelector("[data-owner-stock-tab].active")?.dataset.ownerStockTab || "overview"); }
    else if (section === "finance") { switchView("finance"); switchFinanceTab(activeFinanceTab); }
    else if (section === "access") switchView("registers");
    else if (section === "settings") switchView("settings");
    return;
  }
  const button = event.target.closest("[data-view]");
  if (!button) return;
  switchView(button.dataset.view);
});
$("#menuSubnav").addEventListener("click", (event) => {
  const button = event.target.closest("[data-menu-page]");
  if (button) switchMenuPage(button.dataset.menuPage);
});
$("#analyticsNavSubmenu").addEventListener("click", (event) => {
  const button = event.target.closest("[data-owner-analytics-tab]");
  if (!button) return;
  switchView("reports");
  switchAnalyticsTab(button.dataset.ownerAnalyticsTab);
});
$("#stockNavSubmenu").addEventListener("click", (event) => {
  const viewButton = event.target.closest("[data-owner-view]");
  if (viewButton) { switchView(viewButton.dataset.ownerView); return; }
  const button = event.target.closest("[data-owner-stock-tab]");
  if (!button) return;
  switchView("inventory");
  switchStockTab(button.dataset.ownerStockTab);
});
$("#financeNavSubmenu").addEventListener("click", (event) => {
  const button = event.target.closest("[data-owner-finance-tab]");
  if (!button) return;
  switchView("finance");
  switchFinanceTab(button.dataset.ownerFinanceTab);
});
$("#accessNavSubmenu").addEventListener("click", (event) => {
  const button = event.target.closest("[data-owner-access-view]");
  if (button) switchView(button.dataset.ownerAccessView);
});
document.querySelectorAll("[data-view-jump]").forEach((button) => button.addEventListener("click", () => {
  switchView(button.dataset.viewJump);
  if (button.dataset.viewJump === "inventory") switchStockTab("overview");
}));
$("#view-dashboard").addEventListener("click", (event) => {
  const button = event.target.closest("[data-setup-route]");
  if (!button) return;
  const route = button.dataset.setupRoute;
  if (route === "pos") { openRegisterTerminal(); return; }
  if (route.startsWith("menu/")) { switchView("recipes"); switchMenuPage(route.split("/")[1]); return; }
  if (route.startsWith("inventory/")) { switchView("inventory"); switchStockTab(route.split("/")[1]); return; }
  switchView(route);
});
$("#analyticsTabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-analytics-tab]");
  if (button) switchAnalyticsTab(button.dataset.analyticsTab);
});
$("#financeTabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-finance-tab]");
  if (button) switchFinanceTab(button.dataset.financeTab);
});
$("#financePeriodPreset").addEventListener("change", () => { setFinancePeriod($("#financePeriodPreset").value); renderFinance(); });
[$("#financeDateFrom"), $("#financeDateTo"), $("#financeBranchFilter")].forEach((input) => input.addEventListener("change", () => {
  if (input !== $("#financeBranchFilter")) $("#financePeriodPreset").value = "custom";
  if ($("#financeDateFrom").value > $("#financeDateTo").value) $("#financeDateTo").value = $("#financeDateFrom").value;
  renderFinance();
}));
[$("#financeTransactionSearch"), $("#financeTransactionTypeFilter"), $("#financeTransactionAccountFilter")].forEach((input) => input.addEventListener(input.tagName === "INPUT" ? "input" : "change", () => renderFinanceTransactions(financeContext())));
$("#openFinanceTransactionButton").addEventListener("click", openFinanceTransactionForm);
$("#financeTransactionType").addEventListener("change", updateFinanceTransactionForm);
$("#financeTransactionAccount").addEventListener("change", syncFinanceTransactionBranch);
$("#saveFinanceTransactionButton").addEventListener("click", saveFinanceTransaction);
$("#exportFinanceButton").addEventListener("click", exportFinanceCsv);
$("#addFinanceAccountButton").addEventListener("click", () => openFinanceAccountForm());
$("#saveFinanceAccountButton").addEventListener("click", saveFinanceAccount);
$("#saveFinanceCategoryButton").addEventListener("click", saveFinanceCategory);
$("#view-finance").addEventListener("click", (event) => {
  const deleteButton = event.target.closest("[data-delete-finance-transaction]");
  if (deleteButton) { deleteFinanceTransaction(deleteButton.dataset.deleteFinanceTransaction); return; }
  const accountButton = event.target.closest("[data-edit-finance-account]");
  if (accountButton) { openFinanceAccountForm(accountButton.dataset.editFinanceAccount); return; }
  const categoryButton = event.target.closest("[data-edit-finance-category]");
  if (categoryButton) { openFinanceCategoryForm("expense", categoryButton.dataset.editFinanceCategory); return; }
  const addCategoryButton = event.target.closest("[data-add-finance-category]");
  if (addCategoryButton) openFinanceCategoryForm(addCategoryButton.dataset.addFinanceCategory);
});
$("#reportPeriodPreset").addEventListener("change", () => {
  setReportPeriod($("#reportPeriodPreset").value);
  renderReports();
});
[$("#reportDateFrom"), $("#reportDateTo")].forEach((input) => input.addEventListener("change", () => {
  $("#reportPeriodPreset").value = "custom";
  if ($("#reportDateFrom").value > $("#reportDateTo").value) $("#reportDateTo").value = $("#reportDateFrom").value;
  renderReports();
}));
$("#reportBranchFilter").addEventListener("change", renderReports);
$("#reportGroupBy").addEventListener("change", renderAnalyticsSales);
$("#abcSearch").addEventListener("input", renderABC);
$("#abcTypeFilter").addEventListener("change", renderABC);
$("#abcCategoryFilter").addEventListener("change", renderABC);
$("#receiptSearch").addEventListener("input", renderReceipts);
$("#receiptPaymentFilter").addEventListener("change", renderReceipts);
$("#receiptCashierFilter").addEventListener("change", renderReceipts);
$("#receiptStatusFilter").addEventListener("change", renderReceipts);
$("#receiptsTable").addEventListener("click", (event) => {
  const target = event.target.closest("[data-receipt-open]");
  if (target) {
    expandedReceiptId = expandedReceiptId === target.dataset.receiptOpen ? null : target.dataset.receiptOpen;
    expandedReceiptTab = "bill";
    renderReceipts();
  }
  const tab = event.target.closest("[data-receipt-tab]");
  if (tab) { expandedReceiptTab = tab.dataset.receiptTab; renderReceipts(); }
});
$("#exportAnalyticsButton").addEventListener("click", exportAnalyticsCsv);
$("#printAnalyticsButton").addEventListener("click", () => {
  document.body.classList.add("print-analytics");
  window.print();
  setTimeout(() => document.body.classList.remove("print-analytics"), 100);
});
$("#recipeSearch").addEventListener("input", renderRecipes);
$("#recipeCategory").addEventListener("change", renderRecipes);
$("#recipeStationFilter").addEventListener("change", renderRecipes);
$("#productSearch").addEventListener("input", renderProducts);
$("#productsTable").addEventListener("click", (event) => {
  const button = event.target.closest("[data-product-edit]");
  if (button) openProductForm(button.dataset.productEdit);
});
$("#preparationSearch").addEventListener("input", renderPreparations);
$("#preparationCategoryFilter").addEventListener("change", renderPreparations);
$("#preparationsTable").addEventListener("click", (event) => {
  const button = event.target.closest("[data-preparation-edit]");
  if (button) { openPreparationForm(button.dataset.preparationEdit); return; }
  const compose = event.target.closest('[data-preparation-compose]');
  if (compose) { openPreparationComposition(compose.dataset.preparationCompose); return; }
  const row = event.target.closest('[data-preparation-id]');
  if (row && !window.getSelection()?.toString()) openPreparationComposition(row.dataset.preparationId);
});
$('#closePreparationComposition').addEventListener('click', closePreparationComposition);
$('#preparationCompositionDone').addEventListener('click', closePreparationComposition);
$('#editPreparationComposition').addEventListener('click', () => openPreparationForm(currentPreparationId));
$('#preparationCompositionDrawer').addEventListener('click', event => { if (event.target === $('#preparationCompositionDrawer')) closePreparationComposition(); });
$("#ingredientSearch").addEventListener("input", renderIngredientsMenu);
$("#ingredientsTable").addEventListener("click", (event) => {
  const button = event.target.closest("[data-ingredient-edit]");
  if (button) openIngredientForm(button.dataset.ingredientEdit);
});
$("#menuCategoriesTable").addEventListener("click", (event) => {
  const button = event.target.closest("[data-menu-category-edit]");
  if (button) openCategoryForm("menu", button.dataset.menuCategoryEdit);
});
$("#ingredientCategoriesTable").addEventListener("click", (event) => {
  const button = event.target.closest("[data-ingredient-category-edit]");
  if (button) openCategoryForm("ingredient", button.dataset.ingredientCategoryEdit);
});
$("#stationsTable").addEventListener("click", (event) => {
  const button = event.target.closest("[data-station-edit]");
  if (button) openStationForm(button.dataset.stationEdit);
});
$("#stockSearch").addEventListener("input", renderStock);
$("#stockCategoryFilter").addEventListener("change", renderStock);
$("#documentSearch").addEventListener("input", () => renderDocuments(activeDocumentFilterTab || "supplies"));
[$("#documentDateFrom"), $("#documentDateTo"), $("#documentPartyFilter"), $("#documentStatusFilter")].forEach((control) => control.addEventListener("change", () => renderDocuments(activeDocumentFilterTab || "supplies")));
$("#resetDocumentFilters").addEventListener("click", () => {
  $("#documentSearch").value = "";
  $("#documentDateFrom").value = "";
  $("#documentDateTo").value = "";
  $("#documentPartyFilter").value = "all";
  $("#documentStatusFilter").value = "all";
  renderDocuments(activeDocumentFilterTab || "supplies");
});
$("#supplierSearch").addEventListener("input", renderSuppliers);
$("#supplierStatusFilter").addEventListener("change", renderSuppliers);
$("#addSupplierButton").addEventListener("click", () => openSupplierForm());
$("#suppliersTable").addEventListener("click", (event) => {
  const button = event.target.closest("[data-supplier-edit]");
  if (button) openSupplierForm(button.dataset.supplierEdit);
});
$("#createBranchButton").addEventListener("click", openBranchForm);
$("#branchLoginInput").addEventListener("input", () => { branchLoginEdited = true; });
$("#generateBranchPasswordButton").addEventListener("click", () => { $("#branchPasswordInput").value = generateTemporaryPassword(); });
$("#saveBranchButton").addEventListener("click", saveBranch);
$("#branchCards").addEventListener("click", (event) => {
  const editButton = event.target.closest("[data-edit-branch]");
  if (editButton) { openBranchForm(editButton.dataset.editBranch); return; }
  const managerButton = event.target.closest("[data-manage-branch]");
  if (managerButton) {
    switchView("employees");
    openEmployeeForm(null, managerButton.dataset.manageBranch);
  }
});
$("#copyBranchAccessButton").addEventListener("click", async () => {
  const details = lastBranchAccessText || `${$("#branchAccessTitle").textContent}\nЛогин: ${$("#createdBranchLogin").textContent}`;
  try {
    await navigator.clipboard.writeText(details);
    showToast("Данные доступа скопированы");
  } catch {
    showToast("Не удалось скопировать — выделите логин и пароль вручную");
  }
});
$("#addRegisterButton").addEventListener("click", () => openRegisterForm());
$("#registersTable").addEventListener("click", (event) => {
  const openButton = event.target.closest("[data-open-register]");
  if (openButton) { openRegisterTerminal(openButton.dataset.openRegister); return; }
  const editButton = event.target.closest("[data-edit-register]");
  if (editButton) { openRegisterForm(editButton.dataset.editRegister); return; }
  const logoutButton = event.target.closest("[data-logout-register]");
  if (logoutButton) forceRegisterLogout(logoutButton.dataset.logoutRegister);
});
$("#cashierLink").addEventListener("click", (event) => { event.preventDefault(); openRegisterTerminal(); });
$("#openCreatedRegisterButton").addEventListener("click", (event) => openRegisterTerminal(event.currentTarget.dataset.registerId, event.currentTarget.dataset.accountLogin));
$("#registerBranchInput").addEventListener("change", () => {
  const branch = branchById($("#registerBranchInput").value);
  $("#registerWarehouseInput").value = branch ? `Склад · ${branch.name}` : "—";
});
$("#generateRegisterPasswordButton").addEventListener("click", () => { $("#registerPasswordInput").value = generateTemporaryPassword(); });
$("#saveRegisterButton").addEventListener("click", saveRegister);
$("#copyRegisterAccessButton").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(lastRegisterAccessText); showToast("Данные кассы скопированы"); }
  catch { showToast("Не удалось скопировать — выделите данные вручную"); }
});
$("#addEmployeeButton").addEventListener("click", () => openEmployeeForm());
[$("#employeeSearch"), $("#employeeRoleFilter"), $("#employeeStatusFilter")].forEach((control) => control.addEventListener(control.tagName === "INPUT" ? "input" : "change", renderEmployees));
$("#employeesTable").addEventListener("click", async event => {
  const button = event.target.closest("[data-employee-pin]"); if (!button) return;
  const id = Number(button.dataset.employeePin), employee = employees.find(row => Number(row.id) === id);
  if (!employee) return;
  if (!employee.can_reveal_pin) { openEmployeeForm(id); $("#employeePinInput").focus(); $("#employeePinHint").textContent = "Старый PIN восстановить нельзя. Введите новый и сохраните изменения."; return; }
  const value = button.parentNode.querySelector("[data-employee-pin-value]");
  if (value.textContent) { value.textContent = ""; button.textContent = "Показать PIN"; return; }
  button.disabled = true;
  try {
    const result = await window.AshkanaApi.revealEmployeePin(id);
    if (!result.pin) { showToast("Назначьте новый PIN в настройках сотрудника"); return; }
    value.textContent = result.pin; button.textContent = "Скрыть PIN";
    setTimeout(() => { value.textContent = ""; button.textContent = "Показать PIN"; }, 30000);
  } catch (error) { showToast(error.message || "Не удалось показать PIN"); }
  finally { button.disabled = false; }
});
$("#employeesTable").addEventListener("click", (event) => {
  const remove = event.target.closest('[data-delete-employee]');
  if (remove) { openEmployeeDelete(remove.dataset.deleteEmployee, remove); return; }
  const button = event.target.closest("[data-edit-employee]");
  if (button) openEmployeeForm(button.dataset.editEmployee);
});
$('#deleteEmployeeButton').addEventListener('click', event => openEmployeeDelete(editingEmployeeId, event.currentTarget));
$('#confirmEmployeeDelete').addEventListener('click', confirmEmployeeDelete);
$('#cancelEmployeeDelete').addEventListener('click', closeEmployeeDelete);
$('#closeEmployeeDelete').addEventListener('click', closeEmployeeDelete);
$('#employeeDeleteDialog').addEventListener('cancel', event => { if (deletingEmployee) event.preventDefault(); });
$('#employeeDeleteDialog').addEventListener('close', () => {
  pendingEmployeeDeleteId = null;
  const target = employeeDeleteTrigger?.isConnected && employeeDeleteTrigger.getClientRects().length ? employeeDeleteTrigger : $('#addEmployeeButton');
  target.focus({preventScroll:true});
  employeeDeleteTrigger = null;
});
$("#employeeNameInput").addEventListener("input", () => {
  if (!employeeLoginEdited) $("#employeeLoginInput").value = slugifyBranchLogin($("#employeeNameInput").value).replace(/-/g, ".");
});
$("#employeeLoginInput").addEventListener("input", () => { employeeLoginEdited = true; });
$("#employeeRoleInput").addEventListener("change", () => {
  setEmployeePermissions(employeePermissionDefaults[$("#employeeRoleInput").value]);
  updateEmployeePermissionNote();
});
$("#resetEmployeePermissions").addEventListener("click", () => {
  setEmployeePermissions(employeePermissionDefaults[$("#employeeRoleInput").value]);
  updateEmployeePermissionNote();
});
document.querySelectorAll("[data-employee-permission]").forEach((input) => input.addEventListener("change", updateEmployeePermissionNote));
$("#generateEmployeePasswordButton").addEventListener("click", () => { $("#employeePasswordInput").value = generateTemporaryPassword(); });
$("#generateEmployeePinButton").addEventListener("click", () => { $("#employeePinInput").value = generateEmployeePin(); });
$("#employeePinInput").addEventListener("input", (event) => { event.target.value = event.target.value.replace(/\D/g, "").slice(0, 4); });
$("#saveEmployeeButton").addEventListener("click", saveEmployee);
$("#copyEmployeeAccessButton").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(lastEmployeeAccessText);
    showToast("Данные доступа скопированы");
  } catch {
    showToast("Не удалось скопировать — выделите данные вручную");
  }
});
$("#stockTabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-stock-tab]");
  if (button) switchStockTab(button.dataset.stockTab);
});
$("#productionTabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-production-tab]");
  if (button) switchProductionTab(button.dataset.productionTab);
});
$("#openBatchButton").addEventListener("click", () => openBatchForm());
$("#productionBranchSelect").addEventListener("change", () => { renderProductionRecord(); renderProductionJournal(); });
$("#productionSearch").addEventListener("input", renderProductionRecord);
$("#productionStationFilter").addEventListener("change", renderProductionRecord);
$("#productionRecordTable").addEventListener("click", (event) => {
  const produceButton = event.target.closest("[data-plan-batch]");
  if (produceButton) { openBatchForm(Number(produceButton.dataset.planBatch), $("#productionBranchSelect").value); return; }
  const transferButton = event.target.closest("[data-serving-transfer]");
  if (transferButton) { openServingTransfer(transferButton.dataset.servingTransfer); return; }
  const closeButton = event.target.closest("[data-serving-close]");
  if (closeButton) openServingClose(closeButton.dataset.servingClose);
});
$("#documentsTableBody").addEventListener("click", (event) => {
  const inventoryButton = event.target.closest("[data-open-inventory-document]");
  if (inventoryButton) { openInventoryDocument(inventoryButton.dataset.openInventoryDocument); return; }
  const approveButton = event.target.closest("[data-approve-request]");
  if (approveButton) { approveRequest(approveButton.dataset.approveRequest); return; }
  const dispatchButton = event.target.closest("[data-dispatch-request]");
  if (dispatchButton) { dispatchRequest(dispatchButton.dataset.dispatchRequest); return; }
  const receiveButton = event.target.closest("[data-receive-request]");
  if (receiveButton) { openReceiving(receiveButton.dataset.receiveRequest); return; }
  const approvePointTransferButton = event.target.closest("[data-approve-point-transfer]");
  if (approvePointTransferButton) { approvePointTransfer(approvePointTransferButton.dataset.approvePointTransfer); return; }
  const dispatchPointTransferButton = event.target.closest("[data-dispatch-point-transfer]");
  if (dispatchPointTransferButton) { dispatchPointTransfer(dispatchPointTransferButton.dataset.dispatchPointTransfer); return; }
  const receivePointTransferButton = event.target.closest("[data-receive-point-transfer]");
  if (receivePointTransferButton) { openPointTransferReceiving(receivePointTransferButton.dataset.receivePointTransfer); return; }
  const approveDirectButton = event.target.closest("[data-approve-direct-order]");
  if (approveDirectButton) { approveDirectOrder(approveDirectButton.dataset.approveDirectOrder); return; }
  const openDirectSendButton = event.target.closest("[data-open-direct-send]");
  if (openDirectSendButton) { openDirectOrderSend(openDirectSendButton.dataset.openDirectSend); return; }
  const printDirectButton = event.target.closest("[data-print-direct-order]");
  if (printDirectButton) { openDirectOrderPrint(printDirectButton.dataset.printDirectOrder); return; }
  const receiveDirectButton = event.target.closest("[data-receive-direct-order]");
  if (receiveDirectButton) openDirectReceiving(receiveDirectButton.dataset.receiveDirectOrder);
});
$("#addRequestItemButton").addEventListener("click", () => {
  syncRequestDraft();
  requestDraftItems.push({ itemId: ingredients[0]?.id, quantity: 1 });
  renderRequestItemsEditor();
});
$("#requestItemsEditor").addEventListener("change", (event) => {
  if (!event.target.matches(".request-item-product")) return;
  syncRequestDraft();
  renderRequestItemsEditor();
});
$("#requestItemsEditor").addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-request-item]");
  if (!button) return;
  syncRequestDraft();
  requestDraftItems.splice(Number(button.dataset.removeRequestItem), 1);
  renderRequestItemsEditor();
});
$("#saveRequestButton").addEventListener("click", saveRequest);
$("#addDirectOrderItemButton").addEventListener("click", () => {
  syncDirectOrderDraft();
  const usedIds = new Set(directOrderDraftItems.map((item) => item.itemId));
  const stockEntities = [...ingredients, ...products];
  const entity = stockEntities.find((entry) => !usedIds.has(entry.id)) || stockEntities[0];
  if (!entity) return;
  const branchId = $("#directOrderBranch").value;
  const supplier = supplierById($("#directOrderSupplier").value);
  directOrderDraftItems.push({ itemId: entity.id, quantity: 1, price: directSupplierPrice(supplier, branchId, entity.id) });
  renderDirectOrderItemsEditor();
  updateDirectOrderCalculation();
});
$("#directOrderSupplier").addEventListener("change", () => {
  syncDirectOrderDraft();
  const branchId = $("#directOrderBranch").value;
  const supplier = supplierById($("#directOrderSupplier").value);
  directOrderDraftItems = directOrderDraftItems.map((item) => ({ ...item, price: directSupplierPrice(supplier, branchId, item.itemId) }));
  renderDirectOrderItemsEditor();
  updateDirectOrderCalculation();
});
$("#directOrderItemsEditor").addEventListener("input", updateDirectOrderCalculation);
$("#directOrderItemsEditor").addEventListener("change", (event) => {
  if (!event.target.matches(".direct-order-item-product")) return;
  const row = event.target.closest(".direct-order-item-row");
  const branchId = $("#directOrderBranch").value;
  const supplier = supplierById($("#directOrderSupplier").value);
  row.querySelector(".direct-order-item-price").value = directSupplierPrice(supplier, branchId, event.target.value);
  updateDirectOrderCalculation();
});
$("#directOrderItemsEditor").addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-direct-order-item]");
  if (!button) return;
  syncDirectOrderDraft();
  directOrderDraftItems.splice(Number(button.dataset.removeDirectOrderItem), 1);
  renderDirectOrderItemsEditor();
  updateDirectOrderCalculation();
});
$("#saveDirectOrderButton").addEventListener("click", saveDirectOrder);
$("#directReceivingItemsEditor").addEventListener("input", updateDirectReceivingCalculation);
$("#saveDirectReceivingButton").addEventListener("click", saveDirectReceiving);
$("#pointTransferSource").addEventListener("change", () => {
  syncPointTransferDraft();
  renderPointTransferItemsEditor();
  updatePointTransferCalculation();
});
$("#addPointTransferItemButton").addEventListener("click", () => {
  syncPointTransferDraft();
  const usedIds = new Set(pointTransferDraftItems.map((item) => item.itemId));
  const sourceBranchId = $("#pointTransferSource").value;
  const entities = [...ingredients, ...products];
  const entity = entities.find((entry) => !usedIds.has(entry.id) && branchStock(sourceBranchId, entry.id) > 0) || entities.find((entry) => !usedIds.has(entry.id)) || entities[0];
  if (!entity) return;
  pointTransferDraftItems.push({ itemId: entity.id, quantity: 1 });
  renderPointTransferItemsEditor();
  updatePointTransferCalculation();
});
$("#pointTransferItemsEditor").addEventListener("input", updatePointTransferCalculation);
$("#pointTransferItemsEditor").addEventListener("change", (event) => {
  if (!event.target.matches(".point-transfer-item-product")) return;
  updatePointTransferCalculation();
});
$("#pointTransferItemsEditor").addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-point-transfer-item]");
  if (!button) return;
  syncPointTransferDraft();
  pointTransferDraftItems.splice(Number(button.dataset.removePointTransferItem), 1);
  renderPointTransferItemsEditor();
  updatePointTransferCalculation();
});
$("#savePointTransferButton").addEventListener("click", savePointTransfer);
$("#pointTransferReceivingItems").addEventListener("input", updatePointTransferReceivingCalculation);
$("#savePointTransferReceivingButton").addEventListener("click", savePointTransferReceiving);
$("#receivingItemsEditor").addEventListener("input", updateReceivingVariance);
$("#saveReceivingButton").addEventListener("click", saveReceiving);
$("#batchBranch").addEventListener("change", updateBatchCalculation);
$("#batchRecipe").addEventListener("change", updateBatchCalculation);
$("#batchWeight").addEventListener("input", updateBatchCalculation);
$("#saveBatchButton").addEventListener("click", saveBatch);
$("#servingTransferWeight").addEventListener("input", updateServingTransferCalculation);
$("#saveServingTransferButton").addEventListener("click", saveServingTransfer);
$("#servingSoldPortions").addEventListener("input", updateServingCloseBalance);
$("#servingRemainingWeight").addEventListener("input", updateServingCloseBalance);
$("#saveServingCloseButton").addEventListener("click", saveServingClose);
$("#recipesTable").addEventListener("click", (event) => {
  const editButton = event.target.closest("[data-recipe-edit]");
  if (editButton) {
    event.stopPropagation();
    openRecipeForm(Number(editButton.dataset.recipeEdit));
    return;
  }
  const compositionButton = event.target.closest("[data-recipe-compose]");
  if (compositionButton) {
    event.stopPropagation();
    openRecipe(Number(compositionButton.dataset.recipeCompose));
    return;
  }
  const row = event.target.closest("[data-recipe-id]");
  if (row) openRecipe(Number(row.dataset.recipeId));
});
$("#recipeDrawer").addEventListener("click", (event) => { if (event.target === $("#recipeDrawer")) $("#recipeDrawer").classList.add("hidden"); });
$(".drawer-close").addEventListener("click", () => $("#recipeDrawer").classList.add("hidden"));
$(".drawer-save").addEventListener("click", () => { $("#recipeDrawer").classList.add("hidden"); showToast("Техкарта сохранена"); });
$("#editRecipeButton").addEventListener("click", () => openRecipeForm(currentRecipeId));
$("#menuPageActionButton").addEventListener("click", () => {
  const action = $("#menuPageActionButton").dataset.menuAction || "recipes";
  if (action === "recipes") openRecipeForm();
  else if (action === "preparations") openPreparationForm();
  else if (action === "ingredients") openIngredientForm();
  else if (action === "products") openProductForm();
  else if (action === "menu-categories") openCategoryForm("menu");
  else if (action === "ingredient-categories") openCategoryForm("ingredient");
  else if (action === "stations") openStationForm();
  else {
    const label = menuPageConfig[action]?.title || "позиции";
    showToast(`Форма «Добавить: ${label}» откроется в следующем шаге`);
  }
});
$("#addComponentButton").addEventListener("click", () => {
  syncRecipeDraftFromEditor();
  recipeDraftComponents.push({ ingredientId: ingredients[0]?.id, gross: 0, net: 0 });
  renderRecipeComponentsEditor();
});
$("#recipeComponentsEditor").addEventListener("input", updateRecipeLiveCalculation);
$("#recipeComponentsEditor").addEventListener("change", (event) => {
  syncRecipeDraftFromEditor();
  if (event.target.matches(".component-ingredient")) renderRecipeComponentsEditor();
  else updateRecipeLiveCalculation();
});
$("#recipeComponentsEditor").addEventListener("click", (event) => {
  const button = event.target.closest(".remove-component");
  if (!button) return;
  const row = button.closest("[data-component-index]");
  syncRecipeDraftFromEditor();
  recipeDraftComponents.splice(Number(row.dataset.componentIndex), 1);
  renderRecipeComponentsEditor();
});
$("#recipePriceInput").addEventListener("input", updateRecipeLiveCalculation);
$("#saveRecipeButton").addEventListener("click", saveRecipeForm);
$("#deleteRecipeButton").addEventListener("click", () => {
  const recipe = recipes.find((entry) => String(entry.id) === String(editingRecipeId));
  if (recipe) requestCatalogDelete("recipe", recipe.id, recipe.name);
});
$("#addPreparationComponentButton").addEventListener("click", () => {
  syncPreparationDraftFromEditor();
  const usedIds = new Set(preparationDraftComponents.map((component) => component.ingredientId));
  const ingredient = ingredients.find((entry) => !usedIds.has(entry.id));
  if (!ingredient) {
    showToast("Все ингредиенты уже добавлены в состав");
    return;
  }
  preparationDraftComponents.push({ ingredientId: ingredient.id, gross: 100, net: 100 });
  renderPreparationComponentsEditor();
});
$("#preparationComponentsEditor").addEventListener("input", updatePreparationCalculation);
$("#preparationComponentsEditor").addEventListener("change", (event) => {
  syncPreparationDraftFromEditor();
  if (event.target.matches(".preparation-component-ingredient")) renderPreparationComponentsEditor();
  else updatePreparationCalculation();
});
$("#preparationComponentsEditor").addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-preparation-component]");
  if (!button) return;
  syncPreparationDraftFromEditor();
  preparationDraftComponents.splice(Number(button.dataset.removePreparationComponent), 1);
  renderPreparationComponentsEditor();
});
$("#preparationYieldInput").addEventListener("input", updatePreparationCalculation);
$("#savePreparationButton").addEventListener("click", savePreparationForm);
$("#deletePreparationButton").addEventListener("click", () => {
  const preparation = preparationById(editingPreparationId);
  if (preparation) requestCatalogDelete("preparation", preparation.id, preparation.name);
});
$("#categoryColorInput").addEventListener("input", () => { $("#categoryColorText").value = $("#categoryColorInput").value.toUpperCase(); });
$("#categoryColorText").addEventListener("input", () => {
  const color = $("#categoryColorText").value.trim();
  if (/^#[0-9a-f]{6}$/i.test(color)) $("#categoryColorInput").value = color;
});
$("#saveCategoryButton").addEventListener("click", saveCategoryForm);
$("#deleteCategoryButton").addEventListener("click", () => {
  if (!editingCategoryName) return;
  requestCatalogDelete(editingCategoryKind === "menu" ? "menu-category" : "ingredient-category", editingCategoryName, editingCategoryName);
});
$("#stationDestinationMode").addEventListener("change", updateStationDestinationField);
$("#saveStationButton").addEventListener("click", saveStationForm);
$("#deleteStationButton").addEventListener("click", () => {
  if (editingStationName) requestCatalogDelete("station", editingStationName, editingStationName);
});
$("#ingredientStockInput").addEventListener("input", updateIngredientOpeningTotal);
$("#ingredientCostInput").addEventListener("input", updateIngredientOpeningTotal);
$("#saveIngredientButton").addEventListener("click", saveIngredientForm);
$("#deleteIngredientButton").addEventListener("click", () => {
  const ingredient = ingredientById(editingIngredientId);
  if (ingredient) requestCatalogDelete("ingredient", ingredient.id, ingredient.name);
});
function renderProductCover() {
  const preview = $("#productCoverPreview");
  preview.style.backgroundColor = $("#productColorInput").value;
  $("#removeProductPhoto").classList.toggle("hidden", !productPhotoDraft);
  preview.replaceChildren();
  if (productPhotoDraft) { const img = document.createElement("img"); img.src = productPhotoDraft; img.alt = "Фото товара"; preview.append(img); }
  else preview.textContent = $("#productNameInput").value.trim().slice(0, 1) || "А";
}
$("#productColorInput").addEventListener("input", renderProductCover);
$("#productNameInput").addEventListener("input", renderProductCover);
$("#removeProductPhoto").addEventListener("click", () => { productPhotoDraft = ""; $("#productPhotoInput").value = ""; renderProductCover(); });
$("#productPhotoInput").addEventListener("change", async event => {
  const file = event.target.files[0]; if (!file) return;
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 2 * 1024 * 1024) { showToast("Выберите JPG, PNG или WebP размером до 2 МБ"); event.target.value = ""; return; }
  const formId = editingProductId;
  try {
    const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
    const img = new Image(); img.src = data; await img.decode();
    const canvas = document.createElement("canvas"), scale = Math.min(1, 640 / Math.max(img.width, img.height));
    canvas.width = Math.max(1, Math.round(img.width * scale)); canvas.height = Math.max(1, Math.round(img.height * scale));
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    if (editingProductId !== formId || event.target.files[0] !== file) return;
    productPhotoDraft = canvas.toDataURL("image/png"); renderProductCover();
  } catch { showToast("Не удалось открыть изображение"); }
});
$("#productMarkupInput").addEventListener("input", () => {
  const cost = Number($("#productCostInput").value || 0), markup = Number($("#productMarkupInput").value);
  if (!Number.isFinite(markup) || markup < -100) return;
  if (cost > 0) $("#productPriceInput").value = Math.round(cost * (1 + markup / 100) * 100) / 100;
});
$("#productCostInput").addEventListener("input", updateProductCalculation);
$("#productPriceInput").addEventListener("input", updateProductCalculation);
$("#productStockInput").addEventListener("input", updateProductCalculation);
$("#saveProductButton").addEventListener("click", () => saveProductForm());
$("#saveProductAndNewButton").addEventListener("click", () => saveProductForm(true));
$("#createProductCategory").addEventListener("click", async () => {
  const button = $("#createProductCategory"); button.disabled = true;
  try { await ensureProductCategory(); } finally { button.disabled = false; }
});
$("#productCategoryInput").addEventListener("change", () => { $("#productCategorySearch").value = $("#productCategoryInput").value; });
$("#deleteProductButton").addEventListener("click", () => {
  const product = productById(editingProductId);
  if (product) requestCatalogDelete("product", product.id, product.name);
});
$("#confirmCatalogDeleteButton").addEventListener("click", confirmCatalogDelete);
function prepareWorkspacePages() {
  const pageBackdrops = document.querySelectorAll(".modal-backdrop:not(.supply-page-backdrop):not(.catalog-delete-backdrop), .side-drawer-backdrop");
  pageBackdrops.forEach((backdrop) => {
    const backButton = backdrop.querySelector(".modal-close, .drawer-close");
    if (backButton) {
      backButton.classList.add("workspace-back");
      backButton.setAttribute("aria-label", "Вернуться назад");
      backButton.innerHTML = uiIcon("arrow");
    }
    new MutationObserver(() => {
      if (backdrop.classList.contains("hidden")) return;
      const workspace = backdrop.querySelector(".admin-modal, .detail-drawer");
      if (workspace) workspace.scrollTop = 0;
    }).observe(backdrop, { attributes: true, attributeFilter: ["class"] });
  });
}
prepareWorkspacePages();
function openSupplyForm() {
  if (!hasRole("owner", "branch")) return;
  if (!branches.length) { showToast("Сначала добавьте заведение"); return; }
  populateSupplyIngredients();
  const branchId = $("#supplyWarehouse").value;
  if (!ensureBranchStockUnlocked(branchId)) return;
  $("#supplyModal").classList.remove("hidden");
  $("#mainNav").scrollTop = 0;
}
document.querySelectorAll("[data-open-supply]").forEach((button) => button.addEventListener("click", openSupplyForm));
document.querySelectorAll("[data-open-inventory]").forEach((button) => button.addEventListener("click", openInventoryForm));
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(`#${button.dataset.close}`).classList.add("hidden")));
document.querySelectorAll(".modal-backdrop").forEach((modal) => modal.addEventListener("click", (event) => { if (event.target === modal) modal.classList.add("hidden"); }));
$("#addSupplyItemButton").addEventListener("click", () => {
  syncSupplyDraft();
  const usedIds = new Set(supplyDraftItems.map((item) => String(item.itemId)));
  const entity = [...ingredients, ...products].find((entry) => !usedIds.has(String(entry.id))) || [...ingredients, ...products][0];
  if (!entity) return;
  supplyDraftItems.push({ itemId: entity.id, quantity: 1, price: branchUnitCost($("#supplyWarehouse").value, entity.id) });
  renderSupplyItemsEditor();
  updateSupplyCalculation();
});
$("#quickAddSupplierButton").addEventListener("click", () => openSupplierForm(null, true));
$("#supplyItemsEditor").addEventListener("input", updateSupplyCalculation);
$("#supplyItemsEditor").addEventListener("change", (event) => {
  if (!event.target.matches(".supply-item-product")) { updateSupplyCalculation(); return; }
  const row = event.target.closest(".supply-item-row");
  const entity = stockEntityById(event.target.value);
  if (entity) row.querySelector(".supply-item-price").value = branchUnitCost($("#supplyWarehouse").value, entity.id);
  updateSupplyCalculation();
});
$("#supplyItemsEditor").addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-supply-item]");
  if (!button) return;
  syncSupplyDraft();
  supplyDraftItems.splice(Number(button.dataset.removeSupplyItem), 1);
  if (!supplyDraftItems.length) {
    const entity = [...ingredients, ...products][0];
    if (entity) supplyDraftItems.push({ itemId: entity.id, quantity: 1, price: branchUnitCost($("#supplyWarehouse").value, entity.id) });
  }
  renderSupplyItemsEditor();
  updateSupplyCalculation();
});
$("#supplyWarehouse").addEventListener("change", () => {
  syncSupplyDraft();
  syncSupplyPayments();
  renderSupplyItemsEditor();
  renderSupplyPayments();
  updateSupplyCalculation();
});
$("#addSupplyPaymentButton").addEventListener("click", () => {
  syncSupplyPayments();
  const accounts = supplyPaymentAccounts();
  if (!accounts.length) { showToast("Нет доступного финансового счёта для оплаты"); return; }
  const paid = supplyMoney(supplyDraftPayments.reduce((sum, payment) => sum + Number(payment.amount || 0), 0));
  supplyDraftPayments.push({ accountId: accounts[0].id, occurredAt: $("#supplyReceivedAt").value, amount: Math.max(0, supplyMoney(supplyDocumentAmount() - paid)) });
  renderSupplyPayments();
});
$("#supplyPaymentEditor").addEventListener("input", updateSupplyPaymentCalculation);
$("#supplyPaymentEditor").addEventListener("change", updateSupplyPaymentCalculation);
$("#supplyPaymentEditor").addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-supply-payment]");
  if (!button) return;
  syncSupplyPayments();
  supplyDraftPayments.splice(Number(button.dataset.removeSupplyPayment), 1);
  renderSupplyPayments();
});
$("#saveSupplyButton").addEventListener("click", saveSupply);
$("#printSupplyButton").addEventListener("click", printSupplyDraft);
$("#supplyImportInput").addEventListener("change", (event) => {
  importSupplyCsv(event.target.files?.[0]);
  event.target.value = "";
});
$("#supplyImportZone").addEventListener("dragover", (event) => {
  event.preventDefault();
  event.currentTarget.classList.add("dragover");
});
$("#supplyImportZone").addEventListener("dragleave", (event) => event.currentTarget.classList.remove("dragover"));
$("#supplyImportZone").addEventListener("drop", (event) => {
  event.preventDefault();
  event.currentTarget.classList.remove("dragover");
  importSupplyCsv(event.dataTransfer?.files?.[0]);
});
$("#saveSupplierButton").addEventListener("click", saveSupplier);
$("#printDirectOrderButton").addEventListener("click", () => openDirectOrderPrint());
$("#confirmDirectOrderSendButton").addEventListener("click", confirmDirectOrderSend);
$("#writeoffIngredient").addEventListener("change", updateWriteoffCalculation);
$("#writeoffQuantity").addEventListener("input", updateWriteoffCalculation);
$("#saveWriteoffButton").addEventListener("click", saveWriteoff);
$("#productionRecipe").addEventListener("change", updateProductionPreview);
$("#productionQuantity").addEventListener("input", updateProductionPreview);
$("#saveProductionButton").addEventListener("click", saveProduction);
$("#inventoryScope").addEventListener("change", () => { $("#inventoryCategory").disabled = $("#inventoryScope").value !== "category"; });
$("#inventoryCountList").addEventListener("input", () => { updateInventoryDifference(); filterInventoryCount(true); });
$("#inventoryCountList").addEventListener("change", () => filterInventoryCount());
$("#inventoryCountSearch").addEventListener("input", filterInventoryCount);
$("#inventoryCountFilter").addEventListener("change", filterInventoryCount);
$("#inventoryCountList").addEventListener("click", event => {
  const button = event.target.closest("[data-inventory-movement]");
  if (button) openInventoryMovement(button.dataset.inventoryMovement, button.dataset.movementBucket);
});
$("#closeInventoryMovement").addEventListener("click", () => $("#inventoryMovementDialog").close());
$("#printInventoryButton").addEventListener("click", printInventoryDocument);
$("#exportInventoryButton").addEventListener("click", exportInventoryDocument);
$("#startInventoryButton").addEventListener("click", startInventoryCount);
$("#saveInventoryDraftButton").addEventListener("click", saveInventoryDraft);
$("#submitInventoryButton").addEventListener("click", submitInventory);
$("#cancelInventoryButton").addEventListener("click", cancelInventory);
$("#returnInventoryButton").addEventListener("click", returnInventory);
$("#postInventoryButton").addEventListener("click", postInventory);
$("#documentActionButton").addEventListener("click", () => {
  const action = $("#documentActionButton").dataset.action;
  if (action === "requests") openRequestForm();
  else if (action === "direct-orders") openDirectOrderForm();
  else if (action === "point-transfers") openPointTransferForm();
  else if (action === "inventories") openInventoryForm();
  else if (action === "supplies" || action === "supply") openSupplyForm();
  else if (action === "writeoff") { populateWriteoffForm(); $("#writeoffModal").classList.remove("hidden"); }
  else if (action === "production") { populateProductionForm(); $("#productionModal").classList.remove("hidden"); }
  else if (action === "inventory") openInventoryForm();
  else if (action === "transfer") showToast("Реестр перемещений подготовлен к экспорту");
  else if (action === "movement") showToast("Отчёт по движению подготовлен к экспорту");
});
$("#createFirstRequestButton").addEventListener("click", openRequestForm);
$("#dashboardOrdersButton").addEventListener("click", () => { switchView("reports"); switchAnalyticsTab("receipts"); });
$("#signOutButton").addEventListener("click", async () => {
  if (serverMode) {
    try { await window.AshkanaApi.logout(); } catch {}
  }
  sessionStorage.removeItem(authSessionKey);
  location.href = "/login";
});
document.addEventListener("keydown", (event) => {
  if ($('#employeeDeleteDialog').open) return;
  if (event.key === "Escape") {
    closeNotifications();
    $("#recipeDrawer").classList.add("hidden");
    if (!$('#preparationCompositionDrawer').classList.contains('hidden')) closePreparationComposition();
    document.querySelectorAll(".modal-backdrop").forEach((modal) => modal.classList.add("hidden"));
  }
});

function routeInitialWorkspace() {
  const initialView = location.hash.slice(1);
  if (initialView.startsWith("settings") && canAccessView("settings")) {
    switchView("settings");
    window.CompanySettings.open(initialView.split("/")[1] || "general");
  } else if (initialView === "new-direct-order" && currentRole === "branch") {
    switchView("inventory");
    switchStockTab("supplies");
    openSupplyForm();
  } else if (currentRole !== "owner") {
    if (initialView.startsWith("inventory/")) routeRoleWorkspace(initialView);
    else if (initialView === "inventory") routeRoleWorkspace("inventory/overview");
    else if (initialView === "logistics" && currentRole === "branch") routeRoleWorkspace("logistics");
    else routeRoleWorkspace(defaultRoleRoute());
  } else if (initialView === "supply") {
    switchView("inventory");
    switchStockTab("supplies");
    openSupplyForm();
  } else if (initialView === "new-ingredient") {
    switchView("recipes");
    switchMenuPage("ingredients");
    openIngredientForm();
  } else if (initialView === "new-product") {
    switchView("recipes");
    switchMenuPage("products");
    openProductForm();
  } else if (initialView === "new-recipe") {
    switchView("recipes");
    switchMenuPage("recipes");
    openRecipeForm();
  } else if (initialView === "new-preparation") {
    switchView("recipes");
    switchMenuPage("preparations");
    openPreparationForm();
  } else if (initialView === "new-menu-category") {
    switchView("recipes");
    switchMenuPage("menu-categories");
    openCategoryForm("menu");
  } else if (initialView === "new-station") {
    switchView("recipes");
    switchMenuPage("stations");
    openStationForm();
  } else if (initialView.startsWith("menu/")) {
    switchView("recipes");
    switchMenuPage(initialView.split("/")[1]);
  } else if (initialView.startsWith("inventory/")) {
    switchView("inventory");
    switchStockTab(initialView.split("/")[1]);
  } else if (initialView === "inventory") {
    switchView("inventory");
    switchStockTab("overview");
  } else if (initialView.startsWith("reports")) {
    switchView("reports");
    switchAnalyticsTab(initialView.split("/")[1] || "sales");
  } else if (initialView.startsWith("finance")) {
    switchView("finance");
    switchFinanceTab(initialView.split("/")[1] || "pnl");
  } else if (initialView === "branches") {
    switchView("dashboard");
  } else if (document.querySelector(`#view-${initialView}`)) switchView(initialView);
}

async function initializeApplication() {
  if (!testMode) {
    try {
      const authResponse = await window.AshkanaApi.me();
      if (authResponse.session.role !== currentRole) {
        sessionStorage.setItem(authSessionKey, JSON.stringify(authResponse.session));
        location.replace(authResponse.session.route);
        return;
      }
      Object.assign(currentSession, authResponse.session);
      sessionStorage.setItem(authSessionKey, JSON.stringify(authResponse.session));
      if (currentRole === "branch" && ["cashier", "waiter", "hall_admin", "pos_terminal", "production"].includes(currentSession.staffRole)) {
        location.replace(currentSession.route || "/pos");
        return;
      }
      const workspace = await window.AshkanaApi.workspace();
      serverMode = true;
      hydrateServerWorkspace(workspace);
      if (currentRole === "owner") {
        [employees, posRegisters, posShifts] = await Promise.all([
          window.AshkanaApi.employees(),
          window.AshkanaApi.posRegisters(),
          window.AshkanaApi.posShifts(),
        ]);
      } else if (currentSession.staffRole === "branch_manager") {
        [employees, posRegisters] = await Promise.all([
          window.AshkanaApi.employees(),
          window.AshkanaApi.posRegisters(),
        ]);
      }
      workspaceRefreshTimer = window.setInterval(() => refreshServerWorkspace(), 15000);
    } catch (error) {
      sessionStorage.removeItem(authSessionKey);
      location.replace([401, 403].includes(error.status) ? "/login?access=changed" : "/login?server=unavailable");
      return;
    }
  }
  applyRoleWorkspace();
  const trialNotice = document.querySelector('#trialNotice');
  if (trialNotice && currentRole === 'owner' && currentSession.subscriptionStatus === 'trialing' && currentSession.trialEndsAt) {
    const end = new Date(currentSession.trialEndsAt);
    if (Number.isFinite(end.getTime())) {
      trialNotice.hidden = false;
      trialNotice.textContent = `Пробный доступ до ${end.toLocaleDateString('ru-RU')}. Осталось дней: ${Math.max(0, Math.ceil((end.getTime() - Date.now()) / 86400000))}. Для продолжения после пробного периода свяжитесь с командой Oimo. Автоматических списаний нет.`;
    }
  }
  renderAll();
  routeInitialWorkspace();
}

window.ProductVariants.mount();
window.IngredientsList.mount();
window.CompanySettings.mount({
  session: currentSession,
  branchName: () => branches[0]?.name,
  notify: showToast,
  save: async (section, values) => {
    if (serverMode) return runServerAction("settings.update", { section, values });
    const saved = JSON.parse(localStorage.getItem("ashkana-company-settings-test") || "{}");
    saved[section] = values;
    localStorage.setItem("ashkana-company-settings-test", JSON.stringify(saved));
    return { state: { companySettings: saved } };
  }
});
if (testMode) {
  try { window.CompanySettings.receive(JSON.parse(localStorage.getItem("ashkana-company-settings-test") || "{}"), currentSession); } catch { window.CompanySettings.receive({}, currentSession); }
}
document.querySelectorAll("[data-settings-tab]").forEach(button => button.addEventListener("click", () => {
  switchView("settings");
  window.CompanySettings.open(button.dataset.settingsTab);
}));
initializeApplication();

let adminCustodyPanel = null;
function openCustodyJournal(documentId = null) {
  if (typeof documentId !== "string") documentId = null;
  if (!serverMode) { showToast("Журнал доступен при подключении к серверу"); return; }
  if (adminCustodyPanel) { if(documentId) adminCustodyPanel.reviewDocument(documentId); else adminCustodyPanel.reload(); $("#adminCustodyPanel").scrollIntoView({block:"start",behavior:"smooth"}); return; }
  adminCustodyPanel = window.Custody.mount($("#adminCustodyPanel"),{
    load:()=>window.AshkanaApi.productionContext($("#productionBranchSelect").value || currentSession.branchId),
    action:(action,payload)=>window.AshkanaApi.action(action,{...payload,branchId:$("#productionBranchSelect").value || currentSession.branchId}),
    after:response=>{hydrateServerWorkspace(response);renderProductionRecord();renderProductionJournal();renderNotifications();}
  });
  if(documentId) adminCustodyPanel.reviewDocument(documentId);
  $("#adminCustodyPanel").scrollIntoView({block:"start",behavior:"smooth"});
}
$("#openCustodyJournal").addEventListener("click",openCustodyJournal);
$("#productionBranchSelect").addEventListener("change",()=>{if(adminCustodyPanel)adminCustodyPanel.reload();});

function salePaymentParts(sale) { return Array.isArray(sale.payments) ? sale.payments : [{method:sale.paymentMethod,amount:Number(sale.total || 0)}]; }
function salePaymentAmount(sale, method) { return salePaymentParts(sale).filter(part=>part.method===method).reduce((sum,part)=>sum+Number(part.amount || 0),0); }
function salePaymentSummary(sale) { return salePaymentParts(sale).map(part=>`${paymentMethodLabel(part.method)}: ${money(part.amount)}`).join(" · "); }


const supplyDetails = document.createElement('dialog');
supplyDetails.id = 'supplyDetailsDialog';
document.body.append(supplyDetails);
function openSupplyDetails(id) {
  const supply = logisticsState.supplies.find(s => s.id === id);
  if (!supply) return;
  const accounts = financeState.accounts.filter(a => a.status === 'active' && a.type !== 'cash' && (!a.branchId || a.branchId === supply.branchId));
  const debt = Math.max(0, supplyMoney(supply.debt || 0));
  const canPay = currentRole === 'owner' && debt > 0;
  const paymentForm = canPay && accounts.length ? `<form><label>Счёт<select name="account" required>${accounts.map(a=>`<option value="${escapeHtml(a.id)}">${escapeHtml(a.name)}</option>`).join('')}</select></label><label>Сумма<input name="amount" type="number" min="0.01" step="0.01" max="${debt}" value="${debt}" required></label><p role="alert" data-error></p><button class="primary-button" type="submit">Оплатить поставку</button></form>` : canPay ? '<p>Для оплаты добавьте активный счёт в разделе «Финансы → Счета».</p>' : '';
  supplyDetails.innerHTML = `<header><h2>${escapeHtml(supply.number)} · ${escapeHtml(supply.supplier)}</h2><button type="button" data-close-supply class="icon-button" aria-label="Закрыть">×</button></header><p>${supplyPaymentStatusLabel(supply.paymentStatus)} · Долг: <strong>${money(debt)}</strong></p><div class="supply-detail-items">${(supply.items || []).map(i=>`<div><span>${escapeHtml(logisticsItem(i.itemId)?.name || i.itemId)}</span><span>${Number(i.quantity).toLocaleString('ru-RU')} × ${money(i.price)}</span></div>`).join('')}</div><h3>Платежи</h3>${(supply.payments || []).map(p=>`<article class="supply-payment-history"><div><strong>${money(p.amount)}</strong><span>${escapeHtml(financeState.accounts.find(a=>a.id===p.accountId)?.name || '')}</span><small>${escapeHtml(new Date(p.occurredAt).toLocaleString('ru-RU'))}</small>${p.reversedAt ? `<small class="supply-payment-reversed">Отменён ${escapeHtml(new Date(p.reversedAt).toLocaleString('ru-RU'))} · ${escapeHtml(p.reversedBy)}<br>${escapeHtml(p.reversalReason)}</small>` : ''}</div>${currentRole === 'owner' && p.id && !p.reversedAt ? `<button type="button" class="icon-button" data-reverse-payment="${escapeHtml(p.id)}" title="Отменить оплату" aria-label="Отменить оплату ${money(p.amount)}">${uiIcon('arrow')}</button>` : ''}</article>`).join('') || '<p>Оплат пока нет</p>'}<section data-payment-reversal hidden></section>${paymentForm}`;
  supplyDetails.querySelector('[data-close-supply]').onclick = ()=>supplyDetails.close();
  supplyDetails.querySelectorAll('[data-reverse-payment]').forEach(button => {
    button.onclick = () => openSupplyPaymentReversal(supply, button.dataset.reversePayment, accounts);
  });
  const form = supplyDetails.querySelector('form');
  if(form) {
    form.onsubmit = async event=>{
      event.preventDefault();
      const button = form.querySelector('button');
      if (button.disabled) return;
      button.disabled = true;
      form.querySelector('[data-error]').textContent = '';
      form.elements.account.disabled = true;
      form.elements.amount.disabled = true;
      try {
        const response = await runServerAction('supply.pay', {id, accountId:form.elements.account.value, amount:Number(form.elements.amount.value)});
        if(response) { openSupplyDetails(id); renderDocuments(); }
        else form.querySelector('[data-error]').textContent = $('#adminToast')?.textContent || 'Не удалось сохранить платёж. Проверьте соединение и повторите попытку.';
      } catch(error) { form.querySelector('[data-error]').textContent = error.message; }
      finally { button.disabled = false; form.elements.account.disabled = false; form.elements.amount.disabled = false; }
    };
  }
  if(!supplyDetails.open) supplyDetails.showModal();
}
function openSupplyPaymentReversal(supply, paymentId, accounts) {
  const payment = (supply.payments || []).find(p => p.id === paymentId);
  if (!payment || payment.reversedAt || currentRole !== 'owner') return;
  const section = supplyDetails.querySelector('[data-payment-reversal]');
  const payForm = supplyDetails.querySelector(':scope > form');
  if (payForm) payForm.hidden = true;
  section.hidden = false;
  section.innerHTML = `<form class="supply-reversal-form"><h3>Отменить оплату ${money(payment.amount)}</h3><p>Долг восстановится. Укажите, куда вернулись деньги.</p><label>Счёт возврата<select name="account" required>${accounts.map(a=>`<option value="${escapeHtml(a.id)}" ${a.id === payment.accountId ? 'selected' : ''}>${escapeHtml(a.name)}</option>`).join('')}</select></label><label>Причина<textarea name="reason" minlength="3" maxlength="1000" rows="2" required></textarea></label><p role="alert" data-error></p><div class="supply-reversal-actions"><button type="button" class="secondary-action" data-cancel-reversal>Назад</button><button type="submit" class="primary-button" ${accounts.length ? '' : 'disabled'}>Подтвердить отмену</button></div></form>`;
  section.querySelector('[data-cancel-reversal]').onclick = () => openSupplyDetails(supply.id);
  const form = section.querySelector('form');
  form.onsubmit = async event => {
    event.preventDefault();
    if (form.dataset.pending) return;
    if (!form.reportValidity()) return;
    form.dataset.pending = 'true';
    const payload = {id:supply.id, paymentId, accountId:form.elements.account.value, reason:form.elements.reason.value.trim()};
    const controls = [...form.querySelectorAll('button,input,select,textarea')];
    controls.forEach(control => { control.disabled = true; });
    form.querySelector('[data-error]').textContent = '';
    try {
      const response = await runServerAction('supply.payment.reverse', payload);
      if (response) { openSupplyDetails(supply.id); renderDocuments(); showToast('Оплата отменена, долг восстановлен'); }
      else form.querySelector('[data-error]').textContent = $('#adminToast')?.textContent || 'Не удалось отменить оплату';
    } catch (error) { form.querySelector('[data-error]').textContent = error.message; }
    finally { delete form.dataset.pending; controls.forEach(control => { control.disabled = false; }); }
  };
  section.scrollIntoView({block:'nearest'});
  form.elements.reason.focus({preventScroll:true});
}
document.addEventListener('click', event=>{ const button=event.target.closest('[data-view-supply]'); if(button)openSupplyDetails(button.dataset.viewSupply); });

function prepareInventorySelection() {
  $('#inventorySelectionSearch').value = '';
  $('#inventorySelectionList').innerHTML = inventorySnapshotItems($('#inventoryWarehouse').value, 'full', '').map(item =>
    `<label class="inventory-selection-row"><input type="checkbox" data-inventory-select value="${escapeHtml(item.itemId)}"><span class="inventory-selection-name">${escapeHtml(logisticsItem(item.itemId)?.name || item.itemId)}</span></label>`
  ).join('');
  renderInventorySelection();
}

function renderInventorySelection() {
  const query = $('#inventorySelectionSearch').value.trim().toLocaleLowerCase();
  const rows = [...document.querySelectorAll('#inventorySelectionList .inventory-selection-row')];
  rows.forEach(row => { row.hidden = !row.textContent.toLocaleLowerCase().includes(query); });
  const selected = rows.filter(row => row.querySelector('input').checked).length;
  $('#inventorySelectionCount').textContent = `Выбрано: ${selected} из ${rows.length}`;
  $('#inventorySelectionEmpty').classList.toggle('hidden', rows.some(row => !row.hidden));
}
$('#inventoryScope').addEventListener('change',()=>{
 const scope=$('#inventoryScope').value;
 $('#inventorySelection').classList.toggle('hidden',scope!=='selected');
 $('#inventoryCountedAt').disabled=scope==='serving';
 if(scope==='serving')$('#inventoryCountedAt').value='';
});
$('#inventorySelectionSearch').oninput=renderInventorySelection;
$('#inventorySelectionList').addEventListener('change', renderInventorySelection);

// Disclosures keep occasional tools out of the main workflow.
{
  const disclosures = [...document.querySelectorAll('.ux-tools, .ux-advanced-filters')];
  document.addEventListener('click', event => {
    disclosures.forEach(details => {
      if (details.open && !details.contains(event.target)) details.open = false;
    });
    const command = event.target.closest('.ux-tools-panel button');
    if (command) command.closest('.ux-tools').open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    disclosures.filter(details => details.open).forEach(details => {
      details.open = false;
      details.querySelector('summary').focus();
    });
  });
  const extraFilters = document.querySelector('.ux-advanced-filters');
  const updateExtraFilterCount = () => {
    if (!extraFilters) return;
    const count = [...extraFilters.querySelectorAll('select')].filter(select => select.value !== (select.id === 'ingredientSort' ? 'name' : '')).length;
    const badge = document.querySelector('#ingredientExtraFilterCount');
    badge.hidden = !count;
    badge.textContent = count ? String(count) : '';
    extraFilters.classList.toggle('has-active-filters', count > 0);
  };
  extraFilters?.addEventListener('change', updateExtraFilterCount);
  document.querySelector('#resetIngredientFilters')?.addEventListener('click', updateExtraFilterCount);
  updateExtraFilterCount();
}
