(function createAshkanaApi(global) {
  class ApiError extends Error {
    constructor(message, status = 0, details = null) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.details = details;
    }
  }

  const protocol = location.protocol === "https:" ? "https:" : "http:";
  const hostname = location.hostname || "127.0.0.1";
  const candidates = location.protocol.startsWith("http")
    ? [`${location.origin}/api/v1`, `${protocol}//${hostname}:8001/api/v1`]
    : [`http://127.0.0.1:8001/api/v1`];
  let activeBase = "";
  try { activeBase = sessionStorage.getItem("ashkana-api-base-v1") || ""; } catch (_) { /* Storage is optional for API access. */ }
  if (!candidates.includes(activeBase)) activeBase = "";
  const pageName = location.pathname.split("/").pop() || "";
  let clientMode = ["index.html", "pos"].includes(pageName) || new URLSearchParams(location.search).get("mode") === "pos" ? "pos" : "admin";

  async function parseResponse(response) {
    const contentType = response.headers.get("content-type") || "";
    if (response.ok && response.status !== 204 && !contentType.includes("application/json")) throw new Error("Сервер вернул некорректное подтверждение");
    const body = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      const detail = body?.detail;
      const message = typeof detail === "string" ? detail : detail?.message || `Ошибка сервера (${response.status})`;
      throw new ApiError(message, response.status, detail);
    }
    return body;
  }

  async function request(path, options = {}) {
    const { retrySafe = false, ...fetchOptions } = options;
    const canRetry = ["GET", "HEAD"].includes((options.method || "GET").toUpperCase()) || retrySafe;
    const bases = activeBase ? [activeBase, ...candidates.filter((base) => base !== activeBase)] : candidates;
    let lastError = null;
    for (const base of bases) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), clientMode === "pos" && !/photos|import-preview|export|reports/.test(path) ? 8000 : 90000);
      try {
        let registerScope = {};
        if (clientMode === "pos" && !['/auth/me','/auth/login'].includes(path)) {
          try {
            const session = JSON.parse(sessionStorage.getItem('ashkana-auth-session-v1') || '{}');
            if (session.role === 'branch' && session.registerId) registerScope = {'X-Oimo-Register':String(session.registerId), ...session.tenantId && {'X-Oimo-Tenant':String(session.tenantId)}};
            if(operationActorId&&!['/pos/unlock','/pos/operator','/pos/operators','/pos/offline/receipts'].includes(path))registerScope['X-Oimo-Operator']=String(operationActorId);
          } catch (_) { /* Initial activation has no terminal scope yet. */ }
        }
        const response = await fetch(`${base}${path}`, {
          credentials: "include",
          headers: { "Content-Type": "application/json", "X-Ashkana-Client": clientMode, ...registerScope, ...(options.headers || {}) },
          signal: controller.signal,
          ...fetchOptions,
        });
        const contentType = response.headers.get("content-type") || "";
        if (canRetry && response.status === 404 && !contentType.includes("application/json") && base !== bases[bases.length - 1]) continue;
        const body = await parseResponse(response);
        activeBase = base;
        // A browser storage failure must not turn a confirmed write into a retry.
        try { sessionStorage.setItem("ashkana-api-base-v1", base); } catch (_) { /* Use the in-memory endpoint. */ }
        return body;
      } catch (error) {
        if (error instanceof ApiError) throw error;
        lastError = error;
        // A failed response does not mean a write failed. Only replay protected writes.
        if (!canRetry) throw new ApiError("Не удалось получить подтверждение операции. Проверьте её в истории перед повтором.", 0, error?.message);
      } finally {
        clearTimeout(timeout);
      }
    }
    throw new ApiError("Не удалось связаться с Oimo. Проверьте подключение к интернету и повторите попытку.", 0, lastError?.message);
  }

  const replayProtectedActions = new Set(["pnl.expense.create", "pnl.expense.void", "pnl.pay", "pnl.reverse", "payroll.policy", "payroll.time", "payroll.adjust", "payroll.approve", "payroll.pay", "payroll.advance", "payroll.reverse", "work.shift.open", "work.shift.close", "supply.create", "batch.create", "pos.cash.movement", "supply.pay", "supply.payment.reverse"]);
  const pendingActions = new Map();
  const pendingIds = new Map();
  let operationActorId = null;
  function operationScope() {
    let session = {};
    try { session = JSON.parse(sessionStorage.getItem("ashkana-auth-session-v1") || "{}"); } catch (_) { /* Server authorization remains authoritative. */ }
    return [clientMode, session?.tenantId, session?.tenantSlug, session?.branchId, session?.registerId, session?.login, operationActorId];
  }
  function canonicalPayload(value) {
    if (Array.isArray(value)) return value.map(canonicalPayload);
    if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonicalPayload(value[key])]));
    return value;
  }
  async function operationStorageKey(signature) {
    if (crypto.subtle) {
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(signature));
      return "oimo-pending-operation-" + Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
    }
    // Local terminals may use plain HTTP on a LAN, where SubtleCrypto is unavailable.
    // This hash only indexes pending IDs; the server still compares the full payload.
    let first = 2166136261, second = 5381;
    for (const character of signature) {
      first = Math.imul(first ^ character.codePointAt(0), 16777619);
      second = Math.imul(second, 33) ^ character.codePointAt(0);
    }
    return `oimo-pending-operation-${signature.length}-${(first >>> 0).toString(16)}-${(second >>> 0).toString(16)}`;
  }
  function newRequestId() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, "0")).join("");
  }
  function action(actionName, payload = {}) {
    if (!replayProtectedActions.has(actionName)) return request("/workspace/actions", { method: "POST", body: JSON.stringify({ action: actionName, payload }) });
    const signature = JSON.stringify([operationScope(), actionName, canonicalPayload(payload)]);
    if (pendingActions.has(signature)) return pendingActions.get(signature);
    const pending = (async () => {
      const storageKey = await operationStorageKey(signature);
      let requestId = payload.requestId || pendingIds.get(storageKey);
      try { requestId ||= sessionStorage.getItem(storageKey); } catch (_) { /* Keep the in-memory ID when storage is unavailable. */ }
      requestId ||= newRequestId();
      pendingIds.set(storageKey, requestId);
      try { sessionStorage.setItem(storageKey, requestId); } catch (_) { /* Private browser storage can be unavailable. */ }
      const result = await request("/workspace/actions", {
        method: "POST", retrySafe: true,
        body: JSON.stringify({ action: actionName, payload: { ...payload, requestId } }),
      });
      pendingIds.delete(storageKey);
      try { sessionStorage.removeItem(storageKey); } catch (_) { /* In-memory cleanup is sufficient for this session. */ }
      return result;
    })().finally(() => pendingActions.delete(signature));
    pendingActions.set(signature, pending);
    return pending;
  }

  global.AshkanaApi = {
    ApiError,
    setClientMode: (mode) => { clientMode = mode === "pos" ? "pos" : "admin"; },
    setOperationActor: (id) => { operationActorId = id == null ? null : String(id); },
    login: (login, password, registerId = null) => request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ login, password, ...(registerId ? { register_id: Number(registerId) } : {}) }),
    }),
    me: () => request("/auth/me"),
    logout: () => request("/auth/logout", { method: "POST", body: "{}" }),
    workspace: () => request("/workspace"),
    exportInventory: (id, items) => request(`/workspace/inventories/${encodeURIComponent(id)}/export`, { method: "POST", body: JSON.stringify({ items }) }),
    action,
    offlineLease: (token,version) => request('/pos/offline/lease', {method:'POST',body:JSON.stringify({token,version})}),
    syncOfflineReceipt: receipt => request('/pos/offline/receipts', {method:'POST',retrySafe:true,body:JSON.stringify(receipt)}),
    offlineConflicts: () => request('/offline/receipts'),
    resolveOfflineReceipt: payload => request('/offline/receipts/resolve', {method:'POST',retrySafe:true,body:JSON.stringify(payload)}),
    auditEvents: (limit = 100) => request(`/audit-events?limit=${encodeURIComponent(limit)}`),
    payroll: (start = "", end = "") => request(`/payroll?${new URLSearchParams({...start && {start}, ...end && {end}})}`),
    pnl: (start, end, branch = "all") => request(`/pnl?${new URLSearchParams({start, end, branch})}`),
    currentWorkShift: () => request("/pos/work-shift"),
    employees: () => request("/employees"),
    revealEmployeePin: (id) => request(`/employees/${encodeURIComponent(id)}/pin/reveal`, { method: "POST", body: "{}" }),
    createEmployee: (payload) => request("/employees", { method: "POST", body: JSON.stringify(payload) }),
    updateEmployee: (employeeId, payload) => request(`/employees/${encodeURIComponent(employeeId)}`, { method: "PUT", body: JSON.stringify(payload) }),
    deleteEmployee: (employeeId) => request(`/employees/${encodeURIComponent(employeeId)}`, { method: "DELETE" }),
    posRegisters: () => request("/pos/registers"),
    createPosRegister: (payload) => request("/pos/registers", { method: "POST", body: JSON.stringify(payload) }),
    updatePosRegister: (registerId, payload) => request(`/pos/registers/${encodeURIComponent(registerId)}`, { method: "PUT", body: JSON.stringify(payload) }),
    logoutPosRegister: (registerId) => request(`/pos/registers/${encodeURIComponent(registerId)}/logout`, { method: "POST", body: "{}" }),
    posOperators: () => request("/pos/operators"),
    posOperator: () => request("/pos/operator"),
    productionContext: (branchId) => request(`/production/context?branch_id=${encodeURIComponent(branchId)}`),
    posProductionContext: () => request("/pos/production/context"),
    posTransferHistory: () => request("/pos/transfers/history"),
    posShiftHistory: () => request("/pos/shifts/history"),
    posServingSurpluses: () => request("/pos/serving/surpluses"),
    posServingWriteoffs: () => request("/pos/serving/writeoffs"),
    posReceiving: () => request("/pos/receiving"),
    posSupplyContext: () => request("/pos/supplies/context"),
    previewSupplyImport: (payload) => request("/pos/supplies/import-preview", { method: "POST", body: JSON.stringify(payload) }),
    uploadSupplyPhoto: (payload) => request("/pos/supplies/photos", { method: "POST", body: JSON.stringify(payload) }),
    recognizeSupplyPhoto: (id) => request(`/pos/supplies/photos/${encodeURIComponent(id)}/recognize`, { method: "POST", body: "{}" }),
    unlockPos: (pin) => request("/pos/unlock", { method: "POST", body: JSON.stringify({ pin }) }),
    lockPos: () => request("/pos/lock", { method: "POST", body: "{}" }),
    previewSalesImport: (payload) => request("/pos/sales-import/preview", {method: "POST", body: JSON.stringify(payload)}),
    salesReport: (params) => request(`/pos/sales-report?${new URLSearchParams(params)}`),
    posShifts: (limit = 200) => request(`/pos/shifts?limit=${encodeURIComponent(limit)}`),
    openPosShift: (openingCash) => request("/pos/shifts/open", { method: "POST", body: JSON.stringify({ opening_cash: openingCash }) }),
    closingShiftStock: () => request("/pos/shifts/closing-stock"),
    closePosShift: (closingCash, stock = {}) => request("/pos/shifts/close", { method: "POST", body: JSON.stringify({ closing_cash: closingCash, ...stock }) }),
    connectionRequests: () => request("/platform/connection-requests"),
    mailStatus: () => request('/platform/mail'),
    testMail: () => request('/platform/mail/test', {method:'POST', body:'{}'}),
    retryMail: () => request('/platform/mail/retry', {method:'POST', body:'{}'}),
    markRequestContacted: id => request(`/platform/connection-requests/${encodeURIComponent(id)}/contacted`, {method:"PATCH",body:"{}"}),
    plans: () => request("/platform/plans"),
    updatePlan: (code, payload) => request(`/platform/plans/${encodeURIComponent(code)}`, { method: "PUT", body: JSON.stringify(payload) }),
    deleteTenant: (id, name) => request(`/platform/tenants/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ confirmation_name: name }) }),
    tenants: () => request("/platform/tenants"),
    createTenant: (payload) => request("/platform/tenants", { method: "POST", body: JSON.stringify(payload) }),
    updateTenant: (tenantId, payload) => request(`/platform/tenants/${encodeURIComponent(tenantId)}`, { method: "PUT", body: JSON.stringify(payload) }),
    updateTenantOwner: (tenantId, payload) => request(`/platform/tenants/${encodeURIComponent(tenantId)}/owner-access`, { method: "PUT", body: JSON.stringify(payload) }),
    platformEvents: (limit = 100) => request(`/platform/events?limit=${encodeURIComponent(limit)}`),
    clearEndpoint: () => {
      activeBase = "";
      try { sessionStorage.removeItem("ashkana-api-base-v1"); } catch (_) { /* The in-memory endpoint was cleared. */ }
    },
  };
})(window);
