"""Write-back tests: sheet XML editing, package parts, and safe I/O."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree

import openpyxl
import pytest
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Font

from activities._formula import xlsx_writer
from activities._formula.values import CellError
from activities._formula.workbook import Workbook

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

SHEET_PART = "xl/worksheets/sheet1.xml"


def _parts(path: Path) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        return [(info.filename, archive.read(info.filename)) for info in archive.infolist()]


def _write_parts(path: Path, parts: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts:
            archive.writestr(name, data)


def _rewrite_part(path: Path, name: str, transform: Callable[[bytes], bytes]) -> None:
    parts = _parts(path)
    rewritten: list[tuple[str, bytes]] = []
    for part_name, data in parts:
        if part_name == name:
            data = transform(data)
        rewritten.append((part_name, data))
    _write_parts(path, rewritten)


def _add_calc_chain(path: Path) -> None:
    parts = _parts(path)

    def with_override(data: bytes) -> bytes:
        override = (
            b'<Override PartName="/xl/calcChain.xml" '
            b'ContentType="application/vnd.openxmlformats-officedocument.'
            b'spreadsheetml.calcChain+xml"/>'
        )
        return data.replace(b"</Types>", override + b"</Types>")

    def with_relationship(data: bytes) -> bytes:
        relationship = (
            b'<Relationship Id="rIdCalcChain" '
            b'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            b'relationships/calcChain" Target="calcChain.xml"/>'
        )
        return data.replace(b"</Relationships>", relationship + b"</Relationships>")

    updated: list[tuple[str, bytes]] = []
    for name, data in parts:
        if name == "[Content_Types].xml":
            data = with_override(data)
        elif name == "xl/_rels/workbook.xml.rels":
            data = with_relationship(data)
        updated.append((name, data))
    updated.append(
        (
            "xl/calcChain.xml",
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<calcChain xmlns="' + MAIN_NS.encode() + b'"><c r="B1" i="1"/></calcChain>',
        )
    )
    _write_parts(path, updated)


def _strip_calc_pr(path: Path, *, add_ext_lst: bool = False) -> None:
    def transform(data: bytes) -> bytes:
        stripped, count = re.subn(rb"<calcPr[^>]*/>", b"", data)
        assert count == 1
        if add_ext_lst:
            extension = (
                b'<extLst><ext uri="{TEST}"><x:marker xmlns:x="urn:test:workbook"/></ext></extLst>'
            )
            stripped = stripped.replace(b"</workbook>", extension + b"</workbook>")
        return stripped

    _rewrite_part(path, "xl/workbook.xml", transform)


def _share_formulas(path: Path, anchor: str, ref: str, cells: list[str]) -> None:
    """Rewrite saved formulas as one shared group, the way Excel stores them."""

    def transform(data: bytes) -> bytes:
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
        return ElementTree.tostring(root, encoding="UTF-8", xml_declaration=True)

    _rewrite_part(path, SHEET_PART, transform)


def _sheet_root(path: Path) -> ElementTree.Element:
    with zipfile.ZipFile(path) as archive:
        return ElementTree.fromstring(archive.read(SHEET_PART))  # noqa: S314


def _workbook_root(path: Path) -> ElementTree.Element:
    with zipfile.ZipFile(path) as archive:
        return ElementTree.fromstring(archive.read("xl/workbook.xml"))  # noqa: S314


def _cell(root: ElementTree.Element, ref: str) -> ElementTree.Element:
    for cell in root.iter(f"{{{MAIN_NS}}}c"):
        if cell.get("r") == ref:
            return cell
    raise AssertionError(f"cell {ref} not found")


def _child_names(cell: ElementTree.Element) -> list[str]:
    return [child.tag.rpartition("}")[2] for child in cell]


def _build(path: Path, *, chart: bool = False, second_sheet: bool = False) -> Path:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = 1
    sheet["A2"] = 2
    sheet["A3"] = "=A1+A2"
    sheet["B1"] = '="hi"'
    sheet["B2"] = "=1=1"
    sheet["B3"] = "=1/0"
    sheet["B4"] = "=3/1"
    sheet["B5"] = "=1/2"
    if second_sheet:
        other = book.create_sheet("Other")
        other["A1"] = "untouched"
    if chart:
        bar = BarChart()
        bar.add_data(Reference(sheet, min_col=1, min_row=1, max_row=2))
        sheet.add_chart(bar, "E2")
    book.save(path)
    return path


def test_save_keeps_chart_and_removes_calc_chain(tmp_path: Path) -> None:
    path = _build(tmp_path / "book.xlsx", chart=True)
    _add_calc_chain(path)
    before = dict(_parts(path))

    book = Workbook.open(path)
    book.save()

    after = dict(_parts(path))
    assert "xl/drawings/drawing1.xml" in after
    assert "xl/charts/chart1.xml" in after
    assert after["xl/charts/chart1.xml"] == before["xl/charts/chart1.xml"]
    assert after["xl/drawings/drawing1.xml"] == before["xl/drawings/drawing1.xml"]
    assert "xl/calcChain.xml" not in after
    assert b"calcChain" not in after["[Content_Types].xml"]
    assert b"calcChain" not in after["xl/_rels/workbook.xml.rels"]

    calc_pr = _workbook_root(path).find(f"{{{MAIN_NS}}}calcPr")
    assert calc_pr is not None
    assert calc_pr.get("fullCalcOnLoad") == "1"

    loaded = openpyxl.load_workbook(path, data_only=True)
    sheet = loaded["Sheet1"]
    assert sheet["A3"].value == 3
    assert sheet["B1"].value == "hi"
    assert sheet["B2"].value is True
    assert sheet["B3"].value == "#DIV/0!"


def test_formula_values_use_the_right_xml(tmp_path: Path) -> None:
    path = _build(tmp_path / "book.xlsx")
    Workbook.open(path).save()

    root = _sheet_root(path)
    expected = {
        "A3": (None, "3"),
        "B4": (None, "3"),
        "B5": (None, "0.5"),
        "B1": ("str", "hi"),
        "B2": ("b", "1"),
        "B3": ("e", "#DIV/0!"),
    }
    for ref, (kind, text) in expected.items():
        cell = _cell(root, ref)
        value = cell.find(f"{{{MAIN_NS}}}v")
        assert value is not None, ref
        assert value.text == text, ref
        assert cell.get("t") == kind, ref
        assert _child_names(cell)[:2] == ["f", "v"], ref

    loaded = openpyxl.load_workbook(path, data_only=True)
    sheet = loaded["Sheet1"]
    assert sheet["A3"].value == 3
    assert sheet["B4"].value == 3
    assert sheet["B5"].value == 0.5
    assert sheet["B1"].value == "hi"
    assert sheet["B2"].value is True
    assert sheet["B3"].value == "#DIV/0!"
    assert sheet["A2"].value == 2


def test_circ_is_rewritten_as_value_but_engine_keeps_circ(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = "=B1"
    sheet["B1"] = "=A1"
    path = tmp_path / "cycle.xlsx"
    book.save(path)

    loaded = Workbook.open(path)
    assert loaded.recalculate()[("Sheet1", "A1")] is CellError.CIRC
    loaded.save()

    root = _sheet_root(path)
    for ref in ("A1", "B1"):
        cell = _cell(root, ref)
        assert cell.get("t") == "e"
        value = cell.find(f"{{{MAIN_NS}}}v")
        assert value is not None
        assert value.text == "#VALUE!"

    assert loaded.recalculate()[("Sheet1", "A1")] is CellError.CIRC
    assert loaded.value("Sheet1", "B1") is CellError.CIRC
    assert str(loaded.value("Sheet1", "A1")) == "#CIRC!"


def test_shared_formula_dependents_keep_their_formula(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    for row in (1, 2, 3):
        sheet[f"A{row}"] = row
        sheet[f"B{row}"] = f"=A{row}*10"
    path = tmp_path / "shared.xlsx"
    book.save(path)
    _share_formulas(path, "B1", "B1:B3", ["B2", "B3"])

    loaded = Workbook.open(path)
    assert loaded.value("Sheet1", "B3") == 30.0
    loaded.save()

    root = _sheet_root(path)
    for ref, text in (("B1", "10"), ("B2", "20"), ("B3", "30")):
        cell = _cell(root, ref)
        formula = cell.find(f"{{{MAIN_NS}}}f")
        assert formula is not None
        assert formula.get("t") == "shared"
        assert formula.get("si") == "0"
        value = cell.find(f"{{{MAIN_NS}}}v")
        assert value is not None
        assert value.text == text
    for ref in ("B2", "B3"):
        dependent = _cell(root, ref).find(f"{{{MAIN_NS}}}f")
        assert dependent is not None
        assert dependent.text is None
    anchor = _cell(root, "B1").find(f"{{{MAIN_NS}}}f")
    assert anchor is not None
    assert anchor.get("ref") == "B1:B3"
    assert anchor.text == "A1*10"

    loaded = openpyxl.load_workbook(path, data_only=True)
    assert [loaded["Sheet1"][f"B{row}"].value for row in (1, 2, 3)] == [10, 20, 30]


def test_style_attribute_survives(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = 1
    sheet["A2"] = "=A1*2"
    sheet["A2"].font = Font(bold=True)
    sheet["A2"].number_format = "0.00"
    path = tmp_path / "styled.xlsx"
    book.save(path)

    before = _cell(_sheet_root(path), "A2").get("s")
    assert before is not None

    Workbook.open(path).save()

    assert _cell(_sheet_root(path), "A2").get("s") == before
    loaded = openpyxl.load_workbook(path)
    assert loaded["Sheet1"]["A2"].font.bold is True
    assert loaded["Sheet1"]["A2"].number_format == "0.00"


def test_set_input_existing_and_new_cells(tmp_path: Path) -> None:
    path = _build(tmp_path / "book.xlsx")
    loaded = Workbook.open(path)
    loaded.set_input("Sheet1", "A1", 10)
    loaded.set_input("Sheet1", "C1", "inline")
    loaded.set_input("Sheet1", "A10", True)
    loaded.set_input("Sheet1", "B10", 3.5)
    loaded.set_input("Sheet1", "C10", " hello ")
    destination = tmp_path / "out.xlsx"
    loaded.save(destination)

    root = _sheet_root(destination)
    dimension = root.find(f"{{{MAIN_NS}}}dimension")
    assert dimension is not None
    assert dimension.get("ref") == "A1:C10"

    rows = list(root.iter(f"{{{MAIN_NS}}}row"))
    assert [row.get("r") for row in rows] == ["1", "2", "3", "4", "5", "10"]
    row_one = [cell.get("r") for cell in rows[0].findall(f"{{{MAIN_NS}}}c")]
    assert row_one == ["A1", "B1", "C1"]
    row_ten = [cell.get("r") for cell in rows[-1].findall(f"{{{MAIN_NS}}}c")]
    assert row_ten == ["A10", "B10", "C10"]

    a1 = _cell(root, "A1")
    assert a1.get("t") is None
    assert a1.find(f"{{{MAIN_NS}}}v").text == "10"  # type: ignore[union-attr]

    c1 = _cell(root, "C1")
    assert c1.get("t") == "inlineStr"
    assert c1.find(f"{{{MAIN_NS}}}v") is None
    inline = c1.find(f"{{{MAIN_NS}}}is/{{{MAIN_NS}}}t")
    assert inline is not None
    assert inline.text == "inline"
    assert inline.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"

    a10 = _cell(root, "A10")
    assert a10.get("t") == "b"
    assert a10.find(f"{{{MAIN_NS}}}v").text == "1"  # type: ignore[union-attr]

    b10 = _cell(root, "B10")
    assert b10.get("t") is None
    assert b10.find(f"{{{MAIN_NS}}}v").text == "3.5"  # type: ignore[union-attr]

    c10 = _cell(root, "C10")
    assert c10.get("t") == "inlineStr"
    text = c10.find(f"{{{MAIN_NS}}}is/{{{MAIN_NS}}}t")
    assert text is not None
    assert text.text == " hello "
    assert text.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"

    values = openpyxl.load_workbook(destination, data_only=True)["Sheet1"]
    assert values["A1"].value == 10
    assert values["A3"].value == 12
    assert values["B1"].value == "hi"
    assert values["C1"].value == "inline"
    assert values["A10"].value is True
    assert values["B10"].value == 3.5
    assert values["C10"].value == " hello "


def test_full_calc_on_load_is_inserted_in_schema_order(tmp_path: Path) -> None:
    path = _build(tmp_path / "book.xlsx")
    _strip_calc_pr(path, add_ext_lst=True)

    original = _workbook_root(path)
    assert original.find(f"{{{MAIN_NS}}}calcPr") is None

    Workbook.open(path).save()

    root = _workbook_root(path)
    children = [child.tag.rpartition("}")[2] for child in root]
    assert root.find(f"{{{MAIN_NS}}}calcPr") is not None
    calc_pr = root.find(f"{{{MAIN_NS}}}calcPr")
    assert calc_pr is not None
    assert calc_pr.get("fullCalcOnLoad") == "1"
    assert children.index("definedNames") < children.index("calcPr") < children.index("extLst")
    extension = root.find(f"{{{MAIN_NS}}}extLst")
    assert extension is not None


def test_save_in_place_and_to_another_path(tmp_path: Path) -> None:
    path = _build(tmp_path / "book.xlsx")
    loaded = Workbook.open(path)
    loaded.set_input("Sheet1", "A1", 5)

    before = path.read_bytes()
    loaded.save()
    after_in_place = path.read_bytes()
    assert after_in_place != before

    destination = tmp_path / "copy.xlsx"
    loaded.save(destination)

    assert path.read_bytes() == after_in_place
    for candidate in (path, destination):
        sheet = openpyxl.load_workbook(candidate, data_only=True)["Sheet1"]
        assert sheet["A3"].value == 7
        assert sheet["B1"].value == "hi"


def test_failure_leaves_destination_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _build(tmp_path / "book.xlsx")
    destination = tmp_path / "dest.xlsx"
    destination.write_bytes(b"original contents")
    loaded = Workbook.open(path)

    def explode(source: object, target: object) -> None:
        raise OSError("boom")

    monkeypatch.setattr(xlsx_writer.os, "replace", explode)

    with pytest.raises(OSError, match="boom"):
        loaded.save(destination)

    assert destination.read_bytes() == b"original contents"
    assert not [item for item in tmp_path.iterdir() if item.name.endswith(".tmp")]


def test_untouched_parts_are_byte_identical_and_ordered(tmp_path: Path) -> None:
    path = _build(tmp_path / "book.xlsx", chart=True, second_sheet=True)
    before = _parts(path)
    with zipfile.ZipFile(path) as archive:
        compression = {info.filename: info.compress_type for info in archive.infolist()}

    Workbook.open(path).save()

    after = _parts(path)
    assert [name for name, _ in after] == [name for name, _ in before]
    changed = {SHEET_PART, "xl/workbook.xml"}
    for (name, original), (_, rewritten) in zip(before, after, strict=True):
        if name not in changed:
            assert rewritten == original, name
    assert dict(after)["xl/worksheets/sheet2.xml"] == dict(before)["xl/worksheets/sheet2.xml"]
    with zipfile.ZipFile(path) as archive:
        assert {info.filename: info.compress_type for info in archive.infolist()} == compression


@pytest.mark.parametrize("absolute", [True, False])
def test_worksheet_relationship_target_forms(tmp_path: Path, *, absolute: bool) -> None:
    path = _build(tmp_path / "book.xlsx")

    def transform(data: bytes) -> bytes:
        if absolute:
            return data
        return data.replace(
            b'Target="/xl/worksheets/sheet1.xml"',
            b'Target="worksheets/sheet1.xml"',
        )

    _rewrite_part(path, "xl/_rels/workbook.xml.rels", transform)
    if not absolute:
        assert b'Target="worksheets/sheet1.xml"' in dict(_parts(path))["xl/_rels/workbook.xml.rels"]

    Workbook.open(path).save()

    value = _cell(_sheet_root(path), "A3").find(f"{{{MAIN_NS}}}v")
    assert value is not None
    assert value.text == "3"


def test_declaration_namespaces_and_extension_list_survive(tmp_path: Path) -> None:
    path = _build(tmp_path / "book.xlsx")
    declaration = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

    def transform(data: bytes) -> bytes:
        data = declaration + data
        data = data.replace(
            b"<worksheet ",
            b'<worksheet xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
            b'xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac" '
            b'mc:Ignorable="x14ac" ',
            1,
        )
        extension = b'<extLst><ext uri="{TEST}"><x:marker xmlns:x="urn:test:sheet"/></ext></extLst>'
        return data.replace(b"</worksheet>", extension + b"</worksheet>")

    # Open before injecting the extension so openpyxl does not drop or warn about it; save
    # reads the package again, so the writer still has to round-trip the injected content.
    book = Workbook.open(path)
    _rewrite_part(path, SHEET_PART, transform)
    book.save()

    raw = dict(_parts(path))[SHEET_PART]
    assert raw.startswith(declaration)
    text = raw.decode()
    assert 'mc:Ignorable="x14ac"' in text
    assert "urn:test:sheet" in text
    assert "<extLst>" in text
