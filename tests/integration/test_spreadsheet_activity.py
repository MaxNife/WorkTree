"""The ``spreadsheet`` activity on the pure-Python formula engine, and ``excel`` recalculation.

These tests use the real engine: no calculator binary, environment variable or skip is needed.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

import openpyxl
import pandas as pd
import pytest
import xlsxwriter
from openpyxl.chart import BarChart, Reference
from pydantic import ValidationError
from python_calamine import CalamineWorkbook

from activities.spreadsheet import SpreadsheetActivity, SpreadsheetInputs
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome

PAYMENT_300K = 1610.4648690364195  # PMT(5%/12, 360, -300000)


@pytest.fixture
def ctx(tmp_path: Path) -> ActivityContext:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return ActivityContext(
        run_id="grid", step_id="s", workspace=workspace, clock=FakeClock(), correlation_id="c"
    )


def sheet(ctx: ActivityContext, **inputs: Any) -> Any:
    return SpreadsheetActivity().execute(ctx, inputs)


def loan_model(ctx: ActivityContext, name: str = "loan.xlsx") -> Path:
    """Formulas written by xlsxwriter, which stores no calculated results."""
    path = ctx.workspace / name
    book = xlsxwriter.Workbook(path)
    ws = book.add_worksheet("Loan")
    ws.write_row(0, 0, ["principal", "rate", "years", "payment", "account"])
    ws.write_row(1, 0, [300000, 0.05, 30])
    ws.write_formula(1, 3, "=PMT(B2/12,C2*12,-A2)")
    ws.write_string(1, 4, "001234")
    ws.write(3, 0, "total")
    ws.write_formula(3, 3, "=D2*C2*12")
    book.close()
    return path


def cached(path: Path, row: int, column: int, sheet_name: str = "Loan") -> Any:
    return (
        CalamineWorkbook.from_path(str(path)).get_sheet_by_name(sheet_name).to_python()[row][column]
    )


def test_inputs_are_checked_before_the_engine_runs() -> None:
    with pytest.raises(ValidationError, match="not a cell address"):
        SpreadsheetInputs(operation="calculate", values={"A1;rm": 1})
    with pytest.raises(ValidationError, match="must start with '='"):
        SpreadsheetInputs(operation="calculate", formulas={"A1": "SUM(B1)"})
    with pytest.raises(ValidationError, match="not a range"):
        SpreadsheetInputs(operation="read_range", range="A1:B2;C3")
    with pytest.raises(ValidationError, match="convert needs an output_path"):
        SpreadsheetInputs(operation="convert", output_path="out.exe")
    with pytest.raises(ValidationError, match="calculate needs values or formulas"):
        SpreadsheetInputs(operation="calculate")
    with pytest.raises(ValidationError, match="evaluate needs a formula"):
        SpreadsheetInputs(operation="evaluate", path="", formula="SUM(A1)")


def test_recalculate_gives_an_xlsxwriter_workbook_real_values(ctx) -> None:
    path = loan_model(ctx)
    assert cached(path, 1, 3) == 0.0  # what xlsxwriter stores for a formula
    result = sheet(ctx, operation="recalculate", path="loan.xlsx")
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["files"] == ["loan.xlsx"]
    assert cached(path, 1, 3) == pytest.approx(PAYMENT_300K)
    assert cached(path, 3, 3) == pytest.approx(PAYMENT_300K * 360)
    assert not list(ctx.workspace.glob(".*worktree-*")), "no temporary file left behind"

    # The writer marks the workbook for a full recalculation in Excel.
    with zipfile.ZipFile(path) as archive:
        workbook_xml = archive.read("xl/workbook.xml")
    assert b'fullCalcOnLoad="1"' in workbook_xml


def test_recalculate_writes_a_copy_and_leaves_the_source_alone(ctx) -> None:
    source = loan_model(ctx)
    result = sheet(ctx, operation="recalculate", path="loan.xlsx", output_path="copy.xlsx")
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["files"] == ["copy.xlsx"]
    assert cached(source, 1, 3) == 0.0
    assert cached(ctx.workspace / "copy.xlsx", 1, 3) == pytest.approx(PAYMENT_300K)


def test_calculate_fills_inputs_and_reads_results(ctx) -> None:
    loan_model(ctx)
    result = sheet(
        ctx,
        operation="calculate",
        path="loan.xlsx",
        sheet="Loan",
        values={
            "A2": 150000,
            "F1": '=HYPERLINK("http://evil")',
            "G1": "00123",
        },
        formulas={"F2": "=D2*2"},
        read=["D2", "D4", "F1:G2"],
        output_path="quote.xlsx",
    )
    assert result.outcome == Outcome.DONE, result.message
    results = result.outputs["results"]
    assert results["D2"][0][0] == pytest.approx(PAYMENT_300K / 2, rel=1e-9)
    assert results["D4"][0][0] == pytest.approx(PAYMENT_300K / 2 * 360, rel=1e-9)
    # Data that looks like a formula stays text; formulas come only from `formulas`.
    assert results["F1:G2"][0][0] == '=HYPERLINK("http://evil")'
    assert results["F1:G2"][0][1] == "00123"
    assert results["F1:G2"][1][0] == pytest.approx(PAYMENT_300K, rel=1e-9)
    assert result.outputs["files"] == ["quote.xlsx"]
    assert cached(ctx.workspace / "loan.xlsx", 1, 0) == 300000, "the model itself is unchanged"

    # The output keeps the explicit formula and the calculated cached value.
    saved = openpyxl.load_workbook(ctx.workspace / "quote.xlsx")
    try:
        assert saved["Loan"]["F2"].value == "=D2*2"
        assert saved["Loan"]["F1"].value == '=HYPERLINK("http://evil")'
        assert saved["Loan"]["G1"].value == "00123"
    finally:
        saved.close()
    assert cached(ctx.workspace / "quote.xlsx", 1, 5) == pytest.approx(PAYMENT_300K)


def test_calculate_rejects_non_finite_values(ctx) -> None:
    loan_model(ctx)
    result = sheet(
        ctx,
        operation="calculate",
        path="loan.xlsx",
        sheet="Loan",
        values={"A2": float("inf")},
    )
    assert result.outcome == Outcome.FAILED
    assert "not finite" in result.message
    assert not (ctx.workspace / "loan-calculated.xlsx").exists()


def test_read_range_keeps_text_like_account_numbers(ctx) -> None:
    loan_model(ctx)
    result = sheet(
        ctx,
        operation="read_range",
        path="loan.xlsx",
        sheet="Loan",
        range="A1:E2",
        output_path="loan.parquet",
    )
    assert result.outcome == Outcome.DONE, result.message
    [row] = result.outputs["preview"]
    assert row["account"] == "001234"
    assert row["payment"] == pytest.approx(PAYMENT_300K, rel=1e-6)
    assert result.outputs["rows"] == 1
    frame = pd.read_parquet(ctx.workspace / "loan.parquet")
    assert list(frame.columns) == ["principal", "rate", "years", "payment", "account"]


def test_read_range_without_a_header_uses_column_names(ctx) -> None:
    loan_model(ctx)
    result = sheet(
        ctx,
        operation="read_range",
        path="loan.xlsx",
        sheet="Loan",
        range="A2:B2",
        header=False,
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["preview"] == [{"column_1": 300000, "column_2": 0.05}]


def test_evaluate_and_convert(ctx) -> None:
    loan_model(ctx)
    alone = sheet(ctx, operation="evaluate", path="", formula="=ROUND(PMT(5%/12,360,-300000),2)")
    assert alone.outcome == Outcome.DONE, alone.message
    assert alone.outputs["value"] == 1610.46
    against = sheet(ctx, operation="evaluate", path="loan.xlsx", sheet="Loan", formula="=A2+C2")
    assert against.outputs["value"] == 300030
    no_network = sheet(
        ctx, operation="evaluate", path="", formula='=WEBSERVICE("http://127.0.0.1:9")'
    )
    assert no_network.outputs["value"] == {"error": "#VALUE!"}
    divided_by_zero = sheet(ctx, operation="evaluate", path="", formula="=1/0")
    assert divided_by_zero.outputs["value"] == {"error": "#DIV/0!"}

    converted = sheet(
        ctx, operation="convert", path="loan.xlsx", sheet="Loan", output_path="loan.csv"
    )
    assert converted.outcome == Outcome.DONE, converted.message
    text = (ctx.workspace / "loan.csv").read_text(encoding="utf-8")
    assert "1610.46" in text
    assert "001234" in text


def test_convert_csv_to_xlsx_keeps_text_and_formula_looking_data(ctx) -> None:
    (ctx.workspace / "accounts.csv").write_text(
        'account,amount,note\n00123,42.50,=HYPERLINK("http://evil")\n',
        encoding="utf-8",
    )
    converted = sheet(ctx, operation="convert", path="accounts.csv", output_path="accounts.xlsx")
    assert converted.outcome == Outcome.DONE, converted.message
    assert cached(ctx.workspace / "accounts.xlsx", 1, 0, "Sheet1") == "00123"
    assert cached(ctx.workspace / "accounts.xlsx", 1, 2, "Sheet1") == '=HYPERLINK("http://evil")'
    assert cached(ctx.workspace / "accounts.xlsx", 1, 1, "Sheet1") == 42.5

    as_json = sheet(ctx, operation="convert", path="accounts.xlsx", output_path="accounts.json")
    assert as_json.outcome == Outcome.DONE, as_json.message
    assert '"account": "00123"' in (ctx.workspace / "accounts.json").read_text(encoding="utf-8")

    as_html = sheet(ctx, operation="convert", path="accounts.xlsx", output_path="accounts.html")
    assert as_html.outcome == Outcome.DONE, as_html.message
    assert "00123" in (ctx.workspace / "accounts.html").read_text(encoding="utf-8")


def test_convert_xlsx_to_xlsx_preserves_charts(ctx) -> None:
    path = ctx.workspace / "chart.xlsx"
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "Data"
    ws["A1"] = 1
    ws["A2"] = 2
    ws["B1"] = "=A1*2"
    chart = BarChart()
    chart.add_data(Reference(ws, min_col=1, min_row=1, max_row=2))
    ws.add_chart(chart, "D2")
    book.save(path)
    book.close()

    result = sheet(ctx, operation="convert", path="chart.xlsx", output_path="chart-out.xlsx")
    assert result.outcome == Outcome.DONE, result.message
    with zipfile.ZipFile(ctx.workspace / "chart-out.xlsx") as archive:
        names = archive.namelist()
    assert any(name.startswith("xl/charts/chart") for name in names)
    assert cached(ctx.workspace / "chart-out.xlsx", 0, 1, "Data") == 2


def _replace_cached(path: Path, cell: str, text: str) -> None:
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(path.with_suffix(".tmp"), "w") as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename.startswith("xl/worksheets/sheet"):
                data = re.sub(
                    rb'(<c r="' + cell.encode() + rb'"[^>]*>.*?<v>)[^<]+(</v>)',
                    rb"\g<1>" + text.encode() + rb"\g<2>",
                    data,
                )
            target.writestr(item, data)
    path.with_suffix(".tmp").replace(path)


def test_check_finds_a_stored_result_that_does_not_match(ctx) -> None:
    path = loan_model(ctx)
    sheet(ctx, operation="recalculate", path="loan.xlsx")
    clean = sheet(ctx, operation="check", path="loan.xlsx")
    assert clean.outcome == Outcome.DONE, clean.message
    assert clean.outputs["formula_cells"] == 2
    assert clean.outputs["checked"] == 2
    assert clean.outputs["mismatched"] == 0 and clean.outputs["matched"] == 2
    assert clean.outputs["no_stored_result"] == 0

    # Tamper with the stored payment, as a hand-edited or corrupted file would.
    tampered = ctx.workspace / "tampered.xlsx"
    tampered.write_bytes(path.read_bytes())
    _replace_cached(tampered, "D2", "999")
    found = sheet(ctx, operation="check", path="tampered.xlsx")
    assert found.outcome == Outcome.FAILED
    assert found.outputs["mismatched"] >= 1
    mismatch = next(m for m in found.outputs["mismatches"] if m["cell"].endswith("D2"))
    assert mismatch["formula"] == "=PMT(B2/12,C2*12,-A2)"
    assert mismatch["kind"] == "numeric"
    report_only = sheet(ctx, operation="check", path="tampered.xlsx", fail_on_mismatch=False)
    assert report_only.outcome == Outcome.DONE

    # A small difference is inside the requested tolerance and is not a mismatch.
    tolerant = ctx.workspace / "tolerant.xlsx"
    tolerant.write_bytes(path.read_bytes())
    _replace_cached(tolerant, "D2", str(PAYMENT_300K + 1e-5))
    assert sheet(ctx, operation="check", path="tolerant.xlsx").outcome == Outcome.FAILED
    assert (
        sheet(ctx, operation="check", path="tolerant.xlsx", tolerance=1e-3).outcome == Outcome.DONE
    )


def test_check_reports_formulas_without_a_stored_result(ctx) -> None:
    path = ctx.workspace / "uncached.xlsx"
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "Sheet1"
    ws["A1"] = 1
    ws["A2"] = "=A1+1"
    book.save(path)
    book.close()

    result = sheet(ctx, operation="check", path="uncached.xlsx")
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["formula_cells"] == 1
    assert result.outputs["checked"] == 0
    assert result.outputs["no_stored_result"] == 1


def test_paths_cannot_escape_the_workspace(ctx) -> None:
    loan_model(ctx)
    result = sheet(ctx, operation="recalculate", path="../outside.xlsx")
    assert result.outcome == Outcome.FAILED
    assert "escapes the run workspace" in result.message
    assert not (ctx.workspace.parent / "outside.xlsx").exists()
