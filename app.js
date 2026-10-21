const authSessionKey = "ashkana-auth-session-v1";
const paymentLabels = { cash: "Наличные", card: "Банковская карта", qr: "QR-оплата", mixed: "Смешанная оплата", external: "Внешняя касса" };

let products = [];
let sales = [];
let workspaceState = null;
let posState = { customers: [], openOrders: [], cashMovements: [] };
let currentSession = null;
let cart = new Map();
let activeCategory = null;
let selectedPaymentMethod = "cash";
let lastSale = null;
let activeOperator = null;
let activeShift = null;
let pinValue = "";
let pinSubmitting = false;
let pendingShiftCloseCash = null;
const terminalDeviceDefaults = { receiptPrinterMode: "browser", receiptPrinterName: "", receiptPaperWidth: 80, receiptDots: 0, receiptCutPaper: false, autoPrintReceipt: false, printKitchenTicket: false };
let terminalDeviceSettings = { ...terminalDeviceDefaults };
let currentCustomer = null;
let currentOpenOrderId = null;
let selectedReceiptId = null;
let posSupplyContext = { suppliers: [], items: [], accounts: [], supplies: [] };
let posSupplyLineSequence = 0;
let posSupplyImportData = null, posSupplyImportBusy = false, posSupplyImportRequest = 0, posSupplySaving = false;

const $ = (selector) => document.querySelector(selector);
const money = (value) => window.CompanySettings.currency(value, posCompanySettings().general.currency);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
const posIcon = (name) => `<svg class="ui-icon" aria-hidden="true"><use href="#pos-${name}"></use></svg>`;

function operatorCan(permission) {
  if (!activeOperator) return false;
  if (activeOperator.staffRole === "production") {
    if (["posCash", "posRefunds"].includes(permission)) return false;
    if (["posAccess", "posSupply", "production"].includes(permission)) return true;
  }
  if (activeOperator.permissions && Object.prototype.hasOwnProperty.call(activeOperator.permissions, permission)) return Boolean(activeOperator.permissions[permission]);
  const defaults = {
    posAccess: ["branch_manager", "hall_admin", "waiter", "cashier"],
    posRefunds: ["branch_manager", "hall_admin"],
    posCash: ["branch_manager", "hall_admin", "cashier"],
    posSupply: ["branch_manager"],
    production: ["branch_manager", "production"],
  };
  return (defaults[permission] || []).includes(activeOperator.staffRole);
}

function branchById(id) {
  return workspaceState?.branches?.find((branch) => String(branch.id) === String(id));
}

function availableRecipePortions(recipe, branchId) {
  if (workspaceState?.serviceMode === "restaurant") return Number(recipe.availableToOrder || 0);
  if (Array.isArray(recipe.availableLots)) return recipe.availableLots.reduce((sum,lot)=>sum+Number(lot.available||0),0);
  return 0;
}

function hydrateWorkspace(response) {
  workspaceState = response?.state;
  if (!workspaceState || !currentSession?.branchId) return false;
  const restaurant = workspaceState.serviceMode === "restaurant";
  updateProductionAccess();

  const title = document.querySelector(".catalog-toolbar h1");
  if (title) title.textContent = restaurant ? "Новый заказ" : "Что на подносе?";
  document.querySelector(".brand span").textContent = restaurant ? "Касса ресторана" : "Касса столовой";
  const branchId = currentSession.branchId;
  const branchStock = workspaceState.logisticsState?.branchStocks?.[branchId] || {};
  const recipes = (workspaceState.recipes || []).map((recipe) => ({
    id: String(recipe.id),
    name: recipe.name,
    image: recipe.image || "",
    price: Number(recipe.price || 0),
    category: recipe.category,
    station: recipe.station || "",
    color: recipe.color || workspaceState.menuCategories?.find((category) => category.name === recipe.category)?.color || "#3987df",
    unit: "порция",
    available: availableRecipePortions(recipe, branchId),
    availableLots: recipe.availableLots,
    kind: "recipe"
  }));
  const readyProducts = (workspaceState.products || []).map((product) => ({
    id: String(product.id),
    name: product.name,
    price: Number(product.price || 0),
    category: product.category,
    image: product.image || "",
    groupName: product.groupName || "", parentId: product.parentId || "", variantName: product.variantName || "", barcode: product.barcode || "", station: product.station || "",
    color: product.color || workspaceState.menuCategories?.find((category) => category.name === product.category)?.color || "#7b8ba2",
    unit: product.unit || "шт",
    available: Math.max(0, Number(branchStock[String(product.id)] || 0)),
    kind: "product",
    noDiscount: Boolean(product.noDiscount)
  }));
  products = [...recipes, ...readyProducts].filter((product) => product.price > 0);
  configureOrderSettings(!cart.size);
  sales = Array.isArray(workspaceState.sales) ? workspaceState.sales : [];
  posState = {
    customers: workspaceState.posState?.customers || [],
    openOrders: workspaceState.posState?.openOrders || [],
    cashMovements: workspaceState.posState?.cashMovements || [],
  };
  if (currentCustomer) currentCustomer = posState.customers.find((customer) => customer.id === currentCustomer.id) || null;
  for (const [id, item] of cart) {
    const current = products.find((product) => product.id === item.id);
    if (current && item.lotId) {
      const lot = current.availableLots?.find(lot=>lot.id===item.lotId);
      cart.set(id,{...current,lotId:item.lotId,cartKey:id,servingLine:item.servingLine,available:Number(lot?.available||0),quantity:item.quantity});
      continue;
    }
    if (currentOpenOrderId && (!current || item.quantity > current.available)) {
      cart.set(id, { ...item, ...(current || {}), cartKey:id, quantity:item.quantity, available:Number(current?.available || 0) });
    }
    else if (!current || item.quantity > current.available) cart.delete(id);
    else cart.set(id, { ...current, quantity: item.quantity });
  }
  return true;
}

function getSales() { return sales; }

function cartSubtotal() {
  return [...cart.values()].reduce((sum, item) => sum + item.price * item.quantity, 0);
}

function currentDiscountPercent() { return Number(currentCustomer?.discountPercent || 0); }

function cartDiscount() {
  const discountable = [...cart.values()].filter((item) => !item.noDiscount).reduce((sum, item) => sum + item.price * item.quantity, 0);
  return Math.round(discountable * currentDiscountPercent()) / 100;
}

function posCompanySettings() { return window.CompanySettings.normalize(workspaceState?.companySettings); }
function orderContext() {
  return { orderType: $("#posOrderType").value, table: $("#posOrderTable").value,
    deliveryArea: $("#posDeliveryArea").value, deliveryAddress: $("#posDeliveryAddress").value.trim(),
    deliveryPhone: $("#posDeliveryPhone").value.trim(), applyService: $("#posApplyService").checked };
}
function configureOrderSettings(reset = false) {
  const settings = posCompanySettings();
  const current = $("#posOrderType").value;
  const table = $("#posOrderTable").value;
  const area = $("#posDeliveryArea").value;
  $("#posOrderType").innerHTML = [["dine-in", "В заведении", settings.orders.dineIn], ["takeaway", "С собой", settings.orders.takeaway], ["delivery", "Доставка", settings.delivery.enabled]].filter(row => row[2]).map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  $("#posOrderType").value = reset ? settings.orders.defaultType : current || settings.orders.defaultType;
  if (!$("#posOrderType").value) $("#posOrderType").selectedIndex = 0;
  $("#posOrderTable").innerHTML = '<option value="">Выберите стол</option>' + settings.orders.tables.map(name => `<option>${escapeHtml(name)}</option>`).join("");
  $("#posOrderTable").value = reset ? "" : table;
  $("#posDeliveryArea").innerHTML = '<option value="">Выберите район</option>' + settings.delivery.areas.map(row => `<option>${escapeHtml(row.name)}</option>`).join("");
  $("#posDeliveryArea").value = reset ? "" : area;
  if (reset) {
    $("#posApplyService").checked = settings.general.serviceDefault;
    $("#posDeliveryAddress").value = "";
    $("#posDeliveryPhone").value = "";
  }
  $("#posTableField").classList.toggle("hidden", !settings.general.floorPlan || $("#posOrderType").value !== "dine-in");
  $("#posDeliveryFields").classList.toggle("hidden", $("#posOrderType").value !== "delivery");
  $("#posServiceField").classList.toggle("hidden", !settings.general.servicePercent);
  $("#posServicePercent").textContent = `${settings.general.servicePercent}%`;
}
function cartExtras() {
  const settings = posCompanySettings();
  const base = Math.max(0, cartSubtotal() - cartDiscount());
  const context = orderContext();
  const service = context.applyService ? Math.round(base * settings.general.servicePercent) / 100 : 0;
  const area = settings.delivery.areas.find(row => row.name === context.deliveryArea);
  const delivery = context.orderType === "delivery" && area && !(area.freeFrom > 0 && base >= area.freeFrom) ? Number(area.cost) : 0;
  return { service, delivery };
}
function cartTotal() {
  const extras = cartExtras();
  const total = Math.round((Math.max(0, cartSubtotal() - cartDiscount()) + extras.service + extras.delivery) * 100) / 100;
  return posCompanySettings().general.roundTotal ? Math.floor(total) : total;
}
function allowProtectedAction(key) {
  if (posCompanySettings().security[key] !== "always" || ["branch_manager", "hall_admin"].includes(activeOperator?.staffRole)) return true;
  showToast("Для этого действия войдите под PIN управляющего");
  return false;
}

function cartQuantity() {
  return [...cart.values()].reduce((sum, item) => sum + item.quantity, 0);
}

function nextReceiptNumber() {
  return Math.max(0,...sales.map(sale=>Number(sale.number)).filter(value=>Number.isSafeInteger(value)&&value>0))+1;
}

function visibleInCatalog(product) {
  return workspaceState?.serviceMode === "restaurant" || product.kind !== "recipe" || product.available > 0;
}

function categories() {
  return [...new Set(products.filter(visibleInCatalog).map((product) => product.category || "Без категории"))];
}

function renderCategories() {
  if (!categories().includes(activeCategory)) activeCategory = null;
  $("#categories").innerHTML = categories().map((category) => {
    const categoryAppearance = workspaceState.menuCategories?.find(item=>item.name===category);
    const cover = categoryAppearance?.image || "";
    const categoryColor = /^#[0-9a-f]{6}$/i.test(categoryAppearance?.color || "") ? categoryAppearance.color : "#633d60";
    return `<button class="category-button ${category === activeCategory ? "active" : ""}" data-category="${escapeHtml(category)}" style="--category-color:${categoryColor}" type="button">${cover ? `<img src="${escapeHtml(cover)}" alt="">` : `<span class="category-cover" aria-hidden="true">${category === "Все" ? "▦" : escapeHtml(category.slice(0,2))}</span>`}<span class="category-label"><strong>${escapeHtml(category)}</strong><small>${products.filter(product => (product.category || "Без категории") === category && visibleInCatalog(product)).length} поз.</small></span><span class="category-forward" aria-hidden="true">${posIcon("arrow")}</span></button>`;
  }).join("");
}

function filteredProducts() {
  const query = $("#searchInput").value.trim().toLowerCase();
  return products.filter((product) => {
    const categoryMatches = query ? true : (product.category || "Без категории") === activeCategory;
    const queryMatches = !query || product.name.toLowerCase().includes(query) || product.id.toLowerCase().includes(query) || (product.barcode || "").toLowerCase().includes(query);
    return visibleInCatalog(product) && categoryMatches && queryMatches;
  });
}

function renderProducts() {
  renderCategories();
  const searching = Boolean($("#searchInput").value.trim());
  const categoryHome = !activeCategory && !searching;
  $("#categories").classList.toggle("hidden", !categoryHome);
  $("#catalogBack").classList.toggle("hidden", categoryHome);
  $("#catalogCategoryTitle").textContent = searching ? "Результаты поиска" : activeCategory || "Категории";
  $("#productGrid").classList.toggle("hidden", categoryHome);
  if (categoryHome) {
    $("#productGrid").innerHTML = "";
    $("#catalogCount").textContent = categories().length ? "Выберите категорию" : "Нет доступных категорий";
    return;
  }
  const seenGroups = new Set();
  const visibleProducts = filteredProducts().filter(product => {
    const key = product.parentId || product.id;
    if (seenGroups.has(key)) return false;
    seenGroups.add(key); return true;
  }).map(product => {
    if (!product.variantName) return product;
    const groupId = product.parentId || product.id;
    const variants = products.filter(item => item.id === groupId || item.parentId === groupId);
    return {...product, id:groupId, name:product.groupName, price:Math.min(...variants.map(item=>item.price)), available:variants.reduce((sum,item)=>sum + Math.max(0,item.available - (cart.get(item.id)?.quantity || 0)),0), variantCount:variants.length};
  });
  $("#catalogCount").textContent = `${visibleProducts.length} ${visibleProducts.length === 1 ? "позиция" : "позиций"}`;
  $("#productGrid").innerHTML = visibleProducts.length ? visibleProducts.map((product) => {
    const inCart = product.variantCount ? 0 : [...cart.values()].filter(item=>item.id===product.id).reduce((sum,item)=>sum+Number(item.quantity),0);
    const unavailable = product.available - inCart < (product.kind === "recipe" && posCompanySettings().general.fractional ? 0.01 : 1);
    return `
      <button class="product-card" style="--product-accent:${escapeHtml(product.color || "#3987df")}" data-product-id="${escapeHtml(product.id)}" type="button" ${unavailable ? "disabled" : ""}>
        ${product.image ? `<img class="product-photo" src="${escapeHtml(product.image)}" alt="" />` : ""}
        ${inCart > 0 ? `<span class="mobile-product-count">${inCart}</span>` : ""}
        <span class="product-code">Код ${escapeHtml(product.id)}</span>
        <strong>${escapeHtml(product.name)}</strong>
        <span class="product-bottom">
          <span class="product-price">${product.variantCount ? "от " : ""}${money(product.price)}</span>
          <span class="product-unit">${product.variantCount ? `${product.variantCount} вида` : unavailable ? (workspaceState?.serviceMode === "restaurant" ? "нет ингредиентов/остатка" : "нет на раздаче/складе") : `доступно ${product.available} ${escapeHtml(product.unit)}`}</span>
        </span>
      </button>`;
  }).join("") : `<div class="no-products">Нет доступных позиций или ничего не найдено.</div>`;
}

function cartItemAvailabilityIssue(item) {
  const product = products.find(entry => entry.id === String(item.id));
  if (!product) return `${item.name}: позиция недоступна. Удалите её или замените.`;
  const available = item.lotId ? Number(product.availableLots?.find(lot => lot.id === item.lotId)?.available || 0) : Number(product.available || 0);
  return item.quantity > available ? `${item.name}: доступно ${available} ${item.unit}. Уменьшите количество или замените позицию.` : '';
}

function cartAvailabilityIssue() {
  return [...cart.values()].map(cartItemAvailabilityIssue).find(Boolean) || '';
}

function renderCart() {
  const items = [...cart.values()];
  const total = cartTotal();
  const extras = cartExtras();
  $("#posExtraTotal").classList.toggle("hidden", !(extras.service + extras.delivery));
  $("#posExtraAmount").textContent = money(extras.service + extras.delivery);
  const openOrder = posState.openOrders.find((order) => order.id === currentOpenOrderId);
  $("#orderTitle").textContent = openOrder?.number ? `${openOrder.number} · открыт` : `Заказ №${nextReceiptNumber()}`;
  $("#itemCount").textContent = cartQuantity();
  $("#totalAmount").textContent = money(total);
  $("#payButtonAmount").textContent = money(total);
  const availabilityIssue = cartAvailabilityIssue();
  $("#payButton").disabled = items.length === 0 || !activeOperator || Boolean(availabilityIssue);
  $("#payButton").title = availabilityIssue;
  $("#customerName").textContent = currentCustomer?.name || "Не выбран";
  $("#customerDiscount").textContent = currentCustomer && currentDiscountPercent() ? `−${currentDiscountPercent()}%` : "";
  $("#discountLine").classList.toggle("hidden", cartDiscount() <= 0);
  $("#discountAmount").textContent = `− ${money(cartDiscount())}`;
  $("#saveOrderButton").disabled = items.length === 0;
  renderProducts();

  if (!items.length) {
    $("#orderItems").innerHTML = `<div class="empty-order"><div class="tray-icon">${posIcon("tray")}</div><strong>${workspaceState?.serviceMode === "restaurant" ? "Заказ пока пуст" : "Поднос пока пуст"}</strong><span>Выберите блюда в каталоге справа</span></div>`;
    return;
  }

  $("#orderItems").innerHTML = items.map((item) => `
    <div class="order-row">
      <div><div class="order-row-title">${escapeHtml(item.name)}</div><div class="order-row-price">${money(item.price)} · ${escapeHtml(item.unit)}${item.servingLine ? `<small>${escapeHtml(item.servingLine)}</small>` : ""}</div>${cartItemAvailabilityIssue(item) ? `<small class="danger-text">${escapeHtml(cartItemAvailabilityIssue(item))}</small><button type="button" class="danger-button" data-quantity-action="remove" data-product-id="${escapeHtml(item.cartKey || item.id)}">Убрать из заказа</button>` : ''}</div>
      <div class="order-row-right">
        <span class="row-sum">${money(item.price * item.quantity)}</span>
        <div class="quantity-control">
          <button data-quantity-action="minus" data-product-id="${escapeHtml(item.cartKey || item.id)}" type="button">−</button>
          ${item.kind === "recipe" && posCompanySettings().general.fractional ? `<input class="fractional-quantity" aria-label="Количество ${escapeHtml(item.name)}" data-fractional-id="${escapeHtml(item.cartKey || item.id)}" type="number" min="0.01" max="${item.available}" step="0.01" value="${item.quantity}">` : `<span>${item.quantity}</span>`}
          <button data-quantity-action="plus" data-product-id="${escapeHtml(item.cartKey || item.id)}" type="button" ${item.quantity >= item.available ? "disabled" : ""}>+</button>
        </div>
      </div>
    </div>`).join("");
}

function chooseProduct(id) {
  const product = products.find(item => item.id === String(id));
  if (!product?.variantName) return addProduct(id);
  const groupId = product.parentId || product.id;
  $("#productVariantDialog > p").textContent = "Выберите модификацию";
  $("#variantDialogTitle").textContent = product.groupName;
  $("#variantDialogOptions").innerHTML = products.filter(item => item.id === groupId || item.parentId === groupId).map(item => {
    const remaining = item.available - (cart.get(item.id)?.quantity || 0);
    return `<button type="button" data-select-variant="${escapeHtml(item.id)}" ${remaining <= 0 ? "disabled" : ""}><span class="variant-cover" style="background:${escapeHtml(item.color || "#633d60")}">${item.image ? `<img src="${escapeHtml(item.image)}" alt="">` : escapeHtml(item.variantName.slice(0,1))}</span><span>${escapeHtml(item.variantName)}<small>${remaining > 0 ? `Остаток: ${remaining} ${escapeHtml(item.unit)}` : "Нет на складе"}</small></span><strong>${money(item.price)}</strong></button>`;
  }).join("");
  $("#productVariantDialog").showModal();
}
function addProduct(id, lotId = null) {
  if (activeOperator?.staffRole === "production") return;
  let product = products.find((entry) => entry.id === String(id));
  if (!product) return;
  let existing = cart.get(product.id);
  let cartKey = product.id;
  if (Array.isArray(product.availableLots)) {
    const lot = product.availableLots.find(lot=>lot.id===(lotId || existing?.lotId)) || (product.availableLots.length===1 ? product.availableLots[0] : null);
    if (!lot) {
      if (!product.availableLots.length) { showToast("Нет принятого остатка на витрине"); return; }
      $("#productVariantDialog > p").textContent = "Укажите, с какой витрины отпущено блюдо.";
      $("#variantDialogTitle").textContent = `${product.name} · откуда выдано`;
      $("#variantDialogOptions").innerHTML = product.availableLots.map(lot=>`<button type="button" data-select-lot="${escapeHtml(lot.id)}" data-lot-product="${escapeHtml(product.id)}"><span>${escapeHtml(lot.line)}<small>${escapeHtml(lot.batchNumber)} · ${escapeHtml(lot.responsibleName || 'Ответственный не зафиксирован')}</small></span><strong>${lot.available} порц.</strong></button>`).join('');
      $("#productVariantDialog").showModal(); return;
    }
    cartKey=product.id+'::'+lot.id; existing=cart.get(cartKey);
    product={...product,cartKey,lotId:lot.id,servingLine:`${lot.line} · ${lot.batchNumber}`,available:Number(lot.available)};
  }
  const quantityStep = product.kind === "recipe" && posCompanySettings().general.fractional ? Math.min(1, Math.floor((product.available - (existing?.quantity || 0)) * 100) / 100) : 1;
  const nextQuantity = (existing?.quantity || 0) + quantityStep;
  if (quantityStep <= 0) return;
  if (nextQuantity > product.available) { showToast(`Недостаточно доступного количества: ${product.name}`); return; }
  cart.set(cartKey, { ...product, quantity: nextQuantity });
  renderCart();
}

function updateQuantity(id, delta) {
  const item = cart.get(String(id));
  if (!item) return;
  const quantity = item.quantity + delta;
  if (quantity <= 0) cart.delete(String(id));
  else if (delta < 0 || quantity <= item.available) cart.set(String(id), { ...item, quantity });
  else showToast(`Доступно только ${item.available} ${item.unit}`);
  renderCart();
}

function roundCashOptions(total) {
  const candidates = [total, Math.ceil(total / 50) * 50, Math.ceil(total / 100) * 100, Math.ceil(total / 500) * 500, 1000, 2000];
  return [...new Set(candidates)].filter((amount) => amount >= total).slice(0, 4);
}

function paymentInput(method = selectedPaymentMethod) { return $("#" + ({cash:"cashReceived",card:"cardReceived",qr:"qrReceived"}[method])); }
function checkoutPayments() {
  return ["cash","card","qr"].map(method => ({method, amount:Number(paymentInput(method).value || 0)}));
}
function selectPaymentMethod(method, fillRemaining = false) {
  if(window.OfflinePos?.isOffline() && method !== 'cash'){showToast('Без связи с сервером доступна оплата наличными.');return;}
  if (fillRemaining) {
    if (!checkoutEdited) ["cash","card","qr"].forEach(key => { paymentInput(key).value = 0; });
    const other = checkoutPayments().filter(part => part.method !== method && !(method !== "cash" && checkoutCashAutomatic && part.method === "cash")).reduce((sum,part) => sum + part.amount, 0);
    if (!Number(paymentInput(method).value)) paymentInput(method).value = Math.max(0, Math.round((cartTotal()-other)*100)/100);
    if (method !== "cash" && checkoutCashAutomatic) fillCheckoutCashRemainder();
  }
  selectedPaymentMethod = method;
  document.querySelectorAll("[data-payment-row]").forEach(row => row.classList.toggle("active", row.dataset.paymentRow === method));
  replaceCheckoutAmount = true;
  checkoutAmountBuffer = "";
  updatePaymentState();
}
function updatePaymentState() {
  const parts = checkoutPayments();
  const total = Math.round(cartTotal()*100);
  const received = parts.reduce((sum,part) => sum + Math.round(part.amount*100),0);
  const noncash = parts.filter(part => part.method !== "cash").reduce((sum,part) => sum + Math.round(part.amount*100),0);
  const validAmounts = parts.every(part => Number.isFinite(part.amount) && part.amount >= 0 && Math.abs(part.amount*100-Math.round(part.amount*100)) < 0.00001);
  const error = cartAvailabilityIssue() || (!validAmounts ? "Проверьте суммы оплаты" : noncash > total ? "Сумма карты и QR превышает итог чека" : "");
  $("#confirmPaymentButton").disabled = paymentSubmitting || !!error || received < total;
  $("#paymentRemaining").textContent = money(Math.max(0,total-received)/100);
  $("#changeAmount").textContent = money(!error ? Math.max(0,received-total)/100 : 0);
  $("#paymentSplitError").textContent = error;
  $("#paymentSplitError").classList.toggle("hidden", !error);
}

