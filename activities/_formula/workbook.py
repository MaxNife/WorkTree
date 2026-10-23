"""A workbook loaded from ``.xlsx`` and calculated with the pure-Python formula engine.

The workbook is read twice: once with formulas, and once with ``data_only=True`` for the
cached results a ``check`` operation will compare against. Everything is evaluated on demand
and memoised; ``set_input`` is the only way to change a value, and it clears the memo.

openpyxl expands shared formulas while it parses a worksheet, so dependent cells already
carry their translated formula text. Expanding them again would shift the references twice.
Array formulas are kept once, on their anchor cell (``ArrayFormula.text``); the other cells
in the array range remain ordinary values from the file.

Only the 1900 date system is supported: openpyxl would otherwise turn date cells into
different serials than :mod:`activities._formula.values` produces.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterator
from datetime import datetime
from itertools import chain
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.datetime import MAC_EPOCH
from openpyxl.worksheet.formula import ArrayFormula

from activities._formula.evaluator import Evaluator, Host
from activities._formula.parser import (
    ArrayLit,
    Binary,
    Call,
    Expr,
    Name,
    ParseError,
    Ref,
    Unary,
    col_letters,
    parse,
    parse_cell,
)
from activities._formula.values import (
    CellError,
    Value,
    date_to_serial,
    python_value,
)
from activities._formula.xlsx_writer import write_back

CellKey = tuple[str, int, int]
"""``(sheet, row, column)``, row and column 0-based."""


class Workbook(Host):
    """A workbook whose formula cells are calculated lazily and memoised.

    ``Workbook.open`` is the normal entry point. A fresh load starts with no cached formula
    results; each ``value`` or ``recalculate`` call fills the memo, and re-entrant calls from
    the evaluator reuse it. A dependency pre-pass walks the parsed formula before it is
    evaluated, so a chain thousands of cells long does not depend on Python's recursion limit.
    """

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], float] | None = None,
        deadline: Callable[[], None] | None = None,
    ) -> None:
        self._clock = clock
        self._deadline = deadline
        self._path = Path(path)
        self._sheets: list[str] = []
        self._sheet_set: set[str] = set()
        self._formulas: dict[CellKey, str] = {}
        self._literals: dict[CellKey, Value] = {}
        self._stored: dict[CellKey, Value] = {}
        self._inputs: dict[CellKey, Value] = {}
        self._memo: dict[CellKey, Value] = {}
        self._in_progress: set[CellKey] = set()
        self._formula_rows: dict[str, list[int]] = {}
        self._formula_cols: dict[tuple[str, int], list[int]] = {}
        self._bounds: dict[str, tuple[int, int]] = {}
        self._defined: dict[str, str] = {}
        self._defined_local: dict[tuple[str, str], str] = {}
        self._load(Path(path))

    # ------------------------------------------------------------ loading
    @classmethod
    def open(
        cls,
        path: Path,
        *,
        clock: Callable[[], float] | None = None,
        deadline: Callable[[], None] | None = None,
    ) -> Workbook:
        """Open ``path``, keeping formulas and the cached values read with ``data_only=True``.

        ``deadline`` is called while formulas are calculated; it may raise to stop a
        calculation that has exceeded the caller's time budget.
        """
        return cls(path, clock=clock, deadline=deadline)

    def _load(self, path: Path) -> None:
        book = load_workbook(path)
        if book.epoch == MAC_EPOCH:
            raise ValueError(
                f"{path} uses the 1904 date system, which is not supported; "
                "resave it with the 1900 date system"
            )
        cached = load_workbook(path, data_only=True)

        self._sheets = list(book.sheetnames)
        self._sheet_set = set(self._sheets)
        for worksheet in book.worksheets:
            self._tick()
            sheet = str(worksheet.title)
            for row in worksheet.iter_rows():
                for cell in row:
                    if cell.value is None:
                        continue
                    key = (sheet, int(cell.row) - 1, int(cell.column) - 1)
                    if cell.data_type == "f":
                        formula = _formula_text(cell.value)
                        if formula is not None:
                            self._formulas[key] = formula
                        continue
                    self._literals[key] = python_value(cell.value)

        for worksheet in cached.worksheets:
            self._tick()
            sheet = str(worksheet.title)
            for row in worksheet.iter_rows():
                for cell in row:
                    if cell.value is None:
                        continue
                    key = (sheet, int(cell.row) - 1, int(cell.column) - 1)
                    self._stored[key] = python_value(cell.value)

        self._load_names(book)
        self._compute_bounds()
        self._index_formulas()

    def _index_formulas(self) -> None:
        """Rows and columns of formula cells, sorted, for range lookups by bisection."""
        columns: dict[tuple[str, int], list[int]] = {}
        rows: dict[str, set[int]] = {}
        for sheet, row, col in self._formulas:
            columns.setdefault((sheet, row), []).append(col)
            rows.setdefault(sheet, set()).add(row)
        for key, cols in columns.items():
            cols.sort()
            self._formula_cols[key] = cols
        for sheet, sheet_rows in rows.items():
            self._formula_rows[sheet] = sorted(sheet_rows)

    def _load_names(self, book: Any) -> None:
        for name, definition in book.defined_names.items():
            self._store_name(str(name), definition, None)
        for worksheet in book.worksheets:
            sheet = str(worksheet.title)
            for name, definition in worksheet.defined_names.items():
                self._store_name(str(name), definition, sheet)

    def _store_name(self, name: str, definition: Any, sheet: str | None) -> None:
        text = getattr(definition, "attr_text", None)
        if not isinstance(text, str) or not text:
            return
        upper = name.upper()
        local = getattr(definition, "localSheetId", None)
        if sheet is None and isinstance(local, int) and 0 <= local < len(self._sheets):
            sheet = self._sheets[local]
        if sheet is None:
            self._defined[upper] = text
        else:
            self._defined_local[(sheet, upper)] = text

    def _compute_bounds(self) -> None:
        for sheet in self._sheets:
            self._bounds[sheet] = (-1, -1)
        for key in chain(self._literals, self._formulas, self._stored):
            sheet, row, col = key
            last_row, last_col = self._bounds.get(sheet, (-1, -1))
            self._bounds[sheet] = (max(last_row, row), max(last_col, col))

    # ------------------------------------------------------------ public API
    @property
    def sheet_names(self) -> list[str]:
        """Sheet names in workbook order."""
        return list(self._sheets)

    def value(self, sheet: str, ref: str) -> Value:
        """The calculated value of a cell: formula cells are evaluated, everything else is
        the current input or literal value read from the file."""
        key = self._key(sheet, ref)
        if key in self._formulas:
            return self._ensure(key)
        return self._plain_value(key)

    def formula(self, sheet: str, ref: str) -> str | None:
        """The formula text on a cell (``=...``), or ``None`` when it is not a formula."""
        return self._formulas.get(self._key(sheet, ref))

    def stored_value(self, sheet: str, ref: str) -> Value:
        """The cached value from the ``data_only=True`` load, regardless of inputs or memo."""
        return self._stored.get(self._key(sheet, ref))

    def set_input(self, sheet: str, ref: str, value: float | int | str | bool) -> None:
        """Set a plain input value and invalidate every memoised formula result."""
        key = self._key(sheet, ref)
        if key in self._formulas:
            raise ValueError(f"{sheet}!{ref} is a formula cell; set its precedents instead")
        if isinstance(value, bool):
            stored: Value = value
        elif isinstance(value, int | float):
            stored = float(value)
        else:
            stored = value
        self._inputs[key] = stored
        last_row, last_col = self._bounds.get(sheet, (-1, -1))
        self._bounds[sheet] = (max(last_row, key[1]), max(last_col, key[2]))
        self._memo.clear()

    def recalculate(self) -> dict[tuple[str, str], Value]:
        """Evaluate every formula cell and return the results keyed by ``(sheet, ref)``."""
        results: dict[tuple[str, str], Value] = {}
        for key in list(self._formulas):
            sheet, row, col = key
            results[(sheet, f"{col_letters(col)}{row + 1}")] = self._ensure(key)
        return results

    def save(self, dst: Path | None = None) -> None:
        """Write recalculated results and ``set_input`` changes into an ``.xlsx`` file.

        ``dst`` defaults to the path the workbook was opened from. The package is edited as
        XML, so charts, images and parts the engine does not understand are preserved.
        """
        destination = Path(dst) if dst is not None else self._path
        results = {key: self._ensure(key) for key in self._formulas}
        write_back(self._path, destination, results, self._inputs)

    def evaluate(self, sheet: str, formula_text: str) -> Value:
        """Evaluate an ad-hoc formula in the context of ``sheet``."""
        self._require_sheet(sheet)
        self._tick()
        return Evaluator(self, sheet).evaluate_text(formula_text)

    def _tick(self) -> None:
        if self._deadline is not None:
            self._deadline()

    # ------------------------------------------------------------ evaluator Host
    def cell_value(self, sheet: str, row: int, col: int) -> Value:
        key = (sheet, row, col)
        if key in self._formulas:
            return self._ensure(key)
        return self._plain_value(key)

    def has_sheet(self, sheet: str) -> bool:
        return sheet in self._sheet_set

    def used_bounds(self, sheet: str) -> tuple[int, int]:
        return self._bounds.get(sheet, (-1, -1))

    def defined_name(self, name: str, sheet: str) -> str | None:
        key = name.upper()
        local = self._defined_local.get((sheet, key))
        return local if local is not None else self._defined.get(key)

    def now_serial(self) -> float:
        if self._clock is not None:
            return self._clock()
        now = datetime.now()
        seconds = now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1e6
        return date_to_serial(now.date()) + seconds / 86400

    # ------------------------------------------------------------ cell lookup and calculation
    def _plain_value(self, key: CellKey) -> Value:
        if key in self._inputs:
            return self._inputs[key]
        if key in self._literals:
            return self._literals[key]
        return self._stored.get(key)

    def _ensure(self, root: CellKey) -> Value:
        """Evaluate ``root`` after evaluating its formula precedents, iteratively."""
        if root in self._memo:
            return self._memo[root]
        if root in self._in_progress:
            return CellError.CIRC
        if root not in self._formulas:
            return self._plain_value(root)

        stack: list[tuple[CellKey, list[CellKey], int]] = []
        entered: set[CellKey] = set()

        def push(key: CellKey) -> None:
            self._in_progress.add(key)
            entered.add(key)
            stack.append((key, self._dependencies(key), 0))

        push(root)
        try:
            while stack:
                self._tick()
                key, dependencies, index = stack[-1]
                if index < len(dependencies):
                    dependency = dependencies[index]
                    stack[-1] = (key, dependencies, index + 1)
                    if (
                        dependency in self._memo
                        or dependency in self._in_progress
                        or dependency not in self._formulas
                    ):
                        continue
                    push(dependency)
                    continue
                stack.pop()
                if key not in self._memo:
                    self._memo[key] = self._calculate(key)
                self._in_progress.discard(key)
        finally:
            for key in entered:
                self._in_progress.discard(key)
        return self._memo.get(root, CellError.CIRC)

    def _calculate(self, key: CellKey) -> Value:
        sheet, row, col = key
        return Evaluator(self, sheet, row, col).evaluate_text(self._formulas[key])

    def _dependencies(self, key: CellKey) -> list[CellKey]:
        """Formula cells whose values ``key`` reads, found from the parsed AST.

        References hidden behind ``INDIRECT`` have no static address and are not collected;
        the evaluator's re-entrant ``cell_value`` path handles those. Ranges are looked up in
        the formula-cell index, so a whole-column reference visits only populated cells.
        """
        sheet = key[0]
        try:
            expression = parse(self._formulas[key])
        except ParseError:
            return []
        found: set[CellKey] = set()
        ordered: list[CellKey] = []
        for area_sheet, r0, c0, r1, c1 in self._references(expression, sheet):
            for dependency in self._formula_cells_in(area_sheet, r0, c0, r1, c1):
                if dependency not in found:
                    found.add(dependency)
                    ordered.append(dependency)
        return ordered

    def _references(self, expression: Expr, sheet: str) -> Iterator[tuple[str, int, int, int, int]]:
        """All static references under ``expression``, resolving defined names as it goes."""
        names_seen: set[str] = set()
        stack: list[Expr] = [expression]
        while stack:
            node = stack.pop()
            if isinstance(node, Ref):
                yield (
                    node.sheet or sheet,
                    node.r0,
                    node.c0,
                    node.r1,
                    node.c1,
                )
            elif isinstance(node, Binary):
                stack.append(node.right)
                stack.append(node.left)
            elif isinstance(node, Unary):
                stack.append(node.operand)
            elif isinstance(node, Call):
                stack.extend(node.args)
            elif isinstance(node, ArrayLit):
                for row in node.rows:
                    stack.extend(row)
            elif isinstance(node, Name):
                name = node.name.upper()
                if name in names_seen:
                    continue
                names_seen.add(name)
                text = self.defined_name(name, sheet)
                if text is None:
                    continue
                try:
                    stack.append(parse(text))
                except ParseError:
                    continue

    def _formula_cells_in(
        self, sheet: str, r0: int, c0: int, r1: int, c1: int
    ) -> Iterator[CellKey]:
        rows = self._formula_rows.get(sheet)
        if not rows:
            return
        start = bisect_left(rows, r0)
        stop = bisect_right(rows, r1)
        for row in rows[start:stop]:
            columns = self._formula_cols[(sheet, row)]
            first = bisect_left(columns, c0)
            last = bisect_right(columns, c1)
            for col in columns[first:last]:
                yield (sheet, row, col)

    # ------------------------------------------------------------ addressing
    def _key(self, sheet: str, ref: str) -> CellKey:
        self._require_sheet(sheet)
        cell = parse_cell(ref.strip())
        if cell is None:
            raise ValueError(f"not a cell reference: {ref!r}")
        return (sheet, cell[0], cell[1])

    def _require_sheet(self, sheet: str) -> None:
        if sheet not in self._sheet_set:
            raise ValueError(f"no such sheet: {sheet!r}")


def _formula_text(value: object) -> str | None:
    """Formula text held on an openpyxl cell, including an array formula's anchor."""
    if isinstance(value, ArrayFormula):
        text = value.text
        return text if isinstance(text, str) and text else None
    if isinstance(value, str) and value.startswith("="):
        return value
    return None
