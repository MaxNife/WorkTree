"""Spreadsheet calculation on the pure-Python formula engine.

Recalculate a workbook, fill a model's inputs and read its results, read computed ranges,
evaluate a formula, convert, and check a workbook's stored results. The engine is
:mod:`activities._formula`: :class:`~activities._formula.workbook.Workbook` loads formulas and
cached values, and the evaluator calculates them on demand. No calculator process is started.

A workbook written by a library that cannot calculate (xlsxwriter stores 0) gains real values.
Data cells are inputs, never formulas: text that starts with ``=`` stays text, and formulas are
only ever taken from the ``formulas`` input. Leading-zero numerals stay text. Web functions are
not implemented, so a workbook from outside cannot make the worker fetch URLs.
"""

from __future__ import annotations

import csv
import html
import json
import math
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from activities._common import artifact_for, safe_path, write_rows
from activities._formula.evaluator import Evaluator
from activities._formula.parser import col_letters, parse_cell
from activities._formula.values import (
    Array,
    CellError,
    Value,
    date_to_serial,
    scalar,
)
from activities._formula.workbook import Workbook
from app.domain.activity import Activity, ActivityContext, ActivityResult

WORKBOOK_FORMATS = {".xlsx", ".xlsm", ".xls", ".xlsb", ".ods", ".csv", ".tsv"}
CONVERT_FORMATS = {".xlsx", ".csv", ".tsv", ".json", ".html"}
ROWS_FORMATS = {".csv", ".json", ".parquet"}
ENGINE_FORMATS = {".xlsx", ".xlsm"}
TABLE_FORMATS = {".csv", ".tsv"}
CELL = re.compile(r"^[A-Za-z]{1,3}[1-9][0-9]{0,6}$")
RANGE = re.compile(r"^(used|[A-Za-z]{1,3}[1-9][0-9]{0,6}(:[A-Za-z]{1,3}[1-9][0-9]{0,6})?)$")


class SpreadsheetInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["recalculate", "calculate", "read_range", "evaluate", "convert", "check"] = (
        "recalculate"
    )
    path: str = "book.xlsx"
    sheet: str = ""
    output_path: str = ""
    # calculate: data values are stored as values (text starting with "=" stays text);
    # formulas are only ever taken from ``formulas``.
    values: dict[str, Any] = Field(default_factory=dict)
    formulas: dict[str, str] = Field(default_factory=dict)
    read: list[str] = Field(default_factory=list)
    # read_range
    range: str = "used"
    header: bool = True
    # evaluate
    formula: str = ""
    # check
    tolerance: float = Field(default=1e-9, gt=0, le=1)
    fail_on_mismatch: bool = True
    timeout_seconds: int = Field(default=300, ge=1, le=3600)

    @model_validator(mode="after")
    def _check(self) -> SpreadsheetInputs:
        if self.operation != "evaluate" or self.path:
            suffix = Path(self.path).suffix.lower()
            if suffix not in WORKBOOK_FORMATS:
                raise ValueError(f"unsupported workbook format: {suffix or '(none)'}")
        for cell in [*self.values, *self.formulas]:
            if not CELL.match(cell):
                raise ValueError(f"not a cell address: {cell!r}")
        for item in [*self.read, self.range]:
            if not RANGE.match(item):
                raise ValueError(f"not a range: {item!r}")
        for cell, text in self.formulas.items():
            if not text.startswith("="):
                raise ValueError(f"formula for {cell} must start with '='")
        if self.operation == "calculate" and not (self.values or self.formulas):
            raise ValueError("calculate needs values or formulas")
        if self.operation == "evaluate" and not self.formula.startswith("="):
            raise ValueError("evaluate needs a formula starting with '='")
        if (
            self.operation == "convert"
            and Path(self.output_path).suffix.lower() not in CONVERT_FORMATS
        ):
            raise ValueError("convert needs an output_path ending .xlsx/.csv/.tsv/.json/.html")
        if (
            self.operation == "read_range"
            and self.output_path
            and Path(self.output_path).suffix.lower() not in ROWS_FORMATS
        ):
            raise ValueError("read_range writes .csv, .json or .parquet")
        return self


