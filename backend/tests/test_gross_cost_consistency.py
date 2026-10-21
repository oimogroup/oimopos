"""Preparation and recipe prices must equal the raw stock actually consumed."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import main
from app.workspace import _set_stock, _stock, apply_action, default_state
from test_accounting_readiness_regressions import MANAGER


OWNER = {"id": 1, "role": "owner", "display_name": "Owner"}


@pytest.mark.parametrize("plan", ["canteen", "restaurant"])
@pytest.mark.parametrize("net", [800, 700])
def test_preparation_cost_matches_raw_consumption_with_processing_loss(plan, net):
    state = default_state()
    state["logisticsState"]["batches"] = []
    _set_stock(state, "b1", "rice", 10, 100)
    component = {"ingredientId": "rice", "gross": 1000, "net": net}
    _, preparation_id = apply_action(state, OWNER, "preparation.upsert", {
        "name": "Rice preparation", "station": "Kitchen", "yield": 800,
        "components": [component],
    })
    preparation = next(p for p in state["preparations"] if p["id"] == preparation_id)
    assert preparation["cost"] == 100
    assert preparation["yield"] == 800 and preparation["components"][0]["net"] == net
    assert _stock(state, "b1", "rice") == 10  # Saving a card never consumes stock.
    _, recipe_id = apply_action(state, OWNER, "recipe.upsert", {
        "name": "Rice portion", "station": "Kitchen", "category": "Meals", "price": 200,
        "yield": 800, "components": [component],
    })
    actor = {**MANAGER, "plan_code": plan}
    if plan == "canteen":
        _, batch_id = apply_action(state, actor, "batch.create", {
            "recipeId": recipe_id, "weight": .8, "requestId": "produce-with-loss",
        })
        batch = next(b for b in state["logisticsState"]["batches"] if b["id"] == batch_id)
        assert batch["cost"] == preparation["cost"]
        assert batch["actualWeight"] == .8 and batch["portionWeight"] == 800
        apply_action(state, actor, "batch.serve", {
            "recipeId": recipe_id, "weight": .8, "requestId": "transfer-with-loss",
        })
        document = next(d for d in state["logisticsState"]["custodyDocuments"] if d["kind"] == "transfer")
        apply_action(state, actor, "pos.receiving.accept", {
            "documentId": document["id"], "actualWeight": .8, "requestId": "accept-with-loss",
        })
    apply_action(state, actor, "sale.create", {
        "items": [{"id": recipe_id, "quantity": 1}], "paymentMethod": "card",
        "requestId": "sell-with-loss",
    })
    assert _stock(state, "b1", "rice") == 9
    movements = [row for row in state["logisticsState"]["stockLedger"] if row["itemId"] == "rice"]
    assert len(movements) == 1
    assert -movements[0]["quantity"] * movements[0]["unitCost"] == preparation["cost"]
    assert state["sales"][0]["items"][0]["unitCost"] == preparation["cost"]


def test_sql_technical_cards_use_stock_units_for_gross_and_preserve_output_yield():
    rows = {
        "catalog_items": [
            {"id": "raw", "purchase_cost": Decimal("100"), "unit": "кг"},
            {"id": "prep", "purchase_cost": Decimal("0"), "unit": "кг"},
            {"id": "dish", "purchase_cost": Decimal("0"), "unit": "порция"},
        ],
        "technical_cards": [
            {"id": 11, "output_item_id": "prep", "yield_quantity": Decimal("0.8"), "yield_weight_grams": None},
            {"id": 12, "output_item_id": "dish", "yield_quantity": Decimal("1"), "yield_weight_grams": Decimal("300")},
        ],
        "technical_card_components": [
            {"id": 21, "technical_card_id": 11, "component_item_id": "raw", "gross_quantity": Decimal("1"), "net_quantity": Decimal("0.8")},
            {"id": 22, "technical_card_id": 12, "component_item_id": "prep", "gross_quantity": Decimal("0.4"), "net_quantity": Decimal("0.3")},
        ],
    }

    class Connection:
        def execute(self, query, params):
            assert params == ("isolated-tenant",)
            table = next(name for name in rows if "FROM " + name + "\n" in query)
            return SimpleNamespace(fetchall=lambda: rows[table])

    preparation = main._card_response(Connection(), "isolated-tenant", 11)
    assert preparation["total_cost"] == Decimal("100")
    assert preparation["unit_cost"] == Decimal("125")
    assert preparation["yield_quantity"] == Decimal("0.8")
    assert preparation["components"][0]["line_cost"] == Decimal("100")
    assert preparation["components"][0]["net_quantity"] == Decimal("0.8")
    dish = main._card_response(Connection(), "isolated-tenant", 12)
    assert dish["total_cost"] == dish["unit_cost"] == Decimal("50")
    assert dish["components"][0]["unit_cost"] == Decimal("125")
    assert dish["yield_quantity"] == 1 and dish["yield_weight_grams"] == 300
