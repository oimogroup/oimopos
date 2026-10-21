"""Regression scenarios found while auditing normal stock and cash operations."""
from copy import deepcopy
import json

import pytest

from app import custody, shift_reconciliation
from app.workspace import WorkspaceError, apply_action, default_state, visible_state


MANAGER = {
    "id": 701, "login": "manager", "display_name": "Manager", "role": "branch",
    "branch_id": "b1", "staff_role": "branch_manager", "plan_code": "canteen",
    "register_id": 801, "shift_id": 901,
}


def scenario():
    state = default_state()
    state["logisticsState"]["batches"] = []
    state["logisticsState"]["branchStocks"]["b1"]["rice"] = 10
    recipe = state["recipes"][0]
    recipe["yield"] = 250
    recipe["components"] = [{"ingredientId": "rice", "gross": 250, "net": 250}]
    return state, recipe


def request_for(action, recipe):
    if action == "batch.create":
        return {"recipeId": recipe["id"], "weight": 1, "requestId": "production-retry"}
    if action == "pos.cash.movement":
        return {"type": "deposit", "amount": 1000, "requestId": "cash-retry"}
    return {
        "supplierId": "supplier-frunze", "invoiceNumber": "RETRY-1",
        "items": [{"itemId": "rice", "quantity": 2, "price": 100}],
        "payments": [{"accountId": "finance-cash-b1", "amount": 100}],
        "requestId": "supply-retry",
    }


@pytest.mark.parametrize("action", ["batch.create", "pos.cash.movement", "supply.create"])
def test_repeated_stock_cash_request_survives_reload_without_duplicate_effects(action):
    state, recipe = scenario()
    payload = request_for(action, recipe)
    result = apply_action(state, MANAGER, action, payload)
    # Simulate a lost successful response followed by another process loading JSONB.
    state = json.loads(json.dumps(state))
    before = deepcopy(state)
    assert apply_action(state, {**MANAGER, "shift_id": 902}, action, deepcopy(payload)) == result
    assert state == before
    if action == "batch.create":
        assert len(state["logisticsState"]["batches"]) == 1
        assert state["logisticsState"]["branchStocks"]["b1"]["rice"] == 9
    elif action == "pos.cash.movement":
        assert len(state["posState"]["cashMovements"]) == 1
        assert sum(row["amount"] for row in state["financeState"]["transactions"]) == 1000
    else:
        assert len(state["logisticsState"]["supplies"]) == 1
        assert state["logisticsState"]["branchStocks"]["b1"]["rice"] == 12
        assert len(state["financeState"]["transactions"]) == 1
        assert len(state["posState"]["cashMovements"]) == 1
        supply = state["logisticsState"]["supplies"][0]
        assert supply["debt"] == 100
        assert state["financeState"]["transactions"][0]["paymentId"] == supply["payments"][0]["id"]


@pytest.mark.parametrize("action", ["batch.create", "pos.cash.movement", "supply.create"])
def test_reused_request_rejects_changed_payload_actor_branch_or_register(action):
    state, recipe = scenario()
    payload = request_for(action, recipe)
    apply_action(state, MANAGER, action, payload)
    before = deepcopy(state)
    with pytest.raises(WorkspaceError) as error:
        apply_action(state, MANAGER, action, {**payload, "comment": "Different operation"})
    assert error.value.status_code == 409
    for changed in ({"id": 702}, {"branch_id": "b2"}, {"register_id": 802}):
        with pytest.raises(WorkspaceError) as error:
            apply_action(state, {**MANAGER, **changed}, action, payload)
        assert error.value.status_code == 403
    assert state == before


@pytest.mark.parametrize("action", ["batch.create", "pos.cash.movement", "supply.create"])
@pytest.mark.parametrize("request_id", [None, "", " " * 2, "x" * 81, 123])
def test_invalid_supplied_request_id_does_not_change_accounting(action, request_id):
    state, recipe = scenario()
    before = deepcopy(state)
    with pytest.raises(WorkspaceError) as error:
        apply_action(state, MANAGER, action, {**request_for(action, recipe), "requestId": request_id})
    assert error.value.status_code == 422
    assert state == before


def accepted_batch(weight, portion_weight):
    state, recipe = scenario()
    recipe["yield"] = portion_weight
    _, batch_id = apply_action(state, MANAGER, "batch.create", {"recipeId": recipe["id"], "weight": weight})
    apply_action(state, MANAGER, "batch.serve", {"recipeId": recipe["id"], "weight": weight, "requestId": "send"})
    document = next(row for row in state["logisticsState"]["custodyDocuments"] if row["kind"] == "transfer")
    apply_action(state, MANAGER, "pos.receiving.accept", {"documentId": document["id"], "actualWeight": weight, "requestId": "accept"})
    batch = next(row for row in state["logisticsState"]["batches"] if row["id"] == batch_id)
    return state, recipe, batch


def test_all_displayed_whole_portions_can_be_sold_without_phantom_shortage():
    state, recipe, batch = accepted_batch(1.005, 335)
    available = next(row for row in visible_state(state, MANAGER)["recipes"] if row["id"] == recipe["id"])["availableLots"]
    assert available[0]["available"] == 3
    apply_action(state, MANAGER, "sale.create", {
        "items": [{"id": recipe["id"], "quantity": 3}], "paymentMethod": "card", "requestId": "pay",
    })
    assert custody.lot_available(batch["servingLots"][0]) == 0
    assert sum(row["weight"] for row in state["sales"][0]["items"][0]["batchAllocations"]) == pytest.approx(1.005)
    with pytest.raises(WorkspaceError):
        apply_action(state, MANAGER, "sale.create", {
            "items": [{"id": recipe["id"], "quantity": 1}], "paymentMethod": "card", "requestId": "oversell",
        })


def test_approved_surplus_survives_truthful_close_and_next_shift_acceptance():
    state, _, batch = accepted_batch(1, 250)
    lot = batch["servingLots"][0]
    _, document_id = apply_action(state, MANAGER, "pos.serving.surplus", {
        "batchId": batch["id"], "lotId": lot["id"], "weight": 2,
        "reason": "Found unrecorded cooked stock", "requestId": "surplus",
    })
    apply_action(state, MANAGER, "custody.review", {
        "documentId": document_id, "decision": "approve", "reason": "Count checked", "requestId": "review",
    })
    assert custody.lot_balance(lot) == 3
    counts = [{**row, "actualWeight": row["expectedWeight"]} for row in shift_reconciliation.serving_rows(state, MANAGER)]
    shift_reconciliation.close_serving(state, MANAGER, counts, True)
    assert custody.lot_available(lot) == 0
    handover_id = lot["handoverId"]
    next_cashier = {**MANAGER, "id": 702, "shift_id": 902}
    with pytest.raises(WorkspaceError):
        apply_action(state, next_cashier, "pos.receiving.accept", {
            "documentId": handover_id, "actualWeight": 4, "reason": "Unexpected new stock", "requestId": "too-much",
        })
    apply_action(state, next_cashier, "pos.receiving.accept", {
        "documentId": handover_id, "actualWeight": 3, "requestId": "next-accept",
    })
    assert custody.lot_available(lot) == 3
    assert lot["responsibleId"] == next_cashier["id"]
    assert lot["acceptedShiftId"] == 902
