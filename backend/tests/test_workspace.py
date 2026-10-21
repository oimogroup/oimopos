from custody_helpers import accepted_transfer
import pytest

from app.workspace import WorkspaceError, apply_action, default_state, visible_state


OWNER = {"id": 1, "login": "admin", "role": "owner", "branch_id": None, "display_name": "Администратор"}
BRANCH = {"id": 2, "login": "manasa", "role": "branch", "branch_id": "b1", "display_name": "Управляющий"}
POS_MANAGER = {**BRANCH, "staff_role": "branch_manager", "register_id": 10, "shift_id": 20}


def test_branch_creation_keeps_name_address_and_suppliers_separate() -> None:
    state = default_state()

    entity_type, branch_id = apply_action(state, OWNER, "branch.upsert", {
        "short": "Столовая на Аламедин",
        "address": "Бишкек, ул. Аламединская, 10",
        "phone": "+996 555 000 010",
        "openTime": "07:30",
        "closeTime": "19:30",
        "login": "ashkana",
        "status": "active",
    })

    branch = next(entry for entry in state["branches"] if entry["id"] == branch_id)
    assert entity_type == "branch"
    assert branch["name"] == "Столовая на Аламедин"
    assert branch["address"] == "Бишкек, ул. Аламединская, 10"
    assert branch["workHours"] == {"open": "07:30", "close": "19:30"}
    assert branch["managerName"] == "Не назначен"
    assert all(branch_id not in supplier["locations"] for supplier in state["suppliers"])
    assert all("b1" in supplier["locations"] for supplier in state["suppliers"])


def test_branch_cannot_approve_its_own_order() -> None:
    state = default_state()
    apply_action(state, BRANCH, "order.create", {
        "supplierId": "supplier-frunze",
        "neededAt": "2026-09-15",
        "items": [{"itemId": "rice", "requested": 5, "estimatedPrice": 0}],
    })
    order = state["logisticsState"]["directOrders"][0]

    with pytest.raises(WorkspaceError) as error:
        apply_action(state, BRANCH, "order.approve", {"id": order["id"]})

    assert error.value.status_code == 403
    assert order["status"] == "submitted"


def test_receipt_updates_only_branch_balance_and_writes_ledger() -> None:
    state = default_state()
    apply_action(state, BRANCH, "order.create", {
        "supplierId": "supplier-frunze",
        "neededAt": "2026-09-15",
        "items": [{"itemId": "rice", "requested": 5, "estimatedPrice": 100}],
    })
    order = state["logisticsState"]["directOrders"][0]
    apply_action(state, OWNER, "order.approve", {"id": order["id"]})
    apply_action(state, BRANCH, "order.send", {"id": order["id"], "method": "manual"})
    apply_action(state, BRANCH, "order.receive", {
        "id": order["id"],
        "invoiceNumber": "INV-1",
        "items": [{"itemId": "rice", "received": 4, "receivedPrice": 120, "temperature": 18}],
    })

    assert state["logisticsState"]["branchStocks"]["b1"]["rice"] == 72
    assert state["logisticsState"]["stockLedger"][0]["movementType"] == "supplier_receipt"
    assert state["logisticsState"]["stockLedger"][0]["quantity"] == 4


def test_supply_immediately_updates_stock_cost_payment_and_supplier_debt() -> None:
    state = default_state()

    entity_type, supply_id = apply_action(state, BRANCH, "supply.create", {
        "supplierId": "supplier-frunze",
        "invoiceNumber": "INV-POSTER-1",
        "receivedAt": "2026-09-19T09:30:00+06:00",
        "items": [{"itemId": "rice", "quantity": 4, "price": 120}],
        "payments": [{"accountId": "finance-bank", "amount": 300, "occurredAt": "2026-09-19T09:30:00+06:00"}],
    })

    supply = next(entry for entry in state["logisticsState"]["supplies"] if entry["id"] == supply_id)
    assert entity_type == "supplier_receipt"
    assert state["logisticsState"]["branchStocks"]["b1"]["rice"] == 72
    assert state["logisticsState"]["branchCosts"]["b1"]["rice"] == pytest.approx((68 * 96 + 4 * 120) / 72)
    assert supply["total"] == 480
    assert supply["paidTotal"] == 300
    assert supply["debt"] == 180
    assert supply["paymentStatus"] == "partial"
    assert state["logisticsState"]["stockLedger"][0]["movementType"] == "supplier_receipt"
    assert state["financeState"]["transactions"][0]["amount"] == 300
    assert state["financeState"]["transactions"][0]["documentId"] == supply_id

    with pytest.raises(WorkspaceError) as error:
        apply_action(state, BRANCH, "supply.create", {
            "supplierId": "supplier-frunze",
            "invoiceNumber": "inv-poster-1",
            "items": [{"itemId": "rice", "quantity": 1, "price": 100}],
        })
    assert error.value.status_code == 409


