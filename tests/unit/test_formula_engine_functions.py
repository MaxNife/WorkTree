"""Text, date, financial and math worksheet functions of the pure-Python formula engine."""

from __future__ import annotations

from datetime import date

import pytest

from activities._formula.values import CellError, date_to_serial
from tests.unit.formula_support import MIXED, Host, assert_close, evaluate

# ---------------------------------------------------------------- text


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ('=LEFT("hello",2)', "he"),
        ('=LEFT("hello")', "h"),
        ('=LEFT("hello",0)', ""),
        ('=LEFT("hello",99)', "hello"),
        ('=RIGHT("hello",2)', "lo"),
        ('=RIGHT("hello")', "o"),
        ('=RIGHT("hello",0)', ""),
        ('=MID("hello",2,3)', "ell"),
        ('=MID("hello",2,99)', "ello"),
        ('=MID("hello",1,0)', ""),
        ('=LEN("hello")', 5.0),
        ('=LEN("")', 0.0),
        ('=LOWER("Hello World")', "hello world"),
        ('=UPPER("Hello World")', "HELLO WORLD"),
        ('=TRIM("  a   b  ")', "a b"),
        ('=TRIM("   ")', ""),
        ('=SUBSTITUTE("aaa","a","b")', "bbb"),
        ('=SUBSTITUTE("aaa","a","b",2)', "aba"),
        ('=SUBSTITUTE("aaa","a","b",4)', "aaa"),
        ('=TEXT(1234.567,"#,##0.00")', "1,234.57"),
        ('=TEXT(1234.567,"$#,##0.00")', "$1,234.57"),
        ('=TEXT(1234.567,"0")', "1235"),
        ('=TEXT(0.5,"0%")', "50%"),
        ('=TEXT(0.1234,"0.0%")', "12.3%"),
        ('=TEXT("abc","0")', "abc"),
        ('=TEXT(DATE(2024,1,1),"yyyy-mm-dd")', "2024-01-01"),
        ('=TEXT(DATE(2024,1,1),"dddd")', "Monday"),
        ('=TEXT(DATE(2024,1,1),"mmmm d, yyyy")', "January 1, 2024"),
        ('=TEXT(0.5,"hh:mm")', "12:00"),
        ('=TEXT(0.75,"hh:mm:ss")', "18:00:00"),
        ('=CONCATENATE("a","b",1)', "ab1"),
        ('=CONCAT("a",1,TRUE)', "a1TRUE"),
        ("=CONCAT(A1:A3)", "12text"),
        ('=TEXTJOIN("-",TRUE,"a","","b")', "a-b"),
        ('=TEXTJOIN("-",FALSE,"a","","b")', "a--b"),
        ('=TEXTJOIN("-",TRUE,A1:A3)', "1-2-text"),
        ('=FIND("l","hello")', 3.0),
        ('=FIND("l","hello",4)', 4.0),
        ('=FIND("L","hello")', CellError.VALUE),
        ('=FIND("z","hello")', CellError.VALUE),
        ('=SEARCH("L","hello")', 3.0),
        ('=SEARCH("?l","hello")', 2.0),
        ('=SEARCH("l*","hello")', 3.0),
        ('=SEARCH("~*","a*b")', 2.0),
        ('=VALUE("1,234.5")', 1234.5),
        ('=VALUE("50%")', 0.5),
        ('=VALUE("abc")', CellError.VALUE),
    ],
)
def test_text_functions(formula: str, expected: object) -> None:
    assert evaluate(formula, MIXED) == expected


def test_text_range_argument_uses_implicit_intersection() -> None:
    host = Host({"Sheet1!A1": "alpha", "Sheet1!A2": "beta"})

    assert host.evaluate("=LEFT(A1:A2,2)", row=1) == "be"


