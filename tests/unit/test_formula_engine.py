"""Evaluation tests for operators, coercion, aggregates, criteria and lookup functions."""

from __future__ import annotations

import pytest

from activities._formula.values import Array, CellError
from tests.unit.formula_support import CRITERIA, LOOKUP, MIXED, NUMBERS, Host, PoisonHost, evaluate

# ---------------------------------------------------------------- operators and precedence


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=-2^2", 4.0),
        ("=-3^2", 9.0),
        ("=2^-3", 0.125),
        ("=2^3^2", 64.0),
        ("=2^3*4", 32.0),
        ("=2*3^2", 18.0),
        ("=(2^3)^2", 64.0),
        ("=2+3*4", 14.0),
        ("=(2+3)*4", 20.0),
        ("=1+2*3^2", 19.0),
        ("=10-3-2", 5.0),
        ("=100/10/2", 5.0),
        ("=100/10*2", 20.0),
        ("=50%", 0.5),
        ("=200%*2", 4.0),
        ("=-50%", -0.5),
        ("=2+50%", 2.5),
        ("=50%%", 0.005),
        ('="a"&"b"', "ab"),
        ('="Total: "&1+2', "Total: 3"),
        ("=1&2&3", "123"),
        ("=1<2", True),
        ("=2<=2", True),
        ("=2>3", False),
        ("=2>=2", True),
        ("=1=1", True),
        ("=1<>1", False),
        ('="A"="a"', True),
        ('="a"<"b"', True),
        ('=1<"a"', True),
        ('="a"<TRUE', True),
        ("=FALSE<TRUE", True),
        ("=FALSE=0", False),
    ],
)
def test_operators_and_precedence(formula: str, expected: object) -> None:
    assert evaluate(formula) == expected


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=0.1+0.2=0.3", True),
        ("=0.1+0.2>0.3", False),
        ("=1.000000000000001=1", True),
        ("=1.234567890123456=1.234567890123457", True),
        ("=1234567890123456=1234567890123457", True),
        ("=1/3=0.333333333333333", True),
        ("=100000000000000=100000000000001", False),
    ],
)
def test_comparison_uses_fifteen_significant_digits(formula: str, expected: bool) -> None:
    assert evaluate(formula) is expected


# ---------------------------------------------------------------- coercion


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ('="1,234.5"+0', 1234.5),
        ('="50%"+0', 0.5),
        ('="$1,234.50"+0', 1234.5),
        ('="(1,234)"+0', -1234.0),
        ('="1e3"*1', 1000.0),
        ("=TRUE+1", 2.0),
        ("=FALSE+1", 1.0),
        ("=TRUE*5", 5.0),
        ('=1&""', "1"),
        ('=2.5&""', "2.5"),
        ('=TRUE&""', "TRUE"),
        ('=FALSE&""', "FALSE"),
        ('=""&""', ""),
        ('=1/3&""', "0.333333333333333"),
    ],
)
def test_coercion(formula: str, expected: object) -> None:
    assert evaluate(formula) == expected


def test_empty_cell_coerces_to_zero_and_empty_text() -> None:
    host = Host({"Sheet1!A1": None})

    assert host.evaluate("=A1+5") == 5.0
    assert host.evaluate("=5-A1") == 5.0
    assert host.evaluate("=A1*0") == 0.0
    assert host.evaluate('=A1&"x"') == "x"
    assert host.evaluate('=""&A1') == ""
    assert host.evaluate("=A1=0") is True
    assert host.evaluate('=A1=""') is True
    assert host.evaluate("=A1=FALSE") is True


