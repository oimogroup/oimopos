"""Compensating supplier refunds: preserve the payment and restore the debt."""
from uuid import uuid4


def reverse(state, user, payload):
    from .workspace import _ensure_finance, _find, _money, _next_number, _now, _require

    _require(user.get("role") == "owner", "Отмена оплаты доступна владельцу компании", 403)
    supply = _find(state["logisticsState"]["supplies"], payload.get("id"))
    _require(supply is not None, "Поставка не найдена", 404)
    payment = _find(supply.get("payments", []), payload.get("paymentId"))
    _require(payment is not None, "Платёж не найден", 404)
    request_id = str(payload.get("requestId") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    account_id = str(payload.get("accountId") or payment["accountId"])
    _require(0 < len(request_id) <= 200, "Не указан идентификатор отмены")
    previous = next((r for r in supply.get("paymentReversals", []) if r["requestId"] == request_id), None)
    if previous:
        _require(previous["paymentId"] == payment["id"] and previous["accountId"] == account_id
                 and previous["reason"] == reason and str(previous["createdById"]) == str(user["id"]),
                 "Идентификатор уже использован для другой отмены", 409)
        return "supplier_receipt", supply["id"]
    _require(not payment.get("reversedAt"), "Платёж уже отменён", 409)
    _require(3 <= len(reason) <= 1000, "Укажите причину отмены (от 3 до 1000 символов)")
    finance = _ensure_finance(state)
    account = _find(finance["accounts"], account_id)
    _require(account and account.get("status") == "active", "Выберите активный счёт возврата")
    _require(not account.get("branchId") or str(account["branchId"]) == str(supply["branchId"]),
             "Счёт относится к другому заведению", 403)
    _require(account.get("type") != "cash",
             "Для возврата выберите сейф или банковский счёт. Наличные в кассу внесите через открытую смену", 409)
    amount = _money(payment["amount"])
    _require(0 < amount <= _money(supply.get("paidTotal", 0)), "Проверьте сумму проведённых оплат", 409)
    now = _now()
    reversal_id = f"supply-payment-reversal-{uuid4()}"
    category_id = "finance-income-supplier-refunds"
    if not _find(finance["categories"], category_id):
        finance["categories"].append({"id": category_id, "name": "Возвраты оплат поставщикам", "kind": "income", "status": "active"})
    reversal = {
        "id": reversal_id, "requestId": request_id, "paymentId": payment["id"],
        "accountId": account_id, "amount": amount, "reason": reason,
        "occurredAt": now, "createdBy": user["display_name"], "createdById": user["id"],
    }
    supply.setdefault("paymentReversals", []).append(reversal)
    payment.update({"reversedAt": now, "reversedBy": user["display_name"], "reversalId": reversal_id, "reversalReason": reason})
    supply["paidTotal"] = _money(supply["paidTotal"] - amount)
    supply["debt"] = _money(supply["total"] - supply["paidTotal"])
    supply["paymentStatus"] = "unpaid" if supply["paidTotal"] == 0 else "partial" if supply["debt"] else "paid"
    finance["transactions"].insert(0, {
        "id": f"finance-transaction-{uuid4()}", "number": _next_number("ФО", finance["transactions"]),
        "type": "income", "amount": amount, "occurredAt": now,
        "accountId": account_id, "destinationAccountId": None, "categoryId": category_id,
        "branchId": supply["branchId"], "counterparty": supply["supplier"],
        "comment": f"Отмена оплаты поставки {supply['number']}: {reason}",
        "documentId": supply["id"], "paymentId": payment["id"], "reversalId": reversal_id,
        "automatic": True, "createdAt": now, "createdBy": user["display_name"],
    })
    return "supplier_receipt", supply["id"]
