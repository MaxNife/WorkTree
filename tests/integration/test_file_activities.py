"""CP-23: CSV/Excel/ZIP/text tools, streaming, caps and the 1M-row memory gate."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import openpyxl
import pandas as pd
import psutil
import pytest
import pyzipper

from activities import files as files_module
from activities.files import CsvActivity, ExcelActivity, TxtLogActivity, ZipActivity
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome
from fixtures.data import FIXED_WIDTH_WIDTHS, ZIP_PASSWORD

REPO = Path(__file__).resolve().parents[2]


def _ctx(workspace: Path) -> ActivityContext:
    workspace.mkdir(parents=True, exist_ok=True)
    return ActivityContext(
        run_id="files", step_id="s", workspace=workspace, clock=FakeClock(), correlation_id="c"
    )


def _json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- CSV
def test_csv_read_streams_to_every_output_format(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    with (ctx.workspace / "invoices.csv").open("w", encoding="utf-8", newline="") as handle:
        handle.write("invoice_id,amount,posted_at\n")
        for index in range(120):
            handle.write(f"INV-{index:04d},{index / 100:.2f},2026-01-01\n")
    activity = CsvActivity()
    parquet = activity.execute(
        ctx,
        {
            "operation": "read",
            "path": "invoices.csv",
            "output_path": "invoices.parquet",
            "chunk_size": 7,
        },
    )
    assert parquet.outcome == Outcome.DONE, parquet.message
    assert parquet.outputs["rows"] == 120
    frame = pd.read_parquet(ctx.workspace / "invoices.parquet")
    assert len(frame) == 120
    assert frame.iloc[0]["invoice_id"] == "INV-0000"

    csv_out = activity.execute(
        ctx,
        {
            "operation": "read",
            "path": "invoices.csv",
            "output_path": "head.csv",
            "output_format": "csv",
            "max_rows": 5,
            "chunk_size": 3,
        },
    )
    assert csv_out.outcome == Outcome.DONE, csv_out.message
    assert csv_out.outputs["rows"] == 5
    assert len((ctx.workspace / "head.csv").read_text(encoding="utf-8").splitlines()) == 6

    json_out = activity.execute(
        ctx,
        {
            "operation": "read",
            "path": "invoices.csv",
            "output_path": "invoices.json",
            "output_format": "json",
            "chunk_size": 50,
        },
    )
    assert json_out.outcome == Outcome.DONE, json_out.message
    rows = _json(ctx.workspace / "invoices.json")
    assert len(rows) == 120 and rows[-1]["invoice_id"] == "INV-0119"


def test_csv_read_uses_the_declared_encoding_and_delimiter(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    (ctx.workspace / "latin.csv").write_bytes("name;city\nCafé;Zürich\n".encode("cp1252"))
    result = CsvActivity().execute(
        ctx,
        {
            "operation": "read",
            "path": "latin.csv",
            "encoding": "cp1252",
            "delimiter": ";",
            "output_path": "latin.json",
            "output_format": "json",
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert _json(ctx.workspace / "latin.json") == [{"name": "Café", "city": "Zürich"}]


def test_csv_read_fwf_uses_widths_names_and_string_dtype(
    generated_data: dict[str, Path], tmp_path: Path
) -> None:
    ctx = _ctx(tmp_path / "ws")
    shutil.copyfile(generated_data["fixed_width"], ctx.workspace / "invoices.fixed")
    result = CsvActivity().execute(
        ctx,
        {
            "operation": "read_fwf",
            "path": "invoices.fixed",
            "widths": [width for _, width in FIXED_WIDTH_WIDTHS],
            "names": [name for name, _ in FIXED_WIDTH_WIDTHS],
            "output_path": "fixed.parquet",
            "max_rows": 500,
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["rows"] == 500
    frame = pd.read_parquet(ctx.workspace / "fixed.parquet")
    assert frame.iloc[0].to_dict() == {
        "invoice_id": "INV0000000",
        "supplier": "Supplier 00",
        "amount": "0.00",
        "posted_at": "2026-01-01",
    }


def test_csv_read_fwf_requires_widths_and_names(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    (ctx.workspace / "fixed.txt").write_text("abc\n", encoding="utf-8")
    no_widths = CsvActivity().execute(ctx, {"operation": "read_fwf", "path": "fixed.txt"})
    assert no_widths.outcome == Outcome.FAILED
    assert "widths are required" in no_widths.message
    no_names = CsvActivity().execute(
        ctx, {"operation": "read_fwf", "path": "fixed.txt", "widths": [3]}
    )
    assert no_names.outcome == Outcome.FAILED
    assert "names are required" in no_names.message


def test_csv_write_append_and_source_path(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    activity = CsvActivity()
    written = activity.execute(
        ctx,
        {
            "operation": "write",
            "path": "out.csv",
            "rows": [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}],
        },
    )
    assert written.outcome == Outcome.DONE, written.message
    appended = activity.execute(
        ctx,
        {"operation": "append", "path": "out.csv", "rows": [{"b": "6", "a": "5"}]},
    )
    assert appended.outcome == Outcome.DONE, appended.message
    with (ctx.workspace / "out.csv").open(encoding="utf-8", newline="") as handle:
        assert list(csv.reader(handle)) == [
            ["a", "b"],
            ["1", "2"],
            ["3", "4"],
            ["5", "6"],
        ]

    pd.DataFrame([{"a": "7", "b": "8"}]).to_parquet(ctx.workspace / "source.parquet", index=False)
    from_source = activity.execute(
        ctx, {"operation": "write", "path": "from-parquet.csv", "source_path": "source.parquet"}
    )
    assert from_source.outcome == Outcome.DONE, from_source.message
    assert (ctx.workspace / "from-parquet.csv").read_text(encoding="utf-8").splitlines() == [
        "a,b",
        "7,8",
    ]


def test_csv_empty_file_is_an_empty_table(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    (ctx.workspace / "empty.csv").write_text("", encoding="utf-8")
    result = CsvActivity().execute(
        ctx,
        {
            "operation": "read",
            "path": "empty.csv",
            "output_path": "empty.parquet",
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["rows"] == 0
    assert pd.read_parquet(ctx.workspace / "empty.parquet").empty


# ----------------------------------------------------------------------------- Excel
def test_excel_sheets_and_read_realistic_workbook(
    generated_data: dict[str, Path], tmp_path: Path
) -> None:
    ctx = _ctx(tmp_path / "ws")
    shutil.copyfile(generated_data["excel"], ctx.workspace / "invoices.xlsx")
    activity = ExcelActivity()
    sheets = activity.execute(ctx, {"operation": "sheets", "path": "invoices.xlsx"})
    assert sheets.outcome == Outcome.DONE, sheets.message
    assert sheets.outputs["sheets"] == ["Invoices"]

    read = activity.execute(
        ctx,
        {
            "operation": "read",
            "path": "invoices.xlsx",
            "sheet": "Invoices",
            "output_path": "invoices.parquet",
            "max_rows": 500,
        },
    )
    assert read.outcome == Outcome.DONE, read.message
    assert read.outputs["rows"] == 500
    frame = pd.read_parquet(ctx.workspace / "invoices.parquet")
    assert list(frame.columns) == ["invoice_id", "supplier", "amount", "currency", "posted_at"]
    assert frame.iloc[0]["invoice_id"] == "INV-0000000"


def test_excel_write_styles_and_set_cells(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    activity = ExcelActivity()
    written = activity.execute(
        ctx,
        {
            "operation": "write",
            "path": "out.xlsx",
            "sheet": "Ledger",
            "rows": [
                {"account": "1000", "amount": "42.50"},
                {"account": "2000", "amount": "-42.50"},
            ],
        },
    )
    assert written.outcome == Outcome.DONE, written.message
    book = openpyxl.load_workbook(ctx.workspace / "out.xlsx")
    try:
        sheet = book["Ledger"]
        assert sheet["A1"].value == "account" and sheet["A1"].font.bold
        assert sheet["B2"].value == "42.50"
    finally:
        book.close()

    updated = activity.execute(
        ctx,
        {
            "operation": "set_cells",
            "path": "out.xlsx",
            "sheet": "Ledger",
            "cells": {"B2": 99.5, "C1": "checked"},
        },
    )
    assert updated.outcome == Outcome.DONE, updated.message
    book = openpyxl.load_workbook(ctx.workspace / "out.xlsx")
    try:
        assert book["Ledger"]["B2"].value == 99.5
        assert book["Ledger"]["C1"].value == "checked"
    finally:
        book.close()


def test_excel_recalculate_fails_clearly_when_libreoffice_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path / "ws")
    monkeypatch.setattr(files_module.shutil, "which", lambda name: None)
    result = ExcelActivity().execute(
        ctx,
        {
            "operation": "write",
            "path": "out.xlsx",
            "rows": [{"a": "1"}],
            "recalculate": True,
        },
    )
    assert result.outcome == Outcome.FAILED
    assert "G9" in result.message and "LibreOffice" in result.message


# ----------------------------------------------------------------------------- ZIP
def test_zip_create_list_and_extract_with_aes(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    (ctx.workspace / "a.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (ctx.workspace / "b.txt").write_text("notes\n", encoding="utf-8")
    activity = ZipActivity()
    created = activity.execute(
        ctx,
        {
            "operation": "create",
            "path": "archive.zip",
            "files": ["a.csv", "b.txt"],
            "password": "fixture-password",
        },
    )
    assert created.outcome == Outcome.DONE, created.message
    assert created.outputs["path"] == "archive.zip"
    with pyzipper.AESZipFile(ctx.workspace / "archive.zip") as archive:
        assert archive.namelist() == ["a.csv", "b.txt"]

    listed = activity.execute(
        ctx, {"operation": "list", "path": "archive.zip", "password": "fixture-password"}
    )
    assert listed.outcome == Outcome.DONE, listed.message
    assert listed.outputs["count"] == 2

    denied = activity.execute(
        ctx,
        {
            "operation": "extract",
            "path": "archive.zip",
            "output_dir": "bad",
            "password": "wrong",
        },
    )
    assert denied.outcome == Outcome.FAILED
    assert not any((ctx.workspace / "bad").glob("*"))

    extracted = activity.execute(
        ctx,
        {
            "operation": "extract",
            "path": "archive.zip",
            "output_dir": "extracted",
            "password": "fixture-password",
        },
    )
    assert extracted.outcome == Outcome.DONE, extracted.message
    assert extracted.outputs["count"] == 2
    assert (ctx.workspace / "extracted" / "a.csv").read_text(encoding="utf-8") == "a,b\n1,2\n"


def test_zip_rejects_zip_slip_and_cleans_up(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    with zipfile.ZipFile(ctx.workspace / "slip.zip", "w") as archive:
        archive.writestr("good.txt", "ok")
        archive.writestr("../escape.txt", "escaped")
    result = ZipActivity().execute(
        ctx, {"operation": "extract", "path": "slip.zip", "output_dir": "out"}
    )
    assert result.outcome == Outcome.FAILED
    assert "escapes the output folder" in result.message
    assert not (ctx.workspace / "escape.txt").exists()
    assert not (ctx.workspace / "out" / "good.txt").exists(), "partial extraction is removed"


def test_zip_rejects_size_and_entry_bombs(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    with zipfile.ZipFile(ctx.workspace / "bomb.zip", "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.txt", b"0" * 2_000_000)
    too_big = ZipActivity().execute(
        ctx,
        {
            "operation": "extract",
            "path": "bomb.zip",
            "output_dir": "bomb-out",
            "max_total_bytes": 1_000,
        },
    )
    assert too_big.outcome == Outcome.FAILED
    assert "size cap" in too_big.message
    assert not any((ctx.workspace / "bomb-out").glob("*"))

    with zipfile.ZipFile(ctx.workspace / "many.zip", "w") as z:
        for index in range(3):
            z.writestr(f"f{index}.txt", "x")
    too_many = ZipActivity().execute(
        ctx,
        {"operation": "extract", "path": "many.zip", "output_dir": "many-out", "max_entries": 2},
    )
    assert too_many.outcome == Outcome.FAILED
    assert "entry cap" in too_many.message
    assert not any((ctx.workspace / "many-out").glob("*"))


def test_zip_round_trips_a_realistic_workbook(
    generated_data: dict[str, Path], tmp_path: Path
) -> None:
    ctx = _ctx(tmp_path / "ws")
    shutil.copyfile(generated_data["excel"], ctx.workspace / "invoices.xlsx")
    created = ZipActivity().execute(
        ctx,
        {
            "operation": "create",
            "path": "invoices.zip",
            "files": ["invoices.xlsx"],
            "password": ZIP_PASSWORD,
        },
    )
    assert created.outcome == Outcome.DONE, created.message
    extracted = ZipActivity().execute(
        ctx,
        {
            "operation": "extract",
            "path": "invoices.zip",
            "output_dir": "unpacked",
            "password": ZIP_PASSWORD,
        },
    )
    assert extracted.outcome == Outcome.DONE, extracted.message
    read = ExcelActivity().execute(
        ctx,
        {"operation": "read", "path": "unpacked/invoices.xlsx", "sheet": "Invoices"},
    )
    assert read.outcome == Outcome.DONE, read.message
    assert read.outputs["rows"] == 500


# ----------------------------------------------------------------------------- text log
def test_txt_log_write_append_and_tail(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    activity = TxtLogActivity()
    written = activity.execute(
        ctx, {"operation": "write", "path": "run.log", "lines": ["first", "second"]}
    )
    assert written.outcome == Outcome.DONE, written.message
    appended = activity.execute(ctx, {"operation": "append", "path": "run.log", "text": "third"})
    assert appended.outcome == Outcome.DONE, appended.message
    read = activity.execute(ctx, {"operation": "read", "path": "run.log"})
    assert read.outcome == Outcome.DONE, read.message
    assert read.outputs == {"lines": ["first", "second", "third"], "count": 3}

    tail = activity.execute(ctx, {"operation": "read", "path": "run.log", "max_lines": 2})
    assert tail.outputs == {"lines": ["second", "third"], "count": 3}
    missing = activity.execute(ctx, {"operation": "read", "path": "missing.log"})
    assert missing.outputs == {"lines": [], "count": 0}


def test_txt_log_reads_a_realistic_log_tail(
    generated_data: dict[str, Path], tmp_path: Path
) -> None:
    ctx = _ctx(tmp_path / "ws")
    shutil.copyfile(generated_data["log"], ctx.workspace / "invoices.log")
    result = TxtLogActivity().execute(
        ctx, {"operation": "read", "path": "invoices.log", "max_lines": 50}
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["count"] == 500
    assert len(result.outputs["lines"]) == 50
    assert any(" ERROR " in line for line in result.outputs["lines"])


# ----------------------------------------------------------------------------- 1M memory
@pytest.fixture(scope="session")
def million_row_csv(
    generated_data: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> Path:
    target = tmp_path_factory.mktemp("million") / "invoices.csv"
    with pyzipper.AESZipFile(generated_data["encrypted_zip"]) as archive:
        archive.setpassword(ZIP_PASSWORD.encode("utf-8"))
        with archive.open("invoices.csv") as source, target.open("wb") as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
    return target


MEMORY_CHILD = """
import json
import sys
import tracemalloc
from pathlib import Path