def test_branch_supply_accepts_only_assigned_supplier() -> None:
    state = default_state()
    state["suppliers"][0]["locations"] = []

    with pytest.raises(WorkspaceError) as error:
        apply_action(state, BRANCH, "supply.create", {
            "supplierId": "supplier-frunze",
            "items": [{"itemId": "rice", "quantity": 1, "price": 100}],
        })

    assert error.value.status_code == 403
    assert state["logisticsState"]["supplies"] == []


def test_sale_requires_serving_batch_and_uses_server_price() -> None:
    state = default_state()
    apply_action(state, BRANCH, "batch.create", {"recipeId": 201, "weight": 0.76})
    batch = state["logisticsState"]["batches"][0]
    accepted_transfer(state, BRANCH, {"id": batch["id"], "weight": 0.76, "temperature": 65, "line": "Линия №1"})

    apply_action(state, BRANCH, "sale.create", {
        "paymentMethod": "cash",
        "received": 500,
        "items": [{"id": 201, "quantity": 2, "price": 1}],
    })

    sale = state["sales"][0]
    assert sale["total"] == 460
    assert sale["change"] == 40
    assert sale["cashier"] == "Управляющий"
    assert sale["items"][0]["unitCost"] > 0
    assert batch["soldPortions"] == 2

    with pytest.raises(WorkspaceError):
        apply_action(state, BRANCH, "sale.create", {
            "paymentMethod": "card",
            "items": [{"id": 201, "quantity": 1}],
        })


def test_branch_workspace_hides_other_branch_balances_and_supplier_prices() -> None:
    state = default_state()
    state["branches"].append({"id": "b2", "number": 2, "short": "Тест", "name": "Столовая №2 — Тест", "login": "secret-login", "status": "active"})
    state["logisticsState"]["branchStocks"]["b2"] = {"rice": 999}
    state["logisticsState"]["branchCosts"]["b2"] = {"rice": 1}
    state["suppliers"][0]["prices"] = {"b1": {"rice": 100}, "b2": {"rice": 1}}

    visible = visible_state(state, BRANCH)

    assert set(visible["logisticsState"]["branchStocks"]) == {"b1"}
    assert set(visible["logisticsState"]["branchCosts"]) == {"b1"}
    assert set(visible["suppliers"][0]["prices"]) == {"b1"}
    assert "login" not in next(branch for branch in visible["branches"] if branch["id"] == "b2")


def test_cashier_workspace_hides_costs_and_purchase_documents() -> None:
    state = default_state()
    state["logisticsState"]["directOrders"].append({"id": "order-1", "branchId": "b1"})
    state["logisticsState"]["batches"].append({"id": "batch-1", "branchId": "b1", "recipeId": 201, "transferredWeight": 1, "soldPortions": 0, "status": "serving", "cost": 500})
    state["sales"].append({"id": "sale-1", "branchId": "b1", "items": [{"id": 201, "name": "Плов", "price": 200, "quantity": 1, "unitCost": 100}]})
    cashier = {**BRANCH, "staff_role": "cashier"}

    visible = visible_state(state, cashier)

    assert visible["ingredients"] == []
    assert visible["suppliers"] == []
    assert visible["logisticsState"]["branchCosts"] == {"b1": {}}
    assert visible["logisticsState"]["directOrders"] == []
    assert visible["logisticsState"]["supplies"] == []
    assert "components" not in visible["recipes"][0]
    assert "cost" not in visible["logisticsState"]["batches"][0]
    assert "unitCost" not in visible["sales"][0]["items"][0]

    terminal_visible = visible_state(state, {**BRANCH, "staff_role": "pos_terminal"})
    assert terminal_visible["ingredients"] == []
    assert terminal_visible["suppliers"] == []
    assert terminal_visible["logisticsState"]["branchCosts"] == {"b1": {}}


