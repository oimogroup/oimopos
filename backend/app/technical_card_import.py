"""Read-only previews of technical card CSV/XLSX import tables."""
import base64
import binascii
import csv
import io
import math
import posixpath
import re
import unicodedata
import zipfile
import zlib
from decimal import Decimal, InvalidOperation, localcontext
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET


MAX_FILE_BYTES = 2_000_000
MAX_UNPACKED_BYTES = 20_000_000
MAX_ROWS = 1000
_MAIN_NS = {"http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "http://purl.oclc.org/ooxml/spreadsheetml/main"}


def normalize(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value)).strip()).casefold().replace("ё", "е")


def _header_name(value):
    return re.sub(r"[^\w]+", " ", normalize(value)).strip()


_ALIASES = {
    "card": ("наименование блюда", "блюдо", "наименование", "name", "карта", "техкарта", "output"),
    "kind": ("вид", "kind", "тип", "type", "полуфабрикат", "техкарта", "продукция"),
    "category": ("категория", "category", "категория блюда"),
    "station": ("цех", "station", "цех приготовления"),
    "yield": ("выход", "yield", "выход блюда", "выход, г"),
    "weight": ("вес", "weight", "вес блюда", "yield_weight", "вес, г"),
    "price": ("цена", "price", "цена продажи", "sale_price", "цена, сом"),
    "ingredient": ("ингредиент", "ingredient", "компонент", "продукт", "товар"),
    "gross": ("брутто", "gross", "gross_quantity", "брутто, г"),
    "net": ("нетто", "net", "net_quantity", "нетто, г"),
}
_HEADERS = {_header_name(alias): key for key, aliases in _ALIASES.items() for alias in aliases}


def _columns(cells):
    columns = {}
    duplicates = set()
    for column, value in cells.items():
        key = _HEADERS.get(_header_name(value))
        if key:
            if key in columns:
                duplicates.add(key)
            columns[key] = column
    if {"card", "ingredient", "gross", "net"} <= columns.keys():
        if duplicates:
            raise ValueError("В заголовке повторяются столбцы. Оставьте по одному столбцу каждого вида")
        return columns
    return None


def _number(value, row, label, *, zero=False):
    text = re.sub(r"\s+", " ", str(value).strip())
    pattern = r"\+?(?:\d+|\d{1,3}(?: \d{3})+)(?:[.,]\d+)?(?:[eE][+-]?\d+)?"
    if len(text) > 128 or not re.fullmatch(pattern, text):
        raise ValueError(f"Строка {row}: {label} должно быть положительным числом")
    try:
        number = Decimal(text.replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Строка {row}: некорректное значение «{label}»") from None
    if not number.is_finite() or number < 0 or (not zero and number == 0):
        raise ValueError(f"Строка {row}: {label} должно быть положительным конечным числом")
    return number


def _table(rows, header):
    index, columns = header
    result = []
    with localcontext() as context:
        context.prec = 160
        for number, cells in rows[index + 1:]:
            if not any(str(value).strip() for value in cells.values()):
                continue
            mapped = {key: str(cells.get(column, "")).strip() for key, column in columns.items()}
            name = mapped["card"]
            if not name:
                raise ValueError(f"Строка {number}: не указано наименование блюда")
            ingredient_name = mapped["ingredient"]
            if not ingredient_name:
                raise ValueError(f"Строка {number}: не указан ингредиент")
            gross = _number(mapped["gross"], number, "брутто")
            net = _number(mapped["net"], number, "нетто")
            if net > gross:
                raise ValueError(f"Строка {number}: нетто не может быть больше брутто")
            card_yield = _number(mapped.get("yield", ""), number, "выход", zero=True) if mapped.get("yield") else None
            weight = _number(mapped.get("weight", ""), number, "вес", zero=True) if mapped.get("weight") else None
            price = _number(mapped.get("price", ""), number, "цена", zero=True) if mapped.get("price") else None
            kind = str(mapped.get("kind", "")).strip() or "техкарта"
            if kind not in {"техкарта", "полуфабрикат"}:
                raise ValueError(f"Строка {number}: укажите вид — техкарта или полуфабрикат")
            result.append({
                "row": number,
                "kind": kind,
                "card": name,
                "category": mapped.get("category", ""),
                "station": mapped.get("station", ""),
                "yield": float(card_yield) if card_yield is not None else None,
                "weight": float(weight) if weight is not None else None,
                "price": float(price) if price is not None else None,
                "ingredient": ingredient_name,
                "gross": float(gross),
                "net": float(net),
            })
            if len(result) > MAX_ROWS:
                raise ValueError("В файле должно быть не больше 1000 позиций")
    if not result:
        raise ValueError("После заголовка нет позиций техкарт")
    return result


def _find_header(rows):
    for index, (number, cells) in enumerate(rows):
        if number > 30:
            break
        columns = _columns(cells)
        if columns:
            return index, columns
    return None


def _csv(raw):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1251")
        except UnicodeDecodeError:
            raise ValueError("Не удалось прочитать CSV: сохраните файл в UTF-8 или Windows-1251") from None
    if "\x00" in text:
        raise ValueError("Не удалось прочитать CSV: сохраните файл в UTF-8 или Windows-1251")
    candidates = []
    for delimiter in (";", ",", "\t"):
        rows = []
        try:
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
            previous_line = 0
            for values in reader:
                rows.append((previous_line + 1, dict(enumerate(values))))
                previous_line = reader.line_num
                if len(rows) > 10_000:
                    raise ValueError("Слишком много строк")
        except csv.Error:
            continue
        header = _find_header(rows)
        if header:
            candidates.append((rows, header))
    if len(candidates) > 1:
        raise ValueError("Неоднозначный разделитель CSV. Используйте точку с запятой")
    if not candidates:
        raise ValueError("Не найдены столбцы «Блюдо», «Ингредиент», «Брутто», «Нетто» в первых 30 строках CSV")
    return _table(*candidates[0])


def _part(source, target):
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("В Excel обнаружена неподдерживаемая внешняя ссылка на лист")
    target = unquote(parsed.path)
    if "\\" in target or "\x00" in target:
        raise ValueError("Некорректная структура Excel")
    path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(posixpath.dirname(source), target))
    if path in {".", ".."} or path.startswith("../"):
        raise ValueError("Некорректная структура Excel")
    return path


