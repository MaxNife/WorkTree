"""Formula evaluation: references, operators, implicit intersection, array broadcasting,
lazy branches and the aggregate argument rules.

Ported from GridCraft (CraftApps, MIT OR Apache-2.0): ``gridcraft-calc/src/eval.rs``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, assert_never

from activities._formula.parser import (
    ArrayLit,
    Binary,
    Bool,
    Call,
    Err,
    Expr,
    Missing,
    Name,
    Num,
    ParseError,
    Ref,
    Text,
    Unary,
    parse,
)
from activities._formula.values import (
    Array,
    CellError,
    FormulaError,
    Value,
    compare,
    number,
    scalar,
    to_bool,
    to_number,
    to_text,
)


@dataclass(frozen=True)
class Area:
    sheet: str
    r0: int
    c0: int
    r1: int
    c1: int

    @property
    def single(self) -> bool:
        return self.r0 == self.r1 and self.c0 == self.c1

    @property
    def height(self) -> int:
        return self.r1 - self.r0 + 1

    @property
    def width(self) -> int:
        return self.c1 - self.c0 + 1


class Host(Protocol):
    """What the evaluator needs from a workbook."""

    def cell_value(self, sheet: str, row: int, col: int) -> Value: ...

    def has_sheet(self, sheet: str) -> bool: ...

    def used_bounds(self, sheet: str) -> tuple[int, int]:
        """(last row, last column) holding data, 0-based; (-1, -1) when empty."""
        ...

    def defined_name(self, name: str, sheet: str) -> str | None: ...

    def now_serial(self) -> float: ...


@dataclass
class Arg:
    """A function argument: its value (a range becomes an Array) and, when it was a
    reference, its areas."""

    value: Value
    areas: list[Area] | None = None

    @property
    def from_ref(self) -> bool:
        return self.areas is not None


Ev = Value | list[Area]
Function = Callable[["Evaluator", list[Arg]], Value]
FUNCTIONS: dict[str, Function] = {}
LAZY = {"IF", "IFS", "IFERROR", "IFNA", "CHOOSE", "SWITCH"}
REF_FUNCTIONS = {"ROW", "COLUMN", "ROWS", "COLUMNS", "ISREF", "AREAS"}


class Evaluator:
    def __init__(self, host: Host, sheet: str, row: int = 0, col: int = 0) -> None:
        self.host = host
        self.sheet = sheet
        self.row = row
        self.col = col
        self.names_in_progress: set[str] = set()

    # ------------------------------------------------------------ entry points
    def evaluate_text(self, formula: str) -> Value:
        try:
            expr = parse(formula)
        except ParseError:
            return CellError.NAME
        return self.value(expr)

    def value(self, expr: Expr) -> Value:
        return self.deref(self.eval(expr))

    def deref(self, ev: Ev) -> Value:
        if not isinstance(ev, list):
            return ev
        if len(ev) != 1:
            return CellError.VALUE
        return self.area_value(ev[0])

    def area_value(self, area: Area) -> Value:
        if area.single:
            return self.host.cell_value(area.sheet, area.r0, area.c0)
        last_row, last_col = self.host.used_bounds(area.sheet)
        r1, c1 = min(area.r1, max(last_row, area.r0)), min(area.c1, max(last_col, area.c0))
        rows = [
            [self.host.cell_value(area.sheet, r, c) for c in range(area.c0, c1 + 1)]
            for r in range(area.r0, r1 + 1)
        ]
        return Array.of(rows)

    def scalar_of(self, arg: Arg) -> Value:
        """One value from an argument: a multi-cell reference intersects the formula's row or
        column (Excel's implicit intersection); an array gives its top-left element."""
        if arg.areas is not None and len(arg.areas) == 1 and not arg.areas[0].single:
            area = arg.areas[0]
            if area.width == 1 and area.r0 <= self.row <= area.r1:
                return self.host.cell_value(area.sheet, self.row, area.c0)
            if area.height == 1 and area.c0 <= self.col <= area.c1:
                return self.host.cell_value(area.sheet, area.r0, self.col)
            return CellError.VALUE
        return scalar(arg.value)

    # ------------------------------------------------------------ evaluation
    def eval(self, expr: Expr) -> Ev:
        try:
            return self._eval(expr)
        except FormulaError as exc:
            return exc.error
        except RecursionError:
            return CellError.CALC

    def _eval(self, expr: Expr) -> Ev:
        if isinstance(expr, Num):
            return number(expr.value)
        if isinstance(expr, Text):
            return expr.value
        if isinstance(expr, Bool):
            return expr.value
        if isinstance(expr, Err):
            return expr.error
        if isinstance(expr, Missing):
            return None
        if isinstance(expr, Ref):
            sheet = expr.sheet or self.sheet
            if not self.host.has_sheet(sheet):
                return CellError.REF
            return [Area(sheet, expr.r0, expr.c0, expr.r1, expr.c1)]
        if isinstance(expr, Name):
            return self._name(expr.name)
        if isinstance(expr, ArrayLit):
            rows = [[self.value(item) for item in row] for row in expr.rows]
            return Array.of(rows)
        if isinstance(expr, Unary):
            return self._unary(expr)
        if isinstance(expr, Binary):
            return self._binary(expr)
        if isinstance(expr, Call):
            return self._call(expr.name, list(expr.args))
        assert_never(expr)

    def _name(self, name: str) -> Ev:
        key = name.upper()
        formula = self.host.defined_name(key, self.sheet)
        if formula is None or key in self.names_in_progress:
            return CellError.NAME
        self.names_in_progress.add(key)
        try:
            return self.eval(parse(formula))
        except ParseError:
            return CellError.NAME
        finally:
            self.names_in_progress.discard(key)

    def _unary(self, expr: Unary) -> Ev:
        if expr.op == "@":
            ev = self.eval(expr.operand)
            if isinstance(ev, list):
                return self.scalar_of(Arg(self.deref(ev) if len(ev) == 1 else None, ev))
            return scalar(ev)
        value = self.value(expr.operand)
        if expr.op == "-":
            return _map(value, lambda x: number(-x))
        if expr.op == "%":
            return _map(value, lambda x: number(x / 100))
        return value  # unary plus keeps the value as it is

    def _binary(self, expr: Binary) -> Ev:
        op = expr.op
        if op in (":", ",", " "):
            left, right = self.eval(expr.left), self.eval(expr.right)
            for side in (left, right):
                if isinstance(side, CellError):
                    return side
            if not isinstance(left, list) or not isinstance(right, list):
                return CellError.VALUE
            if op == ",":
                return left + right
            if op == ":":
                areas = left + right
                if any(a.sheet != areas[0].sheet for a in areas):
                    return CellError.VALUE
                return [
                    Area(
                        areas[0].sheet,
                        min(a.r0 for a in areas),
                        min(a.c0 for a in areas),
                        max(a.r1 for a in areas),
                        max(a.c1 for a in areas),
                    )
                ]
            out = []
            for p in left:
                for q in right:
                    if p.sheet != q.sheet:
                        continue
                    r0, c0, r1, c1 = (
                        max(p.r0, q.r0),
                        max(p.c0, q.c0),
                        min(p.r1, q.r1),
                        min(p.c1, q.c1),
                    )
                    if r0 <= r1 and c0 <= c1:
                        out.append(Area(p.sheet, r0, c0, r1, c1))
            return out or CellError.NULL
        return binary_values(op, self.value(expr.left), self.value(expr.right))

    # ------------------------------------------------------------ calls
    def _call(self, name: str, args: list[Expr]) -> Ev:
        if name in LAZY:
            return self._lazy(name, args)
        function = FUNCTIONS.get(name)
        if function is None:
            return CellError.NAME
        evaluated: list[Arg] = []
        for expr in args:
            ev = self.eval(expr)
            if isinstance(ev, list):
                value = self.area_value(ev[0]) if len(ev) == 1 else CellError.VALUE
                evaluated.append(Arg(value, ev))
            else:
                evaluated.append(Arg(ev))
        try:
            return function(self, evaluated)
        except FormulaError as exc:
            return exc.error
        except (ValueError, OverflowError, ZeroDivisionError):
            return CellError.NUM

    def _lazy(self, name: str, args: list[Expr]) -> Ev:
        if name == "IF":
            if not 1 <= len(args) <= 3:
                return CellError.VALUE
            condition = scalar(self.value(args[0]))
            if isinstance(condition, CellError):
                return condition
            try:
                truth = to_bool(condition)
            except FormulaError as exc:
                return exc.error
            if truth:
                return self.eval(args[1]) if len(args) > 1 else True
            return self.eval(args[2]) if len(args) > 2 else False
        if name in ("IFERROR", "IFNA"):
            if len(args) != 2:
                return CellError.VALUE
            first = self.eval(args[0])
            value = self.deref(first) if isinstance(first, list) else first
            caught = isinstance(value, CellError) and (name == "IFERROR" or value == CellError.NA)
            return self.eval(args[1]) if caught else first
        if name == "IFS":
            if len(args) < 2 or len(args) % 2:
                return CellError.VALUE
            for i in range(0, len(args), 2):
                condition = scalar(self.value(args[i]))
                if isinstance(condition, CellError):
                    return condition
                try:
                    if to_bool(condition):
                        return self.eval(args[i + 1])
                except FormulaError as exc:
                    return exc.error
            return CellError.NA
        if name == "CHOOSE":
            if len(args) < 2:
                return CellError.VALUE
            try:
                index = int(to_number(self.value(args[0])))
            except FormulaError as exc:
                return exc.error
            except (OverflowError, ValueError):
                return CellError.VALUE
            if not 1 <= index < len(args):
                return CellError.VALUE
            return self.eval(args[index])
        # SWITCH(expression, value1, result1, ..., [default])
        if len(args) < 3:
            return CellError.VALUE
        target = scalar(self.value(args[0]))
        if isinstance(target, CellError):
            return target
        pairs = len(args) - 1
        for i in range(1, pairs - pairs % 2 + 1, 2):
            candidate = scalar(self.value(args[i]))
            if isinstance(candidate, CellError):
                return candidate
            if compare(target, candidate) == 0 and _same_kind(target, candidate):
                return self.eval(args[i + 1])
        return self.eval(args[-1]) if pairs % 2 else CellError.NA


def _same_kind(a: Value, b: Value) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool)
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str)
    return True