def test_sale_rejects_fractional_portions_and_duplicate_rows() -> None:
    state = default_state()
    apply_action(state, BRANCH, "batch.create", {"recipeId": 201, "weight": 0.76})
    batch = state["logisticsState"]["batches"][0]
    accepted_transfer(state, BRANCH, {"id": batch["id"], "weight": 0.76})

    with pytest.raises(WorkspaceError):
        apply_action(state, BRANCH, "sale.create", {"paymentMethod": "card", "items": [{"id": 201, "quantity": 0.5}]})

    with pytest.raises(WorkspaceError):
        apply_action(state, BRANCH, "sale.create", {"paymentMethod": "card", "items": [{"id": 201, "quantity": 1}, {"id": 201, "quantity": 1}]})


def test_pos_customer_discount_and_refund_restore_inventory() -> None:
    state = default_state()
    _, customer_id = apply_action(state, POS_MANAGER, "pos.customer.upsert", {
        "name": "Айжан", "phone": "+996700000001", "discountPercent": 10,
    })
    opening = state["logisticsState"]["branchStocks"]["b1"]["p-1"]

    _, sale_id = apply_action(state, POS_MANAGER, "sale.create", {
        "paymentMethod": "cash", "received": 100,
        "customerId": customer_id, "discountPercent": 10,
        "comment": "Без пакета", "items": [{"id": "p-1", "quantity": 2}],
    })

    sale = state["sales"][0]
    assert sale["id"] == sale_id
    assert sale["subtotal"] == 80
    assert sale["discountAmount"] == 8
    assert sale["total"] == 72
    assert sale["customerName"] == "Айжан"
    assert state["logisticsState"]["branchStocks"]["b1"]["p-1"] == opening - 2
    customer = state["posState"]["customers"][0]
    assert customer["visits"] == 1
    assert customer["revenue"] == 72

    apply_action(state, POS_MANAGER, "sale.refund", {"id": sale_id, "reason": "Ошибка кассира"})
    assert sale["refundedAt"]
    assert sale["refundReason"] == "Ошибка кассира"
    assert sale["refundShiftId"] == 20
    assert state["logisticsState"]["branchStocks"]["b1"]["p-1"] == opening
    assert state["logisticsState"]["stockLedger"][0]["movementType"] == "sale_refund"


def test_pos_open_orders_and_cash_movements_are_branch_scoped() -> None:
    state = default_state()
    _, order_id = apply_action(state, POS_MANAGER, "pos.order.save", {
        "label": "Стол 4", "items": [{"id": "p-1", "quantity": 2}],
    })
    _, movement_id = apply_action(state, POS_MANAGER, "pos.cash.movement", {
        "type": "deposit", "amount": 500, "comment": "Размен",
    })

    visible = visible_state(state, {**POS_MANAGER, "staff_role": "cashier"})
    assert visible["posState"]["openOrders"][0]["id"] == order_id
    assert visible["posState"]["cashMovements"][0]["id"] == movement_id
    assert visible["posState"]["cashMovements"][0]["shiftId"] == 20
    finance_transaction = state["financeState"]["transactions"][0]
    assert finance_transaction["sourceId"] == movement_id
    assert finance_transaction["accountId"] == "finance-safe"
    assert finance_transaction["destinationAccountId"] == "finance-cash-b1"

    apply_action(state, POS_MANAGER, "pos.order.remove", {"id": order_id})
    assert state["posState"]["openOrders"] == []