# ---------------------------------------------------------------- aggregates


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=SUM(A1:A5)", 3.0),
        ("=SUM(A1:A5,B1:B3)", 63.0),
        ("=SUM(A1:A5)+SUM(B1:B3)", 63.0),
        ("=AVERAGE(A1:A5)", 1.5),
        ("=MIN(A1:A5)", 1.0),
        ("=MAX(A1:A5)", 2.0),
        ("=COUNT(A1:A5)", 2.0),
        ("=COUNTA(A1:A5)", 4.0),
        ("=COUNTBLANK(A1:A5)", 1.0),
        ('=SUM("2",TRUE)', 3.0),
        ('=SUM("2","3")', 5.0),
        ("=SUM(TRUE,FALSE,TRUE)", 2.0),
        ("=SUM(1,,2)", 3.0),
        ("=SUM({1,2;3,4})", 10.0),
        ("=SUM(B1:B3*2)", 120.0),
        ("=PRODUCT(2,3,4)", 24.0),
        ("=PRODUCT(B1:B3)", 6000.0),
    ],
)
def test_aggregates(formula: str, expected: float) -> None:
    assert evaluate(formula, MIXED) == expected


@pytest.mark.parametrize(
    ("formula", "error"),
    [
        ('=SUM("abc")', CellError.VALUE),
        ("=SUM(A1:A2,NA())", CellError.NA),
        ("=SUM(1,1/0)", CellError.DIV0),
        ("=SUM(A1:A3*2)", CellError.VALUE),
        ("=AVERAGE(A1:A3*2)", CellError.VALUE),
    ],
)
def test_aggregate_errors(formula: str, error: CellError) -> None:
    assert evaluate(formula, MIXED) is error


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=SUM(A1:A3)", 6.0),
        ("=AVERAGE(A1:A3)", 2.0),
        ("=MIN(A1:A3)", 1.0),
        ("=MAX(A1:A3)", 3.0),
        ("=COUNT(A1:A3)", 3.0),
        ("=COUNTA(A1:A3)", 3.0),
    ],
)
def test_aggregates_over_numeric_ranges(formula: str, expected: float) -> None:
    assert evaluate(formula, NUMBERS) == expected


# ---------------------------------------------------------------- implicit intersection


def test_implicit_intersection_of_a_column_range() -> None:
    host = Host(NUMBERS)

    assert host.evaluate("=ABS(A1:A5)", row=1) == 2.0
    assert host.evaluate("=ABS(A1:A5)", row=4) == 5.0
    assert host.evaluate("=ABS(A1:A5)", row=7) is CellError.VALUE
    assert host.evaluate("=@A1:A5", row=2) == 3.0


def test_implicit_intersection_of_a_row_range() -> None:
    host = Host({"Sheet1!A1": 1.0, "Sheet1!B1": 10.0, "Sheet1!C1": 100.0})

    assert host.evaluate("=ABS(A1:C1)", col=1) == 10.0
    assert host.evaluate("=ABS(A1:C1)", col=2) == 100.0
    assert host.evaluate("=ABS(A1:C1)", row=1) == 1.0
    assert host.evaluate("=ABS(A1:C1)", row=1, col=3) is CellError.VALUE


def test_two_dimensional_range_in_scalar_context_is_value_error() -> None:
    host = Host(MIXED)

    assert host.evaluate("=ABS(A1:B2)", row=1) is CellError.VALUE
    assert host.evaluate("=@A1:B2") is CellError.VALUE


def test_range_arithmetic_broadcasts_to_an_array() -> None:
    value = evaluate("=A1:A3*2", NUMBERS)

    assert isinstance(value, Array)
    assert (value.rows, value.cols) == (3, 1)
    assert value.data == (2.0, 4.0, 6.0)
    assert evaluate("=SUM(A1:A3*10)", NUMBERS) == 60.0