function openPayment(preselectedMethod = "cash") {
  if (activeOperator?.staffRole === "production") return;
  if (!activeOperator) { showOperatorSelection(); return; }
  if (pendingPayment()) { recoverPayment(); return; }
  if (!cart.size) return;
  const availabilityIssue = cartAvailabilityIssue();
  if (availabilityIssue) { showToast(availabilityIssue); return; }
  if (!$("#paymentModal").classList.contains("hidden")) {
    selectPaymentMethod(preselectedMethod, true);
    return;
  }
  const total = cartTotal();
  const autonomous=Boolean(window.OfflinePos?.isOffline());
  document.querySelector('.checkout-hint').textContent=autonomous?'Нет связи: новый заказ можно оплатить наличными. Чек сохранится на устройстве и отправится позже.':'Укажите суммы: можно сочетать наличные, карту и QR. Нажмите на способ, чтобы заполнить остаток.';
  ['card','qr'].forEach(method=>{paymentInput(method).disabled=autonomous;document.querySelector(`[data-method="${method}"]`).disabled=autonomous;});
  if(autonomous)preselectedMethod='cash';
  $("#modalTotal").textContent = money(total);
  replaceCheckoutAmount = true;
  checkoutAmountBuffer = "";
  checkoutEdited = false;
  checkoutCashAutomatic = true;
  ["cash","card","qr"].forEach(method => { paymentInput(method).value = 0; });
  $("#checkoutPrintReceipt").checked = terminalDeviceSettings.receiptPrinterMode !== "none" && Boolean(terminalDeviceSettings.autoPrintReceipt || posCompanySettings().receipt.autoPrint);
  $("#checkoutPrintReceipt").disabled = terminalDeviceSettings.receiptPrinterMode === "none";
  $("#quickCash").innerHTML = roundCashOptions(total).map((amount) => `<button data-cash-amount="${amount}" type="button">${money(amount)}</button>`).join("");
  $("#checkoutQuickCash").innerHTML = $("#quickCash").innerHTML;
  selectPaymentMethod(preselectedMethod);
  document.querySelectorAll("[data-payment-row]").forEach(row => row.classList.remove("active"));
  $("#paymentModal").classList.remove("hidden");
}

function closePayment() { $("#paymentModal").classList.add("hidden"); }

function paymentRetryKey() { return `o-post:payment:${currentSession?.tenantSlug}:${currentSession?.branchId}:${currentSession?.registerId}:${activeOperator?.id}`; }
function pendingPayment() { try { return JSON.parse(localStorage.getItem(paymentRetryKey()) || 'null'); } catch { return null; } }
async function recoverPayment() {
  const pending = pendingPayment();
  if (!pending || paymentSubmitting || !activeOperator) {
    if(!pending&&activeOperator&&window.OfflinePos){try{const legacy=JSON.parse(localStorage.getItem(`o-post:payment:${currentSession?.tenantSlug}:${currentSession?.branchId}:${activeOperator.id}`)||'null');if(legacy?.payload)await window.OfflinePos.rememberLegacy(legacy);}catch(_){/* Preserve the original legacy record if migration storage is unavailable. */}}
    return;
  }
  paymentSubmitting = true;
  try {
    const response = await window.AshkanaApi.action('sale.create', pending.payload);
    try{localStorage.removeItem(paymentRetryKey());}catch(_){/* A storage cleanup failure must not replay a confirmed payment. */}
    hydrateWorkspace(response);
    const currentItems = [...cart.values()].map(item=>({id:item.id,quantity:item.quantity,lotId:item.lotId}));
    if (JSON.stringify(currentItems)===JSON.stringify(pending.payload.items)) { closePayment(); startNewOrder(); }
    showToast('Оплата восстановлена. Чек сохранён один раз.');
  } catch (error) {
    if (error.status >= 400 && error.status < 500 && ![401,403,423].includes(error.status)) { localStorage.removeItem(paymentRetryKey()); showToast(error.message); return; }
    showToast('Есть неподтверждённая оплата. Повторите сохранение перед новым чеком.');
  } finally { paymentSubmitting = false; }
}

async function completePayment() {
  if (paymentSubmitting) return;
  if (activeOperator?.staffRole === "production") return;
  if (!allowProtectedAction("closeReceipt") || (currentDiscountPercent() && !allowProtectedAction("discount"))) return;
  const total = cartTotal();
  if (!total) return;
  updatePaymentState();
  if ($("#confirmPaymentButton").disabled) return;
  const payments = checkoutPayments().filter(part => part.amount > 0);
  const received = payments.reduce((sum,part) => sum + part.amount, 0);
  const button = $("#confirmPaymentButton");
  const shouldPrintReceipt = $("#checkoutPrintReceipt").checked;
  paymentSubmitting = true;
  button.disabled = true;
  button.textContent = "Сохраняем чек…";
  try {
    const payload = {
      ...orderContext(),
      payments,
      openOrderId: currentOpenOrderId,
      received,
      customerId: currentCustomer?.id || null,
      discountPercent: currentDiscountPercent(),
      comment: $("#orderComment").value.trim(),
      items: [...cart.values()].map((item) => ({ id: item.id, quantity: item.quantity, lotId: item.lotId }))
    };
    const prior = pendingPayment();
    const request = prior || {payload:{...payload,requestId:crypto.randomUUID()}};
    try{localStorage.setItem(paymentRetryKey(),JSON.stringify(request));}catch(error){if(!(window.OfflinePos?.status().ready&&window.OfflinePosCore?.eligible(request.payload)))throw error;}
    const response = await window.AshkanaApi.action("sale.create", request.payload);
    try{localStorage.removeItem(paymentRetryKey());}catch(_){/* The durable queue or server already confirmed this receipt. */}
    hydrateWorkspace(response);
    lastSale = sales.find((sale) => sale.id === response.entity?.id) || sales[0];
    closePayment();
    const paidSale = lastSale;
    startNewOrder();
    activeCategory = null;
    $("#searchInput").value = "";
    renderProducts();
    setTimeout(() => {
      if (shouldPrintReceipt) printReceipt(paidSale);
      if (terminalDeviceSettings.receiptPrinterMode !== "none" && terminalDeviceSettings.printKitchenTicket) printKitchenOrder(paidSale);
    }, 80);
  } catch (error) {
    if (error.status === 423) {
      closePayment();
      activeOperator = null;
      resetTransferHistory();
  refreshReceiving();
      showOperatorSelection();
      showPinError(error.message);
      return;
    }
    if ([401, 403].includes(error.status)) {
      sessionStorage.removeItem(authSessionKey);
      location.replace(terminalLoginUrl({ access: "changed" }));
      return;
    }
    if (error.status >= 400 && error.status < 500 && ![401,403,423].includes(error.status)) localStorage.removeItem(paymentRetryKey());
    showToast(error.message || "Не удалось сохранить чек");
  } finally {
    paymentSubmitting = false;
    button.textContent = "Подтвердить оплату";
    updatePaymentState();
  }
}

function startNewOrder() {
  configureOrderSettings(true);
  cart.clear();
  configureOrderSettings(true);
  currentCustomer = null;
  currentOpenOrderId = null;
  $("#orderComment").value = "";
  renderCart();
  renderHistory();
  renderOpenOrders();
  window.mobilePosView?.("orders");
}

function closeDrawer(selector) {
  if (selector === "#supplyDrawer") { window.SupplyPhotos?.close(); resetPosSupplyImport(); }
  $(selector)?.classList.add("hidden");
}

function orderTotal(order) {
  let discountable = 0;
  const subtotal = (order.items || []).reduce((sum, row) => {
    const product = products.find((entry) => entry.id === String(row.id));
    const lineTotal = Number(product?.price || 0) * Number(row.quantity || 0);
    if (!product?.noDiscount) discountable += lineTotal;
    return sum + lineTotal;
  }, 0);
  const settings = posCompanySettings();
  const base = Math.round((subtotal - discountable * Number(order.discountPercent || 0) / 100) * 100) / 100;
  const service = (order.applyService ?? settings.general.serviceDefault) ? Math.round(base * settings.general.servicePercent) / 100 : 0;
  const area = settings.delivery.areas.find(row => row.name === order.deliveryArea);
  const delivery = order.orderType === "delivery" && area && !(area.freeFrom > 0 && base >= area.freeFrom) ? Number(area.cost) : 0;
  const total = Math.round((base + service + delivery) * 100) / 100;
  return settings.general.roundTotal ? Math.floor(total) : total;
}

function renderOpenOrders() {
  const orders = posState.openOrders || [];
  $("#openOrdersCount").textContent = orders.length;
  $("#openOrdersCount").classList.toggle("hidden", !orders.length);
  $("#openOrdersList").innerHTML = orders.length ? orders.map((order) => {
    const date = new Date(order.updatedAt || order.createdAt);
    const quantity = (order.items || []).reduce((sum, item) => sum + Number(item.quantity || 0), 0);
    const delivery = posCompanySettings().delivery;
    const stages = ["new", ...(delivery.useReadyStatus ? ["ready"] : []), "en-route", ...(delivery.useDeliveredStatus ? ["delivered"] : [])];
    const next = order.orderType === "delivery" ? stages[stages.indexOf(order.status || "new") + 1] : null;
    const labels = { ready: "Готов", "en-route": "Передать курьеру", delivered: "Доставлен" };
    const due = order.dueAt ? new Date(order.dueAt).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "";
    return `<article class="open-order-card">
      <div><strong>${escapeHtml(order.label || order.number)}</strong><span>${escapeHtml(order.number)} · ${quantity} поз. · ${date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</span><small>${escapeHtml(order.customerName || "Без гостя")}${order.comment ? ` · ${escapeHtml(order.comment)}` : ""}</small></div>
      <b>${money(orderTotal(order))}</b><small>${escapeHtml(order.orderType === "delivery" ? `Доставка · ${order.deliveryArea}` : order.table || "")}${due ? ` · Готовность к ${due}` : ""}</small>${next ? `<button class="secondary-button" type="button" data-order-status="${next}" data-order-status-id="${escapeHtml(order.id)}">${labels[next]}</button>` : ""}
      <div class="open-order-actions"><button class="primary-button" data-open-order="${escapeHtml(order.id)}" type="button">Открыть</button><button class="danger-button" data-delete-order="${escapeHtml(order.id)}" type="button">Удалить</button></div>
    </article>`;
  }).join("") : `<div class="history-empty">Открытых заказов нет.</div>`;
}

async function saveOpenOrder(printByStation = false) {
  if (activeOperator?.staffRole === "production") return;
  if (!cart.size) return;
  const button = $("#saveOrderButton");
  button.disabled = true;
  try {
    const response = await window.AshkanaApi.action("pos.order.save", {
      ...orderContext(),
      id: currentOpenOrderId,
      label: currentCustomer?.name ? `Заказ · ${currentCustomer.name}` : `Заказ №${nextReceiptNumber()}`,
      customerId: currentCustomer?.id || null,
      discountPercent: currentDiscountPercent(),
      comment: $("#orderComment").value.trim(),
      items: [...cart.values()].map((item) => ({ id: item.id, quantity: item.quantity, lotId: item.lotId })),
    });
    hydrateWorkspace(response);
    cart.clear();
    configureOrderSettings(true);
    currentCustomer = null;
    currentOpenOrderId = null;
    $("#orderComment").value = "";
    renderWorkspace();
    showToast("Заказ сохранён в открытых чеках");
    if (printByStation === true) printKitchenOrder(posState.openOrders.find(order => order.id === response.entity?.id));
  } catch (error) {
    showToast(error.message || "Не удалось сохранить заказ");
  } finally {
    button.disabled = false;
  }
}

async function loadOpenOrder(orderId) {
  if (cart.size) { showToast("Сначала оплатите или отложите текущий заказ"); return; }
  const order = posState.openOrders.find((entry) => entry.id === orderId);
  if (!order) return;
  const restored = new Map();
  for (const row of order.items || []) {
    const product = products.find((entry) => entry.id === String(row.id)) || { id:String(row.id), name:row.name || 'Недоступная позиция', price:Number(row.price || 0), unit:row.unit || 'шт', available:0, kind:'product' };
    const lot = row.lotId ? product.availableLots?.find(lot=>lot.id===row.lotId) : null;
    const key=row.lotId ? product.id+'::'+row.lotId : product.id;
    restored.set(key, { ...product, cartKey:key, lotId:row.lotId || undefined, servingLine:lot ? `${lot.line} · ${lot.batchNumber}` : '', available:row.lotId ? Number(lot?.available || 0) : product.available, quantity:Number(row.quantity) });
  }
  try {
    cart = restored;
    currentCustomer = posState.customers.find((customer) => customer.id === order.customerId) || null;
    $("#orderComment").value = order.comment || "";
    $("#posOrderType").value = order.orderType || posCompanySettings().orders.defaultType;
    configureOrderSettings();
    $("#posOrderTable").value = order.table || "";
    $("#posDeliveryArea").value = order.deliveryArea || "";
    $("#posDeliveryAddress").value = order.deliveryAddress || "";
    $("#posDeliveryPhone").value = order.deliveryPhone || "";
    $("#posApplyService").checked = order.applyService ?? posCompanySettings().general.serviceDefault;
    currentOpenOrderId = order.id;
    closeDrawer("#openOrdersDrawer");
    window.mobilePosView?.("receipt");
    renderWorkspace();
    showToast(cartAvailabilityIssue() ? "Заказ открыт. Проверьте отмеченные позиции перед оплатой." : "Заказ открыт");
  } catch (error) {
    showToast(error.message || "Не удалось открыть заказ");
  }
}

async function deleteOpenOrder(orderId) {
  try {
    const response = await window.AshkanaApi.action("pos.order.remove", { id: orderId });
    hydrateWorkspace(response);
    renderOpenOrders();
    showToast("Открытый заказ удалён");
  } catch (error) {
    showToast(error.message || "Не удалось удалить заказ");
  }
}

function renderCustomers() {
  const query = $("#customerSearch").value.trim().toLowerCase();
  const customers = (posState.customers || []).filter((customer) => !query || `${customer.name} ${customer.phone}`.toLowerCase().includes(query));
  $("#customerList").innerHTML = customers.length ? customers.map((customer) => `
    <button class="customer-card ${currentCustomer?.id === customer.id ? "active" : ""}" data-customer-id="${escapeHtml(customer.id)}" type="button">
      <span><strong>${escapeHtml(customer.name)}</strong><small>${escapeHtml(customer.phone)} · ${Number(customer.visits || 0)} визитов</small></span>
      <b>${Number(customer.discountPercent || 0) ? `−${Number(customer.discountPercent)}%` : "Без скидки"}</b>
    </button>`).join("") : `<div class="history-empty">Гости не найдены.</div>`;
}

function selectCustomer(customerId) {
  currentCustomer = posState.customers.find((customer) => customer.id === customerId) || null;
  closeDrawer("#customerDrawer");
  renderCart();
}

async function createCustomer(event) {
  event.preventDefault();
  const submit = event.submitter;
  if (submit) submit.disabled = true;
  try {
    const response = await window.AshkanaApi.action("pos.customer.upsert", {
      name: $("#newCustomerName").value.trim(),
      phone: $("#newCustomerPhone").value.trim(),
      discountPercent: Number($("#newCustomerDiscount").value || 0),
    });
    hydrateWorkspace(response);
    currentCustomer = posState.customers.find((customer) => customer.id === response.entity?.id) || null;
    event.currentTarget.reset();
    $("#newCustomerDiscount").value = "0";
    closeDrawer("#customerDrawer");
    renderCart();
    showToast("Гость добавлен к заказу");
  } catch (error) {
    showToast(error.message || "Не удалось добавить гостя");
  } finally {
    if (submit) submit.disabled = false;
  }
}

function shiftSales() {
  return sales.filter((sale) => String(sale.shiftId) === String(activeShift?.id) && !sale.refundedAt);
}

function shiftRefunds() {
  return sales.filter((sale) => String(sale.refundShiftId) === String(activeShift?.id));
}

function shiftMovements() {
  return (posState.cashMovements || []).filter((movement) => String(movement.shiftId) === String(activeShift?.id));
}

function expectedShiftCash() {
  if (!activeShift) return 0;
  const cashSales = sales.filter((sale) => String(sale.shiftId) === String(activeShift.id)).reduce((sum, sale) => sum + salePaymentAmount(sale,"cash"), 0);
  const cashRefunds = shiftRefunds().reduce((sum, sale) => sum + salePaymentAmount(sale,"cash"), 0);
  const movements = shiftMovements();
  const deposits = movements.filter((movement) => movement.type === "deposit").reduce((sum, movement) => sum + Number(movement.amount || 0), 0);
  const withdrawals = movements.filter((movement) => ["expense", "collection"].includes(movement.type)).reduce((sum, movement) => sum + Number(movement.amount || 0), 0);
  return Number(activeShift.openingCash || 0) + cashSales - cashRefunds + deposits - withdrawals;
}

function renderCashDrawer() {
  const shiftSalesRows = shiftSales();
  const grossSales = sales.filter((sale) => String(sale.shiftId) === String(activeShift?.id)).reduce((sum, sale) => sum + Number(sale.total || 0), 0);
  const netSales = grossSales - shiftRefunds().reduce((sum, sale) => sum + Number(sale.total || 0), 0);
  $("#shiftSalesTotal").textContent = money(netSales);
  $("#shiftExpectedTotal").textContent = money(expectedShiftCash());
  $("#shiftReceiptCount").textContent = shiftSalesRows.length;
  const labels = { deposit: "Внесение", expense: "Расход", collection: "Инкассация" };
  const signs = { deposit: "+", expense: "−", collection: "−" };
  const movements = shiftMovements();
  $("#cashMovementList").innerHTML = movements.length ? movements.map((movement) => `
    <article class="cash-movement"><span><strong>${labels[movement.type]}</strong><small>${new Date(movement.createdAt).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })} · ${escapeHtml(movement.createdBy || "Кассир")}${movement.comment ? ` · ${escapeHtml(movement.comment)}` : ""}</small></span><b class="${movement.type === "deposit" ? "positive" : "negative"}">${signs[movement.type]}${money(movement.amount)}</b></article>`).join("") : `<div class="history-empty compact">Операций с наличными пока нет.</div>`;
}

function openCashDrawer() {
  if (!activeShift) { activateOperator(activeOperator, null); return; }
  renderCashDrawer();
  $("#cashOperationForm").classList.add("hidden");
  $("#cashDrawer").classList.remove("hidden");
}

function beginCashOperation(type) {
  if (!operatorCan("posCash")) { showToast("Кассовые операции не разрешены для этого сотрудника"); return; }
  const labels = { deposit: "Внесение наличных", expense: "Расход из кассы", collection: "Инкассация" };
  $("#cashOperationType").value = type;
  $("#cashOperationTitle").textContent = labels[type];
  $("#cashOperationAmount").value = "";
  $("#cashOperationComment").value = "";
  $("#cashOperationForm").classList.remove("hidden");
  setTimeout(() => $("#cashOperationAmount").focus(), 20);
}

async function submitCashOperation(event) {
  event.preventDefault();
  const button = event.submitter || $("#cashOperationForm button[type=submit]");
  if (button?.disabled) return;
  if (button) button.disabled = true;
  try {
    const response = await window.AshkanaApi.action("pos.cash.movement", {
      type: $("#cashOperationType").value,
      amount: Number($("#cashOperationAmount").value || 0),
      comment: $("#cashOperationComment").value.trim(),
    });
    hydrateWorkspace(response);
    $("#cashOperationForm").classList.add("hidden");
    renderCashDrawer();
    showToast("Кассовая операция проведена");
  } catch (error) {
    showToast(error.message || "Не удалось провести операцию");
  } finally {
    if (button) button.disabled = false;
  }
}

function printXReport() {
  if (!allowProtectedAction("reports")) return;
  const rows = sales.filter((sale) => String(sale.shiftId) === String(activeShift?.id));
  const refunds = shiftRefunds();
  const methods = ["cash","card","qr"].map((method) => ({ label: paymentLabels[method], total: rows.reduce((sum, sale) => sum + salePaymentAmount(sale,method), 0) - refunds.reduce((sum, sale) => sum + salePaymentAmount(sale,method), 0) }));
  const printArea = document.createElement("section");
  printArea.id = "posPrintArea";
  printArea.innerHTML = `<h1>X‑отчёт</h1><p>${escapeHtml(branchById(currentSession?.branchId)?.name || "Заведение")}</p><p>Касса: ${escapeHtml(currentSession?.registerName || "Касса")}<br>Кассир: ${escapeHtml(activeOperator?.name || "—")}<br>${new Date().toLocaleString("ru-RU")}</p><hr>${methods.map((entry) => `<p>${entry.label}<b>${money(entry.total)}</b></p>`).join("")}<hr><p>Чеков<b>${rows.length}</b></p><p>Возвратов<b>${refunds.length}</b></p><p>Ожидается наличными<b>${money(expectedShiftCash())}</b></p><small>X‑отчёт не закрывает смену</small>`;
  return submitPrintJob(printArea.innerHTML, "Oimo — X-отчёт");
}

