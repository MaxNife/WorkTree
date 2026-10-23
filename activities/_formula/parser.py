"""Formula lexer and Pratt parser.

Ported from GridCraft (CraftApps, MIT OR Apache-2.0): ``gridcraft-formula/src/lexer.rs``,
``parser.rs`` and ``ast.rs``, with the same operator binding powers (range 90, intersection 85,
union 80, percent 70, prefix sign 60, ^ 50, * / 40, + - 30, & 20, comparisons 10), so ``-2^2``
is 4 as in Excel. Structured references, trim references, spills and LAMBDA are not ported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from activities._formula.values import CellError

MAX_ROWS = 1_048_576
MAX_COLS = 16_384
MAX_DEPTH = 256


class ParseError(ValueError):
    pass


# ---------------------------------------------------------------- AST


@dataclass(frozen=True)
class Num:
    value: float


@dataclass(frozen=True)
class Text:
    value: str


@dataclass(frozen=True)
class Bool:
    value: bool


@dataclass(frozen=True)
class Err:
    error: CellError


@dataclass(frozen=True)
class Missing:
    """An omitted argument, as in ``IF(A1,,2)``."""


@dataclass(frozen=True)
class Ref:
    """A cell or rectangular range, 0-based and inclusive. Whole columns/rows use the sheet
    limits. ``sheet`` is None for the formula's own sheet."""

    sheet: str | None
    r0: int
    c0: int
    r1: int
    c1: int


@dataclass(frozen=True)
class Name:
    name: str


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple[Expr, ...]


@dataclass(frozen=True)
class Unary:
    op: str  # "-", "+", "%", "@"
    operand: Expr


@dataclass(frozen=True)
class Binary:
    op: str  # + - * / ^ & = <> < > <= >= : , " "
    left: Expr
    right: Expr


@dataclass(frozen=True)
class ArrayLit:
    rows: tuple[tuple[Expr, ...], ...]


Expr = Num | Text | Bool | Err | Missing | Ref | Name | Call | Unary | Binary | ArrayLit

PRECEDENCE = {
    ":": 90,
    " ": 85,
    ",": 80,
    "^": 50,
    "*": 40,
    "/": 40,
    "+": 30,
    "-": 30,
    "&": 20,
    "=": 10,
    "<>": 10,
    "<": 10,
    ">": 10,
    "<=": 10,
    ">=": 10,
}

# ---------------------------------------------------------------- lexer


@dataclass(frozen=True)
class Token:
    kind: str  # num text bool error word func sheet op ( ) { } , ; : space eof
    value: object
    pos: int


_CELL = re.compile(r"^\$?([A-Za-z]{1,3})\$?([1-9][0-9]{0,6})$")
_COL = re.compile(r"^\$?([A-Za-z]{1,3})$")
_ROW = re.compile(r"^\$?([1-9][0-9]{0,6})$")
_WORD_CHARS = re.compile(r"[A-Za-z0-9_.$\\?À-￿]")


def tokenize(src: str) -> list[Token]:
    out: list[Token] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in " \t\r\n":
            j = i
            while j < n and src[j] in " \t\r\n":
                j += 1
            out.append(Token("space", None, i))
            i = j
        elif c == '"':
            j, chars = i + 1, []
            while True:
                if j >= n:
                    raise ParseError(f"unterminated text at {i}")
                if src[j] == '"':
                    if j + 1 < n and src[j + 1] == '"':
                        chars.append('"')
                        j += 2
                        continue
                    break
                chars.append(src[j])
                j += 1
            out.append(Token("text", "".join(chars), i))
            i = j + 1
        elif c == "'":
            j, chars = i + 1, []
            while True:
                if j >= n:
                    raise ParseError(f"unterminated sheet name at {i}")
                if src[j] == "'":
                    if j + 1 < n and src[j + 1] == "'":
                        chars.append("'")
                        j += 2
                        continue
                    break
                chars.append(src[j])
                j += 1
            if j + 1 >= n or src[j + 1] != "!":
                raise ParseError(f"expected ! after sheet name at {i}")
            out.append(Token("sheet", "".join(chars), i))
            i = j + 2
        elif c == "#":
            match = re.match(
                r"#(NULL!|DIV/0!|VALUE!|REF!|NAME\?|NUM!|N/A|GETTING_DATA|SPILL!|CALC!)",
                src[i:],
                re.I,
            )
            if not match:
                raise ParseError(f"unknown error literal at {i}")
            error = CellError.parse(match.group(0))
            assert error is not None
            out.append(Token("error", error, i))
            i += len(match.group(0))
        elif c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i
            while j < n and src[j].isdigit():
                j += 1
            if (
                j < n
                and src[j] == ":"
                and j + 1 < n
                and (src[j + 1].isdigit() or src[j + 1] == "$")
            ):
                out.append(Token("word", src[i:j], i))  # row range such as 1:3
                i = j
                continue
            if j < n and src[j] == ".":
                j += 1
                while j < n and src[j].isdigit():
                    j += 1
            if j < n and src[j] in "eE":
                k = j + 1
                if k < n and src[k] in "+-":
                    k += 1
                if k < n and src[k].isdigit():
                    while k < n and src[k].isdigit():
                        k += 1
                    j = k
            out.append(Token("num", float(src[i:j]), i))
            i = j
        elif c in "(){},;:":
            out.append(Token(c, None, i))
            i += 1
        elif c in "<>":
            two = src[i : i + 2]
            op = two if two in ("<=", "<>", ">=") else c
            out.append(Token("op", op, i))
            i += len(op)
        elif c in "+-*/^&%@=":
            out.append(Token("op", c, i))
            i += 1
        elif _WORD_CHARS.match(c):
            j = i
            while j < n and _WORD_CHARS.match(src[j]):
                j += 1
            word = src[i:j]
            if j < n and src[j] == "!":
                out.append(Token("sheet", word, i))
                i = j + 1
                continue
            if j < n and src[j] == "(":
                out.append(Token("func", word, i))
            elif word.upper() in ("TRUE", "FALSE") and not (j < n and src[j] == ":"):
                out.append(Token("bool", word.upper() == "TRUE", i))
            else:
                out.append(Token("word", word, i))
            i = j
        else:
            raise ParseError(f"unexpected character {c!r} at {i}")
    out.append(Token("eof", None, n))
    return _significant_spaces(out)


