import base64
from custody_helpers import accepted_transfer
from copy import deepcopy

import pytest

from app.company_settings import company_settings, validate_settings_section
from app.main import _authorize_staff_action
from app.workspace import WorkspaceError, apply_action, default_state, visible_state

OWNER = {"id": 1, "login": "owner", "role": "owner", "display_name": "Owner"}
CASHIER = {"id": 2, "login": "cashier", "role": "branch", "branch_id": "b1", "staff_role": "cashier", "display_name": "Cashier", "register_id": 1, "shift_id": 1}
MANAGER = {**CASHIER, "staff_role": "branch_manager"}


def update(state, section, **values):
    current = company_settings(state)[section]
    apply_action(state, OWNER, "settings.update", {"section": section, "values": {**current, **values}})


def test_settings_are_isolated_and_other_sections_are_preserved():
    state = default_state()
    other = deepcopy(state)
    update(state, "general", companyName="Кофейня", currency="KZT")
    update(state, "receipt", showNumber=False)
    assert company_settings(state)["general"]["companyName"] == "Кофейня"
    assert company_settings(state)["receipt"]["showNumber"] is False
    assert "companySettings" not in other
    assert visible_state(state, CASHIER)["companySettings"]["general"]["currency"] == "KZT"


def test_cashier_cannot_change_company_settings():
    with pytest.raises(Exception) as denied:
        _authorize_staff_action(CASHIER, "settings.update")
    assert denied.value.status_code == 403
    with pytest.raises(WorkspaceError):
        apply_action(default_state(), CASHIER, "settings.update", {"section": "general", "values": {}})


@pytest.mark.parametrize("section, values", [
    ("general", {"timezone": "Not/AZone"}), ("general", {"shiftEnd": "25:00"}),
    ("general", {"currency": "invalid"}), ("general", {"servicePercent": -5}),
    ("general", {"logo": "data:image/svg+xml;base64,PHN2Zz4="}),
    ("orders", {"dineIn": False, "takeaway": False}),
    ("orders", {"tables": ["1", "1"]}), ("security", {"refund": "allow_everyone"}),
    ("receipt", {"unknown": True}), ("delivery", {"areas": [{"name": "Town", "cost": -1}]}),
])
def test_invalid_settings_rejected(section, values):
    with pytest.raises(ValueError):
        validate_settings_section(section, values)


def test_webp_company_logo_is_accepted():
    webp = base64.b64encode(b"RIFF\x00\x00\x00\x00WEBP").decode("ascii")
    settings = validate_settings_section("general", {"logo": f"data:image/webp;base64,{webp}"})
    assert settings["logo"].startswith("data:image/webp;base64,")


def test_rounding_service_delivery_are_calculated_by_server():
    state = default_state()
    product = state["products"][0]
    product["price"] = 10.6
    state["logisticsState"]["branchStocks"]["b1"][product["id"]] = 10
    update(state, "general", servicePercent=10, serviceDefault=True, roundTotal=True, currency="KZT")
    update(state, "delivery", enabled=True, areas=[{"name": "Центр", "cost": 5.0, "freeFrom": 100.0, "minutes": 60}])
    apply_action(state, CASHIER, "sale.create", {"orderType": "delivery", "deliveryArea": "Центр", "deliveryAddress": "Дом 1", "deliveryPhone": "123", "paymentMethod": "card", "items": [{"id": product["id"], "quantity": 1}], "total": 1, "serviceAmount": 0})
    sale = state["sales"][0]
    assert sale["total"] == 16
    assert sale["serviceAmount"] == 1.06
    assert sale["deliveryAmount"] == 5
    assert sale["rounding"] == pytest.approx(0.66)
    assert sale["currency"] == "KZT"


def test_security_setting_blocks_cashier_but_allows_manager():
    state = default_state()
    update(state, "security", addCustomer="always")
    with pytest.raises(WorkspaceError) as denied:
        apply_action(state, CASHIER, "pos.customer.upsert", {"name": "Guest", "phone": "123"})
    assert denied.value.status_code == 403
    apply_action(state, MANAGER, "pos.customer.upsert", {"name": "Guest", "phone": "123"})
    assert state["posState"]["customers"][0]["name"] == "Guest"


def test_delivery_status_changes_follow_configuration():
    state = default_state()
    update(state, "delivery", enabled=True, useReadyStatus=False, useDeliveredStatus=True, areas=[{"name": "Town", "cost": 0.0, "freeFrom": 0.0, "minutes": 30}])
    _, order_id = apply_action(state, CASHIER, "pos.order.save", {"orderType": "delivery", "deliveryArea": "Town", "deliveryAddress": "Road 1", "deliveryPhone": "123", "items": [{"id": state["products"][0]["id"], "quantity": 1}]})
    with pytest.raises(WorkspaceError):
        apply_action(state, CASHIER, "pos.order.status", {"id": order_id, "status": "ready"})
    apply_action(state, CASHIER, "pos.order.status", {"id": order_id, "status": "en-route"})
    apply_action(state, CASHIER, "pos.order.status", {"id": order_id, "status": "delivered"})
    assert state["posState"]["openOrders"][0]["status"] == "delivered"


def test_fractional_recipe_refund_does_not_return_food_without_count():
    state = default_state()
    apply_action(state, MANAGER, "batch.create", {"recipeId": 201, "weight": 0.76})
    batch = state["logisticsState"]["batches"][0]
    accepted_transfer(state, MANAGER, {"id": batch["id"], "weight": 0.76})
    update(state, "general", fractional=True)
    _, sale_id = apply_action(state, MANAGER, "sale.create", {"paymentMethod": "card", "items": [{"id": 201, "quantity": 0.5}]})
    assert batch["soldPortions"] == 0.5
    apply_action(state, MANAGER, "sale.refund", {"id": sale_id, "reason": "Проверка"})
    assert batch["soldPortions"] == 0.5


def test_fractional_sales_are_preserved_in_custody_count():
    state = default_state()
    apply_action(state, MANAGER, "batch.create", {"recipeId": 201, "weight": 0.76})
    batch = state["logisticsState"]["batches"][0]
    accepted_transfer(state, MANAGER, {"id": batch["id"], "weight": 0.76})
    update(state, "general", fractional=True)
    apply_action(state, MANAGER, "sale.create", {"paymentMethod": "card", "items": [{"id": 201, "quantity": 0.5}]})
    apply_action(state, MANAGER, "custody.count", {"batchId": batch["id"], "lotId": batch["servingLots"][0]["id"], "actualWeight": 0.57, "expectedWeight": 0.57, "requestId":"fractional-count"})
    assert batch["servedPortions"] == 0.5
    assert state["logisticsState"]["custodyDocuments"][0]["variance"] == pytest.approx(0)
