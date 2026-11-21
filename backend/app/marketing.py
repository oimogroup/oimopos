"""Customer directory and discount groups shared by management and POS."""
import re
from uuid import uuid4
from datetime import datetime, timezone


def phone_key(value):
    return re.sub(r"\D", "", str(value or ""))


def discount(state, customer):
    if not customer or customer.get("archivedAt"):
        return 0
    personal = customer.get("personalDiscountPercent", customer.get("discountPercent", 0))
    if personal is not None:
        return float(personal)
    group = next((g for g in state.get("posState", {}).get("customerGroups", []) if g["id"] == customer.get("groupId") and not g.get("archivedAt")), {})
    return float(group.get("discountPercent", 0))


def apply(state, user, action, payload):
    from .workspace import WorkspaceError
    def require(condition, message, status=400):
        if not condition:
            raise WorkspaceError(message, status)
    require(user.get("role") == "owner", "Маркетинг доступен администратору компании", 403)
    pos = state.setdefault("posState", {})
    customers = pos.setdefault("customers", [])
    groups = pos.setdefault("customerGroups", [])
    now = datetime.now(timezone.utc).isoformat()
    def percent(value):
        require(isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100, "Скидка должна быть от 0 до 100%")
        return round(value, 2)
    def entry(rows):
        row = next((r for r in rows if r["id"] == payload.get("id")), None)
        if row:
            require(not row.get("archivedAt"), "Запись находится в архиве", 409)
            require(payload.get("expectedRevision") == row.get("editRevision"), "Запись изменена другим сотрудником. Обновите страницу", 409)
        return row
    if action == "marketing.exclusion.update":
        require(payload.get("kind") in {"product", "recipe"}, "Выберите товар или техкарту")
        row = next((r for r in state[payload["kind"] + "s"] if str(r["id"]) == str(payload.get("id"))), None)
        require(row, "Позиция не найдена", 404)
        from .catalog_saves import revision
        require(payload.get("expectedRevision") == revision(state, payload["kind"] + ".upsert", row["id"]), "Позиция изменена. Обновите страницу", 409)
        require(isinstance(payload.get("noDiscount"), bool), "Укажите исключение")
        row.update(noDiscount=payload["noDiscount"])
        return "marketing_exclusion", str(row["id"])
    is_group = action.startswith("marketing.group.")
    rows = groups if is_group else customers
    row = entry(rows)
    if action.endswith(".archive"):
        require(row, "Запись не найдена", 404)
        if is_group:
            require(not any(c.get("groupId") == row["id"] and not c.get("archivedAt") for c in customers), "Сначала перенесите клиентов из этой группы", 409)
        row.update(archivedAt=now, updatedBy=user["display_name"], editRevision=str(uuid4()))
        return "customer_group" if is_group else "pos_customer", row["id"]
    require(action in {"marketing.group.upsert", "marketing.customer.upsert"}, "Неизвестное действие", 404)
    name = str(payload.get("name", "")).strip()
    require(0 < len(name) <= 150, "Укажите имя или название до 150 символов")
    values = {"name": name}
    if is_group:
        require(not any(g is not row and not g.get("archivedAt") and g["name"].casefold() == name.casefold() for g in groups), "Группа уже существует", 409)
        values["discountPercent"] = percent(payload.get("discountPercent", 0))
    else:
        phone = str(payload.get("phone", "")).strip()
        require(7 <= len(phone_key(phone)) <= 15, "Укажите корректный телефон гостя")
        require(not any(c is not row and phone_key(c.get("phone")) == phone_key(phone) for c in customers), "Гость с таким телефоном уже существует, включая архив", 409)
        group_id = payload.get("groupId") or None
        require(not group_id or any(g["id"] == group_id and not g.get("archivedAt") for g in groups), "Группа не найдена")
        personal = payload.get("personalDiscountPercent")
        personal = None if personal is None else percent(personal)
        require(group_id or personal is not None, "Выберите группу или укажите персональную скидку")
        comment = str(payload.get("comment", "")).strip()
        require(len(comment) <= 1000, "Комментарий слишком длинный")
        values.update(phone=phone, groupId=group_id, personalDiscountPercent=personal, comment=comment)
        values["discountPercent"] = discount(state, values)
    if row is None:
        row = {"id": str(payload.get("id") or uuid4()), "createdAt": now, "createdBy": user["display_name"]}
        require(len(row["id"]) <= 150, "Некорректный идентификатор")
        rows.insert(0, row)
    row.update(values, updatedAt=now, updatedBy=user["display_name"], editRevision=str(uuid4()))
    return "customer_group" if is_group else "pos_customer", row["id"]
