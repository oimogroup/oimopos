"""Cross-operation stock conservation regressions from the accounting audit."""
from copy import deepcopy

import pytest

from app import custody, sales_import
from app.inventory_count import build
from app.workspace import WorkspaceError, _cost, _set_stock, _stock, apply_action, default_state
from test_accounting_readiness_regressions import MANAGER, accepted_batch


OWNER = {"id": 1, "role": "owner", "display_name": "Owner"}


@pytest.mark.parametrize("opening_quantity", [2, 5])
def test_product_refund_preserves_stock_value_after_a_new_receipt(opening_quantity):
    state = default_state()
    _set_stock(state, "b1", "p-1", opening_quantity, 10)
    apply_action(state, MANAGER, "sale.create", {
        "items": [{"id": "p-1", "quantity": 2}], "paymentMethod": "card",
        "requestId": "original-sale",
    })
    sale = state["sales"][0]
    apply_action(state, MANAGER, "supply.create", {
        "supplierId": "supplier-frunze", "requestId": "new-cost",
        "items": [{"itemId": "p-1", "quantity": 3, "price": 30}],
    })
    value_before = _stock(state, "b1", "p-1") * _cost(state, "b1", "p-1")
    apply_action(state, MANAGER, "sale.refund", {"id": sale["id"], "reason": "Returned unopened goods"})
    quantity = _stock(state, "b1", "p-1")
    assert quantity == opening_quantity + 3
    assert quantity * _cost(state, "b1", "p-1") == pytest.approx(value_before + 20)
    assert state["logisticsState"]["stockLedger"][0]["unitCost"] == 10
    before = deepcopy(state)
    with pytest.raises(WorkspaceError, match="возврат уже"):
        apply_action(state, MANAGER, "sale.refund", {"id": sale["id"], "reason": "Duplicate refund"})
    assert state == before
    apply_action(state, MANAGER, "sale.create", {
        "items": [{"id": "p-1", "quantity": 1}], "paymentMethod": "card",
        "requestId": "sale-after-refund",
    })
    assert state["sales"][0]["items"][0]["unitCost"] == pytest.approx((value_before + 20) / quantity)


def pending_surplus():
    state, recipe, batch = accepted_batch(1, 250)
    lot = batch["servingLots"][0]
    _, document_id = apply_action(state, MANAGER, "pos.serving.surplus", {
        "batchId": batch["id"], "lotId": lot["id"], "weight": 1,
        "reason": "Found one unrecorded kilogram", "requestId": "pending-surplus",
    })
    return state, batch, lot, document_id


@pytest.mark.parametrize("action", ["custody.count", "custody.handover", "inventory.start"])
def test_pending_surplus_cannot_be_counted_again_before_approval(action):
    state, batch, lot, document_id = pending_surplus()
    payload = {"batchId": batch["id"], "lotId": lot["id"], "expectedWeight": 1,
               "actualWeight": 2, "reason": "Physical stock count", "requestId": "count-again"}
    actor = MANAGER
    if action == "inventory.start":
        payload = {"scope": "serving"}
    elif action == "custody.handover":
        actor = {**MANAGER, "_custody_recipient": {"id": 702, "name": "Next cashier", "branchId": "b1"}}
        payload["recipientId"] = 702
    before = deepcopy(state)
    with pytest.raises(WorkspaceError, match="излиш"):
        apply_action(state, actor, action, payload)
    assert state == before
    apply_action(state, MANAGER, "custody.review", {
        "documentId": document_id, "decision": "approve", "reason": "Physical count checked",
        "requestId": "approve-surplus",
    })
    _, inventory_id = apply_action(state, MANAGER, "inventory.start", {"scope": "serving"})
    apply_action(state, MANAGER, "inventory.submit", {
        "id": inventory_id, "items": [{"itemId": "lot:" + lot["id"], "actual": 2}],
    })
    apply_action(state, OWNER, "inventory.post", {"id": inventory_id})
    assert custody.lot_balance(lot) == 2


