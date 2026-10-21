from copy import deepcopy

import pytest

from app.workspace import WorkspaceError, apply_action, default_state
from test_workspace import BRANCH, OWNER, POS_MANAGER


def paid_supply(account="finance-bank", amount=100):
    state = default_state()
    _, key = apply_action(state, POS_MANAGER, "supply.create", {
        "supplierId": "supplier-frunze", "items": [{"itemId": "rice", "quantity": 1, "price": 100}],
        "payments": [{"accountId": account, "amount": amount}],
    })
    supply = next(s for s in state["logisticsState"]["supplies"] if s["id"] == key)
    payload = {"id": key, "paymentId": supply["payments"][0]["id"], "accountId": "finance-bank",
               "reason": "Ошибочная оплата", "requestId": "reverse-test"}
    return state, supply, payload


def test_reversal_restores_debt_and_balance_preserving_stock_and_original_expense():
    state, supply, payload = paid_supply()
    stock = deepcopy(state["logisticsState"]["branchStocks"])
    ledger = deepcopy(state["logisticsState"]["stockLedger"])
    expense = deepcopy(state["financeState"]["transactions"][0])
    apply_action(state, OWNER, "supply.payment.reverse", payload)
    assert supply["paidTotal"] == 0 and supply["debt"] == 100 and supply["paymentStatus"] == "unpaid"
    assert supply["payments"][0]["amount"] == 100
    assert supply["payments"][0]["reversalReason"] == payload["reason"]
    assert state["financeState"]["transactions"][1] == expense
    assert sum(t["amount"] * (1 if t["type"] == "income" else -1) for t in state["financeState"]["transactions"]) == 0
    assert state["logisticsState"]["branchStocks"] == stock
    assert state["logisticsState"]["stockLedger"] == ledger
    assert supply["paymentReversals"][0]["createdById"] == OWNER["id"]
    with pytest.raises(WorkspaceError, match="связана с документом"):
        apply_action(state, OWNER, "finance.transaction.delete", {"id": state["financeState"]["transactions"][0]["id"]})


def test_reversal_retry_is_idempotent_but_conflicting_reuse_and_second_reversal_fail():
    state, supply, payload = paid_supply()
    apply_action(state, OWNER, "supply.payment.reverse", payload)
    before = deepcopy(state)
    apply_action(state, OWNER, "supply.payment.reverse", payload)
    assert state == before
    for extra in [{"reason": "Другая причина"}, {"accountId": "finance-safe"}, {"requestId": "second"}]:
        with pytest.raises(WorkspaceError):
            apply_action(state, OWNER, "supply.payment.reverse", {**payload, **extra})
        assert state == before


def test_new_payment_after_reversal_can_settle_supplier_again():
    state, supply, payload = paid_supply(amount=40)
    apply_action(state, OWNER, "supply.pay", {"id": supply["id"], "amount": 60, "accountId": "finance-bank", "requestId": "pay60"})
    apply_action(state, OWNER, "supply.payment.reverse", payload)
    assert supply["paidTotal"] == 60 and supply["debt"] == 40 and supply["paymentStatus"] == "partial"
    apply_action(state, OWNER, "supply.pay", {"id": supply["id"], "amount": 40, "accountId": "finance-bank", "requestId": "pay40"})
    assert supply["paymentStatus"] == "paid" and supply["debt"] == 0
    assert len(supply["payments"]) == 3


@pytest.mark.parametrize("extra", [{"reason": ""}, {"reason": " "}, {"requestId": ""},
                                  {"accountId": "missing"}, {"accountId": "finance-cash-b1"},
                                  {"accountId": "foreign"}, {"paymentId": "missing"}])
def test_invalid_reversal_does_not_change_accounting(extra):
    state, supply, payload = paid_supply()
    state["financeState"]["accounts"].append({"id": "foreign", "status": "active", "type": "bank", "branchId": "b2"})
    before = deepcopy(state)
    with pytest.raises(WorkspaceError):
        apply_action(state, OWNER, "supply.payment.reverse", {**payload, **extra})
    assert state == before


def test_branch_even_with_company_write_cannot_reverse_payment():
    state, supply, payload = paid_supply()
    before = deepcopy(state)
    with pytest.raises(WorkspaceError) as error:
        apply_action(state, {**BRANCH, "_company_write": True}, "supply.payment.reverse", payload)
    assert error.value.status_code == 403 and state == before


def test_cash_refund_to_safe_leaves_original_cash_shift_unchanged():
    state, supply, payload = paid_supply(account="finance-cash-b1")
    cash = deepcopy(state["posState"]["cashMovements"])
    apply_action(state, OWNER, "supply.payment.reverse", {**payload, "accountId": "finance-safe"})
    assert state["posState"]["cashMovements"] == cash
    assert state["financeState"]["transactions"][0]["accountId"] == "finance-safe"
    assert supply["debt"] == 100


def test_legacy_payment_without_finance_payment_link_can_be_reversed():
    state, supply, payload = paid_supply()
    state["financeState"]["transactions"][0].pop("paymentId")
    apply_action(state, OWNER, "supply.payment.reverse", payload)
    assert supply["debt"] == 100