# ---------------------------------------------------------------- IF, IFS, SWITCH, CHOOSE


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=IF(TRUE,1,2)", 1.0),
        ("=IF(FALSE,1,2)", 2.0),
        ("=IF(1,10,20)", 10.0),
        ("=IF(0,10,20)", 20.0),
        ('=IF("TRUE",10,20)', 10.0),
        ('=IF("FALSE",10,20)', 20.0),
        ("=IF(TRUE,1)", 1.0),
        ("=IF(FALSE,1)", False),
        ("=IFERROR(1/0,42)", 42.0),
        ("=IFERROR(7,1/0)", 7.0),
        ('=IFNA(NA(),"missing")', "missing"),
        ('=IFNA(1/0,"missing")', CellError.DIV0),
        ("=IFERROR(1/0,1/0)", CellError.DIV0),
        ("=IF(NA(),1,2)", CellError.NA),
        ('=IF("yes",1,2)', CellError.VALUE),
        ("=IFS(FALSE,1,TRUE,2)", 2.0),
        ("=IFS(0,1,1,2)", 2.0),
        ("=IFS(0,1)", CellError.NA),
        ("=IFS(TRUE)", CellError.VALUE),
        ('=SWITCH(2,1,"a",2,"b")', "b"),
        ('=SWITCH(9,1,"a",2,"b")', CellError.NA),
        ('=SWITCH(9,1,"a",2,"b","other")', "other"),
        ('=SWITCH("x","x",1)', 1.0),
        ('=CHOOSE(2,"a","b","c")', "b"),
        ('=CHOOSE(9,"a")', CellError.VALUE),
        ('=CHOOSE(0,"a")', CellError.VALUE),
        ('=CHOOSE("1e999",1)', CellError.VALUE),
    ],
)
def test_if_family(formula: str, expected: object) -> None:
    assert evaluate(formula) == expected


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=IF(TRUE,1,A1)", 1.0),
        ("=IFERROR(1,A1)", 1.0),
        ("=IFNA(1,A1)", 1.0),
        ("=IFS(TRUE,1,FALSE,A1)", 1.0),
        ("=CHOOSE(1,1,A1)", 1.0),
        ('=SWITCH(1,1,"hit",A1,"miss")', "hit"),
    ],
)
def test_untaken_branches_are_not_evaluated(formula: str, expected: object) -> None:
    assert PoisonHost().evaluate(formula) == expected


# ---------------------------------------------------------------- criteria functions


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ('=COUNTIF(A1:A5,"a*")', 4.0),
        ('=COUNTIF(A1:A5,"ap*")', 2.0),
        ('=COUNTIF(A1:A5,"?p*")', 2.0),
        ('=COUNTIF(A1:A5,"a~*b")', 1.0),
        ('=COUNTIF(A1:A5,"a~?b")', 1.0),
        ('=COUNTIF(A1:A5,"<>apple")', 4.0),
        ('=COUNTIF(A1:A5,"apple")', 1.0),
        ('=COUNTIF(C1:C3,">5")', 2.0),
        ('=COUNTIF(C1:C3,">=15")', 2.0),
        ('=COUNTIF(C1:C3,"<=15")', 2.0),
        ('=COUNTIF(C1:C3,"<>15")', 2.0),
        ("=COUNTIF(C1:C3,15)", 1.0),
        ('=COUNTIF(C1:C3,"15")', 1.0),
        ('=COUNTIF(A1:A5,"*e*")', 2.0),
        ("=COUNTBLANK(A1:A5)", 0.0),
    ],
)
def test_countif_and_friends(formula: str, expected: float) -> None:
    assert evaluate(formula, CRITERIA) == expected


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ('=SUMIF(C1:C3,">5")', 40.0),
        ('=SUMIF(C1:C3,">5",B1:B3)', 5.0),
        ('=SUMIF(A1:A5,"a*",B1:B5)', 12.0),
        ('=SUMIF(A1:A5,"a~*b",B1:B5)', 4.0),
        ('=SUMIF(A1:A5,"<>apple",B1:B5)', 14.0),
        ('=SUMIFS(B1:B5,A1:A5,"a*")', 12.0),
        ('=SUMIFS(B1:B5,A1:A5,"a*",B1:B5,">=4")', 9.0),
        ('=AVERAGEIF(C1:C3,">5")', 20.0),
        ('=AVERAGEIF(C1:C3,">5",B1:B3)', 2.5),
        ('=AVERAGEIFS(B1:B5,A1:A5,"a*")', 3.0),
        ('=AVERAGEIFS(B1:B5,A1:A5,"a*",B1:B5,">=4")', 4.5),
        ('=COUNTIFS(A1:A5,"a*",B1:B5,">=4")', 2.0),
        ('=COUNTIFS(C1:C3,">5",C1:C3,"<25")', 1.0),
    ],
)
def test_sumif_countifs_averageifs(formula: str, expected: float) -> None:
    assert evaluate(formula, CRITERIA) == expected