function kitchenOrderHtml(order) {
  const groups = new Map();
  for (const line of order?.items || []) {
    const product = products.find(item => item.id === String(line.id));
    const stationName = line.station ?? product?.station ?? "";
    const station = (workspaceState.stations || []).find(row => row.name === stationName && String(row.branchId) === String(order.branchId));
    const destination = line.destination ?? station?.destination ?? "Без печати";
    if (!stationName || destination === "Без печати") continue;
    const key = `${stationName} · ${destination}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({...line, name:line.name || product?.name || line.id});
  }
  return [...groups].map(([route,lines]) => `<section class="kitchen-print-ticket"><h1>${escapeHtml(route)}</h1><p>Заказ ${escapeHtml(order.number || order.id || "")}</p>${order.table ? `<p>Стол: ${escapeHtml(order.table)}</p>` : ""}${lines.map(line=>`<p><span>${escapeHtml(line.name)}</span><b>× ${Number(line.quantity)}</b></p>`).join("")}${order.comment ? `<hr><p>${escapeHtml(order.comment)}</p>` : ""}</section>`).join("");
}
function printKitchenOrder(order) {
  const html = kitchenOrderHtml(order);
  if (!html) { showToast("Нет позиций с маршрутом печати. Назначьте цех и его маршрут в меню."); return; }
  const area = document.createElement("section"); area.id = "posPrintArea"; area.innerHTML = html;
  return submitPrintJob(html, "Oimo — заказ на кухню");
}

function printReceipt(sale = lastSale) {
  if (!sale) { showToast("Нет чека для печати"); return; }
  const printArea = document.createElement("section");
  printArea.id = "posPrintArea";
  printArea.innerHTML = window.CompanySettings.receiptHtml(sale, workspaceState?.companySettings, branchById(sale.branchId) || {});
  if(sale.offlineStatus && sale.offlineStatus !== 'synced') printArea.innerHTML += `<hr><small>Автономный чек. Сохранён на устройстве, ожидает передачи в облако.<br>Код: ${escapeHtml(sale.requestId || sale.id)}</small>`;
  return submitPrintJob(printArea.innerHTML, `Oimo — чек №${sale.number || sale.id || ""}`);
}

function localDateTimeValue(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function supplyItemOptions(selected = "") {
  const groups = new Map();
  posSupplyContext.items.forEach((item) => {
    const category = item.category || "Без категории";
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(item);
  });
  return `<option value="">Выберите продукт…</option>${[...groups.entries()].map(([category, items]) => `<optgroup label="${escapeHtml(category)}">${items.map((item) => `<option value="${escapeHtml(item.id)}" ${String(item.id) === String(selected) ? "selected" : ""}>${escapeHtml(item.name)} · ${escapeHtml(item.unit)}</option>`).join("")}</optgroup>`).join("")}`;
}

function addPosSupplyLine(values = {}) {
  const rowId = `pos-supply-line-${++posSupplyLineSequence}`;
  const step = values.imported ? "any" : "0.001", priceStep = values.imported ? "any" : "0.01";
  $("#posSupplyLines").insertAdjacentHTML("beforeend", `<div class="supply-line" data-supply-line="${rowId}" ${values.imported ? 'data-supply-imported="true"' : ''}>
    <select data-supply-item ${values.imported ? '' : 'data-options-loaded="true"'} required>${values.imported ? supplyImportItemOptions(values.itemId) : supplyItemOptions(values.itemId)}</select>
    <div class="supply-number"><input aria-label="Количество" data-supply-quantity type="number" min="${values.imported ? '0' : '0.001'}" step="${step}" inputmode="decimal" value="${escapeHtml(values.quantity || "")}" required /><span data-supply-unit>ед.</span></div>
    <div class="supply-number"><input aria-label="Цена за единицу" data-supply-price type="number" min="${values.imported ? '0' : '0.01'}" step="${priceStep}" inputmode="decimal" value="${escapeHtml(values.price || "")}" required /><span>сом</span></div>
    <strong data-supply-row-total>0 сом</strong>
    <button class="icon-button danger-button remove-supply-line" data-remove-supply-line type="button" aria-label="Удалить позицию"><svg class="ui-icon"><use href="#pos-close"/></svg></button>
  </div>`);
  updatePosSupplyRow($("#posSupplyLines").lastElementChild, !values.price);
}

function currentPosSupplier() {
  return posSupplyContext.suppliers.find((supplier) => String(supplier.id) === $("#posSupplySupplier").value);
}

function updatePosSupplyRow(row, suggestPrice = false) {
  if (!row) return;
  const item = posSupplyContext.items.find((entry) => String(entry.id) === row.querySelector("[data-supply-item]").value);
  row.querySelector("[data-supply-unit]").textContent = item?.unit || "ед.";
  const priceInput = row.querySelector("[data-supply-price]");
  if (item && suggestPrice) {
    const supplierPrice = currentPosSupplier()?.prices?.[String(item.id)];
    priceInput.value = supplyMoney(supplierPrice || item.averageCost || 0) || "";
  }
  const total = Number(row.querySelector("[data-supply-quantity]").value || 0) * Number(priceInput.value || 0);
  row.querySelector("[data-supply-row-total]").textContent = money(total);
  updatePosSupplyTotal();
}

function supplyMoney(value) {
  const [coefficient, exponent = '0'] = String(Math.abs(Number(value))).split('e');
  return Math.sign(Number(value)) * Math.round(Number(`${coefficient}e${Number(exponent) + 2}`)) / 100;
}

function posSupplyTotal() {
  return supplyMoney([...document.querySelectorAll("#posSupplyLines .supply-line")].reduce((sum, row) => sum + Number(row.querySelector("[data-supply-quantity]").value || 0) * Number(row.querySelector("[data-supply-price]").value || 0), 0));
}

function updatePosSupplyTotal() {
  const total = posSupplyTotal();
  $("#posSupplyTotal").textContent = money(total);
  $("#posSupplyFooterTotal").textContent = money(total);
  $("#posSupplyPaidAmount").max = total;
  if ($("#posSupplyPaymentMode").value === "paid") $("#posSupplyPaidAmount").value = total || "";
}

function updatePosSupplyPayment() {
  const mode = $("#posSupplyPaymentMode").value;
  const needsPayment = mode !== "unpaid";
  $("#posSupplyAccountField").classList.toggle("hidden", !needsPayment);
  $("#posSupplyPaidField").classList.toggle("hidden", !needsPayment);
  $("#posSupplyPaidAmount").disabled = mode === "paid";
  if (mode === "paid") $("#posSupplyPaidAmount").value = posSupplyTotal() || "";
  if (mode === "unpaid") $("#posSupplyPaidAmount").value = "";
}

function renderPosRecentSupplies() {
  const rows = posSupplyContext.supplies || [];
  $("#posRecentSupplies").innerHTML = rows.length ? rows.map((supply) => {
    const status = supply.paymentStatus === "paid" ? "Оплачено" : supply.paymentStatus === "partial" ? `Долг ${money(supply.debt)}` : `Не оплачено · ${money(supply.debt)}`;
    return `<article class="recent-supply-row"><span><strong>${escapeHtml(supply.number)} · ${escapeHtml(supply.supplier)}</strong><small>${new Date(supply.receivedAt || supply.createdAt).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} · ${(supply.items || []).length} поз.</small>${supply.photo ? `<span class="supply-photo-history-links">${window.SupplyPhotos?.links(supply.photo) || ''}</span>` : ''}</span><span><b>${money(supply.total)}</b><small>${status}</small></span></article>`;
  }).join("") : `<div class="history-empty compact">На этой точке поставок ещё нет.</div>`;
}

function resetPosSupplyForm() {
  window.SupplyPhotos?.reset();
  resetPosSupplyImport();
  $("#posSupplyDate").value = localDateTimeValue();
  $("#posSupplyInvoice").value = "";
  $("#posSupplyComment").value = "";
  $("#posSupplyPaymentMode").value = "unpaid";
  $("#posSupplyPaidAmount").value = "";
  $("#posSupplyLines").innerHTML = "";
  addPosSupplyLine();
  updatePosSupplyPayment();
}

function renderPosSupplyContext() {
  $("#posSupplySupplier").innerHTML = posSupplyContext.suppliers.length ? posSupplyContext.suppliers.map((supplier) => `<option value="${escapeHtml(supplier.id)}">${escapeHtml(supplier.name)}</option>`).join("") : `<option value="">Нет поставщиков для точки</option>`;
  $("#posSupplyAccount").innerHTML = posSupplyContext.accounts.length ? posSupplyContext.accounts.map((account) => `<option value="${escapeHtml(account.id)}">${escapeHtml(account.name)}</option>`).join("") : `<option value="">Нет доступных счетов</option>`;
  resetPosSupplyForm();
  $("#savePosSupplyButton").disabled = !posSupplyContext.suppliers.length || !posSupplyContext.items.length;
  renderPosRecentSupplies();
}

async function openPosSupply() {
  if (!(await requireProductionShift())) return;
  if (!operatorCan("posSupply")) { showToast("Приёмка поставок не разрешена для этого сотрудника"); return; }
  const button = $("#supplyButton");
  button.disabled = true;
  try {
    posSupplyContext = await window.AshkanaApi.posSupplyContext();
    renderPosSupplyContext();
    restoreSupplyDraft();
    $("#supplyDrawer").classList.remove("hidden");
  } catch (error) {
    showToast(error.message || "Не удалось загрузить данные поставки");
  } finally {
    button.disabled = false;
  }
}

async function savePosSupply(event) {
  event.preventDefault();
  if ($("#savePosSupplyButton").disabled || posSupplyImportBusy || posSupplyImportData || posSupplySaving || window.SupplyPhotos?.blocksSave()) return;
  const rows = [...document.querySelectorAll("#posSupplyLines .supply-line")];
  const items = rows.map((row) => ({
    itemId: row.querySelector("[data-supply-item]").value,
    quantity: Number(row.querySelector("[data-supply-quantity]").value || 0),
    price: Number(row.querySelector("[data-supply-price]").value || 0),
  }));
  const total = posSupplyTotal();
  const mode = $("#posSupplyPaymentMode").value;
  const paidAmount = mode === "paid" ? total : mode === "partial" ? supplyMoney($("#posSupplyPaidAmount").value || 0) : 0;
  if (!items.length || items.some((item) => !item.itemId || !Number.isFinite(item.quantity) || !Number.isFinite(item.price) || item.quantity <= 0 || item.price <= 0)) { showToast("Проверьте позиции поставки"); return; }
  if (new Set(items.map((item) => item.itemId)).size !== items.length) { showToast("Одинаковые позиции объедините в одну строку"); return; }
  if (mode !== "unpaid" && !$("#posSupplyAccount").value) { showToast("Выберите счёт оплаты"); return; }
  if (mode === "partial" && (paidAmount <= 0 || paidAmount >= total)) { showToast("Частичная оплата должна быть меньше суммы поставки"); return; }
  const savedScope = supplyDraftKey();
  const submittedPhoto = JSON.parse(JSON.stringify(window.SupplyPhotos?.snapshot() || null));
  const button = $("#savePosSupplyButton");
  posSupplySaving = true;
  updatePosSupplyImportControls();
  button.disabled = true;
  button.textContent = "Принимаем…";
  try {
    const response = await window.AshkanaApi.action("supply.create", {
      supplierId: $("#posSupplySupplier").value,
      invoiceNumber: $("#posSupplyInvoice").value.trim(),
      receivedAt: new Date($("#posSupplyDate").value).toISOString(),
      comment: $("#posSupplyComment").value.trim(),
      items,
      ...(window.SupplyPhotos?.payload() || {}),
      payments: paidAmount > 0 ? [{ accountId: $("#posSupplyAccount").value, amount: paidAmount, occurredAt: new Date($("#posSupplyDate").value).toISOString() }] : [],
    });
    const nextPhotoDocument = window.SupplyPhotos?.afterSaved(submittedPhoto);
    sessionStorage.removeItem(savedScope);
    if (savedScope !== supplyDraftKey()) {
      if (nextPhotoDocument) sessionStorage.setItem(savedScope, JSON.stringify({fields: {}, rows: [], photo: nextPhotoDocument}));
      return; // The response belongs to the operator who submitted this supply.
    }
    hydrateWorkspace(response);
    // Clear committed rows and persist the next invoice before any await, so
    // closing the drawer cannot save the next photo together with old rows.
    renderPosSupplyContext();
    window.SupplyPhotos?.restore(nextPhotoDocument);
    if (nextPhotoDocument) persistSupplyDraft(true);
    renderWorkspace();
    showToast("Поставка принята, остатки обновлены");
    try {
      const refreshed = await window.AshkanaApi.posSupplyContext();
      if (savedScope === supplyDraftKey()) { posSupplyContext = refreshed; renderPosRecentSupplies(); }
    } catch { /* Keep the previous history: POS workspace omits supply records. */ }
  } catch (error) {
    showToast(error.message || "Не удалось принять поставку");
  } finally {
    posSupplySaving = false;
    updatePosSupplyImportControls();
    button.textContent = "Принять поставку";
  }
}

function updatePosSupplyImportControls() {
  const photoBusy = Boolean(window.SupplyPhotos?.blocksSave());
  $("#posSupplyImportButton").disabled = posSupplyImportBusy || posSupplySaving || photoBusy;
  $("#posSupplyImportFile").disabled = posSupplyImportBusy || posSupplySaving || photoBusy;
  $("#savePosSupplyButton").disabled = posSupplySaving || posSupplyImportBusy || Boolean(posSupplyImportData) || photoBusy || !posSupplyContext.suppliers.length || !posSupplyContext.items.length;
  window.SupplyPhotos?.updateControls();
}

function resetPosSupplyImport() {
  posSupplyImportRequest++;
  posSupplyImportData = null;
  posSupplyImportBusy = false;
  $("#posSupplyImportFile").value = "";
  $("#posSupplyImportPreview").classList.add("hidden");
  $("#posSupplyImportRows").innerHTML = "";
  $("#posSupplyImportError").textContent = "";
  $("#posSupplyImportStatus").textContent = "";
  $("#posSupplyImportApply").disabled = true;
  updatePosSupplyImportControls();
}

function supplyImportUnit(value) {
  const unit = String(value || "").trim().toLocaleLowerCase('ru-RU').replace(/\./g, '').replace(/\s+/g, ' ');
  const units = {
    'кг': ['weight', 1], 'kg': ['weight', 1], 'килограмм': ['weight', 1], 'килограммы': ['weight', 1],
    'г': ['weight', 0.001], 'гр': ['weight', 0.001], 'g': ['weight', 0.001], 'грамм': ['weight', 0.001],
    'л': ['volume', 1], 'l': ['volume', 1], 'литр': ['volume', 1],
    'мл': ['volume', 0.001], 'ml': ['volume', 0.001],
    'шт': ['piece', 1], 'штука': ['piece', 1], 'штук': ['piece', 1], 'pcs': ['piece', 1], 'pc': ['piece', 1],
  };
  return {key: unit, dimension: units[unit]?.[0], scale: units[unit]?.[1]};
}

function supplyImportValues(row, itemId) {
  const item = posSupplyContext.items.find(item => String(item.id) === String(itemId));
  if (!item) return {error: 'Выберите позицию'};
  const source = supplyImportUnit(row.unit), target = supplyImportUnit(item.unit);
  let factor = 1;
  if (source.key && source.key !== target.key) {
    if (!source.dimension || source.dimension !== target.dimension) return {error: `В файле: ${row.unit}. В Oimo: ${item.unit}`};
    factor = source.scale / target.scale;
  }
  const quantity = Number((Number(row.quantity) * factor).toPrecision(14));
  const price = Number((Number(row.price) / factor).toPrecision(14));
  if (![quantity, price, quantity * price].every(Number.isFinite) || quantity <= 0 || price <= 0) return {error: 'Проверьте количество и цену'};
  return {itemId: String(item.id), quantity, price, unit: item.unit, imported: true};
}

function selectedPosSupplyImportItems() {
  if (!posSupplyImportData) return [];
  return posSupplyImportData.rows.map((row, index) => supplyImportValues(row, $(`#posSupplyImportRows [data-supply-import-row="${index}"] select`).value));
}

function updatePosSupplyImportPreview() {
  if (!posSupplyImportData) return;
  const items = selectedPosSupplyImportItems();
  items.forEach((item, index) => {
    const row = $(`#posSupplyImportRows [data-supply-import-row="${index}"]`);
    row.classList.toggle('needs-mapping', Boolean(item.error));
    const hint = row.querySelector('[data-supply-import-hint]');
    hint.textContent = item.error || `${Number(item.quantity).toLocaleString('ru-RU', {maximumFractionDigits: 6})} ${item.unit} × ${money(item.price)}`;
  });
  const invalid = items.filter(item => item.error).length;
  $("#posSupplyImportSummary").textContent = `${items.length} поз. · ${money(posSupplyImportData.total)}${invalid ? ` · Проверьте: ${invalid}` : ''}`;
  $("#posSupplyImportApply").disabled = posSupplyImportBusy || !items.length || Boolean(invalid);
  updatePosSupplyImportControls();
}

function supplyImportItemOptions(itemId) {
  const item = posSupplyContext.items.find(item => String(item.id) === String(itemId));
  return '<option value="">Выберите позицию…</option>' + (item ? `<option value="${escapeHtml(item.id)}" selected>${escapeHtml(item.name)} · ${escapeHtml(item.unit)}</option>` : '');
}

function expandSupplyImportOptions(event) {
  const select = event.target.closest('[data-supply-import-item],[data-supply-item]');
  if (!select || select.dataset.optionsLoaded) return;
  const selected = select.value;
  select.innerHTML = supplyItemOptions(selected);
  select.dataset.optionsLoaded = 'true';
}

async function importPosSupplyFile(file) {
  if (!file || posSupplyImportBusy || posSupplySaving || window.SupplyPhotos?.blocksSave() || !operatorCan('posSupply')) return;
  resetPosSupplyImport();
  const errorElement = $("#posSupplyImportError");
  if (!/\.(xlsx|csv)$/i.test(file.name)) { errorElement.textContent = 'Выберите файл Excel (.xlsx) или CSV'; return; }
  if (!file.size || file.size > 2000000) { errorElement.textContent = 'Файл должен быть не пустым и не больше 2 МБ'; return; }
  const request = ++posSupplyImportRequest, actor = activeOperator?.id, scope = supplyDraftKey();
  const isCurrent = () => request === posSupplyImportRequest && actor === activeOperator?.id && scope === supplyDraftKey() && !$("#supplyDrawer").classList.contains('hidden');
  posSupplyImportBusy = true;
  $("#posSupplyImportStatus").textContent = 'Читаем файл…';
  updatePosSupplyImportControls();
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
    if (!isCurrent()) return;
    const data = await window.AshkanaApi.previewSupplyImport({file: btoa(binary), fileName: file.name});
    if (!isCurrent()) return;
    if (!Array.isArray(data.rows) || !data.rows.length) throw new Error('В файле нет позиций поставки');
    posSupplyImportData = data;
    $("#posSupplyImportFileName").textContent = file.name;
    $("#posSupplyImportRows").innerHTML = data.rows.map((row, index) => `<div class="pos-supply-import-row" data-supply-import-row="${index}"><div><strong>${escapeHtml(row.name)}</strong><small>Строка ${escapeHtml(row.row)} · ${escapeHtml(Number(row.quantity).toLocaleString('ru-RU', {maximumFractionDigits: 6}))} ${escapeHtml(row.unit)} · ${escapeHtml(money(row.total))}</small></div><div><select data-supply-import-item aria-label="Позиция Oimo для ${escapeHtml(row.name)}">${supplyImportItemOptions(row.itemId)}</select><small data-supply-import-hint></small></div></div>`).join('');
    $("#posSupplyImportPreview").classList.remove('hidden');
    $("#posSupplyImportRows").scrollTop = 0;
    $("#posSupplyImportStatus").textContent = '';
    $("#posSupplyImportPreview").scrollIntoView({block: 'nearest'});
  } catch (error) {
    if (isCurrent()) { errorElement.textContent = error.message || 'Не удалось прочитать файл'; $("#posSupplyImportStatus").textContent = ''; }
  } finally {
    if (request === posSupplyImportRequest) {
      posSupplyImportBusy = false;
      updatePosSupplyImportControls();
      updatePosSupplyImportPreview();
    }
  }
}

function applyPosSupplyImport() {
  if (!posSupplyImportData || posSupplyImportBusy || posSupplySaving || !operatorCan('posSupply')) return;
  const imported = selectedPosSupplyImportItems();
  if (!imported.length || imported.some(item => item.error)) return;
  $("#posSupplyImportError").textContent = '';
  const existing = [...$("#posSupplyLines").querySelectorAll('.supply-line')].map(row => ({
    itemId: row.querySelector('[data-supply-item]').value,
    quantity: Number(row.querySelector('[data-supply-quantity]').value),
    price: Number(row.querySelector('[data-supply-price]').value),
  })).filter(item => item.itemId || item.quantity || item.price);
  if (existing.some(item => !item.itemId || ![item.quantity, item.price].every(Number.isFinite) || item.quantity <= 0 || item.price <= 0)) {
    $("#posSupplyImportError").textContent = 'Заполните или удалите незавершённые позиции в поставке';
    return;
  }
  const merged = new Map();
  for (const item of [...existing, ...imported]) {
    const previous = merged.get(item.itemId);
    if (!previous) merged.set(item.itemId, {...item, imported: true});
    else {
      const quantity = Number((previous.quantity + item.quantity).toPrecision(14));
      const price = (previous.quantity * previous.price + item.quantity * item.price) / quantity;
      merged.set(item.itemId, {...previous, quantity, price});
    }
  }
  const count = imported.length;
  const total = posSupplyImportData.total;
  $("#posSupplyLines").innerHTML = '';
  for (const item of merged.values()) addPosSupplyLine(item);
  resetPosSupplyImport();
  updatePosSupplyTotal();
  persistSupplyDraft();
  $("#posSupplyImportStatus").textContent = `Добавлено из файла: ${count} поз. · ${money(total)}`;
}

