"""分摊算法测试（对照 guide 里的数字）。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cashflow.allocations import (
    BASE_SHIPPING_HIGH,
    BASE_SHIPPING_LOW,
    allocate_order_fixed_fee,
    allocate_shipping,
    base_shipping,
    lot_surcharge,
    parse_lot,
    split_by_weight,
    split_equal,
    split_per_head,
)


# --------------------------------------------------------------------------- #
# lot
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "title,expected",
    [
        ("Vince Carter/Kevin Garnett Lot(3) 2025-26 Topps Flagship The Daily Dribble", 3),
        ("Scottie Barnes Lot2 2021-22 Panini Chronicles Marquee", 2),
        ("Liam McNeeley/Will Riley Lot(6) 2025-26 Topps Flagship", 6),
        ("Austin Reaves Lot3 2021-22 Panini Mosaic Base Rookies Green RC #241", 3),
        ("Jalen Duren 2022-23 Donruss Elite Base Rookies Asia Hyper Red & Green RC #228", 1),
        ("", 1),
        (None, 1),
    ],
)
def test_parse_lot(title, expected):
    assert parse_lot(title) == expected


@pytest.mark.parametrize(
    "lot,expected",
    [(1, Decimal("1")), (5, Decimal("1")), (6, Decimal("2")), (10, Decimal("2")),
     (11, Decimal("3")), (40, Decimal("3"))],
)
def test_lot_surcharge(lot, expected):
    assert lot_surcharge(lot) == expected


# --------------------------------------------------------------------------- #
# 基础运费
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "track,expected",
    [
        ("ES10031058475954X0101242300N", BASE_SHIPPING_LOW),  # ES 开头 28 位
        ("VR800704956YP", BASE_SHIPPING_LOW),                 # XX123456789XX
        ("YE180059844CN", BASE_SHIPPING_LOW),
        ("UK539678009YP", BASE_SHIPPING_LOW),
        ("", BASE_SHIPPING_HIGH),
        (None, BASE_SHIPPING_HIGH),
        ("SF1234567890123", BASE_SHIPPING_HIGH),
    ],
)
def test_base_shipping(track, expected):
    assert base_shipping(track) == expected


# --------------------------------------------------------------------------- #
# X：按 lot 分配运费（guide 的示例订单）
# --------------------------------------------------------------------------- #
def test_allocate_shipping_matches_guide_example():
    """guide：9 个 item 都是 lot=1，实收 15.5，应收 9.99+8=17.99，系数 0.862。"""
    lots = [1] * 9
    results = allocate_shipping(lots, Decimal("15.50"), "ES10031058475954X0101242300N")

    assert results[0].reminder == "(9.99 / 9) * 0.862"
    assert results[1].reminder == "(9.99 / 9 + 1) * 0.862"
    assert results[0].amount == Decimal("0.96")
    assert results[1].amount == Decimal("1.82")
    # 最后一个取残值，合计必须严格等于实收运费
    assert sum(item.amount for item in results) == Decimal("15.50")
    assert results[-1].amount == Decimal("1.80")


def test_allocate_shipping_second_guide_example_with_lot6():
    """guide：若第 8 个 item 的 lot=6，则附加运费为 2，应收 18.99，系数 0.816。"""
    lots = [1, 1, 1, 1, 1, 1, 1, 6, 1]
    results = allocate_shipping(lots, Decimal("15.50"), "ES10031058475954X0101242300N")

    assert results[0].reminder == "(9.99 / 9) * 0.816"
    assert results[1].reminder == "(9.99 / 9 + 1) * 0.816"
    assert results[7].reminder == "(9.99 / 9 + 2) * 0.816"
    assert sum(item.amount for item in results) == Decimal("15.50")


def test_allocate_shipping_single_item_takes_all():
    results = allocate_shipping([1], Decimal("8.99"), "ES10031058475954X0101242300N")
    assert len(results) == 1
    assert results[0].amount == Decimal("8.99")
    assert results[0].reminder == ""


def test_allocate_shipping_high_base_shipping():
    results = allocate_shipping([1, 1], Decimal("10.00"), "")
    assert results[0].reminder.startswith("(35.99 / 2)")
    assert sum(item.amount for item in results) == Decimal("10.00")


# --------------------------------------------------------------------------- #
# Y：按收入分配固定成交费（guide 的示例）
# --------------------------------------------------------------------------- #
def test_allocate_order_fixed_fee_matches_guide_example():
    """guide：(1+X)/(13.41+15.50) * 0.4，X 是该 item 摊到的运费。"""
    revenues = [
        (Decimal("1.00"), Decimal("0.96")),
        (Decimal("1.00"), Decimal("1.82")),
    ]
    results = allocate_order_fixed_fee(
        revenues,
        Decimal("-0.40"),
        Decimal("13.41"),
        Decimal("15.50"),
    )
    assert results[0].reminder == "(1+0.96)/(13.41+15.50) * 0.4"
    assert sum(item.amount for item in results) == Decimal("-0.40")


def test_allocate_order_fixed_fee_sums_to_total():
    revenues = [
        (Decimal("1.00"), Decimal("0.96")),
        (Decimal("1.25"), Decimal("1.82")),
        (Decimal("4.35"), Decimal("1.82")),
    ]
    results = allocate_order_fixed_fee(
        revenues, Decimal("-0.40"), Decimal("6.60"), Decimal("4.60")
    )
    assert sum(item.amount for item in results) == Decimal("-0.40")


# --------------------------------------------------------------------------- #
# W：按人头均摊
# --------------------------------------------------------------------------- #
def test_split_equal_residual_goes_to_last():
    parts = split_equal(Decimal("15.39"), 3)
    assert parts == [Decimal("5.13"), Decimal("5.13"), Decimal("5.13")]

    parts = split_equal(Decimal("10.00"), 3)
    assert parts == [Decimal("3.33"), Decimal("3.33"), Decimal("3.34")]
    assert sum(parts) == Decimal("10.00")


def test_split_per_head_reminder_format():
    rows = split_per_head(
        Decimal("-5.91"), ["李楚吟", "张三", "王五"], "银行参考编号 MZBIL0TEWF5T66I"
    )
    assert [name for name, _amount, _reminder in rows] == ["李楚吟", "张三", "王五"]
    assert all(amount == Decimal("-1.97") for _n, amount, _r in rows)
    assert rows[0][2] == "银行参考编号 MZBIL0TEWF5T66I  5.91 / 3"
    assert sum(amount for _n, amount, _r in rows) == Decimal("-5.91")


def test_split_per_head_without_participants():
    assert split_per_head(Decimal("-5.91"), []) == []


def test_split_by_weight_residual():
    parts = split_by_weight(
        Decimal("-6.88"), [Decimal("2.23"), Decimal("5.80")]
    )
    assert sum(parts) == Decimal("-6.88")
