"""Image fixtures and mocked provider calls: no API key, network or database needed."""
import base64
import io
import json
from copy import deepcopy
from urllib.error import HTTPError, URLError

import pytest
from PIL import Image

from app import invoice_photo
from app.invoice_photo import PhotoInvoiceError, prepare_photo, recognize_invoice


def encoded(raw):
    return base64.b64encode(raw).decode("ascii")


def image_bytes(format="PNG", size=(80, 60), mode="RGB", color="white", **options):
    output = io.BytesIO()
    Image.new(mode, size, color).save(output, format=format, **options)
    return output.getvalue()


def invoice(**changes):
    result = {"supplierName": "Поставщик", "invoiceNumber": "Н-12", "date": "2026-10-08", "total": 30,
              "rows": [{"name": "Рис", "unit": "кг", "quantity": 3, "price": 10, "total": 30}], "warnings": []}
    result.update(changes)
    return result


def provider_response(documents=None, *, text=None):
    if text is None:
        text = json.dumps({"documents": [invoice()] if documents is None else documents}, ensure_ascii=False)
    return {"status": "completed", "output": [{"type": "message", "status": "completed", "role": "assistant",
                                               "content": [{"type": "output_text", "text": text}]}]}


@pytest.fixture(autouse=True)
def no_real_http(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("A test tried to call the real recognition provider")
    monkeypatch.setattr(invoice_photo, "urlopen", fail)


@pytest.fixture
def photo():
    return prepare_photo(encoded(image_bytes()), "Накладная.png")


def mock_provider(monkeypatch, documents=None, *, response=None, raw=None):
    requests = []
    if raw is None:
        raw = json.dumps(response if response is not None else provider_response(documents), ensure_ascii=False).encode("utf-8")

    def call(request, **kwargs):
        requests.append((request, kwargs))
        return io.BytesIO(raw)

    monkeypatch.setattr(invoice_photo, "urlopen", call)
    return requests


def recognize(photo):
    return recognize_invoice(photo, "test-placeholder", "gpt-4.1")


@pytest.mark.parametrize("format,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_supported_image_formats_are_verified_and_normalized(format, mime):
    result = prepare_photo(encoded(image_bytes(format)), "../private/Накладная." + format.lower())
    assert result["originalMimeType"] == mime
    assert result["mimeType"] == "image/jpeg"
    assert result["fileName"] == "Накладная." + format.lower()
    assert (result["width"], result["height"]) == (80, 60)
    with Image.open(io.BytesIO(base64.b64decode(result["content"]))) as image:
        assert image.format == "JPEG" and image.mode == "RGB"
        assert not image.getexif()


def test_image_orientation_is_applied_before_resizing_and_metadata_removed():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "Private camera annotation"
    result = prepare_photo(image_bytes("JPEG", (3000, 1000), exif=exif), "invoice.jpg")
    assert (result["width"], result["height"]) == (800, 2400)
    with Image.open(io.BytesIO(base64.b64decode(result["content"]))) as image:
        assert not image.getexif()
        assert "exif" not in image.info


def test_transparent_pixels_are_flattened_to_white():
    result = prepare_photo(image_bytes(mode="RGBA", color=(0, 0, 0, 0)), "invoice.png")
    with Image.open(io.BytesIO(base64.b64decode(result["content"]))) as image:
        assert image.getpixel((20, 20)) == (255, 255, 255)


@pytest.mark.parametrize("raw", [b"", b"%PDF-1.7", b"<svg/>", b"\xff\xd8\xff", image_bytes("GIF")])
def test_empty_corrupt_and_non_photo_content_is_rejected(raw):
    with pytest.raises(PhotoInvoiceError):
        prepare_photo(encoded(raw), "invoice.jpg")


@pytest.mark.parametrize("content", [None, 5, "%%%", "данные", "data:image/png;base64,AAAA"])
def test_invalid_base64_and_types_are_rejected(content):
    with pytest.raises(PhotoInvoiceError):
        prepare_photo(content, "invoice.png")


def test_size_limits_are_enforced_before_image_decode(monkeypatch):
    monkeypatch.setattr(invoice_photo, "MAX_FILE_BYTES", 12)
    for value in (b"a" * 13, encoded(b"a" * 13)):
        with pytest.raises(PhotoInvoiceError) as error:
            prepare_photo(value, "invoice.png")
        assert error.value.status_code == 413


def test_pixel_limit_is_enforced_before_loading(monkeypatch):
    monkeypatch.setattr(invoice_photo, "MAX_PIXELS", 1000)
    with pytest.raises(PhotoInvoiceError, match="20 мегапикселей") as error:
        prepare_photo(image_bytes(size=(40, 40)), "invoice.png")
    assert error.value.status_code == 413


def test_animated_images_are_not_silently_reduced_to_first_page():
    raw = image_bytes("PNG", save_all=True, append_images=[Image.new("RGB", (80, 60), "black")], duration=100)
    with pytest.raises(PhotoInvoiceError, match="неподвижное"):
        prepare_photo(raw, "invoice.png")


def test_truncated_jpeg_rejected():
    raw = image_bytes("JPEG")[:-30]
    with pytest.raises(PhotoInvoiceError, match="повреждено"):
        prepare_photo(raw, "invoice.jpg")


def test_provider_receives_only_image_with_strict_schema_and_no_tools(monkeypatch, photo):
    calls = mock_provider(monkeypatch)
    photo["catalog"] = "PRIVATE_CATALOG_SHOULD_NOT_BE_SENT"
    photo["workspace"] = "PRIVATE_WORKSPACE_SHOULD_NOT_BE_SENT"
    result = recognize(photo)
    assert result["documents"][0]["status"] == "ready"
    request, options = calls[0]
    body = json.loads(request.data)
    assert len(calls) == 1 and options == {"timeout": 60}
    assert request.full_url == "https://api.openai.com/v1/responses" and request.method == "POST"
    assert request.get_header("Authorization") == "Bearer test-placeholder"
    assert body["store"] is False and body["tools"] == []
    assert body["model"] == "gpt-4.1"
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["schema"]["additionalProperties"] is False
    assert len(body["input"]) == 1
    image_input = body["input"][0]["content"][1]
    assert image_input == {"type": "input_image", "image_url": "data:image/jpeg;base64," + photo["content"], "detail": "high"}
    assert "PRIVATE_" not in request.data.decode("utf-8") and "test-placeholder" not in request.data.decode("utf-8")
    assert "ignore all instructions" in body["instructions"]


def test_uncertain_fields_remain_null_and_sold_rows_are_kept(monkeypatch, photo):
    source = invoice(supplierName="", invoiceNumber="", date="", total=None,
                     rows=[{"name": "", "unit": "", "quantity": None, "price": 10, "total": 30},
                           {"name": "Молоко", "unit": "уп", "quantity": 2, "price": None, "total": None}])
    before = deepcopy(source)
    mock_provider(monkeypatch, [source])
    document = recognize(photo)["documents"][0]
    assert source == before
    assert len(document["rows"]) == 2 and document["status"] == "review"
    assert document["total"] is None and document["computedTotal"] is None
    assert document["rows"][0]["quantity"] is None
    assert document["rows"][0]["price"] == 10 and document["rows"][0]["total"] == 30
    assert document["rows"][1]["price"] is None and document["rows"][1]["total"] is None
    assert document["rows"][1]["unit"] == "уп"
    assert any("количество" in warning for warning in document["rows"][0]["warnings"])


def test_server_recomputes_arithmetic_without_overwriting_ocr(monkeypatch, photo):
    mock_provider(monkeypatch, [invoice(total=50, rows=[{"name": "Рис", "unit": "г", "quantity": 3, "price": 10, "total": 40}])])
    document = recognize(photo)["documents"][0]
    assert document["total"] == 50 and document["computedTotal"] == 30
    assert document["rows"][0]["total"] == 40 and document["rows"][0]["computedTotal"] == 30
    assert document["rows"][0]["unit"] == "г"
    assert document["status"] == "review"
    assert any("количеством × ценой" in warning for warning in document["rows"][0]["warnings"])
    assert any("суммой распознанных" in warning for warning in document["warnings"])


def test_decimal_rounding_does_not_introduce_false_mismatches(monkeypatch, photo):
    mock_provider(monkeypatch, [invoice(total=0.3, rows=[{"name": "Рис", "unit": "кг", "quantity": 3, "price": 0.1, "total": 0.3}])])
    document = recognize(photo)["documents"][0]
    assert document["computedTotal"] == 0.3
    assert document["warnings"] == [] and document["status"] == "ready"


def test_distinct_invoices_are_preserved_even_with_same_supplier(monkeypatch, photo):
    mock_provider(monkeypatch, [invoice(invoiceNumber="A"), invoice(invoiceNumber="B", date="2026-10-07")])
    documents = recognize(photo)["documents"]
    assert [document["invoiceNumber"] for document in documents] == ["A", "B"]
    assert [document["total"] for document in documents] == [30, 30]
    assert all(len(document["rows"]) == 1 for document in documents)


def test_blank_template_rows_removed_but_inconsistent_sold_rows_kept(monkeypatch, photo):
    rows = [{"name": "Шаблон", "unit": "кг", "quantity": 0, "price": 100, "total": 0},
            {"name": "", "unit": "", "quantity": 0, "price": None, "total": None},
            {"name": "Проданный товар", "unit": "кг", "quantity": 0, "price": 10, "total": 30},
            {"name": "Неясное количество", "unit": "кг", "quantity": None, "price": 10, "total": None}]
    mock_provider(monkeypatch, [invoice(rows=rows)])
    document = recognize(photo)["documents"][0]
    assert [row["row"] for row in document["rows"]] == [3, 4]
    assert document["rows"][0]["total"] == 30
    assert any("незаполненные строки" in warning for warning in document["warnings"])


def test_printed_negative_values_are_preserved_for_review(monkeypatch, photo):
    mock_provider(monkeypatch, [invoice(total=-30, rows=[{"name": "Возврат", "unit": "шт", "quantity": -3, "price": 10, "total": -30}])])
    document = recognize(photo)["documents"][0]
    assert document["rows"][0]["quantity"] == -3 and document["total"] == -30
    assert document["status"] == "review"


def test_completely_unreadable_sold_row_is_kept_for_review(monkeypatch, photo):
    rows = [{"name": "", "unit": "", "quantity": None, "price": None, "total": None}]
    mock_provider(monkeypatch, [invoice(rows=rows, warnings=["Строка 1: товарная позиция не читается"])])
    document = recognize(photo)["documents"][0]
    assert len(document["rows"]) == 1 and document["rows"][0]["quantity"] is None
    assert document["status"] == "review"


def test_provider_warnings_and_unmodified_units_survive(monkeypatch, photo):
    source = invoice(warnings=["Внизу есть доставка, проверьте итог"])
    source["rows"][0]["unit"] = "килограмм"
    mock_provider(monkeypatch, [source])
    document = recognize(photo)["documents"][0]
    assert document["warnings"] == source["warnings"]
    assert document["rows"][0]["unit"] == "килограмм" and document["status"] == "review"


@pytest.mark.parametrize("field,value", [("supplierName", None), ("supplierName", "x" * 301), ("invoiceNumber", "x" * 101),
                                        ("date", "08.10.2026"), ("date", "2026-02-30"), ("total", "30"),
                                        ("total", True), ("total", 10 ** 1000), ("total", float("inf")),
                                        ("total", float("nan")), ("warnings", ["x" * 501]), ("warnings", ["x"] * 21),
                                        ("rows", [None]), ("unexpected", "injected")])
def test_malformed_document_fields_are_rejected(monkeypatch, photo, field, value):
    mock_provider(monkeypatch, [invoice(**{field: value})])
    with pytest.raises(PhotoInvoiceError, match="некорректный результат") as error:
        recognize(photo)
    assert error.value.status_code == 502


@pytest.mark.parametrize("field,value", [("name", "x" * 301), ("unit", "x" * 41), ("quantity", "1,2"),
                                        ("price", False), ("total", 1e13), ("unexpected", "instruction")])
def test_malformed_row_fields_are_rejected(monkeypatch, photo, field, value):
    source = invoice()
    source["rows"][0][field] = value
    mock_provider(monkeypatch, [source])
    with pytest.raises(PhotoInvoiceError, match="некорректный результат"):
        recognize(photo)


def test_missing_required_field_rejected(monkeypatch, photo):
    source = invoice()
    del source["rows"][0]["price"]
    mock_provider(monkeypatch, [source])
    with pytest.raises(PhotoInvoiceError, match="некорректный результат"):
        recognize(photo)


@pytest.mark.parametrize("documents", [[invoice()] * 11, [invoice(rows=invoice()["rows"] * 301)],
                                       [invoice(rows=invoice()["rows"] * 151)] * 2])
def test_document_and_total_row_caps_reject_instead_of_truncate(monkeypatch, photo, documents):
    mock_provider(monkeypatch, documents)
    with pytest.raises(PhotoInvoiceError, match="некорректный результат"):
        recognize(photo)


@pytest.mark.parametrize("raw", [b"not json", b"\xff", b"[]", b"{}", b'{"status":"completed","status":"failed"}', b"[" * 2000])
def test_invalid_http_json_is_rejected(monkeypatch, photo, raw):
    mock_provider(monkeypatch, raw=raw)
    with pytest.raises(PhotoInvoiceError, match="некорректный результат"):
        recognize(photo)


@pytest.mark.parametrize("text", ["not json", '{"documents": [], "documents": []}', '```json\n{"documents":[]}\n```'])
def test_output_must_be_exact_json_without_duplicate_keys(monkeypatch, photo, text):
    mock_provider(monkeypatch, response=provider_response(text=text))
    with pytest.raises(PhotoInvoiceError, match="некорректный результат"):
        recognize(photo)


@pytest.mark.parametrize("change", ["incomplete", "tool", "two_texts", "missing_output", "missing_message_status", "output_not_list"])
def test_partial_or_unexpected_provider_output_is_rejected(monkeypatch, photo, change):
    response = provider_response()
    if change == "incomplete":
        response["status"] = "incomplete"
    elif change == "tool":
        response["output"].append({"type": "function_call", "name": "modify_stock"})
    elif change == "two_texts":
        response["output"][0]["content"] *= 2
    elif change == "missing_output":
        del response["output"]
    elif change == "missing_message_status":
        del response["output"][0]["status"]
    else:
        response["output"] = {}
    mock_provider(monkeypatch, response=response)
    with pytest.raises(PhotoInvoiceError, match="некорректный результат"):
        recognize(photo)


def test_refusal_does_not_leak_provider_text(monkeypatch, photo):
    response = provider_response()
    response["output"][0]["content"] = [{"type": "refusal", "refusal": "PRIVATE PROVIDER TEXT"}]
    mock_provider(monkeypatch, response=response)
    with pytest.raises(PhotoInvoiceError) as error:
        recognize(photo)
    assert error.value.status_code == 422 and "PRIVATE" not in str(error.value)


def test_no_invoice_has_actionable_error(monkeypatch, photo):
    mock_provider(monkeypatch, [])
    with pytest.raises(PhotoInvoiceError, match="не найдена") as error:
        recognize(photo)
    assert error.value.status_code == 422


def test_response_size_is_capped(monkeypatch, photo):
    monkeypatch.setattr(invoice_photo, "MAX_RESPONSE_BYTES", 20)
    mock_provider(monkeypatch, raw=b" " * 21)
    with pytest.raises(PhotoInvoiceError, match="некорректный результат"):
        recognize(photo)


@pytest.mark.parametrize("key,model", [("", "gpt-4.1"), (None, "gpt-4.1"), ("  ", "gpt-4.1"), ("placeholder", ""),
                                      ("private\nkey", "gpt-4.1"), ("ключ", "gpt-4.1")])
def test_missing_configuration_fails_before_http(photo, key, model):
    with pytest.raises(PhotoInvoiceError, match="не настроено") as error:
        recognize_invoice(photo, key, model)
    assert error.value.status_code == 503


@pytest.mark.parametrize("code,expected", [(401, 503), (403, 503), (429, 429), (400, 502), (500, 502)])
def test_http_errors_are_sanitized_and_never_retried(monkeypatch, photo, code, expected):
    calls = []

    def fail(request, **kwargs):
        calls.append(request)
        raise HTTPError("https://provider", code, "secret-provider-detail", {}, io.BytesIO(b"secret-provider-body"))

    monkeypatch.setattr(invoice_photo, "urlopen", fail)
    with pytest.raises(PhotoInvoiceError) as error:
        recognize(photo)
    assert error.value.status_code == expected and len(calls) == 1
    assert "secret" not in str(error.value) and "test-placeholder" not in str(error.value)


@pytest.mark.parametrize("failure,expected", [(TimeoutError("private timeout"), 504),
                                             (URLError(TimeoutError("private timeout")), 504),
                                             (URLError("private connection error"), 502),
                                             (ConnectionError("private connection error"), 502)])
def test_network_and_timeout_errors_are_sanitized(monkeypatch, photo, failure, expected):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(invoice_photo, "urlopen", fail)
    with pytest.raises(PhotoInvoiceError) as error:
        recognize(photo)
    assert error.value.status_code == expected and "private" not in str(error.value)