class SpreadsheetActivity(Activity[SpreadsheetInputs]):
    name = "spreadsheet"
    category = "Platform / Excel"
    description = (
        "Calculate workbooks with the pure-Python formula engine: recalculate formulas, fill a "
        "model's inputs and read its results, read computed ranges, evaluate, convert, check."
    )
    input_model = SpreadsheetInputs
    operation_fields = {
        "recalculate": ("path", "output_path"),
        "calculate": ("path", "sheet", "values", "formulas", "read", "output_path"),
        "read_range": ("path", "sheet", "range", "header", "output_path"),
        "evaluate": ("path", "sheet", "formula"),
        "convert": ("path", "sheet", "output_path"),
        "check": ("path", "tolerance", "fail_on_mismatch"),
    }

    def run(self, ctx: ActivityContext, inputs: SpreadsheetInputs) -> ActivityResult:
        workspace = ctx.workspace.resolve()
        source = safe_path(ctx, inputs.path, must_exist=True) if inputs.path else None
        deadline = _deadline(inputs.timeout_seconds)
        written: list[Path] = []
        outputs: dict[str, Any] = {}

        if inputs.operation == "recalculate":
            assert source is not None
            target = safe_path(ctx, inputs.output_path) if inputs.output_path else source
            _recalculate(source, target, deadline)
            written.append(target)
        elif inputs.operation == "calculate":
            assert source is not None
            target = safe_path(ctx, inputs.output_path or f"{source.stem}-calculated.xlsx")
            outputs["results"] = _calculate(source, target, inputs, deadline)
            written.append(target)
        elif inputs.operation == "read_range":
            assert source is not None
            with _workbook_for(source, workspace, deadline) as book:
                sheet = _sheet_name(book, inputs.sheet)
                rows = _grid_rows(book, sheet, inputs.range)
            records = (
                _records(rows)
                if inputs.header
                else [
                    {f"column_{i + 1}": _cell_value(value) for i, value in enumerate(row)}
                    for row in rows
                ]
            )
            outputs |= {"rows": len(records), "preview": records[:20]}
            if inputs.output_path:
                target = safe_path(ctx, inputs.output_path)
                write_rows(ctx, records, target, fmt=target.suffix.lstrip(".").lower())
                written.append(target)
        elif inputs.operation == "evaluate":
            if source is not None:
                with _workbook_for(source, workspace, deadline) as book:
                    sheet = _sheet_name(book, inputs.sheet)
                    value = book.evaluate(sheet, inputs.formula)
            else:
                value = Evaluator(_EmptyHost(), inputs.sheet or "Sheet1").evaluate_text(
                    inputs.formula
                )
            outputs["value"] = _json_value(value)
        elif inputs.operation == "convert":
            assert source is not None
            target = safe_path(ctx, inputs.output_path)
            _convert(source, target, inputs.sheet, deadline)
            written.append(target)
        else:
            assert source is not None
            outputs |= _check(source, workspace, inputs, deadline)
            if inputs.fail_on_mismatch and outputs["mismatched"]:
                return ActivityResult.failed(
                    f"{outputs['mismatched']} formula result(s) differ from a recalculation",
                    outputs,
                )

        missing = [path for path in written if not path.is_file()]
        if missing:
            return ActivityResult.failed(
                f"spreadsheet did not write {_relative(workspace, missing[0])}"
            )
        outputs["files"] = [_relative(workspace, path) for path in written]
        artifacts = [artifact_for(ctx, path) for path in written]
        return ActivityResult.done(outputs, f"spreadsheet {inputs.operation} completed", artifacts)


# ---------------------------------------------------------------- operations


def _recalculate(source: Path, target: Path, deadline: Callable[[], None]) -> None:
    suffix = source.suffix.lower()
    if suffix in ENGINE_FORMATS:
        if target.suffix.lower() not in ENGINE_FORMATS:
            raise ValueError("recalculate writes .xlsx/.xlsm workbooks")
        Workbook.open(source, deadline=deadline).save(target)
        return
    if suffix in TABLE_FORMATS:
        rows = _table_rows(source)
        if target.suffix.lower() in ENGINE_FORMATS:
            _write_table_xlsx(target, rows, source.stem)
        elif target.suffix.lower() in TABLE_FORMATS:
            _write_table(target, rows)
        else:
            raise ValueError("recalculate writes .xlsx/.xlsm/.csv/.tsv")
        return
    raise ValueError(_unsupported(source))


