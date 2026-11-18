from copy import deepcopy

import pytest

from app.workspace import WorkspaceError, apply_action, default_state, visible_state


OWNER = {"id": 1, "role": "owner", "display_name": "Владелец"}
CASHIER = {
    "id": 2, "role": "branch", "branch_id": "b1", "staff_role": "cashier",
    "login": "cashier", "display_name": "Кассир", "register_id": 1, "shift_id": 1,
    "plan_code": "restaurant",
}
MANAGER = {**CASHIER, "staff_role": "branch_manager"}


def modifier_set(source_type="product", source_id="p-2", quantity=0.25, price=15):
    return {
        "id": "set-extras",
        "name": "Добавки",
        "selectionMode": "single",
        "required": True,
        "maxSelections": 1,
        "options": [
            {
                "id": "extra-cheese", "name": "Сыр", "sourceType": source_type,
                "sourceId": source_id, "quantity": quantity, "price": price,
            },
            {
                "id": "extra-sauce", "name": "Соус", "sourceType": "none",
                "sourceId": "", "quantity": 0, "price": 5,
            },
        ],
    }


def assign_product(state, group):
    apply_action(state, OWNER, "product.upsert", {
        "id": "p-1", "name": "Вода 0,5 л", "price": 40,
        "modifierSetIds": [group["id"]], "modifierSets": [group],
    })


def test_product_modifier_is_priced_and_deducts_source_stock_with_refund():
    state = default_state()
    state["logisticsState"]["branchStocks"]["b1"].update({"p-1": 5, "p-2": 2})
    assign_product(state, modifier_set())

    _, sale_id = apply_action(state, CASHIER, "sale.create", {
        "paymentMethod": "card",
        "items": [{
            "id": "p-1", "quantity": 2,
            "modifiers": [{"setId": "set-extras", "modifierIds": ["extra-cheese"]}],
        }],
    })

    sale = next(row for row in state["sales"] if row["id"] == sale_id)
    assert sale["total"] == 110
    assert sale["items"][0]["price"] == 55
    assert sale["items"][0]["modifiers"][0]["setName"] == "Добавки"
    assert state["logisticsState"]["branchStocks"]["b1"]["p-1"] == 3
    assert state["logisticsState"]["branchStocks"]["b1"]["p-2"] == pytest.approx(1.5)

    apply_action(state, MANAGER, "sale.refund", {"id": sale_id, "reason": "Ошибка"})
    assert state["logisticsState"]["branchStocks"]["b1"]["p-1"] == 5
    assert state["logisticsState"]["branchStocks"]["b1"]["p-2"] == pytest.approx(2)


def test_recipe_modifier_deducts_ingredient_and_is_returned_to_cashier_view():
    state = default_state()
    state["serviceMode"] = "restaurant"
    tomato = "tomato"
    group = modifier_set("ingredient", tomato, 0.02, 25)
    state["logisticsState"]["branchStocks"]["b1"][tomato] = 1
    recipe = deepcopy(state["recipes"][0])
    apply_action(state, OWNER, "recipe.upsert", {
        **recipe, "station": state["stations"][0]["name"],
        "modifierSetIds": [group["id"]], "modifierSets": [group],
    })

    _, sale_id = apply_action(state, CASHIER, "sale.create", {
        "paymentMethod": "card",
        "items": [{
            "id": recipe["id"], "quantity": 1,
            "modifiers": [{"setId": group["id"], "modifierIds": ["extra-cheese"]}],
        }],
    })

    sale = next(row for row in state["sales"] if row["id"] == sale_id)
    assert sale["total"] == recipe["price"] + 25
    assert state["logisticsState"]["branchStocks"]["b1"][tomato] == pytest.approx(0.98)
    visible = visible_state(state, CASHIER)
    visible_sale = next(row for row in visible["sales"] if row["id"] == sale_id)
    assert visible_sale["items"][0]["modifiers"] == [{"setName": "Добавки", "name": "Сыр", "price": 25}]


def test_required_selection_is_validated_and_open_orders_keep_distinct_choices():
    state = default_state()
    assign_product(state, modifier_set(source_type="none", source_id="", quantity=0, price=15))
    with pytest.raises(WorkspaceError):
        apply_action(state, CASHIER, "sale.create", {
            "paymentMethod": "card", "items": [{"id": "p-1", "quantity": 1}],
        })

    _, order_id = apply_action(state, CASHIER, "pos.order.save", {
        "items": [
            {"id": "p-1", "quantity": 1, "modifiers": [{"setId": "set-extras", "modifierIds": ["extra-cheese"]}]},
            {"id": "p-1", "quantity": 1, "modifiers": [{"setId": "set-extras", "modifierIds": ["extra-sauce"]}]},
        ],
    })
    order = next(row for row in state["posState"]["openOrders"] if row["id"] == order_id)
    assert [row["modifiers"][0]["modifierIds"] for row in order["items"]] == [["extra-cheese"], ["extra-sauce"]]

    before = deepcopy(state)
    with pytest.raises(WorkspaceError):
        apply_action(state, CASHIER, "pos.order.save", {
            "id": order_id,
            "items": [
                {"id": "p-1", "quantity": 1, "modifiers": [{"setId": "set-extras", "modifierIds": ["extra-cheese"]}]},
                {"id": "p-1", "quantity": 1, "modifiers": [{"setId": "set-extras", "modifierIds": ["extra-cheese"]}]},
            ],
        })
    assert state == before