def _significant_spaces(tokens: list[Token]) -> list[Token]:
    """Keep a space only where it is the intersection operator."""
    out: list[Token] = []
    for index, token in enumerate(tokens):
        if token.kind == "space":
            prev_end = bool(out) and out[-1].kind in ("word", ")", "error")
            nxt = tokens[index + 1] if index + 1 < len(tokens) else None
            next_start = nxt is not None and nxt.kind in ("word", "sheet", "(", "func", "error")
            if prev_end and next_start:
                out.append(token)
            continue
        out.append(token)
    return out


# ---------------------------------------------------------------- parser


def col_index(letters: str) -> int:
    index = 0
    for ch in letters.upper():
        index = index * 26 + (ord(ch) - 64)
    return index - 1


def col_letters(index: int) -> str:
    index += 1
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def parse_cell(text: str) -> tuple[int, int] | None:
    match = _CELL.match(text)
    if not match:
        return None
    col, row = col_index(match.group(1)), int(match.group(2)) - 1
    if col >= MAX_COLS or row >= MAX_ROWS:
        return None
    return row, col


def normalize_function_name(name: str) -> str:
    upper = name.upper()
    for prefix in ("_XLFN._XLWS.", "_XLFN.", "_XLWS."):
        if upper.startswith(prefix):
            return upper[len(prefix) :]
    return upper