def _calculate(
    source: Path, target: Path, inputs: SpreadsheetInputs, deadline: Callable[[], None]
) -> dict[str, list[list[Any]]]:
    if target.suffix.lower() not in ENGINE_FORMATS:
        raise ValueError("calculate writes .xlsx/.xlsm workbooks")
    inputs_to_set = {
        cell: _input_value(value, cell)
        for cell, value in inputs.values.items()
        if cell not in inputs.formulas
    }
    suffix = source.suffix.lower()
    if suffix in TABLE_FORMATS:
        _write_table_xlsx(target, _table_rows(source), inputs.sheet or source.stem)
    elif suffix in ENGINE_FORMATS:
        if target.resolve() != source.resolve():
            shutil.copyfile(source, target)
    else:
        raise ValueError(_unsupported(source))

    if inputs.formulas:
        _apply_formulas(target, inputs.sheet, inputs.formulas)

    book = Workbook.open(target, deadline=deadline)
    sheet = _sheet_name(book, inputs.sheet)
    for cell, value in inputs_to_set.items():
        book.set_input(sheet, cell, value)
    results = {
        cell_range: [
            [_cell_value(value) for value in row] for row in _grid_rows(book, sheet, cell_range)
        ]
        for cell_range in inputs.read
    }
    book.save(target)
    return results


def _convert(source: Path, target: Path, sheet_name: str, deadline: Callable[[], None]) -> None:
    target_format = target.suffix.lower()
    source_format = source.suffix.lower()
    if target_format not in CONVERT_FORMATS:
        raise ValueError(f"unsupported convert output: {target_format or '(none)'}")
    if target_format in ENGINE_FORMATS:
        if source_format in ENGINE_FORMATS:
            # Save through the engine so charts and other package parts survive.
            Workbook.open(source, deadline=deadline).save(target)
            return
        if source_format in TABLE_FORMATS:
            _write_table_xlsx(target, _table_rows(source), sheet_name or "Sheet1")
            return
        raise ValueError(_unsupported(source))
    if target_format in TABLE_FORMATS:
        if source_format in ENGINE_FORMATS:
            rows = _workbook_rows(source, sheet_name, deadline)
        elif source_format in TABLE_FORMATS:
            rows = _table_rows(source)
        else:
            raise ValueError(_unsupported(source))
        _write_table(target, rows)
        return
    if target_format in {".json", ".html"}:
        if source_format in ENGINE_FORMATS:
            rows = _workbook_rows(source, sheet_name, deadline)
        elif source_format in TABLE_FORMATS:
            rows = _table_rows(source)
        else:
            raise ValueError(_unsupported(source))
        _write_table(target, rows)
        return
    raise ValueError(f"unsupported convert output: {target_format}")


def _check(
    source: Path, workspace: Path, inputs: SpreadsheetInputs, deadline: Callable[[], None]
) -> dict[str, Any]:
    with _workbook_for(source, workspace, deadline) as book:
        results = book.recalculate()
        mismatched = 0
        matched = 0
        missing = 0
        mismatches: list[dict[str, Any]] = []
        for (sheet, ref), actual in results.items():
            expected = book.stored_value(sheet, ref)
            if expected is None:
                missing += 1
                continue
            if _same(actual, expected, inputs.tolerance):
                matched += 1
                continue
            mismatched += 1
            if len(mismatches) < 20:
                mismatches.append(
                    {
                        "cell": f"{sheet}!{ref}",
                        "formula": book.formula(sheet, ref),
                        "expected": _json_value(expected),
                        "actual": _json_value(actual),
                        "kind": _mismatch_kind(expected, actual),
                    }
                )
    return {
        "formula_cells": len(results),
        "checked": matched + mismatched,
        "matched": matched,
        "mismatched": mismatched,
        "no_stored_result": missing,
        "mismatches": mismatches,
    }


# ---------------------------------------------------------------- workbook access


@contextmanager
def _workbook_for(
    source: Path, workspace: Path, deadline: Callable[[], None]
) -> Iterator[Workbook]:
    suffix = source.suffix.lower()
    if suffix in ENGINE_FORMATS:
        yield Workbook.open(source, deadline=deadline)
        return
    if suffix in TABLE_FORMATS:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{source.stem}.uaf-", suffix=".xlsx", dir=workspace
        )
        os.close(descriptor)
        temporary = Path(name)
        try:
            _write_table_xlsx(temporary, _table_rows(source), "Sheet1")
            yield Workbook.open(temporary, deadline=deadline)
        finally:
            temporary.unlink(missing_ok=True)
        return
    raise ValueError(_unsupported(source))


