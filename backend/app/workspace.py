from __future__ import annotations
from . import custody

import re
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from math import floor, isfinite
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from .company_settings import company_settings, validate_settings_section, require_manager


class WorkspaceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def sale_payment_amount(sale: dict, method: str) -> Decimal:
    if isinstance(sale.get("payments"), list):
        return sum((Decimal(str(part.get("amount", 0))) for part in sale["payments"] if part.get("method") == method), Decimal(0))
    return Decimal(str(sale.get("total", 0))) if sale.get("paymentMethod") == method else Decimal(0)


def normalize_sale_payments(payload: dict, total: float) -> tuple[list[dict], str, float, float]:
    methods = {"cash", "card", "qr"}
    raw = payload.get("payments")
    if raw is None:
        method = payload.get("paymentMethod", "cash")
        _require(isinstance(method, str) and method in methods, "Неизвестный способ оплаты")
        raw = [{"method": method, "amount": payload.get("received") if method == "cash" else total}]
    _require(isinstance(raw, list) and 1 <= len(raw) <= 3, "Укажите суммы по способам оплаты")
    amounts = {}
    for part in raw:
        _require(isinstance(part, dict), "Некорректная оплата")
        method = part.get("method")
        _require(isinstance(method, str) and method in methods and method not in amounts, "Неизвестный или повторяющийся способ оплаты")
        try:
            amount = Decimal(str(part.get("amount")))
        except (InvalidOperation, ValueError, TypeError):
            raise WorkspaceError("Некорректная сумма оплаты")
        _require(amount.is_finite() and 0 < amount <= Decimal("999999999") and amount == amount.quantize(Decimal("0.01")), "Сумма оплаты должна быть положительной, с точностью до двух знаков")
        amounts[method] = amount
    due = Decimal(str(total))
    received = sum(amounts.values(), Decimal(0))
    noncash = amounts.get("card", Decimal(0)) + amounts.get("qr", Decimal(0))
    _require(received >= due, "Полученная сумма меньше итога чека")
    _require(noncash <= due, "Сумма карты и QR превышает итог чека")
    change = received - due
    parts = [{"method": method, "amount": float(amount - change if method == "cash" else amount),
              "received": float(amount)} for method, amount in amounts.items()]
    parts = [part for part in parts if part["amount"] > 0]
    _require(bool(parts), "Итог чека должен быть больше нуля")
    return parts, parts[0]["method"] if len(parts) == 1 else "mixed", float(received), float(change)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(condition: bool, message: str, status_code: int = 400) -> None:
    if not condition:
        raise WorkspaceError(message, status_code)


def _owner(user: dict[str, Any]) -> None:
    _require(user["role"] == "owner" or bool(user.get("_company_write")), "Действие доступно только главному администратору", 403)


def _branch_user(user: dict[str, Any]) -> str:
    _require(user["role"] == "branch" and user.get("branch_id"), "Действие доступно только сотруднику точки", 403)
    return str(user["branch_id"])


def _find(entries: list[dict[str, Any]], entry_id: Any) -> dict[str, Any] | None:
    return next((entry for entry in entries if str(entry.get("id")) == str(entry_id)), None)


