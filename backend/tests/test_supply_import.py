"""Real CSV and OOXML fixtures for non-mutating supplier document previews."""
import base64
import csv
import io
import struct
import zipfile
from copy import deepcopy
from xml.sax.saxutils import escape

import pytest

from app import supply_import
from app.supply_import import preview


STATE = {"ingredients": [{"id": "rice", "name": "Рис", "unit": "кг"},
                          {"id": "milk", "name": "Молоко", "unit": "л"}],
         "products": [{"id": "water", "name": "Вода", "unit": "шт"}],
         "logisticsState": {"branchStocks": {"b1": {"rice": 7}}, "supplies": []}}
HEADER = ["Наименование", "Количество", "Цена", "Ед. изм.", "Сумма"]
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def encoded(raw):
    return base64.b64encode(raw).decode("ascii")


def csv_preview(text, *, state=None, encoding="utf-8-sig"):
    return preview(STATE if state is None else state, encoded(text.encode(encoding)), "Поставка.csv")


def sheet(rows):
    result = [f'<worksheet xmlns="{NS}"><sheetData>']
    for number, cells in enumerate(rows, 1):
        result.append(f'<row r="{number}">')
        for column, value in enumerate(cells):
            if value is None:
                continue
            reference = f'{chr(65 + column)}{number}'
            if isinstance(value, dict):
                kind = value.get("type", "n")
                formula = f'<f>{escape(value["formula"])}</f>' if "formula" in value else ""
                cache = f'<v>{escape(str(value["value"]))}</v>' if "value" in value else ""
                result.append(f'<c r="{reference}" t="{kind}">{formula}{cache}</c>')
            elif isinstance(value, (float, int)):
                result.append(f'<c r="{reference}"><v>{value}</v></c>')
            else:
                result.append(f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        result.append('</row>')
    return ''.join(result) + '</sheetData></worksheet>'


def xlsx(sheets=None, *, strings=None, extra=None, targets=None, root_path="xl/workbook.xml"):
    sheets = sheets or [("visible", sheet([HEADER, ["Рис", 2, 10, "кг", 20]]))]
    targets = targets or [f"worksheets/data-{index}.xml" for index in range(len(sheets))]
    workbook = [f'<workbook xmlns="{NS}" xmlns:r="{REL}"><sheets>']
    relationships = [f'<Relationships xmlns="{PKG_REL}">']
    parts = {"_rels/.rels": f'<Relationships xmlns="{PKG_REL}"><Relationship Id="book" Type="{REL}/officeDocument" Target="{root_path}"/></Relationships>'}
    directory = root_path.rsplit("/", 1)[0]
    for index, ((visibility, xml), target) in enumerate(zip(sheets, targets)):
        workbook.append(f'<sheet name="Лист {index}" sheetId="{index + 1}" state="{visibility}" r:id="rel{index}"/>')
        relationships.append(f'<Relationship Id="rel{index}" Type="{REL}/worksheet" Target="{target}"/>')
        parts[f'{directory}/worksheets/data-{index}.xml'] = xml
    if strings is not None:
        relationships.append(f'<Relationship Id="strings" Type="{REL}/sharedStrings" Target="strings/custom.xml"/>')
        parts[f'{directory}/strings/custom.xml'] = f'<sst xmlns="{NS}">' + ''.join(f'<si><t>{escape(value)}</t></si>' for value in strings) + '</sst>'
    parts[root_path] = ''.join(workbook) + '</sheets></workbook>'
    parts[f'{directory}/_rels/{root_path.rsplit("/", 1)[-1]}.rels'] = ''.join(relationships) + '</Relationships>'
    parts.update(extra or {})
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in parts.items():
            archive.writestr(path, content)
    return output.getvalue()


def excel_preview(raw=None, state=None):
    return preview(STATE if state is None else state, encoded(xlsx() if raw is None else raw), "Поставка.xlsx")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp1251"])
def test_csv_encodings_decimal_comma_grouping_and_existing_catalog(encoding):
    result = csv_preview('Поставка №15\nНаименование;Количество;Цена;Ед. изм.;Сумма\n"Рис";"1 234,5";2;г;2469\nМолоко;2,5;10;л;25\nИтого;;;;2494\n', encoding=encoding)
    assert result == {"rows": [
        {"row": 3, "name": "Рис", "quantity": 1234.5, "price": 2.0, "unit": "г", "total": 2469.0, "itemId": "rice"},
        {"row": 4, "name": "Молоко", "quantity": 2.5, "price": 10.0, "unit": "л", "total": 25.0, "itemId": "milk"},
    ], "total": 2494.0, "fileName": "Поставка.csv"}


@pytest.mark.parametrize("delimiter", [",", "\t", ";"])
def test_csv_english_headers_quoted_names_and_optional_columns(delimiter):
    text = delimiter.join(["Product name", "Qty", "Unit price"]) + '\n' + delimiter.join(['"Вода, газированная"', "2", "15.5"])
    row = csv_preview(text)["rows"][0]
    assert row["name"] == "Вода, газированная"
    assert row["quantity"] == 2 and row["price"] == 15.5
    assert row["unit"] == "" and row["itemId"] == ""


def test_multiline_quoted_csv_name_preserves_physical_row_numbers():
    rows = csv_preview('name,quantity,price\n"Минеральная\nвода",1,5\nРис,2,10')["rows"]
    assert [row["row"] for row in rows] == [2, 4]
    assert rows[0]["name"] == "Минеральная\nвода"


def test_exact_normalized_matching_is_unambiguous_and_has_no_fuzzy_fallback():
    state = {"ingredients": [{"id": "a", "name": "  Свёкла красная "}, {"id": "b", "name": "Рис"}],
             "products": [{"id": "c", "name": "РИС"}]}
    rows = csv_preview('name;quantity;price\nСВЕКЛА   красная;1;2\nРис;1;3\nСвекла;1;4\nРисс;1;5', state=state)["rows"]
    assert [row["itemId"] for row in rows] == ["a", "", "", ""]


def test_preview_does_not_write_state_even_when_a_later_row_fails():
    state = deepcopy(STATE)
    before = deepcopy(state)
    excel_preview(state=state)
    csv_preview('name;quantity;price\nРис;1;2', state=state)
    with pytest.raises(ValueError, match="Строка 3"):
        csv_preview('name;quantity;price\nРис;1;2\nМолоко;2;', state=state)
    assert state == before


@pytest.mark.parametrize("file_type", ["csv", "xlsx"])
def test_preview_then_single_receipt_updates_stock_debt_and_history(file_type):
    from app.workspace import apply_action, default_state

    state = default_state()
    rice = next(item for item in state["ingredients"] if item["id"] == "rice")
    product = state["products"][0]
    source_rows = [HEADER, [rice["name"], 2.5, 120, rice["unit"], 300],
                   [product["name"], 3, 20, product.get("unit", "шт"), 60]]
    if file_type == "csv":
        output = io.StringIO(newline="")
        csv.writer(output, delimiter=";").writerows(source_rows)
        raw = output.getvalue().encode("utf-8-sig")
    else:
        raw = xlsx([("visible", sheet(source_rows))])
    before = deepcopy(state)
    imported = preview(state, encoded(raw), f"receipt.{file_type}")
    assert state == before
    assert imported["total"] == 360
    assert [row["itemId"] for row in imported["rows"]] == ["rice", str(product["id"])]
    payload = {
        "requestId": f"imported-{file_type}-receipt", "supplierId": "supplier-frunze",
        "invoiceNumber": f"IMPORT-{file_type}",
        "items": [{key: row[key] for key in ("itemId", "quantity", "price")} for row in imported["rows"]],
        "payments": [{"accountId": "finance-bank", "amount": 100}],
    }
    actor = {"id": 42, "role": "branch", "branch_id": "b1", "display_name": "Сотрудник производства",
             "staff_role": "production", "register_id": 99, "production_shift_id": "production-import-test"}
    entity_type, document_id = apply_action(state, actor, "supply.create", payload)
    assert entity_type == "supplier_receipt"
    assert len(state["logisticsState"]["supplies"]) == len(before["logisticsState"].get("supplies", [])) + 1
    document = next(entry for entry in state["logisticsState"]["supplies"] if entry["id"] == document_id)
    assert (document["total"], document["paidTotal"], document["debt"]) == (360, 100, 260)
    assert document["status"] == "received" and document["paymentStatus"] == "partial"
    assert document["createdBy"] == actor["display_name"]
    for row in imported["rows"]:
        previous_stock = before["logisticsState"]["branchStocks"]["b1"].get(row["itemId"], 0)
        assert state["logisticsState"]["branchStocks"]["b1"][row["itemId"]] == previous_stock + row["quantity"]
        assert any(line["itemId"] == row["itemId"] and line["quantity"] == row["quantity"] and line["price"] == row["price"] for line in document["items"])
        assert any(entry["itemId"] == row["itemId"] and entry["quantity"] == row["quantity"] and entry["documentNumber"] == document["number"] for entry in state["logisticsState"]["stockLedger"])
    payments = [entry for entry in state["financeState"]["transactions"] if entry.get("documentId") == document_id]
    assert len(payments) == 1 and payments[0]["amount"] == 100
    after_receipt = deepcopy(state)
    assert apply_action(state, actor, "supply.create", deepcopy(payload)) == (entity_type, document_id)
    assert state == after_receipt


@pytest.mark.parametrize("quantity,price", [("0", "1"), ("-1", "2"), ("1", "0"), ("1", "-2"),
                                            ("NaN", "1"), ("Infinity", "1"), ("1", "inf"),
                                            ("1e999", "1"), ("1e-999", "1"), ("1", ""),
                                            ("", "1"), ("1 2", "1"), ("1,2.3", "1")])
def test_invalid_numbers_fail_the_entire_file_with_row_number(quantity, price):
    with pytest.raises(ValueError, match="Строка 2"):
        csv_preview(f'name;quantity;price\nРис;{quantity};{price}')


def test_decimal_precision_and_rounding_tolerance():
    result = csv_preview('name;quantity;price;total\nРис;0,333333;3;1\nВода;0.1;0.2;0.02')
    assert result["rows"][0]["quantity"] == .333333
    assert result["rows"][0]["total"] == .999999
    assert result["rows"][1]["total"] == .02
    assert result["total"] == 1.019999
    with pytest.raises(ValueError, match="сумма не совпадает"):
        csv_preview('name;quantity;price;total\nРис;3;10;10')


@pytest.mark.parametrize("text", [
    'name;quantity;price\n;1;2',
    'name;quantity;price\nРис;1;2\nПечать поставщика',
    'name;quantity;price\nРис;1;2\n;3;4',
    'name;quantity;price\nРис;1;2\nname;quantity;price\nВода;1;3',
    'name;quantity;price;price\nРис;1;2;3',
    'name;quantity;price\n"Рис;1;2',
    'name;quantity\nРис;1',
])
def test_partial_malformed_or_multiple_tables_are_never_silently_dropped(text):
    with pytest.raises(ValueError):
        csv_preview(text)


def test_header_search_and_exact_1000_row_limit():
    preamble = '\n'.join(['Накладная'] * 29)
    rows = '\n'.join(f'Рис {number};1;2' for number in range(1000))
    text = preamble + '\nname;quantity;price\n' + rows
    assert len(csv_preview(text)["rows"]) == 1000
    with pytest.raises(ValueError, match="1000"):
        csv_preview(text + '\nЛишняя;1;2')
    with pytest.raises(ValueError, match="30"):
        csv_preview('Предисловие\n' + text)


def test_unquoted_decimal_comma_and_data_without_column_headings_are_rejected():
    with pytest.raises(ValueError, match="Строка 2.*без заголовка"):
        csv_preview('name,quantity,price\nРис,1,5,10')
    result = csv_preview('name;quantity;price;Код\nРис;1;2;001')
    assert result["total"] == 2  # Explicitly headed auxiliary fields are allowed.


def test_frontend_template_headers_are_supported():
    assert csv_preview('Наименование;Количество;Цена за единицу;Ед. изм.\nРис;1;10;кг')["rows"][0]["itemId"] == "rice"


@pytest.mark.parametrize("file_type", ["csv", "xlsx"])
def test_sales_register_explains_correct_import_without_creating_supply(file_type):
    # The sales export has a grouped heading in A and item names in B.
    rows = [[], ["Реестр продаж с 25.09.2026 по 25.09.2026"], [],
            ["Склад/Блюдо", None, None, None, None, "Код", "Артикул", "Ед. изм", "Количество", "Цена", "Сумма"],
            ["Бар", None, None, None, None, None, None, "Итого:", 12, None, 900],
            [None, "Липтон 0,5", None, None, None, "524", None, "шт", 12, 75, 900]]
    if file_type == "xlsx":
        raw = xlsx([("visible", sheet(rows))])
    else:
        output = io.StringIO(newline="")
        csv.writer(output, delimiter=";").writerows(rows)
        raw = output.getvalue().encode("utf-8-sig")
    state = deepcopy(STATE)
    with pytest.raises(ValueError, match="Выбран реестр продаж.*Импорт продаж из Excel"):
        preview(state, encoded(raw), f"report.{file_type}")
    assert state == STATE


def test_hidden_sales_register_does_not_block_visible_supply():
    raw = xlsx([
        ("hidden", sheet([["Реестр продаж с 25.09.2026 по 25.09.2026"]])),
        ("visible", sheet([HEADER, ["Рис", 2, 10, "кг", 20]])),
    ])
    assert excel_preview(raw)["total"] == 20


def test_real_xlsx_relationships_select_visible_table_after_cover_and_hidden_sheet():
    raw = xlsx([
        ("hidden", sheet([HEADER, ["Скрыто", 1, 5]])),
        ("visible", sheet([["Накладная №44"]])),
        ("visible", sheet([HEADER, ["Рис", .5, 100, "кг", 50]])),
    ], root_path="custom/location/book.xml")
    result = excel_preview(raw)
    assert result["rows"][0]["itemId"] == "rice" and result["total"] == 50


def test_xlsx_shared_strings_numeric_and_cached_formula_cells():
    raw = xlsx([( "visible", sheet([
        [{"type": "s", "value": i} for i in range(5)],
        [{"type": "s", "value": 5}, 2, 10, "кг", {"formula": "B2*C2", "value": 20}],
    ]))], strings=HEADER + ["Рис"])
    assert excel_preview(raw)["rows"][0]["total"] == 20


@pytest.mark.parametrize("cell", [{"formula": "2+2"}, {"formula": "2+2", "value": ""}, {"type": "e", "value": "#VALUE!"}])
def test_xlsx_formula_without_cache_or_excel_error_is_actionable(cell):
    with pytest.raises(ValueError, match="Строка 2"):
        excel_preview(xlsx([("visible", sheet([HEADER, ["Рис", cell, 10]]))]))


def test_xlsx_rejects_multiple_visible_tables_and_ignores_empty_sheet():
    table = sheet([HEADER, ["Рис", 1, 2]])
    with pytest.raises(ValueError, match="несколько таблиц"):
        excel_preview(xlsx([("visible", table), ("visible", table)]))
    assert excel_preview(xlsx([("visible", sheet([])), ("visible", table)]))["total"] == 2


@pytest.mark.parametrize("target", ["../../../../outside.xml", "https://example.invalid/data.xml", "../bad\\file.xml"])
def test_xlsx_rejects_unsafe_relationship_targets(target):
    with pytest.raises(ValueError):
        excel_preview(xlsx(targets=[target]))


def test_xlsx_resolves_valid_relative_and_absolute_relationship_targets():
    for target in ["../xl/worksheets/data-0.xml", "/xl/worksheets/data-0.xml"]:
        assert excel_preview(xlsx(targets=[target]))["total"] == 20


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_xlsx_rejects_unsafe_xml_even_in_utf16(encoding):
    xml = f'<?xml version="1.0" encoding="{encoding}"?><!DOCTYPE worksheet [<!ENTITY name "Рис">]><worksheet xmlns="{NS}"><sheetData/></worksheet>'
    with pytest.raises(ValueError, match="Небезопасный XML"):
        excel_preview(xlsx([("visible", xml.encode(encoding))]))


@pytest.mark.parametrize("raw", [b"not a zip", b"PK\x03\x04", xlsx(extra={"../escape.xml": "bad"}), xlsx(extra={"xl/worksheets/data-0.xml": "<bad"})])
def test_malformed_xlsx_is_a_validation_error(raw):
    with pytest.raises(ValueError):
        excel_preview(raw)


def test_decoded_and_expanded_size_limits():
    with pytest.raises(ValueError, match="2 МБ"):
        preview(STATE, encoded(b"x" * (supply_import.MAX_FILE_BYTES + 1)), "too-large.csv")
    raw = xlsx(extra={"xl/large.txt": b"x" * (supply_import.MAX_UNPACKED_BYTES + 1)})
    assert len(raw) < supply_import.MAX_FILE_BYTES
    with pytest.raises(ValueError, match="20 МБ"):
        excel_preview(raw)


def test_encrypted_archive_and_duplicate_members_are_rejected():
    raw = bytearray(xlsx())
    # The flag is checked before reading any member; no password is attempted.
    start = raw.index(b'PK\x01\x02')
    flags = struct.unpack_from('<H', raw, start + 8)[0]
    struct.pack_into('<H', raw, start + 8, flags | 1)
    with pytest.raises(ValueError, match="паролем"):
        excel_preview(bytes(raw))
    output = io.BytesIO(xlsx())
    with zipfile.ZipFile(output, 'a') as archive:
        with pytest.warns(UserWarning, match="Duplicate"):
            archive.writestr('xl/workbook.xml', '<bad/>')
    with pytest.raises(ValueError, match="структура"):
        excel_preview(output.getvalue())


def test_corrupt_compressed_member_returns_validation_error():
    raw = bytearray(xlsx())
    # Corrupt the first member's deflate stream, retaining ZIP metadata.
    name_length, extra_length = struct.unpack_from('<HH', raw, 26)
    start = 30 + name_length + extra_length
    raw[start:start + 4] = b'\xff\xff\xff\xff'
    with pytest.raises(ValueError, match="Не удалось прочитать Excel"):
        excel_preview(bytes(raw))


@pytest.mark.parametrize("cell", [{"type": "s", "value": "bad"}, {"type": "s", "value": -1}])
def test_invalid_shared_string_references_are_validation_errors(cell):
    with pytest.raises(ValueError, match="Excel"):
        excel_preview(xlsx([("visible", sheet([HEADER, [cell, 1, 2]]))], strings=["Рис"]))


@pytest.mark.parametrize("file_name,content", [("supply.xls", b"old"), ("supply.pdf", b"pdf"), ("", b"file"), (None, b"file"), ("empty.csv", b"")])
def test_extension_and_empty_files(file_name, content):
    with pytest.raises(ValueError):
        preview(STATE, encoded(content), file_name)


@pytest.mark.parametrize("content", [None, [], "%%invalid%%", "я"])
def test_invalid_base64_is_validation_error(content):
    with pytest.raises(ValueError):
        preview(STATE, content, "supply.csv")
