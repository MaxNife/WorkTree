"""The `document` activity on plain docx XML: text, info, convert and mail merge (no skips)."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from pydantic import ValidationError

from activities import _docx
from activities.document import DocumentActivity, DocumentInputs
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome
from fixtures.docx_files import complex_field, paragraph, simple_field, write_docx

CORE = (
    '<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Letter</dc:title><dc:creator>Ada</dc:creator>'
    "</cp:coreProperties>"
)


@pytest.fixture
def ctx(tmp_path: Path) -> ActivityContext:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return ActivityContext(
        run_id="doc", step_id="s", workspace=workspace, clock=FakeClock(), correlation_id="c"
    )


def document(ctx: ActivityContext, **inputs: Any) -> Any:
    return DocumentActivity().execute(ctx, inputs)


def make_template(ctx: ActivityContext, name: str = "letter.docx") -> None:
    body = (
        paragraph("Invoice", style="Heading1")
        + f'<w:p><w:r><w:t xml:space="preserve">Dear </w:t></w:r>{simple_field("Name")}'
        "<w:r><w:t>,</w:t></w:r></w:p>"
        f'<w:p><w:r><w:t xml:space="preserve">Amount: </w:t></w:r>{complex_field("Amount")}</w:p>'
    )
    write_docx(ctx.workspace / name, body, core=CORE)


def text_of(ctx: ActivityContext, name: str) -> str:
    return _docx.plain_text(_docx.load_document(ctx.workspace / name))


def test_inputs_are_checked_up_front() -> None:
    with pytest.raises(ValidationError, match="unsupported input format"):
        DocumentInputs(path="a.pdf")
    with pytest.raises(ValidationError, match="convert needs output_path"):
        DocumentInputs(operation="convert")
    with pytest.raises(ValidationError, match="unsupported output format"):
        DocumentInputs(operation="convert", output_path="a.pdf")
    with pytest.raises(ValidationError, match="exactly one of data_path or rows"):
        DocumentInputs(operation="mail_merge")
    with pytest.raises(ValidationError, match="exactly one of data_path or rows"):
        DocumentInputs(operation="mail_merge", data_path="a.csv", rows=[{"a": 1}])
    with pytest.raises(ValidationError, match="unsupported recipients format"):
        DocumentInputs(operation="mail_merge", data_path="a.docx")


def test_mail_merge_from_csv_one_section_per_record(ctx) -> None:
    make_template(ctx)
    before = (ctx.workspace / "letter.docx").read_bytes()
    (ctx.workspace / "people.csv").write_text(
        "Name,Amount\nAda,10.50\nGrace,00123\n", encoding="utf-8"
    )
    result = document(
        ctx,
        operation="mail_merge",
        path="letter.docx",
        data_path="people.csv",
        output_path="out.docx",
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["records"] == 2
    assert (ctx.workspace / "letter.docx").read_bytes() == before  # template untouched
    text = text_of(ctx, "out.docx")
    assert "Dear Ada," in text and "Amount: 10.50" in text
    assert "Dear Grace," in text and "Amount: 00123" in text  # leading zeros survive
    assert "MERGEFIELD" not in text
    root = _docx.load_document(ctx.workspace / "out.docx")
    sections = list(root.iter(_docx.w("sectPr")))
    assert len(sections) == 2  # one per record: the first ends in its last paragraph
    assert all(s.find(_docx.w("type")).get(_docx.w("val")) == "nextPage" for s in sections)
    assert root.find(_docx.w("body")).find(_docx.w("sectPr")) is sections[-1]
    # the bold formatting of the simple field is carried onto the merged value
    assert any(r.find(_docx.w("rPr")) is not None for r in root.iter(_docx.w("r")))


def test_merged_drawings_get_unique_ids_and_quoted_field_names(ctx) -> None:
    wp = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    drawing = (
        f'<w:p><w:r><w:drawing><wp:inline xmlns:wp="{wp}"><wp:docPr id="7" name="Logo"/>'
        "</wp:inline></w:drawing></w:r></w:p>"
    )
    quoted = '<w:fldSimple w:instr=" MERGEFIELD &quot;First Name&quot; "><w:r><w:t>x</w:t></w:r></w:fldSimple>'
    write_docx(ctx.workspace / "logo.docx", drawing + f"<w:p>{quoted}</w:p>")
    result = document(
        ctx,
        operation="mail_merge",
        path="logo.docx",
        rows=[{"First Name": "Ada"}, {"First Name": "Grace"}, {"First Name": "Lin"}],
        output_path="logo-out.docx",
    )
    assert result.outcome == Outcome.DONE, result.message
    root = _docx.load_document(ctx.workspace / "logo-out.docx")
    ids = [n.get("id") for n in root.iter(f"{{{wp}}}docPr")]
    assert len(ids) == 3 and len(set(ids)) == 3
    assert "Ada" in text_of(ctx, "logo-out.docx") and "Lin" in text_of(ctx, "logo-out.docx")


def test_mail_merge_from_inline_rows_and_excel(ctx) -> None:
    make_template(ctx)
    rows = document(
        ctx,
        operation="mail_merge",
        path="letter.docx",
        rows=[{"Name": "Lin", "Amount": 5}, {"name": "Case-insensitive", "Amount": 2.0}],
        output_path="rows.docx",
    )
    assert rows.outcome == Outcome.DONE, rows.message
    text = text_of(ctx, "rows.docx")
    assert "Dear Lin," in text and "Dear Case-insensitive," in text and "Amount: 2" in text
    assert not any(p.name.startswith(".uaf") for p in ctx.workspace.iterdir())

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "People"
    sheet.append(["Name", "Amount"])
    sheet.append(["Xu", 7])
    book.save(ctx.workspace / "people.xlsx")
    excel = document(
        ctx,
        operation="mail_merge",
        path="letter.docx",
        data_path="people.xlsx",
        sheet="People",
        output_path="x.docx",
    )
    assert excel.outcome == Outcome.DONE, excel.message
    assert "Dear Xu," in text_of(ctx, "x.docx")


def test_mail_merge_refuses_empty_recipients_and_overwriting_the_template(ctx) -> None:
    make_template(ctx)
    (ctx.workspace / "none.csv").write_text("Name,Amount\n", encoding="utf-8")
    empty = document(ctx, operation="mail_merge", path="letter.docx", data_path="none.csv")
    assert empty.outcome == Outcome.FAILED
    same = document(
        ctx,
        operation="mail_merge",
        path="letter.docx",
        rows=[{"Name": "a"}],
        output_path="letter.docx",
    )
    assert same.outcome == Outcome.FAILED


def test_text_info_and_convert(ctx) -> None:
    make_template(ctx)
    text = document(ctx, operation="text", path="letter.docx")
    assert text.outcome == Outcome.DONE, text.message
    assert text.outputs["preview"].startswith("Invoice\nDear x,")

    info = document(ctx, operation="info", path="letter.docx")
    assert info.outputs["info"]["merge_fields"] == ["Name", "Amount"]
    assert info.outputs["info"]["title"] == "Letter"
    assert info.outputs["info"]["creator"] == "Ada"

    md = document(ctx, operation="convert", path="letter.docx", output_path="l.md")
    assert md.outcome == Outcome.DONE, md.message
    assert (ctx.workspace / "l.md").read_text(encoding="utf-8").startswith("# Invoice")
    document(ctx, operation="convert", path="letter.docx", output_path="l.html")
    assert "<h1>Invoice</h1>" in (ctx.workspace / "l.html").read_text(encoding="utf-8")


def test_markup_is_escaped_and_tables_render(ctx) -> None:
    table = (
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>a&lt;b</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>2</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )
    write_docx(ctx.workspace / "t.docx", paragraph("x &amp; <![CDATA[y]]>", bold=True) + table)
    document(ctx, operation="convert", path="t.docx", output_path="t.html")
    page = (ctx.workspace / "t.html").read_text(encoding="utf-8")
    assert "<strong>x &amp; y</strong>" in page and "a&lt;b" in page and "<table>" in page
    document(ctx, operation="convert", path="t.docx", output_path="t.md")
    assert "| a<b | 2 |" in (ctx.workspace / "t.md").read_text(encoding="utf-8")


def test_hostile_files_and_paths_are_refused(ctx, tmp_path) -> None:
    (ctx.workspace / "bad.docx").write_bytes(b"not a zip")
    assert document(ctx, operation="info", path="bad.docx").outcome == Outcome.FAILED
    with zipfile.ZipFile(ctx.workspace / "nodoc.docx", "w") as archive:
        archive.writestr("x.txt", "hi")
    assert document(ctx, operation="info", path="nodoc.docx").outcome == Outcome.FAILED
    outside = tmp_path / "outside.docx"
    write_docx(outside, paragraph("secret"))
    assert document(ctx, operation="text", path="../outside.docx").outcome == Outcome.FAILED
    marker = tmp_path / "marker.txt"
    marker.write_text("TOP-SECRET-MARKER", encoding="utf-8")
    entity = (
        f'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY e SYSTEM "{marker.as_uri()}">]>'
        f'<w:document xmlns:w="{_docx.W}"><w:body><w:p><w:r><w:t>&e;</w:t></w:r></w:p></w:body></w:document>'
    )
    with zipfile.ZipFile(ctx.workspace / "xxe.docx", "w") as archive:
        archive.writestr("word/document.xml", entity)
    result = document(ctx, operation="text", path="xxe.docx")
    assert "TOP-SECRET-MARKER" not in str(result.outputs) + result.message
    assert "TOP-SECRET-MARKER" not in "".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in ctx.workspace.glob("*.txt")
    )