function downloadPosSupplyTemplate() {
  const csv = '\uFEFFНаименование;Количество;Цена за единицу;Ед. изм.\r\n';
  const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8'}));
  const link = document.createElement('a');
  link.href = url; link.download = 'Шаблон поставки Oimo.csv'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

let archiveFilter = "all";
let archiveDateInitialized = false;
let archiveShifts = [];
let archiveShiftGeneration = 0;
let archiveShiftDefaulted = false;
let archiveShiftLoading = false;
function historyShiftKey(shift) {
  return shift?.id != null ? `${shift.kind || 'cash'}:${shift.id}` : 'unassigned';
}
function historyShiftTitle(shift) {
  if (!shift) return 'Без привязки к смене';
  return shift.number != null ? `Смена №${shift.number}` : 'Смена';
}
function historyShiftCaption(shift) {
  if (!shift) return 'У старой записи не сохранена смена';
  const period = shift.openedAt ? `${transferHistoryDate(shift.openedAt)} — ${shift.closedAt ? transferHistoryDate(shift.closedAt) : shift.status === 'closed' ? 'закрыта' : 'открыта'}` : 'Время смены не сохранено';
  return [period, shift.employeeName, shift.registerName].filter(Boolean).join(' · ');
}
function historyShiftOptions(select, shifts, currentId, kind = 'cash', extras = []) {
  const selected = select.value;
  const options = new Map(shifts.map(shift => [historyShiftKey(shift), shift]));
  select.innerHTML = '<option value="all">Все смены</option>' + [...options.values()]
    .sort((a, b) => (Date.parse(b.openedAt) || 0) - (Date.parse(a.openedAt) || 0))
    .map(shift => `<option value="${escapeHtml(historyShiftKey(shift))}">${escapeHtml([String(shift.id) === String(currentId) && shift.kind === kind ? 'Текущая' : '', historyShiftTitle(shift), shift.openedAt ? transferHistoryDate(shift.openedAt) : '', shift.employeeName].filter(Boolean).join(' · '))}</option>`).join('')
    + extras.map(([key, title]) => `<option value="${escapeHtml(key)}">${escapeHtml(title)}</option>`).join('');
  select.value = [...select.options].some(option => option.value === selected) ? selected : 'all';
}
function historyShiftGroups(rows, describe, renderRow) {
  const groups = new Map();
  for (const row of rows) {
    const group = describe(row);
    if (!groups.has(group.key)) groups.set(group.key, {...group, rows: []});
    groups.get(group.key).rows.push(row);
  }
  return [...groups.values()].sort((a, b) => {
    if (a.key === 'pending' || b.key === 'pending') return a.key === b.key ? 0 : a.key === 'pending' ? -1 : 1;
    return (Date.parse(b.shift?.openedAt) || 0) - (Date.parse(a.shift?.openedAt) || 0);
  }).map(group => `<section class="history-shift-group" data-history-shift="${escapeHtml(group.key)}"><header><strong>${escapeHtml(group.title || historyShiftTitle(group.shift))}</strong><small>${escapeHtml(group.caption ?? historyShiftCaption(group.shift))}</small><span>Записей: ${group.rows.length}</span></header>${group.rows.map(renderRow).join('')}</section>`).join('');
}
function receiptHistoryShift(sale) {
  if (sale.shiftId == null) return null;
  return archiveShifts.find(shift => String(shift.id) === String(sale.shiftId)) || (activeShift && String(activeShift.id) === String(sale.shiftId) ? {...activeShift, kind:'cash', number:activeShift.id, employeeName:activeShift.openedBy} : null) || {
    id: sale.shiftId, kind: 'cash', number: sale.shiftId,
  };
}
function receiptHistoryGroup(sale) {
  const shift = receiptHistoryShift(sale);
  if (shift) return {key: historyShiftKey(shift), shift};
  if (sale.paymentMethod === 'external' || sale.source === 'external') return {key:'external', title:'Импорт из другой кассы', caption:'По дате исходного отчёта'};
  return {key:'unassigned', shift:null};
}
function resetReceiptHistory() {
  archiveShiftGeneration++;
  archiveShiftLoading = false;
  archiveShiftDefaulted = false;
  archiveShifts = [];
  $('#archiveShift').innerHTML = '<option value="all">Все смены</option>';
  $('#archiveShiftMessage').textContent = '';
  $('#archiveDate').value = '';
  $('#archiveSearch').value = '';
  selectedReceiptId = null;
}
async function refreshReceiptShifts() {
  if (!activeOperator || !window.AshkanaApi.posShiftHistory || archiveShiftLoading) return;
  const generation = archiveShiftGeneration, actor = activeOperator.id;
  archiveShiftLoading = true;
  $('#archiveShiftMessage').textContent = 'Загрузка смен…';
  try {
    const data = await window.AshkanaApi.posShiftHistory();
    if (generation !== archiveShiftGeneration || activeOperator?.id !== actor) return;
    archiveShifts = data.shifts || [];
    $('#archiveShiftMessage').textContent = '';
    renderHistory();
  } catch (error) {
    if (generation === archiveShiftGeneration) $('#archiveShiftMessage').textContent = `Не удалось загрузить смены. ${error.message}`;
  } finally {
    if (generation === archiveShiftGeneration) archiveShiftLoading = false;
  }
}
function historyTimeZone() {
  const timeZone = workspaceState?.companySettings?.general?.timezone;
  return timeZone ? {timeZone} : {};
}
function archiveDay(value, originalReport = false) {
  if (originalReport && /^\d{4}-\d{2}-\d{2}T/.test(String(value))) return String(value).slice(0,10);
  const d = new Date(value);
  if (!Number.isFinite(d.getTime())) return '';
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {...historyTimeZone(), year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(d).map(part => [part.type,part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}
function receiptHistoryDate(sale) {
  return sale.paymentMethod === 'external' || sale.source === 'external' ? archiveDay(sale.createdAt, true).split('-').reverse().join('.') + ' · Импорт' : transferHistoryDate(sale.createdAt);
}
function renderHistory() {
  if (!archiveDateInitialized) { $("#archiveDate").value='';archiveDateInitialized=true; }
  const choices = [...archiveShifts];
  if (activeShift && !choices.some(shift => String(shift.id) === String(activeShift.id))) choices.push({...activeShift, kind:'cash', number:activeShift.id, employeeName:activeShift.openedBy});
  for (const sale of sales) if (sale.shiftId != null && !choices.some(shift => String(shift.id) === String(sale.shiftId))) choices.push(receiptHistoryShift(sale));
  historyShiftOptions($('#archiveShift'), choices, activeShift?.id, 'cash', [['external','Импорт из другой кассы'], ['unassigned','Без привязки к смене']]);
  if (!archiveShiftDefaulted && activeOperator) {
    if (activeShift && window.AshkanaApi.posShiftHistory) $('#archiveShift').value = `cash:${activeShift.id}`;
    archiveShiftDefaulted = true;
  }
  const shiftFilter = $('#archiveShift').value;
  const query=$("#archiveSearch").value.trim().toLocaleLowerCase();
  const day=$("#archiveDate").value;
  const filtered=sales.filter(sale=>(shiftFilter === 'all' || receiptHistoryGroup(sale).key === shiftFilter) && (!day || archiveDay(sale.createdAt, sale.paymentMethod === 'external' || sale.source === 'external')===day) && (archiveFilter==='all' || archiveFilter==='refund' ? archiveFilter!=='refund'||Boolean(sale.refundedAt) : !sale.refundedAt&&salePaymentAmount(sale,archiveFilter)>0) && (!query || [sale.number,sale.offlineNumber,sale.requestId,sale.cashier,...(sale.items||[]).map(item=>item.name)].join(' ').toLocaleLowerCase().includes(query))).sort((a,b)=>new Date(b.createdAt)-new Date(a.createdAt));
  const completed=filtered.filter(sale=>!sale.refundedAt);
  $("#salesCount").textContent=filtered.length;
  $("#salesTotal").textContent=money(completed.reduce((sum,sale)=>sum+Number(sale.total||0),0));
  if (!filtered.some(sale=>sale.id===selectedReceiptId)) selectedReceiptId=filtered[0]?.id || null;
  $("#historyList").innerHTML=historyShiftGroups(filtered, receiptHistoryGroup, sale=>`<button class="archive-receipt ${sale.id===selectedReceiptId?'active':''}" data-receipt-id="${escapeHtml(sale.id)}" aria-pressed="${sale.id===selectedReceiptId}" type="button"><span><strong>№ ${escapeHtml(sale.number)}</strong><b>${money(sale.total)}</b></span><small>${escapeHtml((sale.items||[]).map(item=>item.name).join(', '))}</small><small>${escapeHtml(receiptHistoryDate(sale))}${sale.offlineNumber?' · '+escapeHtml(sale.offlineNumber):''}${sale.refundedAt?' · Возврат':''}</small></button>`) || '<p class="history-empty">В этой смене чеков нет</p>';
  const sale=filtered.find(sale=>sale.id===selectedReceiptId);
  if (!sale) { $("#archiveDetails").innerHTML='<p class="history-empty">Выберите другую смену или измените фильтр</p>';return; }
  const line=(label,value)=>`<div class="archive-total-line"><span>${label}</span><strong>${value}</strong></div>`;
  $("#archiveDetails").innerHTML=`<header class="archive-detail-header"><h2>Чек №${escapeHtml(sale.number)}</h2><button id="archivePrint" class="secondary-button" type="button">Печать чека</button><span>${sale.refundedAt?'Возврат':'Оплачен'}</span></header><dl class="archive-meta"><dt>Кассир</dt><dd>${escapeHtml(sale.cashier||'Не указан')}</dd>${sale.openedAt?`<dt>Открыт</dt><dd>${escapeHtml(new Date(sale.openedAt).toLocaleString('ru-RU'))}</dd>`:''}<dt>Закрыт</dt><dd>${escapeHtml(receiptHistoryDate(sale))}</dd>${sale.customerName?`<dt>Гость</dt><dd>${escapeHtml(sale.customerName)}</dd>`:''}${sale.table?`<dt>Стол</dt><dd>${escapeHtml(sale.table)}</dd>`:''}</dl><div class="archive-items"><table><thead><tr><th>Наименование</th><th>Кол-во</th><th>Цена</th><th>Итого</th></tr></thead><tbody>${(sale.items||[]).map(item=>`<tr><td>${escapeHtml(item.name)}</td><td>${Number(item.quantity).toLocaleString('ru-RU')} ${escapeHtml(item.unit||'')}</td><td>${money(item.price)}</td><td>${money(Number(item.price)*Number(item.quantity))}</td></tr>`).join('')}</tbody></table></div><div class="archive-totals">${sale.discountAmount?line('Скидка','−'+money(sale.discountAmount)):''}${sale.serviceAmount?line('Обслуживание',money(sale.serviceAmount)):''}${sale.deliveryAmount?line('Доставка',money(sale.deliveryAmount)):''}${sale.rounding?line('Округление','−'+money(sale.rounding)):''}${line('Итого',money(sale.total))}</div><h3>Оплата</h3>${salePaymentParts(sale).filter(part=>Number(part.amount)>0).map(part=>line(escapeHtml(paymentLabels[part.method] || part.method),money(part.amount))).join('')}${Number(sale.change)>0?line('Сдача',money(sale.change)):''}${sale.comment?`<p class="archive-comment">${escapeHtml(sale.comment)}</p>`:''}${sale.refundedAt?`<p class="archive-refund">Возврат · ${escapeHtml(new Date(sale.refundedAt).toLocaleString('ru-RU'))}<br>${escapeHtml(sale.refundedBy||'')} · ${escapeHtml(sale.refundReason||'')}</p>`:sale.paymentMethod !== 'external' && operatorCan('posRefunds')?`<details class="archive-refund"><summary>Оформить возврат</summary><form data-refund-form="${escapeHtml(sale.id)}"><input name="reason" required maxlength="200" placeholder="Причина возврата"><button class="danger-button" type="submit">Подтвердить возврат</button></form></details>`:''}`;
  const historyGroup = receiptHistoryGroup(sale);
  $('#archiveDetails .archive-meta').insertAdjacentHTML('afterbegin', `<dt>Смена</dt><dd>${escapeHtml(historyGroup.title || historyShiftTitle(historyGroup.shift))}<small class="archive-shift-caption">${escapeHtml(historyGroup.caption ?? historyShiftCaption(historyGroup.shift))}</small></dd>`);
}

async function refundSale(event) {
  const form = event.target.closest("[data-refund-form]");
  if (!form) return;
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await window.AshkanaApi.action("sale.refund", { id: form.dataset.refundForm, reason: new FormData(form).get("reason") });
    hydrateWorkspace(response);
    renderWorkspace();
    renderCashDrawer();
    showToast("Возврат оформлен, остатки восстановлены");
  } catch (error) {
    showToast(error.message || "Не удалось оформить возврат");
  } finally {
    button.disabled = false;
  }
}

function renderWorkspace() {
  renderCategories();
  renderProducts();
  renderCart();
  renderHistory();
  renderOpenOrders();
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 3000);
}

function terminalSettingsKey() {
  return `ashkana-pos-device-settings-v1-${currentSession?.registerId || "terminal"}`;
}

function normalizeTerminalDeviceSettings(raw) {
  return window.OimoPrinting?.normalize(raw) || { ...terminalDeviceDefaults, ...raw };
}

function loadTerminalSettings() {
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(terminalSettingsKey()) || "{}"); } catch {}
  terminalDeviceSettings = normalizeTerminalDeviceSettings(stored || {});
  $("#receiptPrinterMode").value = terminalDeviceSettings.receiptPrinterMode;
  const selector = $("#receiptPrinterName");
  selector.replaceChildren(new Option("Выберите принтер", ""));
  if (terminalDeviceSettings.receiptPrinterName) selector.add(new Option(terminalDeviceSettings.receiptPrinterName, terminalDeviceSettings.receiptPrinterName));
  selector.value = terminalDeviceSettings.receiptPrinterName;
  $("#receiptPaperWidth").value = terminalDeviceSettings.receiptPaperWidth;
  $("#receiptDots").value = terminalDeviceSettings.receiptDots;
  $("#receiptCutPaper").checked = terminalDeviceSettings.receiptCutPaper;
  $("#autoPrintReceipt").checked = Boolean(terminalDeviceSettings.autoPrintReceipt);
  $("#printKitchenTicket").checked = Boolean(terminalDeviceSettings.printKitchenTicket);
  $("#printerStatus").textContent = "";
  updatePrinterControls();
}

function printerSettingsFromForm() {
  return normalizeTerminalDeviceSettings({
    receiptPrinterMode: $("#receiptPrinterMode").value,
    receiptPrinterName: $("#receiptPrinterName").value,
    receiptPaperWidth: $("#receiptPaperWidth").value,
    receiptDots: $("#receiptDots").value,
    receiptCutPaper: $("#receiptCutPaper").checked,
    autoPrintReceipt: $("#autoPrintReceipt").checked,
    printKitchenTicket: $("#printKitchenTicket").checked,
  });
}

function updatePrinterControls() {
  const mode = $("#receiptPrinterMode").value;
  $("#qzPrinterControls").hidden = !["qz", "escpos"].includes(mode);
  $("#escposPrinterOptions").hidden = mode !== "escpos";
  $("#printerModeHint").textContent = mode === "browser" ? "Принтер и соответствующий размер бумаги выбираются в системном окне печати." : mode === "none" ? "Автоматическая и ручная печать отключены на этом устройстве." : "Найдите принтеры на этой кассе, выберите устройство и напечатайте пробный чек.";
  $("#autoPrintReceipt").disabled = mode === "none";
  $("#printKitchenTicket").disabled = mode === "none";
}

function saveTerminalSettings() {
  const settings = printerSettingsFromForm();
  if (["qz", "escpos"].includes(settings.receiptPrinterMode) && !settings.receiptPrinterName) {
    $("#printerStatus").textContent = "Сначала найдите и выберите принтер.";
    return;
  }
  try { localStorage.setItem(terminalSettingsKey(), JSON.stringify(settings)); }
  catch (_) { $("#printerStatus").textContent = "Браузер не разрешил сохранить настройки. Проверьте доступ к локальному хранилищу."; return; }
  terminalDeviceSettings = settings;
  $("#terminalSettingsDrawer").classList.add("hidden");
  showToast("Настройки печати сохранены для этой кассы в этом браузере");
}

async function submitPrintJob(html, title, settings = terminalDeviceSettings) {
  try {
    if (!window.OimoPrinting) throw new Error("Модуль печати не загрузился. Обновите страницу.");
    const result = await window.OimoPrinting.print(html, settings, title);
    const message = result.status === "queued" ? "Задание передано в очередь принтера. Проверьте бумажный чек." : "Окно печати закрыто. Проверьте, напечатался ли чек.";
    $("#printerStatus").textContent = message;
    return result;
  } catch (error) {
    const message = "Печать не подтверждена. " + (error.message || "Проверьте принтер и очередь печати перед повтором.");
    $("#printerStatus").textContent = message;
    $("#printErrorText").textContent = message;
    $("#printErrorNotice").classList.remove("hidden");
    return { status: "error" };
  }
}

function openTerminalSettings() {
  loadTerminalSettings();
  $("#settingsRegisterName").textContent = currentSession?.registerName || "Касса";
  $("#settingsBranchName").textContent = branchById(currentSession?.branchId)?.name || currentSession?.scope || "Заведение";
  $("#settingsAccountLogin").textContent = `Аккаунт ${currentSession?.tenantSlug || "—"}`;
  $("#terminalSettingsDrawer").classList.remove("hidden");
}

function closeTerminalSettings() {
  $("#terminalSettingsDrawer").classList.add("hidden");
}

async function syncTerminalWorkspace() {
  const button = $("#syncTerminalButton");
  button.disabled = true;
  try {
    const response = await window.AshkanaApi.workspace();
    if (!hydrateWorkspace(response)) throw new Error("Не удалось обновить данные");
    renderWorkspace();
    closeTerminalSettings();
    showToast("Меню, цены и остатки обновлены");
  } catch (error) {
    showToast(error.message || "Не удалось обновить данные");
  } finally {
    button.disabled = false;
  }
}

function terminalLoginUrl(extra = {}) {
  const params = new URLSearchParams({ mode: "pos", ...extra });
  if (currentSession?.tenantSlug) params.set("login", currentSession.tenantSlug);
  if (currentSession?.registerId) params.set("register", currentSession.registerId);
  return `/login?${params.toString()}`;
}