def _number(value: Any, *, minimum: float = 0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0
    if not isfinite(number):
        number = 0
    return max(minimum, number)


def _money(value: Any) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _receipt_time(value: Any) -> str:
    if not value:
        return _now()
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        _require(date.tzinfo is not None and date <= datetime.now(timezone.utc), "Проверьте дату и время приёмки")
        return date.isoformat()
    except (ValueError, TypeError):
        raise WorkspaceError("Проверьте дату и время приёмки")


def _supply_cash_payment(state: dict, user: dict, account: dict, payment: dict, supply: dict) -> None:
    """Link drawer expenses to the actual register shift without duplicating finance entries."""
    if account.get("type") != "cash":
        return
    _require(user.get("register_id") and user.get("shift_id") and str(account.get("branchId")) == str(user.get("branch_id")),
             "Оплату из кассы оформите в терминале на открытой смене. В админке выберите сейф или банковский счёт", 409)
    _ensure_pos(state)["cashMovements"].insert(0, {
        "id": f"supply-cash-{payment['id']}", "branchId": supply["branchId"],
        "registerId": user["register_id"], "shiftId": user["shift_id"],
        "type": "expense", "amount": payment["amount"],
        "comment": f"Оплата поставки {supply['number']}", "documentId": supply["id"], "paymentId": payment["id"],
        "createdAt": _now(), "createdBy": user["display_name"],
    })


def _next_number(prefix: str, collection: list[dict[str, Any]]) -> str:
    return f"{prefix}-{len(collection) + 1:04d}"


def _entity(state: dict[str, Any], item_id: Any) -> dict[str, Any] | None:
    return _find(state["ingredients"], item_id) or _find(state["products"], item_id)


def _recipe(state: dict[str, Any], recipe_id: Any) -> dict[str, Any] | None:
    return _find(state["recipes"], recipe_id)


def _stock(state: dict[str, Any], branch_id: str, item_id: Any) -> float:
    return _number(state["logisticsState"]["branchStocks"].get(branch_id, {}).get(str(item_id), 0))


def _cost(state: dict[str, Any], branch_id: str, item_id: Any) -> float:
    entity = _entity(state, item_id) or {}
    return _number(state["logisticsState"]["branchCosts"].get(branch_id, {}).get(str(item_id), entity.get("averageCost", 0)))


def _set_stock(state: dict[str, Any], branch_id: str, item_id: Any, quantity: float, cost: float | None = None) -> None:
    key = str(item_id)
    state["logisticsState"]["branchStocks"].setdefault(branch_id, {})[key] = max(0, quantity)
    state["logisticsState"]["branchCosts"].setdefault(branch_id, {})
    if cost is not None:
        state["logisticsState"]["branchCosts"][branch_id][key] = max(0, cost)


def _locked(state: dict[str, Any], branch_id: str) -> bool:
    return any(
        inventory.get("branchId") == branch_id and inventory.get("status") in {"counting", "submitted", "returned"}
        for inventory in state["logisticsState"]["inventories"]
    )


def _require_unlocked(state: dict[str, Any], branch_id: str) -> None:
    _require(not _locked(state, branch_id), "На точке идёт инвентаризация — движения временно заблокированы", 409)


def _ensure_finance(state: dict[str, Any]) -> dict[str, Any]:
    finance = state.setdefault("financeState", {})
    finance.setdefault("transactions", [])
    finance.setdefault("accounts", [
        {"id": "finance-bank", "name": "Расчётный счёт", "type": "bank", "branchId": None, "openingBalance": 0, "status": "active"},
        {"id": "finance-safe", "name": "Сейф", "type": "safe", "branchId": None, "openingBalance": 0, "status": "active"},
    ])
    finance.setdefault("categories", [
        {"id": "finance-income-other", "name": "Прочие доходы", "kind": "income", "status": "active"},
        {"id": "finance-expense-payroll", "name": "Заработная плата", "kind": "expense", "status": "active"},
        {"id": "finance-expense-rent", "name": "Аренда и коммунальные", "kind": "expense", "status": "active"},
        {"id": "finance-expense-supplies", "name": "Хозяйственные расходы", "kind": "expense", "status": "active"},
        {"id": "finance-expense-marketing", "name": "Маркетинг", "kind": "expense", "status": "active"},
        {"id": "finance-expense-tax", "name": "Налоги и комиссии", "kind": "expense", "status": "active"},
        {"id": "finance-expense-other", "name": "Прочие расходы", "kind": "expense", "status": "active"},
    ])
    for category in (
        {"id": "finance-expense-utilities", "name": "Коммунальные услуги", "kind": "expense", "status": "active"},
        {"id": "finance-expense-taxes", "name": "Налоги", "kind": "expense", "status": "active"},
        {"id": "finance-expense-fees", "name": "Банковские комиссии", "kind": "expense", "status": "active"},
    ):
        if not _find(finance["categories"], category["id"]):
            finance["categories"].append(category)
    accounts = finance["accounts"]
    for branch in state.get("branches", []):
        account_id = f"finance-cash-{branch['id']}"
        if not _find(accounts, account_id):
            accounts.append({
                "id": account_id, "name": f"Касса · {branch['short']}", "type": "cash",
                "branchId": str(branch["id"]), "openingBalance": 0, "status": "active",
            })
    return finance


def _ensure_pos(state: dict[str, Any]) -> dict[str, Any]:
    pos = state.setdefault("posState", {})
    pos.setdefault("customers", [])
    pos.setdefault("openOrders", [])
    pos.setdefault("cashMovements", [])
    return pos


def _ensure_supplies(state: dict[str, Any]) -> list[dict[str, Any]]:
    logistics = state["logisticsState"]
    supplies = logistics.setdefault("supplies", [])
    known_ids = {str(entry.get("id")) for entry in supplies}
    for legacy in logistics.get("directOrders", []):
        if legacy.get("status") != "received" or str(legacy.get("id")) in known_ids:
            continue
        total = _number(legacy.get("total"))
        supplies.append({
            **deepcopy(legacy),
            "documentType": "supply",
            "paymentStatus": legacy.get("paymentStatus", "paid"),
            "paidTotal": _number(legacy.get("paidTotal", total)),
            "debt": _number(legacy.get("debt")),
            "payments": deepcopy(legacy.get("payments", [])),
        })
        known_ids.add(str(legacy.get("id")))
    supplies.sort(key=lambda entry: str(entry.get("receivedAt") or entry.get("createdAt") or ""), reverse=True)
    return supplies


def _ledger(
    state: dict[str, Any], *, branch_id: str, item_id: Any, quantity: float, unit_cost: float,
    movement_type: str, document_number: str, actor: str, related_branch_id: str | None = None,
) -> None:
    state["logisticsState"].setdefault("stockLedger", []).insert(0, {
        "id": f"ledger-{uuid4()}",
        "branchId": branch_id,
        "itemId": str(item_id),
        "quantity": quantity,
        "unitCost": unit_cost,
        "movementType": movement_type,
        "documentNumber": document_number,
        "relatedBranchId": related_branch_id,
        "createdAt": _now(),
        "createdBy": actor,
    })


def default_state() -> dict[str, Any]:
    ingredients = [
        {"id": "rice", "name": "Рис лазер", "category": "Крупы", "unit": "кг", "stock": 0, "averageCost": 96, "limit": 25},
        {"id": "beef", "name": "Говядина", "category": "Мясо", "unit": "кг", "stock": 0, "averageCost": 520, "limit": 20},
        {"id": "carrot", "name": "Морковь", "category": "Овощи", "unit": "кг", "stock": 0, "averageCost": 55, "limit": 10},
        {"id": "onion", "name": "Лук репчатый", "category": "Овощи", "unit": "кг", "stock": 0, "averageCost": 45, "limit": 10},
        {"id": "oil", "name": "Масло растительное", "category": "Бакалея", "unit": "л", "stock": 0, "averageCost": 145, "limit": 10},
        {"id": "salt", "name": "Соль", "category": "Бакалея", "unit": "кг", "stock": 0, "averageCost": 30, "limit": 3},
        {"id": "spices", "name": "Специи для плова", "category": "Бакалея", "unit": "кг", "stock": 0, "averageCost": 760, "limit": 1},
        {"id": "potato", "name": "Картофель", "category": "Овощи", "unit": "кг", "stock": 0, "averageCost": 48, "limit": 20},
        {"id": "flour", "name": "Мука высший сорт", "category": "Бакалея", "unit": "кг", "stock": 0, "averageCost": 54, "limit": 25},
        {"id": "chicken", "name": "Курица", "category": "Мясо", "unit": "кг", "stock": 0, "averageCost": 260, "limit": 15},
        {"id": "tomato", "name": "Помидоры", "category": "Овощи", "unit": "кг", "stock": 0, "averageCost": 130, "limit": 8},
        {"id": "tea", "name": "Чай чёрный", "category": "Напитки", "unit": "кг", "stock": 0, "averageCost": 680, "limit": 1.5},
    ]
    products = [
        {"id": "p-1", "name": "Вода 0,5 л", "category": "Напитки", "barcode": "4860001123456", "averageCost": 28, "price": 40, "stock": 0, "unit": "шт", "limit": 20},
        {"id": "p-2", "name": "Coca-Cola 0,5 л", "category": "Напитки", "barcode": "5449000054227", "averageCost": 52, "price": 80, "stock": 0, "unit": "шт", "limit": 12},
        {"id": "p-3", "name": "Сок яблочный 0,2 л", "category": "Напитки", "barcode": "4860012345678", "averageCost": 36, "price": 60, "stock": 0, "unit": "шт", "limit": 10},
        {"id": "p-4", "name": "Шоколад молочный", "category": "Сладости", "barcode": "4607065000781", "averageCost": 45, "price": 70, "stock": 0, "unit": "шт", "limit": 8},
        {"id": "p-5", "name": "Салфетки влажные", "category": "Дополнительно", "barcode": "4860098765432", "averageCost": 12, "price": 20, "stock": 0, "unit": "шт", "limit": 25},
    ]
    recipes = [
        {"id": 201, "name": "Плов праздничный", "category": "Горячее", "price": 230, "color": "#e39a3d", "yield": 380, "components": [
            {"ingredientId": "rice", "gross": 150, "net": 150}, {"ingredientId": "beef", "gross": 115, "net": 100},
            {"ingredientId": "carrot", "gross": 82, "net": 70}, {"ingredientId": "onion", "gross": 35, "net": 30},
            {"ingredientId": "oil", "gross": 25, "net": 25, "measure": "мл"}, {"ingredientId": "salt", "gross": 3, "net": 3},
            {"ingredientId": "spices", "gross": 2, "net": 2},
        ]},
        {"id": 203, "name": "Лагман", "category": "Горячее", "price": 250, "color": "#bd6557", "yield": 450, "components": [
            {"ingredientId": "beef", "gross": 130, "net": 110}, {"ingredientId": "flour", "gross": 150, "net": 150},
            {"ingredientId": "onion", "gross": 45, "net": 40}, {"ingredientId": "tomato", "gross": 90, "net": 80},
            {"ingredientId": "oil", "gross": 18, "net": 18, "measure": "мл"}, {"ingredientId": "spices", "gross": 2, "net": 2},
        ]},
        {"id": 101, "name": "Шорпо с говядиной", "category": "Первые", "price": 210, "color": "#62a56f", "yield": 420, "components": [
            {"ingredientId": "beef", "gross": 120, "net": 100}, {"ingredientId": "potato", "gross": 150, "net": 125},
            {"ingredientId": "carrot", "gross": 35, "net": 30}, {"ingredientId": "onion", "gross": 30, "net": 26},
            {"ingredientId": "salt", "gross": 3, "net": 3}, {"ingredientId": "spices", "gross": 1, "net": 1},
        ]},
        {"id": 205, "name": "Курица запечённая", "category": "Горячее", "price": 180, "color": "#cc7c58", "yield": 210, "components": [
            {"ingredientId": "chicken", "gross": 260, "net": 200}, {"ingredientId": "oil", "gross": 7, "net": 7, "measure": "мл"},
            {"ingredientId": "salt", "gross": 3, "net": 3}, {"ingredientId": "spices", "gross": 2, "net": 2},
        ]},
        {"id": 401, "name": "Салат Ачичук", "category": "Салаты", "price": 85, "color": "#4e9b8d", "yield": 160, "components": [
            {"ingredientId": "tomato", "gross": 130, "net": 120}, {"ingredientId": "onion", "gross": 45, "net": 38},
            {"ingredientId": "salt", "gross": 2, "net": 2},
        ]},
    ]
    quantities = {entry["id"]: entry["averageCost"] for entry in [*ingredients, *products]}
    opening = {entry["id"]: value for entry, value in zip([*ingredients, *products], [68, 32, 25, 18, 12, 8, 2, 52, 76, 24, 15, 1.2, 86, 48, 34, 22, 120])}
    return {
        "schemaVersion": 1,
        "branches": [{
            "id": "b1", "number": 1, "short": "Манаса", "name": "Столовая №1 — Манаса",
            "address": "Бишкек, ул. Манаса", "phone": "", "managerName": "Управляющий точки",
            "login": "manasa", "status": "active", "route": "Поставщики → Манаса",
        }],
        "suppliers": [
            {"id": "supplier-frunze", "name": "Фрунзе Маркет", "inn": "", "contact": "Отдел поставок", "phone": "+996 555 120 120", "email": "", "address": "Бишкек", "comment": "", "status": "active", "locations": ["b1"], "prices": {}},
            {"id": "supplier-alamedin", "name": "Аламедин Агро", "inn": "", "contact": "Бакыт", "phone": "+996 700 240 240", "email": "", "address": "Бишкек, Аламединский рынок", "comment": "Овощи и бакалея", "status": "active", "locations": ["b1"], "prices": {}},
            {"id": "supplier-meat", "name": "Мясной двор", "inn": "", "contact": "Отдел продаж", "phone": "+996 777 310 310", "email": "", "address": "Бишкек", "comment": "Мясная продукция", "status": "active", "locations": ["b1"], "prices": {}},
        ],
        "ingredients": ingredients,
        "products": products,
        "recipes": recipes,
        "preparations": [],
        "menuCategories": [
            {"name": "Горячее", "color": "#e39a3d"},
            {"name": "Первые", "color": "#62a56f"},
            {"name": "Салаты", "color": "#4e9b8d"},
            {"name": "Выпечка", "color": "#5b8fbd"},
            {"name": "Напитки", "color": "#bd6557"},
            {"name": "Сладости", "color": "#7b69d4"},
            {"name": "Дополнительно", "color": "#5b8fbd"},
        ],
        "ingredientCategories": ["Крупы", "Мясо", "Овощи", "Бакалея", "Напитки"],
        "stations": [
            {"name": "Кухня", "branchId": "b1", "warehouse": "Склад · Столовая №1 — Манаса", "destination": "Экран кухни №1"},
            {"name": "Холодный цех", "branchId": "b1", "warehouse": "Склад · Столовая №1 — Манаса", "destination": "Принтер холодного цеха"},
            {"name": "Бар", "branchId": "b1", "warehouse": "Склад · Столовая №1 — Манаса", "destination": "Без печати"},
        ],
        "logisticsState": {
            "requests": [], "branchStocks": {"b1": opening}, "branchCosts": {"b1": quantities},
            "directOrders": [], "supplies": [], "pointTransfers": [], "inventories": [], "batches": [],
            "stockLedger": [], "supplyModel": "poster",
        },
        "sales": [],
        "posState": {"customers": [], "openOrders": [], "cashMovements": []},
        "financeState": {"transactions": []},
    }


def new_tenant_state() -> dict[str, Any]:
    """Create an empty Poster-style account without demo catalog or balances."""
    return {
        "schemaVersion": 2,
        "branches": [],
        "suppliers": [],
        "ingredients": [],
        "products": [],
        "recipes": [],
        "preparations": [],
        "menuCategories": [],
        "ingredientCategories": ["Крупы", "Мясо", "Овощи", "Бакалея", "Напитки"],
        "stations": [],
        "logisticsState": {
            "requests": [],
            "branchStocks": {},
            "branchCosts": {},
            "directOrders": [],
            "supplies": [],
            "pointTransfers": [],
            "inventories": [],
            "batches": [],
            "stockLedger": [],
            "supplyModel": "poster",
        },
        "sales": [],
        "posState": {"customers": [], "openOrders": [], "cashMovements": []},
        "financeState": {"transactions": []},
    }


def _appearance(payload, existing=None):
    existing = existing or {}
    image = str(payload.get("image", existing.get("image", "")))
    color = str(payload.get("color", existing.get("color", "#633d60")))
    _require(not image or (len(image) <= 3000000 and re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+", image)), "Некорректное фото: выберите PNG, JPG или WebP до 2 МБ")
    _require(re.fullmatch(r"#[0-9a-fA-F]{6}", color) is not None, "Некорректный цвет")
    return {"image": image, "color": color.lower()}


def _station_route(state: dict[str, Any], item: dict[str, Any], branch_id: str) -> dict[str, str]:
    name = str(item.get("station") or "")
    station = next((row for row in state.get("stations", []) if row.get("name") == name and str(row.get("branchId")) == str(branch_id)), None)
    return {"station": name, "destination": str(station.get("destination") or "Без печати") if station else "Без печати"}


def _ensure_stations(state: dict[str, Any]) -> None:
    if isinstance(state.get("stations"), list):
        return
    first_branch = state.get("branches", [None])[0] if state.get("branches") else None
    if not first_branch:
        state["stations"] = []
        return
    warehouse = f"Склад · {first_branch['name']}"
    state["stations"] = [
        {"name": "Кухня", "branchId": str(first_branch["id"]), "warehouse": warehouse, "destination": "Экран кухни №1"},
        {"name": "Холодный цех", "branchId": str(first_branch["id"]), "warehouse": warehouse, "destination": "Принтер холодного цеха"},
        {"name": "Бар", "branchId": str(first_branch["id"]), "warehouse": warehouse, "destination": "Без печати"},
    ]


def recipe_requirements(recipe, quantity=1):
    requirements = {}
    for component in recipe.get("components", []):
        item_id = str(component["ingredientId"])
        amount = _number(component.get("gross", component.get("net"))) / 1000 * quantity
        requirements[item_id] = requirements.get(item_id, 0) + amount
    return requirements


def restaurant_availability(state, recipe, branch_id):
    requirements = recipe_requirements(recipe)
    capacity = min((_stock(state, branch_id, key) / amount for key, amount in requirements.items() if amount > 0), default=0)
    scale = 100 if company_settings(state)["general"]["fractional"] else 1
    return max(0, floor(capacity * scale + 1e-9) / scale)


def production_context(state, branch_id):
    recipes = []
    for recipe in state.get("recipes", []):
        requirements = recipe_requirements(recipe)
        portions = min((_stock(state, branch_id, key) / amount for key, amount in requirements.items() if amount > 0), default=0)
        recipes.append({"id": recipe["id"], "name": recipe["name"], "yield": recipe.get("yield", 0),
                        "maxWeight": max(0, floor(portions * _number(recipe.get("yield")) + 1e-8) / 1000)})
    batches = []
    for batch in state.get("logisticsState", {}).get("batches", []):
        available = custody.kitchen_balance(batch)
        if batch.get("branchId") != branch_id or batch.get("status") == "closed" or available <= 0:
            continue
        recipe = _recipe(state, batch.get("recipeId"))
        batches.append({"id": batch["id"], "number": batch["number"], "name": recipe["name"] if recipe else "Блюдо удалено",
                        "recipeId": batch.get("recipeId"), "yield": custody.portion_weight(batch, recipe) if recipe else 0,
                        "availableWeight": available, "createdAt": batch.get("createdAt")})
    return {"recipes": recipes, "batches": batches}


def visible_state(state: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    output = deepcopy(state)
    freeze_batch_portions(output)
    output["serviceMode"] = "restaurant" if user.get("plan_code") == "restaurant" else "canteen"
    if output["serviceMode"] == "restaurant" and user.get("branch_id"):
        for recipe in output.get("recipes", []):
            recipe["availableToOrder"] = restaurant_availability(state, recipe, str(user["branch_id"]))
    for batch in output.get("logisticsState", {}).get("batches", []):
        recipe = _recipe(output, batch.get("recipeId")) or {}
        batch["availableWeight"] = custody.serving_balance(batch, recipe)
        batch["kitchenAvailableWeight"] = custody.kitchen_balance(batch)
    if user.get("branch_id") and output["serviceMode"] != "restaurant":
        fractional = company_settings(state)["general"]["fractional"]
        for recipe in output.get("recipes", []):
            lots = []
            for batch in output["logisticsState"]["batches"]:
                if batch.get("branchId") != user["branch_id"] or str(batch.get("recipeId")) != str(recipe["id"]) or batch.get("status") not in {"serving", "partial"}:
                    continue
                custody.initialize(batch, recipe)
                for lot in batch["servingLots"]:
                    weight = custody.lot_available(lot)
                    scale = 100 if fractional else 1
                    portions = floor(weight * 1000 / max(custody.portion_weight(batch, recipe), 0.001) * scale + 1e-8) / scale
                    if portions > 0:
                        lots.append({"id": lot["id"], "line": lot["line"], "batchNumber": batch.get("number", batch["id"]), "responsibleName": lot.get("responsibleName"), "available": portions})
            recipe["availableLots"] = lots
    output["companySettings"] = company_settings(state)
    _ensure_stations(output)
    _ensure_finance(output)
    _ensure_supplies(output)
    pos = _ensure_pos(output)
    for records in (output["logisticsState"].get("batches", []), output["logisticsState"].get("supplies", []), pos["cashMovements"]):
        for record in records:
            for key in ("requestId", "requestPayload", "requestActorId", "requestRegisterId"):
                record.pop(key, None)
    output.pop("offlinePos", None)
    if user["role"] == "owner":
        return output
    output.pop("payrollState", None)
    output.pop("pnlState", None)
    for sale in output.get("sales", []):
        sale.pop("payrollAccruals", None)
    branch_id = str(user["branch_id"])
    output["branches"] = [
        branch if branch.get("id") == branch_id else {key: branch.get(key) for key in ("id", "number", "short", "name", "address", "status")}
        for branch in output["branches"]
    ]
    output["suppliers"] = [
        {**supplier, "prices": {branch_id: supplier.get("prices", {}).get(branch_id, {})}}
        for supplier in output["suppliers"]
    ]
    output["externalSalesImports"] = []
    logistics = output["logisticsState"]
    logistics["custodyDocuments"] = [doc for doc in logistics.get("custodyDocuments", []) if doc.get("branchId") == branch_id]
    logistics["directOrders"] = [order for order in logistics["directOrders"] if order.get("branchId") == branch_id]
    logistics["supplies"] = [supply for supply in logistics["supplies"] if supply.get("branchId") == branch_id]
    logistics["pointTransfers"] = [transfer for transfer in logistics["pointTransfers"] if branch_id in {transfer.get("sourceBranchId"), transfer.get("destinationBranchId")}]
    logistics["inventories"] = [inventory for inventory in logistics["inventories"] if inventory.get("branchId") == branch_id]
    logistics["batches"] = [batch for batch in logistics["batches"] if batch.get("branchId") == branch_id]
    logistics["productionShifts"] = [shift for shift in logistics.get("productionShifts", []) if shift.get("branchId") == branch_id]
    logistics["cashShiftCounts"] = [count for count in logistics.get("cashShiftCounts", []) if count.get("branchId") == branch_id]
    logistics["servingRequests"] = [entry for entry in logistics.get("servingRequests", []) if entry.get("branchId") == branch_id]
    logistics["branchStocks"] = {branch_id: logistics["branchStocks"].get(branch_id, {})}
    logistics["branchCosts"] = {branch_id: logistics["branchCosts"].get(branch_id, {})}
    logistics["stockLedger"] = [entry for entry in logistics.get("stockLedger", []) if entry.get("branchId") == branch_id]
    output["sales"] = [sale for sale in output["sales"] if sale.get("branchId") == branch_id]
    pos["openOrders"] = [order for order in pos["openOrders"] if order.get("branchId") == branch_id]
    pos["cashMovements"] = [movement for movement in pos["cashMovements"] if movement.get("branchId") == branch_id]
    finance = output.get("financeState", {})
    output["financeState"] = {
        "accounts": [
            {key: account.get(key) for key in ("id", "name", "type", "branchId", "status")}
            for account in finance.get("accounts", [])
            if not account.get("branchId") or str(account.get("branchId")) == branch_id
        ],
        "transactions": [],
        "categories": [],
    }
    staff_role = user.get("staff_role") or "branch_manager"
    permissions = user.get("access_permissions")
    if isinstance(permissions, dict) and permissions and staff_role != "pos_terminal" and not user.get("register_id"):
        can_inventory = bool(permissions.get("inventory"))
        can_production = bool(permissions.get("production"))
        can_menu = bool(permissions.get("menu"))
        if permissions.get("finance"):
            output["financeState"] = {
                "accounts": [
                    {key: account.get(key) for key in ("id", "name", "type", "branchId", "openingBalance", "status")}
                    for account in finance.get("accounts", [])
                    if not account.get("branchId") or str(account.get("branchId")) == branch_id
                ],
                "transactions": [transaction for transaction in finance.get("transactions", []) if not transaction.get("branchId") or str(transaction.get("branchId")) == branch_id],
                "categories": finance.get("categories", []),
            }
        else:
            output.pop("financeState", None)
        if not permissions.get("reports"):
            output["sales"] = []
        if not can_inventory:
            output["suppliers"] = []
            logistics["directOrders"] = []
            logistics["supplies"] = []
            logistics["pointTransfers"] = []
            logistics["inventories"] = []
            logistics["stockLedger"] = []
        if not can_production:
            logistics["batches"] = []
        if not can_menu and not can_production:
            output["recipes"] = []
            output["preparations"] = []
            output["stations"] = []
        if not (can_menu or can_inventory or can_production):
            output["ingredients"] = []
            output["products"] = []
            output["ingredientCategories"] = []
            output["menuCategories"] = []
        if not (can_menu or can_inventory or can_production or permissions.get("finance")):
            logistics["branchCosts"] = {branch_id: {}}
            logistics["custodyDocuments"] = []
            for sale in output["sales"]:
                for item in sale.get("items", []):
                    item.pop("unitCost", None)
                    for allocation in item.get("ingredientAllocations", []):
                        allocation.pop("unitCost", None)
                    for allocation in item.get("batchAllocations", []):
                        for ingredient in allocation.get("productionIngredients", []):
                            ingredient.pop("unitCost", None)
        return output
    if staff_role in {"cashier", "waiter", "hall_admin", "pos_terminal"}:
        output.pop("financeState", None)
        output["suppliers"] = []
        output["ingredients"] = []
        output["preparations"] = []
        output["stations"] = []
        output["ingredientCategories"] = []
        output["recipes"] = [
            {key: recipe.get(key) for key in ("id", "name", "category", "price", "yield", "color", "image", "station", "availableToOrder", "availableLots")}
            for recipe in output["recipes"]
        ]
        output["products"] = [
            {key: product.get(key) for key in ("id", "name", "category", "barcode", "price", "unit", "weighted", "noDiscount", "image", "color", "station", "groupName", "variantName", "parentId")}
            for product in output["products"]
        ]
        logistics.pop("custodyDocuments", None)
        logistics["branchCosts"] = {branch_id: {}}
        logistics["directOrders"] = []
        logistics["supplies"] = []
        logistics["pointTransfers"] = []
        logistics["inventories"] = []
        logistics["stockLedger"] = []
        logistics["batches"] = [
            {key: batch.get(key) for key in ("id", "number", "branchId", "recipeId", "transferredWeight", "soldPortions", "status", "createdAt", "availableWeight")}
            for batch in logistics["batches"]
        ]
        output["sales"] = [
            {
                    **{key: sale.get(key) for key in ("id", "number", "branchId", "branch", "cashier", "registerId", "shiftId", "createdAt", "paymentMethod", "payments", "subtotal", "discountPercent", "discountAmount", "serviceAmount", "deliveryAmount", "rounding", "currency", "orderType", "table", "deliveryAddress", "deliveryPhone", "deliveryArea", "total", "received", "change", "customerId", "customerName", "comment", "refundedAt", "refundedBy", "refundReason", "refundShiftId", "refundRegisterId")},
                "items": [
                    {key: item.get(key) for key in ("id", "name", "category", "unit", "price", "quantity", "station", "destination")}
                    for item in sale.get("items", [])
                ],
            }
            for sale in output["sales"]
        ]
    elif staff_role == "production":
        output.pop("financeState", None)
        output["suppliers"] = []
        output["products"] = []
        output["sales"] = []
        logistics["directOrders"] = []
        logistics["supplies"] = []
        logistics["pointTransfers"] = []
        logistics["inventories"] = []
        logistics["stockLedger"] = []
    elif staff_role == "storekeeper":
        output["recipes"] = []
        output["preparations"] = []
        output["stations"] = []
        output["sales"] = []
    elif staff_role == "marketer":
        output.pop("financeState", None)
        output["suppliers"] = []
        output["ingredients"] = []
        output["preparations"] = []
        output["stations"] = []
        logistics["directOrders"] = []
        logistics["supplies"] = []
        logistics["pointTransfers"] = []
        logistics["inventories"] = []
        logistics["stockLedger"] = []
        logistics["batches"] = []
        logistics["batches"] = []
    return output


def _order_details(state, payload):
    settings = company_settings(state)
    orders = settings["orders"]
    order_type = payload.get("orderType", orders["defaultType"])
    enabled = {"dine-in": orders["dineIn"], "takeaway": orders["takeaway"], "delivery": settings["delivery"]["enabled"]}
    _require(enabled.get(order_type, False), "Этот тип заказа отключён в настройках")
    _require(not orders["requireCustomer"] or bool(payload.get("customerId")), "Выберите гостя для заказа")
    _require(not orders["requireComment"] or bool(str(payload.get("comment", "")).strip()), "Добавьте комментарий к заказу")
    details = {"orderType": order_type, "table": "", "deliveryAddress": "", "deliveryPhone": "", "deliveryArea": ""}
    if order_type == "dine-in" and settings["general"]["floorPlan"]:
        _require(payload.get("table") in orders["tables"], "Выберите стол")
        details["table"] = payload["table"]
    if order_type == "delivery":
        _require(any(area["name"] == payload.get("deliveryArea") for area in settings["delivery"]["areas"]), "Выберите район доставки")
        for key in ("deliveryAddress", "deliveryPhone", "deliveryArea"):
            value = str(payload.get(key, "")).strip()
            _require(bool(value) and len(value) <= 250, "Заполните адрес, телефон и район доставки")
            details[key] = value
    return details


def sale_replay(state, user, payload):
    request_id = str(payload.get("requestId") or "").strip()
    if not request_id:
        return None
    _require(len(request_id) <= 80, "Некорректный идентификатор оплаты", 422)
    previous = next((sale for sale in state.get("sales", []) if sale.get("requestId") == request_id), None)
    if previous:
        _require(str(previous.get("cashierId")) == str(user.get("id")) and previous.get("branchId") == user.get("branch_id") and previous.get("registerId") == user.get("register_id"), "Оплата принадлежит другой кассе или сотруднику", 403)
        _require(previous.get("requestPayload") == payload, "Идентификатор оплаты уже использован с другими данными", 409)
    return previous


def operation_replay(state, user, action, payload):
    """Find a committed stock/cash operation before checking mutable balances."""
    if "requestId" not in payload:
        return None
    request_id = payload.get("requestId")
    _require(isinstance(request_id, str) and 0 < len(request_id.strip()) <= 80,
             "Не указан корректный идентификатор операции", 422)
    request_id = request_id.strip()
    collections = {
        "batch.create": (state.get("logisticsState", {}).get("batches", []), "production_batch"),
        "supply.create": (state.get("logisticsState", {}).get("supplies", []), "supplier_receipt"),
        "pos.cash.movement": (state.get("posState", {}).get("cashMovements", []), "pos_cash_movement"),
    }
    if action not in collections:
        return None
    entries, entity_type = collections[action]
    previous = next((entry for entry in entries if entry.get("requestId") == request_id), None)
    if previous is None:
        return None
    branch_id = str(payload.get("branchId") or "") if action == "supply.create" and user.get("role") == "owner" else _branch_user(user)
    _require(previous.get("branchId") == branch_id
             and str(previous.get("requestActorId")) == str(user.get("id"))
             and previous.get("requestRegisterId") == user.get("register_id"),
             "Операция принадлежит другой кассе, сотруднику или заведению", 403)
    _require(previous.get("requestPayload") == payload,
             "Идентификатор операции уже использован с другими данными", 409)
    return entity_type, previous["id"]


def _record_operation_request(entry, user, payload):
    if "requestId" in payload:
        entry.update(requestId=payload["requestId"].strip(), requestPayload=deepcopy(payload),
                     requestActorId=user.get("id"), requestRegisterId=user.get("register_id"))


def freeze_batch_portions(state):
    for batch in state.get("logisticsState", {}).get("batches", []):
        if batch.get("portionWeight"):
            continue
        historical = next((allocation for sale in state.get("sales", []) for item in sale.get("items", []) for allocation in item.get("batchAllocations", []) if allocation.get("batchId") == batch.get("id") and allocation.get("quantity", 0) > 0 and allocation.get("weight", 0) > 0), None)
        recipe = _recipe(state, batch.get("recipeId")) or {}
        batch["portionWeight"] = historical["weight"] * 1000 / historical["quantity"] if historical else recipe.get("yield", 0)
        batch["portionWeightSource"] = "sale" if historical else "legacy_recipe"


def apply_action(state: dict[str, Any], user: dict[str, Any], action: str, payload: dict[str, Any]) -> tuple[str, str | None]:
    if action.startswith("pnl."):
        from .pnl import apply as apply_pnl
        return apply_pnl(state, user, action, payload)
    if action.startswith("payroll.") or action.startswith("work.shift."):
        from .payroll import apply as apply_payroll
        return apply_payroll(state, user, action, payload)
    if action in {"batch.create", "supply.create", "pos.cash.movement"}:
        previous = operation_replay(state, user, action, payload)
        if previous:
            return previous
    freeze_batch_portions(state)
    if action == "sale.create":
        previous = sale_replay(state, user, payload)
        if previous:
            return "sale", previous["id"]
    _ensure_stations(state)
    finance = _ensure_finance(state)
    pos = _ensure_pos(state)
    actor = user["display_name"]
    logistics = state["logisticsState"]
    supplies = _ensure_supplies(state)

    settings = company_settings(state)
    if action == "settings.update":
        _owner(user)
        try:
            values = validate_settings_section(payload.get("section"), payload.get("values", {}))
        except ValueError as error:
            raise WorkspaceError(str(error)) from error
        if payload["section"] == "general" and (state.get("payrollState") or state.get("pnlState") or state.get("offlinePos")):
            _require(all(values.get(k) == settings["general"].get(k) for k in ("currency", "timezone")), "После начала учёта зарплаты, расходов или автономной кассы валюту и часовой пояс меняют только с переносом учёта", 409)
        state.setdefault("companySettings", {})[payload["section"]] = values
        return "settings", payload["section"]

    security_keys = {"sale.refund": "refund", "pos.customer.upsert": "addCustomer", "supply.create": "addSupply", "pos.order.remove": "deleteOrder", "sale.create": "closeReceipt"}
    try:
        if action in security_keys and user.get("register_id"):
            require_manager(state, user, security_keys[action])
        if action in {"sale.create", "pos.order.save"} and payload.get("customerId"):
            customer_for_policy = _find(pos["customers"], payload.get("customerId"))
            if customer_for_policy and customer_for_policy.get("discountPercent"):
                require_manager(state, user, "discount")
    except PermissionError as error:
        raise WorkspaceError(str(error), 403) from error

    if action == "ingredient.import":
        _owner(user)
        items = payload.get("items")
        _require(isinstance(items, list) and 0 < len(items) <= 500, "Импортируйте от 1 до 500 ингредиентов")
        imported_state = deepcopy(state)
        names = {str(item["name"]).strip().casefold() for item in state["ingredients"]}
        for index, item in enumerate(items):
            _require(isinstance(item, dict), f"Строка {index + 1}: неверные данные")
            name = str(item.get("name", "")).strip()
            _require(name and len(name) <= 200 and name.casefold() not in names, f"Строка {index + 1}: название пустое или уже существует")
            _require(item.get("unit") in {"кг", "л", "шт"}, f"Строка {index + 1}: неверная единица измерения")
            limit = item.get("limit", 0)
            _require(isinstance(limit, (int, float)) and isfinite(limit) and limit >= 0, f"Строка {index + 1}: неверный лимит")
            names.add(name.casefold())
            apply_action(imported_state, user, "ingredient.upsert", {
                "id": f"i-{uuid4().hex[:12]}", "name": name, "unit": item["unit"],
                "category": str(item.get("category") or "Без категории"),
                "barcode": str(item.get("barcode") or "")[:64], "limit": limit,
                "averageCost": 0,
            })
        state.clear()
        state.update(imported_state)
        return "ingredient-import", str(len(items))

    if action == "branch.upsert":
        _owner(user)
        branch = _find(state["branches"], payload.get("id"))
        creating = branch is None
        if creating:
            next_number = max([int(entry.get("number", 0)) for entry in state["branches"]] or [0]) + 1
            branch = {"id": f"b{next_number}", "number": next_number}
            state["branches"].append(branch)
            logistics["branchStocks"][branch["id"]] = {str(entry["id"]): 0 for entry in [*state["ingredients"], *state["products"]]}
            logistics["branchCosts"][branch["id"]] = {str(entry["id"]): 0 for entry in [*state["ingredients"], *state["products"]]}
            branch.update({"createdAt": _now(), "createdBy": actor})
        short = str(payload.get("short", "")).strip()
        login = str(payload.get("login", "")).strip().lower()
        open_time = str(payload.get("openTime") or branch.get("workHours", {}).get("open") or "08:00").strip()
        close_time = str(payload.get("closeTime") or branch.get("workHours", {}).get("close") or "20:00").strip()
        _require(short and payload.get("address") and login, "Заполните название, адрес и данные кассы")
        _require(len(open_time) == 5 and len(close_time) == 5, "Проверьте режим работы точки")
        _require(not any(entry["id"] != branch["id"] and entry["short"].lower() == short.lower() for entry in state["branches"]), "Точка с таким названием уже существует", 409)
        branch.update({
            "short": short, "name": short, "address": str(payload["address"]).strip(),
            "phone": str(payload.get("phone", "")).strip(),
            "workHours": {"open": open_time, "close": close_time},
            "managerName": str(payload.get("managerName") or branch.get("managerName") or "Не назначен").strip(),
            "login": login, "status": payload.get("status") if payload.get("status") in {"active", "inactive"} else "active", "route": f"Поставщики → {short}",
            "updatedAt": _now(), "updatedBy": actor,
        })
        if "supplierIds" in payload:
            supplier_ids = {str(value) for value in payload.get("supplierIds", [])}
            for supplier in state["suppliers"]:
                locations = set(supplier.get("locations", []))
                locations.discard(branch["id"])
                if str(supplier["id"]) in supplier_ids:
                    locations.add(branch["id"])
                supplier["locations"] = sorted(locations)
        payload["resolvedBranchId"] = branch["id"]
        _ensure_finance(state)
        return "branch", branch["id"]

    if action == "finance.transaction.create":
        _owner(user)
        transaction_type = str(payload.get("type", ""))
        _require(transaction_type in {"income", "expense", "transfer"}, "Выберите тип операции")
        amount = _number(payload.get("amount"))
        _require(amount > 0, "Сумма должна быть больше нуля")
        occurred_at = str(payload.get("occurredAt", "")).strip()
        _require(occurred_at, "Укажите дату операции")
        from .pnl import local_day
        local_day(state, occurred_at)
        recognition_date = str(payload.get("recognitionDate") or "").strip()
        if recognition_date:
            from .payroll import day
            day(recognition_date)
        _require(isinstance(payload.get("affectsProfit", True), bool), "Проверьте участие операции в прибыли")
        account = _find(finance["accounts"], payload.get("accountId"))
        _require(account and account.get("status") == "active", "Выберите активный счёт")
        requested_branch_id = str(payload.get("branchId") or "") or None
        if account.get("branchId"):
            _require(not requested_branch_id or requested_branch_id == str(account["branchId"]), "Счёт относится к другой точке")
        branch_id = str(account.get("branchId") or requested_branch_id or "") or None
        if branch_id:
            _require(_find(state["branches"], branch_id) is not None, "Точка не найдена", 404)
        category = None
        destination = None
        if transaction_type == "transfer":
            destination = _find(finance["accounts"], payload.get("destinationAccountId"))
            _require(destination and destination.get("status") == "active", "Выберите счёт назначения")
            _require(destination["id"] != account["id"], "Для перевода нужны разные счета")
        else:
            category = _find(finance["categories"], payload.get("categoryId"))
            _require(category and category.get("status") == "active" and category.get("kind") == transaction_type, "Выберите подходящую категорию")
        transaction = {
            "id": f"finance-transaction-{uuid4()}",
            "number": _next_number("ФО", finance["transactions"]),
            "type": transaction_type,
            "amount": amount,
            "occurredAt": occurred_at,
            "recognitionDate": recognition_date or None,
            "affectsProfit": payload.get("affectsProfit", True),
            "accountId": str(account["id"]),
            "destinationAccountId": str(destination["id"]) if destination else None,
            "categoryId": str(category["id"]) if category else None,
            "branchId": branch_id,
            "counterparty": str(payload.get("counterparty", "")).strip(),
            "comment": str(payload.get("comment", "")).strip(),
            "createdAt": _now(),
            "createdBy": actor,
        }
        finance["transactions"].insert(0, transaction)
        return "finance_transaction", transaction["id"]

    if action == "finance.transaction.delete":
        _owner(user)
        transaction = _find(finance["transactions"], payload.get("id"))
        _require(transaction is not None, "Операция не найдена", 404)
        _require(not transaction.get("automatic") and not transaction.get("documentId"), "Операция связана с документом и не может быть удалена отдельно", 409)
        finance["transactions"].remove(transaction)
        return "finance_transaction", str(transaction["id"])

    if action == "finance.account.upsert":
        _owner(user)
        account = _find(finance["accounts"], payload.get("id"))
        name = str(payload.get("name", "")).strip()
        account_type = str(payload.get("type", ""))
        branch_id = str(payload.get("branchId") or "") or None
        _require(name, "Укажите название счёта")
        _require(account_type in {"cash", "bank", "card", "safe", "other"}, "Выберите тип счёта")
        _require(not branch_id or _find(state["branches"], branch_id), "Точка не найдена", 404)
        _require(not any(entry is not account and str(entry.get("name", "")).lower() == name.lower() for entry in finance["accounts"]), "Счёт с таким названием уже существует", 409)
        if account is None:
            account = {"id": f"finance-account-{uuid4()}"}
            finance["accounts"].append(account)
        account.update({
            "name": name, "type": account_type, "branchId": branch_id,
            "openingBalance": _number(payload.get("openingBalance")),
            "status": payload.get("status") if payload.get("status") in {"active", "inactive"} else "active",
        })
        return "finance_account", str(account["id"])

    if action == "finance.category.upsert":
        _owner(user)
        category = _find(finance["categories"], payload.get("id"))
        name = str(payload.get("name", "")).strip()
        kind = str(payload.get("kind", ""))
        _require(name, "Укажите название категории")
        _require(kind in {"income", "expense"}, "Выберите тип категории")
        _require(not any(entry is not category and entry.get("kind") == kind and str(entry.get("name", "")).lower() == name.lower() for entry in finance["categories"]), "Такая категория уже существует", 409)
        if category is None:
            category = {"id": f"finance-category-{uuid4()}"}
            finance["categories"].append(category)
        category.update({"name": name, "kind": kind, "status": payload.get("status") if payload.get("status") in {"active", "inactive"} else "active"})
        return "finance_category", str(category["id"])

    if action == "supplier.upsert":
        name = str(payload.get("name", "")).strip()
        if user["role"] == "owner":
            locations = [str(branch["id"]) for branch in state["branches"] if branch.get("status") == "active"]
        else:
            locations = [_branch_user(user)]
        _require(name, "Укажите название поставщика")
        supplier = _find(state["suppliers"], payload.get("id"))
        _require(not any(entry is not supplier and entry["name"].lower() == name.lower() for entry in state["suppliers"]), "Поставщик с таким названием уже существует", 409)
        if supplier is None:
            supplier = {"id": f"supplier-{uuid4()}", "prices": {}}
            state["suppliers"].insert(0, supplier)
        supplier.update({key: str(payload.get(key, "")).strip() for key in ("inn", "contact", "phone", "email", "address", "comment")})
        if supplier and user["role"] == "branch":
            locations = sorted(set([*supplier.get("locations", []), *locations]))
        supplier.update({"name": name, "locations": locations, "status": payload.get("status") if payload.get("status") in {"active", "inactive"} else "active"})
        return "supplier", str(supplier["id"])

    if action == "category.upsert":
        _owner(user)
        kind = str(payload.get("kind", ""))
        name = str(payload.get("name", "")).strip()
        original_name = str(payload.get("originalName") or "").strip()
        _require(kind in {"menu", "ingredient"}, "Неизвестный тип категории")
        _require(name and len(name) <= 80, "Название категории должно содержать от 1 до 80 символов")
        if kind == "menu":
            palette = ["#e39a3d", "#62a56f", "#4e9b8d", "#5b8fbd", "#bd6557", "#7b69d4"]
            registry = state.get("menuCategories")
            if not isinstance(registry, list):
                registry = []
            normalized_registry: list[dict[str, str]] = []
            for index, raw in enumerate(registry):
                category_name = str(raw if isinstance(raw, str) else raw.get("name", "")).strip()
                category_color = str(raw.get("color", "") if isinstance(raw, dict) else "")
                if category_name and not any(entry["name"].lower() == category_name.lower() for entry in normalized_registry):
                    normalized_registry.append({"image": raw.get("image", "") if isinstance(raw, dict) else "", "name": category_name, "color": category_color if len(category_color) == 7 and category_color.startswith("#") else palette[index % len(palette)]})
            for item in [*state["recipes"], *state["products"]]:
                category_name = str(item.get("category") or "Без категории").strip() or "Без категории"
                if not any(entry["name"].lower() == category_name.lower() for entry in normalized_registry):
                    normalized_registry.append({"name": category_name, "color": palette[len(normalized_registry) % len(palette)]})
            state["menuCategories"] = normalized_registry
            entry = next((category for category in normalized_registry if category["name"].lower() == original_name.lower()), None) if original_name else None
            _require(not original_name or entry is not None, "Категория не найдена", 404)
            _require(not any(category is not entry and category["name"].lower() == name.lower() for category in normalized_registry), "Категория с таким названием уже существует", 409)
            color = str(payload.get("color", "")).lower()
            if not (len(color) == 7 and color.startswith("#") and all(character in "0123456789abcdef" for character in color[1:])):
                color = entry["color"] if entry else palette[len(normalized_registry) % len(palette)]
            if entry is None:
                normalized_registry.append({"name": name, **_appearance({**payload, "color": color})})
            else:
                previous_name = entry["name"]
                entry.update({"name": name, **_appearance({**payload, "color": color}, entry)})
                for recipe in state["recipes"]:
                    if recipe.get("category") == previous_name:
                        recipe.update({"category": name})
                for product in state["products"]:
                    if product.get("category") == previous_name:
                        product["category"] = name
        else:
            registry = state.get("ingredientCategories")
            normalized_registry = []
            if isinstance(registry, list):
                for raw in registry:
                    category_name = str(raw if isinstance(raw, str) else raw.get("name", "")).strip()
                    if category_name and not any(entry.lower() == category_name.lower() for entry in normalized_registry):
                        normalized_registry.append(category_name)
            for ingredient in state["ingredients"]:
                category_name = str(ingredient.get("category") or "Без категории").strip() or "Без категории"
                if not any(entry.lower() == category_name.lower() for entry in normalized_registry):
                    normalized_registry.append(category_name)
            state["ingredientCategories"] = normalized_registry
            entry_index = next((index for index, category in enumerate(normalized_registry) if category.lower() == original_name.lower()), None) if original_name else None
            _require(not original_name or entry_index is not None, "Категория не найдена", 404)
            _require(not any(index != entry_index and category.lower() == name.lower() for index, category in enumerate(normalized_registry)), "Категория с таким названием уже существует", 409)
            if entry_index is None:
                normalized_registry.append(name)
            else:
                previous_name = normalized_registry[entry_index]
                normalized_registry[entry_index] = name
                for ingredient in state["ingredients"]:
                    if ingredient.get("category") == previous_name:
                        ingredient["category"] = name
        if kind == "ingredient":
            covers = state.setdefault("ingredientCategoryCovers", {})
            previous = covers.get(original_name, {})
            appearance = _appearance(payload, previous)
            if original_name and original_name != name:
                covers.pop(original_name, None)
            covers[name] = appearance
        return "category", f"{kind}:{name}"

    if action == "station.upsert":
        _owner(user)
        stations = state.setdefault("stations", [])
        name = str(payload.get("name", "")).strip()
        original_name = str(payload.get("originalName") or "").strip()
        branch = _find(state["branches"], payload.get("branchId"))
        destination = str(payload.get("destination", "")).strip()
        _require(name and len(name) <= 80, "Название цеха должно содержать от 1 до 80 символов")
        _require(branch is not None, "Выберите точку и склад списания")
        _require(destination and len(destination) <= 120, "Укажите маршрут заказа")
        station = next((entry for entry in stations if str(entry.get("name", "")).lower() == original_name.lower()), None) if original_name else None
        _require(not original_name or station is not None, "Цех не найден", 404)
        _require(
            not any(entry is not station and str(entry.get("name", "")).lower() == name.lower() for entry in stations),
            "Цех с таким названием уже существует",
            409,
        )
        if station is None:
            station = {}
            stations.append(station)
        previous_name = str(station.get("name", ""))
        if previous_name and previous_name != name:
            for recipe in state["recipes"]:
                legacy_station = "Холодный цех" if recipe.get("category") == "Салаты" else "Бар" if recipe.get("category") == "Напитки" else "Кухня"
                if recipe.get("station") == previous_name or (not recipe.get("station") and legacy_station == previous_name):
                    recipe["station"] = name
            for product in state["products"]:
                if product.get("station") == previous_name:
                    product["station"] = name
            for preparation in state.get("preparations", []):
                if preparation.get("station") == previous_name:
                    preparation["station"] = name
        station.update({
            "name": name,
            "branchId": str(branch["id"]),
            "warehouse": f"Склад · {branch['name']}",
            "destination": destination,
            "updatedAt": _now(),
            "updatedBy": actor,
        })
        return "station", name

    if action == "preparation.upsert":
        _owner(user)
        preparations = state.setdefault("preparations", [])
        name = str(payload.get("name", "")).strip()
        category = str(payload.get("category", "Без категории")).strip() or "Без категории"
        station = str(payload.get("station", "Кухня")).strip()
        output_yield = _number(payload.get("yield"))
        _require(name and station and output_yield > 0, "Укажите название, цех и выход полуфабриката")
        preparation = _find(preparations, payload.get("id"))
        _require(
            not any(entry is not preparation and str(entry.get("name", "")).lower() == name.lower() for entry in preparations),
            "Полуфабрикат с таким названием уже существует",
            409,
        )
        components: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        calculated_cost = 0.0
        for raw in payload.get("components", []):
            ingredient_id = str(raw.get("ingredientId", ""))
            ingredient = _find(state["ingredients"], ingredient_id)
            gross = _number(raw.get("gross"))
            net = _number(raw.get("net"))
            _require(ingredient is not None and gross > 0 and net > 0 and net <= gross and ingredient_id not in seen, "Проверьте состав полуфабриката")
            seen.add(ingredient_id)
            components.append({"ingredientId": ingredient_id, "gross": gross, "net": net})
            branch_costs = [
                _number(costs.get(ingredient_id))
                for costs in state["logisticsState"].get("branchCosts", {}).values()
                if _number(costs.get(ingredient_id)) > 0
            ]
            unit_cost = sum(branch_costs) / len(branch_costs) if branch_costs else _number(ingredient.get("averageCost"))
            calculated_cost += unit_cost * gross / 1000
        _require(components, "Добавьте хотя бы один ингредиент")
        if preparation is None:
            preparation = {"id": str(payload.get("id") or f"pf-{uuid4().hex[:10]}")}
            preparations.append(preparation)
        preparation.update({
            **_appearance(payload, preparation),
            "name": name,
            "category": category,
            "station": station,
            "yield": output_yield,
            "process": str(payload.get("process", "")).strip(),
            "usedIn": str(payload.get("usedIn", "")).strip(),
            "components": components,
            "cost": calculated_cost,
            "updatedAt": _now(),
            "updatedBy": actor,
        })
        return "preparation", str(preparation["id"])

    if action == "product.group.upsert":
        _owner(user)
        draft = deepcopy(state)
        root_id = str(payload.get("id") or f"product-{uuid4().hex[:12]}")
        existing = _find(draft["products"], root_id)
        _require(not existing or not existing.get("parentId"), "Редактируйте основную карточку товара")
        variants = payload.get("variants")
        _require(isinstance(variants, list) and 1 <= len(variants) <= 50, "Добавьте от 1 до 50 модификаций")
        name = str(payload.get("name", "")).strip()
        _require(name and len(name) <= 200, "Укажите название товара")
        old_ids = {str(item["id"]) for item in draft["products"] if item.get("parentId") == root_id or str(item["id"]) == root_id}
        used_ids, used_names = set(), set()
        for index, raw in enumerate(variants):
            _require(isinstance(raw, dict), "Проверьте модификации")
            variant_name = str(raw.get("name", "")).strip()
            _require(variant_name and len(variant_name) <= 80 and variant_name.casefold() not in used_names, "Укажите разные названия модификаций")
            used_names.add(variant_name.casefold())
            variant_id = root_id if index == 0 else str(raw.get("id") or f"product-{uuid4().hex[:12]}")
            _require(not raw.get("id") or str(raw["id"]) == variant_id, "Первая модификация должна сохранять код товара")
            found = _find(draft["products"], variant_id)
            _require(variant_id not in used_ids and (not found or variant_id in old_ids), "Некорректный код модификации")
            used_ids.add(variant_id)
            _require(_number(raw.get("price")) > 0, "Укажите цену каждой модификации")
            apply_action(draft, user, "product.upsert", {**payload, **raw, "id": variant_id, "name": f"{name} — {variant_name}", "averageCost": found.get("averageCost", 0) if found else 0})
            variant = _find(draft["products"], variant_id)
            variant.update({"groupName": name, "variantName": variant_name, "parentId": None if index == 0 else root_id})
        _require(old_ids <= used_ids, "Сохранённые модификации нельзя исключать из карточки: сохраните их складскую историю", 409)
        state.clear()
        state.update(draft)
        return "product", root_id

    if action in {"ingredient.upsert", "product.upsert", "recipe.upsert"}:
        _owner(user)
        collection_name = {"ingredient.upsert": "ingredients", "product.upsert": "products", "recipe.upsert": "recipes"}[action]
        collection = state[collection_name]
        entry = _find(collection, payload.get("id"))
        name = str(payload.get("name", "")).strip()
        _require(name, "Укажите название")
        if entry is None:
            if collection_name == "recipes":
                entry_id: Any = max([int(item.get("id", 0)) for item in collection] or [100]) + 1
            else:
                prefix = "ingredient" if collection_name == "ingredients" else "p"
                entry_id = str(payload.get("id") or f"{prefix}-{uuid4().hex[:10]}")
            entry = {"id": entry_id}
            collection.append(entry)
            if collection_name != "recipes":
                for branch in state["branches"]:
                    _set_stock(state, branch["id"], entry_id, 0, 0)
        if collection_name == "ingredients":
            losses = payload.get("losses") if isinstance(payload.get("losses"), dict) else {}
            entry.update({
                "name": name, "category": str(payload.get("category", "Без категории")),
                "unit": str(payload.get("unit", "кг")), "limit": _number(payload.get("limit")),
                "stock": 0, "averageCost": _number(payload.get("averageCost")),
                "losses": {key: min(99, _number(losses.get(key))) for key in ("boil", "fry", "bake", "clean")},
                "barcode": str(payload.get("barcode", entry.get("barcode", "")))[:64],
            })
        elif collection_name == "products":
            station = str(payload.get("station", entry.get("station", ""))).strip()
            _require(not station or any(row.get("name") == station for row in state.get("stations", [])), "Выберите существующий цех")
            entry["station"] = station
            image = str(payload.get("image", entry.get("image", "")))
            color = str(payload.get("color", entry.get("color", "#5b8fbd")))
            _require(not image or (len(image) <= 3000000 and re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+", image)), "Некорректное фото товара")
            _require(re.fullmatch(r"#[0-9a-fA-F]{6}", color) is not None, "Некорректный цвет товара")
            markup = payload.get("markup", entry.get("markup", 0))
            _require(isinstance(markup, (int, float)) and isfinite(markup) and markup >= -100, "Некорректная наценка")
            entry.update({"image": image, "color": color, "markup": markup})
            entry.update({"name": name, "category": str(payload.get("category", "Без категории")), "unit": str(payload.get("unit", "шт")), "barcode": str(payload.get("barcode", "")), "limit": _number(payload.get("limit")), "price": _number(payload.get("price")), "averageCost": _number(payload.get("averageCost")), "weighted": bool(payload.get("weighted")), "noDiscount": bool(payload.get("noDiscount")), "stock": 0})
        else:
            raw_components = payload.get("components", [])
            components: list[dict[str, Any]] = []
            calculated_yield = 0.0
            for raw in raw_components if isinstance(raw_components, list) else []:
                _require(isinstance(raw, dict), "Проверьте состав техкарты")
                ingredient_id = str(raw.get("ingredientId", ""))
                gross = _number(raw.get("gross"))
                net = _number(raw.get("net"))
                _require(_find(state["ingredients"], ingredient_id) is not None and gross > 0 and net > 0 and net <= gross, "Проверьте состав техкарты")
                components.append({**raw, "ingredientId": ingredient_id, "gross": gross, "net": net})
                calculated_yield += net
            _require(components and calculated_yield > 0, "Проверьте состав техкарты")
            output_yield = _number(payload.get("yield")) if "yield" in payload else calculated_yield
            _require(output_yield > 0, "Укажите выход готового блюда")
            station = str(payload.get("station", "")).strip()
            _require(station, "Укажите цех приготовления")
            entry.update({"name": name, "category": str(payload.get("category", "Без категории")), "station": station, "price": _number(payload.get("price")), "yield": output_yield, "color": str(payload.get("color", entry.get("color", "#6549d5"))), "components": components})
        entry.update(_appearance(payload, entry))
        return collection_name[:-1], str(entry["id"])

    if action == "catalog.delete":
        _owner(user)
        kind = str(payload.get("kind", "")).strip()
        entry_id = str(payload.get("id", "")).strip()
        allowed = {"recipe", "preparation", "ingredient", "product", "menu-category", "ingredient-category", "station"}
        _require(kind in allowed and entry_id, "Неизвестная позиция справочника")
        if kind == "product":
            children = [row for row in state["products"] if row.get("parentId") == entry_id]
            if children:
                draft = deepcopy(state)
                for row in children:
                    apply_action(draft, user, "catalog.delete", {"kind": "product", "id": row["id"]})
                apply_action(draft, user, "catalog.delete", {"kind": "product", "id": entry_id})
                state.clear()
                state.update(draft)
                return "catalog-delete", f"product:{entry_id}"
        logistics = state["logisticsState"]

        def document_uses_item(item_id: str) -> bool:
            for collection_name in ("requests", "directOrders", "supplies", "pointTransfers", "inventories"):
                for document in logistics.get(collection_name, []):
                    for row in document.get("items", []):
                        row_id = row.get("itemId", row.get("ingredientId", row.get("productId", row.get("id"))))
                        if str(row_id) == item_id:
                            return True
            return any(str(row.get("itemId")) == item_id for row in logistics.get("stockLedger", []))

        def sale_uses_item(item_id: str) -> bool:
            return any(str(row.get("id")) == item_id for sale in state.get("sales", []) for row in sale.get("items", []))

        if kind == "recipe":
            entry = _find(state["recipes"], entry_id)
            _require(entry is not None, "Техкарта не найдена", 404)
            _require(not any(str(batch.get("recipeId")) == entry_id for batch in logistics.get("batches", [])), "Техкарту нельзя удалить: по ней уже есть производство", 409)
            _require(not sale_uses_item(entry_id), "Техкарту нельзя удалить: по ней уже есть продажи", 409)
            state["recipes"].remove(entry)
        elif kind == "preparation":
            entry = _find(state.setdefault("preparations", []), entry_id)
            _require(entry is not None, "Полуфабрикат не найден", 404)
            state["preparations"].remove(entry)
        elif kind in {"ingredient", "product"}:
            collection = state["ingredients"] if kind == "ingredient" else state["products"]
            entry = _find(collection, entry_id)
            _require(entry is not None, "Ингредиент не найден" if kind == "ingredient" else "Товар не найден", 404)
            branches_with_stock = [branch["name"] for branch in state["branches"] if _stock(state, str(branch["id"]), entry_id) > 0.000001]
            _require(not branches_with_stock, f"Сначала обнулите остаток: {', '.join(branches_with_stock[:3])}", 409)
            _require(not document_uses_item(entry_id), "Позицию нельзя удалить: она есть в складских документах", 409)
            _require(not sale_uses_item(entry_id), "Позицию нельзя удалить: по ней уже есть продажи", 409)
            if kind == "ingredient":
                for item in [*state["recipes"], *state.get("preparations", [])]:
                    item["components"] = [row for row in item.get("components", []) if str(row.get("ingredientId")) != entry_id]
            collection.remove(entry)
            for branch_stock in logistics.get("branchStocks", {}).values():
                branch_stock.pop(entry_id, None)
            for branch_cost in logistics.get("branchCosts", {}).values():
                branch_cost.pop(entry_id, None)
            for supplier in state.get("suppliers", []):
                for prices in supplier.get("prices", {}).values():
                    if isinstance(prices, dict):
                        prices.pop(entry_id, None)
        elif kind in {"menu-category", "ingredient-category"}:
            registry_name = "menuCategories" if kind == "menu-category" else "ingredientCategories"
            registry = state.setdefault(registry_name, [])
            index = next((index for index, raw in enumerate(registry) if str(raw.get("name", "") if isinstance(raw, dict) else raw).lower() == entry_id.lower()), None)
            _require(index is not None, "Категория не найдена", 404)
            linked = [*state["recipes"], *state["products"]] if kind == "menu-category" else state["ingredients"]
            linked_count = sum(str(item.get("category", "")).lower() == entry_id.lower() for item in linked)
            _require(not linked_count, f"Сначала перенесите {linked_count} связанных позиций в другую категорию", 409)
            registry.pop(index)
            state.get("ingredientCategoryCovers", {}).pop(entry_id, None)
        else:
            stations = state.setdefault("stations", [])
            station = next((entry for entry in stations if str(entry.get("name", "")).lower() == entry_id.lower()), None)
            _require(station is not None, "Цех не найден", 404)
            linked_recipes = 0
            for recipe in state["recipes"]:
                legacy_station = "Холодный цех" if recipe.get("category") == "Салаты" else "Бар" if recipe.get("category") == "Напитки" else "Кухня"
                if str(recipe.get("station") or legacy_station).lower() == entry_id.lower():
                    linked_recipes += 1
            linked_preparations = sum(str(preparation.get("station", "")).lower() == entry_id.lower() for preparation in state.get("preparations", []))
            linked_products = sum(item.get("station") == entry_id for item in state["products"])
            _require(not linked_products, "Сначала назначьте другой цех связанным товарам", 409)
            _require(not linked_recipes and not linked_preparations, f"Сначала назначьте другой цех: {linked_recipes} техкарт, {linked_preparations} полуфабрикатов", 409)
            stations.remove(station)
        return "catalog-delete", f"{kind}:{entry_id}"

    if action == "supply.create":
        if user["role"] == "owner":
            branch_id = str(payload.get("branchId") or "")
            branch = _find(state["branches"], branch_id)
            _require(branch and branch.get("status") == "active", "Выберите действующее заведение")
        else:
            branch_id = _branch_user(user)
            branch = _find(state["branches"], branch_id)
        _require_unlocked(state, branch_id)
        supplier = _find(state["suppliers"], payload.get("supplierId"))
        _require(
            supplier and supplier.get("status") == "active" and (user["role"] == "owner" or branch_id in supplier.get("locations", [])),
            "Поставщик не обслуживает это заведение",
            403,
        )
        invoice = str(payload.get("invoiceNumber", "")).strip()
        if invoice:
            _require(
                not any(entry.get("supplierId") == supplier["id"] and str(entry.get("invoiceNumber", "")).lower() == invoice.lower() for entry in supplies),
                "Поставка с таким номером накладной уже существует",
                409,
            )
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        total = 0.0
        for raw in payload.get("items", []):
            item_id = str(raw.get("itemId", ""))
            quantity = _number(raw.get("quantity"))
            price = _number(raw.get("price"))
            _require(_entity(state, item_id) is not None and quantity > 0 and price > 0 and item_id not in seen, "Проверьте позиции поставки")
            seen.add(item_id)
            rows.append({"itemId": item_id, "quantity": quantity, "price": price, "received": quantity, "receivedPrice": price})
            total += quantity * price
        _require(rows, "Добавьте хотя бы одну позицию")
        total = _money(total)
        number = _next_number("ПСТ", supplies)
        received_at = _receipt_time(payload.get("receivedAt"))
        payments: list[dict[str, Any]] = []
        paid_total = 0.0
        for raw in payload.get("payments", []):
            amount = _money(_number(raw.get("amount")))
            if amount <= 0:
                continue
            account = _find(finance["accounts"], raw.get("accountId"))
            _require(account and account.get("status") == "active", "Выберите активный финансовый счёт")
            _require(not account.get("branchId") or str(account.get("branchId")) == branch_id, "Счёт относится к другому заведению", 403)
            if account.get("type") == "cash":
                _require(user.get("register_id") and user.get("shift_id") and str(account.get("branchId")) == branch_id,
                         "Оплату из кассы оформите в терминале на открытой смене. В админке выберите сейф или банковский счёт", 409)
            payment = {
                "id": f"supply-payment-{uuid4()}", "accountId": str(account["id"]), "amount": amount,
                "occurredAt": str(raw.get("occurredAt") or received_at),
            }
            payments.append(payment)
            paid_total += amount
        paid_total = _money(paid_total)
        _require(paid_total <= total, "Сумма оплаты не может быть больше суммы поставки")
        supply_category = _find(finance["categories"], "finance-expense-purchases")
        if supply_category is None:
            supply_category = {"id": "finance-expense-purchases", "name": "Поставки", "kind": "expense", "status": "active"}
            finance["categories"].append(supply_category)
        for row in rows:
            old_quantity = _stock(state, branch_id, row["itemId"])
            old_cost = _cost(state, branch_id, row["itemId"])
            next_cost = (old_quantity * old_cost + row["quantity"] * row["price"]) / (old_quantity + row["quantity"])
            _set_stock(state, branch_id, row["itemId"], old_quantity + row["quantity"], next_cost)
            supplier.setdefault("prices", {}).setdefault(branch_id, {})[row["itemId"]] = row["price"]
        debt = max(0.0, _money(total - paid_total))
        supply = {
            "id": f"supply-{uuid4()}", "number": number, "documentType": "supply",
            "branchId": branch_id, "supplierId": supplier["id"], "supplier": supplier["name"],
            "invoiceNumber": invoice, "receivedAt": received_at, "createdAt": _now(), "createdBy": actor,
            "receivedBy": actor, "comment": str(payload.get("comment", "")).strip(), "items": rows,
            "total": total, "paidTotal": paid_total, "debt": debt, "payments": payments,
            "paymentStatus": "paid" if debt <= 0.0001 else "partial" if paid_total > 0 else "unpaid",
            "status": "received",
        }
        _record_operation_request(supply, user, payload)
        supplies.insert(0, supply)
        for row in rows:
            _ledger(state, branch_id=branch_id, item_id=row["itemId"], quantity=row["quantity"], unit_cost=row["price"], movement_type="supplier_receipt", document_number=number, actor=actor)
            logistics["stockLedger"][0]["effectiveAt"] = received_at
        for payment in payments:
            _supply_cash_payment(state, user, _find(finance["accounts"], payment["accountId"]), payment, supply)
            finance["transactions"].insert(0, {
                "id": f"finance-transaction-{uuid4()}", "number": _next_number("ФО", finance["transactions"]),
                "type": "expense", "amount": payment["amount"], "occurredAt": payment["occurredAt"],
                "accountId": payment["accountId"], "destinationAccountId": None,
                "categoryId": supply_category["id"], "branchId": branch_id,
                "counterparty": supplier["name"], "comment": f"Поставка {number}",
                "documentId": supply["id"], "paymentId": payment["id"], "automatic": True, "createdAt": _now(), "createdBy": actor,
            })
        return "supplier_receipt", supply["id"]

    if action == "supply.payment.reverse":
        from .supplier_payments import reverse
        return reverse(state, user, payload)

    if action == "supply.pay":
        _owner(user)
        supply = _find(logistics["supplies"], payload.get("id"))
        _require(supply is not None, "Поставка не найдена", 404)
        request_id = str(payload.get("requestId") or "").strip()
        _require(request_id, "Не указан идентификатор платежа")
        previous_payment = next((p for p in supply.get("payments", []) if p.get("requestId") == request_id), None)
        if previous_payment:
            _require(previous_payment["amount"] == _money(_number(payload.get("amount"))) and previous_payment["accountId"] == payload.get("accountId"), "Идентификатор уже использован для другого платежа", 409)
            return "supplier_receipt", supply["id"]
        amount = _money(_number(payload.get("amount")))
        debt = _money(supply["total"]) - _money(supply.get("paidTotal", 0))
        debt = _money(debt)
        _require(0 < amount <= debt, "Укажите сумму не больше остатка долга")
        account = _find(finance["accounts"], payload.get("accountId"))
        _require(account and account.get("status") == "active", "Выберите активный счёт")
        _require(not account.get("branchId") or account["branchId"] == supply["branchId"], "Счёт другого заведения", 403)
        payment = {"id": f"supply-payment-{uuid4()}", "requestId": request_id, "amount": amount, "accountId": account["id"], "occurredAt": _now()}
        _supply_cash_payment(state, user, account, payment, supply)
        supply.setdefault("payments", []).append(payment)
        supply["paidTotal"] = round(float(supply.get("paidTotal", 0)) + amount, 2)
        supply["debt"] = round(debt - amount, 2)
        supply["paymentStatus"] = "paid" if supply["debt"] == 0 else "partial"
        if not _find(finance["categories"], "finance-expense-purchases"):
            finance["categories"].append({"id": "finance-expense-purchases", "name": "Поставки", "kind": "expense", "status": "active"})
        finance["transactions"].insert(0, {"id": f"finance-transaction-{uuid4()}", "number": _next_number("ФО", finance["transactions"]), "type": "expense", "amount": amount, "occurredAt": payment["occurredAt"], "accountId": account["id"], "destinationAccountId": None, "categoryId": "finance-expense-purchases", "branchId": supply["branchId"], "counterparty": supply["supplier"], "comment": f"Оплата поставки {supply['number']}", "documentId": supply["id"], "paymentId": payment["id"], "automatic": True, "createdAt": _now(), "createdBy": actor})
        return "supplier_receipt", supply["id"]

    if action == "order.create":
        branch_id = _branch_user(user)
        supplier = _find(state["suppliers"], payload.get("supplierId"))
        _require(supplier and supplier.get("status") == "active" and branch_id in supplier.get("locations", []), "Поставщик не обслуживает эту точку", 403)
        items = []
        seen: set[tuple[str, str]] = set()
        for raw in payload.get("items", []):
            item_id = str(raw.get("itemId"))
            quantity = _number(raw.get("requested"))
            _require(_entity(state, item_id) is not None and quantity > 0 and (item_id, str(raw.get("lotId") or "")) not in seen, "Проверьте состав заказа")
            seen.add((item_id, str(raw.get("lotId") or "")))
            items.append({"itemId": item_id, "requested": quantity, "estimatedPrice": _number(raw.get("estimatedPrice"))})
        _require(items, "Добавьте хотя бы одну позицию")
        order = {
            "id": f"direct-order-{uuid4()}", "number": _next_number("ЗП", logistics["directOrders"]), "branchId": branch_id,
            "supplierId": supplier["id"], "supplier": supplier["name"], "neededAt": payload.get("neededAt"),
            "comment": str(payload.get("comment", "")).strip(), "items": items,
            "total": sum(item["requested"] * item["estimatedPrice"] for item in items), "status": "submitted",
            "createdAt": _now(), "createdBy": actor,
        }
        logistics["directOrders"].insert(0, order)
        return "purchase_order", order["id"]

    if action == "order.approve":
        _owner(user)
        order = _find(logistics["directOrders"], payload.get("id"))
        _require(order and order.get("status") == "submitted", "Заказ уже обработан", 409)
        order.update({"status": "approved", "approvedAt": _now(), "approvedBy": actor})
        return "purchase_order", order["id"]

    if action == "order.send":
        branch_id = _branch_user(user)
        order = _find(logistics["directOrders"], payload.get("id"))
        _require(order and order.get("branchId") == branch_id and order.get("status") == "approved", "Заказ нельзя отправить", 409)
        order.update({"status": "ordered", "orderedAt": _now(), "orderedBy": actor, "sentVia": payload.get("method", "manual"), "sentTo": str(payload.get("recipient", "Передан вручную"))})
        return "purchase_order", order["id"]

    if action == "order.receive":
        branch_id = _branch_user(user)
        _require_unlocked(state, branch_id)
        received_at = _receipt_time(payload.get("receivedAt"))
        order = _find(logistics["directOrders"], payload.get("id"))
        _require(order and order.get("branchId") == branch_id and order.get("status") == "ordered", "Поставка недоступна для приёмки", 409)
        invoice = str(payload.get("invoiceNumber", "")).strip()
        _require(invoice, "Укажите номер накладной поставщика")
        _require(not any(other is not order and other.get("supplierId") == order.get("supplierId") and other.get("invoiceNumber", "").lower() == invoice.lower() for other in logistics["directOrders"]), "Накладная с таким номером уже принята", 409)
        received_by_id = {str(item.get("itemId")): item for item in payload.get("items", [])}
        accepted = 0
        total = 0.0
        variance = 0.0
        supplier = _find(state["suppliers"], order["supplierId"])
        for item in order["items"]:
            actual_row = received_by_id.get(str(item["itemId"]), {})
            actual = _number(actual_row.get("received"))
            price = _number(actual_row.get("receivedPrice"))
            _require(not actual or price > 0, "Укажите фактическую цену принятой позиции")
            old_quantity = _stock(state, branch_id, item["itemId"])
            old_cost = _cost(state, branch_id, item["itemId"])
            item.update({"received": actual, "receivedPrice": price, "temperature": _number(actual_row.get("temperature"))})
            if actual:
                next_cost = (old_quantity * old_cost + actual * price) / (old_quantity + actual)
                _set_stock(state, branch_id, item["itemId"], old_quantity + actual, next_cost)
                supplier.setdefault("prices", {}).setdefault(branch_id, {})[str(item["itemId"])] = price
                _ledger(state, branch_id=branch_id, item_id=item["itemId"], quantity=actual, unit_cost=price, movement_type="supplier_receipt", document_number=order["number"], actor=actor)
                logistics["stockLedger"][0]["effectiveAt"] = received_at
                accepted += 1
            total += actual * price
            variance += actual - _number(item.get("requested"))
        _require(accepted > 0, "Укажите фактически принятое количество")
        order.update({"status": "received", "receivedAt": received_at, "receivedBy": actor, "invoiceNumber": invoice, "receivingComment": str(payload.get("comment", "")).strip(), "total": _money(total), "variance": variance})
        return "supplier_receipt", order["id"]

    if action == "transfer.create":
        destination = _branch_user(user)
        source = str(payload.get("sourceBranchId", ""))
        _require(source != destination and _find(state["branches"], source), "Выберите другую точку-отправителя")
        items = []
        seen: set[tuple[str, str]] = set()
        for raw in payload.get("items", []):
            item_id = str(raw.get("itemId"))
            quantity = _number(raw.get("requested"))
            _require(_entity(state, item_id) and quantity > 0 and item_id not in seen, "Проверьте состав перемещения")
            seen.add(item_id)
            items.append({"itemId": item_id, "requested": quantity})
        _require(items, "Добавьте продукты")
        transfer = {"id": f"point-transfer-{uuid4()}", "number": _next_number("МТ", logistics["pointTransfers"]), "sourceBranchId": source, "destinationBranchId": destination, "neededAt": payload.get("neededAt"), "comment": str(payload.get("comment", "")).strip(), "items": items, "status": "submitted", "createdAt": _now(), "createdBy": actor}
        logistics["pointTransfers"].insert(0, transfer)
        return "point_transfer", transfer["id"]

    if action == "transfer.approve":
        _owner(user)
        transfer = _find(logistics["pointTransfers"], payload.get("id"))
        _require(transfer and transfer.get("status") == "submitted", "Перемещение уже обработано", 409)
        approved_total = 0.0
        for item in transfer["items"]:
            reserved = sum(_number(row.get("approved")) for other in logistics["pointTransfers"] if other is not transfer and other.get("sourceBranchId") == transfer["sourceBranchId"] and other.get("status") == "approved" for row in other.get("items", []) if str(row.get("itemId")) == str(item["itemId"]))
            item["approved"] = min(_number(item["requested"]), max(0, _stock(state, transfer["sourceBranchId"], item["itemId"]) - reserved))
            approved_total += item["approved"]
        _require(approved_total > 0, "На точке-отправителе нет доступного остатка", 409)
        transfer.update({"status": "approved", "approvedAt": _now(), "approvedBy": actor, "hasShortage": any(_number(item["approved"]) < _number(item["requested"]) for item in transfer["items"])})
        return "point_transfer", transfer["id"]

    if action == "transfer.dispatch":
        branch_id = _branch_user(user)
        transfer = _find(logistics["pointTransfers"], payload.get("id"))
        _require(transfer and transfer.get("sourceBranchId") == branch_id and transfer.get("status") == "approved", "Отгрузку подтверждает точка-отправитель", 403)
        _require_unlocked(state, branch_id)
        shipped_total = 0.0
        total_cost = 0.0
        for item in transfer["items"]:
            shipped = min(_number(item.get("approved")), _stock(state, branch_id, item["itemId"]))
            unit_cost = _cost(state, branch_id, item["itemId"])
            item.update({"shipped": shipped, "unitCost": unit_cost})
            _set_stock(state, branch_id, item["itemId"], _stock(state, branch_id, item["itemId"]) - shipped)
            if shipped:
                _ledger(state, branch_id=branch_id, item_id=item["itemId"], quantity=-shipped, unit_cost=unit_cost, movement_type="transfer_out", document_number=transfer["number"], actor=actor, related_branch_id=transfer["destinationBranchId"])
            shipped_total += shipped
            total_cost += shipped * unit_cost
        _require(shipped_total > 0, "Нет доступного остатка для отгрузки", 409)
        transfer.update({"status": "shipped", "shippedAt": _now(), "shippedBy": actor, "totalCost": total_cost})
        return "point_transfer", transfer["id"]

    if action == "transfer.receive":
        branch_id = _branch_user(user)
        transfer = _find(logistics["pointTransfers"], payload.get("id"))
        _require(transfer and transfer.get("destinationBranchId") == branch_id and transfer.get("status") == "shipped", "Приёмку подтверждает точка-получатель", 403)
        _require_unlocked(state, branch_id)
        actual_by_id = {str(item.get("itemId")): _number(item.get("received")) for item in payload.get("items", [])}
        variance = 0.0
        accepted = 0.0
        for item in transfer["items"]:
            shipped = _number(item.get("shipped"))
            actual = actual_by_id.get(str(item["itemId"]), 0)
            _require(actual <= shipped, "Принятое количество не может быть больше отгруженного")
            old_quantity = _stock(state, branch_id, item["itemId"])
            old_cost = _cost(state, branch_id, item["itemId"])
            incoming_cost = _number(item.get("unitCost"))
            item["received"] = actual
            if actual:
                next_cost = (old_quantity * old_cost + actual * incoming_cost) / (old_quantity + actual)
                _set_stock(state, branch_id, item["itemId"], old_quantity + actual, next_cost)
                _ledger(state, branch_id=branch_id, item_id=item["itemId"], quantity=actual, unit_cost=incoming_cost, movement_type="transfer_in", document_number=transfer["number"], actor=actor, related_branch_id=transfer["sourceBranchId"])
                accepted += actual
            loss = shipped - actual
            if loss:
                _ledger(state, branch_id=transfer["sourceBranchId"], item_id=item["itemId"], quantity=0, unit_cost=incoming_cost, movement_type="transfer_variance", document_number=transfer["number"], actor=actor, related_branch_id=branch_id)
            variance += actual - shipped
        _require(accepted > 0, "Укажите фактически принятое количество")
        transfer.update({"status": "received", "receivedAt": _now(), "receivedBy": actor, "receivingComment": str(payload.get("comment", "")).strip(), "variance": variance})
        return "point_transfer", transfer["id"]

    if action == "inventory.start":
        branch_id = str(payload.get("branchId") or "") if user["role"] == "owner" else _branch_user(user)
        _require(_find(state["branches"], branch_id), "Выберите заведение")
        _require(not _locked(state, branch_id), "На точке уже идёт инвентаризация", 409)
        scope = payload.get("scope", "full")
        category = str(payload.get("category", ""))
        entities = [*state["ingredients"], *state["products"]]
        if scope == "category":
            entities = [entry for entry in entities if entry.get("category") == category]
        _require(entities, "В выбранной категории нет продуктов")
        from .inventory_count import build
        count_items, counted_at = build(state, branch_id, payload, entities)
        _require(count_items, "Нет позиций для подсчёта")
        inventory = {"id": f"inventory-{uuid4()}", "number": _next_number("ИНВ", logistics["inventories"]), "branchId": branch_id, "scope": scope, "category": category, "responsible": str(payload.get("responsible") or actor), "status": "counting", "items": count_items, "countedAt": counted_at, "comment": "", "createdAt": _now(), "createdBy": actor}
        logistics["inventories"].insert(0, inventory)
        return "inventory", inventory["id"]

    if action in {"inventory.save", "inventory.submit", "inventory.cancel"}:
        inventory = _find(logistics["inventories"], payload.get("id"))
        branch_id = inventory.get("branchId") if user["role"] == "owner" and inventory else _branch_user(user)
        _require(inventory and inventory.get("branchId") == branch_id and inventory.get("status") in {"counting", "returned"}, "Инвентаризация недоступна", 409)
        if action != "inventory.cancel":
            actual_by_id = {str(item.get("itemId")): item.get("actual") for item in payload.get("items", [])}
            for item in inventory["items"]:
                if str(item["itemId"]) in actual_by_id:
                    raw = actual_by_id[str(item["itemId"])]
                    if raw not in {None, ""}:
                        try:
                            _require(isfinite(float(raw)) and float(raw) >= 0, "Фактический остаток должен быть числом не меньше нуля")
                        except (ValueError, TypeError):
                            raise WorkspaceError("Фактический остаток должен быть числом не меньше нуля")
                    item["actual"] = None if raw in {None, ""} else _number(raw)
            inventory["comment"] = str(payload.get("comment", "")).strip()
        if action == "inventory.save":
            inventory.update({"savedAt": _now(), "savedBy": actor})
        elif action == "inventory.submit":
            _require(all(item.get("actual") is not None for item in inventory["items"]), "Введите фактическое количество всех позиций")
            inventory.update({"status": "submitted", "submittedAt": _now(), "submittedBy": actor, "reviewComment": ""})
        else:
            inventory.update({"status": "cancelled", "cancelledAt": _now(), "cancelledBy": actor})
        return "inventory", inventory["id"]

    if action in {"inventory.return", "inventory.post"}:
        _require(user.get("role") == "owner", "Инвентаризацию проводит владелец компании", 403)
        inventory = _find(logistics["inventories"], payload.get("id"))
        _require(inventory and inventory.get("status") == "submitted", "Инвентаризация уже обработана", 409)
        if action == "inventory.return":
            comment = str(payload.get("comment", "")).strip()
            _require(comment, "Укажите причину возврата на пересчёт")
            inventory.update({"status": "returned", "reviewComment": comment, "returnedAt": _now(), "returnedBy": actor})
        else:
            from .inventory_count import current, adjust, variance
            for item in inventory["items"]:
                _require(abs(current(state, inventory["branchId"], item) - _number(item.get("currentBook", item["book"]))) < 0.0001, "Остаток изменился после начала — нужен новый подсчёт", 409)
                _require(current(state, inventory["branchId"], item) + variance(item.get("actual"), item["book"]) >= -0.000001, "Корректировка создаёт отрицательный текущий остаток")
            for item in inventory["items"]:
                actual = _number(item.get("actual"))
                difference = variance(actual, item["book"])
                adjust(state, inventory["branchId"], item, difference)
                if difference:
                    _ledger(state, branch_id=inventory["branchId"], item_id=item["itemId"], quantity=difference, unit_cost=_number(item["unitCost"]), movement_type="inventory_adjustment", document_number=inventory["number"], actor=actor)
                    logistics["stockLedger"][0]["effectiveAt"] = inventory.get("countedAt", inventory["createdAt"])
            inventory.update({"status": "posted", "postedAt": _now(), "postedBy": actor, "reviewComment": str(payload.get("comment", "")).strip()})
        return "inventory", inventory["id"]

    if action.startswith("production.shift."):
        _require_unlocked(state, _branch_user(user))
        from . import production_shifts
        draft = deepcopy(state)
        try:
            result = production_shifts.apply(draft, user, action, payload)
        except custody.CustodyError as error:
            raise WorkspaceError(str(error), error.status_code) from error
        state.clear()
        state.update(draft)
        return result

    if action == "sale.import":
        from .sales_import import commit
        return commit(state, user, payload)

    if action == "pos.serving.surplus":
        _require(user.get("shift_id") and user.get("staff_role") in {"cashier", "branch_manager", "hall_admin"}, "Излишек оформляет кассир на открытой смене", 403)
        _require(payload.get("lotId"), "Выберите принятую партию блюда")
        try:
            return custody.apply(state, {**user, "_serving_surplus": True}, "custody.surplus", payload)
        except custody.CustodyError as error:
            raise WorkspaceError(str(error), error.status_code) from error

    if action == "pos.serving.writeoff":
        _require(user.get("shift_id") and user.get("staff_role") in {"cashier", "branch_manager", "hall_admin"}, "Списание доступно кассиру на открытой смене", 403)
        _require(payload.get("lotId"), "Выберите принятую партию блюда")
        try:
            return custody.apply(state, {**user, "_serving_writeoff": True}, "custody.writeoff", payload)
        except custody.CustodyError as error:
            raise WorkspaceError(str(error), error.status_code) from error

    if action in {"pos.receiving.accept", "pos.receiving.reject"}:
        _require_unlocked(state, _branch_user(user))
        _require(user.get("shift_id") and user.get("staff_role") in {"cashier", "branch_manager", "hall_admin"}, "Приёмка доступна кассиру на открытой смене", 403)
        if str(payload.get("documentId", "")).startswith("legacy:"):
            _require(action == "pos.receiving.accept", "Для старого остатка укажите фактический вес; отсутствующий остаток — 0 с причиной")
            batch_id = str(payload["documentId"])[len("legacy:"):]
            try:
                return custody.apply(state, {**user, "_receiving_cashier": True}, "custody.confirm_stock", {**payload, "batchId": batch_id, "lotId": "legacy-" + batch_id})
            except custody.CustodyError as error:
                raise WorkspaceError(str(error), error.status_code) from error
        source = next((entry for entry in logistics.get("custodyDocuments", []) if entry["id"] == payload.get("documentId")), None)
        _require(source and source.get("recipient", {}).get("kind") == "branch_cashiers", "Передача на кассу не найдена", 404)
        try:
            return custody.apply(state, {**user, "_receiving_cashier": True}, "custody.accept" if action.endswith("accept") else "custody.reject", payload)
        except custody.CustodyError as error:
            raise WorkspaceError(str(error), error.status_code) from error

    if action.startswith("custody.") or action == "batch.transfer":
        try:
            return custody.apply(state, user, "custody.send" if action == "batch.transfer" else action, payload)
        except custody.CustodyError as error:
            raise WorkspaceError(str(error), error.status_code) from error

    if action == "batch.serve_many":
        branch_id = _branch_user(user)
        _require(user.get("plan_code") != "restaurant", "Передача на раздачу доступна в режиме столовой", 403)
        request_id = str(payload.get("requestId", "")).strip()
        raw_items = payload.get("items")
        _require(0 < len(request_id) <= 80, "Не указан идентификатор передачи")
        _require(isinstance(raw_items, list) and 0 < len(raw_items) <= 100, "Добавьте от 1 до 100 блюд")
        _require(all(isinstance(item, dict) for item in raw_items), "Проверьте строки передачи")
        items = [{"recipeId": str(item.get("recipeId", "")), "weight": _number(item.get("weight"))} for item in raw_items]
        _require(all(item["weight"] > 0 and _recipe(state, item["recipeId"]) for item in items), "Выберите блюда и укажите количество")
        _require(len({item["recipeId"] for item in items}) == len(items), "Одинаковые блюда объедините в одну строку")
        fingerprint = {"actorId": str(user.get("id")), "items": items}
        prior = next((entry for entry in logistics.get("servingRequests", []) if entry["requestId"] == request_id and entry["branchId"] == branch_id), None)
        if prior:
            _require(prior.get("fingerprint") == fingerprint, "Запрос уже использован для другой передачи", 409)
            return "serving_document", prior["id"]
        draft = deepcopy(state)
        group_id = "serving-" + str(uuid4())
        previous_docs = {entry["id"] for entry in draft["logisticsState"].get("custodyDocuments", [])}
        for item in items:
            try:
                apply_action(draft, user, "batch.serve", {**item, "requestId": str(uuid4())})
            except WorkspaceError as error:
                raise WorkspaceError(f"{_recipe(state, item['recipeId'])['name']}: {error}", error.status_code) from error
        for document in draft["logisticsState"].get("custodyDocuments", []):
            if document["id"] not in previous_docs:
                document["servingDocumentId"] = group_id
        draft["logisticsState"].setdefault("servingRequests", []).append({"id": group_id, "requestId": request_id, "branchId": branch_id, "fingerprint": fingerprint, "createdAt": _now()})
        state.clear()
        state.update(draft)
        return "serving_document", group_id

    if action == "batch.serve":
        branch_id = _branch_user(user)
        payload = {**payload, "line": "Раздача", "recipientId": "branch_cashiers"}
        user = {**user, "_custody_recipient": {"id": "branch_cashiers", "kind": "branch_cashiers", "name": "Касса заведения", "branchId": branch_id}}
        _require(user.get("plan_code") != "restaurant", "Передача на раздачу доступна в режиме столовой", 403)
        request_id = str(payload.get("requestId", "")).strip()
        weight = _number(payload.get("weight"))
        _require(0 < len(request_id) <= 80 and weight > 0, "Укажите количество и идентификатор передачи")
        fingerprint = {"recipeId": str(payload.get("recipeId")), "weight": weight, "line": str(payload.get("line", "")).strip(), "recipientId": str(payload.get("recipientId")), "actorId": str(user.get("id"))}
        previous = next((entry for entry in logistics.get("servingRequests", []) if entry["requestId"] == request_id and entry["branchId"] == branch_id), None)
        if previous:
            _require(previous["fingerprint"] == fingerprint, "Запрос уже использован для другой передачи", 409)
            return "production_batch", previous["batchId"]
        draft = deepcopy(state)
        remaining = weight
        batch_id = None
        batches = sorted(draft["logisticsState"]["batches"], key=lambda batch: batch.get("createdAt", ""))
        for batch in batches:
            if batch.get("branchId") != branch_id or str(batch.get("recipeId")) != fingerprint["recipeId"] or batch.get("status") == "closed":
                continue
            amount = min(remaining, max(0, custody.kitchen_balance(batch)))
            if amount <= 0:
                continue
            batch_id = batch["id"]
            apply_action(draft, user, "batch.transfer", {**payload, "id": batch_id, "weight": amount, "requestId": str(uuid4())})
            remaining = round(remaining - amount, 6)
            if remaining <= 0:
                break
        if remaining > 0:
            _, batch_id = apply_action(draft, user, "batch.release", {**payload, "weight": remaining, "requestId": str(uuid4())})
        draft["logisticsState"].setdefault("servingRequests", []).append({"requestId": request_id, "branchId": branch_id, "fingerprint": fingerprint, "batchId": batch_id, "createdAt": _now()})
        state.clear()
        state.update(draft)
        return "production_batch", batch_id

    if action == "batch.release":
        branch_id = _branch_user(user)
        _require(user.get("plan_code") != "restaurant", "Выпуск на витрину доступен в режиме столовой", 403)
        request_id = str(payload.get("requestId", "")).strip()
        _require(0 < len(request_id) <= 80, "Не указан идентификатор выпуска")
        previous = next((batch for batch in logistics["batches"] if batch.get("branchId") == branch_id and batch.get("releaseRequestId") == request_id), None)
        if previous:
            _require(str(previous["recipeId"]) == str(payload.get("recipeId")) and abs(_number(previous["actualWeight"]) - _number(payload.get("weight"))) < 0.000001 and previous.get("releaseLine") == str(payload.get("line", "")).strip() and str(previous.get("releaseRecipientId")) == str(payload.get("recipientId")), "Этот запрос уже использован для другого выпуска", 409)
            return "production_batch", previous["id"]
        draft = deepcopy(state)
        _, batch_id = apply_action(draft, user, "batch.create", payload)
        apply_action(draft, user, "batch.transfer", {**payload, "id": batch_id, "receiver": actor})
        batch = _find(draft["logisticsState"]["batches"], batch_id)
        batch.update({"releaseRequestId": request_id, "releaseLine": str(payload.get("line", "")).strip(), "releaseRecipientId": payload.get("recipientId")})
        state.clear()
        state.update(draft)
        return "production_batch", batch_id

    if action == "batch.create":
        _require(user.get("plan_code") != "restaurant", "В тарифе «Ресторан» ингредиенты списываются по техкарте при оплате заказа", 403)
        branch_id = _branch_user(user)
        _require_unlocked(state, branch_id)
        recipe = _recipe(state, payload.get("recipeId"))
        weight = _number(payload.get("weight"))
        _require(recipe and weight > 0, "Укажите блюдо и фактический вес")
        equivalent = weight * 1000 / _number(recipe["yield"], minimum=0.001)
        requirements = [( {"ingredientId": key}, amount) for key, amount in recipe_requirements(recipe, equivalent).items()]
        _require(requirements and any(required > 0 for _, required in requirements), "Заполните состав техкарты")
        shortages = []
        for component, required in requirements:
            missing = required - _stock(state, branch_id, component["ingredientId"])
            if missing > 0.0001:
                ingredient = _find(state.get("ingredients", []), component["ingredientId"]) or {}
                shortages.append(f"{ingredient.get('name', component['ingredientId'])}: {missing:.3f} {ingredient.get('unit', '')}".strip())
        _require(not shortages, "На точке недостаточно сырья. Не хватает: " + "; ".join(shortages), 409)
        number = _next_number("АП", logistics["batches"])
        total_cost = 0.0
        ingredient_snapshot = []
        for component, required in requirements:
            item_id = component["ingredientId"]
            unit_cost = _cost(state, branch_id, item_id)
            _set_stock(state, branch_id, item_id, _stock(state, branch_id, item_id) - required)
            _ledger(state, branch_id=branch_id, item_id=item_id, quantity=-required, unit_cost=unit_cost, movement_type="production_consumption", document_number=number, actor=actor)
            total_cost += required * unit_cost
            ingredient = _find(state["ingredients"], item_id) or {}
            ingredient_snapshot.append({"itemId": item_id, "name": ingredient.get("name", str(item_id)), "unit": ingredient.get("unit", "кг"), "quantity": required, "unitCost": unit_cost})
        batch = {"id": f"batch-{uuid4()}", "number": number, "branchId": branch_id, "recipeId": recipe["id"], "actualWeight": weight, "portionWeight": recipe["yield"], "portionWeightSource": "production", "transferredWeight": 0, "soldPortions": 0, "servedPortions": 0, "status": "kitchen", "createdAt": _now(), "createdBy": actor, "createdById": user.get("id"), "cost": total_cost, "ingredientSnapshot": ingredient_snapshot, "custodyVersion": 1, "servingLots": [], "dispatchedWeight": 0}
        _record_operation_request(batch, user, payload)
        logistics["batches"].insert(0, batch)
        return "production_batch", batch["id"]

    if action == "batch.close":
        branch_id = _branch_user(user)
        batch = _find(logistics["batches"], payload.get("id"))
        _require(batch and batch.get("branchId") == branch_id and batch.get("status") in {"serving", "partial"}, "Партия не находится на раздаче", 409)
        _require(not batch.get("custodyVersion"), "Для новой партии оформите пересчёт и списание через журнал витрины")
        recipe = _recipe(state, batch["recipeId"])
        remaining = _number(payload.get("remainingWeight"))
        sold = _number(batch.get("soldPortions"))
        used = sold * custody.portion_weight(batch, recipe) / 1000
        _require(remaining <= _number(batch["transferredWeight"]) - used + 0.0001, "Остаток больше доступной массы")
        batch.update({"servedPortions": sold, "remainingWeight": remaining, "remainderAction": payload.get("remainderAction", "writeoff"), "massVariance": _number(batch["transferredWeight"]) - used - remaining, "status": "closed", "closedAt": _now(), "closedBy": actor})
        return "production_batch", batch["id"]

    if action == "pos.customer.upsert":
        branch_id = _branch_user(user)
        name = str(payload.get("name", "")).strip()
        phone = str(payload.get("phone", "")).strip()
        _require(name, "Укажите имя гостя")
        _require(phone, "Укажите телефон гостя")
        customer = _find(pos["customers"], payload.get("id"))
        _require(not any(
            other is not customer and str(other.get("phone", "")).strip() == phone
            for other in pos["customers"]
        ), "Гость с таким телефоном уже существует", 409)
        if customer is None:
            customer = {
                "id": f"customer-{uuid4()}", "createdAt": _now(), "createdBy": actor,
                "visits": 0, "revenue": 0, "branches": [],
            }
            pos["customers"].insert(0, customer)
        discount = _number(payload.get("discountPercent"))
        _require(discount <= 100, "Скидка не может быть больше 100%")
        customer.update({
            "name": name, "phone": phone,
            "discountPercent": discount,
            "comment": str(payload.get("comment", "")).strip(),
            "updatedAt": _now(), "updatedBy": actor,
        })
        branches = {str(value) for value in customer.get("branches", [])}
        branches.add(branch_id)
        customer["branches"] = sorted(branches)
        return "pos_customer", customer["id"]

    if action == "pos.order.save":
        branch_id = _branch_user(user)
        order_details = _order_details(state, payload)
        raw_items = payload.get("items", [])
        _require(raw_items, "В заказе нет позиций")
        normalized_items = []
        seen: set[tuple[str, str]] = set()
        for raw in raw_items:
            item_id = str(raw.get("id"))
            quantity = _number(raw.get("quantity"))
            _require((_recipe(state, item_id) or _find(state["products"], item_id)) and quantity > 0 and (item_id, str(raw.get("lotId") or "")) not in seen, "Проверьте состав заказа")
            seen.add((item_id, str(raw.get("lotId") or "")))
            item = _recipe(state, item_id) or _find(state["products"], item_id)
            normalized_items.append({"id": item_id, "quantity": quantity, "lotId": raw.get("lotId"), "name": item["name"], **_station_route(state, item, branch_id)})
        order = _find(pos["openOrders"], payload.get("id"))
        if order is None:
            order = {
                "id": f"open-order-{uuid4()}",
                "number": _next_number("З", pos["openOrders"]),
                "createdAt": _now(), "createdBy": actor, "openedById": user.get("id"),
            }
            pos["openOrders"].insert(0, order)
        _require(order.get("branchId") in {None, branch_id}, "Заказ относится к другой точке", 403)
        customer = _find(pos["customers"], payload.get("customerId"))
        discount = _number(customer.get("discountPercent")) if customer else 0
        _require(discount <= 100, "Скидка не может быть больше 100%")
        order.update({
            **order_details,
            "branchId": branch_id, "registerId": user.get("register_id"),
            "shiftId": user.get("shift_id"), "items": normalized_items,
            "applyService": bool(payload.get("applyService", settings["general"]["serviceDefault"])),
            "status": order.get("status", "new"),
            "dueAt": order.get("dueAt") or (datetime.now(timezone.utc) + timedelta(minutes=settings["orders"]["preparationMinutes"])).isoformat(),
            "customerId": customer.get("id") if customer else None,
            "customerName": customer.get("name") if customer else "",
            "discountPercent": discount,
            "comment": str(payload.get("comment", "")).strip(),
            "label": str(payload.get("label", "")).strip() or "Заказ без названия",
            "updatedAt": _now(), "updatedBy": actor,
        })
        return "pos_open_order", order["id"]

    if action == "pos.order.status":
        branch_id = _branch_user(user)
        order = _find(pos["openOrders"], payload.get("id"))
        _require(order and order.get("branchId") == branch_id and order.get("orderType") == "delivery", "Заказ доставки не найден", 404)
        stages = ["new"] + (["ready"] if settings["delivery"]["useReadyStatus"] else []) + ["en-route"] + (["delivered"] if settings["delivery"]["useDeliveredStatus"] else [])
        current = order.get("status", "new")
        _require(payload.get("status") in stages and current in stages and stages.index(payload["status"]) == stages.index(current) + 1, "Недопустимый переход статуса")
        order["status"] = payload["status"]
        order["updatedAt"] = _now()
        return "pos_open_order", order["id"]

    if action == "pos.order.remove":
        branch_id = _branch_user(user)
        order = _find(pos["openOrders"], payload.get("id"))
        _require(order and order.get("branchId") == branch_id, "Заказ не найден", 404)
        pos["openOrders"].remove(order)
        return "pos_open_order", str(order["id"])

    if action == "pos.cash.movement":
        branch_id = _branch_user(user)
        movement_type = str(payload.get("type", ""))
        _require(movement_type in {"deposit", "expense", "collection"}, "Выберите кассовую операцию")
        amount = _number(payload.get("amount"))
        _require(amount > 0, "Сумма должна быть больше нуля")
        movement = {
            "id": f"cash-movement-{uuid4()}", "branchId": branch_id,
            "registerId": user.get("register_id"), "shiftId": user.get("shift_id"),
            "type": movement_type, "amount": amount,
            "comment": str(payload.get("comment", "")).strip(),
            "createdAt": _now(), "createdBy": actor,
        }
        _record_operation_request(movement, user, payload)
        pos["cashMovements"].insert(0, movement)
        cash_account_id = f"finance-cash-{branch_id}"
        finance_transaction = {
            "id": f"finance-transaction-{uuid4()}",
            "number": _next_number("КО", finance["transactions"]),
            "type": "expense" if movement_type == "expense" else "transfer",
            "amount": amount, "occurredAt": movement["createdAt"],
            "accountId": cash_account_id if movement_type in {"expense", "collection"} else "finance-safe",
            "destinationAccountId": cash_account_id if movement_type == "deposit" else ("finance-safe" if movement_type == "collection" else None),
            "categoryId": "finance-expense-other" if movement_type == "expense" else None,
            "branchId": branch_id, "counterparty": actor,
            "comment": movement["comment"] or {"deposit": "Внесение в кассу", "expense": "Расход из кассы", "collection": "Инкассация"}[movement_type],
            "createdAt": movement["createdAt"], "createdBy": actor,
            "automatic": True, "sourceType": "pos_cash_movement", "sourceId": movement["id"],
        }
        finance["transactions"].insert(0, finance_transaction)
        return "pos_cash_movement", movement["id"]

    if action == "sale.refund":
        branch_id = _branch_user(user)
        _require_unlocked(state, branch_id)
        _require(user.get("staff_role") in {"branch_manager", "hall_admin"}, "Возврат подтверждает руководитель или администратор зала", 403)
        sale = _find(state["sales"], payload.get("id"))
        _require(sale and sale.get("branchId") == branch_id, "Чек не найден", 404)
        _require(sale.get("paymentMethod") != "external", "Возврат импортированного реестра оформляется во внешней кассе", 409)
        _require(not sale.get("refundedAt"), "По этому чеку возврат уже оформлен", 409)
        for item in sale.get("items", []):
            for allocation in item.get("batchAllocations", []):
                batch = _find(logistics["batches"], allocation.get("batchId")) or {}
                lot = next((row for row in batch.get("servingLots", []) if row["id"] == allocation.get("lotId")), None)
                _require(not lot or not lot.get("handoverId"), "Завершите приёмку остатков следующей сменой перед возвратом", 409)

        for item in sale.get("items", []):
            product = _find(state["products"], item.get("id"))
            if product:
                quantity = _number(item.get("quantity"))
                current_quantity = _stock(state, branch_id, product["id"])
                current_cost = _cost(state, branch_id, product["id"])
                returned_cost = _number(item.get("unitCost"))
                next_quantity = current_quantity + quantity
                next_cost = (current_quantity * current_cost + quantity * returned_cost) / next_quantity if next_quantity else current_cost
                _set_stock(state, branch_id, product["id"], next_quantity, next_cost)
                _ledger(state, branch_id=branch_id, item_id=product["id"], quantity=quantity, unit_cost=_number(item.get("unitCost")), movement_type="sale_refund", document_number=f"ВОЗВРАТ-{sale.get('number')}", actor=actor)
                continue
            if item.get("ingredientAllocations"):
                # Prepared food is not returned to raw stock by a payment refund.
                # Disposal and stock corrections are separate inventory documents.
                continue
            if any(allocation.get("lotId") and not str(allocation["lotId"]).startswith("legacy-") for allocation in item.get("batchAllocations", [])):
                continue
            remaining = _number(item.get("quantity"))
            allocations = item.get("batchAllocations", [])
            for allocation in allocations:
                batch = _find(logistics["batches"], allocation.get("batchId"))
                quantity = min(remaining, _number(allocation.get("quantity")))
                if batch and quantity:
                    batch["soldPortions"] = max(0, _number(batch.get("soldPortions")) - quantity)
                    batch["servedPortions"] = batch["soldPortions"]
                    if allocation.get("lotId"):
                        lot = next((row for row in batch.get("servingLots", []) if row["id"] == allocation["lotId"]), None)
                        if lot:
                            recipe = _recipe(state, batch["recipeId"]) or {}
                            lot["soldWeight"] = max(0, _number(lot.get("soldWeight")) - (quantity / max(_number(allocation.get("quantity")), .000001) * _number(allocation["weight"]) if "weight" in allocation else quantity * custody.portion_weight(batch, recipe) / 1000))
                    remaining -= quantity
            if remaining:
                for batch in logistics["batches"]:
                    if batch.get("branchId") != branch_id or str(batch.get("recipeId")) != str(item.get("id")):
                        continue
                    quantity = min(remaining, _number(batch.get("soldPortions")))
                    batch["soldPortions"] = _number(batch.get("soldPortions")) - quantity
                    batch["servedPortions"] = batch["soldPortions"]
                    remaining -= quantity
                    if not remaining:
                        break
        reason = str(payload.get("reason", "")).strip()
        _require(reason, "Укажите причину возврата")
        sale.update({
            "refundedAt": _now(), "refundedBy": actor, "refundReason": reason,
            "refundShiftId": user.get("shift_id"), "refundRegisterId": user.get("register_id"),
        })
        from .payroll import record_refund
        record_refund(state, sale)
        return "sale_refund", str(sale["id"])

    if action == "sale.create":
        _require_unlocked(state, _branch_user(user))
        open_order = _find(pos["openOrders"], payload.get("openOrderId")) if payload.get("openOrderId") else None
        if payload.get("openOrderId"):
            _require(open_order and open_order.get("branchId") == user.get("branch_id"), "Заказ уже закрыт или недоступен", 409)
        order_details = _order_details(state, payload)
        branch_id = _branch_user(user)
        raw_items = payload.get("items", [])
        _require(raw_items, "Чек пуст")
        raw_ids = [(str(item.get("id")), str(item.get("lotId") or "")) for item in raw_items]
        _require(len(raw_ids) == len(set(raw_ids)), "Одна позиция не может повторяться в чеке")
        sale_items: list[dict[str, Any]] = []
        allocations: list[tuple[dict[str, Any], int]] = []
        ready_deductions: list[tuple[dict[str, Any], float]] = []
        total = 0.0
        ingredient_deductions = {}
        serving_allocations = []
        for raw in raw_items:
            item_id = raw.get("id")
            quantity = _number(raw.get("quantity"))
            recipe = _recipe(state, item_id)
            product = _find(state["products"], item_id)
            _require(quantity > 0 and (recipe or product), "В чеке есть недоступная позиция")
            ingredient_allocations = []
            if product or user.get("plan_code") == "restaurant":
                _require(not raw.get("lotId"), "Партия указывается только для блюда с витрины")
            if recipe and user.get("plan_code") == "restaurant":
                _require(settings["general"]["fractional"] or quantity.is_integer(), "Блюда по заказу продаются целыми порциями")
                requirements = recipe_requirements(recipe, quantity)
                _require(requirements and any(requirements.values()), f"Заполните состав техкарты: {recipe['name']}")
                for ingredient_id, required in requirements.items():
                    ingredient_deductions[ingredient_id] = ingredient_deductions.get(ingredient_id, 0) + required
                    _require(ingredient_deductions[ingredient_id] <= _stock(state, branch_id, ingredient_id) + 0.000001, f"Недостаточно ингредиентов для блюда: {recipe['name']}", 409)
                    ingredient = _find(state["ingredients"], ingredient_id) or {}
                    ingredient_allocations.append({"itemId": ingredient_id, "name": ingredient.get("name", str(ingredient_id)), "unit": ingredient.get("unit", "кг"), "quantity": required, "unitCost": _cost(state, branch_id, ingredient_id)})
                unit_cost = sum(row["quantity"] * row["unitCost"] for row in ingredient_allocations) / quantity
                item = recipe
                batch_allocations = []
            elif recipe:
                _require(settings["general"]["fractional"] or quantity.is_integer(), "Блюда на раздаче продаются целыми порциями")
                required = quantity
                candidates = [batch for batch in reversed(logistics["batches"]) if batch.get("branchId") == branch_id and str(batch.get("recipeId")) == str(recipe["id"]) and batch.get("status") in {"serving", "partial"}]
                for batch in candidates:
                    custody.initialize(batch, recipe)
                eligible = [lot for batch in candidates for lot in batch["servingLots"] if custody.lot_available(lot) > 0.000001]
                selected_lot_id = raw.get("lotId")
                if not selected_lot_id and len(eligible) == 1:
                    selected_lot_id = eligible[0]["id"]
                _require(selected_lot_id or len(eligible) <= 1, f"Выберите витрину и партию: {recipe['name']}", 409)
                remaining_to_allocate = required
                line_cost = 0.0
                batch_allocations: list[dict[str, Any]] = []
                for batch in candidates:
                    capacity = sum(max(0, custody.lot_available(lot) - sum(weight for planned, weight in serving_allocations if planned["id"] == lot["id"])) for lot in batch["servingLots"] if lot["id"] == selected_lot_id) * 1000 / custody.portion_weight(batch, recipe)
                    if not settings["general"]["fractional"]:
                        capacity = floor(capacity + 1e-8)
                    allocated = min(max(0, capacity), remaining_to_allocate)
                    if allocated:
                        allocations.append((batch, allocated))
                        custody.initialize(batch, recipe)
                        pending_weight = allocated * custody.portion_weight(batch, recipe) / 1000
                        for lot in batch["servingLots"]:
                            if lot["id"] != selected_lot_id:
                                continue
                            taken = min(max(0, custody.lot_available(lot) - sum(weight for planned, weight in serving_allocations if planned["id"] == lot["id"])), pending_weight)
                            if taken > 0:
                                serving_allocations.append((lot, taken))
                                batch_allocations.append({"batchId": batch["id"], "lotId": lot["id"], "quantity": taken * 1000 / custody.portion_weight(batch, recipe), "responsibleId": lot.get("responsibleId"), "responsibleName": lot.get("responsibleName"), "line": lot.get("line"), "weight": taken})
                                batch_allocations[-1]["batchNumber"] = batch.get("number")
                                batch_allocations[-1]["productionIngredients"] = [
                                    {**row, "quantity": _number(row.get("quantity")) * taken / _number(batch["actualWeight"], minimum=0.001)}
                                    for row in batch.get("ingredientSnapshot", [])
                                ]
                                pending_weight -= taken
                            if pending_weight < 0.000001:
                                break
                        produced_portions = _number(batch.get("actualWeight")) * 1000 / custody.portion_weight(batch, recipe)
                        produced_portions = max(0.001, produced_portions) if settings["general"]["fractional"] else max(1, floor(produced_portions))
                        line_cost += allocated * custody.portion_weight(batch, recipe) / 1000 * _number(batch.get("cost")) / max(_number(batch.get("actualWeight")), 0.001)
                        remaining_to_allocate -= allocated
                    if not remaining_to_allocate:
                        break
                _require(remaining_to_allocate <= 0.000001, f"На раздаче недостаточно порций: {recipe['name']}", 409)
                item = recipe
                unit_cost = line_cost / quantity
            else:
                _require(bool(product.get("weighted")) or quantity.is_integer(), "Штучный товар продаётся целым количеством")
                _require(quantity <= _stock(state, branch_id, product["id"]), f"Недостаточно остатка: {product['name']}", 409)
                ready_deductions.append((product, quantity))
                item = product
                unit_cost = _cost(state, branch_id, product["id"])
                batch_allocations = []
            price = _number(item.get("price"))
            sale_items.append({"id": item["id"], **_station_route(state, item, branch_id), "name": item["name"], "category": item["category"], "unit": "порция" if recipe else item.get("unit", "шт"), "price": price, "unitCost": unit_cost, "quantity": quantity, "noDiscount": bool(item.get("noDiscount")), "batchAllocations": batch_allocations, "ingredientAllocations": ingredient_allocations})
            total += price * quantity
        subtotal = total
        customer = _find(pos["customers"], payload.get("customerId"))
        discount_percent = _number(customer.get("discountPercent")) if customer else 0
        _require(discount_percent <= 100, "Скидка не может быть больше 100%")
        discountable = sum(item["price"] * item["quantity"] for item in sale_items if not item.get("noDiscount"))
        discount_amount = round(discountable * discount_percent / 100, 2)
        total = round(subtotal - discount_amount, 2)
        service_percent = settings["general"]["servicePercent"] if payload.get("applyService", settings["general"]["serviceDefault"]) else 0
        service_amount = round(total * service_percent / 100, 2)
        delivery_amount = 0
        if order_details["orderType"] == "delivery":
            area = next(area for area in settings["delivery"]["areas"] if area["name"] == order_details["deliveryArea"])
            delivery_amount = 0 if area["freeFrom"] > 0 and total >= area["freeFrom"] else area["cost"]
        total = round(total + service_amount + delivery_amount, 2)
        rounding = total - floor(total) if settings["general"]["roundTotal"] else 0
        total = round(total - rounding, 2)
        payments, payment_method, received, change = normalize_sale_payments(payload, total)
        if ingredient_deductions:
            _require_unlocked(state, branch_id)
        for ingredient_id, quantity in ingredient_deductions.items():
            _set_stock(state, branch_id, ingredient_id, _stock(state, branch_id, ingredient_id) - quantity)
            _ledger(state, branch_id=branch_id, item_id=ingredient_id, quantity=-quantity, unit_cost=_cost(state, branch_id, ingredient_id), movement_type="sale_consumption", document_number="POS", actor=actor)
        for lot, weight in serving_allocations:
            lot["soldWeight"] = _number(lot.get("soldWeight")) + weight
        for batch, allocated in allocations:
            batch["soldPortions"] = _number(batch.get("soldPortions")) + allocated
            batch["servedPortions"] = batch["soldPortions"]
        for product, quantity in ready_deductions:
            _set_stock(state, branch_id, product["id"], _stock(state, branch_id, product["id"]) - quantity)
            _ledger(state, branch_id=branch_id, item_id=product["id"], quantity=-quantity, unit_cost=_cost(state, branch_id, product["id"]), movement_type="sale", document_number="POS", actor=actor)
        branch_sales = [sale for sale in state["sales"] if sale.get("branchId") == branch_id]
        sale = {**order_details, "serviceAmount": service_amount, "deliveryAmount": delivery_amount, "rounding": rounding, "currency": settings["general"]["currency"], "id": f"sale-{uuid4()}", "number": max([int(row.get("number", 0)) for row in branch_sales] or [0]) + 1, "branchId": branch_id, "branch": _find(state["branches"], branch_id)["name"], "cashier": actor, "cashierId": user.get("id"), "registerId": user.get("register_id"), "shiftId": user.get("shift_id"), "createdAt": user.get('_offline_created_at') or _now(), "paymentMethod": payment_method, "payments": payments, "subtotal": subtotal, "discountPercent": discount_percent, "discountAmount": discount_amount, "total": total, "received": received, "change": change, "customerId": customer.get("id") if customer else None, "customerName": customer.get("name") if customer else "", "comment": str(payload.get("comment", "")).strip(), "items": sale_items}
        if payload.get("requestId"):
            sale.update(requestId=str(payload["requestId"]).strip(), requestPayload=deepcopy(payload))
        sale["orderOwnerId"] = open_order.get("openedById", user.get("id")) if open_order else user.get("id")
        from .payroll import record_sale
        record_sale(state, sale, sale["orderOwnerId"])
        state["sales"].insert(0, sale)
        if open_order:
            pos["openOrders"].remove(open_order)
        if customer:
            customer["visits"] = int(_number(customer.get("visits"))) + 1
            customer["revenue"] = _number(customer.get("revenue")) + total
            customer["lastVisitAt"] = sale["createdAt"]
        return "sale", sale["id"]

    raise WorkspaceError("Неизвестное действие", 404)
