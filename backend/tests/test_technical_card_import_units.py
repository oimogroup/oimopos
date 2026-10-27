import base64
import pytest
from app.technical_card_import import prepare_import, preview
from app.technical_card_report import workbook


def row(**updates):
    return {"card": "Тесто", "kind": "полуфабрикат", "station": "Кухня", "yield": 800,
            "ingredientId": "raw", "ingredient": "Сырьё", "gross": 1, "net": .8, "unit": "кг", **updates}


@pytest.mark.parametrize('unit,target,gross,expected', [('кг','кг',.005,5), ('г','кг',5,5), ('л','л',.02,20), ('мл','л',20,20), ('шт','шт',.5,500), ('','кг',5,5)])
def test_units_convert_to_workspace_quantities(unit,target,gross,expected):
    result = prepare_import({"ingredients":[{"id":"raw","unit":target}]}, [row(unit=unit,gross=gross,net=gross)])
    assert result[0]['components'][0]['gross'] == expected


def test_duplicates_merge_before_save():
    result = prepare_import({"ingredients":[{"id":"raw","unit":"кг"}]}, [row(), row(gross=.5,net=.4)])
    assert result[0]['components'] == [{'ingredientId':'raw','gross':1500,'net':1200}]


@pytest.mark.parametrize('updates', [{'station':''}, {'ingredientId':''}, {'unit':'л'}, {'net':2}, {'gross':float('inf')}])
def test_invalid_rows_rejected(updates):
    with pytest.raises(ValueError):
        prepare_import({'ingredients':[{'id':'raw','unit':'кг'}]}, [row(**updates)])


def test_export_import_keeps_piece_volume_mass_and_cost():
    ingredients = [{'id':'mass','name':'Мука','unit':'кг','averageCost':100},
                   {'id':'volume','name':'Масло','unit':'л','averageCost':200},
                   {'id':'pieces','name':'Яйцо','unit':'шт','averageCost':10}]
    card = {'name':'Смесь','station':'Кухня','yield':700,'components':[
        {'ingredientId':i['id'],'gross':q,'net':q} for i,q in zip(ingredients,[500,20,500])]}
    state = {'ingredients':ingredients}
    data = preview(state, workbook([], [card], {i['id']:i for i in ingredients}), 'cards.xlsx')
    assert prepare_import(state, data['rows'])[0]['components'] == card['components']


def test_missing_yield_is_sum_of_net_and_missing_net_defaults_to_gross():
    result = prepare_import({'ingredients':[{'id':'raw','unit':'кг'}]}, [row(**{'yield':None,'net':None})])
    assert result[0]['yield'] == 1000
    assert result[0]['components'][0]['net'] == 1000


def test_automatic_yield_uses_piece_weight_and_volume_default():
    state = {'ingredients':[{'id':'egg','unit':'шт'}, {'id':'milk','unit':'л'}]}
    items = [row(**{'ingredientId':'egg','unit':'шт','gross':2,'net':None,'yield':None,'pieceWeightGrams':50}),
             row(**{'ingredientId':'milk','unit':'л','gross':.2,'net':None,'yield':None})]
    assert prepare_import(state, items)[0]['yield'] == 300


def test_piece_weight_required_only_when_yield_is_automatic():
    state = {'ingredients':[{'id':'raw','unit':'шт'}]}
    with pytest.raises(ValueError, match='массу штуки'):
        prepare_import(state, [row(**{'unit':'шт','yield':None})])
    assert prepare_import(state, [row(unit='шт')])[0]['yield'] == 800


def test_csv_without_net_column_uses_gross():
    data = 'Карта;Вид;Ингредиент;Брутто;Ед.;Цех\nТесто;полуфабрикат;Мука;0,5;кг;Кухня'
    state = {'ingredients':[{'id':'raw','name':'Мука','unit':'кг'}]}
    rows = preview(state, base64.b64encode(data.encode()).decode(), 'test.csv')['rows']
    assert rows[0]['net'] == .5
    assert prepare_import(state, rows)[0]['yield'] == 500