function tickClock() {
  $("#clock").textContent = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function renderPinDots() {
  $("#pinDots").querySelectorAll("i").forEach((dot, index) => dot.classList.toggle("filled", index < pinValue.length));
  $("#pinDots").setAttribute("aria-label", `Введено цифр: ${pinValue.length}`);
}

function showPinError(message = "") {
  $("#pinError").textContent = message;
  $("#pinError").classList.toggle("hidden", !message);
}

function showOperatorSelection() {
  $("#operatorStepKitchen").classList.add("hidden");
  pinValue = "";
  showPinError();
  renderPinDots();
  $("#operatorStepPin").classList.remove("hidden");
  $("#operatorStepShift").classList.add("hidden");
  $("#operatorLock").classList.remove("hidden");
  renderCart();
}

function updateShiftHeader() {
  if (!activeShift) {
    $("#shiftStatus").textContent = "Смена не открыта";
    $("#shiftCaption").textContent = "нажмите, чтобы открыть";
    return;
  }
  $("#shiftStatus").textContent = "Смена открыта";
  $("#shiftCaption").textContent = `с ${new Date(activeShift.openedAt).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`;
}

function activateOperator(operator, shift = null) {
  setTimeout(()=>window.OfflinePos?.prepare(),0);
  window.AshkanaApi?.setOperationActor?.(operator?.id);
  resetTransferHistory();
  activeOperator = operator;
  activeShift = shift;
  setTimeout(refreshReceiving, 0);
  if (operator.staffRole !== "production") setTimeout(recoverPayment, 0);
  pinValue = "";
  $("#cashierInitials").textContent = operator.initials;
  $("#cashierName").textContent = operator.name;
  $("#cashierActionCaption").textContent = `${operator.roleLabel} · сменить`;
  $("#supplyButton").classList.toggle("hidden", !operatorCan("posSupply"));
  updateProductionAccess();
  const productionOnly = operator.staffRole === "production";
  if (productionOnly) setTimeout(enterProductionShift, 0);
  $("#closeProductionTerminal").classList.remove("hidden");
  $("#posAdminLink").classList.toggle("hidden", productionOnly || currentSession?.staffRole !== "branch_manager");
  document.querySelector(".workspace").classList.toggle("hidden", productionOnly);
  $("#productionHome").classList.toggle("hidden", !productionOnly);
  if (productionOnly) setTimeout(refreshTransferHistory, 0);
  ["#openOrdersButton", "#historyButton", "#cashMenuButton", "#shiftButton"].forEach(selector => $(selector).classList.toggle("hidden", productionOnly));
  if (productionOnly) {
    cart.clear();
    $("#closeSalesReport").click();
    closePayment();
    ["#historyDrawer", "#openOrdersDrawer", "#customerDrawer", "#cashDrawer"].forEach(closeDrawer);
  }
  document.querySelector(".cash-actions").classList.toggle("hidden", !operatorCan("posCash"));
  updateShiftHeader();
  $("#operatorStepKitchen").classList.add("hidden");
  if (productionOnly) {
    ["#operatorStepPin", "#operatorStepShift"].forEach(selector => $(selector).classList.add("hidden"));
    $("#operatorStepKitchen").classList.remove("hidden");
    $("#operatorLock").classList.remove("hidden");
  } else if (activeShift) {
    $("#operatorLock").classList.add("hidden");
  } else {
    $("#operatorStepPin").classList.add("hidden");
    $("#operatorStepShift").classList.remove("hidden");
    $("#operatorLock").classList.remove("hidden");
    $("#openingCashInput").value = "0";
    setTimeout(() => $("#openingCashInput").select(), 20);
  }
  renderCart();
}

async function submitPin() {
  if (pinValue.length !== 4 || pinSubmitting) return;
  pinSubmitting = true;
  showPinError();
  try {
    const response = await window.AshkanaApi.unlockPos(pinValue);
    activateOperator(response.operator, response.shift);
    if (pendingShiftCloseCash !== null) {
      const closingCash = pendingShiftCloseCash;
      pendingShiftCloseCash = null;
      if (activeShift && activeOperator.staffRole !== "production") {
        openShiftClose();
        $("#closingCashInput").value = closingCash;
      }
    }
  } catch (error) {
    pinValue = "";
    renderPinDots();
    showPinError(error.message || "Не удалось проверить PIN");
  } finally {
    pinSubmitting = false;
  }
}

async function openShift() {
  if (!activeOperator) { showOperatorSelection(); return; }
  const openingCash = Number($("#openingCashInput").value || 0);
  if (openingCash < 0) { showToast("Остаток не может быть отрицательным"); return; }
  const button = $("#openShiftButton");
  button.disabled = true;
  button.textContent = "Открываем смену…";
  try {
    const response = await window.AshkanaApi.openPosShift(openingCash);
    activateOperator(activeOperator, response.shift);
    showToast("Кассовая смена открыта");
  } catch (error) {
    showToast(error.message || "Не удалось открыть смену");
  } finally {
    button.disabled = false;
    button.textContent = "Открыть смену";
  }
}

let closingStockContext = null;
async function openShiftClose() {
  if (!activeOperator) { showOperatorSelection(); return; }
  if (!activeShift) { activateOperator(activeOperator, null); return; }
  if (cart.size) { showToast("Сначала завершите или очистите текущий чек"); return; }
  if (pendingPayment()) { showToast("Сначала восстановите неподтверждённую оплату"); recoverPayment(); return; }
  const expected = expectedShiftCash();
  $("#expectedShiftCash").textContent = money(expected);
  $("#closingCashInput").value = expected;
  closeDrawer("#cashDrawer");
  $("#shiftCloseModal").classList.remove("hidden");
  closingStockContext = null;
  $("#confirmShiftCloseButton").disabled = true;
  $("#shiftClosingStock").textContent = "Загрузка остатков…";
  try {
    closingStockContext = await window.AshkanaApi.closingShiftStock();
    $("#shiftClosingStock").innerHTML = closingStockContext.required ? `<h3>Остатки раздачи</h3>${closingStockContext.rows.map(row=>`<div class="shift-count-row" data-closing-lot="${escapeHtml(row.lotId)}"><strong>${escapeHtml(row.name)}</strong><small>${escapeHtml(row.number)} · по учёту ${Number(row.expectedWeight).toLocaleString('ru-RU',{maximumFractionDigits:3})} кг</small><label>Фактически, кг<input data-actual type="number" min="0" step="0.001" inputmode="decimal" required value="${Number(Number(row.expectedWeight).toFixed(3))}"></label><input data-reason placeholder="Причина расхождения" minlength="3" maxlength="500"></div>`).join('') || '<p>Остатков нет</p>'}<label><input id="shiftStockConfirmed" type="checkbox" checked> Передать остатки следующей смене</label>` : '';
    updateStockCountReasons($('#shiftClosingStock'));
    $("#confirmShiftCloseButton").disabled = false;
  } catch (error) { $("#shiftClosingStock").textContent = error.message; }

}

function roundClosingStockInput(input) {
  if (input.value !== '' && Number.isFinite(input.valueAsNumber) && input.valueAsNumber >= 0) {
    input.value = Number(input.valueAsNumber.toFixed(3));
  }
}
$('#shiftClosingStock').addEventListener('input',event=>{
  if (event.target.matches('[data-actual]')) updateStockCountReasons($('#shiftClosingStock'));
});
$('#shiftClosingStock').addEventListener('change',event=>{
  if (event.target.matches('[data-actual]')) {
    roundClosingStockInput(event.target);
    updateStockCountReasons($('#shiftClosingStock'));
  }
});

async function closeShift() {
  const closingCash = Number($("#closingCashInput").value || 0);
  if (closingCash < 0) return;
  const button = $("#confirmShiftCloseButton");
  button.disabled = true;
  try {
    if (!closingStockContext) throw new Error("Сначала загрузите остатки смены");
    $('#shiftClosingStock').querySelectorAll('[data-actual]').forEach(roundClosingStockInput);
    updateStockCountReasons($('#shiftClosingStock'));
    const stock_counts = closingStockContext.rows.map(row=> {
      const card = [...document.querySelectorAll('[data-closing-lot]')].find(el=>el.dataset.closingLot===row.lotId);
      const input = card.querySelector('[data-actual]');
      if (!input.value || !input.checkValidity()) { input.focus(); throw new Error(`${row.name}: укажите фактический остаток`); }
      const actualWeight=stockCountValue(card,row.expectedWeight),reasonInput=card.querySelector('[data-reason]');
      const reason=reasonInput.value.trim();
      if (Math.abs(actualWeight-Number(row.expectedWeight))>0.000001 && reason.length<3) { reasonInput.focus(); throw new Error(`${row.name}: укажите причину расхождения`); }
      return {...row,actualWeight,reason};
    });
    const response = await window.AshkanaApi.closePosShift(closingCash, {stock_counts, stock_confirmed:Boolean($("#shiftStockConfirmed")?.checked),state_version:closingStockContext.version});
    $("#shiftCloseModal").classList.add("hidden");
    activeShift = null;
    updateShiftHeader();
    await lockOperator();
    const variance = Number(response.shift?.variance || 0);
    showToast(variance ? `Смена закрыта · расхождение ${money(variance)}` : "Смена закрыта без расхождений");
  } catch (error) {
    if (error.status === 423) {
      pendingShiftCloseCash = closingCash;
      $("#shiftCloseModal").classList.add("hidden");
      activeOperator = null;
      resetTransferHistory();
  refreshReceiving();
      showOperatorSelection();
      showPinError("Сеанс кассира завершён. Подтвердите PIN, чтобы продолжить закрытие смены.");
      return;
    }
    showToast(error.message || "Не удалось закрыть смену");
  } finally {
    button.disabled = false;
  }
}

function enterPinDigit(digit) {
  if (pinSubmitting || pinValue.length >= 4) return;
  pinValue += digit;
  showPinError();
  renderPinDots();
  if (pinValue.length === 4) submitPin();
}

async function lockOperator() {
  reportRequest++; reportOptionsRequest++; terminalSalesReport=null; $("#salesReportModal").classList.add("hidden"); $("#salesReportResult").innerHTML="";
  if (cart.size) { showToast("Сначала оплатите или отложите текущий заказ"); return; }
  const button = $("#closeProductionTerminal");
  button.disabled = true;
  try { await window.AshkanaApi.lockPos(); }
  catch(error) { showToast(error.message || "Не удалось заблокировать терминал. Повторите попытку."); button.disabled=false; return; }
  button.disabled = false;
  cart.clear();closePayment();
  ["#historyDrawer", "#supplyDrawer", "#productionDrawer", "#productionShiftDrawer", "#receivingDrawer", "#servingSurplusDrawer"].forEach(closeDrawer);
  if ($('#productionShiftNotice').open) $('#productionShiftNotice').close();
  $("#productionButton").classList.add("hidden");
  activeOperator = null;
  resetTransferHistory();
  refreshReceiving();
  $("#supplyButton").classList.add("hidden");
  showOperatorSelection();

}
$("#closeProductionTerminal").addEventListener("click", lockOperator);

async function logoutTerminal() {
  if(window.OfflinePos && !await window.OfflinePos.canLeave()) return;
  try { await window.AshkanaApi.logout(); } catch {}
  sessionStorage.removeItem(authSessionKey);
  location.href = terminalLoginUrl();
}

async function initializePos() {
  try {
    const authResponse = await window.AshkanaApi.me();
    currentSession = authResponse.session;
    sessionStorage.setItem(authSessionKey, JSON.stringify(currentSession));
    if (currentSession.role !== "branch" || !["pos_terminal", "branch_manager"].includes(currentSession.staffRole || "")) {
      $("#productGrid").innerHTML = '<div class="no-products">У этой учётной записи нет доступа к терминалу кассы.</div>';
      $("#payButton").disabled = true;
      return;
    }
    const response = await window.AshkanaApi.workspace();
    if (!hydrateWorkspace(response)) throw new Error("Не удалось загрузить данные точки");
    const branch = branchById(currentSession.branchId);
    $("#branchSelect").innerHTML = `<option value="${escapeHtml(branch.id)}">${escapeHtml(branch.name)}</option>`;
    $("#branchSelect").disabled = true;
    $("#operatorBranchName").textContent = `${branch.name} · ${currentSession.registerName || "Касса"}`;
    $("#posAdminLink").classList.toggle("hidden", currentSession.staffRole !== "branch_manager");
    configureOrderSettings(true);
    loadTerminalSettings();
    updateShiftHeader();
    renderWorkspace();
    const operatorResponse = await window.AshkanaApi.posOperator();
    if (operatorResponse.operator) activateOperator(operatorResponse.operator, operatorResponse.shift);
    else showOperatorSelection();
  } catch (error) {
    if ([401, 403].includes(error.status)) {
      sessionStorage.removeItem(authSessionKey);
      location.replace("/login?mode=pos");
      return;
    }
    $("#productGrid").innerHTML = `<div class="no-products">${escapeHtml(error.message || "Сервер Oimo недоступен")}</div>`;
    $("#payButton").disabled = true;
  }
}

$("#categories").addEventListener("click", (event) => {
  const button = event.target.closest("[data-category]");
  if (!button) return;
  activeCategory = button.dataset.category;
  $("#searchInput").value = "";
  renderCategories();
  renderProducts();
});

$("#catalogBack").addEventListener("click", () => {
  activeCategory = null;
  $("#searchInput").value = "";
  renderProducts();
});

$("#productGrid").addEventListener("click", (event) => {
  const button = event.target.closest("[data-product-id]");
  if (button) chooseProduct(button.dataset.productId);
});

$("#orderItems").addEventListener("click", (event) => {
  const button = event.target.closest("[data-quantity-action]");
  if (!button) return;
  if (button.dataset.quantityAction === 'remove') {
    cart.delete(button.dataset.productId);
    renderCart();
  } else updateQuantity(button.dataset.productId, button.dataset.quantityAction === "plus" ? 1 : -1);
});

$("#searchInput").addEventListener("input", renderProducts);
$("#payButton").addEventListener("click", () => openPayment("cash"));
$("#cashReceived").addEventListener("input", updatePaymentState);
$("#confirmPaymentButton").addEventListener("click", completePayment);

$("#paymentMethods").addEventListener("click", (event) => {
  const button = event.target.closest("[data-method]");
  if (button) selectPaymentMethod(button.dataset.method, true);
});

$("#quickCash").addEventListener("click", (event) => {
  const button = event.target.closest("[data-cash-amount]");
  if (!button) return;
  $("#cashReceived").value = button.dataset.cashAmount;
  updatePaymentState();
});

$("#clearOrderButton").addEventListener("click", () => {
  if (!cart.size) return;
  cart.clear();
  configureOrderSettings(true);
  currentCustomer = null;
  currentOpenOrderId = null;
  $("#orderComment").value = "";
  renderCart();
  showToast("Текущий заказ очищен");
});

$("#saveOrderButton").addEventListener("click", () => saveOpenOrder());
$("#sendKitchenOrderButton").addEventListener("click", () => saveOpenOrder(true));
$("#closeVariantDialog").addEventListener("click", () => $("#productVariantDialog").close());
$("#variantDialogOptions").addEventListener("click", event => { const button = event.target.closest("[data-select-variant]"); if (!button || button.disabled) return; addProduct(button.dataset.selectVariant); $("#productVariantDialog").close(); });
$("#supplyButton").addEventListener("click", openPosSupply);
$("#closeSupplyButton").addEventListener("click", () => closeDrawer("#supplyDrawer"));
$("#supplyDrawer").addEventListener("click", (event) => { if (event.target === $("#supplyDrawer")) closeDrawer("#supplyDrawer"); });
$("#addPosSupplyLine").addEventListener("click", () => addPosSupplyLine());
$("#posSupplyImportButton").addEventListener("click", () => $("#posSupplyImportFile").click());
$("#posSupplyImportFile").addEventListener("change", event => importPosSupplyFile(event.target.files[0]));
$("#posSupplyImportCancel").addEventListener("click", resetPosSupplyImport);
$("#posSupplyImportApply").addEventListener("click", applyPosSupplyImport);
$("#posSupplyImportTemplate").addEventListener("click", downloadPosSupplyTemplate);
$("#posSupplyImportRows").addEventListener("focusin", expandSupplyImportOptions);
$("#posSupplyImportRows").addEventListener("pointerdown", expandSupplyImportOptions);
$("#posSupplyLines").addEventListener("focusin", expandSupplyImportOptions);
$("#posSupplyLines").addEventListener("pointerdown", expandSupplyImportOptions);
$("#posSupplyImportRows").addEventListener("change", () => { $("#posSupplyImportError").textContent = ''; updatePosSupplyImportPreview(); });
$("#posSupplySupplier").addEventListener("change", () => document.querySelectorAll("#posSupplyLines .supply-line").forEach((row) => updatePosSupplyRow(row, !row.dataset.supplyImported)));
$("#posSupplyLines").addEventListener("input", (event) => { const row = event.target.closest(".supply-line"); if (row) updatePosSupplyRow(row, false); });
$("#posSupplyLines").addEventListener("change", (event) => { const row = event.target.closest(".supply-line"); if (row) updatePosSupplyRow(row, event.target.matches("[data-supply-item]")); });
$("#posSupplyLines").addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-supply-line]");
  if (!button) return;
  const rows = document.querySelectorAll("#posSupplyLines .supply-line");
  if (rows.length === 1) { rows[0].querySelector("[data-supply-item]").value = ""; rows[0].querySelector("[data-supply-quantity]").value = ""; rows[0].querySelector("[data-supply-price]").value = ""; updatePosSupplyRow(rows[0]); return; }
  button.closest(".supply-line").remove();
  updatePosSupplyTotal();
});
$("#posSupplyPaymentMode").addEventListener("change", updatePosSupplyPayment);
$("#posSupplyPaidAmount").addEventListener("input", updatePosSupplyTotal);
$("#posSupplyForm").addEventListener("submit", savePosSupply);
$("#openOrdersButton").addEventListener("click", () => { renderOpenOrders(); $("#openOrdersDrawer").classList.remove("hidden"); });
$("#closeOpenOrdersButton").addEventListener("click", () => closeDrawer("#openOrdersDrawer"));
$("#openOrdersDrawer").addEventListener("click", (event) => { if (event.target === $("#openOrdersDrawer")) closeDrawer("#openOrdersDrawer"); });
$("#openOrdersList").addEventListener("click", (event) => {
  const openButton = event.target.closest("[data-open-order]");
  const deleteButton = event.target.closest("[data-delete-order]");
  if (openButton) loadOpenOrder(openButton.dataset.openOrder);
  if (deleteButton) deleteOpenOrder(deleteButton.dataset.deleteOrder);
});
$("#customerButton").addEventListener("click", () => { renderCustomers(); $("#customerDrawer").classList.remove("hidden"); setTimeout(() => $("#customerSearch").focus(), 20); });
$("#closeCustomerButton").addEventListener("click", () => closeDrawer("#customerDrawer"));
$("#customerDrawer").addEventListener("click", (event) => { if (event.target === $("#customerDrawer")) closeDrawer("#customerDrawer"); });
$("#customerSearch").addEventListener("input", renderCustomers);
$("#customerList").addEventListener("click", (event) => { const button = event.target.closest("[data-customer-id]"); if (button) selectCustomer(button.dataset.customerId); });
$("#clearCustomerButton").addEventListener("click", () => { currentCustomer = null; closeDrawer("#customerDrawer"); renderCart(); });
$("#customerForm").addEventListener("submit", createCustomer);
$("#historyButton").addEventListener("click", () => { if (!allowProtectedAction("orderHistory")) return; renderHistory(); $("#historyDrawer").classList.remove("hidden"); refreshReceiptShifts(); });
$("#closeHistoryButton").addEventListener("click", () => $("#historyDrawer").classList.add("hidden"));
$("#historyDrawer").addEventListener("click", (event) => { if (event.target === $("#historyDrawer")) $("#historyDrawer").classList.add("hidden"); });
$("#historyList").addEventListener("click", (event) => { const button = event.target.closest("[data-receipt-id]"); if (button) { selectedReceiptId = button.dataset.receiptId; renderHistory(); } });
$("#archiveDetails").addEventListener("submit", refundSale);
$("#archiveDetails").addEventListener("click", event=>{if(event.target.closest('#archivePrint')){const sale=sales.find(sale=>sale.id===selectedReceiptId);if(sale)printReceipt(sale);}});
$("#archiveFilters").addEventListener("click", event=>{const button=event.target.closest('[data-archive-filter]');if(!button)return;archiveFilter=button.dataset.archiveFilter;document.querySelectorAll('[data-archive-filter]').forEach(el=>el.classList.toggle('active',el===button));renderHistory();});
$("#archiveSearch").addEventListener("input",renderHistory);
$("#archiveDate").addEventListener("change",renderHistory);
$("#archiveShift").addEventListener("change",()=>{archiveShiftDefaulted=true;$("#archiveDate").value='';renderHistory();});
$("#archiveAllDates").addEventListener("click",()=>{$("#archiveDate").value='';$("#archiveShift").value='all';archiveShiftDefaulted=true;renderHistory();});
$("#cashMenuButton").addEventListener("click", openCashDrawer);
$("#shiftButton").addEventListener("click", openCashDrawer);
$("#closeCashDrawerButton").addEventListener("click", () => closeDrawer("#cashDrawer"));
$("#cashDrawer").addEventListener("click", (event) => { if (event.target === $("#cashDrawer")) closeDrawer("#cashDrawer"); });
document.querySelectorAll("[data-cash-action]").forEach((button) => button.addEventListener("click", () => beginCashOperation(button.dataset.cashAction)));
$("#cashOperationForm").addEventListener("submit", submitCashOperation);
$("#cancelCashOperation").addEventListener("click", () => $("#cashOperationForm").classList.add("hidden"));
$("#printXReportButton").addEventListener("click", printXReport);
$("#openShiftCloseButton").addEventListener("click", openShiftClose);
$("#openTerminalSettingsButton").addEventListener("click", () => { closeDrawer("#cashDrawer"); openTerminalSettings(); });
$("#closeTerminalSettingsButton").addEventListener("click", closeTerminalSettings);
$("#terminalSettingsDrawer").addEventListener("click", (event) => { if (event.target === $("#terminalSettingsDrawer")) closeTerminalSettings(); });
$("#saveTerminalSettingsButton").addEventListener("click", saveTerminalSettings);
$("#receiptPrinterMode").addEventListener("change", updatePrinterControls);
$("#findPrintersButton").addEventListener("click", async event => {
  const button = event.currentTarget; button.disabled = true;
  $("#printerStatus").textContent = "Ищем принтеры через QZ Tray…";
  try {
    const names = await window.OimoPrinting.findPrinters();
    const selector = $("#receiptPrinterName"), previous = selector.value;
    selector.replaceChildren(new Option("Выберите принтер", ""));
    names.forEach(name => selector.add(new Option(name, name)));
    selector.value = names.includes(previous) ? previous : names.length === 1 ? names[0] : "";
    $("#printerStatus").textContent = names.length ? `Найдено принтеров: ${names.length}. Выберите устройство и напечатайте пробный чек.` : "Принтеров нет. Установите драйвер и добавьте устройство в операционной системе кассы.";
  } catch (error) { $("#printerStatus").textContent = error.message || "Не удалось получить список принтеров."; }
  finally { button.disabled = false; }
});
$("#testPrinterButton").addEventListener("click", async event => {
  const button = event.currentTarget; button.disabled = true;
  const settings = printerSettingsFromForm();
  const html = `<h1>Oimo</h1><p>Пробный чек<b>${settings.receiptPaperWidth} мм</b></p><p>${escapeHtml(currentSession?.registerName || "Касса")}</p><p>${new Date().toLocaleString("ru-RU")}</p><hr><p>Проверка кириллицы: чай, борщ, счёт</p><p>Длинное название блюда для проверки переноса строк<b>123 456,78</b></p><hr><small>Если этот текст виден полностью, печать можно использовать. Пробный чек не создаёт продажу.</small>`;
  try { await submitPrintJob(html, "Oimo — пробный чек", settings); }
  finally { button.disabled = false; }
});
$("#printErrorHistory").addEventListener("click", () => $("#historyButton").click());
$("#dismissPrintError").addEventListener("click", () => $("#printErrorNotice").classList.add("hidden"));

$("#syncTerminalButton").addEventListener("click", syncTerminalWorkspace);
$("#settingsSwitchOperatorButton").addEventListener("click", () => { closeTerminalSettings(); lockOperator(); });
$("#settingsLogoutButton").addEventListener("click", () => {
  if (activeShift) { closeTerminalSettings(); showToast("Сначала закройте кассовую смену"); return; }
  logoutTerminal();
});
document.querySelectorAll("[data-close-modal]").forEach((button) => button.addEventListener("click", closePayment));
$("#paymentModal").addEventListener("click", (event) => { if (event.target === $("#paymentModal")) closePayment(); });

$("#cashierButton").addEventListener("click", lockOperator);
$("#operatorLogoutButton").addEventListener("click", logoutTerminal);
$("#shiftChangeOperatorButton").addEventListener("click", lockOperator);
$("#openShiftButton").addEventListener("click", openShift);
$("#cancelShiftCloseButton").addEventListener("click", () => $("#shiftCloseModal").classList.add("hidden"));
$("#confirmShiftCloseButton").addEventListener("click", closeShift);

$("#pinKeypad").innerHTML = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "delete"].map((key) => {
  if (key === "clear") return '<button class="pin-clear" data-pin-key="clear" type="button">Очистить</button>';
  if (key === "delete") return '<button class="pin-delete" data-pin-key="delete" type="button" aria-label="Удалить цифру">⌫</button>';
  return `<button data-pin-key="${key}" type="button">${key}</button>`;
}).join("");
$("#pinKeypad").addEventListener("click", (event) => {
  const button = event.target.closest("[data-pin-key]");
  if (!button) return;
  if (button.dataset.pinKey === "clear") pinValue = "";
  else if (button.dataset.pinKey === "delete") pinValue = pinValue.slice(0, -1);
  else { enterPinDigit(button.dataset.pinKey); return; }
  showPinError();
  renderPinDots();
});

document.addEventListener("keydown", (event) => {
  if (document.querySelector('dialog[open]')) return;
  if (!$("#operatorLock").classList.contains("hidden")) {
    if (!$("#operatorStepPin").classList.contains("hidden")) {
      if (/^\d$/.test(event.key)) { event.preventDefault(); enterPinDigit(event.key); }
      if (event.key === "Backspace") { event.preventDefault(); pinValue = pinValue.slice(0, -1); showPinError(); renderPinDots(); }
      if (event.key === "Enter") { event.preventDefault(); submitPin(); }
      if (event.key === "Escape") { event.preventDefault(); showOperatorSelection(); }
    }
    return;
  }
  if (event.key === "Escape") {
    $("#terminalFunctions").classList.add("hidden");
    $("#closeSalesReport").click();
    closePayment();
    ["#historyDrawer", "#openOrdersDrawer", "#customerDrawer", "#cashDrawer", "#supplyDrawer", "#productionDrawer", "#transferHistoryDrawer"].forEach(closeDrawer);
    closeTerminalSettings();
  }
});

tickClock();
setInterval(tickClock, 1000);
initializePos();

$("#posOrderSettings").addEventListener("change", () => { configureOrderSettings(); renderCart(); });
$("#orderItems").addEventListener("change", event => {
  const input = event.target.closest("[data-fractional-id]");
  if (!input) return;
  const item = cart.get(input.dataset.fractionalId);
  const quantity = Number(input.value);
  if (!item || !Number.isFinite(quantity) || quantity <= 0 || quantity > item.available) { showToast("Проверьте количество и доступный остаток"); renderCart(); return; }
  item.quantity = Math.round(quantity * 100) / 100;
  renderCart();
});

$("#openOrdersList").addEventListener("click", async event => {
  const button = event.target.closest("[data-order-status]");
  if (!button) return;
  button.disabled = true;
  try { hydrateWorkspace(await window.AshkanaApi.action("pos.order.status", { id: button.dataset.orderStatusId, status: button.dataset.orderStatus })); renderOpenOrders(); }
  catch (error) { showToast(error.message); button.disabled = false; }
});

