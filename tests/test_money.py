"""金额与日期解析测试。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cashflow.money import (
    fmt2,
    fmt_date,
    parse_date,
    parse_date_input,
    parse_money,
    q2,
    to_db,
    trim,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("US $15.50", Decimal("15.50")),
        ("US $1,234.56", Decimal("1234.56")),
        ("-0.29", Decimal("-0.29")),
        ("--", None),
        ("", None),
        (None, None),
        (Decimal("0.25"), Decimal("0.25")),
        ("21.95", Decimal("21.95")),
    ],
)
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected


def test_money_keeps_two_decimals_in_db():
    assert to_db(Decimal("15.5")) == "15.50"
    assert to_db(Decimal("-0.4")) == "-0.40"
    assert to_db("US $1.00") == "1.00"


def test_rounding_is_half_up_not_bankers():
    # float / round() 在这里会给出 0.01 或 0.02 的不确定结果，Decimal 必须稳定
    assert q2(Decimal("0.005")) == Decimal("0.01")
    assert q2(Decimal("0.015")) == Decimal("0.02")
    assert q2(Decimal("0.025")) == Decimal("0.03")


def test_trim_and_fmt2():
    assert trim(Decimal("1.00")) == "1"
    assert trim(Decimal("0.40")) == "0.4"
    assert trim(Decimal("15.50")) == "15.5"
    assert trim(Decimal("-0.40")) == "-0.4"
    assert fmt2(Decimal("15.5")) == "15.50"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Jan-17-26", 20260117),
        ("17-Jan-26", 20260117),
        ("2026-01-01 08:29:00 PDT", 20260101),
        ("2026-01-01", 20260101),
        ("20260117", 20260117),
        ("01/17/2026", 20260117),
        ("--", None),
        ("", None),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_parse_date_input_accepts_html_date_field():
    assert parse_date_input("2026-01-17") == 20260117
    assert parse_date_input("20260117") == 20260117
    assert parse_date_input("") is None


def test_fmt_date():
    assert fmt_date(20260117) == "2026-01-17"
    assert fmt_date(0) == ""
    assert fmt_date(None) == ""
