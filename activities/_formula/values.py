"""Cell values and Excel's coercion and comparison rules.

Ported from GridCraft (CraftApps, MIT OR Apache-2.0): ``gridcraft-core/src/value.rs`` and
``parse.rs``. A value is ``None`` (empty), ``float``, ``str``, ``bool``, ``CellError`` or
``Array``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Any, Union


class CellError(Enum):
    NULL = "#NULL!"
    DIV0 = "#DIV/0!"
    VALUE = "#VALUE!"
    REF = "#REF!"
    NAME = "#NAME?"
    NUM = "#NUM!"
    NA = "#N/A"
    GETTING_DATA = "#GETTING_DATA"
    SPILL = "#SPILL!"
    CALC = "#CALC!"
    CIRC = "#CIRC!"

    @property
    def code(self) -> int:
        """``ERROR.TYPE`` number."""
        return _ERROR_CODES[self]

    @classmethod
    def parse(cls, text: str) -> CellError | None:
        upper = text.strip().upper()
        return next((error for error in cls if error.value == upper), None)

    def __str__(self) -> str:
        return self.value


_ERROR_CODES = {
    CellError.NULL: 1,
    CellError.DIV0: 2,
    CellError.VALUE: 3,
    CellError.REF: 4,
    CellError.NAME: 5,
    CellError.NUM: 6,
    CellError.NA: 7,
    CellError.GETTING_DATA: 8,
    CellError.SPILL: 9,
    CellError.CALC: 14,
    CellError.CIRC: 15,
}


@dataclass(frozen=True)
class Array:
    """A 2-D array of values, row-major, always at least 1x1."""

    rows: int
    cols: int
    data: tuple[Value, ...] = field(default_factory=tuple)

    @classmethod
    def of(cls, rows: list[list[Value]]) -> Array:
        if not rows or not rows[0]:
            return cls(1, 1, (CellError.CALC,))
        width = len(rows[0])
        return cls(len(rows), width, tuple(v for row in rows for v in row))

    def get(self, r: int, c: int) -> Value:
        if 0 <= r < self.rows and 0 <= c < self.cols:
            return self.data[r * self.cols + c]
        return CellError.NA

    def broadcast(self, r: int, c: int) -> Value:
        """A 1-row or 1-column array repeats along that axis; outside it is #N/A."""
        return self.get(0 if self.rows == 1 else r, 0 if self.cols == 1 else c)

    def row_values(self, r: int) -> list[Value]:
        return list(self.data[r * self.cols : (r + 1) * self.cols])

    def col_values(self, c: int) -> list[Value]:
        return [self.data[r * self.cols + c] for r in range(self.rows)]

    def to_rows(self) -> list[list[Value]]:
        return [self.row_values(r) for r in range(self.rows)]


Value = Union[None, float, str, bool, CellError, Array]  # noqa: UP007 - recursive alias


class FormulaError(Exception):
    """Raised inside function code to return an error value."""

    def __init__(self, error: CellError) -> None:
        super().__init__(error.value)
        self.error = error


def number(value: float) -> Value:
    """A number, or #NUM! when it is NaN or infinite (Excel never stores those)."""
    if math.isnan(value) or math.isinf(value):
        return CellError.NUM
    return 0.0 if value == 0 else float(value)


def scalar(value: Value) -> Value:
    """Top-left element of an array, the value itself otherwise."""
    if isinstance(value, Array):
        return value.data[0] if value.data else None
    return value


def to_number(value: Value) -> float:
    """Coercion as arithmetic does it: empty 0, TRUE 1, numeric text parses (dates, times,
    percentages, currency), other text #VALUE!. Raises ``FormulaError``."""
    value = scalar(value)
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, float | int):
        return float(value)
    if isinstance(value, str):
        parsed = parse_number_text(value)
        if parsed is None:
            raise FormulaError(CellError.VALUE)
        return parsed
    if isinstance(value, CellError):
        raise FormulaError(value)
    return 0.0


def to_text(value: Value) -> str:
    """Coercion to text as ``&`` does it."""
    value = scalar(value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float | int):
        return number_to_text(float(value))
    if isinstance(value, CellError):
        raise FormulaError(value)
    return str(value)


def to_bool(value: Value) -> bool:
    """Coercion to a boolean as ``IF`` does it."""
    value = scalar(value)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, float | int):
        return value != 0
    if isinstance(value, str):
        if value.upper() == "TRUE":
            return True
        if value.upper() == "FALSE":
            return False
        raise FormulaError(CellError.VALUE)
    if isinstance(value, CellError):
        raise FormulaError(value)
    return False


def display(value: Value) -> str:
    if isinstance(value, CellError):
        return value.value
    try:
        return to_text(value)
    except FormulaError:
        return ""


def _rank(value: Value) -> int:
    if isinstance(value, bool):
        return 2
    if isinstance(value, float | int):
        return 0
    if isinstance(value, str):
        return 1
    if isinstance(value, CellError):
        return 3
    if value is None:
        return 4
    return 5


def compare(a: Value, b: Value) -> int:
    """Excel's comparison for ``=``, ``<``...: -1, 0 or 1. Text compares case-insensitively;
    empty acts as 0, "" or FALSE depending on the other side; numbers at 15 significant
    digits; otherwise numbers < text < booleans < errors."""
    if a is None and b is None:
        return 0
    if a is None:
        a = _empty_like(b)
    elif b is None:
        b = _empty_like(a)
    if isinstance(a, bool) and isinstance(b, bool):
        return (a > b) - (a < b)
    a_num = isinstance(a, float | int) and not isinstance(a, bool)
    b_num = isinstance(b, float | int) and not isinstance(b, bool)
    if a_num and b_num:
        return compare_numbers(float(a), float(b))  # type: ignore[arg-type]
    if isinstance(a, str) and isinstance(b, str):
        x, y = a.lower(), b.lower()
        return (x > y) - (x < y)
    if isinstance(a, CellError) and isinstance(b, CellError):
        return (a.code > b.code) - (a.code < b.code)
    ra, rb = _rank(a), _rank(b)
    return (ra > rb) - (ra < rb)