let transferHistoryDocuments = [];
let transferHistoryLoading = null;
let transferHistoryGeneration = 0;
let transferHistoryLoaded = false;
let transferHistoryShifts = [];
let transferHistoryCurrentShiftId = null;
let transferHistoryShiftKind = 'production';
let transferHistoryShiftDefaulted = false;
let transferHistoryHasShifts = false;
function canViewTransferHistory() {
  return Boolean(activeOperator && ['production','cashier','hall_admin','branch_manager'].includes(activeOperator.staffRole) && workspaceState?.serviceMode !== 'restaurant');
}
function resetTransferHistory() {
  resetReceiptHistory();
  transferHistoryGeneration++;
  transferHistoryLoading = null;
  transferHistoryLoaded = false;
  transferHistoryDocuments = [];
  transferHistoryShifts = [];
  transferHistoryCurrentShiftId = null;
  transferHistoryShiftDefaulted = false;
  transferHistoryHasShifts = false;
  $('#transferHistoryShift').innerHTML = '<option value="all">Все смены</option>';
  closeDrawer('#transferHistoryDrawer');
  ['#productionHistoryList','#transferHistoryList','#productionHistoryMessage','#transferHistoryMessage'].forEach(id => $(id).textContent = '');
  ['#transferHistorySearch','#transferHistoryStatus','#transferHistoryFrom','#transferHistoryTo'].forEach(id => $(id).value = '');
}
function transferHasDifference(row) {
  return row.status === 'accepted' && row.actualWeight != null && Math.abs(Number(row.actualWeight) - Number(row.weight)) > 0.000001;
}
function transferHistoryDate(value) {
  const date = new Date(value);
  return value && Number.isFinite(date.getTime()) ? date.toLocaleString('ru-RU', {...historyTimeZone(),day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}) : 'Время не зафиксировано';
}
function transferHistoryGroup(row) {
  const shift = transferHistoryShiftKind === 'production' ? row.productionShift : row.receivingShift;
  if (!shift && transferHistoryShiftKind === 'cash' && row.status === 'pending') return {key:'pending', title:'Ожидают приёмки', caption:'Будут отнесены к смене после решения кассира'};
  return {key: historyShiftKey(shift), shift};
}
function transferHistoryCard(row) {
  const difference = transferHasDifference(row);
  const state = difference ? 'difference' : row.status;
  const status = {pending:'Ожидает приёмки',accepted:'Принято',difference:'С расхождением',rejected:'Отказано',canceled:'Отменено'}[state] || 'Передача';
  const weight = value => Number(value || 0).toLocaleString('ru-RU', {maximumFractionDigits:6}) + ' кг';
  const event = (title, date, actor, detail = '', shift = null) => `<li><strong>${escapeHtml(title)}</strong><span>${escapeHtml(transferHistoryDate(date))}${actor?.name ? ' · ' + escapeHtml(actor.name) : ''}</span>${shift ? `<span class="history-event-shift">${escapeHtml(historyShiftTitle(shift))} · ${escapeHtml(historyShiftCaption(shift))}</span>` : ''}${detail ? `<p>${escapeHtml(detail)}</p>` : ''}</li>`;
  let events = event('Отправлено на раздачу', row.createdAt, row.actor, weight(row.weight), row.productionShift);
  if (row.status === 'accepted') {
    events += event('Принято на раздаче', row.acceptedAt, row.acceptedBy, row.actualWeight == null ? '' : weight(row.actualWeight), row.receivingShift);
    if (difference) events += `<li class="transfer-event-difference"><strong>Расхождение: ${escapeHtml(weight(Number(row.actualWeight) - Number(row.weight)))}</strong>${row.reason ? `<p>${escapeHtml(row.reason)}</p>` : ''}<span>${row.reviewStatus === 'approved' ? 'Проверено руководителем' : 'Ожидает проверки руководителя'}</span></li>`;
    if (row.reviewedAt) events += event('Проверка расхождения', row.reviewedAt, row.reviewedBy, row.reviewNote);
  } else if (row.status === 'rejected') {
    events += event('Отказано · блюдо возвращено на кухню', row.rejectedAt, row.rejectedBy, row.rejectReason, row.receivingShift);
  } else if (row.status === 'canceled') {
    events += event('Передача отменена', row.canceledAt, row.canceledBy, row.cancelReason);
  } else {
    events += `<li><strong>Ожидает приёмки</strong><span>${escapeHtml(row.recipient?.name || 'Раздача')}</span></li>`;
  }
  return `<details class="transfer-history-card" data-transfer-id="${escapeHtml(row.id)}"><summary><span class="transfer-history-dish"><strong>${escapeHtml(row.name)}</strong><small>${escapeHtml(transferHistoryDate(row.createdAt))}${row.batchNumber ? ' · ' + escapeHtml(row.batchNumber) : ''}</small></span><span class="transfer-history-amount">${escapeHtml(weight(row.weight))}</span><span class="transfer-history-badge" data-status="${escapeHtml(state)}">${status}</span><span class="transfer-history-chevron" aria-hidden="true">${posIcon("chevron")}</span></summary><div class="transfer-history-details"><p class="transfer-document-number">${escapeHtml(row.number || '')}</p><ol class="transfer-timeline">${events}</ol></div></details>`;
}
function renderTransferHistory() {
  const choices = [...transferHistoryShifts];
  for (const row of transferHistoryDocuments) {
    const shift = transferHistoryGroup(row).shift;
    if (shift && !choices.some(choice => historyShiftKey(choice) === historyShiftKey(shift))) choices.push(shift);
  }
  historyShiftOptions($('#transferHistoryShift'), choices, transferHistoryCurrentShiftId, transferHistoryShiftKind,
    [...(transferHistoryShiftKind === 'cash' ? [['pending','Ожидают приёмки']] : []), ['unassigned','Без привязки к смене']]);
  if (!transferHistoryShiftDefaulted && transferHistoryLoaded) {
    const currentKey = `${transferHistoryShiftKind}:${transferHistoryCurrentShiftId}`;
    if (choices.some(shift => historyShiftKey(shift) === currentKey)) $('#transferHistoryShift').value = currentKey;
    transferHistoryShiftDefaulted = true;
  }
  const shiftFilter = $('#transferHistoryShift').value;
  const search = $('#transferHistorySearch').value.trim().toLocaleLowerCase('ru-RU');
  const status = $('#transferHistoryStatus').value;
  const from = $('#transferHistoryFrom').value;
  const to = $('#transferHistoryTo').value;
  const filtered = transferHistoryDocuments.filter(row => {
    const date = new Date(transferHistoryShiftKind === 'cash' ? row.acceptedAt || row.rejectedAt || row.createdAt : row.createdAt);
    const day = Number.isFinite(date.getTime()) ? archiveDay(date) : '';
    return (shiftFilter === 'all' || transferHistoryGroup(row).key === shiftFilter) && (!from || day >= from) && (!to || day <= to) && (!status || (status === 'difference' ? transferHasDifference(row) : row.status === status)) && (!search || [row.name,row.number,row.batchNumber,row.actor?.name,row.acceptedBy?.name,row.rejectedBy?.name].join(' ').toLocaleLowerCase('ru-RU').includes(search));
  });
  const render = (id, rows) => {
    const target = $(id);
    const focused = target.contains(document.activeElement) ? document.activeElement.closest('[data-transfer-id]')?.dataset.transferId : null;
    const opened = new Set(Array.from(target.querySelectorAll('details[open]'), node => node.dataset.transferId));
    target.innerHTML = id === '#transferHistoryList' ? historyShiftGroups(rows, transferHistoryGroup, transferHistoryCard) : rows.map(transferHistoryCard).join('');
    target.querySelectorAll('details').forEach(node => {
      node.open = opened.has(node.dataset.transferId);
      if (node.dataset.transferId === focused) node.querySelector('summary').focus({preventScroll:true});
    });
  };
  const homeRows = transferHistoryHasShifts ? transferHistoryDocuments.filter(row => transferHistoryCurrentShiftId != null && String(row.productionShift?.id) === String(transferHistoryCurrentShiftId)) : transferHistoryDocuments;
  render('#productionHistoryList', homeRows.slice(0, 5));
  render('#transferHistoryList', filtered);
  $('#productionHistoryMessage').textContent = homeRows.length > 5 ? `Последние 5 из ${homeRows.length} за смену` : homeRows.length ? '' : transferHistoryLoaded ? 'За эту смену передач пока нет. Прошлые доступны в истории смен.' : '';
  $('#transferHistoryMessage').textContent = from && to && from > to ? 'Дата начала должна быть раньше даты окончания.' : filtered.length ? `Передач: ${filtered.length}` : transferHistoryLoaded ? 'Передач по выбранным условиям нет.' : '';
}
async function refreshTransferHistory() {
  if (!canViewTransferHistory() || transferHistoryLoading || !window.AshkanaApi.posTransferHistory) return;
  const token = {actor:activeOperator.id, generation:transferHistoryGeneration};
  transferHistoryLoading = token;
  if (!transferHistoryLoaded) ['#productionHistoryMessage','#transferHistoryMessage'].forEach(id => $(id).textContent = 'Загрузка истории…');
  try {
    const data = await window.AshkanaApi.posTransferHistory();
    if (token.generation !== transferHistoryGeneration || activeOperator?.id !== token.actor || !canViewTransferHistory()) return;
    transferHistoryDocuments = data.documents || [];
    transferHistoryShifts = data.shifts || [];
    transferHistoryCurrentShiftId = data.currentShiftId ?? null;
    transferHistoryShiftKind = data.currentShiftKind || (activeOperator.staffRole === 'production' ? 'production' : 'cash');
    transferHistoryHasShifts = Object.prototype.hasOwnProperty.call(data, 'currentShiftId');
    transferHistoryLoaded = true;
    renderTransferHistory();
  } catch (error) {
    if (token.generation === transferHistoryGeneration) ['#productionHistoryMessage','#transferHistoryMessage'].forEach(id => $(id).textContent = `Не удалось обновить историю. ${error.message}`);
  } finally {
    if (transferHistoryLoading === token) transferHistoryLoading = null;
  }
}
async function openTransferHistory() {
  if (!canViewTransferHistory()) return;
  $('#transferHistoryTitle').textContent = activeOperator.staffRole === 'production' ? 'Мои передачи' : 'История передач';
  $('#transferHistoryDrawer').classList.remove('hidden');
  renderTransferHistory();
  await refreshTransferHistory();
}
$('#refreshTransferHistory').addEventListener('click', refreshTransferHistory);
['#transferHistorySearch','#transferHistoryStatus','#transferHistoryFrom','#transferHistoryTo'].forEach(id => $(id).addEventListener('input', renderTransferHistory));
$('#transferHistoryShift').addEventListener('change', () => { transferHistoryShiftDefaulted=true; $('#transferHistoryFrom').value=''; $('#transferHistoryTo').value=''; renderTransferHistory(); });
$('#transferHistoryDrawer').addEventListener('click', event => { if (event.target === $('#transferHistoryDrawer')) closeDrawer('#transferHistoryDrawer'); });
setInterval(() => {
  if (!document.hidden && (!$('#productionHome').classList.contains('hidden') || !$('#transferHistoryDrawer').classList.contains('hidden'))) refreshTransferHistory();
}, 8000);