def _sheet_name(book: Workbook, requested: str) -> str:
    if requested:
        if requested not in book.sheet_names:
            raise ValueError(f"sheet not found: {requested}")
        return requested
    if not book.sheet_names:
        raise ValueError("workbook has no sheets")
    return book.sheet_names[0]


def _range_bounds(book: Workbook, sheet: str, cell_range: str) -> tuple[int, int, int, int]:
    if cell_range == "used":
        last_row, last_col = book.used_bounds(sheet)
        return (0, 0, last_row, last_col)
    first, _, last = cell_range.partition(":")
    start = parse_cell(first)
    end = parse_cell(last) if last else start
    if start is None or end is None:
        raise ValueError(f"not a range: {cell_range!r}")
    return (
        min(start[0], end[0]),
        min(start[1], end[1]),
        max(start[0], end[0]),
        max(start[1], end[1]),
    )


def _grid_rows(book: Workbook, sheet: str, cell_range: str) -> list[list[Value]]:
    r0, c0, r1, c1 = _range_bounds(book, sheet, cell_range)
    if r1 < r0 or c1 < c0:
        return []
    return [
        [book.value(sheet, f"{col_letters(col)}{row + 1}") for col in range(c0, c1 + 1)]
        for row in range(r0, r1 + 1)
    ]


def _workbook_rows(
    source: Path, sheet_name: str, deadline: Callable[[], None]
) -> list[list[Value]]:
    with _workbook_for(source, source.parent, deadline) as book:
        sheet = _sheet_name(book, sheet_name)
        return _grid_rows(book, sheet, "used")


def _apply_formulas(path: Path, sheet_name: str, formulas: dict[str, str]) -> None:
    import openpyxl

    book = openpyxl.load_workbook(path, keep_vba=path.suffix.lower() == ".xlsm")
    try:
        if sheet_name and sheet_name not in book.sheetnames:
            raise ValueError(f"sheet not found: {sheet_name}")
        sheet = book[sheet_name] if sheet_name else book.active
        for cell, formula in formulas.items():
            sheet[cell] = formula
        book.save(path)
    finally:
        book.close()


# ---------------------------------------------------------------- table conversion


def _table_rows(path: Path) -> list[list[Any]]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            [_number(cell) if cell != "" else None for cell in row]
            for row in csv.reader(handle, delimiter=delimiter)
        ]


def _write_table(path: Path, rows: list[list[Any]]) -> None:
    fmt = path.suffix.lower()
    if fmt in TABLE_FORMATS:
        delimiter = "\t" if fmt == ".tsv" else ","
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=delimiter)
            for row in rows:
                writer.writerow([_csv_text(value) for value in row])
        return
    if fmt == ".json":
        text = json.dumps(_records(rows), indent=2, allow_nan=False, default=str)
        path.write_text(text, encoding="utf-8")
        return
    if fmt == ".html":
        lines = ["<!doctype html>", '<html><head><meta charset="utf-8"></head><body>', "<table>"]
        for row in rows:
            cells = "".join(f"<td>{html.escape(_csv_text(value))}</td>" for value in row)
            lines.append(f"<tr>{cells}</tr>")
        lines += ["</table>", "</body></html>", ""]
        path.write_text("\n".join(lines), encoding="utf-8")
        return
    raise ValueError(f"unsupported table output: {fmt or '(none)'}")


def _write_table_xlsx(path: Path, rows: list[list[Any]], sheet_name: str) -> None:
    import xlsxwriter

    workbook = xlsxwriter.Workbook(path)
    try:
        sheet = workbook.add_worksheet((sheet_name or "Sheet1")[:31] or "Sheet1")
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                _write_xlsx_cell(sheet, row_index, col_index, value)
    finally:
        workbook.close()


def _write_xlsx_cell(sheet: Any, row: int, col: int, value: Any) -> None:
    value = scalar(value)
    if value is None or value == "":
        sheet.write_blank(row, col, None)
    elif isinstance(value, bool):
        sheet.write_boolean(row, col, value)
    elif isinstance(value, int | float):
        number = float(value)
        if math.isfinite(number):
            sheet.write_number(row, col, number)
        else:
            sheet.write_string(row, col, CellError.NUM.value)
    elif isinstance(value, CellError):
        sheet.write_string(row, col, value.value)
    else:
        sheet.write_string(row, col, str(value))


# ---------------------------------------------------------------- values and output


def _input_value(value: Any, cell: str) -> float | int | str | bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return ""
    if isinstance(value, int | float):
        if not math.isfinite(float(value)):
            raise ValueError(f"value for {cell} is not finite")
        return value
    return str(value)


