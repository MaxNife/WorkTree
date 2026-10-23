"""Workbook loading and memoised recalculation tests for the pure-Python formula engine."""

from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

import openpyxl
import pytest
from openpyxl.utils.datetime import MAC_EPOCH
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.formula import ArrayFormula

from activities._formula.values import CellError
from activities._formula.workbook import Workbook

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _save(book: openpyxl.Workbook, path: Path) -> Path:
    book.save(path)
    return path


def _simple(path: Path) -> Path:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = 1
    sheet["A2"] = "=A1+1"
    sheet["A3"] = "=A2*2"
    return _save(book, path)


def _share_formulas(path: Path, anchor: str, ref: str, cells: list[str]) -> None:
    """Rewrite already-saved formulas as one shared-formula group, as Excel writes them."""
    with zipfile.ZipFile(path) as archive:
        items = [(info.filename, archive.read(info.filename)) for info in archive.infolist()]

    rewritten: list[tuple[str, bytes]] = []
    for filename, data in items:
        if filename == "xl/worksheets/sheet1.xml":
            root = ElementTree.fromstring(data)  # noqa: S314 - the test wrote this archive
            by_ref = {cell.get("r"): cell for cell in root.iter(f"{{{MAIN_NS}}}c")}
            anchor_formula = by_ref[anchor].find(f"{{{MAIN_NS}}}f")
            assert anchor_formula is not None
            anchor_formula.set("t", "shared")
            anchor_formula.set("ref", ref)
            anchor_formula.set("si", "0")
            for cell_ref in cells:
                formula = by_ref[cell_ref].find(f"{{{MAIN_NS}}}f")
                assert formula is not None
                formula.text = None
                formula.set("t", "shared")
                formula.set("si", "0")
            data = ElementTree.tostring(root, encoding="UTF-8", xml_declaration=True)
        rewritten.append((filename, data))

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, data in rewritten:
            archive.writestr(filename, data)


def test_simple_formula_chain(tmp_path: Path) -> None:
    path = _simple(tmp_path / "book.xlsx")
    book = Workbook.open(path)

    assert book.sheet_names == ["Sheet1"]
    assert book.formula("Sheet1", "A1") is None
    assert book.formula("Sheet1", "A2") == "=A1+1"
    assert book.value("Sheet1", "A1") == 1.0
    assert book.value("Sheet1", "A2") == 2.0
    assert book.value("Sheet1", "A3") == 4.0
    assert book.stored_value("Sheet1", "A3") is None
    assert book.evaluate("Sheet1", "=A1+2") == 3.0
    assert book.evaluate("Sheet1", "=SUM(A1:A3)") == 7.0
    assert book.recalculate() == {
        ("Sheet1", "A2"): 2.0,
        ("Sheet1", "A3"): 4.0,
    }


