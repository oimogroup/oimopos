/* Pass the current admin.js source to runInventoryWorkflowTests in a JS runtime. */
function runInventoryWorkflowTests(source) {
  const passed = [];
  const assert = (condition, name) => {
    if (!condition) throw new Error(name);
    passed.push(name);
  };
  const load = (name, dependencies) => {
    const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
    if (start < 0) throw new Error(`Missing function ${name}`);
    const next = source.slice(start + 1).search(/\n(?:async )?function /);
    const body = next < 0 ? source.slice(start) : source.slice(start, start + 1 + next);
    return new Function(...Object.keys(dependencies), `${body}\nreturn ${name};`)(...Object.values(dependencies));
  };
  const elements = {};
  const element = (selector) => elements[selector] ||= {
    value: "", textContent: "", innerHTML: "", disabled: true,
    classList: { add() {}, remove() {} }
  };

  for (const item of [
    { itemId: "p-1", book: 10, currentBook: 15, actual: 9 },
    { itemId: "lot:accepted", lotId: "accepted", book: 4, currentBook: 4, actual: 3 }
  ]) {
    const calls = [];
    load("postInventory", {
      currentInventoryId: "count", currentRole: "owner", testMode: false, serverMode: true,
      inventoryById: () => ({ id: "count", number: "INV-1", status: "submitted", branchId: "b1", items: [item] }),
      branchStock: () => { throw new Error("Server counts must use authoritative backend stock checks"); },
      runServerAction: (action, payload) => { calls.push({ action, payload }); return null; },
      $: element
    })();
    assert(calls.length === 1 && calls[0].action === "inventory.post", `post-${item.lotId ? "serving" : "historical"}-reaches-server`);
  }

  const opened = [];
  const setupDependencies = {
    currentRole: "owner", testMode: false, currentSession: { name: "Owner" },
    pendingOwnerObjectScope: null, branches: [{ id: "b1", name: "First" }, { id: "b2", name: "Second" }],
    currentInventoryId: null, inventoryLockForBranch: () => ({ id: "existing" }),
    openInventoryDocument: (id) => opened.push(id), inventoryCategories: () => [],
    escapeHtml: String, $: element, prepareInventorySelection() {}
  };
  load("showInventorySetup", setupDependencies)();
  assert(opened.length === 0 && !element("#inventoryWarehouse").disabled && element("#inventoryWarehouse").innerHTML.includes('value="b2"'), "owner-can-choose-another-branch-during-count");
  load("showInventorySetup", { ...setupDependencies, currentRole: "branch", currentSession: { branchId: "b1", name: "Storekeeper" } })();
  assert(opened[0] === "existing", "branch-resumes-existing-count");

  const makeRow = (id, book, actual, cost) => {
    const difference = { textContent: "", className: "" };
    return {
      dataset: { inventoryItem: id, bookStock: String(book), unitCost: String(cost) },
      difference,
      querySelector: (selector) => selector === ".inventory-actual" ? { value: actual } : selector === ".inventory-diff" ? difference : null
    };
  };
  const rows = [makeRow("lot:accepted", 4, "3", 20), makeRow("p-1", 2, "3", 10), makeRow("lot:blank", 5, "", 20)];
  load("updateInventoryDifference", {
    currentInventoryId: "count", inventoryById: () => ({ items: [{ itemId: "lot:accepted", unit: "кг" }, { itemId: "lot:blank", unit: "кг" }] }),
    stockEntityById: (id) => id === "p-1" ? { unit: "шт" } : null,
    document: { querySelectorAll: () => rows }, decimal: String, money: String, $: element
  })();
  assert(rows[0].difference.textContent === "-1 кг", "serving-variance-keeps-snapshot-unit");
  assert(rows[1].difference.textContent === "+1 шт", "warehouse-variance-keeps-product-unit");
  assert(rows[2].difference.textContent === "—", "blank-count-stays-unfilled");
  assert(element("#inventorySurplus").textContent === "10" && element("#inventoryShortage").textContent === "20", "variance-cost-totals");
  return passed;
}