def test_transfer_requires_all_four_roles_steps_and_preserves_cost() -> None:
    state = default_state()
    state["branches"].append({"id": "b2", "number": 2, "short": "Вторая", "name": "Столовая №2 — Вторая", "status": "active"})
    state["logisticsState"]["branchStocks"]["b2"] = {"rice": 0}
    state["logisticsState"]["branchCosts"]["b2"] = {"rice": 0}
    destination = {**BRANCH, "id": 3, "login": "second", "branch_id": "b2", "display_name": "Получатель"}

    apply_action(state, destination, "transfer.create", {"sourceBranchId": "b1", "items": [{"itemId": "rice", "requested": 5}]})
    transfer = state["logisticsState"]["pointTransfers"][0]
    apply_action(state, OWNER, "transfer.approve", {"id": transfer["id"]})
    apply_action(state, BRANCH, "transfer.dispatch", {"id": transfer["id"]})
    apply_action(state, destination, "transfer.receive", {"id": transfer["id"], "items": [{"itemId": "rice", "received": 4}]})

    assert transfer["status"] == "received"
    assert transfer["variance"] == -1
    assert state["logisticsState"]["branchStocks"]["b1"]["rice"] == 63
    assert state["logisticsState"]["branchStocks"]["b2"]["rice"] == 4
    assert state["logisticsState"]["branchCosts"]["b2"]["rice"] == 96


def test_inventory_locks_movements_until_owner_posts_adjustment() -> None:
    state = default_state()
    apply_action(state, BRANCH, "inventory.start", {"scope": "category", "category": "Крупы", "responsible": "Кладовщик"})
    inventory = state["logisticsState"]["inventories"][0]

    with pytest.raises(WorkspaceError) as error:
        apply_action(state, BRANCH, "batch.create", {"recipeId": 201, "weight": 0.38})
    assert error.value.status_code == 409

    apply_action(state, BRANCH, "inventory.submit", {"id": inventory["id"], "items": [{"itemId": "rice", "actual": 67}]})
    apply_action(state, OWNER, "inventory.post", {"id": inventory["id"], "comment": "Проверено"})

    assert inventory["status"] == "posted"
    assert state["logisticsState"]["branchStocks"]["b1"]["rice"] == 67
    assert state["logisticsState"]["stockLedger"][0]["movementType"] == "inventory_adjustment"


def test_supplier_invoice_number_cannot_be_received_twice() -> None:
    state = default_state()
    for suffix in (1, 2):
        apply_action(state, BRANCH, "order.create", {"supplierId": "supplier-frunze", "items": [{"itemId": "rice", "requested": 1}]})
        order = state["logisticsState"]["directOrders"][0]
        apply_action(state, OWNER, "order.approve", {"id": order["id"]})
        apply_action(state, BRANCH, "order.send", {"id": order["id"]})
        if suffix == 1:
            apply_action(state, BRANCH, "order.receive", {"id": order["id"], "invoiceNumber": "INV-SAME", "items": [{"itemId": "rice", "received": 1, "receivedPrice": 100}]})
        else:
            with pytest.raises(WorkspaceError) as error:
                apply_action(state, BRANCH, "order.receive", {"id": order["id"], "invoiceNumber": "inv-same", "items": [{"itemId": "rice", "received": 1, "receivedPrice": 100}]})
            assert error.value.status_code == 409


def test_owner_can_create_and_edit_preparation_with_calculated_cost() -> None:
    state = default_state()
    payload = {
        "name": "Тесто тестовое",
        "category": "Заготовки кухни",
        "station": "Кухня",
        "yield": 1000,
        "process": "Замесить и выдержать 30 минут",
        "usedIn": "Лагман",
        "components": [
            {"ingredientId": "flour", "gross": 950, "net": 950},
            {"ingredientId": "salt", "gross": 20, "net": 20},
        ],
    }

    entity_type, entity_id = apply_action(state, OWNER, "preparation.upsert", payload)
    preparation = state["preparations"][0]

    assert entity_type == "preparation"
    assert preparation["id"] == entity_id
    assert preparation["cost"] == pytest.approx(51.9)
    assert preparation["process"] == "Замесить и выдержать 30 минут"
    assert len(preparation["components"]) == 2

    apply_action(state, OWNER, "preparation.upsert", {**payload, "id": entity_id, "name": "Тесто обновлённое", "yield": 1200})
    assert len(state["preparations"]) == 1
    assert state["preparations"][0]["name"] == "Тесто обновлённое"
    assert state["preparations"][0]["yield"] == 1200