# ---------------------------------------------------------------- dates


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=DATE(2024,1,1)", 45292.0),
        ("=DATE(2024,2,29)", 45351.0),
        ("=DATE(2024,13,1)", 45658.0),
        ("=DATE(2024,0,1)", 45261.0),
        ("=DATE(2024,1,0)", 45291.0),
        ("=DATE(2024,2,30)", 45352.0),
        ("=DATE(1900,1,1)", 1.0),
        ("=DATE(1900,2,28)", 59.0),
        ("=DATE(1900,2,29)", 60.0),
        ("=DATE(1900,2,30)", 61.0),
        ("=DATE(1900,3,1)", 61.0),
        ("=DATE(1900,1,0)", 0.0),
        ("=EDATE(DATE(2024,1,31),1)", 45351.0),
        ("=EDATE(DATE(2024,3,31),-1)", 45351.0),
        ("=EDATE(DATE(2023,1,31),1)", 44985.0),
        ("=EOMONTH(DATE(2024,1,15),1)", 45351.0),
        ("=EOMONTH(DATE(2024,3,31),-1)", 45351.0),
        ("=EOMONTH(DATE(2024,1,31),0)", 45322.0),
        ("=DAYS(DATE(2024,1,31),DATE(2024,1,1))", 30.0),
        ('=DATEVALUE("2024-01-15")', 45306.0),
        ("=WEEKDAY(DATE(2024,1,1))", 2.0),
        ("=WEEKDAY(DATE(2024,1,1),2)", 1.0),
        ("=WEEKDAY(DATE(2024,1,1),3)", 0.0),
        ("=WEEKDAY(DATE(2024,1,7))", 1.0),
        ("=YEAR(DATE(2024,3,5))", 2024.0),
        ("=MONTH(DATE(2024,3,5))", 3.0),
        ("=DAY(DATE(2024,3,5))", 5.0),
        ("=DAY(59)", 28.0),
        ("=MONTH(59)", 2.0),
        ("=YEAR(59)", 1900.0),
        ("=DAY(61)", 1.0),
        ("=TIME(12,30,0)", 0.5208333333333334),
        ("=HOUR(0.5)", 12.0),
        ("=MINUTE(0.5208333333333334)", 30.0),
        ("=WORKDAY(DATE(2024,1,1),10)", 45306.0),
        ("=NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,31))", 23.0),
        ("=NETWORKDAYS(DATE(2024,1,31),DATE(2024,1,1))", -23.0),
    ],
)
def test_date_functions(formula: str, expected: float) -> None:
    assert evaluate(formula) == expected


@pytest.mark.parametrize(
    ("unit", "expected"),
    [("Y", 1.0), ("M", 14.0), ("D", 430.0), ("YM", 2.0), ("MD", 5.0), ("YD", 64.0)],
)
def test_datedif_units(unit: str, expected: float) -> None:
    formula = f'=DATEDIF(DATE(2024,1,15),DATE(2025,3,20),"{unit}")'

    assert evaluate(formula) == expected


def test_networkdays_with_holidays() -> None:
    cells = {"Sheet1!C1": 45292.0, "Sheet1!C2": 45306.0}  # 1 and 15 January 2024

    assert evaluate("=NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,31),C1:C2)", cells) == 21.0
    assert evaluate("=NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,31),C1)", cells) == 22.0


def test_1900_serial_helpers_agree_with_date_function() -> None:
    assert date_to_serial(date(1900, 2, 28)) == 59.0
    assert date_to_serial(date(1900, 3, 1)) == 61.0
    assert date_to_serial(date(2024, 1, 1)) == 45292.0


# ---------------------------------------------------------------- financial


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=PMT(0.05/12,360,-300000)", 1610.4648690364195),
        ("=PMT(0.08/12,10,-10000)", 1037.0320893591636),
        ("=PMT(0,10,1000)", -100.0),
        ("=IPMT(0.05/12,1,360,-300000)", 1250.0),
        ("=IPMT(0.1/12,1,36,8000)", -66.66666666666667),
        ("=PPMT(0.05/12,1,360,-300000)", 360.4648690364195),
        ("=PPMT(0.1/12,1,24,2000)", -75.62318600836664),
        ("=NPER(0.06/12,-200,10000)", 57.68013595777633),
        ("=NPER(0.12/12,-100,-1000,10000,1)", 59.67386567429457),
        ("=RATE(48,-200,8000)", 0.007701472488202268),
        ("=RATE(10,0,-1000,2000)", 0.07177346253629316),
        ("=NPV(0.1,-10000,3000,4200,6800)", 1188.4434123352207),
        ("=NPV(0.1,100,200,300)", 481.59278737791124),
        ("=FV(0.06/12,10,-200,-500,1)", 2581.4033740601362),
        ("=FV(0.05/12,120,-100)", 15528.22794456672),
        ("=PV(0.08/12,240,500)", -59777.14585118777),
        ("=PV(0.05/12,120,-100)", 9428.135032823473),
    ],
)
def test_financial_functions(formula: str, expected: float) -> None:
    assert_close(evaluate(formula), expected, rel=1e-10, tol=1e-8)


