"""Error values, parser details, workbook integration and property-based checks."""

from __future__ import annotations

import math
import string
from pathlib import Path

import openpyxl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from openpyxl.workbook.defined_name import DefinedName

from activities._formula.parser import (
    MAX_COLS,
    MAX_ROWS,
    ArrayLit,
    Binary,
    Call,
    Name,
    Num,
    ParseError,
    Ref,
    Text,
    Unary,
    parse,
)
from activities._formula.values import Array, CellError
from activities._formula.workbook import Workbook
from tests.unit.formula_support import MIXED, Host, evaluate

# ---------------------------------------------------------------- errors


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=1+#VALUE!", CellError.VALUE),
        ("=NA()+1", CellError.NA),
        ('="x"&NA()', CellError.NA),
        ("=#REF!", CellError.REF),
        ("=#DIV/0!*2", CellError.DIV0),
        ("=UNKNOWNFN(1)", CellError.NAME),
        ("=Missing!A1", CellError.REF),
        ('="abc"+1', CellError.VALUE),
        ("=SUM(1,1/0)", CellError.DIV0),
        ("=IFERROR(1/0,1/0)", CellError.DIV0),
        ("=#N/A<1", CellError.NA),
        ("=ISERROR(#N/A)", True),
        ("=ISNA(#N/A)", True),
        ("=ISNA(#VALUE!)", False),
    ],
)
def test_error_values(formula: str, expected: object) -> None:
    assert evaluate(formula) == expected


def test_error_propagates_through_text_and_arithmetic() -> None:
    assert evaluate('=#N/A&"x"') is CellError.NA
    assert evaluate("=1+#REF!") is CellError.REF


# ---------------------------------------------------------------- parser


def test_parse_tree_shapes() -> None:
    tree = parse("=-2^2")

    assert isinstance(tree, Binary) and tree.op == "^"
    assert isinstance(tree.left, Unary) and tree.left.op == "-"
    assert isinstance(tree.right, Num) and tree.right.value == 2.0
    power = parse("=2^3^2")
    assert isinstance(power, Binary) and power.op == "^"
    assert power.left == Binary("^", Num(2.0), Num(3.0))
    call = parse("=SUM(1,2)")
    assert isinstance(call, Call) and call.name == "SUM" and len(call.args) == 2
    assert isinstance(parse("={1,2;3,4}"), ArrayLit)
    assert parse("x") == Name("x")


def test_parser_references() -> None:
    assert parse("=$A$1") == Ref(None, 0, 0, 0, 0)
    assert parse("=A1:B2") == Ref(None, 0, 0, 1, 1)
    assert parse("=B2:A1") == Ref(None, 0, 0, 1, 1)
    assert parse("='My Sheet'!C3") == Ref("My Sheet", 2, 2, 2, 2)
    assert parse("=A:A") == Ref(None, 0, 0, MAX_ROWS - 1, 0)
    assert parse("=1:3") == Ref(None, 0, 0, 2, MAX_COLS - 1)
    assert parse("=Name1") == Name("Name1")
    assert parse("=_xlfn.CONCAT(1)").name == "CONCAT"


def test_string_escapes_and_quoted_sheets() -> None:
    assert parse('="a""b"') == Text('a"b')
    assert evaluate('="a""b"') == 'a"b'
    assert evaluate('=""""') == '"'
    host = Host({"My Sheet!A1": 9.0, "It's!A1": 4.0}, sheets=("My Sheet", "It's"))

    assert host.evaluate("='My Sheet'!A1") == 9.0
    assert host.evaluate("='It''s'!A1") == 4.0
    assert host.evaluate("='My Sheet'!A1*2") == 18.0


def test_defined_names_resolve_through_the_host() -> None:
    host = Host(
        {"Sheet1!B2": 5.0},
        names={"Rate": "Sheet1!$B$2", "Doubled": "=Rate*2"},
    )

    assert host.evaluate("=Rate") == 5.0
    assert host.evaluate("=Rate*2") == 10.0
    assert host.evaluate("=Doubled") == 10.0
    assert host.evaluate("=MissingName") is CellError.NAME


