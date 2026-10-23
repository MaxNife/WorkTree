"""The `spreadsheet` activity on the GridCraft engine, and `excel` recalculation through it.

Needs a built ``gridcraft-cli``: set ``UAF_TEST_GRIDCRAFT_CLI`` to its path, or put it on PATH
(build: ``cargo build --release -p gridcraft-cli`` in CraftApps/gridcraft). Skipped otherwise.
"""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import xlsxwriter
from pydantic import ValidationError
from python_calamine import CalamineWorkbook

from activities.files import ExcelActivity
from activities.spreadsheet import SpreadsheetActivity, SpreadsheetInputs
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome

ENGINE = os.environ.get("UAF_TEST_GRIDCRAFT_CLI") or shutil.which("gridcraft-cli") or ""
needs_engine = pytest.mark.skipif(
    not ENGINE or not Path(ENGINE).is_file(), reason="gridcraft-cli not available"
)
PAYMENT_300K = 1610.4648690364195  # PMT(5%/12, 360, -300000)


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ActivityContext:
    monkeypatch.setenv("UAF_CHILD_GRIDCRAFT_CLI", ENGINE)
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


def cached(path: Path, row: int, column: int) -> Any:
    return CalamineWorkbook.from_path(str(path)).get_sheet_by_name("Loan").to_python()[row][column]


def test_missing_engine_is_a_clear_failure(ctx, monkeypatch) -> None:
    monkeypatch.setenv("UAF_CHILD_GRIDCRAFT_CLI", str(ctx.workspace / "none.exe"))
    loan_model(ctx)
    result = sheet(ctx, operation="recalculate", path="loan.xlsx")
    assert result.outcome == Outcome.FAILED
    assert "gridcraft-cli is not installed" in result.message


def test_inputs_are_checked_before_the_engine_runs() -> None:
    with pytest.raises(ValidationError, match="not a cell address"):
        SpreadsheetInputs(operation="calculate", values={"A1;rm": 1})
    with pytest.raises(ValidationError, match="must start with '='"):
        SpreadsheetInputs(operation="calculate", formulas={"A1": "SUM(B1)"})
    with pytest.raises(ValidationError, match="not a range"):
        SpreadsheetInputs(operation="read_range", range="A1:B2;C3")
    with pytest.raises(ValidationError, match="convert needs an output_path"):
        SpreadsheetInputs(operation="convert", output_path="out.exe")


@needs_engine
def test_recalculate_gives_an_xlsxwriter_workbook_real_values(ctx) -> None:
    path = loan_model(ctx)
    assert cached(path, 1, 3) == 0.0  # what xlsxwriter stores for a formula
    result = sheet(ctx, operation="recalculate", path="loan.xlsx")
    assert result.outcome == Outcome.DONE, result.message
    assert cached(path, 1, 3) == pytest.approx(PAYMENT_300K)
    assert cached(path, 3, 3) == pytest.approx(PAYMENT_300K * 360)
    assert not list(ctx.workspace.glob(".*uaf-tmp*")), "no temporary file left behind"


@needs_engine
def test_excel_recalculate_uses_gridcraft_when_installed(ctx) -> None:
    result = ExcelActivity().execute(
        ctx,
        {
            "operation": "write",
            "path": "calc.xlsx",
            "rows": [{"a": 2, "b": 3}],
            "recalculate": True,
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    set_formula = ExcelActivity().execute(
        ctx,
        {
            "operation": "set_cells",
            "path": "calc.xlsx",
            "cells": {"C2": "=A2*B2"},
            "recalculate": True,
        },
    )
    assert set_formula.outcome == Outcome.DONE, set_formula.message
    rows = CalamineWorkbook.from_path(str(ctx.workspace / "calc.xlsx")).get_sheet_by_index(0)
    assert rows.to_python()[1][2] == 6


@needs_engine
def test_calculate_fills_inputs_and_reads_results(ctx) -> None:
    loan_model(ctx)
    result = sheet(
        ctx,
        operation="calculate",
        path="loan.xlsx",
        sheet="Loan",
        values={"A2": 150000, "F1": '=HYPERLINK("http://evil")'},
        formulas={"F2": "=D2*2"},
        read=["D2", "D4", "F1:F2"],
        output_path="quote.xlsx",
    )
    assert result.outcome == Outcome.DONE, result.message
    results = result.outputs["results"]
    assert results["D2"][0][0] == pytest.approx(PAYMENT_300K / 2, rel=1e-9)
    assert results["D4"][0][0] == pytest.approx(PAYMENT_300K / 2 * 360, rel=1e-9)
    # Data that looks like a formula stays text; formulas come only from `formulas`.
    assert results["F1:F2"][0][0] == '=HYPERLINK("http://evil")'
    assert results["F1:F2"][1][0] == pytest.approx(PAYMENT_300K, rel=1e-9)
    assert result.outputs["files"] == ["quote.xlsx"]
    assert cached(ctx.workspace / "loan.xlsx", 1, 0) == 300000, "the model itself is unchanged"


@needs_engine
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
    frame = pd.read_parquet(ctx.workspace / "loan.parquet")
    assert list(frame.columns) == ["principal", "rate", "years", "payment", "account"]


@needs_engine
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

    converted = sheet(
        ctx, operation="convert", path="loan.xlsx", sheet="Loan", output_path="loan.csv"
    )
    assert converted.outcome == Outcome.DONE, converted.message
    assert "1610.46" in (ctx.workspace / "loan.csv").read_text(encoding="utf-8")


@needs_engine
def test_check_finds_a_stored_result_that_does_not_match(ctx) -> None:
    path = loan_model(ctx)
    sheet(ctx, operation="recalculate", path="loan.xlsx")
    clean = sheet(ctx, operation="check", path="loan.xlsx")
    assert clean.outcome == Outcome.DONE, clean.message
    assert clean.outputs["mismatched"] == 0 and clean.outputs["matched"] == 2

    # Tamper with the stored payment, as a hand-edited or corrupted file would.
    tampered = ctx.workspace / "tampered.xlsx"
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(tampered, "w") as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename.startswith("xl/worksheets/sheet"):
                data = re.sub(rb"(<c r=\"D2\"[^>]*>.*?<v>)[^<]+(</v>)", rb"\g<1>999\g<2>", data)
            target.writestr(item, data)
    found = sheet(ctx, operation="check", path="tampered.xlsx")
    assert found.outcome == Outcome.FAILED
    assert found.outputs["mismatched"] >= 1
    assert any(m["cell"].endswith("D2") for m in found.outputs["mismatches"])
    report_only = sheet(ctx, operation="check", path="tampered.xlsx", fail_on_mismatch=False)
    assert report_only.outcome == Outcome.DONE