def _empty_like(other: Value) -> Value:
    if isinstance(other, bool):
        return False
    if isinstance(other, str):
        return ""
    return 0.0


def compare_numbers(a: float, b: float) -> int:
    """Both rounded to 15 significant digits first, so 0.1+0.2 equals 0.3."""
    if a == b:
        return 0
    if abs(a - b) > max(abs(a), abs(b)) * 1e-13:
        return -1 if a < b else 1
    ra, rb = float(f"{a:.14e}"), float(f"{b:.14e}")
    return (ra > rb) - (ra < rb)


def number_to_text(n: float) -> str:
    """Up to 15 significant digits, scientific for very large or very small magnitudes."""
    if n == 0 or not math.isfinite(n):
        return "0"
    a = abs(n)
    if (not (1e-9 <= a < 1e15) and round(a) != a) or a >= 1e15:
        return _sci_text(n, 15)
    magnitude = math.floor(math.log10(a))
    decimals = min(max(14 - magnitude, 0), 30)
    return _trim_decimal(f"{n:.{decimals}f}")


def _trim_decimal(text: str) -> str:
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _sci_text(n: float, sig: int) -> str:
    mantissa, _, exponent = f"{n:.{sig - 1}e}".partition("e")
    e = int(exponent)
    return f"{_trim_decimal(mantissa)}E{'-' if e < 0 else '+'}{abs(e):02d}"


# ---------------------------------------------------------------- numeric text and dates

_PLAIN = re.compile(r"^\d+(\.\d*)?([eE][-+]?\d+)?$|^\.\d+([eE][-+]?\d+)?$")
_EPOCH = date(1899, 12, 30)


def parse_number_text(text: str) -> float | None:
    """Text that Excel reads as a number: signs, currency, thousands separators, percent,
    exponent, parenthesised negatives, ISO and common dates and times."""
    t = text.strip()
    if not t:
        return None
    if t.startswith("(") and t.endswith(")"):
        inner = parse_number_text(t[1:-1])
        return None if inner is None else -inner
    plain = _parse_plain(t)
    if plain is not None:
        return plain
    return parse_datetime_text(t)


def _parse_plain(t: str) -> float | None:
    s, negative, percent = t, False, False
    if s.startswith("-"):
        negative, s = True, s[1:].lstrip()
    elif s.startswith("+"):
        s = s[1:].lstrip()
    if s[:1] in "$£€":
        s = s[1:].lstrip()
        if not negative and s.startswith("-"):
            negative, s = True, s[1:]
    if s.endswith("%"):
        percent, s = True, s[:-1].rstrip()
    if not s:
        return None
    if "," in s:
        whole, dot, fraction = s.partition(".")
        groups = whole.split(",")
        if not groups[0] or len(groups[0]) > 3 or any(len(g) != 3 for g in groups[1:]):
            return None
        s = "".join(groups) + (dot + fraction if dot else "")
    if not _PLAIN.match(s):
        return None
    value = float(s)
    if percent:
        value /= 100
    return -value if negative else value


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%d-%b-%Y",
    "%d-%b-%y",
)
_TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p")


def parse_datetime_text(text: str) -> float | None:
    t = " ".join(text.replace(",", " ").split())
    date_part, time_part = t, ""
    for sep in ("T", " "):
        head, _, tail = t.rpartition(sep)
        if head and any(_try(tail, f) for f in _TIME_FORMATS):
            date_part, time_part = head, tail
            break
    if not time_part and any(_try(t, f) for f in _TIME_FORMATS):
        return _time_fraction(next(r for f in _TIME_FORMATS if (r := _try(t, f))))
    for fmt in _DATE_FORMATS:
        parsed = _try(date_part, fmt)
        if parsed is not None:
            serial = date_to_serial(parsed.date())
            if time_part:
                clock = next(r for f in _TIME_FORMATS if (r := _try(time_part, f)))
                serial += _time_fraction(clock)
            return serial
    return None


def _try(text: str, fmt: str) -> datetime | None:
    try:
        return datetime.strptime(text, fmt)
    except ValueError:
        return None


def _time_fraction(moment: datetime) -> float:
    return (moment.hour * 3600 + moment.minute * 60 + moment.second) / 86400


def date_to_serial(day: date) -> float:
    """1900 date system serial (with Excel's phantom 29 Feb 1900 below 61)."""
    serial = float((day - _EPOCH).days)
    return serial if serial >= 61 else serial - 1


def serial_to_date(serial: float) -> date:
    whole = math.floor(serial)
    if whole < 1:
        raise FormulaError(CellError.NUM)
    if whole < 61:
        whole += 1
    from datetime import timedelta

    return _EPOCH + timedelta(days=whole)


def python_value(value: Any) -> Value:
    """A value read from openpyxl as a formula value."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, datetime):
        return date_to_serial(value.date()) + _time_fraction(value)
    if isinstance(value, date):
        return date_to_serial(value)
    if isinstance(value, time):
        return (value.hour * 3600 + value.minute * 60 + value.second) / 86400
    text = str(value)
    error = CellError.parse(text) if text.startswith("#") else None
    return error if error is not None else text