@pytest.mark.parametrize("period", [1, 2, 180, 360])
def test_ipmt_and_ppmt_add_up_to_pmt(period: int) -> None:
    pmt = evaluate("=PMT(0.05/12,360,-300000)")
    ipmt = evaluate(f"=IPMT(0.05/12,{period},360,-300000)")
    ppmt = evaluate(f"=PPMT(0.05/12,{period},360,-300000)")

    assert isinstance(pmt, float) and isinstance(ipmt, float) and isinstance(ppmt, float)
    assert_close(ipmt + ppmt, pmt)


def test_irr_xirr_and_xnpv() -> None:
    assert_close(
        evaluate("=IRR({-70000,12000,15000,18000,21000,26000})"),
        0.08663094803653165,
        rel=1e-9,
        tol=1e-9,
    )
    assert_close(evaluate("=IRR({-100,30,40,50})"), 0.0889633946933499, rel=1e-9, tol=1e-9)
    flows = {
        "Sheet1!A1": -10000.0,
        "Sheet1!A2": 2750.0,
        "Sheet1!A3": 4250.0,
        "Sheet1!A4": 3250.0,
        "Sheet1!A5": 2750.0,
        "Sheet1!B1": 39448.0,
        "Sheet1!B2": 39508.0,
        "Sheet1!B3": 39751.0,
        "Sheet1!B4": 39859.0,
        "Sheet1!B5": 39904.0,
    }

    assert_close(evaluate("=XIRR(A1:A5,B1:B5)", flows), 0.37336253351883125, rel=1e-9)
    assert_close(evaluate("=XNPV(0.373362535,A1:A5,B1:B5)", flows), 0.0, rel=1.0, tol=1e-4)


def test_financial_errors() -> None:
    assert evaluate("=IRR({1,2,3})") is CellError.NUM
    assert evaluate("=NPV(0.1)") is CellError.VALUE
    assert evaluate("=PMT(0,0,1)") is CellError.NUM
    assert (
        evaluate(
            "=XIRR(A1:A2,B1:B2)",
            {"Sheet1!A1": 1.0, "Sheet1!A2": 2.0, "Sheet1!B1": 1.0, "Sheet1!B2": 2.0},
        )
        is CellError.NUM
    )


# ---------------------------------------------------------------- math


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=ROUND(2.5,0)", 3.0),
        ("=ROUND(-2.5,0)", -3.0),
        ("=ROUND(0.5,0)", 1.0),
        ("=ROUND(-0.5,0)", -1.0),
        ("=ROUND(2.675,2)", 2.68),
        ("=ROUND(-2.675,2)", -2.68),
        ("=ROUND(1234.5,-2)", 1200.0),
        ("=ROUND(1250,-2)", 1300.0),
        ("=ROUND(15,-1)", 20.0),
        ("=ROUNDUP(1234.1,-2)", 1300.0),
        ("=ROUNDUP(-1.1,0)", -2.0),
        ("=ROUNDDOWN(1239.9,-2)", 1200.0),
        ("=ROUNDDOWN(-1.9,0)", -1.0),
        ("=MOD(-3,2)", 1.0),
        ("=MOD(3,-2)", -1.0),
        ("=MOD(5,3)", 2.0),
        ("=MOD(-5,-3)", -2.0),
        ("=INT(-2.5)", -3.0),
        ("=INT(2.9)", 2.0),
        ("=ABS(-2.5)", 2.5),
        ("=CEILING(-2.5,2)", -2.0),
        ("=CEILING(2.1,0.5)", 2.5),
        ("=FLOOR(-2.5,2)", -4.0),
        ("=FLOOR(2.9,0.5)", 2.5),
        ("=POWER(2,10)", 1024.0),
        ("=SQRT(9)", 3.0),
        ("=LOG(8,2)", 3.0),
        ("=TRUNC(-1.9)", -1.0),
        ("=MROUND(10,3)", 9.0),
        ("=GCD(12,18)", 6.0),
        ("=LCM(4,6)", 12.0),
    ],
)
def test_math_functions(formula: str, expected: float) -> None:
    assert_close(evaluate(formula), expected)


@pytest.mark.parametrize(
    ("formula", "error"),
    [
        ("=SQRT(-1)", CellError.NUM),
        ("=POWER(-8,1/3)", CellError.NUM),
        ("=POWER(0,-1)", CellError.DIV0),
        ("=POWER(0,0)", CellError.NUM),
        ("=MOD(1,0)", CellError.DIV0),
        ("=1/0", CellError.DIV0),
        ("=0/0", CellError.DIV0),
    ],
)
def test_math_errors(formula: str, error: CellError) -> None:
    assert evaluate(formula) is error