def parse(source: str) -> Expr:
    body = source[1:] if source.startswith("=") else source
    parser = _Parser(tokenize(body))
    expr = parser.expr(0, allow_union=False)
    if parser.peek().kind != "eof":
        raise ParseError(f"unexpected {parser.peek().kind} at {parser.peek().pos}")
    return expr


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.i = 0
        self.depth = 0

    def peek(self, k: int = 0) -> Token:
        return self.tokens[min(self.i + k, len(self.tokens) - 1)]

    def next(self) -> Token:
        token = self.peek()
        self.i = min(self.i + 1, len(self.tokens) - 1)
        return token

    def expect(self, kind: str) -> None:
        token = self.next()
        if token.kind != kind:
            raise ParseError(f"expected {kind!r}, found {token.kind!r} at {token.pos}")

    def binop(self, allow_union: bool) -> str | None:
        token = self.peek()
        if token.kind == "op" and token.value in PRECEDENCE:
            return str(token.value)
        if token.kind == ":":
            return ":"
        if token.kind == "space":
            return " "
        if token.kind == "," and allow_union:
            return ","
        return None

    def expr(self, min_bp: int, allow_union: bool) -> Expr:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ParseError("formula is nested too deeply")
        left = self.prefix(allow_union)
        while True:
            token = self.peek()
            if token.kind == "op" and token.value == "%":
                if min_bp > 70:
                    break
                self.next()
                left = Unary("%", left)
                continue
            op = self.binop(allow_union)
            if op is None:
                break
            bp = PRECEDENCE[op]
            if bp < min_bp:
                break
            self.next()
            right = self.expr(bp + 1, allow_union)
            left = Binary(op, left, right)
        self.depth -= 1
        return left

    def args(self) -> tuple[Expr, ...]:
        self.expect("(")
        args: list[Expr] = []
        if self.peek().kind == ")":
            self.next()
            return ()
        while True:
            if self.peek().kind in (",", ")"):
                args.append(Missing())
            else:
                args.append(self.expr(0, allow_union=False))
            token = self.next()
            if token.kind == ",":
                continue
            if token.kind == ")":
                break
            raise ParseError(f"expected ',' or ')' at {token.pos}")
        if len(args) > 255:
            raise ParseError("too many arguments")
        return tuple(args)

    def prefix(self, allow_union: bool) -> Expr:
        token = self.next()
        kind = token.kind
        if kind == "num":
            return Num(float(token.value))  # type: ignore[arg-type]
        if kind == "text":
            return Text(str(token.value))
        if kind == "bool":
            return Bool(bool(token.value))
        if kind == "error":
            assert isinstance(token.value, CellError)
            return Err(token.value)
        if kind == "op" and token.value in ("-", "+"):
            return Unary(str(token.value), self.expr(60, allow_union))
        if kind == "op" and token.value == "@":
            return Unary("@", self.expr(95, allow_union))
        if kind == "(":
            inner = self.expr(0, allow_union=True)
            self.expect(")")
            return inner
        if kind == "{":
            return self.array()
        if kind == "func":
            return Call(normalize_function_name(str(token.value)), self.args())
        if kind == "sheet":
            word = self.next()
            if word.kind == "error" and word.value == CellError.REF:
                return Err(CellError.REF)
            if word.kind not in ("word", "num", "bool"):
                raise ParseError(f"expected a reference after the sheet name at {word.pos}")
            text = str(word.value) if word.kind == "word" else _token_text(word)
            return self.reference(str(token.value), text)
        if kind == "word":
            return self.reference(None, str(token.value))
        raise ParseError(f"unexpected {kind!r} at {token.pos}")

    def reference(self, sheet: str | None, word: str) -> Expr:
        cell = parse_cell(word)
        if self.peek().kind == ":":
            end = self.peek(1)
            end_text = _token_text(end)
            if cell is not None and parse_cell(end_text) is not None:
                self.next()
                self.next()
                other = parse_cell(end_text)
                assert other is not None
                return _range(sheet, cell, other)
            col_a, col_b = _COL.match(word), _COL.match(end_text)
            if cell is None and col_a and col_b:
                self.next()
                self.next()
                a, b = col_index(col_a.group(1)), col_index(col_b.group(1))
                return Ref(sheet, 0, min(a, b), MAX_ROWS - 1, max(a, b))
            row_a, row_b = _ROW.match(word), _ROW.match(end_text)
            if row_a and row_b:
                self.next()
                self.next()
                a, b = int(row_a.group(1)) - 1, int(row_b.group(1)) - 1
                return Ref(sheet, min(a, b), 0, max(a, b), MAX_COLS - 1)
        if cell is not None:
            return Ref(sheet, cell[0], cell[1], cell[0], cell[1])
        if sheet is not None:
            raise ParseError(f"not a reference: {sheet}!{word}")
        return Name(word)

    def array(self) -> ArrayLit:
        rows: list[list[Expr]] = [[]]
        while True:
            token = self.next()
            if token.kind == "num":
                element: Expr = Num(float(token.value))  # type: ignore[arg-type]
            elif token.kind == "op" and token.value in ("-", "+"):
                number = self.next()
                if number.kind != "num":
                    raise ParseError("expected a number in array")
                sign = -1.0 if token.value == "-" else 1.0
                element = Num(sign * float(number.value))  # type: ignore[arg-type]
            elif token.kind == "text":
                element = Text(str(token.value))
            elif token.kind == "bool":
                element = Bool(bool(token.value))
            elif token.kind == "error":
                assert isinstance(token.value, CellError)
                element = Err(token.value)
            else:
                raise ParseError("array constants may only contain constants")
            rows[-1].append(element)
            separator = self.next()
            if separator.kind == ",":
                continue
            if separator.kind == ";":
                rows.append([])
                continue
            if separator.kind == "}":
                break
            raise ParseError("expected ',', ';' or '}' in array")
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise ParseError("array rows must have the same length")
        return ArrayLit(tuple(tuple(row) for row in rows))


def _range(sheet: str | None, a: tuple[int, int], b: tuple[int, int]) -> Ref:
    return Ref(sheet, min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def _token_text(token: Token) -> str:
    if token.kind == "num":
        value = float(token.value)  # type: ignore[arg-type]
        return str(int(value)) if value.is_integer() else str(value)
    if token.kind == "bool":
        return "TRUE" if token.value else "FALSE"
    return str(token.value) if token.value is not None else ""
