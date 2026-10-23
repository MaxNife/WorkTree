"""Worksheet functions.

Ported from GridCraft (CraftApps, MIT OR Apache-2.0): ``gridcraft-functions/src`` (math, stat,
logical, info, text, date, lookup, financial). Argument rules follow GridCraft's aggregate
semantics: inside a reference or array only numbers count; a direct scalar argument is coerced.
"""

from __future__ import annotations

import itertools
import math
import re
import statistics
from collections.abc import Callable, Iterable
from datetime import date, timedelta

from activities._formula.evaluator import Arg, Evaluator, register
from activities._formula.values import (
    Array,
    CellError,
    FormulaError,
    Value,
    compare,
    date_to_serial,
    number,
    number_to_text,
    parse_datetime_text,
    parse_number_text,
    serial_to_date,
    to_bool,
    to_number,
    to_text,
)

# ---------------------------------------------------------------- argument helpers


def _fail(error: CellError = CellError.VALUE) -> FormulaError:
    return FormulaError(error)


@register("WEBSERVICE", "FILTERXML")
def _web_function(ctx: Evaluator, args: list[Arg]) -> Value:
    """Web functions are deliberately not implemented: a workbook cannot make the worker
    fetch a URL. They fail the same way the previous engine reported them (#VALUE!)."""
    raise _fail()


def _arg(ctx: Evaluator, args: list[Arg], i: int) -> Value:
    if i >= len(args):
        raise _fail()
    value = ctx.scalar_of(args[i])
    if isinstance(value, CellError):
        raise FormulaError(value)
    return value


def _num(ctx: Evaluator, args: list[Arg], i: int, default: float | None = None) -> float:
    if i >= len(args) or (args[i].value is None and not args[i].from_ref and default is not None):
        if default is None:
            raise _fail()
        return default
    return to_number(_arg(ctx, args, i))


def _text(ctx: Evaluator, args: list[Arg], i: int, default: str | None = None) -> str:
    if i >= len(args):
        if default is None:
            raise _fail()
        return default
    return to_text(_arg(ctx, args, i))


def _bool(ctx: Evaluator, args: list[Arg], i: int, default: bool) -> bool:
    if i >= len(args) or (args[i].value is None and not args[i].from_ref):
        return default
    return to_bool(_arg(ctx, args, i))


def _count(args: list[Arg], low: int, high: int | None = None) -> None:
    if len(args) < low or (high is not None and len(args) > high):
        raise _fail()


def _values(value: Value) -> list[Value]:
    if isinstance(value, Array):
        return list(value.data)
    return [value]


def _numbers(args: Iterable[Arg], *, count_text: bool = False) -> list[float]:
    """Numbers for SUM/AVERAGE-style functions. References and arrays contribute numbers only
    (errors propagate); direct scalars are coerced (non-numeric text is #VALUE!)."""
    out: list[float] = []
    for arg in args:
        if arg.from_ref or isinstance(arg.value, Array):
            for value in _values(arg.value):
                if isinstance(value, CellError):
                    raise FormulaError(value)
                if isinstance(value, float | int) and not isinstance(value, bool):
                    out.append(float(value))
                elif count_text and isinstance(value, str | bool):
                    out.append(1.0 if value is True else 0.0)
        else:
            value = arg.value
            if isinstance(value, CellError):
                raise FormulaError(value)
            if value is None:
                continue
            out.append(to_number(value))
    return out


def _array(arg: Arg) -> Array:
    value = arg.value
    if isinstance(value, Array):
        return value
    return Array(1, 1, (value,))


def _check(value: float) -> Value:
    result = number(value)
    if isinstance(result, CellError):
        raise FormulaError(result)
    return result


# ---------------------------------------------------------------- criteria (SUMIF & co)

_CRITERION = re.compile(r"^(<=|>=|<>|=|<|>)?(.*)$", re.S)


def _criterion(raw: Value) -> Callable[[Value], bool]:
    if isinstance(raw, CellError):
        raise FormulaError(raw)
    if not isinstance(raw, str):
        target = raw
        return lambda v: v is not None and compare(v, target) == 0 and _kind_match(v, target)
    match = _CRITERION.match(raw)
    assert match is not None
    op, operand = match.group(1) or "=", match.group(2)
    as_number = parse_number_text(operand) if operand else None
    if as_number is not None:
        target_num = as_number

        def numeric(v: Value) -> bool:
            if isinstance(v, bool) or not isinstance(v, float | int):
                return op == "<>"
            order = compare(float(v), target_num)
            return _apply(op, order)

        return numeric
    upper = operand.upper()
    if upper in ("TRUE", "FALSE"):
        flag = upper == "TRUE"
        return lambda v: _apply(op, 0 if v is flag else 1) if op in ("=", "<>") else False
    if op in ("=", "<>"):
        if operand == "":
            return (
                (lambda v: v is None or v == "")
                if op == "="
                else (lambda v: not (v is None or v == ""))
            )
        pattern = _wildcard(operand)

        def textual(v: Value) -> bool:
            hit = isinstance(v, str) and pattern.fullmatch(v) is not None
            return hit if op == "=" else not hit

        return textual
    return lambda v: isinstance(v, str) and _apply(op, compare(v, operand))


def _apply(op: str, order: int) -> bool:
    return {
        "=": order == 0,
        "<>": order != 0,
        "<": order < 0,
        ">": order > 0,
        "<=": order <= 0,
        ">=": order >= 0,
    }[op]


def _kind_match(a: Value, b: Value) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool)
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str)
    return True


def _wildcard(text: str) -> re.Pattern[str]:
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "~" and i + 1 < len(text) and text[i + 1] in "*?~":
            out.append(re.escape(text[i + 1]))
            i += 2
            continue
        out.append(".*" if ch == "*" else "." if ch == "?" else re.escape(ch))
        i += 1
    return re.compile("".join(out), re.I | re.S)


def _matching(ctx: Evaluator, args: list[Arg], start: int) -> list[bool]:
    """Criteria pairs (range, criterion) from ``start``: a mask over the first range's cells."""
    if (len(args) - start) % 2 or len(args) - start < 2:
        raise _fail()
    mask: list[bool] | None = None
    shape: tuple[int, int] | None = None
    for i in range(start, len(args), 2):
        cells = _array(args[i])
        if shape is None:
            shape = (cells.rows, cells.cols)
        elif (cells.rows, cells.cols) != shape:
            raise _fail()
        test = _criterion(ctx.scalar_of(args[i + 1]))
        hits = [test(v) for v in cells.data]
        mask = hits if mask is None else [a and b for a, b in zip(mask, hits, strict=True)]
    return mask or []


def _masked_numbers(values: Array, mask: list[bool]) -> list[float]:
    if len(values.data) != len(mask):
        raise _fail()
    out = []
    for value, hit in zip(values.data, mask, strict=True):
        if hit and isinstance(value, float | int) and not isinstance(value, bool):
            out.append(float(value))
    return out


# ---------------------------------------------------------------- math and statistics


@register("SUM")
def _sum(ctx: Evaluator, args: list[Arg]) -> Value:
    return _check(math.fsum(_numbers(args)))