def _relationships(xml, source):
    path = posixpath.join(posixpath.dirname(source), "_rels", posixpath.basename(source) + ".rels") if source else "_rels/.rels"
    result = {}
    for relation in xml(path):
        if relation.tag.rsplit("}", 1)[-1] != "Relationship":
            continue
        key = relation.get("Id")
        if not key or key in result:
            raise ValueError("В Excel повторяются идентификаторы связей")
        result[key] = relation.attrib
    return result


def _related_part(source, relation):
    if relation.get("TargetMode", "Internal") != "Internal" or not relation.get("Target"):
        raise ValueError("Внешние ссылки на листы Excel не поддерживаются")
    return _part(source, relation["Target"])


def _sheet_rows(root, strings):
    namespace = root.tag.partition("}")[0].lstrip("{")
    if namespace not in _MAIN_NS or root.tag.rsplit("}", 1)[-1] != "worksheet":
        raise ValueError("Неподдерживаемый формат листа Excel")
    ns = {"s": namespace}
    result = []
    previous_row = 0
    for row in root.findall("s:sheetData/s:row", ns):
        try:
            number = int(row.get("r", previous_row + 1))
        except ValueError:
            raise ValueError("В Excel некорректный номер строки") from None
        if not previous_row < number <= 1_048_576:
            raise ValueError("В Excel некорректные или повторяющиеся номера строк")
        previous_row = number
        cells = {}
        previous_column = -1
        for cell in row.findall("s:c", ns):
            reference = cell.get("r")
            column = previous_column + 1
            if reference:
                match = re.fullmatch(r"([A-Z]{1,3})([1-9]\d*)", reference)
                if not match or int(match[2]) != number:
                    raise ValueError(f"Строка {number}: некорректный адрес ячейки Excel")
                column = 0
                for letter in match[1]:
                    column = column * 26 + ord(letter) - ord("A") + 1
                column -= 1
            if column in cells or not 0 <= column < 16_384:
                raise ValueError(f"Строка {number}: некорректные или повторяющиеся ячейки Excel")
            previous_column = column
            value = cell.find("s:v", ns)
            value = value.text if value is not None else ""
            if cell.find("s:f", ns) is not None and not str(value or "").strip():
                raise ValueError(f"Строка {number}: формула без сохранённого результата")
            kind = cell.get("t", "n")
            if kind == "s":
                try:
                    idx = int(value)
                except (TypeError, ValueError):
                    raise ValueError(f"Строка {number}: некорректная ссылка на текст Excel") from None
                if not 0 <= idx < len(strings):
                    raise ValueError("Некорректная таблица строк Excel")
                value = strings[idx]
            elif kind == "inlineStr":
                inline = cell.find("s:is", ns)
                value = _string(inline, ns) if inline is not None else ""
            elif kind == "e":
                raise ValueError(f"Строка {number}: исправьте ошибку в ячейке Excel")
            elif kind == "b":
                value = "TRUE" if value == "1" else "FALSE"
            elif kind not in {"n", "str", "d"}:
                raise ValueError(f"Строка {number}: неподдерживаемый тип ячейки Excel")
            cells[column] = value or ""
        result.append((number, cells))
        if len(result) > 10_000:
            raise ValueError("Слишком много строк")
    return result