def _map(value: Value, f: Callable[[float], Value]) -> Value:
    if isinstance(value, Array):
        return Array(value.rows, value.cols, tuple(_map(v, f) for v in value.data))
    try:
        return f(to_number(value))
    except FormulaError as exc:
        return exc.error


def binary_values(op: str, a: Value, b: Value) -> Value:
    """An operator over two values; arrays broadcast element-wise."""
    if isinstance(a, Array) or isinstance(b, Array):
        x = a if isinstance(a, Array) else Array(1, 1, (a,))
        y = b if isinstance(b, Array) else Array(1, 1, (b,))
        rows = _broadcast(x.rows, y.rows)
        cols = _broadcast(x.cols, y.cols)
        data = tuple(
            _binary_scalar(op, x.broadcast(r, c), y.broadcast(r, c))
            for r in range(rows)
            for c in range(cols)
        )
        return Array(rows, cols, data)
    return _binary_scalar(op, a, b)


def _broadcast(a: int, b: int) -> int:
    if a == 1:
        return b
    if b == 1:
        return a
    return max(a, b)


def _binary_scalar(op: str, a: Value, b: Value) -> Value:
    if isinstance(a, CellError):
        return a
    if isinstance(b, CellError):
        return b
    try:
        if op == "&":
            return to_text(a) + to_text(b)
        if op in ("=", "<>", "<", ">", "<=", ">="):
            order = compare(a, b)
            return {
                "=": order == 0,
                "<>": order != 0,
                "<": order < 0,
                ">": order > 0,
                "<=": order <= 0,
                ">=": order >= 0,
            }[op]
        x, y = to_number(a), to_number(b)
    except FormulaError as exc:
        return exc.error
    if op == "+":
        return number(x + y)
    if op == "-":
        return number(x - y)
    if op == "*":
        return number(x * y)
    if op == "/":
        return CellError.DIV0 if y == 0 else number(x / y)
    if op == "^":
        if x == 0 and y < 0:
            return CellError.DIV0
        if x == 0 and y == 0:
            return CellError.NUM
        try:
            result = x**y
        except OverflowError:
            return CellError.NUM
        return CellError.NUM if isinstance(result, complex) else number(result)
    return CellError.VALUE


def register(*names: str) -> Callable[[Function], Function]:
    def decorator(function: Function) -> Function:
        for name in names:
            FUNCTIONS[name] = function
        return function

    return decorator