@register("PRODUCT")
def _product(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _numbers(args)
    return _check(math.prod(values)) if values else 0.0


@register("SUMSQ")
def _sumsq(ctx: Evaluator, args: list[Arg]) -> Value:
    return _check(math.fsum(v * v for v in _numbers(args)))


@register("AVERAGE")
def _average(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _numbers(args)
    if not values:
        raise _fail(CellError.DIV0)
    return _check(math.fsum(values) / len(values))


@register("AVERAGEA")
def _averagea(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _numbers(args, count_text=True)
    if not values:
        raise _fail(CellError.DIV0)
    return _check(math.fsum(values) / len(values))


@register("COUNT")
def _count_fn(ctx: Evaluator, args: list[Arg]) -> Value:
    total = 0
    for arg in args:
        for value in _values(arg.value):
            if isinstance(value, bool):
                total += 0 if (arg.from_ref or isinstance(arg.value, Array)) else 1
            elif isinstance(value, float | int):
                total += 1
            elif isinstance(value, str) and not arg.from_ref and not isinstance(arg.value, Array):
                total += 1 if parse_number_text(value) is not None else 0
    return float(total)


@register("COUNTA")
def _counta(ctx: Evaluator, args: list[Arg]) -> Value:
    total = 0
    for arg in args:
        for value in _values(arg.value):
            if value is not None or not (arg.from_ref or isinstance(arg.value, Array)):
                total += 1
    return float(total)


@register("COUNTBLANK")
def _countblank(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 1, 1)
    return float(sum(1 for v in _values(args[0].value) if v is None or v == ""))


@register("MAX")
def _max(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _numbers(args)
    return max(values) if values else 0.0


@register("MIN")
def _min(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _numbers(args)
    return min(values) if values else 0.0


@register("MEDIAN")
def _median(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _numbers(args)
    if not values:
        raise _fail(CellError.NUM)
    return _check(statistics.median(values))


@register("STDEV", "STDEV.S")
def _stdev(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _numbers(args)
    if len(values) < 2:
        raise _fail(CellError.DIV0)
    return _check(statistics.stdev(values))


@register("STDEV.P", "STDEVP")
def _stdevp(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _numbers(args)
    if not values:
        raise _fail(CellError.DIV0)
    return _check(statistics.pstdev(values))


@register("VAR", "VAR.S")
def _var(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _numbers(args)
    if len(values) < 2:
        raise _fail(CellError.DIV0)
    return _check(statistics.variance(values))


@register("VAR.P", "VARP")
def _varp(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _numbers(args)
    if not values:
        raise _fail(CellError.DIV0)
    return _check(statistics.pvariance(values))


@register("LARGE")
def _large(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 2)
    values = sorted(_numbers(args[:1]), reverse=True)
    k = math.ceil(_num(ctx, args, 1))
    if not values or not 1 <= k <= len(values):
        raise _fail(CellError.NUM)
    return values[k - 1]


@register("SMALL")
def _small(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 2)
    values = sorted(_numbers(args[:1]))
    k = math.ceil(_num(ctx, args, 1))
    if not values or not 1 <= k <= len(values):
        raise _fail(CellError.NUM)
    return values[k - 1]


@register("RANK", "RANK.EQ")
def _rank(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 3)
    target = _num(ctx, args, 0)
    values = _numbers(args[1:2])
    ascending = _num(ctx, args, 2, 0.0) != 0
    if not any(compare(v, target) == 0 for v in values):
        raise _fail(CellError.NA)
    better = sum(1 for v in values if (v < target if ascending else v > target))
    return float(better + 1)


@register("SUMIF")
def _sumif(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 3)
    mask = _matching(ctx, args[:2], 0)
    target = _array(args[2]) if len(args) == 3 else _array(args[0])
    return _check(math.fsum(_masked_numbers(target, mask)))


@register("SUMIFS")
def _sumifs(ctx: Evaluator, args: list[Arg]) -> Value:
    mask = _matching(ctx, args, 1)
    return _check(math.fsum(_masked_numbers(_array(args[0]), mask)))


@register("COUNTIF")
def _countif(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 2)
    return float(sum(_matching(ctx, args, 0)))


@register("COUNTIFS")
def _countifs(ctx: Evaluator, args: list[Arg]) -> Value:
    return float(sum(_matching(ctx, args, 0)))


@register("AVERAGEIF")
def _averageif(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 3)
    mask = _matching(ctx, args[:2], 0)
    values = _masked_numbers(_array(args[2]) if len(args) == 3 else _array(args[0]), mask)
    if not values:
        raise _fail(CellError.DIV0)
    return _check(math.fsum(values) / len(values))


@register("AVERAGEIFS")
def _averageifs(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _masked_numbers(_array(args[0]), _matching(ctx, args, 1))
    if not values:
        raise _fail(CellError.DIV0)
    return _check(math.fsum(values) / len(values))


@register("MAXIFS")
def _maxifs(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _masked_numbers(_array(args[0]), _matching(ctx, args, 1))
    return max(values) if values else 0.0


@register("MINIFS")
def _minifs(ctx: Evaluator, args: list[Arg]) -> Value:
    values = _masked_numbers(_array(args[0]), _matching(ctx, args, 1))
    return min(values) if values else 0.0


@register("SUMPRODUCT")
def _sumproduct(ctx: Evaluator, args: list[Arg]) -> Value:
    if not args:
        raise _fail()
    arrays = [_array(a) for a in args]
    shape = (arrays[0].rows, arrays[0].cols)
    if any((a.rows, a.cols) != shape for a in arrays):
        raise _fail()
    total = 0.0
    for i in range(len(arrays[0].data)):
        product = 1.0
        for a in arrays:
            value = a.data[i]
            if isinstance(value, CellError):
                raise FormulaError(value)
            product *= (
                float(value)
                if isinstance(value, float | int) and not isinstance(value, bool)
                else 0.0
            )
        total += product
    return _check(total)


def _round_half_away(x: float, digits: int) -> float:
    factor = 10.0**digits
    scaled = abs(x) * factor
    # Correct binary noise (2.675 is stored as 2.67499...): round at 15 significant digits.
    scaled = float(f"{scaled:.15g}")
    return math.copysign(math.floor(scaled + 0.5) / factor, x)


@register("ROUND")
def _round(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 2)
    return _check(_round_half_away(_num(ctx, args, 0), int(_num(ctx, args, 1))))


@register("ROUNDUP")
def _roundup(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 2)
    x, factor = _num(ctx, args, 0), 10.0 ** int(_num(ctx, args, 1))
    scaled = float(f"{abs(x) * factor:.15g}")
    return _check(math.copysign(math.ceil(scaled) / factor, x))


@register("ROUNDDOWN")
def _rounddown(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 2)
    x, factor = _num(ctx, args, 0), 10.0 ** int(_num(ctx, args, 1))
    scaled = float(f"{abs(x) * factor:.15g}")
    return _check(math.copysign(math.floor(scaled) / factor, x))


@register("TRUNC")
def _trunc(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 1, 2)
    x, factor = _num(ctx, args, 0), 10.0 ** int(_num(ctx, args, 1, 0.0))
    return _check(math.trunc(x * factor) / factor)


@register("INT")
def _int(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 1, 1)
    return _check(float(math.floor(_num(ctx, args, 0))))


@register("MROUND")
def _mround(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 2)
    x, m = _num(ctx, args, 0), _num(ctx, args, 1)
    if m == 0:
        return 0.0
    if x * m < 0:
        raise _fail(CellError.NUM)
    return _check(_round_half_away(x / m, 0) * m)


@register("CEILING", "CEILING.MATH")
def _ceiling(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 1, 3)
    x, sig = _num(ctx, args, 0), _num(ctx, args, 1, 1.0)
    if sig == 0:
        return 0.0
    return _check(math.ceil(x / abs(sig)) * abs(sig))


@register("FLOOR", "FLOOR.MATH")
def _floor(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 1, 3)
    x, sig = _num(ctx, args, 0), _num(ctx, args, 1, 1.0)
    if sig == 0:
        raise _fail(CellError.DIV0)
    return _check(math.floor(x / abs(sig)) * abs(sig))


def _unary(
    name: str, f: Callable[[float], float], domain: Callable[[float], bool] = lambda _: True
) -> None:
    def function(ctx: Evaluator, args: list[Arg]) -> Value:
        _count(args, 1, 1)
        x = _num(ctx, args, 0)
        if not domain(x):
            raise _fail(CellError.NUM)
        return _check(f(x))

    register(name)(function)


_unary("ABS", abs)
_unary("SQRT", math.sqrt, lambda x: x >= 0)
_unary("EXP", math.exp)
_unary("LN", math.log, lambda x: x > 0)
_unary("LOG10", math.log10, lambda x: x > 0)
_unary("SIGN", lambda x: float((x > 0) - (x < 0)))
_unary("EVEN", lambda x: math.copysign(math.ceil(abs(x) / 2) * 2, x))
_unary("ODD", lambda x: math.copysign(math.ceil((abs(x) - 1) / 2) * 2 + 1, x) if x else 1.0)
_unary("FACT", lambda x: float(math.factorial(int(x))), lambda x: 0 <= x <= 170)
_unary("RADIANS", math.radians)
_unary("DEGREES", math.degrees)
_unary("SIN", math.sin)
_unary("COS", math.cos)
_unary("TAN", math.tan)


@register("LOG")
def _log(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 1, 2)
    x, base = _num(ctx, args, 0), _num(ctx, args, 1, 10.0)
    if x <= 0 or base <= 0:
        raise _fail(CellError.NUM)
    if base == 1:
        raise _fail(CellError.DIV0)
    return _check(math.log(x, base))


@register("POWER")
def _power(ctx: Evaluator, args: list[Arg]) -> Value:
    from activities._formula.evaluator import binary_values

    _count(args, 2, 2)
    return binary_values("^", _num(ctx, args, 0), _num(ctx, args, 1))


@register("MOD")
def _mod(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 2)
    x, d = _num(ctx, args, 0), _num(ctx, args, 1)
    if d == 0:
        raise _fail(CellError.DIV0)
    return _check(x - d * math.floor(x / d))


@register("QUOTIENT")
def _quotient(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 2)
    x, d = _num(ctx, args, 0), _num(ctx, args, 1)
    if d == 0:
        raise _fail(CellError.DIV0)
    return float(math.trunc(x / d))


@register("GCD")
def _gcd(ctx: Evaluator, args: list[Arg]) -> Value:
    values = [int(v) for v in _numbers(args)]
    if any(v < 0 for v in values):
        raise _fail(CellError.NUM)
    return float(math.gcd(*values)) if values else 0.0


@register("LCM")
def _lcm(ctx: Evaluator, args: list[Arg]) -> Value:
    values = [int(v) for v in _numbers(args)]
    if any(v < 0 for v in values):
        raise _fail(CellError.NUM)
    return float(math.lcm(*values)) if values else 0.0


@register("PI")
def _pi(ctx: Evaluator, args: list[Arg]) -> Value:
    return math.pi


# ---------------------------------------------------------------- logical and information


@register("TRUE")
def _true(ctx: Evaluator, args: list[Arg]) -> Value:
    return True


@register("FALSE")
def _false(ctx: Evaluator, args: list[Arg]) -> Value:
    return False


def _logicals(args: list[Arg]) -> list[bool]:
    out: list[bool] = []
    for arg in args:
        if arg.from_ref or isinstance(arg.value, Array):
            for value in _values(arg.value):
                if isinstance(value, CellError):
                    raise FormulaError(value)
                if isinstance(value, bool):
                    out.append(value)
                elif isinstance(value, float | int):
                    out.append(value != 0)
        else:
            out.append(to_bool(arg.value))
    if not out:
        raise _fail()
    return out


@register("AND")
def _and(ctx: Evaluator, args: list[Arg]) -> Value:
    return all(_logicals(args))


@register("OR")
def _or(ctx: Evaluator, args: list[Arg]) -> Value:
    return any(_logicals(args))


@register("XOR")
def _xor(ctx: Evaluator, args: list[Arg]) -> Value:
    return sum(_logicals(args)) % 2 == 1


@register("NOT")
def _not(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 1, 1)
    return not to_bool(_arg(ctx, args, 0))


def _is(name: str, test: Callable[[Value], bool]) -> None:
    def function(ctx: Evaluator, args: list[Arg]) -> Value:
        _count(args, 1, 1)
        return test(ctx.scalar_of(args[0]))

    register(name)(function)


_is("ISBLANK", lambda v: v is None)
_is("ISNUMBER", lambda v: isinstance(v, float | int) and not isinstance(v, bool))
_is("ISTEXT", lambda v: isinstance(v, str))
_is("ISNONTEXT", lambda v: not isinstance(v, str))
_is("ISLOGICAL", lambda v: isinstance(v, bool))
_is("ISERROR", lambda v: isinstance(v, CellError))
_is("ISERR", lambda v: isinstance(v, CellError) and v != CellError.NA)
_is("ISNA", lambda v: v == CellError.NA)


@register("ISEVEN")
def _iseven(ctx: Evaluator, args: list[Arg]) -> Value:
    return math.trunc(_num(ctx, args, 0)) % 2 == 0


@register("ISODD")
def _isodd(ctx: Evaluator, args: list[Arg]) -> Value:
    return math.trunc(_num(ctx, args, 0)) % 2 == 1


@register("ISREF")
def _isref(ctx: Evaluator, args: list[Arg]) -> Value:
    return bool(args) and args[0].from_ref


@register("NA")
def _na(ctx: Evaluator, args: list[Arg]) -> Value:
    return CellError.NA


@register("ERROR.TYPE")
def _error_type(ctx: Evaluator, args: list[Arg]) -> Value:
    value = ctx.scalar_of(args[0]) if args else None
    if isinstance(value, CellError):
        return float(value.code)
    return CellError.NA


@register("N")
def _n(ctx: Evaluator, args: list[Arg]) -> Value:
    value = ctx.scalar_of(args[0]) if args else None
    if isinstance(value, CellError):
        return value
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value) if isinstance(value, float | int) else 0.0


@register("T")
def _t(ctx: Evaluator, args: list[Arg]) -> Value:
    value = ctx.scalar_of(args[0]) if args else None
    if isinstance(value, CellError):
        return value
    return value if isinstance(value, str) else ""


# ---------------------------------------------------------------- text


@register("CONCATENATE")
def _concatenate(ctx: Evaluator, args: list[Arg]) -> Value:
    return "".join(_text(ctx, args, i) for i in range(len(args)))


def _texts(args: list[Arg]) -> list[str]:
    out = []
    for arg in args:
        for value in _values(arg.value):
            if isinstance(value, CellError):
                raise FormulaError(value)
            out.append(to_text(value))
    return out


@register("CONCAT")
def _concat(ctx: Evaluator, args: list[Arg]) -> Value:
    return "".join(_texts(args))


@register("TEXTJOIN")
def _textjoin(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3)
    delimiter, skip_empty = _text(ctx, args, 0), _bool(ctx, args, 1, True)
    parts = [t for t in _texts(args[2:]) if t or not skip_empty]
    return delimiter.join(parts)


@register("LEFT")
def _left(ctx: Evaluator, args: list[Arg]) -> Value:
    count = int(_num(ctx, args, 1, 1.0))
    if count < 0:
        raise _fail()
    return _text(ctx, args, 0)[:count]


@register("RIGHT")
def _right(ctx: Evaluator, args: list[Arg]) -> Value:
    count = int(_num(ctx, args, 1, 1.0))
    if count < 0:
        raise _fail()
    text = _text(ctx, args, 0)
    return text[len(text) - count :] if count else ""


@register("MID")
def _mid(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3, 3)
    text, start, count = _text(ctx, args, 0), int(_num(ctx, args, 1)), int(_num(ctx, args, 2))
    if start < 1 or count < 0:
        raise _fail()
    return text[start - 1 : start - 1 + count]


@register("LEN")
def _len(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 1, 1)
    return float(len(_text(ctx, args, 0)))


@register("UPPER")
def _upper(ctx: Evaluator, args: list[Arg]) -> Value:
    return _text(ctx, args, 0).upper()


@register("LOWER")
def _lower(ctx: Evaluator, args: list[Arg]) -> Value:
    return _text(ctx, args, 0).lower()


@register("PROPER")
def _proper(ctx: Evaluator, args: list[Arg]) -> Value:
    return re.sub(r"[A-Za-zÀ-￿]+", lambda m: m.group(0).capitalize(), _text(ctx, args, 0))


@register("TRIM")
def _trim(ctx: Evaluator, args: list[Arg]) -> Value:
    # Excel's TRIM removes leading/trailing spaces and collapses inner runs to one space.
    return re.sub(r" +", " ", _text(ctx, args, 0).strip(" "))


@register("CLEAN")
def _clean(ctx: Evaluator, args: list[Arg]) -> Value:
    return "".join(ch for ch in _text(ctx, args, 0) if ord(ch) >= 32)


@register("EXACT")
def _exact(ctx: Evaluator, args: list[Arg]) -> Value:
    return _text(ctx, args, 0) == _text(ctx, args, 1)


@register("REPT")
def _rept(ctx: Evaluator, args: list[Arg]) -> Value:
    times = int(_num(ctx, args, 1))
    text = _text(ctx, args, 0)
    if times < 0 or len(text) * times > 32767:
        raise _fail()
    return text * times


@register("SUBSTITUTE")
def _substitute(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3, 4)
    text, old, new = _text(ctx, args, 0), _text(ctx, args, 1), _text(ctx, args, 2)
    if not old:
        return text
    if len(args) == 3:
        return text.replace(old, new)
    nth = int(_num(ctx, args, 3))
    if nth < 1:
        raise _fail()
    index = -1
    for _ in range(nth):
        index = text.find(old, index + 1)
        if index < 0:
            return text
    return text[:index] + new + text[index + len(old) :]


@register("REPLACE")
def _replace(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 4, 4)
    text, start, count, new = (
        _text(ctx, args, 0),
        int(_num(ctx, args, 1)),
        int(_num(ctx, args, 2)),
        _text(ctx, args, 3),
    )
    if start < 1 or count < 0:
        raise _fail()
    return text[: start - 1] + new + text[start - 1 + count :]


@register("FIND")
def _find(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 3)
    needle, haystack, start = _text(ctx, args, 0), _text(ctx, args, 1), int(_num(ctx, args, 2, 1.0))
    if start < 1 or start > len(haystack) + 1:
        raise _fail()
    index = haystack.find(needle, start - 1)
    if index < 0:
        raise _fail()
    return float(index + 1)


@register("SEARCH")
def _search(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 3)
    needle, haystack, start = _text(ctx, args, 0), _text(ctx, args, 1), int(_num(ctx, args, 2, 1.0))
    if start < 1 or start > len(haystack) + 1:
        raise _fail()
    match = re.compile(_wildcard(needle).pattern, re.I | re.S).search(haystack, start - 1)
    if match is None:
        raise _fail()
    return float(match.start() + 1)


@register("VALUE")
def _value(ctx: Evaluator, args: list[Arg]) -> Value:
    value = _arg(ctx, args, 0)
    if isinstance(value, float | int) and not isinstance(value, bool):
        return float(value)
    parsed = parse_number_text(to_text(value))
    if parsed is None:
        raise _fail()
    return parsed


@register("CHAR")
def _char(ctx: Evaluator, args: list[Arg]) -> Value:
    code = int(_num(ctx, args, 0))
    if not 1 <= code <= 255:
        raise _fail()
    return bytes([code]).decode("cp1252", errors="replace")


@register("CODE")
def _code(ctx: Evaluator, args: list[Arg]) -> Value:
    text = _text(ctx, args, 0)
    if not text:
        raise _fail()
    return float(text[0].encode("cp1252", errors="replace")[0])


@register("FIXED")
def _fixed(ctx: Evaluator, args: list[Arg]) -> Value:
    x, decimals, no_commas = (
        _num(ctx, args, 0),
        int(_num(ctx, args, 1, 2.0)),
        _bool(ctx, args, 2, False),
    )
    rounded = _round_half_away(x, decimals)
    places = max(decimals, 0)
    return f"{rounded:.{places}f}" if no_commas else f"{rounded:,.{places}f}"


@register("TEXT")
def _text_fn(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 2)
    value, fmt = _arg(ctx, args, 0), _text(ctx, args, 1)
    return format_number(value, fmt)


def format_number(value: Value, fmt: str) -> str:
    """A subset of Excel number formats: General, 0/0.00 with thousands separators,
    percentages, and date/time codes (yyyy, yy, mmmm, mmm, mm, m, dd, d, hh, h, ss, AM/PM)."""
    if isinstance(value, str):
        parsed = parse_number_text(value)
        if parsed is None:
            return value
        value = parsed
    x = to_number(value)
    if fmt.upper() in ("", "GENERAL", "@"):
        return number_to_text(x)
    if re.search(r"[ymdhs]", fmt, re.I) and not re.search(r"[0#]", fmt):
        return _format_date(x, fmt)
    percent = fmt.endswith("%")
    body = fmt.rstrip("%")
    if percent:
        x *= 100
    decimals = len(body.split(".", 1)[1]) if "." in body else 0
    rounded = _round_half_away(x, decimals)
    text = f"{rounded:,.{decimals}f}" if "," in body else f"{rounded:.{decimals}f}"
    prefix = re.match(r"^[^0#,.]*", body)
    lead = prefix.group(0).strip('"') if prefix else ""
    return f"{lead}{text}{'%' if percent else ''}"


def _format_date(serial: float, fmt: str) -> str:
    # A serial below 1 is a time of day ("0.5" is noon); there is no date part to show.
    day = date(1899, 12, 30) if 0 <= serial < 1 else serial_to_date(serial)
    seconds = round((serial - math.floor(serial)) * 86400)
    hour, minute, second = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    ampm = "AM/PM" in fmt.upper()
    tokens = [
        ("yyyy", f"{day.year:04d}"),
        ("yy", f"{day.year % 100:02d}"),
        ("mmmm", day.strftime("%B")),
        ("mmm", day.strftime("%b")),
        ("dddd", day.strftime("%A")),
        ("ddd", day.strftime("%a")),
        ("dd", f"{day.day:02d}"),
        ("d", str(day.day)),
        ("hh", f"{(hour % 12 or 12) if ampm else hour:02d}"),
        ("h", str((hour % 12 or 12) if ampm else hour)),
        ("ss", f"{second:02d}"),
        ("AM/PM", "AM" if hour < 12 else "PM"),
    ]
    out, i = [], 0
    lower = fmt
    while i < len(lower):
        for token, replacement in tokens:
            if lower[i : i + len(token)].lower() == token.lower():
                out.append(replacement)
                i += len(token)
                break
        else:
            if lower[i : i + 2].lower() == "mm" or lower[i].lower() == "m":
                width = 2 if lower[i : i + 2].lower() == "mm" else 1
                previous = "".join(out)
                is_minute = (
                    bool(re.search(r"[h]\D*$", fmt[:i], re.I))
                    or lower[i + width : i + width + 1] == ":"
                )
                value = minute if is_minute and ":" in fmt else day.month
                out.append(f"{value:02d}" if width == 2 else str(value))
                i += width
                del previous
            else:
                out.append(lower[i].strip('"\\'))
                i += 1
    return "".join(out)


# ---------------------------------------------------------------- dates


_MAX_SERIAL = 2_958_465  # 9999-12-31 in the 1900 date system


def _serial(ctx: Evaluator, args: list[Arg], i: int) -> float:
    value = _arg(ctx, args, i)
    if isinstance(value, str):
        parsed = parse_datetime_text(value)
        if parsed is None:
            parsed = parse_number_text(value)
        if parsed is None:
            raise _fail()
        return parsed
    serial = to_number(value)
    if serial < 0:
        raise _fail(CellError.NUM)
    return serial


def _date_arg(ctx: Evaluator, args: list[Arg], i: int) -> date:
    return serial_to_date(math.floor(_serial(ctx, args, i)))


@register("DATE")
def _date(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3, 3)
    year, month, day = int(_num(ctx, args, 0)), int(_num(ctx, args, 1)), int(_num(ctx, args, 2))
    if 0 <= year < 1900:
        year += 1900
    if not 1900 <= year <= 9999:
        raise _fail(CellError.NUM)
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    try:
        start = date(year, month, 1)
    except ValueError as exc:
        raise _fail(CellError.NUM) from exc
    # Serial arithmetic, not date arithmetic: Excel counts the phantom 29 Feb 1900, so
    # DATE(1900,2,29) is 60 and DATE(1900,2,30) is 61 (both would be March here).
    serial = date_to_serial(start) + day - 1
    if not 0 <= serial <= _MAX_SERIAL:
        raise _fail(CellError.NUM)
    return serial


@register("TIME")
def _time(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3, 3)
    total = _num(ctx, args, 0) * 3600 + _num(ctx, args, 1) * 60 + _num(ctx, args, 2)
    if total < 0:
        raise _fail(CellError.NUM)
    return (total % 86400) / 86400


@register("YEAR")
def _year(ctx: Evaluator, args: list[Arg]) -> Value:
    return float(_date_arg(ctx, args, 0).year)


@register("MONTH")
def _month(ctx: Evaluator, args: list[Arg]) -> Value:
    return float(_date_arg(ctx, args, 0).month)


@register("DAY")
def _day(ctx: Evaluator, args: list[Arg]) -> Value:
    return float(_date_arg(ctx, args, 0).day)


def _clock(ctx: Evaluator, args: list[Arg]) -> tuple[int, int, int]:
    seconds = round((_serial(ctx, args, 0) % 1) * 86400) % 86400
    return seconds // 3600, (seconds % 3600) // 60, seconds % 60


@register("HOUR")
def _hour(ctx: Evaluator, args: list[Arg]) -> Value:
    return float(_clock(ctx, args)[0])


@register("MINUTE")
def _minute(ctx: Evaluator, args: list[Arg]) -> Value:
    return float(_clock(ctx, args)[1])


@register("SECOND")
def _second(ctx: Evaluator, args: list[Arg]) -> Value:
    return float(_clock(ctx, args)[2])


@register("TODAY")
def _today(ctx: Evaluator, args: list[Arg]) -> Value:
    return float(math.floor(ctx.host.now_serial()))


@register("NOW")
def _now(ctx: Evaluator, args: list[Arg]) -> Value:
    return ctx.host.now_serial()


@register("DATEVALUE")
def _datevalue(ctx: Evaluator, args: list[Arg]) -> Value:
    parsed = parse_datetime_text(_text(ctx, args, 0))
    if parsed is None:
        raise _fail()
    return float(math.floor(parsed))


def _add_months(start: date, months: int, end_of_month: bool) -> date:
    index = start.year * 12 + start.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, last if end_of_month else min(start.day, last))


@register("EDATE")
def _edate(ctx: Evaluator, args: list[Arg]) -> Value:
    return date_to_serial(_add_months(_date_arg(ctx, args, 0), int(_num(ctx, args, 1)), False))


@register("EOMONTH")
def _eomonth(ctx: Evaluator, args: list[Arg]) -> Value:
    return date_to_serial(_add_months(_date_arg(ctx, args, 0), int(_num(ctx, args, 1)), True))


@register("DAYS")
def _days(ctx: Evaluator, args: list[Arg]) -> Value:
    return float(math.floor(_serial(ctx, args, 0)) - math.floor(_serial(ctx, args, 1)))


@register("WEEKDAY")
def _weekday(ctx: Evaluator, args: list[Arg]) -> Value:
    day = _date_arg(ctx, args, 0)
    kind = int(_num(ctx, args, 1, 1.0))
    sunday_based = (day.isoweekday() % 7) + 1  # Sunday 1 .. Saturday 7
    if kind == 1:
        return float(sunday_based)
    if kind == 2:
        return float(day.isoweekday())
    if kind == 3:
        return float(day.isoweekday() - 1)
    raise _fail(CellError.NUM)


@register("DATEDIF")
def _datedif(ctx: Evaluator, args: list[Arg]) -> Value:
    start, end, unit = _date_arg(ctx, args, 0), _date_arg(ctx, args, 1), _text(ctx, args, 2).upper()
    if end < start:
        raise _fail(CellError.NUM)
    months = (
        (end.year - start.year) * 12 + end.month - start.month - (1 if end.day < start.day else 0)
    )
    if unit == "D":
        return float((end - start).days)
    if unit == "M":
        return float(months)
    if unit == "Y":
        return float(months // 12)
    if unit == "YM":
        return float(months % 12)
    if unit == "MD":
        anchor = _add_months(start, months, False)
        return float((end - anchor).days)
    if unit == "YD":
        anchor = _add_months(start, (months // 12) * 12, False)
        return float((end - anchor).days)
    raise _fail(CellError.NUM)


def _holidays(args: list[Arg], i: int) -> set[date]:
    if i >= len(args):
        return set()
    out = set()
    for value in _values(args[i].value):
        if isinstance(value, float | int) and not isinstance(value, bool):
            out.add(serial_to_date(float(value)))
    return out


@register("NETWORKDAYS")
def _networkdays(ctx: Evaluator, args: list[Arg]) -> Value:
    start, end = _date_arg(ctx, args, 0), _date_arg(ctx, args, 1)
    holidays = _holidays(args, 2)
    sign = 1
    if end < start:
        start, end, sign = end, start, -1
    total, day = 0, start
    while day <= end:
        if day.weekday() < 5 and day not in holidays:
            total += 1
        day += timedelta(days=1)
    return float(sign * total)


@register("WORKDAY")
def _workday(ctx: Evaluator, args: list[Arg]) -> Value:
    day, count = _date_arg(ctx, args, 0), int(_num(ctx, args, 1))
    holidays = _holidays(args, 2)
    step = 1 if count >= 0 else -1
    remaining = abs(count)
    while remaining:
        day += timedelta(days=step)
        if day.weekday() < 5 and day not in holidays:
            remaining -= 1
    return date_to_serial(day)


def _days360(start: date, end: date, european: bool) -> int:
    d1, d2 = start.day, end.day
    if european:
        d1, d2 = min(d1, 30), min(d2, 30)
    else:
        last_feb = (start + timedelta(days=1)).month != start.month and start.month == 2
        if last_feb:
            d1 = 30
        if d1 == 31:
            d1 = 30
        if d2 == 31 and d1 >= 30:
            d2 = 30
    return (end.year - start.year) * 360 + (end.month - start.month) * 30 + (d2 - d1)


@register("DAYS360")
def _days360_fn(ctx: Evaluator, args: list[Arg]) -> Value:
    return float(
        _days360(_date_arg(ctx, args, 0), _date_arg(ctx, args, 1), _bool(ctx, args, 2, False))
    )


@register("YEARFRAC")
def _yearfrac(ctx: Evaluator, args: list[Arg]) -> Value:
    start, end = _date_arg(ctx, args, 0), _date_arg(ctx, args, 1)
    basis = int(_num(ctx, args, 2, 0.0))
    if end < start:
        start, end = end, start
    days = (end - start).days
    if basis == 0:
        return _days360(start, end, False) / 360
    if basis == 1:
        years = range(start.year, end.year + 1)
        avg = sum(366 if _leap(y) else 365 for y in years) / len(years)
        return days / avg
    if basis == 2:
        return days / 360
    if basis == 3:
        return days / 365
    if basis == 4:
        return _days360(start, end, True) / 360
    raise _fail(CellError.NUM)


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


# ---------------------------------------------------------------- lookup


def _lookup_equal(a: Value, b: Value) -> bool:
    if isinstance(b, str) and isinstance(a, str) and any(ch in b for ch in "*?"):
        return _wildcard(b).fullmatch(a) is not None
    return compare(a, b) == 0 and _kind_match(a, b)


def _approximate(values: list[Value], target: Value) -> int | None:
    """Last position whose value is <= target among same-kind values (binary-search result
    on sorted data)."""
    found = None
    for index, value in enumerate(values):
        if value is None or not _kind_match(value, target):
            continue
        if compare(value, target) <= 0:
            found = index
        else:
            break
    return found


def _table_lookup(ctx: Evaluator, args: list[Arg], vertical: bool) -> Value:
    _count(args, 3, 4)
    target = _arg(ctx, args, 0)
    table = _array(args[1])
    index = int(_num(ctx, args, 2))
    approximate = _bool(ctx, args, 3, True)
    keys = table.col_values(0) if vertical else table.row_values(0)
    limit = table.cols if vertical else table.rows
    if not 1 <= index <= limit:
        raise _fail(CellError.REF if index > limit else CellError.VALUE)
    if approximate:
        position = _approximate(keys, target)
    else:
        position = next((i for i, v in enumerate(keys) if _lookup_equal(v, target)), None)
    if position is None:
        raise _fail(CellError.NA)
    result = table.get(position, index - 1) if vertical else table.get(index - 1, position)
    return 0.0 if result is None else result


register("VLOOKUP")(lambda ctx, args: _table_lookup(ctx, args, True))
register("HLOOKUP")(lambda ctx, args: _table_lookup(ctx, args, False))


def _vector(arg: Arg) -> list[Value]:
    array = _array(arg)
    if array.rows != 1 and array.cols != 1:
        raise _fail(CellError.NA)
    return list(array.data)


@register("MATCH")
def _match(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 3)
    target = _arg(ctx, args, 0)
    values = _vector(args[1])
    kind = int(_num(ctx, args, 2, 1.0))
    if kind == 0:
        position = next((i for i, v in enumerate(values) if _lookup_equal(v, target)), None)
    elif kind > 0:
        position = _approximate(values, target)
    else:
        position = None
        for i, value in enumerate(values):
            if value is None or not _kind_match(value, target):
                continue
            if compare(value, target) >= 0:
                position = i
            else:
                break
    if position is None:
        raise _fail(CellError.NA)
    return float(position + 1)


@register("XLOOKUP")
def _xlookup(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3, 6)
    target = _arg(ctx, args, 0)
    keys = _vector(args[1])
    results = _array(args[2])
    match_mode = int(_num(ctx, args, 4, 0.0))
    search_mode = int(_num(ctx, args, 5, 1.0))
    order = list(range(len(keys)))
    if search_mode < 0:
        order.reverse()
    position = None
    if match_mode in (0, 2):
        for i in order:
            hit = (
                _lookup_equal(keys[i], target)
                if match_mode == 2
                else (compare(keys[i], target) == 0 and _kind_match(keys[i], target))
            )
            if hit:
                position = i
                break
    elif match_mode in (-1, 1):
        best: int | None = None
        for i in order:
            key = keys[i]
            if key is None or not _kind_match(key, target):
                continue
            order_cmp = compare(key, target)
            if order_cmp == 0:
                best = i
                break
            if (
                match_mode == -1
                and order_cmp < 0
                and (best is None or compare(key, keys[best]) > 0)
            ) or (
                match_mode == 1 and order_cmp > 0 and (best is None or compare(key, keys[best]) < 0)
            ):
                best = i
        position = best
    else:
        raise _fail()
    if position is None:
        if len(args) > 3 and not (args[3].value is None and not args[3].from_ref):
            return args[3].value
        raise _fail(CellError.NA)
    if results.cols == len(keys) and results.rows >= 1 and (results.rows == 1 or results.cols != 1):
        column = results.col_values(position) if results.rows > 1 else [results.get(0, position)]
        return column[0] if len(column) == 1 else Array.of([[v] for v in column])
    row = results.row_values(position)
    return row[0] if len(row) == 1 else Array.of([row])


@register("INDEX")
def _index(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 3)
    array = _array(args[0])
    row = int(_num(ctx, args, 1))
    col = int(_num(ctx, args, 2, 0.0))
    if array.rows == 1 and len(args) == 2:
        row, col = 1, row
    if row < 0 or col < 0 or row > array.rows or col > array.cols:
        raise _fail(CellError.REF)
    if row == 0 and col == 0:
        return array
    if row == 0:
        return Array.of([[v] for v in array.col_values(col - 1)])
    if col == 0:
        if array.cols == 1:
            col = 1
        else:
            return Array.of([array.row_values(row - 1)])
    value = array.get(row - 1, col - 1)
    return 0.0 if value is None else value


@register("ROW")
def _row(ctx: Evaluator, args: list[Arg]) -> Value:
    if not args:
        return float(ctx.row + 1)
    if not args[0].areas:
        raise _fail()
    return float(args[0].areas[0].r0 + 1)


@register("COLUMN")
def _column(ctx: Evaluator, args: list[Arg]) -> Value:
    if not args:
        return float(ctx.col + 1)
    if not args[0].areas:
        raise _fail()
    return float(args[0].areas[0].c0 + 1)


@register("ROWS")
def _rows(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 1, 1)
    if args[0].areas:
        return float(args[0].areas[0].height)
    return float(_array(args[0]).rows)


@register("COLUMNS")
def _columns(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 1, 1)
    if args[0].areas:
        return float(args[0].areas[0].width)
    return float(_array(args[0]).cols)


# ---------------------------------------------------------------- financial
# Sign convention follows Excel: money paid out is negative, money received is positive.


def _pmt(rate: float, nper: float, pv: float, fv: float, typ: float) -> float:
    if rate == 0:
        return -(pv + fv) / nper
    p = float((1 + rate) ** nper)
    return -(rate * (fv + pv * p)) / ((1 + rate * typ) * (p - 1))


def _fv(rate: float, nper: float, pmt: float, pv: float, typ: float) -> float:
    if rate == 0:
        return -(pv + pmt * nper)
    p = float((1 + rate) ** nper)
    return -(pv * p + pmt * (1 + rate * typ) * (p - 1) / rate)


def _pv(rate: float, nper: float, pmt: float, fv: float, typ: float) -> float:
    if rate == 0:
        return -(fv + pmt * nper)
    p = float((1 + rate) ** nper)
    return -(fv + pmt * (1 + rate * typ) * (p - 1) / rate) / p


def _type(ctx: Evaluator, args: list[Arg], i: int) -> float:
    return 1.0 if _num(ctx, args, i, 0.0) != 0 else 0.0


@register("PMT")
def _pmt_fn(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3, 5)
    rate, nper, pv = _num(ctx, args, 0), _num(ctx, args, 1), _num(ctx, args, 2)
    if nper == 0:
        raise _fail(CellError.NUM)
    return _check(_pmt(rate, nper, pv, _num(ctx, args, 3, 0.0), _type(ctx, args, 4)))


@register("FV")
def _fv_fn(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3, 5)
    return _check(
        _fv(
            _num(ctx, args, 0),
            _num(ctx, args, 1),
            _num(ctx, args, 2),
            _num(ctx, args, 3, 0.0),
            _type(ctx, args, 4),
        )
    )


@register("PV")
def _pv_fn(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3, 5)
    return _check(
        _pv(
            _num(ctx, args, 0),
            _num(ctx, args, 1),
            _num(ctx, args, 2),
            _num(ctx, args, 3, 0.0),
            _type(ctx, args, 4),
        )
    )


@register("NPER")
def _nper(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3, 5)
    rate, pmt, pv = _num(ctx, args, 0), _num(ctx, args, 1), _num(ctx, args, 2)
    fv, typ = _num(ctx, args, 3, 0.0), _type(ctx, args, 4)
    if rate == 0:
        if pmt == 0:
            raise _fail(CellError.NUM)
        return _check(-(pv + fv) / pmt)
    numerator = pmt * (1 + rate * typ) - fv * rate
    denominator = pv * rate + pmt * (1 + rate * typ)
    if denominator == 0:
        raise _fail(CellError.NUM)
    q = numerator / denominator
    if q <= 0 or rate <= -1:
        raise _fail(CellError.NUM)
    return _check(math.log(q) / math.log(1 + rate))


def _ipmt(rate: float, per: float, nper: float, pv: float, fv: float, typ: float) -> float:
    payment = _pmt(rate, nper, pv, fv, typ)
    if typ == 1 and per == 1:
        return 0.0
    interest = _fv(rate, per - 1, payment, pv, typ) * rate
    return interest / (1 + rate) if typ == 1 else interest


@register("IPMT")
def _ipmt_fn(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 4, 6)
    rate, per, nper, pv = (_num(ctx, args, i) for i in range(4))
    if per < 1 or per > nper or nper == 0:
        raise _fail(CellError.NUM)
    return _check(_ipmt(rate, per, nper, pv, _num(ctx, args, 4, 0.0), _type(ctx, args, 5)))


@register("PPMT")
def _ppmt_fn(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 4, 6)
    rate, per, nper, pv = (_num(ctx, args, i) for i in range(4))
    fv, typ = _num(ctx, args, 4, 0.0), _type(ctx, args, 5)
    if per < 1 or per > nper or nper == 0:
        raise _fail(CellError.NUM)
    return _check(_pmt(rate, nper, pv, fv, typ) - _ipmt(rate, per, nper, pv, fv, typ))


def _cumulative(ctx: Evaluator, args: list[Arg], principal: bool) -> Value:
    _count(args, 6, 6)
    rate, nper, pv = _num(ctx, args, 0), math.trunc(_num(ctx, args, 1)), _num(ctx, args, 2)
    start, end, typ = (
        math.trunc(_num(ctx, args, 3)),
        math.trunc(_num(ctx, args, 4)),
        _num(ctx, args, 5),
    )
    if (
        rate <= 0
        or nper <= 0
        or pv <= 0
        or start < 1
        or end < start
        or end > nper
        or typ not in (0, 1)
    ):
        raise _fail(CellError.NUM)
    payment = _pmt(rate, nper, pv, 0.0, typ)
    total = 0.0
    for per in range(int(start), int(end) + 1):
        interest = _ipmt(rate, per, nper, pv, 0.0, typ)
        total += payment - interest if principal else interest
    return _check(total)


register("CUMIPMT")(lambda ctx, args: _cumulative(ctx, args, False))
register("CUMPRINC")(lambda ctx, args: _cumulative(ctx, args, True))


def _newton(f: Callable[[float], float], guess: float) -> float | None:
    x = guess
    for _ in range(200):
        y = f(x)
        if not math.isfinite(y):
            return None
        h = 1e-6 * max(abs(x), 1e-3)
        d = (f(x + h) - f(x - h)) / (2 * h)
        if d == 0 or not math.isfinite(d):
            return None
        nx = x - y / d
        if nx <= -1:
            nx = (x - 1) / 2
            if nx <= -1:
                nx = -0.999_999_999
        if abs(nx - x) < 1e-12 * max(abs(nx), 1.0):
            return nx
        x = nx
    return None


def _solve_rate(f: Callable[[float], float], guess: float) -> float:
    """Newton from the guess and fallback starting points, then bisection over a bracket."""

    def safe(r: float) -> float:
        try:
            return f(r)
        except (OverflowError, ZeroDivisionError, ValueError):
            return math.nan

    scale = 1 + min(abs(safe(guess)) if math.isfinite(safe(guess)) else 1e12, 1e12)
    for start in (guess, 0.1, 0.01, 0.5, -0.5, 1.0, 0.001, 5.0, -0.9, 10.0):
        root = _newton(safe, start)
        if (
            root is not None
            and root > -1
            and math.isfinite(safe(root))
            and abs(safe(root)) < 1e-7 * scale
        ):
            return root
    grid = [
        -0.999999,
        -0.99,
        -0.9,
        -0.5,
        -0.2,
        0.0,
        0.05,
        0.1,
        0.2,
        0.5,
        1.0,
        2.0,
        5.0,
        10.0,
        100.0,
        1000.0,
    ]
    for lo, hi in itertools.pairwise(grid):
        flo, fhi = safe(lo), safe(hi)
        if not (math.isfinite(flo) and math.isfinite(fhi)) or flo * fhi > 0:
            continue
        lo_negative = flo < 0
        for _ in range(200):
            mid = (lo + hi) / 2
            if (safe(mid) < 0) == lo_negative:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    raise _fail(CellError.NUM)


@register("RATE")
def _rate(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3, 6)
    nper, pmt, pv = _num(ctx, args, 0), _num(ctx, args, 1), _num(ctx, args, 2)
    fv, typ, guess = _num(ctx, args, 3, 0.0), _type(ctx, args, 4), _num(ctx, args, 5, 0.1)
    if nper <= 0:
        raise _fail(CellError.NUM)

    def f(r: float) -> float:
        if abs(r) < 1e-12:
            return pv + pmt * nper + fv
        p = float((1 + r) ** nper)
        return pv * p + pmt * (1 + r * typ) * (p - 1) / r + fv

    return _check(_solve_rate(f, guess))


@register("NPV")
def _npv(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2)
    rate = _num(ctx, args, 0)
    if rate == -1:
        raise _fail(CellError.DIV0)
    total, discount = 0.0, 1.0
    for value in _numbers(args[1:]):
        discount *= 1 + rate
        total += value / discount
    return _check(total)


def _flows(arg: Arg) -> list[float]:
    out = []
    for value in _values(arg.value):
        if isinstance(value, CellError):
            raise FormulaError(value)
        if isinstance(value, float | int) and not isinstance(value, bool):
            out.append(float(value))
    return out


@register("IRR")
def _irr(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 1, 2)
    flows, guess = _flows(args[0]), _num(ctx, args, 1, 0.1)
    if not any(v > 0 for v in flows) or not any(v < 0 for v in flows):
        raise _fail(CellError.NUM)

    def f(r: float) -> float:
        return sum(v / (1 + r) ** i for i, v in enumerate(flows))

    return _check(_solve_rate(f, guess))


def _dated_flows(values: Arg, dates: Arg) -> tuple[list[float], list[float]]:
    v_raw, d_raw = _values(values.value), _values(dates.value)
    if len(v_raw) != len(d_raw):
        raise _fail(CellError.NUM)
    flows, days = [], []
    for v, d in zip(v_raw, d_raw, strict=True):
        if isinstance(v, CellError):
            raise FormulaError(v)
        if isinstance(d, CellError):
            raise FormulaError(d)
        if isinstance(v, bool) or not isinstance(v, float | int):
            raise _fail()
        flows.append(float(v))
        days.append(float(math.trunc(to_number(d))))
    if not days or any(day < days[0] or day < 0 for day in days):
        raise _fail(CellError.NUM)
    return flows, days


def _xnpv_calc(rate: float, flows: list[float], days: list[float]) -> float:
    return float(
        sum(v / (1 + rate) ** ((d - days[0]) / 365) for v, d in zip(flows, days, strict=True))
    )


@register("XNPV")
def _xnpv(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3, 3)
    rate = _num(ctx, args, 0)
    if rate <= -1:
        raise _fail(CellError.NUM)
    flows, days = _dated_flows(args[1], args[2])
    return _check(_xnpv_calc(rate, flows, days))


@register("XIRR")
def _xirr(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 3)
    flows, days = _dated_flows(args[0], args[1])
    if not any(v > 0 for v in flows) or not any(v < 0 for v in flows):
        raise _fail(CellError.NUM)
    return _check(_solve_rate(lambda r: _xnpv_calc(r, flows, days), _num(ctx, args, 2, 0.1)))


@register("MIRR")
def _mirr(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 3, 3)
    flows = _flows(args[0])
    finance, reinvest = _num(ctx, args, 1), _num(ctx, args, 2)
    if len(flows) < 2:
        raise _fail(CellError.DIV0)
    n = len(flows)
    positive = sum(v / (1 + reinvest) ** i for i, v in enumerate(flows) if v > 0)
    negative = sum(v / (1 + finance) ** i for i, v in enumerate(flows) if v < 0)
    if negative == 0:
        raise _fail(CellError.DIV0)
    return _check((-positive * (1 + reinvest) ** (n - 1) / negative) ** (1 / (n - 1)) - 1)


@register("FVSCHEDULE")
def _fvschedule(ctx: Evaluator, args: list[Arg]) -> Value:
    _count(args, 2, 2)
    principal = _num(ctx, args, 0)
    for value in _values(args[1].value):
        if isinstance(value, CellError):
            raise FormulaError(value)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, float | int):
            raise _fail()
        principal *= 1 + float(value)
    return _check(principal)


@register("EFFECT")
def _effect(ctx: Evaluator, args: list[Arg]) -> Value:
    nominal, periods = _num(ctx, args, 0), math.trunc(_num(ctx, args, 1))
    if nominal <= 0 or periods < 1:
        raise _fail(CellError.NUM)
    return _check((1 + nominal / periods) ** periods - 1)


@register("NOMINAL")
def _nominal(ctx: Evaluator, args: list[Arg]) -> Value:
    effective, periods = _num(ctx, args, 0), math.trunc(_num(ctx, args, 1))
    if effective <= 0 or periods < 1:
        raise _fail(CellError.NUM)
    return _check(periods * ((1 + effective) ** (1 / periods) - 1))


@register("PDURATION")
def _pduration(ctx: Evaluator, args: list[Arg]) -> Value:
    rate, pv, fv = _num(ctx, args, 0), _num(ctx, args, 1), _num(ctx, args, 2)
    if rate <= 0 or pv <= 0 or fv <= 0:
        raise _fail(CellError.NUM)
    return _check((math.log(fv) - math.log(pv)) / math.log(1 + rate))


@register("RRI")
def _rri(ctx: Evaluator, args: list[Arg]) -> Value:
    nper, pv, fv = _num(ctx, args, 0), _num(ctx, args, 1), _num(ctx, args, 2)
    if nper <= 0 or pv == 0:
        raise _fail(CellError.NUM)
    return _check((fv / pv) ** (1 / nper) - 1)


@register("SLN")
def _sln(ctx: Evaluator, args: list[Arg]) -> Value:
    cost, salvage, life = _num(ctx, args, 0), _num(ctx, args, 1), _num(ctx, args, 2)
    if life == 0:
        raise _fail(CellError.DIV0)
    return _check((cost - salvage) / life)


@register("SYD")
def _syd(ctx: Evaluator, args: list[Arg]) -> Value:
    cost, salvage, life, per = (_num(ctx, args, i) for i in range(4))
    if life <= 0 or per <= 0 or per > life:
        raise _fail(CellError.NUM)
    return _check((cost - salvage) * (life - per + 1) * 2 / (life * (life + 1)))


@register("DDB")
def _ddb(ctx: Evaluator, args: list[Arg]) -> Value:
    cost, salvage, life, period = (_num(ctx, args, i) for i in range(4))
    factor = _num(ctx, args, 4, 2.0)
    if cost < 0 or salvage < 0 or life <= 0 or period <= 0 or period > life or factor <= 0:
        raise _fail(CellError.NUM)
    book, depreciation = cost, 0.0
    for _ in range(math.ceil(period)):
        depreciation = min(book * factor / life, max(book - salvage, 0.0))
        book -= depreciation
    return _check(depreciation)


@register("DB")
def _db(ctx: Evaluator, args: list[Arg]) -> Value:
    cost, salvage, life, period = (_num(ctx, args, i) for i in range(4))
    month = _num(ctx, args, 4, 12.0)
    if (
        cost < 0
        or salvage < 0
        or life <= 0
        or period <= 0
        or not 1 <= month <= 12
        or period > life + 1
    ):
        raise _fail(CellError.NUM)
    rate = 0.0 if cost == 0 else round(1 - (salvage / cost) ** (1 / life), 3)
    total, depreciation = 0.0, cost * rate * month / 12
    if period == 1:
        return _check(depreciation)
    total = depreciation
    for current in range(2, int(period) + 1):
        if current == int(life) + 1:
            depreciation = (cost - total) * rate * (12 - month) / 12
        else:
            depreciation = (cost - total) * rate
        total += depreciation
    return _check(depreciation)
