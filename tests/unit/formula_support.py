"""Shared harness for the pure-Python formula engine tests.

The ``Host`` here implements the same protocol as
:class:`activities._formula.workbook.Workbook`, so formulas can be evaluated without writing
an ``.xlsx`` file. Values are read from a sparse ``"Sheet!A1"`` map.
"""

from __future__ import annotations

import math

from activities._formula.evaluator import Evaluator
from activities._formula.parser import parse_cell
from activities._formula.values import CellError, Value


def as_value(raw: object) -> Value:
    if raw is None:
        return None
    if isinstance(raw, bool | str | CellError):
        return raw
    if isinstance(raw, int | float):
        return float(raw)
    raise TypeError(f"unsupported test cell value: {raw!r}")


class Host:
    """A sparse grid with the Workbook's Host behaviour, including defined names."""

    def __init__(
        self,
        cells: dict[str, object] | None = None,
        *,
        sheets: tuple[str, ...] = (),
        names: dict[str, str] | None = None,
        now: float = 45000.25,
    ) -> None:
        self.cells: dict[tuple[str, int, int], Value] = {}
        self.sheets = {"Sheet1", *sheets}
        self.names = {name.upper(): formula for name, formula in (names or {}).items()}
        self.now = now
        for ref, raw in (cells or {}).items():
            sheet, _, cell = ref.partition("!")
            position = parse_cell(cell)
            assert position is not None, f"bad cell reference in fixture: {ref}"
            self.sheets.add(sheet)
            self.cells[(sheet, *position)] = as_value(raw)

    def cell_value(self, sheet: str, row: int, col: int) -> Value:
        return self.cells.get((sheet, row, col))

    def has_sheet(self, sheet: str) -> bool:
        return sheet in self.sheets

    def used_bounds(self, sheet: str) -> tuple[int, int]:
        used = [(row, col) for name, row, col in self.cells if name == sheet]
        return (
            max((row for row, _ in used), default=-1),
            max((col for _, col in used), default=-1),
        )

    def defined_name(self, name: str, sheet: str) -> str | None:
        return self.names.get(name.upper())

    def now_serial(self) -> float:
        return self.now

    def evaluate(self, formula: str, *, row: int = 0, col: int = 0, sheet: str = "Sheet1") -> Value:
        return Evaluator(self, sheet, row, col).evaluate_text(formula)


class PoisonHost(Host):
    """A host whose cells must never be read; proves lazy branches stay unevaluated."""

    def cell_value(self, sheet: str, row: int, col: int) -> Value:
        raise AssertionError(f"lazy branch read {sheet}!R{row + 1}C{col + 1}")


def evaluate(
    formula: str,
    cells: dict[str, object] | None = None,
    *,
    row: int = 0,
    col: int = 0,
) -> Value:
    return Host(cells).evaluate(formula, row=row, col=col)


def assert_close(actual: Value, expected: float, *, rel: float = 1e-9, tol: float = 1e-9) -> None:
    assert isinstance(actual, float), actual
    assert math.isclose(actual, expected, rel_tol=rel, abs_tol=tol), f"{actual!r} != {expected!r}"


MIXED = {
    "Sheet1!A1": 1.0,
    "Sheet1!A2": 2.0,
    "Sheet1!A3": "text",
    "Sheet1!A4": True,
    "Sheet1!A5": None,
    "Sheet1!B1": 10.0,
    "Sheet1!B2": 20.0,
    "Sheet1!B3": 30.0,
}

NUMBERS = {f"Sheet1!A{row}": float(row) for row in range(1, 6)}

LOOKUP = {
    **{f"Sheet1!A{row}": float(row) for row in range(1, 6)},
    **{f"Sheet1!B{row}": letter for row, letter in enumerate("abcde", start=1)},
    **{f"Sheet1!C{row}": float(6 - row) for row in range(1, 6)},
    "Sheet1!D1": 1.0,
    "Sheet1!D2": 2.0,
    "Sheet1!D3": 3.0,
    "Sheet1!E1": "one",
    "Sheet1!E2": "two",
    "Sheet1!E3": "three",
    "Sheet1!G1": 1.0,
    "Sheet1!H1": 2.0,
    "Sheet1!I1": 3.0,
    "Sheet1!G2": "x",
    "Sheet1!H2": "y",
    "Sheet1!I2": "z",
}

CRITERIA = {
    **{f"Sheet1!A{row}": text for row, text in enumerate(["apple", "apricot", "berry"], 1)},
    **{f"Sheet1!A{row}": text for row, text in [(4, "a*b"), (5, "a?b")]},
    **{f"Sheet1!B{row}": float(row) for row in range(1, 6)},
    "Sheet1!C1": 5.0,
    "Sheet1!C2": 15.0,
    "Sheet1!C3": 25.0,
}