def test_branch_cannot_manage_preparations() -> None:
    state = default_state()
    with pytest.raises(WorkspaceError) as error:
        apply_action(state, BRANCH, "preparation.upsert", {
            "name": "Запрещённая заготовка",
            "category": "Заготовки кухни",
            "station": "Кухня",
            "yield": 1000,
            "components": [{"ingredientId": "flour", "gross": 1000, "net": 1000}],
        })

    assert error.value.status_code == 403


def test_owner_can_create_and_rename_catalog_categories() -> None:
    state = default_state()

    apply_action(state, OWNER, "category.upsert", {
        "kind": "menu", "originalName": "Горячее", "name": "Основные блюда", "color": "#123456",
    })
    apply_action(state, OWNER, "category.upsert", {
        "kind": "menu", "name": "Детское меню", "color": "#abcdef",
    })
    apply_action(state, OWNER, "category.upsert", {
        "kind": "ingredient", "originalName": "Крупы", "name": "Крупы и зерно",
    })

    assert all(recipe["category"] == "Основные блюда" for recipe in state["recipes"] if recipe["id"] in {201, 203, 205})
    assert next(c for c in state["menuCategories"] if c["name"] == "Основные блюда")["color"] == "#123456"
    assert any(category["name"] == "Детское меню" for category in state["menuCategories"])
    assert next(ingredient for ingredient in state["ingredients"] if ingredient["id"] == "rice")["category"] == "Крупы и зерно"
    assert "Крупы и зерно" in state["ingredientCategories"]


def test_branch_cannot_manage_catalog_categories() -> None:
    state = default_state()
    with pytest.raises(WorkspaceError) as error:
        apply_action(state, BRANCH, "category.upsert", {"kind": "menu", "name": "Запрещённая"})

    assert error.value.status_code == 403


def test_owner_can_create_and_rename_station_with_linked_cards() -> None:
    state = default_state()
    state["preparations"].append({
        "id": "pf-test", "name": "Бульон", "category": "Заготовки кухни",
        "station": "Кухня", "yield": 1000, "components": [],
    })

    apply_action(state, OWNER, "station.upsert", {
        "originalName": "Кухня", "name": "Горячий цех", "branchId": "b1",
        "destination": "Экран горячего цеха",
    })
    apply_action(state, OWNER, "station.upsert", {
        "name": "Кондитерский цех", "branchId": "b1", "destination": "Без печати",
    })

    assert next(station for station in state["stations"] if station["name"] == "Горячий цех")["warehouse"] == "Склад · Столовая №1 — Манаса"
    assert any(station["name"] == "Кондитерский цех" for station in state["stations"])
    assert all(recipe["station"] == "Горячий цех" for recipe in state["recipes"] if recipe["category"] != "Салаты")
    assert state["preparations"][0]["station"] == "Горячий цех"


def test_legacy_workspace_without_stations_gets_safe_defaults() -> None:
    state = default_state()
    del state["stations"]

    visible = visible_state(state, OWNER)
    assert [station["name"] for station in visible["stations"]] == ["Кухня", "Холодный цех", "Бар"]

    apply_action(state, OWNER, "station.upsert", {
        "originalName": "Кухня", "name": "Основная кухня", "branchId": "b1", "destination": "Экран №1",
    })
    assert any(station["name"] == "Основная кухня" for station in state["stations"])


def test_branch_cannot_manage_stations() -> None:
    state = default_state()
    with pytest.raises(WorkspaceError) as error:
        apply_action(state, BRANCH, "station.upsert", {
            "name": "Запрещённый цех", "branchId": "b1", "destination": "Без печати",
        })

    assert error.value.status_code == 403


