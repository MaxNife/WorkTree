"""File activities: CSV, Excel, ZIP and text logs. Files always travel by workspace reference."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import tempfile
import zipfile
from collections import deque
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from activities._common import (
    artifact_for,
    csv_records,
    read_table,
    safe_path,
    write_rows,
)
from app.domain.activity import Activity, ActivityContext, ActivityResult


class CsvInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["read", "write", "append", "read_fwf"] = "read"
    path: str = "data.csv"
    source_path: str | None = None
    output_path: str | None = None
    encoding: str = "utf-8"
    delimiter: str = ","
    widths: list[int] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    output_format: Literal["parquet", "csv", "json"] = "parquet"
    max_rows: int = Field(default=100_000, ge=1, le=5_000_000)
    chunk_size: int = Field(default=50_000, ge=1, le=1_000_000)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class CsvActivity(Activity[CsvInputs]):
    name = "csv"
    category = "Platform / Files"
    description = "Stream or chunk CSV and fixed-width files; tables leave as Parquet references."
    input_model = CsvInputs
    operation_fields = {
        "read": (
            "path",
            "encoding",
            "delimiter",
            "output_path",
            "output_format",
            "max_rows",
            "chunk_size",
        ),
        "read_fwf": (
            "path",
            "encoding",
            "widths",
            "names",
            "output_path",
            "output_format",
            "max_rows",
            "chunk_size",
        ),
        "write": ("path", "encoding", "rows", "source_path"),
        "append": ("path", "encoding", "rows", "source_path"),
    }

    def run(self, ctx: ActivityContext, inputs: CsvInputs) -> ActivityResult:
        path = safe_path(ctx, inputs.path)
        if inputs.operation in {"read", "read_fwf"}:
            if inputs.operation == "read_fwf" and not inputs.widths:
                raise ValueError("widths are required for read_fwf")
            if inputs.operation == "read_fwf" and not inputs.names:
                raise ValueError("names are required for read_fwf")
            output = safe_path(ctx, inputs.output_path or f"{path.stem}.parquet")
            count = _stream_table(path, output, inputs)
            return ActivityResult.done(
                {"rows": count, "path": str(output.relative_to(ctx.workspace))},
                f"{count} rows read",
                [artifact_for(ctx, output)],
            )
        if inputs.operation == "write":
            rows = inputs.rows
            if inputs.source_path:
                rows = read_table(safe_path(ctx, inputs.source_path, must_exist=True))
            with path.open("w", encoding=inputs.encoding, newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
                writer.writeheader()
                writer.writerows(rows)
            return ActivityResult.done(
                {"rows": len(rows)}, f"{len(rows)} rows written", [artifact_for(ctx, path)]
            )
        rows = (
            read_table(safe_path(ctx, inputs.source_path, must_exist=True))
            if inputs.source_path
            else inputs.rows
        )
        # Appended rows follow the existing header's column order, not the new rows' key order.
        header: list[str] = []
        if path.is_file() and path.stat().st_size > 0:
            with path.open(encoding=inputs.encoding, newline="") as existing:
                header = next(csv.reader(existing), [])
        with path.open("a", encoding=inputs.encoding, newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header or (list(rows[0]) if rows else []))
            if not header:
                writer.writeheader()
            writer.writerows(rows)
        return ActivityResult.done({"rows": len(rows)}, "rows appended")


def _stream_table(path: Path, output: Path, inputs: CsvInputs) -> int:
    """Read a delimited/fixed-width table in chunks and write it without materialising it.

    The read side is bounded by ``chunk_size``; the Parquet side streams one row group per
    chunk, so the 1M-row gate does not depend on the whole table fitting in memory.
    """
    import pandas as pd

    try:
        if inputs.operation == "read_fwf":
            header = list(inputs.names)
            reader = pd.read_fwf(
                path,
                widths=inputs.widths,
                names=inputs.names or None,
                dtype=str,
                encoding=inputs.encoding,
                chunksize=inputs.chunk_size,
                nrows=inputs.max_rows,
            )
        else:
            header = list(
                pd.read_csv(
                    path,
                    dtype=str,
                    encoding=inputs.encoding,
                    sep=inputs.delimiter,
                    nrows=0,
                ).columns
            )
            reader = pd.read_csv(
                path,
                dtype=str,
                encoding=inputs.encoding,
                sep=inputs.delimiter,
                chunksize=inputs.chunk_size,
                nrows=inputs.max_rows,
            )
    except pd.errors.EmptyDataError:
        _write_empty_table(output, inputs.output_format)
        return 0
    sink = _TableSink(output, inputs.output_format, header)
    try:
        for frame in reader:
            sink.write(csv_records(frame))
    finally:
        sink.close()
    return sink.rows


class _TableSink:
    """Incremental writer for the table formats an activity can hand to the next step."""

    def __init__(self, path: Path, fmt: str, columns: list[str]) -> None:
        self.path = path
        self.format = fmt.lower()
        self.columns = columns
        self.rows = 0
        self._first_json = True
        self._handle: Any = None
        self._writer: Any = None
        self._parquet: Any = None
        self._schema: Any = None
        if self.format == "csv":
            self._handle = path.open("w", encoding="utf-8", newline="")
            self._writer = csv.DictWriter(self._handle, fieldnames=columns)
            self._writer.writeheader()
        elif self.format == "json":
            self._handle = path.open("w", encoding="utf-8")
            self._handle.write("[")
        elif self.format != "parquet":
            raise ValueError(f"unsupported output format: {fmt}")

    def write(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        if self.format == "parquet":
            import pyarrow as pa
            import pyarrow.parquet as pq

            if self._parquet is None:
                self._schema = pa.schema([(column, pa.string()) for column in self.columns])
                self._parquet = pq.ParquetWriter(self.path, self._schema)
            arrays = [
                pa.array(
                    [None if row.get(column) is None else str(row.get(column)) for row in rows],
                    type=pa.string(),
                )
                for column in self.columns
            ]
            self._parquet.write_table(pa.Table.from_arrays(arrays, names=self.columns))
        elif self.format == "csv":
            self._writer.writerows(rows)
        else:
            for row in rows:
                if not self._first_json:
                    self._handle.write(",")
                self._first_json = False
                self._handle.write(json.dumps(row, default=str))
        self.rows += len(rows)

    def close(self) -> None:
        if self.format == "parquet":
            if self._parquet is not None:
                self._parquet.close()
            else:
                import pyarrow as pa
                import pyarrow.parquet as pq

                schema = pa.schema([(column, pa.string()) for column in self.columns])
                pq.write_table(pa.Table.from_batches([], schema=schema), self.path)
        elif self.format == "json":
            self._handle.write("]")
            self._handle.close()
        else:
            self._handle.close()


def _write_empty_table(path: Path, fmt: str) -> None:
    if fmt == "parquet":
        import pandas as pd

        pd.DataFrame().to_parquet(path, index=False)
    elif fmt == "json":
        path.write_text("[]", encoding="utf-8")
    else:
        path.write_text("", encoding="utf-8")


class ExcelInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["read", "write", "set_cells", "sheets"] = "read"
    path: str = "book.xlsx"
    source_path: str | None = None
    sheet: str = ""
    output_path: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    cells: dict[str, Any] = Field(default_factory=dict)
    output_format: Literal["parquet", "csv", "json"] = "parquet"
    max_rows: int = Field(default=100_000, ge=1, le=1_000_000)
    recalculate: bool = False


def _sheet_options(values: dict[str, Any], workspace: Path | None) -> list[dict[str, str]]:
    """Sheet names of the workbook named in ``path`` (resolved in the pinned run workspace)."""
    if workspace is None or not values.get("path"):
        return []
    root = workspace.resolve()
    book_path = (root / str(values["path"])).resolve()
    if root not in book_path.parents or not book_path.is_file():
        return []
    from python_calamine import CalamineWorkbook

    names = CalamineWorkbook.from_path(str(book_path)).sheet_names
    return [{"value": name, "label": name} for name in names]


class ExcelActivity(Activity[ExcelInputs]):
    name = "excel"
    category = "Platform / Excel"
    description = "Read with calamine, edit with openpyxl, write with XlsxWriter."
    input_model = ExcelInputs
    option_providers = {"sheet": _sheet_options}
    operation_fields = {
        "read": ("path", "sheet", "output_path", "output_format", "max_rows"),
        "write": ("path", "sheet", "rows", "source_path", "recalculate"),
        "set_cells": ("path", "sheet", "cells", "recalculate"),
        "sheets": ("path",),
    }

    def run(self, ctx: ActivityContext, inputs: ExcelInputs) -> ActivityResult:
        path = safe_path(ctx, inputs.path)
        if inputs.operation == "read":
            rows = self._read(path, inputs)
            output = safe_path(
                ctx, inputs.output_path or f"{path.stem}-{inputs.sheet or 'sheet'}.parquet"
            )
            write_rows(ctx, rows, output, fmt=inputs.output_format)
            return ActivityResult.done(
                {"rows": len(rows), "path": str(output.relative_to(ctx.workspace))},
                f"{len(rows)} rows read",
                [artifact_for(ctx, output)],
            )
        if inputs.operation == "write":
            rows = inputs.rows
            if inputs.source_path:
                rows = read_table(safe_path(ctx, inputs.source_path, must_exist=True))
            self._write(path, rows, inputs.sheet or "Sheet1")
            if inputs.recalculate:
                _recalculate(path)
            return ActivityResult.done(
                {"rows": len(rows)}, f"{len(rows)} rows written", [artifact_for(ctx, path)]
            )
        if inputs.operation == "sheets":
            from python_calamine import CalamineWorkbook

            book = CalamineWorkbook.from_path(str(path))
            return ActivityResult.done({"sheets": book.sheet_names})
        import openpyxl

        book = openpyxl.load_workbook(path)
        if inputs.sheet and inputs.sheet not in book.sheetnames:
            raise ValueError(f"sheet not found: {inputs.sheet}")
        sheet = book[inputs.sheet] if inputs.sheet else book.active
        for address, value in inputs.cells.items():
            sheet[address] = value
        book.save(path)
        if inputs.recalculate:
            _recalculate(path)
        return ActivityResult.done(
            {"updated": list(inputs.cells)}, "cells updated", [artifact_for(ctx, path)]
        )

    @staticmethod
    def _read(path: Path, inputs: ExcelInputs) -> list[dict[str, Any]]:
        import pandas as pd

        frame = pd.read_excel(
            path,
            sheet_name=inputs.sheet or 0,
            dtype=str,
            nrows=inputs.max_rows,
            engine="calamine",
        )
        return cast(list[dict[str, Any]], frame.fillna("").to_dict(orient="records"))

    @staticmethod
    def _write(path: Path, rows: list[dict[str, Any]], sheet_name: str) -> None:
        import xlsxwriter

        # constant_memory streams rows to disk instead of keeping the whole workbook in RAM.
        workbook = xlsxwriter.Workbook(path, {"constant_memory": True})
        worksheet = workbook.add_worksheet(sheet_name[:31] or "Sheet1")
        header = workbook.add_format({"bold": True, "bg_color": "#DDEBF7"})
        columns = list(rows[0]) if rows else []
        for index, column in enumerate(columns):
            worksheet.write(0, index, column, header)
        for row_index, row in enumerate(rows, start=1):
            for column_index, column in enumerate(columns):
                worksheet.write(row_index, column_index, row.get(column, ""))
        workbook.close()


def _recalculate(path: Path) -> None:
    """Recalculate formulas with headless LibreOffice (opt-in; off by default)."""
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if executable is None:
        raise RuntimeError(
            "LibreOffice recalculation was requested but soffice is not installed (KNOWN_GAPS G9)"
        )
    with tempfile.TemporaryDirectory() as folder:
        completed = subprocess.run(  # noqa: S603 - fixed executable, no shell
            [executable, "--headless", "--convert-to", "xlsx", "--outdir", folder, str(path)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
            check=False,
        )
        converted = Path(folder) / path.name
        if completed.returncode != 0 or not converted.is_file():
            raise RuntimeError(f"LibreOffice recalculation failed: {completed.stderr[-500:]}")
        shutil.copy2(converted, path)


class ZipInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["extract", "list", "create"] = "extract"
    path: str = "archive.zip"
    output_dir: str = "extracted"
    password: str = ""
    files: list[str] = Field(default_factory=list)
    max_total_bytes: int = Field(default=1_000_000_000, ge=1)
    max_entries: int = Field(default=10_000, ge=1, le=1_000_000)


class ZipActivity(Activity[ZipInputs]):
    name = "zip"
    category = "Platform / Files"
    description = "AES ZIP create/extract with zip-slip and size protections."
    input_model = ZipInputs
    sensitive_fields = ("password",)
    operation_fields = {
        "extract": ("path", "output_dir", "password", "max_total_bytes", "max_entries"),
        "list": ("path", "password"),
        "create": ("path", "files", "password"),
    }

    def run(self, ctx: ActivityContext, inputs: ZipInputs) -> ActivityResult:
        path = safe_path(ctx, inputs.path)
        if inputs.operation == "list":
            with _open_zip(path, inputs.password, "r") as archive:
                names = archive.namelist()
            return ActivityResult.done({"files": names, "count": len(names)})
        if inputs.operation == "create":
            target = path if path.suffix else path.with_suffix(".zip")
            with _open_zip(target, inputs.password, "w") as archive:
                for name in inputs.files:
                    source = safe_path(ctx, name, must_exist=True)
                    archive.write(source, source.name)
            return ActivityResult.done(
                {"path": str(target.relative_to(ctx.workspace))},
                "zip created",
                [artifact_for(ctx, target)],
            )
        destination = safe_path(ctx, inputs.output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        total = 0
        extracted: list[str] = []
        created: list[Path] = []
        with _open_zip(path, inputs.password, "r") as archive:
            entries = [info for info in archive.infolist() if not info.is_dir()]
            if len(entries) > inputs.max_entries:
                raise ValueError("zip exceeds the configured entry cap")
            declared = sum(info.file_size for info in entries)
            if declared > inputs.max_total_bytes:
                raise ValueError("zip exceeds the configured uncompressed size cap")
            try:
                for info in entries:
                    target = (destination / info.filename).resolve()
                    root = destination.resolve()
                    if root not in target.parents and target != root:
                        raise ValueError(f"zip entry escapes the output folder: {info.filename}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    created.append(target)
                    with archive.open(info) as source, target.open("wb") as output:
                        while chunk := source.read(1024 * 1024):
                            total += len(chunk)
                            if total > inputs.max_total_bytes:
                                # Declared sizes can lie; stop on what was actually produced.
                                raise ValueError("zip exceeds the configured uncompressed size cap")
                            output.write(chunk)
                    extracted.append(str(target.relative_to(ctx.workspace)))
            except Exception:
                for item in created:
                    item.unlink(missing_ok=True)
                raise
        return ActivityResult.done({"extracted": extracted, "count": len(extracted)})


def _open_zip(path: Path, password: str, mode: Literal["r", "w"]) -> Any:
    if password:
        import pyzipper

        archive = pyzipper.AESZipFile(path, mode)
        if mode == "r":
            archive.setpassword(password.encode())
        else:
            archive.setencryption(pyzipper.WZ_AES)
            archive.setpassword(password.encode())
        return archive
    return zipfile.ZipFile(path, mode)


class TxtLogInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["read", "append", "write"] = "append"
    path: str = "run.log"
    text: str = ""
    lines: list[str] = Field(default_factory=list)
    encoding: str = "utf-8"
    max_lines: int = Field(default=10_000, ge=1, le=1_000_000)


class TxtLogActivity(Activity[TxtLogInputs]):
    name = "txt_log"
    category = "Platform / Files"
    description = "Append or read a plain-text log with a line cap."
    input_model = TxtLogInputs
    operation_fields = {
        "read": ("path", "encoding", "max_lines"),
        "append": ("path", "encoding", "text", "lines"),
        "write": ("path", "encoding", "text", "lines"),
    }

    def run(self, ctx: ActivityContext, inputs: TxtLogInputs) -> ActivityResult:
        path = safe_path(ctx, inputs.path)
        if inputs.operation == "read":
            if not path.is_file():
                return ActivityResult.done({"lines": [], "count": 0})
            tail: deque[str] = deque(maxlen=inputs.max_lines)
            count = 0
            with path.open(encoding=inputs.encoding, errors="replace") as handle:
                for line in handle:
                    count += 1
                    tail.append(line.rstrip("\n"))
            return ActivityResult.done({"lines": list(tail), "count": count})
        content = inputs.text or "\n".join(inputs.lines)
        mode = "w" if inputs.operation == "write" else "a"
        with path.open(mode, encoding=inputs.encoding) as handle:
            handle.write(content)
            if content and not content.endswith("\n"):
                handle.write("\n")
        return ActivityResult.done(
            {"path": str(path.relative_to(ctx.workspace))}, "log written", [artifact_for(ctx, path)]
        )