def test_serving_inventory_never_reopens_a_closed_batch():
    state, _, closed_batch = accepted_batch(1, 250)
    lot = closed_batch["servingLots"][0]
    apply_action(state, MANAGER, "sale.create", {
        "items": [{"id": closed_batch["recipeId"], "quantity": 4}],
        "paymentMethod": "card", "requestId": "sell-remaining",
    })
    apply_action(state, MANAGER, "custody.close", {
        "batchId": closed_batch["id"], "reason": "All portions were sold", "requestId": "close-batch",
    })
    before = deepcopy(closed_batch)
    items, _ = build(state, "b1", {"scope": "serving"}, [])
    assert not items
    with pytest.raises(WorkspaceError, match="Нет позиций"):
        apply_action(state, MANAGER, "inventory.start", {"scope": "serving"})
    assert closed_batch == before
    assert custody.lot_balance(lot) == 0


@pytest.mark.parametrize("blocked_state", ["closed", "pending_surplus"])
def test_old_serving_inventory_cannot_post_against_a_blocked_lot(blocked_state):
    state, batch, lot, _ = pending_surplus()
    if blocked_state == "closed":
        state["logisticsState"]["custodyDocuments"] = []
        lot["soldWeight"] = 1
        batch["status"] = "closed"
    # Persisted pre-fix documents must also be checked when they are posted.
    book = custody.lot_available(lot)
    state["logisticsState"]["inventories"].append({
        "id": "old-count", "number": "ИНВ-OLD", "branchId": "b1", "scope": "serving",
        "status": "submitted", "items": [{"itemId": "lot:" + lot["id"],
        "lotId": lot["id"], "batchId": batch["id"], "book": book, "currentBook": book,
        "actual": book + 1, "unitCost": 100}],
    })
    before = deepcopy(state)
    with pytest.raises(WorkspaceError, match="закрыта|излиш"):
        apply_action(state, OWNER, "inventory.post", {"id": "old-count"})
    assert state == before


def test_preexisting_handover_cannot_accept_a_pending_surplus_twice():
    state, batch, lot, surplus_id = pending_surplus()
    lot["handoverId"] = "old-handover"
    state["logisticsState"]["custodyDocuments"].append({
        "id": "old-handover", "kind": "handover", "status": "pending", "branchId": "b1",
        "batchId": batch["id"], "lotId": lot["id"], "weight": 1,
        "recipient": {"id": 702}, "actor": {"id": MANAGER["id"]},
    })
    before = deepcopy(state)
    with pytest.raises(WorkspaceError, match="излиш"):
        apply_action(state, {**MANAGER, "id": 702}, "custody.accept", {
            "documentId": "old-handover", "actualWeight": 2,
            "reason": "Physical stock includes the pending surplus", "requestId": "accept-old",
        })
    assert state == before
    with pytest.raises(WorkspaceError, match="отмените передачу"):
        apply_action(state, MANAGER, "custody.review", {
            "documentId": surplus_id, "decision": "approve",
            "reason": "Surplus checked", "requestId": "review-old",
        })
    assert state == before
    # Rejecting the duplicate surplus lets the handover record the physical
    # variance exactly once, without changing the already-sent expected weight.
    apply_action(state, MANAGER, "custody.review", {
        "documentId": surplus_id, "decision": "reject",
        "reason": "Will record the count at handover", "requestId": "reject-old",
    })
    apply_action(state, {**MANAGER, "id": 702}, "custody.accept", {
        "documentId": "old-handover", "actualWeight": 2,
        "reason": "Physical stock checked", "requestId": "accept-after-review",
    })
    assert custody.lot_balance(lot) == 2


def test_sales_import_does_not_consume_a_closed_batch_with_legacy_balance():
    state, recipe, batch = accepted_batch(1, 250)
    # Older inventory code could credit a closed batch; preserve that history,
    # but make it unavailable to imports just as it is unavailable to POS sales.
    batch["status"] = "closed"
    before = deepcopy(state)
    assert list(sales_import.lots(state, "b1", recipe)) == []
    assert state == before
