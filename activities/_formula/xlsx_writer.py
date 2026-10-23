"""Write recalculated results and inputs back into an ``.xlsx`` package.

The package is edited as XML with :mod:`lxml` and rebuilt member by member, so charts,
images and every other part survive untouched; re-saving through openpyxl would drop them.
Only the worksheet parts that need a change are re-serialised, and everything else is copied
byte for byte in its original order with its original compression type.

The writer never imports :mod:`activities._formula.workbook`; it receives plain mappings and
therefore keeps the loader independent of the XML editing details.
"""

from __future__ import annotations

import math
import os
import posixpath
import re
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from lxml import etree  # type: ignore[import-untyped]

from activities._formula.parser import col_letters, parse_cell
from activities._formula.values import Array, CellError, Value

CellKey = tuple[str, int, int]
"""``(sheet, row, column)``, row and column 0-based."""

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"

WORKBOOK_PART = "xl/workbook.xml"
WORKBOOK_RELS_PART = "xl/_rels/workbook.xml.rels"
CONTENT_TYPES_PART = "[Content_Types].xml"
CALC_CHAIN_PART = "xl/calcChain.xml"

_CALC_CHAIN_TYPE = "/calcChain"
_WORKSHEET_TYPE = "/worksheet"

# Excel accepts only these error strings in a cached value. The engine has richer errors
# (#CIRC!, #SPILL!, #CALC!); they must not leak into the file.
_EXCEL_ERRORS = {
    CellError.NULL: "#NULL!",
    CellError.DIV0: "#DIV/0!",
    CellError.VALUE: "#VALUE!",
    CellError.REF: "#REF!",
    CellError.NAME: "#NAME?",
    CellError.NUM: "#NUM!",
    CellError.NA: "#N/A",
    CellError.GETTING_DATA: "#GETTING_DATA",
}
_FALLBACK_ERROR = "#VALUE!"

# CT_Workbook children that follow calcPr in schema order.
_AFTER_CALC_PR = frozenset(
    {
        "oleSize",
        "customWorkbookViews",
        "pivotCaches",
        "smartTagPr",
        "smartTagTypes",
        "webPublishing",
        "fileRecoveryPr",
        "webPublishObjects",
        "extLst",
    }
)