def test_owner_can_manage_finance_accounts_categories_and_transactions() -> None:
    state = default_state()

    _, account_id = apply_action(state, OWNER, "finance.account.upsert", {
        "name": "Карта банка", "type": "card", "openingBalance": 1000, "status": "active",
    })
    _, category_id = apply_action(state, OWNER, "finance.category.upsert", {
        "name": "Ремонт оборудования", "kind": "expense", "status": "active",
    })
    _, transaction_id = apply_action(state, OWNER, "finance.transaction.create", {
        "type": "expense", "occurredAt": "2026-09-17", "accountId": account_id,
        "categoryId": category_id, "branchId": "b1", "amount": 350,
        "counterparty": "Сервис", "comment": "Ремонт плиты",
    })

    finance = state["financeState"]
    assert next(account for account in finance["accounts"] if account["id"] == account_id)["openingBalance"] == 1000
    assert next(category for category in finance["categories"] if category["id"] == category_id)["kind"] == "expense"
    transaction = next(entry for entry in finance["transactions"] if entry["id"] == transaction_id)
    assert transaction["amount"] == 350
    assert transaction["branchId"] == "b1"

    apply_action(state, OWNER, "finance.transaction.delete", {"id": transaction_id})
    assert not finance["transactions"]


def test_finance_management_is_owner_only_but_branch_can_see_payment_accounts() -> None:
    state = default_state()

    with pytest.raises(WorkspaceError) as error:
        apply_action(state, BRANCH, "finance.transaction.create", {
            "type": "expense", "occurredAt": "2026-09-17", "accountId": "finance-bank",
            "categoryId": "finance-expense-other", "amount": 1,
        })

    assert error.value.status_code == 403
    visible_finance = visible_state(state, BRANCH)["financeState"]
    assert visible_finance["transactions"] == []
    assert visible_finance["categories"] == []
    assert {account["id"] for account in visible_finance["accounts"]} >= {"finance-bank", "finance-safe", "finance-cash-b1"}


def test_owner_can_delete_unused_catalog_entries() -> None:
    state = default_state()

    _, ingredient_id = apply_action(state, OWNER, "ingredient.upsert", {
        "id": "unused-ingredient", "name": "Ошибочный ингредиент", "category": "Бакалея", "unit": "кг",
    })
    apply_action(state, OWNER, "catalog.delete", {"kind": "ingredient", "id": ingredient_id})
    assert all(ingredient["id"] != ingredient_id for ingredient in state["ingredients"])
    assert ingredient_id not in state["logisticsState"]["branchStocks"]["b1"]

    _, product_id = apply_action(state, OWNER, "product.upsert", {
        "id": "unused-product", "name": "Ошибочный товар", "category": "Дополнительно", "unit": "шт", "price": 10,
    })
    apply_action(state, OWNER, "catalog.delete", {"kind": "product", "id": product_id})
    assert all(product["id"] != product_id for product in state["products"])

    _, recipe_id = apply_action(state, OWNER, "recipe.upsert", {
        "name": "Ошибочная техкарта", "category": "Горячее", "station": "Кухня", "price": 10, "yield": 999,
        "components": [{"ingredientId": "salt", "gross": 1, "net": 1}],
    })
    assert next(recipe for recipe in state["recipes"] if str(recipe["id"]) == recipe_id)["yield"] == 999
    apply_action(state, OWNER, "catalog.delete", {"kind": "recipe", "id": recipe_id})
    assert all(str(recipe["id"]) != recipe_id for recipe in state["recipes"])

    _, preparation_id = apply_action(state, OWNER, "preparation.upsert", {
        "name": "Ошибочный полуфабрикат", "category": "Заготовки кухни", "station": "Кухня", "yield": 100,
        "components": [{"ingredientId": "salt", "gross": 1, "net": 1}],
    })
    apply_action(state, OWNER, "catalog.delete", {"kind": "preparation", "id": preparation_id})
    assert all(preparation["id"] != preparation_id for preparation in state["preparations"])

    apply_action(state, OWNER, "category.upsert", {"kind": "menu", "name": "Пустая категория", "color": "#123456"})
    apply_action(state, OWNER, "catalog.delete", {"kind": "menu-category", "id": "Пустая категория"})
    assert all(category["name"] != "Пустая категория" for category in state["menuCategories"])

    apply_action(state, OWNER, "station.upsert", {"name": "Пустой цех", "branchId": "b1", "destination": "Без печати"})
    apply_action(state, OWNER, "catalog.delete", {"kind": "station", "id": "Пустой цех"})
    assert all(station["name"] != "Пустой цех" for station in state["stations"])