def test_cross_sheet_reference(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    data = book.active
    data.title = "Data"
    data["A1"] = 7
    result = book.create_sheet("Result")
    result["A1"] = "=Data!A1*3"
    result["A2"] = "='Data'!A1+Data!A1"
    path = _save(book, tmp_path / "book.xlsx")

    loaded = Workbook.open(path)

    assert loaded.sheet_names == ["Data", "Result"]
    assert loaded.value("Result", "A1") == 21.0
    assert loaded.value("Result", "A2") == 14.0


def test_workbook_and_sheet_scoped_defined_names(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    first = book.active
    first.title = "First"
    second = book.create_sheet("Second")
    first["A1"] = 5
    first["A2"] = 10
    second["A2"] = 100
    first["B1"] = "=Global*2"
    first["B2"] = "=Rate*2"
    second["B1"] = "=Global+1"
    second["B2"] = "=Rate*2"
    book.defined_names["Global"] = DefinedName("Global", attr_text="First!$A$1")
    first.defined_names["Rate"] = DefinedName("Rate", attr_text="First!$A$2")
    second.defined_names["Rate"] = DefinedName("Rate", attr_text="Second!$A$2")
    path = _save(book, tmp_path / "book.xlsx")

    loaded = Workbook.open(path)

    assert loaded.value("First", "B1") == 10.0
    assert loaded.value("First", "B2") == 20.0
    assert loaded.value("Second", "B1") == 6.0
    assert loaded.value("Second", "B2") == 200.0


def test_shared_formula_is_translated_by_openpyxl_once(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    for row in (1, 2, 3):
        sheet[f"A{row}"] = row
        sheet[f"B{row}"] = f"=A{row}*10"
    path = _save(book, tmp_path / "book.xlsx")
    _share_formulas(path, "B1", "B1:B3", ["B2", "B3"])

    loaded = Workbook.open(path)

    assert loaded.formula("Sheet1", "B1") == "=A1*10"
    assert loaded.formula("Sheet1", "B2") == "=A2*10"
    assert loaded.formula("Sheet1", "B3") == "=A3*10"
    assert loaded.value("Sheet1", "B1") == 10.0
    assert loaded.value("Sheet1", "B2") == 20.0
    assert loaded.value("Sheet1", "B3") == 30.0


def test_cycle_reports_circ(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = "=B1"
    sheet["B1"] = "=A1"
    sheet["C1"] = "=A1+1"
    path = _save(book, tmp_path / "book.xlsx")

    loaded = Workbook.open(path)

    assert loaded.value("Sheet1", "A1") is CellError.CIRC
    assert loaded.value("Sheet1", "B1") is CellError.CIRC
    assert loaded.value("Sheet1", "C1") is CellError.CIRC
    assert str(loaded.value("Sheet1", "A1")) == "#CIRC!"
    results = loaded.recalculate()
    assert results[("Sheet1", "A1")] is CellError.CIRC
    assert results[("Sheet1", "B1")] is CellError.CIRC


def _long_chain(path: Path, *, bottom_up: bool) -> Path:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = 0
    rows = range(5001, 1, -1) if bottom_up else range(2, 5002)
    for row in rows:
        sheet[f"A{row}"] = f"=A{row - 1}+1"
    return _save(book, path)


def test_long_chain_top_down(tmp_path: Path) -> None:
    path = _long_chain(tmp_path / "top.xlsx", bottom_up=False)
    loaded = Workbook.open(path)

    assert loaded.value("Sheet1", "A5001") == 5000.0
    assert loaded.value("Sheet1", "A2") == 1.0


def test_long_chain_bottom_up(tmp_path: Path) -> None:
    path = _long_chain(tmp_path / "bottom.xlsx", bottom_up=True)
    loaded = Workbook.open(path)

    assert loaded.value("Sheet1", "A2") == 1.0
    assert loaded.value("Sheet1", "A5001") == 5000.0
    results = loaded.recalculate()
    assert len(results) == 5000
    assert results[("Sheet1", "A5001")] == 5000.0


def test_now_uses_injected_clock(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = "=NOW()"
    sheet["A2"] = "=NOW()*2"
    path = _save(book, tmp_path / "book.xlsx")

    loaded = Workbook.open(path, clock=lambda: 45000.25)

    assert loaded.value("Sheet1", "A1") == 45000.25
    assert loaded.value("Sheet1", "A2") == 90000.5


def test_set_input_invalidates_dependants(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = 1
    sheet["B1"] = "=A1+1"
    sheet["C1"] = "=B1*2"
    path = _save(book, tmp_path / "book.xlsx")

    loaded = Workbook.open(path)
    assert loaded.value("Sheet1", "C1") == 4.0

    loaded.set_input("Sheet1", "A1", 10)

    assert loaded.value("Sheet1", "B1") == 11.0
    assert loaded.value("Sheet1", "C1") == 22.0
    assert loaded.recalculate() == {
        ("Sheet1", "B1"): 11.0,
        ("Sheet1", "C1"): 22.0,
    }


def test_dates_are_excel_serials(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = date(2024, 1, 1)
    sheet["A2"] = "=A1+1"
    path = _save(book, tmp_path / "book.xlsx")

    loaded = Workbook.open(path)

    assert loaded.value("Sheet1", "A1") == 45292.0
    assert loaded.value("Sheet1", "A2") == 45293.0


def test_stored_value_is_the_cached_value(tmp_path: Path) -> None:
    import xlsxwriter

    path = tmp_path / "cached.xlsx"
    book = xlsxwriter.Workbook(path)
    sheet = book.add_worksheet("Sheet1")
    sheet.write_number(0, 0, 1)
    sheet.write_formula(0, 1, "=A1+1")
    book.close()

    loaded = Workbook.open(path)

    assert loaded.stored_value("Sheet1", "B1") == 0.0  # what xlsxwriter caches
    assert loaded.value("Sheet1", "B1") == 2.0


def test_array_formula_uses_anchor_text(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = 1
    sheet["A2"] = 2
    sheet["A3"] = 3
    sheet["C1"] = ArrayFormula("C1:C3", "=A1:A3*2")
    path = _save(book, tmp_path / "book.xlsx")

    loaded = Workbook.open(path)
    value = loaded.value("Sheet1", "C1")

    assert loaded.formula("Sheet1", "C1") == "=A1:A3*2"
    assert loaded.formula("Sheet1", "C2") is None
    assert loaded.value("Sheet1", "C2") is None
    assert getattr(value, "data", None) == (2.0, 4.0, 6.0)


def test_1904_date_system_is_rejected(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    book.active["A1"] = 1
    book.epoch = MAC_EPOCH
    path = _save(book, tmp_path / "book.xlsx")

    with pytest.raises(ValueError, match="1904"):
        Workbook.open(path)
