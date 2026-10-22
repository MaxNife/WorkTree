"""File activities: CSV, Excel, ZIP and text logs. Files always travel by workspace reference."""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from activities._common import (
    artifact_for,
    read_json,
    read_table,
    safe_path,
    write_json,
    write_rows,
)
from app.domain.activity import Activity, ActivityContext, ActivityResult


class CsvInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["read", "write", "append"] = "read"
    path: str = "data.csv"
    source_path: str | None = None
    output_path: str | None = None
    encoding: str = "utf-8"
    delimiter: str = ","
    output_format: Literal["parquet", "csv", "json"] = "parquet"
    max_rows: int = Field(default=100_000, ge=1, le=5_000_000)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class CsvActivity(Activity[CsvInputs]):
    name = "csv"
    category = "Platform / Files"
    description = "Stream or chunk CSV files; tables leave as Parquet references."
    input_model = CsvInputs

    def run(self, ctx: ActivityContext, inputs: CsvInputs) -> ActivityResult:
        path = safe_path(ctx, inputs.path)
        if inputs.operation == "read":
            rows = _read_csv(path, inputs)
            output = safe_path(ctx, inputs.output_path or f"{path.stem}.parquet")
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
        with path.open("a", encoding=inputs.encoding, newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
            if path.stat().st_size == 0:
                writer.writeheader()
            writer.writerows(rows)
        return ActivityResult.done({"rows": len(rows)}, "rows appended")


def _read_csv(path: Path, inputs: CsvInputs) -> list[dict[str, Any]]:
    import pandas as pd

    frame = pd.read_csv(
        path,
        dtype=str,
        encoding=inputs.encoding,
        sep=inputs.delimiter,
        nrows=inputs.max_rows,
    )
    return cast(list[dict[str, Any]], frame.to_dict(orient="records"))


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


class ExcelActivity(Activity[ExcelInputs]):
    name = "excel"
    category = "Platform / Excel"
    description = "Read with calamine, edit with openpyxl, write with XlsxWriter."
    input_model = ExcelInputs

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
            return ActivityResult.done(
                {"rows": len(rows)}, f"{len(rows)} rows written", [artifact_for(ctx, path)]
            )
        if inputs.operation == "sheets":
            from python_calamine import CalamineWorkbook

            book = CalamineWorkbook.from_path(str(path))
            return ActivityResult.done({"sheets": book.sheet_names})
        import openpyxl

        book = openpyxl.load_workbook(path)
        sheet = (
            book[inputs.sheet] if inputs.sheet and inputs.sheet in book.sheetnames else book.active
        )
        for address, value in inputs.cells.items():
            sheet[address] = value
        book.save(path)
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

        workbook = xlsxwriter.Workbook(path)
        worksheet = workbook.add_worksheet(sheet_name[:31] or "Sheet1")
        header = workbook.add_format({"bold": True, "bg_color": "#DDEBF7"})
        columns = list(rows[0]) if rows else []
        for index, column in enumerate(columns):
            worksheet.write(0, index, column, header)
        for row_index, row in enumerate(rows, start=1):
            for column_index, column in enumerate(columns):
                worksheet.write(row_index, column_index, row.get(column, ""))
        workbook.close()


class ZipInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["extract", "list", "create"] = "extract"
    path: str = "archive.zip"
    output_dir: str = "extracted"
    password: str = ""
    files: list[str] = Field(default_factory=list)
    max_total_bytes: int = Field(default=1_000_000_000, ge=1)


class ZipActivity(Activity[ZipInputs]):
    name = "zip"
    category = "Platform / Files"
    description = "AES ZIP create/extract with zip-slip and size protections."
    input_model = ZipInputs
    sensitive_fields = ("password",)

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
        with _open_zip(path, inputs.password, "r") as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                target = (destination / info.filename).resolve()
                root = destination.resolve()
                if root not in target.parents and target != root:
                    raise ValueError(f"zip entry escapes the output folder: {info.filename}")
                total += info.file_size
                if total > inputs.max_total_bytes:
                    raise ValueError("zip exceeds the configured uncompressed size cap")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                extracted.append(str(target.relative_to(ctx.workspace)))
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
    max_lines: int = Field(default=10_000, ge=1, le=1_000_000)


class TxtLogActivity(Activity[TxtLogInputs]):
    name = "txt_log"
    category = "Platform / Files"
    description = "Append or read a plain-text log with a line cap."
    input_model = TxtLogInputs

    def run(self, ctx: ActivityContext, inputs: TxtLogInputs) -> ActivityResult:
        path = safe_path(ctx, inputs.path)
        if inputs.operation == "read":
            if not path.is_file():
                return ActivityResult.done({"lines": [], "count": 0})
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            return ActivityResult.done({"lines": lines[-inputs.max_lines :], "count": len(lines)})
        content = inputs.text or "\n".join(inputs.lines)
        mode = "w" if inputs.operation == "write" else "a"
        with path.open(mode, encoding="utf-8") as handle:
            handle.write(content)
            if content and not content.endswith("\n"):
                handle.write("\n")
        return ActivityResult.done(
            {"path": str(path.relative_to(ctx.workspace))}, "log written", [artifact_for(ctx, path)]
        )


_ = (io, write_json, read_json)