def test_catalog_delete_protects_links_stock_history_and_permissions() -> None:
    state = default_state()

    protected = [
        {"kind": "ingredient", "id": "rice"},
        {"kind": "product", "id": "p-1"},
        {"kind": "menu-category", "id": "Горячее"},
        {"kind": "ingredient-category", "id": "Крупы"},
        {"kind": "station", "id": "Кухня"},
    ]
    for payload in protected:
        with pytest.raises(WorkspaceError) as error:
            apply_action(state, OWNER, "catalog.delete", payload)
        assert error.value.status_code == 409

    apply_action(state, BRANCH, "batch.create", {"recipeId": 201, "weight": 0.38})
    with pytest.raises(WorkspaceError) as error:
        apply_action(state, OWNER, "catalog.delete", {"kind": "recipe", "id": 201})
    assert error.value.status_code == 409

    with pytest.raises(WorkspaceError) as error:
        apply_action(state, BRANCH, "catalog.delete", {"kind": "preparation", "id": "missing"})
    assert error.value.status_code == 403


def test_recipe_keeps_finished_output_separate_from_raw_weights() -> None:
    state = default_state()
    _, recipe_id = apply_action(state, OWNER, "recipe.upsert", {
        "name": "Cooked rice", "station": "Kitchen", "yield": 300, "price": 70,
        "components": [{"ingredientId": "rice", "gross": 100, "net": 100}],
    })
    recipe = next(r for r in state["recipes"] if str(r["id"]) == recipe_id)
    assert recipe["yield"] == 300
    assert recipe["components"][0]["net"] == 100
    with pytest.raises(WorkspaceError):
        apply_action(state, OWNER, "recipe.upsert", {
            **recipe, "yield": 0,
        })


def test_saved_order_removed_only_after_successful_payment():
    state = default_state()
    order = {'id': 'saved-test', 'branchId': 'b1', 'items': [{'id': 'p-1', 'quantity': 2}]}
    state['posState']['openOrders'].append(order)
    payload = {'openOrderId': order['id'], 'paymentMethod': 'cash', 'received': 1, 'items': order['items']}
    with pytest.raises(WorkspaceError):
        apply_action(state, POS_MANAGER, 'sale.create', payload)
    assert order in state['posState']['openOrders']
    apply_action(state, POS_MANAGER, 'sale.create', {**payload, 'received': 100})
    assert not any(o['id'] == order['id'] for o in state['posState']['openOrders'])
    with pytest.raises(WorkspaceError):
        apply_action(state, POS_MANAGER, 'sale.create', {**payload, 'received': 100})


def test_supply_debt_payment_partial_full_and_retry():
    from copy import deepcopy
    s=default_state()
    account={'id':'test-account','status':'active','branchId':'b1'}
    s['financeState']={'accounts':[account],'categories':[],'transactions':[]}
    s['logisticsState']['supplies'].append({'id':'test-debt','number':'TEST','supplier':'Test','branchId':'b1','total':100,'paidTotal':0,'debt':100,'payments':[]})
    stocks=deepcopy(s['logisticsState']['branchStocks'])
    payload={'id':'test-debt','accountId':account['id'],'amount':40,'requestId':'one'}
    apply_action(s,OWNER,'supply.pay',payload)
    apply_action(s,OWNER,'supply.pay',payload)
    doc=s['logisticsState']['supplies'][-1]
    assert doc['debt']==60 and len(doc['payments'])==1
    with pytest.raises(WorkspaceError):apply_action(s,OWNER,'supply.pay',{**payload,'requestId':'two','amount':61})
    apply_action(s,OWNER,'supply.pay',{**payload,'requestId':'two','amount':60})
    assert doc['paymentStatus']=='paid' and doc['debt']==0
    assert s['logisticsState']['branchStocks']==stocks