@pytest.mark.parametrize(
    "formula",
    [
        "=",
        "=1+",
        "=(1+2",
        '="abc',
        "=SUM(1,",
        "=A1:",
        "=1 2",
        "=1+*2",
        "=)",
        "=#BAD!",
        "=SUM(1))",
    ],
)
def test_malformed_formulas_return_name_error(formula: str) -> None:
    with pytest.raises(ParseError):
        parse(formula)
    assert evaluate(formula) is CellError.NAME


def test_whole_column_and_row_ranges_reference_the_sheet() -> None:
    cells = {"Sheet1!A1": 1.0, "Sheet1!A2": 2.0, "Sheet1!B1": 10.0, "Sheet1!B2": 20.0}

    assert evaluate("=SUM(A:A)", cells) == 3.0
    assert evaluate("=SUM(1:2)", cells) == 33.0
    assert evaluate("=COUNTA(A:A)", cells) == 2.0
    assert evaluate("=SUM(A:A)+SUM($B:$B)", cells) == 33.0


# ---------------------------------------------------------------- workbook integration


def _build_workbook(path: Path) -> Path:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = 1
    sheet["A2"] = 2
    sheet["B1"] = 10
    sheet["B2"] = 20
    sheet["C1"] = "=A1+A2"
    sheet["D1"] = "=E1"
    sheet["E1"] = "=D1"
    sheet["F1"] = "=Nope!A1"
    sheet["G1"] = "=NOSUCHFN(1)"
    sheet["H1"] = "=Factor*10"
    sheet["I1"] = "='My Sheet'!A1*2"
    other = book.create_sheet("My Sheet")
    other["A1"] = 7
    book.defined_names["Factor"] = DefinedName("Factor", attr_text="Sheet1!$A$1")
    book.save(path)
    return path


def test_workbook_evaluation_covers_circ_ref_and_name(tmp_path: Path) -> None:
    book = Workbook.open(_build_workbook(tmp_path / "book.xlsx"))

    assert book.value("Sheet1", "C1") == 3.0
    assert book.value("Sheet1", "D1") is CellError.CIRC
    assert book.value("Sheet1", "E1") is CellError.CIRC
    assert str(book.value("Sheet1", "D1")) == "#CIRC!"
    assert book.value("Sheet1", "F1") is CellError.REF
    assert book.value("Sheet1", "G1") is CellError.NAME
    assert book.value("Sheet1", "H1") == 10.0
    assert book.value("Sheet1", "I1") == 14.0
    assert book.evaluate("Sheet1", "=SUM(A1:B2)") == 33.0
    assert book.evaluate("Sheet1", "=C1*2") == 6.0


# ---------------------------------------------------------------- property tests


def test_arbitrary_printable_text_never_raises() -> None:
    host = Host(MIXED)

    @settings(max_examples=100, deadline=None)
    @given(st.text(alphabet=string.printable, max_size=40))
    def check(text: str) -> None:
        value = host.evaluate(text)
        assert isinstance(value, type(None) | float | str | bool | CellError | Array)

    check()


@settings(max_examples=100, deadline=None)
@given(
    st.lists(
        st.floats(min_value=-1e12, max_value=1e12, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=20,
    )
)
def test_sum_matches_fsum(values: list[float]) -> None:
    formula = "=SUM(" + ",".join(repr(value) for value in values) + ")"
    result = evaluate(formula)

    assert isinstance(result, float)
    assert math.isclose(result, math.fsum(values), rel_tol=1e-12, abs_tol=1e-9)


@settings(max_examples=100, deadline=None)
@given(
    st.floats(allow_nan=False, allow_infinity=False),
    st.floats(allow_nan=False, allow_infinity=False),
)
def test_addition_is_commutative(a: float, b: float) -> None:
    left = evaluate(f"={a!r}+{b!r}")
    right = evaluate(f"={b!r}+{a!r}")

    assert left == right