def _cell_value(value: Value) -> Any:
    value = scalar(value)
    if isinstance(value, CellError):
        return value.value
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        number = float(value)
        if not math.isfinite(number):
            return CellError.NUM.value
        return int(number) if number.is_integer() else number
    if isinstance(value, str):
        return value
    return value


def _json_value(value: Value) -> Any:
    if isinstance(value, CellError):
        return {"error": value.value}
    if isinstance(value, Array):
        return [[_json_value(item) for item in row] for row in value.to_rows()]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        number = float(value)
        if not math.isfinite(number):
            return {"error": CellError.NUM.value}
        return int(number) if number.is_integer() else number
    return value


def _csv_text(value: Any) -> str:
    value = scalar(value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, CellError):
        return value.value
    if isinstance(value, int | float):
        number = float(value)
        if not math.isfinite(number):
            return CellError.NUM.value
        return str(int(number)) if number.is_integer() else repr(number)
    return str(value)


def _records(rows: list[list[Value]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    header = [_header(cell, index) for index, cell in enumerate(rows[0])]
    return [
        {
            name: _cell_value(row[index]) if index < len(row) else None
            for index, name in enumerate(header)
        }
        for row in rows[1:]
        if any(not _blank(cell) for cell in row)
    ]


def _header(value: Value, index: int) -> str:
    value = scalar(value)
    if _blank(value):
        return f"column_{index + 1}"
    return _csv_text(value)


def _blank(value: Value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _same(actual: Value, expected: Value, tolerance: float) -> bool:
    actual, expected = scalar(actual), scalar(expected)
    if isinstance(actual, CellError) or isinstance(expected, CellError):
        return actual == expected
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected
    if isinstance(actual, int | float) and isinstance(expected, int | float):
        # Relative above 1, absolute below it, as the previous check command did.
        magnitude = abs(float(expected))
        allowed = tolerance if magnitude < 1 else tolerance * magnitude
        return abs(float(actual) - float(expected)) <= allowed
    if isinstance(actual, str) and isinstance(expected, str):
        return actual == expected
    return actual == expected


def _mismatch_kind(expected: Value, actual: Value) -> str:
    if expected is None or actual is None:
        return "blank"
    if isinstance(expected, CellError) or isinstance(actual, CellError):
        return "error"
    if isinstance(expected, bool) or isinstance(actual, bool):
        return "bool" if isinstance(expected, bool) and isinstance(actual, bool) else "type"
    if isinstance(expected, int | float) and isinstance(actual, int | float):
        return "numeric"
    if isinstance(expected, str) and isinstance(actual, str):
        return "text"
    return "type"


def _number(text: str) -> Any:
    """Plain numerals become numbers; everything else stays text. Leading zeros (account
    numbers, sort codes) and words such as "nan" or "inf" are never converted."""
    if text == "":
        return None
    if re.fullmatch(r"-?(0|[1-9]\d*)", text):
        return int(text)
    if re.fullmatch(r"-?(0|[1-9]\d*)\.\d+([eE][-+]?\d+)?|-?[1-9](\.\d+)?[eE][-+]?\d+", text):
        return float(text)
    return text


def _deadline(seconds: int) -> Callable[[], None]:
    end = time.monotonic() + seconds

    def check() -> None:
        if time.monotonic() > end:
            raise TimeoutError(f"spreadsheet calculation exceeded {seconds}s")

    return check


def _unsupported(path: Path) -> str:
    suffix = path.suffix.lower()
    return (
        f"{suffix or '(none)'} workbooks are not supported by the pure-Python formula engine; "
        "resave the workbook as .xlsx/.xlsm"
    )


def _relative(workspace: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return path.name


class _EmptyHost:
    """Host for evaluating a formula without a workbook: every cell is empty."""

    def cell_value(self, sheet: str, row: int, col: int) -> Value:
        return None

    def has_sheet(self, sheet: str) -> bool:
        return True

    def used_bounds(self, sheet: str) -> tuple[int, int]:
        return (-1, -1)

    def defined_name(self, name: str, sheet: str) -> str | None:
        return None

    def now_serial(self) -> float:
        now = time.localtime()
        seconds = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
        return date_to_serial(date(now.tm_year, now.tm_mon, now.tm_mday)) + seconds / 86400


__all__ = ["SpreadsheetActivity"]