def _string(element, ns):
    return "".join(child.text or "" for child in element.findall("s:t", ns) + element.findall("s:r/s:t", ns))


def _xlsx(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(infos) > 2000 or sum(info.file_size for info in infos) > MAX_UNPACKED_BYTES:
                raise ValueError("Распакованный Excel должен быть не больше 20 МБ")
            if len(set(names)) != len(names) or any(name.startswith("/") or "\\" in name or ".." in name.split("/") for name in names):
                raise ValueError("Некорректная структура Excel")
            if any(info.flag_bits & 1 for info in infos):
                raise ValueError("Excel защищён паролем. Загрузите файл без шифрования")
            if any(info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} for info in infos):
                raise ValueError("Неподдерживаемое сжатие Excel. Пересохраните файл как .xlsx")

            def xml(path):
                data = archive.read(path)
                if b"<!DOCTYPE" in data.replace(b"\0", b"").upper() or b"<!ENTITY" in data.replace(b"\0", b"").upper():
                    raise ValueError("Небезопасный XML в Excel")
                return ET.fromstring(data)

            workbook_path = "xl/workbook.xml"
            if "_rels/.rels" in names:
                references = [relation for relation in _relationships(xml, "").values() if relation.get("Type", "").endswith("/officeDocument")]
                if len(references) != 1:
                    raise ValueError("В Excel не найдена однозначная рабочая книга")
                workbook_path = _related_part("", references[0])
            book = xml(workbook_path)
            namespace = book.tag.partition("}")[0].lstrip("{")
            if namespace not in _MAIN_NS:
                raise ValueError("Неподдерживаемый формат рабочей книги Excel")
            ns = {"s": namespace}
            relations = _relationships(xml, workbook_path)
            shared = [relation for relation in relations.values() if relation.get("Type", "").endswith("/sharedStrings")]
            if len(shared) > 1:
                raise ValueError("Неоднозначная таблица строк Excel")
            strings = []
            if shared:
                root = xml(_related_part(workbook_path, shared[0]))
                strings = [_string(value, ns) for value in root.findall("s:si", ns)]
            candidates = []
            seen = set()
            for sheet in book.findall("s:sheets/s:sheet", ns):
                if sheet.get("state", "visible") != "visible":
                    continue
                identity = next((value for key, value in sheet.attrib.items() if key.endswith("}id")), None)
                relation = relations.get(identity)
                if relation is None:
                    raise ValueError("В Excel отсутствует связь с листом")
                if not relation.get("Type", "").endswith("/worksheet"):
                    continue
                path = _related_part(workbook_path, relation)
                if path in seen:
                    raise ValueError("Один лист Excel указан несколько раз")
                seen.add(path)
                rows = _sheet_rows(xml(path), strings)
                header = _find_header(rows)
                if header:
                    candidates.append((rows, header))
            if not candidates:
                raise ValueError("Не найдены столбцы «Блюдо», «Ингредиент», «Брутто», «Нетто» в первых 30 строках видимых листов Excel")
            if len(candidates) > 1:
                raise ValueError("В Excel несколько таблиц техкарт. Оставьте один видимый лист с нужной таблицей")
            return _table(*candidates[0])
    except (zipfile.BadZipFile, zipfile.LargeZipFile, KeyError, IndexError, TypeError, ET.ParseError, RuntimeError, NotImplementedError, EOFError, OSError, zlib.error):
        raise ValueError("Не удалось прочитать Excel. Загрузите исправный файл .xlsx без пароля") from None


def preview(state, encoded, file_name):
    """Return a preview without modifying catalog, recipes, or stock."""
    if not isinstance(file_name, str) or not file_name.strip() or len(file_name) > 255:
        raise ValueError("Укажите имя файла с расширением .xlsx или .csv")
    file_name = file_name.strip()
    suffix = file_name.rsplit(".", 1)[-1].casefold()
    if suffix not in {"xlsx", "csv"}:
        raise ValueError("Поддерживаются Excel .xlsx и CSV. Старый .xls пересохраните как .xlsx")
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_FILE_BYTES + 2) // 3):
        raise ValueError("Размер файла должен быть не больше 2 МБ")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Не удалось прочитать файл. Выберите файл заново") from None
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ValueError("Файл пуст или его размер больше 2 МБ")
    rows = _xlsx(raw) if suffix == "xlsx" else _csv(raw)
    catalog = {normalize(item.get("name", "")): str(item["id"]) for item in [*state.get("ingredients", []), *state.get("products", [])]}
    for row in rows:
        row["ingredientId"] = catalog.get(normalize(row["ingredient"]), "")
    return {"rows": rows, "fileName": file_name}