_XML_DECLARATION = re.compile(rb"^\s*<\?xml[^>]*\?>")
_XML_ENCODING = re.compile(rb"encoding\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)


def write_back(
    source: Path,
    destination: Path,
    results: Mapping[CellKey, Value],
    inputs: Mapping[CellKey, Value],
) -> None:
    """Write ``results`` and ``inputs`` into ``source``, producing ``destination``.

    ``source`` may equal ``destination``. The new package is built in a temporary file next
    to the destination and moved into place with :func:`os.replace`, so a failure leaves the
    destination untouched.
    """
    with zipfile.ZipFile(source) as archive:
        comment = archive.comment
        members = [(info, archive.read(info.filename)) for info in archive.infolist()]

    data_by_name = {info.filename: data for info, data in members}

    workbook_data = _member(data_by_name, WORKBOOK_PART)
    rels_data = _member(data_by_name, WORKBOOK_RELS_PART)
    rels_root = _parse(rels_data)
    sheet_parts = _sheet_parts(_parse(workbook_data), rels_root)

    result_groups = _group(results)
    input_groups = _group(inputs)
    changed: dict[str, bytes] = {}
    for sheet in result_groups.keys() | input_groups.keys():
        part = sheet_parts.get(sheet)
        if part is None or part not in data_by_name:
            continue
        original = data_by_name[part]
        rewritten = _edit_sheet(original, result_groups.get(sheet, []), input_groups.get(sheet, []))
        if rewritten != original:
            changed[part] = rewritten

    removed, rels_changed = _remove_calc_chain(rels_root, data_by_name)
    if rels_changed:
        changed[WORKBOOK_RELS_PART] = _serialize(rels_data, rels_root)
    if removed:
        content_types = _drop_content_types(data_by_name.get(CONTENT_TYPES_PART), removed)
        if content_types is not None:
            changed[CONTENT_TYPES_PART] = content_types

    workbook_root = _parse(workbook_data)
    if _ensure_calc_properties(workbook_root):
        changed[WORKBOOK_PART] = _serialize(workbook_data, workbook_root)

    _write_package(destination, members, removed, changed, comment)


# ---------------------------------------------------------------- package structure


def _member(data_by_name: Mapping[str, bytes], name: str) -> bytes:
    data = data_by_name.get(name)
    if data is None:
        raise ValueError(f"not an xlsx package: missing {name}")
    return data


def _sheet_parts(workbook: Any, rels: Any) -> dict[str, str]:
    """Map sheet names to worksheet part paths through the workbook relationships."""
    targets: dict[str, str] = {}
    for rel in rels:
        if _local(rel) != "Relationship":
            continue
        if (rel.get("Type") or "").endswith(_WORKSHEET_TYPE):
            rel_id, target = rel.get("Id"), rel.get("Target")
            if rel_id and target:
                targets[rel_id] = _resolve_part(target)
    parts: dict[str, str] = {}
    for sheet in workbook.iter(_tag("sheet")):
        name = sheet.get("name")
        rel_id = _relationship_id(sheet)
        if name and rel_id and rel_id in targets:
            parts[name] = targets[rel_id]
    return parts


def _relationship_id(element: Any) -> str | None:
    value = element.get(f"{{{REL_NS}}}id")
    if value is not None:
        return cast(str, value)
    for key, candidate in element.attrib.items():
        if isinstance(key, str) and key.startswith("{") and _local_name(key) == "id":
            return cast(str, candidate)
    return None


def _resolve_part(target: str) -> str:
    """Resolve a relationship target, which may be package-absolute or workbook-relative."""
    target = target.replace("\\", "/")
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    return posixpath.normpath(posixpath.join("xl", target))


def _remove_calc_chain(rels: Any, data_by_name: Mapping[str, bytes]) -> tuple[set[str], bool]:
    """Delete calcChain relationships and report the parts they pointed at.

    Returns the parts to drop and whether the relationship part changed.
    """
    removed: set[str] = set()
    rels_changed = False
    if CALC_CHAIN_PART in data_by_name:
        removed.add(CALC_CHAIN_PART)
    for rel in list(rels):
        if _local(rel) != "Relationship":
            continue
        if not (rel.get("Type") or "").endswith(_CALC_CHAIN_TYPE):
            continue
        target = rel.get("Target")
        if target:
            removed.add(_resolve_part(target))
        rels.remove(rel)
        rels_changed = True
    return removed, rels_changed


def _drop_content_types(data: bytes | None, removed: set[str]) -> bytes | None:
    """Remove content-type overrides for deleted parts; ``None`` when there is nothing to do."""
    if data is None or not removed:
        return None
    root = _parse(data)
    wanted = {"/" + part.lower() for part in removed}
    dropped = False
    for element in list(root):
        if _local(element) != "Override":
            continue
        if (element.get("PartName") or "").lower() in wanted:
            root.remove(element)
            dropped = True
    return _serialize(data, root) if dropped else None


def _ensure_calc_properties(workbook: Any) -> bool:
    """Force a full recalculation on load, inserting ``calcPr`` in schema order if needed."""
    calc_pr = next((child for child in workbook if _local(child) == "calcPr"), None)
    if calc_pr is None:
        calc_pr = etree.Element(_tag("calcPr"))
        index = len(workbook)
        for position, child in enumerate(workbook):
            if _local(child) in _AFTER_CALC_PR:
                index = position
                break
        workbook.insert(index, calc_pr)
    elif calc_pr.get("fullCalcOnLoad") == "1":
        return False
    calc_pr.set("fullCalcOnLoad", "1")
    return True


def _write_package(
    destination: Path,
    members: list[tuple[zipfile.ZipInfo, bytes]],
    removed: set[str],
    changed: Mapping[str, bytes],
    comment: bytes,
) -> None:
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        os.close(descriptor)
        temporary = Path(name)
        with zipfile.ZipFile(temporary, "w") as archive:
            archive.comment = comment
            for info, data in members:
                if info.filename in removed:
                    continue
                payload = changed.get(info.filename, data)
                archive.writestr(info, payload, compress_type=info.compress_type)
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


# ---------------------------------------------------------------- worksheet editing


def _edit_sheet(
    original: bytes,
    results: list[tuple[int, int, Value]],
    inputs: list[tuple[int, int, Value]],
) -> bytes:
    root = _parse(original)
    sheet_data = root.find(_tag("sheetData"))
    if sheet_data is None:
        raise ValueError("worksheet part has no sheetData")

    rows: dict[int, Any] = {}
    for row in sheet_data:
        if _local(row) == "row":
            number = _row_number(row)
            if number is not None:
                rows[number] = row

    bounds = _dimension_bounds(root)
    if bounds is None:
        bounds = _content_bounds(sheet_data)

    for row, col, value in results:
        cell = _find_cell(rows, row, col)
        if cell is None:
            continue
        _set_value(cell, _payload(value, inline=False))
        bounds = _expand(bounds, row, col)

    for row, col, value in inputs:
        cell = _find_cell(rows, row, col)
        if cell is None:
            cell = etree.Element(_tag("c"))
            cell.set("r", _reference(row, col))
            _insert_cell(_ensure_row(sheet_data, rows, row), cell, col)
        _set_value(cell, _payload(value, inline=True))
        bounds = _expand(bounds, row, col)

    if bounds is not None:
        _set_dimension(root, bounds)
    return _serialize(original, root)


def _find_cell(rows: Mapping[int, Any], row: int, col: int) -> Any:
    parent = rows.get(row)
    if parent is None:
        return None
    for cell in parent:
        if _local(cell) != "c":
            continue
        parsed = parse_cell(cell.get("r") or "")
        if parsed == (row, col):
            return cell
    return None


def _ensure_row(sheet_data: Any, rows: dict[int, Any], row: int) -> Any:
    existing = rows.get(row)
    if existing is not None:
        return existing
    element = etree.Element(_tag("row"))
    element.set("r", str(row + 1))
    index = len(sheet_data)
    for position, child in enumerate(sheet_data):
        number = _row_number(child) if _local(child) == "row" else None
        if number is not None and number > row:
            index = position
            break
    sheet_data.insert(index, element)
    rows[row] = element
    return element


def _insert_cell(row: Any, cell: Any, col: int) -> None:
    index = len(row)
    for position, child in enumerate(row):
        if _local(child) != "c":
            continue
        parsed = parse_cell(child.get("r") or "")
        if parsed is not None and parsed[1] > col:
            index = position
            break
    row.insert(index, cell)


def _payload(value: Value, *, inline: bool) -> tuple[str | None, str | None, str | None]:
    """Return ``(t, v text, inline text)`` for a cell value."""
    value = _scalar(value)
    if isinstance(value, bool):
        return "b", "1" if value else "0", None
    if isinstance(value, float | int):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return "e", _FALLBACK_ERROR, None
        return None, _number_text(number), None
    if isinstance(value, str):
        return ("inlineStr", None, value) if inline else ("str", value, None)
    if isinstance(value, CellError):
        return "e", _EXCEL_ERRORS.get(value, _FALLBACK_ERROR), None
    return None, None, None


def _scalar(value: Value) -> Value:
    """An array result is cached as its top-left element, which is what the anchor holds."""
    if isinstance(value, Array):
        return value.data[0] if value.data else CellError.CALC
    return value


def _number_text(number: float) -> str:
    text = repr(number)
    return text[:-2] if text.endswith(".0") else text


def _set_value(cell: Any, payload: tuple[str | None, str | None, str | None]) -> None:
    formula_type, value_text, inline_text = payload
    for child in list(cell):
        if _local(child) in {"v", "is"}:
            cell.remove(child)
    if formula_type is None:
        cell.attrib.pop("t", None)
    else:
        cell.set("t", formula_type)
    index = _insert_index(cell)
    if value_text is not None:
        value = etree.Element(_tag("v"))
        value.text = value_text
        cell.insert(index, value)
        index += 1
    if inline_text is not None:
        inline = etree.Element(_tag("is"))
        text = etree.SubElement(inline, _tag("t"))
        text.set(f"{{{XML_NS}}}space", "preserve")
        text.text = inline_text
        cell.insert(index, inline)


def _insert_index(cell: Any) -> int:
    for position, child in enumerate(cell):
        if _local(child) == "f":
            return position + 1
    return 0


# ---------------------------------------------------------------- dimensions


Bounds = tuple[int, int, int, int]
"""``(min_row, min_col, max_row, max_col)``, all 0-based."""


def _dimension_bounds(root: Any) -> Bounds | None:
    dimension = root.find(_tag("dimension"))
    if dimension is None:
        return None
    ref = dimension.get("ref") or ""
    first, _, last = ref.partition(":")
    start = parse_cell(first)
    end = parse_cell(last) if last else start
    if start is None or end is None:
        return None
    return (
        min(start[0], end[0]),
        min(start[1], end[1]),
        max(start[0], end[0]),
        max(start[1], end[1]),
    )


def _content_bounds(sheet_data: Any) -> Bounds | None:
    bounds: Bounds | None = None
    for row in sheet_data:
        if _local(row) != "row":
            continue
        for cell in row:
            if _local(cell) != "c":
                continue
            parsed = parse_cell(cell.get("r") or "")
            if parsed is not None:
                bounds = _expand(bounds, parsed[0], parsed[1])
    return bounds


def _expand(bounds: Bounds | None, row: int, col: int) -> Bounds:
    if bounds is None:
        return row, col, row, col
    return (
        min(bounds[0], row),
        min(bounds[1], col),
        max(bounds[2], row),
        max(bounds[3], col),
    )


def _set_dimension(root: Any, bounds: Bounds) -> None:
    first, last = (bounds[0], bounds[1]), (bounds[2], bounds[3])
    ref = _reference(*first)
    if last != first:
        ref = f"{ref}:{_reference(*last)}"
    dimension = root.find(_tag("dimension"))
    if dimension is not None:
        if dimension.get("ref") != ref:
            dimension.set("ref", ref)
        return
    dimension = etree.Element(_tag("dimension"))
    dimension.set("ref", ref)
    index = 0
    for position, child in enumerate(root):
        if _local(child) == "sheetPr":
            index = position + 1
            break
    root.insert(index, dimension)


# ---------------------------------------------------------------- small helpers


def _group(entries: Mapping[CellKey, Value]) -> dict[str, list[tuple[int, int, Value]]]:
    grouped: dict[str, list[tuple[int, int, Value]]] = {}
    for (sheet, row, col), value in entries.items():
        grouped.setdefault(sheet, []).append((row, col, value))
    for items in grouped.values():
        items.sort(key=lambda item: (item[0], item[1]))
    return grouped


def _reference(row: int, col: int) -> str:
    return f"{col_letters(col)}{row + 1}"


def _row_number(row: Any) -> int | None:
    value = row.get("r")
    if not isinstance(value, str) or not value.isdigit():
        return None
    return int(value) - 1


def _tag(name: str) -> str:
    return f"{{{MAIN_NS}}}{name}"


def _local(element: Any) -> str:
    return _local_name(element.tag)


def _local_name(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rpartition("}")[2]


def _parse(data: bytes) -> Any:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return etree.fromstring(data, parser)


def _serialize(original: bytes, root: Any) -> bytes:
    """Serialise ``root`` behind the original XML declaration, which is kept verbatim."""
    prefix, body = b"", original
    if body.startswith(b"\xef\xbb\xbf"):
        prefix, body = b"\xef\xbb\xbf", body[3:]
    match = _XML_DECLARATION.match(body)
    declaration = match.group(0) if match else b'<?xml version="1.0" encoding="UTF-8"?>'
    encoding = _XML_ENCODING.search(declaration)
    if encoding is not None and encoding.group(1).lower() not in {b"utf-8", b"utf8", b"us-ascii"}:
        declaration = b'<?xml version="1.0" encoding="UTF-8"?>'
    serialized = cast(bytes, etree.tostring(root, encoding="UTF-8", xml_declaration=False))
    return prefix + declaration + b"\n" + serialized
