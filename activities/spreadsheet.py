"""Spreadsheet calculation on the GridCraft engine (``gridcraft-cli``, MIT/Apache-2.0, from
CraftApps): recalculate a workbook, fill a model's inputs and read its results, read computed
ranges, evaluate a formula, convert, and check a workbook's stored results.

GridCraft recalculates every formula when it opens a file, so a workbook written by a library
that cannot calculate (xlsxwriter stores 0) gains real values. Web functions (WEBSERVICE,
FILTERXML) are not implemented by the engine and return #VALUE!, so a workbook from outside
cannot make the worker fetch URLs.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from activities._common import artifact_for, safe_path, write_rows
from activities._engines import EngineMissing, find_engine, relative, run_engine
from app.domain.activity import Activity, ActivityContext, ActivityResult

WORKBOOK_FORMATS = {".xlsx", ".xlsm", ".xls", ".xlsb", ".ods", ".csv", ".tsv"}
CONVERT_FORMATS = {".xlsx", ".csv", ".tsv", ".json", ".html"}
ROWS_FORMATS = {".csv", ".json", ".parquet"}
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
        "Calculate workbooks with the GridCraft engine: recalculate formulas, fill a model's "
        "inputs and read its results, read computed ranges, evaluate, convert, check."
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
        try:
            engine = find_engine("gridcraft-cli", "gridcraft_cli")
        except EngineMissing as exc:
            return ActivityResult.failed(str(exc))
        workspace = ctx.workspace.resolve()
        grid = _Grid(engine, workspace, inputs.timeout_seconds)
        source = safe_path(ctx, inputs.path, must_exist=True) if inputs.path else None
        sheet = ["--sheet", inputs.sheet] if inputs.sheet else []
        written: list[Path] = []
        outputs: dict[str, Any] = {}

        if inputs.operation == "recalculate":
            assert source is not None
            target = safe_path(ctx, inputs.output_path) if inputs.output_path else source
            _replace_via_temp(grid, source, target)
            written.append(target)
        elif inputs.operation == "calculate":
            assert source is not None
            target = safe_path(ctx, inputs.output_path or f"{source.stem}-calculated.xlsx")
            commands: list[str] = []
            for cell, value in inputs.values.items():
                commands += [
                    "--cmd",
                    "cell.set=" + json.dumps({"cell": cell, "input": _as_value(value)}),
                ]
            for cell, formula in inputs.formulas.items():
                commands += ["--cmd", "cell.set=" + json.dumps({"cell": cell, "input": formula})]
            temp = target.with_name(f".{target.stem}.uaf-tmp{target.suffix}")
            grid.run(
                [
                    "run",
                    "--in",
                    relative(workspace, source),
                    *sheet,
                    *commands,
                    "--out",
                    relative(workspace, temp),
                    "--quiet",
                ]
            )
            os.replace(temp, target)
            written.append(target)
            outputs["results"] = {
                cell_range: _grid_values(grid.cat(relative(workspace, target), cell_range, sheet))
                for cell_range in inputs.read
            }
        elif inputs.operation == "read_range":
            assert source is not None
            rows = grid.cat(relative(workspace, source), inputs.range, sheet)
            records = (
                _records(rows)
                if inputs.header
                else [{f"column_{i + 1}": value for i, value in enumerate(row)} for row in rows]
            )
            outputs |= {"rows": len(records), "preview": records[:20]}
            if inputs.output_path:
                target = safe_path(ctx, inputs.output_path)
                write_rows(ctx, records, target, fmt=target.suffix.lstrip(".").lower())
                written.append(target)
        elif inputs.operation == "evaluate":
            args = ["eval", inputs.formula, "--json", *sheet]
            if source is not None:
                args += ["--in", relative(workspace, source)]
            outputs["value"] = json.loads(grid.run(args) or "null")
        elif inputs.operation == "convert":
            assert source is not None
            target = safe_path(ctx, inputs.output_path)
            grid.run(["convert", relative(workspace, source), relative(workspace, target), *sheet])
            written.append(target)
        else:
            assert source is not None
            outputs |= self._check(grid, workspace, source, inputs)
            if inputs.fail_on_mismatch and outputs["mismatched"]:
                return ActivityResult.failed(
                    f"{outputs['mismatched']} formula result(s) differ from a recalculation",
                    outputs,
                )

        missing = [path for path in written if not path.is_file()]
        if missing:
            return ActivityResult.failed(
                f"gridcraft did not write {relative(workspace, missing[0])}"
            )
        outputs["files"] = [relative(workspace, path) for path in written]
        artifacts = [artifact_for(ctx, path) for path in written]
        return ActivityResult.done(outputs, f"spreadsheet {inputs.operation} completed", artifacts)

    @staticmethod
    def _check(
        grid: _Grid, workspace: Path, source: Path, inputs: SpreadsheetInputs
    ) -> dict[str, Any]:
        report = json.loads(
            grid.run(
                [
                    "check",
                    relative(workspace, source),
                    "--json",
                    "--tolerance",
                    str(inputs.tolerance),
                    "--max-report",
                    "20",
                ],
                ok_codes=(0, 1),
            )
        )
        totals = report.get("totals", {})
        calc = (report.get("files") or [{}])[0].get("calc") or {}
        return {
            "formula_cells": totals.get("formulaCells", 0),
            "checked": totals.get("checked", 0),
            "matched": totals.get("matched", 0),
            "mismatched": totals.get("mismatched", 0),
            "no_stored_result": totals.get("noOracle", 0),
            "mismatches": calc.get("mismatches", [])[:20],
        }


class _Grid:
    def __init__(self, engine: str, workspace: Path, timeout: int) -> None:
        self.engine = engine
        self.workspace = workspace
        self.timeout = timeout

    def run(self, args: list[str], ok_codes: tuple[int, ...] = (0,)) -> str:
        _, stdout = run_engine(
            self.engine,
            args,
            workspace=self.workspace,
            timeout=self.timeout,
            name="gridcraft",
            ok_codes=ok_codes,
        )
        return stdout

    def cat(self, path: str, cell_range: str, sheet: list[str]) -> list[list[str]]:
        args = ["cat", path, "--csv", *sheet]
        if cell_range != "used":
            args += ["--range", cell_range]
        return list(csv.reader(io.StringIO(self.run(args))))


def _replace_via_temp(grid: _Grid, source: Path, target: Path) -> None:
    temp = target.with_name(f".{target.stem}.uaf-tmp.xlsx")
    grid.run(["convert", relative(grid.workspace, source), relative(grid.workspace, temp)])
    os.replace(temp, target)


def _as_value(value: Any) -> str:
    """A data value as cell input. Text that would parse as a formula is stored as text."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "'")) else text


def _grid_values(rows: list[list[str]]) -> list[list[Any]]:
    return [[_number(cell) for cell in row] for row in rows]


def _records(rows: list[list[str]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    header = [name or f"column_{i + 1}" for i, name in enumerate(rows[0])]
    return [
        {name: _number(row[i]) if i < len(row) else None for i, name in enumerate(header)}
        for row in rows[1:]
        if any(cell.strip() for cell in row)
    ]


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


__all__ = ["SpreadsheetActivity"]