from activities.files import CsvActivity
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock

workspace = Path(sys.argv[1])
ctx = ActivityContext(
    run_id="memory", step_id="s", workspace=workspace, clock=FakeClock(), correlation_id="m"
)
tracemalloc.start()
result = CsvActivity().execute(
    ctx,
    {
        "operation": "read",
        "path": "invoices.csv",
        "output_path": "invoices.parquet",
        "chunk_size": 50000,
        "max_rows": 1000000,
    },
)
current, peak = tracemalloc.get_traced_memory()
print(json.dumps({
    "outcome": result.outcome.value,
    "rows": result.outputs.get("rows"),
    "message": result.message,
    "tracemalloc_peak_mb": peak / (1024 * 1024),
}))
"""


@pytest.mark.slow
def test_one_million_row_csv_stays_under_500_mb(million_row_csv: Path, tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    workspace = tmp_path / "ws"
    workspace.mkdir()
    shutil.copyfile(million_row_csv, workspace / "invoices.csv")
    environment = {**os.environ, "PYTHONPATH": str(REPO)}
    child = subprocess.Popen(
        [sys.executable, "-c", MEMORY_CHILD, str(workspace)],
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    process = psutil.Process(child.pid)
    peak = 0
    while child.poll() is None:
        try:
            peak = max(peak, process.memory_info().rss)
        except psutil.Error:
            break
        time.sleep(0.02)
    stdout, stderr = child.communicate()
    assert child.returncode == 0, stderr
    result = json.loads(stdout.strip().splitlines()[-1])
    assert result["outcome"] == "done", result
    assert result["rows"] == 1_000_000
    assert pq.ParquetFile(workspace / "invoices.parquet").metadata.num_rows == 1_000_000
    traced_mb = float(result["tracemalloc_peak_mb"])
    print(
        f"peak traced Python memory: {traced_mb:.1f} MB (observed RSS {peak / 1024 / 1024:.1f} MB)"
    )
    assert traced_mb < 500, f"peak traced memory was {traced_mb:.1f} MB"