def test_averageif_without_matches_is_div0() -> None:
    assert evaluate('=AVERAGEIF(C1:C3,">100")', CRITERIA) is CellError.DIV0
    assert evaluate('=AVERAGEIFS(B1:B5,A1:A5,"zzz")', CRITERIA) is CellError.DIV0


# ---------------------------------------------------------------- lookup


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=VLOOKUP(2,D1:E3,2,FALSE)", "two"),
        ("=VLOOKUP(2.5,D1:E3,2,TRUE)", "two"),
        ('=VLOOKUP("b*",B1:B5,1,FALSE)', "b"),
        ("=VLOOKUP(1,D1:E3,1,FALSE)", 1.0),
        ("=VLOOKUP(9,D1:E3,2,FALSE)", CellError.NA),
        ("=VLOOKUP(2,D1:E3,3,FALSE)", CellError.REF),
        ("=VLOOKUP(2,D1:E3,0,FALSE)", CellError.VALUE),
        ("=HLOOKUP(2,G1:I2,2,FALSE)", "y"),
        ("=HLOOKUP(2.5,G1:I2,2,TRUE)", "y"),
        ("=HLOOKUP(9,G1:I2,2,FALSE)", CellError.NA),
        ("=HLOOKUP(2,G1:I2,3,FALSE)", CellError.REF),
        ("=MATCH(3,A1:A5,0)", 3.0),
        ("=MATCH(3,A1:A5)", 3.0),
        ("=MATCH(2.5,A1:A5,1)", 2.0),
        ('=MATCH("b*",B1:B5,0)', 2.0),
        ("=MATCH(0,A1:A5,1)", CellError.NA),
        ("=MATCH(2.5,C1:C5,-1)", 3.0),
        ("=MATCH(9,C1:C5,-1)", CellError.NA),
        ("=MATCH(9,A1:A5,0)", CellError.NA),
        ("=XLOOKUP(3,A1:A5,B1:B5)", "c"),
        ("=XLOOKUP(9,A1:A5,B1:B5)", CellError.NA),
        ('=XLOOKUP(9,A1:A5,B1:B5,"missing")', "missing"),
        ("=XLOOKUP(2.5,A1:A5,B1:B5,,-1)", "b"),
        ("=XLOOKUP(2.5,A1:A5,B1:B5,,1)", "c"),
        ('=XLOOKUP("c*",B1:B5,A1:A5,,2)', 3.0),
        ("=XLOOKUP(3,A1:A5,B1:B5,,0,-1)", "c"),
        ("=INDEX(B1:B5,3)", "c"),
        ("=INDEX(D1:E3,2,2)", "two"),
        ("=INDEX(D1:E3,1,3)", CellError.REF),
        ("=INDEX(D1:E3,4,1)", CellError.REF),
    ],
)
def test_lookup(formula: str, expected: object) -> None:
    assert evaluate(formula, LOOKUP) == expected


def test_index_whole_row_and_column() -> None:
    row = evaluate("=INDEX(D1:E3,2,0)", LOOKUP)
    column = evaluate("=INDEX(D1:E3,0,2)", LOOKUP)
    whole = evaluate("=INDEX(D1:E3,0,0)", LOOKUP)

    assert isinstance(row, Array) and row.data == (2.0, "two")
    assert isinstance(column, Array) and column.data == ("one", "two", "three")
    assert isinstance(whole, Array) and (whole.rows, whole.cols) == (3, 2)
    assert evaluate("=INDEX(A1:A5,2)", LOOKUP) == 2.0
    whole_column = evaluate("=INDEX(A1:A5,0,0)", LOOKUP)
    assert isinstance(whole_column, Array) and whole_column.data == (1.0, 2.0, 3.0, 4.0, 5.0)
