"""The catalog export must also be a supported import template."""
from app.technical_card_import import preview
from app.technical_card_report import workbook


def test_workbook_roundtrip_preserves_card_metadata_and_components():
    ingredient = {"id": "flour", "name": "Мука", "unit": "кг", "averageCost": 50}
    card = {"name": "Тесто", "category": "Кухня", "station": "Горячий цех",
            "yield": 900, "price": 150,
            "components": [{"ingredientId": "flour", "gross": 1000, "net": 900}]}
    preparation = {**card, "process": "Замесить", "usedIn": "Выпечка"}
    result = preview({"ingredients": [ingredient]}, workbook([card], [preparation], {"flour": ingredient}), "catalog.xlsx")
    assert len(result["rows"]) == 2
    for row in result["rows"]:
        assert row["card"] == card["name"]
        assert row["category"] == card["category"]
        assert row["station"] == card["station"]
        assert row["yield"] == 900
        assert row["price"] == 150
        assert (row["ingredientId"], row["gross"], row["net"]) == ("flour", 1, .9)
    assert result["rows"][1]["process"] == "Замесить"
    assert result["rows"][1]["usedIn"] == "Выпечка"


def test_import_accepts_500_catalog_positions():
    ingredient = {"id": "flour", "name": "Мука", "unit": "кг"}
    cards = [{"name": f"Карта {index}", "category": "Кухня", "station": "Кухня",
              "yield": 900, "price": 150,
              "components": [{"ingredientId": "flour", "gross": 1000, "net": 900}]}
             for index in range(500)]
    result = preview({"ingredients": [ingredient]}, workbook(cards, [], {"flour": ingredient}), "catalog.xlsx")
    assert len(result["rows"]) == 500
    assert len({row["card"] for row in result["rows"]}) == 500
    assert all(row["ingredientId"] == "flour" for row in result["rows"])