let productionData = {recipes: [], batches: []};
let productionRequest = null;
let productionBusy = false;
function updateProductionAccess() {
  if (workspaceState?.serviceMode === "restaurant") {
    $("#receivingButton").classList.add("hidden");
    $("#servingWriteoffButton").classList.add("hidden");
    $("#servingSurplusButton").classList.add("hidden");
    closeDrawer("#servingSurplusDrawer");
    closeDrawer("#servingWriteoffDrawer");
    $("#receivingNotice").classList.add("hidden");
    closeDrawer("#receivingDrawer");
  }
  const allowed = operatorCan("production") && workspaceState?.serviceMode !== "restaurant";
  $("#productionButton").classList.toggle("hidden", !allowed);
  if (!allowed) closeDrawer("#productionDrawer");
}
function productionSelected(row = $('#productionLines .production-line')) {
  return productionData.recipes.find(item => String(item.id) === row?.querySelector('[data-production-item]').value);
}
function numberProductionRows() {
  document.querySelectorAll('#productionLines .production-line').forEach((row,index)=>{
    row.querySelector('[data-row-title]').textContent=`Блюдо ${index+1}`;
    for (const [key,id] of [['item','productionItem'],['quantity','productionQuantity'],['unit','productionUnit']]) {
      row.querySelector(`[data-production-${key}]`).id=index===0?id:`${id}-${index}`;
    }
  });
}
function addProductionLine() {
  if(document.querySelectorAll('#productionLines .production-line').length>=100)return;
  const row=document.createElement('div');row.className='production-line';
  row.innerHTML=`<div class="production-line-heading"><strong data-row-title></strong><button class="icon-button danger-button" type="button" data-remove-production aria-label="Удалить блюдо">×</button></div><label>Блюдо<select data-production-item required></select></label><div class="production-quantity"><label>Количество<input data-production-quantity type="number" min="0.001" step="0.001" required inputmode="decimal"></label><label>Единица<select data-production-unit><option value="kg">кг</option><option value="portions">порции / шт.</option></select></label></div>`;
  $('#productionLines').append(row);numberProductionRows();renderProductionOptions(row);row.querySelector('[data-production-item]').focus();
}
function renderProductionOptions(row) {
  if(!row?.matches?.('.production-line')) { document.querySelectorAll('#productionLines .production-line').forEach(renderProductionOptions); return; }
  const select=row.querySelector('[data-production-item]');const selected=select.value;
  const entries=productionData.recipes;
  select.innerHTML='<option value="">Выберите блюдо</option>'+entries.map(item=>`<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');select.value=selected;
  updateProductionQuantity();
}
function updateProductionQuantity() {
  let total=0;let valid=true;const rows=[...document.querySelectorAll('#productionLines .production-line')];
  rows.forEach(row=>{
    const item=productionSelected(row);const portions=row.querySelector('[data-production-unit]').value==='portions';
    const ready=productionData.batches.filter(batch=>String(batch.recipeId)===String(item?.id)).reduce((sum,batch)=>sum+Number(batch.availableWeight||0),0);
    const kg=ready+Number(item?.maxWeight||0);const input=row.querySelector('[data-production-quantity]');
    input.step=portions?'1':'0.001';input.min=portions?'1':'0.001';input.max=portions?(item?.yield>0?Math.floor(kg*1000/item.yield+1e-8):0):kg;
    if(!item||kg<=0)valid=false;
    total+=Number(input.value||0)*(portions?Number(item?.yield||0)/1000:1);
  });
  $('#productionSummary').textContent=`Блюд: ${rows.length} · Всего: ${total.toLocaleString('ru-RU',{maximumFractionDigits:3})} кг`;
  $('#saveProductionButton').disabled=productionBusy||!rows.length||!valid;
}
async function openPosProduction() {
  if (!(await requireProductionShift())) return;
  if (!operatorCan("production") || workspaceState?.serviceMode === "restaurant") { showToast("Производство недоступно этому сотруднику или тарифу"); return; }
  const operatorId = activeOperator.id;
  $("#productionButton").disabled = true;
  try {
    const data = await window.AshkanaApi.posProductionContext();
    if (activeOperator?.id !== operatorId) return;
    productionData = data;
    $("#posProductionForm").hidden=false;
    $("#posProductionForm").reset();
    $("#productionError").textContent = "";
    $("#productionResult").textContent = "";
    productionRequest = null;
    refreshTransferHistory();
    $("#productionLines").innerHTML="";addProductionLine();
    $("#productionHelp").textContent="Добавьте блюда. После отправки кассир подтвердит фактическую приёмку каждой партии.";
    $("#productionDrawer").classList.remove("hidden");
    $("#productionItem").focus();
  } catch(error) { showToast(error.message || "Не удалось загрузить производство"); }
  finally { $("#productionButton").disabled = false; }
}
async function savePosProduction(event) {
  event.preventDefault();
  if (productionBusy || !$("#posProductionForm").reportValidity()) return;
  if (!operatorCan("production")) { showToast("Нет права на производство"); return; }
  const items=[...document.querySelectorAll('#productionLines .production-line')].map(row=>{
    const item=productionSelected(row);const quantity=Number(row.querySelector('[data-production-quantity]').value);
    return {recipeId:item?.id,weight:Math.round(quantity*(row.querySelector('[data-production-unit]').value==='portions'?Number(item?.yield||0)/1000:1)*1e6)/1e6};
  });
  if(!items.length||items.some(item=>!item.recipeId||item.weight<=0)) { $('#productionError').textContent='Добавьте блюда и укажите количество';return; }
  if(new Set(items.map(item=>String(item.recipeId))).size!==items.length) { $('#productionError').textContent='Одинаковые блюда объедините в одну строку';return; }
  productionBusy = true;
  const approved = await confirmProductionTransfer(items);
  productionBusy = false;
  if (!approved) return;
  const payload={items};
  const signature = JSON.stringify(payload);
  if (productionRequest?.signature !== signature) productionRequest = {signature, id:crypto.randomUUID()};
  payload.requestId = productionRequest.id;
  productionBusy = true;
  $("#productionFields").disabled = true; $("#addProductionLine").disabled = true;
  $("#saveProductionButton").disabled = true;
  $("#productionError").textContent = "";
  $("#productionResult").textContent = "";
  try {
    const response = await window.AshkanaApi.action("batch.serve_many", payload);
    hydrateWorkspace(response); renderProducts();
    $("#productionResult").textContent = `Блюд: ${items.length} · ${items.reduce((sum,item)=>sum+item.weight,0).toLocaleString("ru-RU")} кг отправлено на приёмку в кассу`;
    refreshTransferHistory();
    document.querySelectorAll("[data-production-quantity]").forEach(input=>input.value="");
    productionRequest = null;
    try { productionData = await window.AshkanaApi.posProductionContext(); renderProductionOptions(); }
    catch (_) { closeDrawer("#productionDrawer"); showToast("Передача сохранена. Откройте раздел заново для обновления остатков."); }
  } catch(error) { $("#productionError").textContent = error.message || "Не удалось сохранить. Повторите попытку."; }
  finally { productionBusy = false; $("#productionFields").disabled = false; $("#addProductionLine").disabled = false; updateProductionQuantity(); }
}
$("#productionButton").addEventListener("click", openPosProduction);
$("#closeProductionButton").addEventListener("click", () => closeDrawer("#productionDrawer"));
$("#productionDrawer").addEventListener("click", event => { if(event.target === $("#productionDrawer")) closeDrawer("#productionDrawer"); });
$('#addProductionLine').addEventListener('click',addProductionLine);
$('#productionLines').addEventListener('click',event=>{if(!event.target.closest('[data-remove-production]'))return;event.target.closest('.production-line').remove();numberProductionRows();updateProductionQuantity();});
$('#productionLines').addEventListener('input',updateProductionQuantity);
$('#productionLines').addEventListener('change',event=>{if(event.target.matches('[data-production-unit]'))event.target.closest('.production-line').querySelector('[data-production-quantity]').value='';updateProductionQuantity();});
$("#posProductionForm").addEventListener("submit", savePosProduction);

$("#variantDialogOptions").addEventListener("click",event=>{const button=event.target.closest('[data-select-lot]');if(!button)return;addProduct(button.dataset.lotProduct,button.dataset.selectLot);$("#productVariantDialog").close();});

let receivingDocuments = [];
let receivingBusy = false;
let receivingLoading = false;
let receivingVersion = null;
const receivingRequests = new Map();
function canReceive() {
  return activeShift && ['cashier','branch_manager','hall_admin'].includes(activeOperator?.staffRole) && workspaceState?.serviceMode !== 'restaurant';
}
function renderReceiving() {
  $('#receivingList').innerHTML = receivingDocuments.length ? receivingDocuments.map(doc => `<form class="receiving-card" data-receiving-id="${escapeHtml(doc.id)}"><h3>${escapeHtml(doc.name)}</h3><p>${escapeHtml(doc.sender)} · ${escapeHtml(doc.batchNumber)} · ${Number(doc.weight).toLocaleString('ru-RU')} кг</p>${doc.legacy?'<p class="receiving-legacy">Пересчёт остатка</p>':''}<label>Принято, кг<input name="actualWeight" type="number" min="0" step="0.001" required value="${Number(Number(doc.weight).toFixed(3))}"></label><label>Причина расхождения / отказа<input name="reason" maxlength="500" placeholder="—"></label><div class="receiving-actions"><button class="primary-button" type="submit" name="decision" value="accept">Принять</button>${doc.legacy||doc.kind==='handover'?'':'<button class="danger-button" type="submit" name="decision" value="reject" formnovalidate>Отказать</button>'}</div></form>`).join('') : '<p class="production-hint">Нет ожидающих передач.</p>';
}
async function refreshReceiving() {
  const allowed = canReceive();
  $('#receivingButton').classList.toggle('hidden', !allowed);
  $('#servingWriteoffButton').classList.toggle('hidden', !allowed);
  $('#servingSurplusButton').classList.toggle('hidden', !allowed);
  if (!allowed) closeDrawer('#servingSurplusDrawer');
  if (!allowed) closeDrawer('#servingWriteoffDrawer');
  if (!allowed) { $('#receivingNotice').classList.add('hidden'); closeDrawer('#receivingDrawer'); receivingVersion=null; return; }
  if (receivingLoading || receivingBusy || !window.AshkanaApi.posReceiving) return;
  receivingLoading=true;
  const operatorId=activeOperator.id;
  try {
    const data=await window.AshkanaApi.posReceiving();
    if (activeOperator?.id!==operatorId || !canReceive()) return;
    const changed=JSON.stringify(data.documents)!==JSON.stringify(receivingDocuments);
    receivingDocuments=data.documents;
    $('#receivingCount').textContent=receivingDocuments.length;
    $('#receivingNotice').classList.toggle('hidden',!receivingDocuments.length);
    if (changed && !$('#receivingList').contains(document.activeElement)) renderReceiving();
    if (receivingVersion!==null && receivingVersion!==data.version) {
      const response=await window.AshkanaApi.workspace();
      if(activeOperator?.id===operatorId) { hydrateWorkspace(response); renderProducts();renderCart(); }
    }
    receivingVersion=data.version;
  } catch(error) { if(!$('#receivingDrawer').classList.contains('hidden')) $('#receivingError').textContent=error.message; }
  finally { receivingLoading=false; }
}
async function openReceiving() {
  if(!canReceive()) return;
  $('#receivingError').textContent='';
  $('#receivingDrawer').classList.remove('hidden');
  await refreshReceiving();renderReceiving();
}
$('#receivingButton').addEventListener('click',openReceiving);
$('#receivingList').addEventListener('submit',async event=>{
  event.preventDefault();
  if(receivingBusy || !canReceive()) return;
  const form=event.target.closest('[data-receiving-id]');if(!form)return;
  const decision=event.submitter?.value || 'accept';
  const doc=receivingDocuments.find(entry=>entry.id===form.dataset.receivingId);if(!doc)return;
  const weightInput=form.elements.actualWeight;
  const actualWeight=Number(weightInput.value)===Number(weightInput.defaultValue) ? Number(doc.weight) : Number(weightInput.value);
  const reason=form.elements.reason.value.trim();
  if((decision==='reject'||Math.abs(actualWeight-doc.weight)>0.000001)&&reason.length<3) { $('#receivingError').textContent='Укажите причину отказа или расхождения (не менее 3 символов)';return; }
  const payload={documentId:doc.id,actualWeight,reason};
  const signature=JSON.stringify({decision,...payload});
  if(!receivingRequests.has(signature)) receivingRequests.set(signature,crypto.randomUUID());
  payload.requestId=receivingRequests.get(signature);
  receivingBusy=true;$('#receivingError').textContent='';
  form.querySelectorAll('button').forEach(button=>button.disabled=true);
  try {
    const response=await window.AshkanaApi.action('pos.receiving.'+decision,payload);
    hydrateWorkspace(response);renderProducts();renderCart();
    receivingRequests.delete(signature);
    receivingDocuments=receivingDocuments.filter(entry=>entry.id!==doc.id);renderReceiving();
    refreshTransferHistory();
    showToast(decision==='accept'?'Блюдо принято и доступно для продажи':'Передача отклонена. Блюдо осталось на кухне');
  } catch(error) { $('#receivingError').textContent=error.message; }
  finally { receivingBusy=false;form.querySelectorAll('button').forEach(button=>button.disabled=false);await refreshReceiving(); }
});
setInterval(refreshReceiving,8000);

let kitchenShiftContext = {shift:null,counts:[]};
let kitchenShiftSaving=false;
let kitchenShiftRequest=null;
async function loadProductionShift() {
  if(activeOperator?.staffRole!=='production') return;
  const actor=activeOperator.id;
  try {
    const data=await window.AshkanaApi.posProductionContext();
    if(activeOperator?.id!==actor)return;
    kitchenShiftContext=data.productionShift || {shift:null,counts:[]};
    const shift=kitchenShiftContext.shift;
    const mine=shift&&String(shift.employeeId)===String(actor);
    $('#productionShiftStatus').textContent=shift ? (mine?'Смена производства открыта':'Смена у другого сотрудника'):'Смена производства не открыта';
    $('#productionShiftCaption').textContent=shift ? `${shift.employeeName} · с ${new Date(shift.openedAt).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}`:'Примите остатки кухни, чтобы начать работу';
    $('#productionShiftButton').textContent=mine?'Закрыть смену':'Принять смену';
    $('#productionShiftButton').disabled=Boolean(shift&&!mine);
  } catch(error) { $('#productionShiftStatus').textContent=error.message; throw error; }
}
async function requireProductionShift() {
  if(activeOperator?.staffRole!=='production')return true;
  try { await loadProductionShift(); } catch(error) { showToast(error.message);return false; }
  if(String(kitchenShiftContext.shift?.employeeId)===String(activeOperator.id))return true;
  showToast('Сначала примите смену производства');return false;
}
async function openProductionShift() {
  try { await loadProductionShift(); } catch(error) { showToast(error.message);return; }
  const closing=Boolean(kitchenShiftContext.shift);
  if(closing&&String(kitchenShiftContext.shift.employeeId)!==String(activeOperator.id))return;
  $('#productionShiftTitle').textContent=closing?'Закрыть смену':'Принять смену';
  $('#productionShiftSubmit').textContent=closing?'Закрыть смену':'Принять смену';
  $('#productionShiftContext').textContent=[$('#branchSelect').selectedOptions[0]?.textContent,activeOperator?.name].filter(Boolean).join(' · ');
  $('#productionShiftCounts').innerHTML=kitchenShiftContext.counts.map((row,index)=>productionCountRow({id:row.batchId,name:row.name,quantity:row.expectedWeight,unit:'кг',number:row.number},'batch',index)).join('');
  const ingredientStocks = kitchenShiftContext.ingredientStocks || [];
  $('#productionIngredientStocks').innerHTML=ingredientStocks.map((item,index)=>productionCountRow(item,'ingredient',index)).join('');
  $('#productionIngredientTotal').textContent=ingredientStocks.length;
  $('#productionShiftSearch').value='';
  updateStockCountReasons($('#productionShiftForm'));
  $('#productionShiftStockTotal').textContent=kitchenShiftContext.counts.length;
  filterProductionShiftRows();
  updateProductionShiftSummary();
  $('#productionShiftError').textContent='';kitchenShiftRequest=null;
  $('#productionShiftDrawer').classList.remove('hidden');
  $('#productionShiftScroll').scrollTop=0;
}
function productionCountRow(item, kind, index) {
  const nameId=`production-count-${kind}-${index}`;
  const expected=Number(item.quantity);
  const rounded=Number(expected.toFixed(3));
  const unit=escapeHtml(item.unit || 'кг');
  return `<div class="production-count-row" ${kind==='batch'?'data-kitchen-batch':'data-ingredient-count'}="${escapeHtml(String(item.id))}">
    <div class="production-count-name"><strong id="${nameId}">${escapeHtml(item.name)}</strong>${item.number?`<small>${escapeHtml(item.number)}</small>`:''}</div>
    <div class="production-count-expected" aria-label="По учёту: ${rounded} ${unit}">${rounded.toLocaleString('ru-RU',{maximumFractionDigits:3})} <span>${unit}</span></div>
    <div class="production-count-input"><input data-actual type="number" min="0" step="0.001" inputmode="decimal" required value="${rounded}" aria-label="Фактический остаток: ${escapeHtml(item.name)}, ${unit}"><span aria-hidden="true">${unit}</span></div>
    <input data-reason class="production-count-reason hidden" minlength="3" maxlength="500" placeholder="Причина расхождения" aria-label="Причина расхождения: ${escapeHtml(item.name)}">
  </div>`;
}
function filterProductionShiftRows() {
  const query=$('#productionShiftSearch').value.trim().toLocaleLowerCase('ru').replace(/ё/g,'е');
  let visible=0,total=0;
  ['#productionIngredientSection','#productionPreparedStocks'].forEach(selector=>{
    const section=$(selector);
    let matches=0;
    section.querySelectorAll('.production-count-row').forEach(row=>{
      const match=row.querySelector('.production-count-name').textContent.toLocaleLowerCase('ru').replace(/ё/g,'е').includes(query);
      row.classList.toggle('hidden',!match);
      total++;if(match)matches++;
    });
    section.classList.toggle('hidden',!matches);
    visible+=matches;
  });
  $('#productionCountEmpty').classList.toggle('hidden',visible>0);
  $('#productionCountEmpty').textContent=total?'Ничего не найдено':'Нет позиций для сверки';
}
function updateProductionShiftSummary() {
  const rows=[...$('#productionShiftForm').querySelectorAll('.production-count-row')];
  const changed=rows.filter(row=>!row.querySelector('[data-reason]').disabled).length;
  const incomplete=rows.filter(row=>!row.querySelector('[data-actual]').validity.valid).length;
  rows.forEach(row=>row.classList.toggle('is-changed',!row.querySelector('[data-reason]').disabled));
  $('#productionShiftSummary').innerHTML=`<strong>Позиций: ${rows.length}</strong><span>${incomplete?`Проверьте значения: ${incomplete}`:changed?`Изменено: ${changed}`:'Остатки совпадают'}</span>`;
}
// A displayed rounding difference is not a physical stock adjustment.
function stockCountValue(card, expected) {
  const input = card.querySelector('[data-actual]');
  return Number(input.value) === Number(input.defaultValue) ? Number(expected) : Number(input.value);
}

function updateStockCountReasons(container) {
  container.querySelectorAll('[data-actual]').forEach(input=>{
    const card=input.closest('[data-ingredient-count], [data-kitchen-batch], [data-closing-lot]');
    if(!card)return;
    const reason=card.querySelector('[data-reason]');
    const changed=input.value!=='' && Number.isFinite(Number(input.value)) && Math.round(Number(input.value)*1000)!==Math.round(Number(input.defaultValue)*1000);
    const field=reason.closest('label') || reason;
    field.classList.toggle('hidden',!changed);
    reason.required=changed;
    reason.disabled=!changed;
    if(!reason.hasAttribute('aria-label'))reason.setAttribute('aria-label','Причина расхождения');
    if(!changed)reason.value='';
  });
}
$('#productionShiftForm').addEventListener('input',event=>{
  if(event.target.matches('[data-actual]')) {
    updateStockCountReasons($('#productionShiftForm'));
    updateProductionShiftSummary();
  }
});
$('#productionShiftSearch').addEventListener('input',filterProductionShiftRows);
$('#productionShiftSearch').addEventListener('keydown',event=>{if(event.key==='Enter')event.preventDefault();});
// Search never excludes counted items from submission or hides validation errors.
$('#productionShiftForm').addEventListener('invalid',event=>{
  if(!event.target.closest('.production-count-row'))return;
  $('#productionShiftSearch').value='';
  filterProductionShiftRows();
},true);
function showProductionShiftError(error) {
  const message=error?.message || 'Не удалось выполнить действие. Повторите попытку.';
  const pendingKitchen=message.includes('Сначала завершите приёмку передач с кухни и рассмотрение списаний кухни');
  $('#productionShiftError').textContent=message;
  $('#productionShiftNoticeTitle').textContent=pendingKitchen?'Пока нельзя закрыть смену':'Не удалось выполнить действие';
  $('#productionShiftNoticeMessage').textContent=message;
  $('#productionShiftNoticeHelp').classList.toggle('hidden',!pendingKitchen);
  $('#productionShiftNotice').setAttribute('aria-describedby',pendingKitchen?'productionShiftNoticeMessage productionShiftNoticeHelp':'productionShiftNoticeMessage');
  if (!$('#productionShiftNotice').open) $('#productionShiftNotice').showModal();
}
$('#productionShiftNotice').addEventListener('close',()=>{
  if (!$('#productionShiftDrawer').classList.contains('hidden')) $('#productionShiftSubmit').focus({preventScroll:true});
});
$('#productionShiftButton').addEventListener('click',openProductionShift);
$('#productionShiftForm').addEventListener('submit',async event=>{
  event.preventDefault();if(kitchenShiftSaving)return;
  const counts=kitchenShiftContext.counts.map(row=>{const card=[...document.querySelectorAll('[data-kitchen-batch]')].find(el=>el.dataset.kitchenBatch===row.batchId);return {batchId:row.batchId,expectedWeight:row.expectedWeight,actualWeight:stockCountValue(card, row.expectedWeight),reason:card.querySelector('[data-reason]').value.trim()};});
  const action=kitchenShiftContext.shift?'production.shift.close':'production.shift.open';
  const ingredientCounts=(kitchenShiftContext.ingredientStocks || []).map(row=>{const card=[...document.querySelectorAll('[data-ingredient-count]')].find(el=>el.dataset.ingredientCount===String(row.id));return {id:String(row.id),expectedQuantity:row.quantity,actualQuantity:stockCountValue(card, row.quantity),reason:card.querySelector('[data-reason]').value.trim()};});
  const signature=JSON.stringify({action,counts,ingredientCounts});
  if(kitchenShiftRequest?.signature!==signature)kitchenShiftRequest={signature,id:crypto.randomUUID()};
  kitchenShiftSaving=true;$('#productionShiftSubmit').disabled=true;$('#productionShiftError').textContent='';
  try { const response=await window.AshkanaApi.action(action,{counts,ingredientCounts,requestId:kitchenShiftRequest.id});hydrateWorkspace(response);closeDrawer('#productionShiftDrawer');if(action.endsWith('open')) resetTransferHistory();await loadProductionShift();await refreshTransferHistory();if(action.endsWith('open')) { $('#operatorLock').classList.add('hidden');$('#operatorStepKitchen').classList.add('hidden'); } else { await lockOperator(); } showToast(action.endsWith('open')?'Смена производства принята':'Смена производства закрыта'); }
  catch(error) { showProductionShiftError(error); }
  finally { kitchenShiftSaving=false;$('#productionShiftSubmit').disabled=false; }
});

async function enterProductionShift() {
  if(activeOperator?.staffRole!=='production')return;
  const actor=activeOperator.id;
  $('#operatorLock').classList.remove('hidden');
  ['#operatorStepPin','#operatorStepShift'].forEach(selector=>$(selector).classList.add('hidden'));
  $('#operatorStepKitchen').classList.remove('hidden');
  $('#kitchenEntryMessage').textContent='Проверяем смену…';
  $('#kitchenEntryRetry').disabled=true;
  try {
    await loadProductionShift();
    if(activeOperator?.id!==actor)return;
    const shift=kitchenShiftContext.shift;
    if(shift && String(shift.employeeId)===String(actor)) {
      $('#operatorLock').classList.add('hidden');$('#operatorStepKitchen').classList.add('hidden');
    } else if(shift) {
      $('#kitchenEntryMessage').textContent=`Смена открыта у ${shift.employeeName}. Этот сотрудник должен закрыть смену и зафиксировать остатки кухни.`;
    } else {
      await openProductionShift();
    }
  } catch(error) { $('#kitchenEntryMessage').textContent=error.message || 'Не удалось проверить смену. Повторите попытку.'; }
  finally { $('#kitchenEntryRetry').disabled=false; }
}
function closeProductionShiftScreen() {
  if(!kitchenShiftContext.shift) { lockOperator(); return; }
  closeDrawer('#productionShiftDrawer');
}

let servingWriteoffData={lots:[],documents:[]};
let servingWriteoffBusy=false;
let servingWriteoffRequest=null;
function updateServingWriteoffQuantity() {
  const lot=servingWriteoffData.lots.find(lot=>lot.id===$('#servingWriteoffLot').value);
  const portions=$('#servingWriteoffUnit').value==='portions';
  const available=Number(lot?.availableWeight||0);
  $('#servingWriteoffQuantity').step=portions?'1':'0.001';
  $('#servingWriteoffQuantity').min=portions?'1':'0.001';
  $('#servingWriteoffQuantity').max=portions?(lot?.yield>0?Math.floor(available*1000/lot.yield+1e-8):0):available;
  $('#servingWriteoffAvailable').textContent=lot?`Доступно: ${available.toLocaleString('ru-RU')} кг · Принял: ${lot.responsibleName||'—'}`:'Выберите принятую партию';
  $('#servingWriteoffSubmit').disabled=servingWriteoffBusy||!lot||available<=0;
}
async function loadServingWriteoffs() {
  const actor=activeOperator?.id;
  const data=await window.AshkanaApi.posServingWriteoffs();
  if(activeOperator?.id!==actor||!canReceive())return;
  servingWriteoffData=data;
  const selected=$('#servingWriteoffLot').value;
  $('#servingWriteoffLot').innerHTML='<option value="">Выберите блюдо</option>'+data.lots.map(lot=>`<option value="${escapeHtml(lot.id)}">${escapeHtml(lot.name)} · ${escapeHtml(lot.batchNumber)} · ${Number(lot.availableWeight).toLocaleString('ru-RU')} кг</option>`).join('');
  if(data.lots.some(lot=>lot.id===selected))$('#servingWriteoffLot').value=selected;
  const statuses={pending:'Ожидает руководителя',approved:'Списано',rejected:'Отклонено — возвращено в продажу'};
  $('#servingWriteoffHistory').innerHTML=data.documents.length?data.documents.map(doc=>`<article class="receiving-card"><strong>${escapeHtml(doc.name)} · ${Number(doc.weight).toLocaleString('ru-RU')} кг</strong><p>${escapeHtml(statuses[doc.status]||doc.status)}</p><p>${escapeHtml(doc.reason)}</p><small>${escapeHtml(doc.actor?.name)} · ${new Date(doc.createdAt).toLocaleString('ru-RU')}${doc.reviewedBy?`<br>${escapeHtml(doc.reviewedBy.name)}: ${escapeHtml(doc.reviewNote||'')}`:''}</small></article>`).join(''):'<p class="production-hint">Заявок пока нет.</p>';
  updateServingWriteoffQuantity();
}
async function openServingWriteoff() {
  if(!canReceive())return;
  $('#servingWriteoffDrawer').classList.remove('hidden');
  $('#servingWriteoffError').textContent='';$('#servingWriteoffFields').disabled=true;$('#servingWriteoffSubmit').disabled=true;servingWriteoffData={lots:[],documents:[]};
  try { await loadServingWriteoffs(); } catch(error) { $('#servingWriteoffError').textContent=error.message; }
  finally { $('#servingWriteoffFields').disabled=false; }
}
$('#servingWriteoffButton').addEventListener('click',openServingWriteoff);
$('#servingWriteoffLot').addEventListener('change',updateServingWriteoffQuantity);
$('#servingWriteoffUnit').addEventListener('change',()=>{$('#servingWriteoffQuantity').value='';updateServingWriteoffQuantity();});
$('#servingWriteoffForm').addEventListener('submit',async event=>{
  event.preventDefault();if(servingWriteoffBusy||!canReceive())return;
  const lot=servingWriteoffData.lots.find(lot=>lot.id===$('#servingWriteoffLot').value);if(!lot)return;
  const comment=$('#servingWriteoffComment').value.trim();const reason=$('#servingWriteoffReason').value;
  if(!reason||(reason==='Другая причина'&&comment.length<3)) { $('#servingWriteoffError').textContent='Укажите причину списания';return; }
  const weight=Math.round(Number($('#servingWriteoffQuantity').value)*($('#servingWriteoffUnit').value==='portions'?Number(lot.yield)/1000:1)*1e6)/1e6;
  if(!Number.isFinite(weight)||weight<=0||weight>lot.availableWeight) { $('#servingWriteoffError').textContent='Проверьте количество';return; }
  const payload={batchId:lot.batchId,lotId:lot.id,weight,reason:reason+(comment?': '+comment:'')};
  const signature=JSON.stringify(payload);
  if(servingWriteoffRequest?.signature!==signature)servingWriteoffRequest={signature,id:crypto.randomUUID()};
  payload.requestId=servingWriteoffRequest.id;
  const actor=activeOperator.id;
  servingWriteoffBusy=true;$('#servingWriteoffFields').disabled=true;$('#servingWriteoffSubmit').disabled=true;$('#servingWriteoffError').textContent='';
  try {
    const response=await window.AshkanaApi.action('pos.serving.writeoff',payload);
    if(activeOperator?.id!==actor)return;
    hydrateWorkspace(response);renderProducts();renderCart();
    $('#servingWriteoffQuantity').value='';servingWriteoffRequest=null;
    showToast('Заявка отправлена руководителю. Количество исключено из продажи');
    try { await loadServingWriteoffs(); } catch(error) { $('#servingWriteoffError').textContent='Заявка сохранена. Откройте списания повторно для обновления остатков.'; }
  } catch(error) { $('#servingWriteoffError').textContent=error.message; }
  finally { servingWriteoffBusy=false;$('#servingWriteoffFields').disabled=false;updateServingWriteoffQuantity(); }
});


// A terminal function always uses the existing action and its role checks.
const functionTargets = ["workShiftButton", "historyButton", "shiftButton", "receivingButton", "servingWriteoffButton", "servingSurplusButton", "productionButton", "supplyButton", "cashMenuButton", "posAdminLink"];
const terminalActionCopy = {
  workShiftButton: ["Рабочее время", "Начать или закончить рабочий день для расчёта зарплаты"],
  historyButton: ["Чеки и возвраты", "Найти чек, посмотреть состав или оформить возврат"],
  shiftButton: ["Кассовая смена", "Открыть смену, проверить итоги или закрыть смену"],
  receivingButton: ["Принять с кухни", "Проверить количество и подтвердить приёмку"],
  servingWriteoffButton: ["Списать с раздачи", "Указать количество и причину списания"],
  servingSurplusButton: ["Зафиксировать излишек", "Отправить найденный излишек на подтверждение"],
  productionButton: ["Передать на раздачу", "Оформить передачу готовых блюд с кухни"],
  supplyButton: ["Принять поставку", "Указать продукты, количество и закупочную цену"],
  cashMenuButton: ["Деньги в кассе", "Внести или выдать наличные, посмотреть движения"],
  posAdminLink: ["Управление заведением", "Открыть меню, склад, финансы и сотрудников"],
};
function openTerminalFunctions() {
  $("#salesReportButton").classList.toggle("hidden", activeOperator?.role === "production" || activeOperator?.staffRole === "production");
  $("#salesImportButton").classList.toggle("hidden", activeOperator?.role === "production" || activeOperator?.staffRole === "production" || workspaceState.serviceMode === "restaurant");
  const container = $("#functionOperations");
  container.innerHTML = functionTargets.filter(id => !$("#" + id).classList.contains("hidden")).map(id => {
    const [label, hint] = terminalActionCopy[id];
    return `<button type="button" data-function-target="${id}"><strong>${escapeHtml(label)}</strong><small>${escapeHtml(hint)}</small></button>`;
  }).join("");
  if (canViewTransferHistory()) container.insertAdjacentHTML('beforeend', '<button type="button" data-function-transfer-history>История передач</button>');
  $("#terminalFunctions").classList.remove("hidden");
}
$("#terminalFunctionsButton").onclick = openTerminalFunctions;
$("#closeFunctions").onclick = () => $("#terminalFunctions").classList.add("hidden");
$("#terminalFunctions").addEventListener("click", event => {
  if (event.target === $("#terminalFunctions")) $("#terminalFunctions").classList.add("hidden");
  const button = event.target.closest("[data-function-target]");
  if (button) { $("#terminalFunctions").classList.add("hidden"); $("#" + button.dataset.functionTarget).click(); }
  if (event.target.closest('[data-function-transfer-history]')) { $("#terminalFunctions").classList.add("hidden"); openTransferHistory(); }
});
$("#functionSettings").onclick = () => { $("#terminalFunctions").classList.add("hidden"); openTerminalSettings(); };
$("#functionSync").onclick = () => { $("#terminalFunctions").classList.add("hidden"); syncTerminalWorkspace(); };
$("#checkoutKeypad").innerHTML = ["7","8","9","4","5","6","1","2","3",".","0","⌫"].map(key => `<button type="button" data-checkout-key="${key}">${key}</button>`).join("");
let checkoutEdited = false;
let checkoutCashAutomatic = true;
function fillCheckoutCashRemainder() {
  const noncash = ["card", "qr"].reduce((sum, method) => sum + Math.round(Number(paymentInput(method).value || 0) * 100), 0);
  if (Number.isFinite(noncash)) paymentInput("cash").value = Math.max(0, Math.round(cartTotal() * 100) - noncash) / 100;
}
let paymentSubmitting = false;
let replaceCheckoutAmount = true;
let checkoutAmountBuffer = "";
$("#payButton").addEventListener("click", () => { replaceCheckoutAmount = true; });
$("#checkoutKeypad").onclick = event => {
  const button = event.target.closest("[data-checkout-key]"); if (!button) return;
  checkoutEdited = true;
  const input = paymentInput(), key = button.dataset.checkoutKey;
  let value = replaceCheckoutAmount ? "" : checkoutAmountBuffer;
  value = key === "⌫" ? value.slice(0,-1) : key === "." && value.includes(".") ? value : value + key;
  if (value === ".") value = "0.";
  checkoutAmountBuffer = value;
  input.value = value.endsWith(".") ? value.slice(0,-1) : value;
  replaceCheckoutAmount = false; input.dispatchEvent(new Event("input", {bubbles:true}));
};
$("#checkoutQuickCash").onclick = event => {
  const button = event.target.closest("[data-cash-amount]"); if (!button) return;
  selectPaymentMethod("cash"); checkoutEdited = true; $("#cashReceived").value = button.dataset.cashAmount;
  replaceCheckoutAmount = true; $("#cashReceived").dispatchEvent(new Event("input", {bubbles:true}));
};
document.querySelectorAll("[data-payment-input]").forEach(input => {
  input.addEventListener("focus", () => {
    selectPaymentMethod(input.dataset.paymentInput, true);
    input.select();
  });
  input.addEventListener("input", () => {
    checkoutEdited = true;
    checkoutCashAutomatic = input.dataset.paymentInput !== "cash";
    if (checkoutCashAutomatic) fillCheckoutCashRemainder();
    if (document.activeElement === input) { checkoutAmountBuffer = input.value; replaceCheckoutAmount = false; }
    updatePaymentState();
  });
});

function supplyDraftKey() { return `o-post:supply:${currentSession?.tenantSlug}:${currentSession?.branchId}:${activeOperator?.id}`; }
const supplyDraftFields = ["posSupplyDate","posSupplySupplier","posSupplyInvoice","posSupplyComment","posSupplyPaymentMode","posSupplyAccount","posSupplyPaidAmount"];
function persistSupplyDraft(force = false) {
  if (force !== true && $("#supplyDrawer").classList.contains("hidden")) return;
  const fields = Object.fromEntries(supplyDraftFields.map(id => [id,$("#"+id).value]));
  const rows = [...document.querySelectorAll("#posSupplyLines .supply-line")].map(row => ({itemId:row.querySelector("[data-supply-item]").value,quantity:row.querySelector("[data-supply-quantity]").value,price:row.querySelector("[data-supply-price]").value,imported:Boolean(row.dataset.supplyImported)}));
  try { sessionStorage.setItem(supplyDraftKey(), JSON.stringify({fields,rows,photo:window.SupplyPhotos?.snapshot() || null})); } catch {}
}
function restoreSupplyDraft() {
  try {
    const draft = JSON.parse(sessionStorage.getItem(supplyDraftKey()) || "null"); if (!draft) return;
    supplyDraftFields.forEach(id => { if (draft.fields[id] !== undefined) $("#"+id).value = draft.fields[id]; });
    $("#posSupplyLines").innerHTML = ""; draft.rows.forEach(addPosSupplyLine); updatePosSupplyTotal(); updatePosSupplyPayment();
    window.SupplyPhotos?.restore(draft.photo);
  } catch {}
}
$("#posSupplyForm").addEventListener("input", persistSupplyDraft);
$("#posSupplyForm").addEventListener("change", persistSupplyDraft);
$("#posSupplyForm").addEventListener("click", () => queueMicrotask(persistSupplyDraft));

function salePaymentParts(sale) { return Array.isArray(sale.payments) ? sale.payments : [{method:sale.paymentMethod,amount:Number(sale.total || 0)}]; }
function salePaymentAmount(sale, method) { return salePaymentParts(sale).filter(part=>part.method===method).reduce((sum,part)=>sum+Number(part.amount || 0),0); }
function salePaymentSummary(sale) { return salePaymentParts(sale).map(part=>`${paymentLabels[part.method] || part.method}: ${money(part.amount)}`).join(" · "); }

function confirmProductionTransfer(items) {
  const dialog = $("#productionConfirmDialog");
  $("#productionConfirmSummary").textContent = `Блюд: ${items.length} · ${items.reduce((sum,item)=>sum+item.weight,0).toLocaleString("ru-RU")} кг`;
  return new Promise(resolve => {
    dialog.returnValue = "cancel";
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "send"), {once:true});
    dialog.showModal();
  });
}

let surplusData = {lots:[],documents:[]};
let surplusBusy = false;
let surplusRequest = null;
function updateSurplusForm() {
  const lot = surplusData.lots.find(lot=>lot.id===$('#servingSurplusLot').value);
  const portions = $('#servingSurplusUnit').value==='portions';
  $('#servingSurplusQuantity').min = portions?'1':'0.001';
  $('#servingSurplusQuantity').step = portions?'1':'0.001';
  $('#servingSurplusSubmit').disabled = surplusBusy || !lot || (portions && !(lot.yield>0));
}
async function loadServingSurpluses() {
  const actor=activeOperator?.id;
  const data=await window.AshkanaApi.posServingSurpluses();
  if(activeOperator?.id!==actor || !canReceive())return;
  surplusData=data;
  const selected=$('#servingSurplusLot').value;
  $('#servingSurplusLot').innerHTML='<option value="">Выберите блюдо</option>'+data.lots.map(lot=>`<option value="${escapeHtml(lot.id)}">${escapeHtml(lot.name)} · ${escapeHtml(lot.batchNumber)} · ${Number(lot.availableWeight).toLocaleString('ru-RU')} кг</option>`).join('');
  if(data.lots.some(lot=>lot.id===selected))$('#servingSurplusLot').value=selected;
  const labels={pending:'Ожидает руководителя',approved:'Подтверждено — добавлено на раздачу',rejected:'Отклонено'};
  $('#servingSurplusHistory').innerHTML=data.documents.length?data.documents.map(doc=>`<article><strong>${escapeHtml(doc.name)} · ${Number(doc.weight).toLocaleString('ru-RU')} кг</strong><p>${escapeHtml(labels[doc.status] || doc.status)}</p><small>${escapeHtml(doc.actor?.name)} · ${escapeHtml(doc.reason)}${doc.reviewedBy?`<br>${escapeHtml(doc.reviewedBy.name)}: ${escapeHtml(doc.reviewNote || '')}`:''}</small></article>`).join(''):'<p>Заявок нет</p>';
  updateSurplusForm();
}
async function openServingSurplus() {
  if(!canReceive())return;
  $('#servingSurplusDrawer').classList.remove('hidden');
  $('#servingSurplusFields').disabled=true;
  $('#servingSurplusSubmit').disabled=true;
  $('#servingSurplusError').textContent='';
  try { await loadServingSurpluses(); }
  catch(error) { surplusData={lots:[],documents:[]};$('#servingSurplusError').textContent=error.message; }
  finally { $('#servingSurplusFields').disabled=false;updateSurplusForm(); }
}
$('#servingSurplusButton').onclick=openServingSurplus;
$('#servingSurplusLot').onchange=updateSurplusForm;
$('#servingSurplusUnit').onchange=()=>{$('#servingSurplusQuantity').value='';updateSurplusForm();};
$('#servingSurplusDrawer').addEventListener('click',event=>{if(event.target===$('#servingSurplusDrawer'))closeDrawer('#servingSurplusDrawer');});
$('#servingSurplusForm').addEventListener('submit',async event=>{
  event.preventDefault();if(surplusBusy || !canReceive() || !event.target.reportValidity())return;
  const lot=surplusData.lots.find(lot=>lot.id===$('#servingSurplusLot').value);if(!lot)return;
  const quantity=Number($('#servingSurplusQuantity').value);
  const weight=Math.round(quantity*($('#servingSurplusUnit').value==='portions'?Number(lot.yield)/1000:1)*1e6)/1e6;
  const reason=$('#servingSurplusReason').value.trim();
  if(!Number.isFinite(weight)||weight<=0||reason.length<3){$('#servingSurplusError').textContent='Укажите количество и причину';return;}
  const actor=activeOperator.id;
  const payload={batchId:lot.batchId,lotId:lot.id,weight,reason};
  const signature=JSON.stringify({actor,...payload});
  if(surplusRequest?.signature!==signature)surplusRequest={signature,id:crypto.randomUUID()};
  payload.requestId=surplusRequest.id;
  surplusBusy=true;$('#servingSurplusFields').disabled=true;updateSurplusForm();$('#servingSurplusError').textContent='';
  try {
    const response=await window.AshkanaApi.action('pos.serving.surplus',payload);
    if(activeOperator?.id!==actor)return;
    hydrateWorkspace(response);renderCart();
    surplusRequest=null;$('#servingSurplusQuantity').value='';$('#servingSurplusReason').value='';
    showToast('Излишек отправлен руководителю на подтверждение');
    try { await loadServingSurpluses(); } catch(error) { $('#servingSurplusError').textContent='Заявка сохранена. Откройте раздел заново для обновления.'; }
  } catch(error) { $('#servingSurplusError').textContent=error.message; }
  finally { surplusBusy=false;$('#servingSurplusFields').disabled=false;updateSurplusForm(); }
});

let terminalSalesReport = null;
let reportRequest = 0;
let reportOptionsRequest = 0;
const reportLocalDate = date => new Date(date.getTime() - date.getTimezoneOffset()*60000).toISOString().slice(0,16);
const reportEndDate = () => {
  const end = new Date($('#reportTo').value);
  // The picker displays minutes: include every receipt in the selected minute.
  if (Number.isFinite(end.getTime())) end.setSeconds(59, 999);
  return end;
};
$('#salesReportButton').onclick = async () => {
  if (!allowProtectedAction('reports')) return;
  $('#terminalFunctions').classList.add('hidden');
  const now = new Date(), start = new Date(now); start.setHours(0,0,0,0);
  $('#reportFrom').value = reportLocalDate(start); $('#reportTo').value = reportLocalDate(now);
  $('#reportCashier').innerHTML = '<option value="">Все кассиры</option>';
  $('#salesReportResult').innerHTML = ''; $('#reportError').textContent = '';
  $('#salesReportActions').classList.add('hidden'); terminalSalesReport = null;
  $('#salesReportModal').classList.remove('hidden');
  // Load cashier options from the authenticated, branch-scoped report endpoint.
  const actor = activeOperator?.id, request = ++reportOptionsRequest;
  reportRequest++;
  try {
    const data = await window.AshkanaApi.salesReport({start:new Date($('#reportFrom').value).toISOString(), end:reportEndDate().toISOString(), products:false});
    if (actor !== activeOperator?.id || request !== reportOptionsRequest) return;
    $('#reportCashier').innerHTML += data.cashiers.map(row=>`<option value="${escapeHtml(row.id)}">${escapeHtml(row.name)}</option>`).join('');
  } catch(error) { if(request===reportOptionsRequest && actor===activeOperator?.id && !terminalSalesReport) $('#reportError').textContent=error.message; }
};
$('#closeSalesReport').onclick = () => { reportRequest++; reportOptionsRequest++; $('#salesReportModal').classList.add('hidden'); };
$('#salesReportForm').addEventListener('input', () => { reportRequest++; terminalSalesReport=null; $('#salesReportResult').innerHTML=''; $('#salesReportActions').classList.add('hidden'); });
$('#salesReportForm').onsubmit = async event => {
  event.preventDefault();
  const start = new Date($('#reportFrom').value), end = reportEndDate();
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) { $('#reportError').textContent='Укажите начало и окончание периода'; return; }
  if(start > end) { $('#reportError').textContent='Дата окончания раньше начала'; return; }
  const request=++reportRequest, actor=activeOperator?.id, button=event.submitter || $('#salesReportForm button[type="submit"]');
  button.disabled=true; $('#reportError').textContent=''; $('#salesReportActions').classList.add('hidden');
  try {
    const byProducts=$('#reportProducts').checked;
    const data=await window.AshkanaApi.salesReport({start:start.toISOString(), end:end.toISOString(), cashier:$('#reportCashier').value, products:byProducts});
    if(request!==reportRequest || actor!==activeOperator?.id) return;
    terminalSalesReport=data;
    const amount=value=>`${Number(value).toLocaleString('ru-RU',{maximumFractionDigits:2})} ${escapeHtml(data.currency)}`;
    const rows=[['Чеков',data.count],['Импортированных реестров',data.importCount || 0],['Возвратов',data.refundCount],['Продажи до скидок',amount(data.gross)],['Скидки',amount(data.discount)],['Оплачено',amount(data.sales)],['Возвращено',amount(data.refunds)],['Выручка с учётом возвратов',amount(data.net)],['Наличные',amount(data.payments.cash)],['Карта',amount(data.payments.card)],['QR',amount(data.payments.qr)],['Внешняя касса',amount(data.payments.external || 0)]];
    $('#salesReportResult').innerHTML=`<h3>${escapeHtml(data.branch)}</h3><p>${start.toLocaleString('ru-RU')} — ${end.toLocaleString('ru-RU')} · ${escapeHtml(data.cashier)}</p>${byProducts?`<div class="report-table-scroll"><table><thead><tr><th>Наименование</th><th>Кол-во</th><th>Цена</th><th>Сумма</th></tr></thead><tbody>${data.products.map(row=>`<tr><td>${escapeHtml(row.name)}</td><td>${Number(row.quantity).toLocaleString('ru-RU')} ${escapeHtml(row.unit)}</td><td>${amount(row.price)}</td><td>${amount(row.total)}</td></tr>`).join('') || '<tr><td colspan="4">Нет продаж за выбранный период</td></tr>'}</tbody></table></div><small>Товары — с учётом возвратов, до скидок.</small>`:''}<dl class="report-totals">${rows.map(([label,value])=>`<div><dt>${label}</dt><dd>${value}</dd></div>`).join('')}</dl>`;
    $('#salesReportActions').classList.remove('hidden');
  } catch(error) { if(request===reportRequest) $('#reportError').textContent=error.message; }
  finally { button.disabled=false; }
};
$('#reportExcel').onclick = () => {
  if(!terminalSalesReport)return;
  const bytes=Uint8Array.from(atob(terminalSalesReport.xlsx), char=>char.charCodeAt(0));
  const url=URL.createObjectURL(new Blob([bytes],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}));
  const link=document.createElement('a'); link.href=url; link.download=`Продажи-${$('#reportFrom').value.slice(0,10)}.xlsx`; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
};
$('#reportPrint').onclick = () => {
  if(!terminalSalesReport)return;
  const area=document.createElement('section'); area.id='posPrintArea'; area.innerHTML='<h1>Отчёт по продажам</h1>'+$('#salesReportResult').innerHTML;
  return submitPrintJob(area.innerHTML, "Oimo — отчёт по продажам", { ...terminalDeviceSettings, receiptPrinterMode: "browser" });
};

// On a phone the catalogue and receipt each use the full screen width.
(() => {
  const workspace = document.querySelector('.workspace');
  const orderPanel = document.querySelector('.order-panel');
  const orderBody = document.createElement('div');
  orderBody.className = 'responsive-order-body';
  const orderFooter = orderPanel.querySelector('.order-footer');
  Array.from(orderPanel.children).filter(child => !child.classList.contains('order-header') && child !== orderFooter).forEach(child => orderBody.append(child));
  orderPanel.insertBefore(orderBody, orderFooter);
  const navigation = document.createElement('nav');
  navigation.className = 'mobile-pos-navigation';
  navigation.setAttribute('aria-label', 'Рабочий экран кассы');
  navigation.innerHTML = '<button type="button" data-pos-view="catalog" aria-pressed="true">Меню</button><button type="button" data-pos-view="receipt" aria-pressed="false">Чек <span></span></button>';
  workspace.before(navigation);
  navigation.addEventListener('click', event => {
    const button = event.target.closest('[data-pos-view]');
    if (!button) return;
    document.body.dataset.posView = button.dataset.posView;
    navigation.querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  });
  const refresh = () => {
    navigation.classList.toggle('hidden', workspace.classList.contains('hidden'));
    navigation.querySelector('span').textContent = document.querySelector('#totalAmount').textContent;
  };
  new MutationObserver(refresh).observe(document.querySelector('#totalAmount'), {childList:true, subtree:true});
  new MutationObserver(refresh).observe(workspace, {attributes:true, attributeFilter:['class']});
  refresh();
})();

// Icon-only mobile controls retain names for assistive technology.
for (const [id, label] of Object.entries({openOrdersButton:'Заказы',historyButton:'Архив чеков',receivingButton:'Приёмка раздачи',cashierButton:'Сменить сотрудника',terminalFunctionsButton:'Функции терминала'})) {
  document.getElementById(id).setAttribute('aria-label', label);
  document.getElementById(id).setAttribute('title', label);
}

// Mobile workflow: orders → receipt → catalogue → payment.
(() => {
  const workspace=document.querySelector('.workspace');
  const home=document.createElement('section');home.id='mobileOrdersHome';
  home.innerHTML='<h2>Заказы</h2><div id="mobileOrderList"></div><button id="mobileNewOrder" type="button" class="pay-button">Новый заказ</button>';
  workspace.before(home);
  const header=document.createElement('div');header.className='mobile-flow-header';
  header.innerHTML='<button type="button" id="mobileFlowBack" aria-label="Назад">‹</button><strong id="mobileFlowTitle">Чек</strong><button type="button" id="mobileFlowClient">Клиент</button><button type="button" id="mobileOrderOptions" aria-label="Действия с заказом" aria-expanded="false">⋯</button>';
  workspace.before(header);
  const add=document.createElement('button');add.id='mobileAddItems';add.type='button';add.textContent='+ Добавить товар';
  document.querySelector('.order-footer').before(add);
  const back=document.createElement('button');back.id='mobileReturnReceipt';back.type='button';back.className='pay-button';back.textContent='Вернуться к заказу';workspace.after(back);
  window.mobilePosView=view=>{
    document.body.dataset.posView=view;
    document.querySelector('#mobileFlowTitle').textContent=view==='catalog'?'Выбор товаров':document.querySelector('#orderTitle').textContent;
    document.querySelector('#mobileFlowClient').hidden=view!=='receipt';
    document.querySelector('#mobileOrderOptions').hidden=view!=='receipt';
    home.classList.toggle('production-hidden',workspace.classList.contains('hidden'));
  };
  const refresh=()=>{
    document.querySelector('#mobileNewOrder').textContent=cart.size?'Продолжить заказ':'Новый заказ';
    document.querySelector('#mobileOrderList').innerHTML=(cart.size?'<button type="button" data-current-draft>Текущий заказ · '+escapeHtml(document.querySelector('#totalAmount').textContent)+'</button>':'')+(posState.openOrders||[]).map(order=>`<button type="button" data-mobile-order="${escapeHtml(order.id)}"><strong>${escapeHtml(order.label||order.number)}</strong><span>${money(orderTotal(order))}</span><small>${escapeHtml((order.items||[]).map(item=>item.name||products.find(p=>p.id===String(item.id))?.name||'Товар').join(', '))}</small></button>`).join('')||'<p class="history-empty">Открытых заказов нет</p>';
    home.classList.toggle('production-hidden',workspace.classList.contains('hidden'));
    header.classList.toggle('production-hidden',workspace.classList.contains('hidden'));
    back.classList.toggle('production-hidden',workspace.classList.contains('hidden'));
  };
  home.addEventListener('click',event=>{
    const order=event.target.closest('[data-mobile-order]');if(order){loadOpenOrder(order.dataset.mobileOrder);return;}
    if(event.target.closest('#mobileNewOrder,[data-current-draft]'))mobilePosView('receipt');
  });
  add.onclick=()=>{activeCategory=null;document.querySelector('#searchInput').value='';renderProducts();mobilePosView('catalog');};
  back.onclick=()=>mobilePosView('receipt');
  document.querySelector('#mobileFlowBack').onclick=()=>mobilePosView(document.body.dataset.posView==='catalog'?'receipt':'orders');
  document.querySelector('#mobileOrderOptions').onclick=()=>{const expanded=document.body.classList.toggle('mobile-order-options');document.querySelector('#mobileOrderOptions').setAttribute('aria-expanded',String(expanded));};
  document.querySelector('#mobileFlowClient').onclick=()=>document.querySelector('#customerButton').click();
  document.querySelector('#openOrdersButton').addEventListener('click',()=>{if(matchMedia('(max-width:700px)').matches){closeDrawer('#openOrdersDrawer');refresh();mobilePosView('orders');}});
  new MutationObserver(refresh).observe(document.querySelector('#openOrdersList'),{childList:true});
  new MutationObserver(refresh).observe(document.querySelector('#totalAmount'),{childList:true});
  new MutationObserver(refresh).observe(workspace,{attributes:true,attributeFilter:['class']});
  mobilePosView('orders');refresh();
})();


let salesImportData = null, salesImportFile = null, salesImportBusy = false;
function salesImportSelectionSummary(data, selections) {
  const totals = Object.fromEntries(['file', 'selected', 'posted', 'unmapped', 'unchecked'].map(key => [key, {count: 0, cents: 0}]));
  const choices = new Map(selections.map(choice => [String(choice.row), choice]));
  for (const row of data?.rows || []) {
    const amount = Number(row.total);
    const cents = Number.isFinite(amount) ? Math.round((amount + Number.EPSILON) * 100) : 0;
    const choice = choices.get(String(row.row));
    const bucket = row.posted ? 'posted' : !choice?.mapped ? 'unmapped' : choice.selected ? 'selected' : 'unchecked';
    for (const key of ['file', bucket]) { totals[key].count++; totals[key].cents += cents; }
  }
  return Object.fromEntries(Object.entries(totals).map(([key, value]) => [key, {count: value.count, amount: value.cents / 100}]));
}
function renderSalesImportSummary() {
  const element = $('#salesImportSummary');
  element.setAttribute('aria-live', 'polite');
  if (!salesImportData || $('#salesImportError').textContent) { element.textContent = ''; return; }
  const selections = [...$('#salesImportRows').querySelectorAll('[data-import-row]')].map(row => ({
    row: row.dataset.importRow,
    selected: row.querySelector('.import-select').checked,
    mapped: Boolean(row.querySelector('.import-recipe').value),
  }));
  const totals = salesImportSelectionSummary(salesImportData, selections);
  const labels = {file: 'В файле', selected: 'К импорту', posted: 'Уже проведено', unmapped: 'Без сопоставления', unchecked: 'Не выбрано'};
  element.innerHTML = Object.entries(labels).filter(([key]) => key === 'file' || key === 'selected' || totals[key].count)
    .map(([key, label]) => `${label}: ${totals[key].count} поз. · <strong>${escapeHtml(money(totals[key].amount))}</strong>`).join('<br>');
}
$('#salesImportButton').onclick = () => {
  $('#terminalFunctions').classList.add('hidden');
  $('#salesImportModal').classList.remove('hidden');
};
$('#closeSalesImport').onclick = () => { if (!salesImportBusy) $('#salesImportModal').classList.add('hidden'); };
$('#salesImportFile').onchange = async event => {
  const file = event.target.files[0];
  if (!file || salesImportBusy) return;
  salesImportData = null; salesImportFile = null;
  $('#salesImportRows').innerHTML = ''; $('#salesImportError').textContent = '';
  renderSalesImportSummary();
  $('#salesImportCommit').disabled = true;
  if (file.size > 2000000) { $('#salesImportError').textContent = 'Размер файла должен быть не больше 2 МБ'; return; }
  salesImportBusy = true; event.target.disabled = true;
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = ''; for (const byte of bytes) binary += String.fromCharCode(byte);
    const encoded = btoa(binary);
    const data = await AshkanaApi.previewSalesImport({file: encoded});
    salesImportData = data; salesImportFile = {file: encoded, fileName: file.name};
    const available = data.recipes;
    $('#salesImportRows').innerHTML = `<h3>${escapeHtml(data.title)}</h3>${data.rows.map(row => `<div class="sales-import-row" data-import-row="${escapeHtml(row.row)}"><label><input type="checkbox" class="import-select" ${row.posted ? 'disabled' : available.some(r => r.id === row.recipeId) ? 'checked' : ''}> ${escapeHtml(row.name)} — ${row.quantity} ${escapeHtml(row.unit)} · ${money(row.total)} ${row.posted ? '(уже проведено)' : ''}</label><select class="import-recipe" aria-label="Блюдо для ${escapeHtml(row.name)}" ${row.posted ? 'disabled' : ''}><option value="">Выберите блюдо или товар</option>${available.map(r => `<option value="${escapeHtml(r.id)}" ${row.recipeId === r.id ? 'selected' : ''}>${escapeHtml(r.name)} · ${Number(r.availablePortions).toLocaleString('ru-RU', {maximumFractionDigits:3})} ${escapeHtml(r.unit || 'порц.')}</option>`).join('')}</select></div>`).join('')}`;
  } catch (error) { $('#salesImportError').textContent = error.message; }
  finally { salesImportBusy = false; event.target.disabled = false; $('#salesImportRows').onchange(); }
};
$('#salesImportRows').onchange = event => {
  if (event) $('#salesImportError').textContent = '';
  if (event?.target.matches('.import-recipe')) {
    const row = event.target.closest('[data-import-row]');
    row.querySelector('.import-select').checked = Boolean(event.target.value);
  }
  const selected = [...document.querySelectorAll('[data-import-row]')].filter(r => r.querySelector('.import-select').checked);
  renderSalesImportSummary();
  $('#salesImportCommit').disabled = salesImportBusy || !selected.length || selected.some(r => !r.querySelector('.import-recipe').value);
};
$('#salesImportCommit').onclick = async () => {
  if (!salesImportFile || salesImportBusy) return;
  const selections = [...document.querySelectorAll('[data-import-row]')].filter(r => r.querySelector('.import-select').checked).map(r => ({row: r.dataset.importRow, recipeId: r.querySelector('.import-recipe').value}));
  if (!selections.length || !confirm(`Списать выбранные строки: ${selections.length}?`)) return;
  salesImportBusy = true; $('#salesImportCommit').disabled = true; $('#salesImportFile').disabled = true;
  $('#salesImportError').textContent = '';
  try {
    const response = await AshkanaApi.action('sale.import', {...salesImportFile, selections});
    hydrateWorkspace(response); renderWorkspace();
    $('#salesImportRows').innerHTML = ''; salesImportData = null; salesImportFile = null; $('#salesImportFile').value = '';
    showToast('Продажи из файла списаны с раздачи');
    $('#salesImportModal').classList.add('hidden');
  } catch(error) { $('#salesImportError').textContent = error.message; }
  finally { salesImportBusy = false; $('#salesImportFile').disabled = false; $('#salesImportRows').onchange(); }
};
