"""用 description/ 下的真实样例数据校验导入结果。"""

from __future__ import annotations

from decimal import Decimal

from cashflow.db import connect
from cashflow.importer import (
    INVOICE_KIND,
    ORDERS_KIND,
    TRANSACTIONS_KIND,
    import_file,
)
from cashflow.repository import save_seller

from .conftest import INVOICE_FILE, ORDERS_FILE, TRANSACTIONS_FILE, samples_available

pytestmark = samples_available


def _import(app, kind, path):
    connection = connect(app.config["DB_PATH"])
    try:
        return import_file(connection, kind, path)
    finally:
        connection.close()


def _query(app, sql, *params):
    connection = connect(app.config["DB_PATH"])
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _import_all(app, participants=False):
    if participants:
        connection = connect(app.config["DB_PATH"])
        try:
            save_seller(connection, "李楚吟", r"^.* (李楚吟)$", True, 10)
            save_seller(connection, "张三", r"^.* (张三)$", True, 11)
            save_seller(connection, "王五", r"^.* (王五)$", True, 12)
            connection.commit()
        finally:
            connection.close()
    results = {}
    for kind, path in (
        (ORDERS_KIND, ORDERS_FILE),
        (TRANSACTIONS_KIND, TRANSACTIONS_FILE),
        (INVOICE_KIND, INVOICE_FILE),
    ):
        results[kind] = _import(app, kind, path)
    return results


# --------------------------------------------------------------------------- #
# 订单表
# --------------------------------------------------------------------------- #
def test_orders_import_counts(app):
    result = _import(app, ORDERS_KIND, ORDERS_FILE)
    assert result.inserted_items == 311
    assert result.inserted_cashflows == 622  # 每个 item 一条成交价 + 一条运费
    assert result.failed == 0
    # 文件尾部的「62 笔已下载记录」「卖家用户名 : lcy-228」等统计行不会被当成数据
    assert _query(app, "SELECT COUNT(*) n FROM ebay_item WHERE item_id IN ('62', '')")[0]["n"] == 0


def test_orders_multiple_item_order_allocation(app):
    """guide 的示例订单 27-14089-26755：X 分配与 reminder。"""
    _import(app, ORDERS_KIND, ORDERS_FILE)
    rows = _query(
        app,
        "SELECT * FROM ebay_item WHERE order_id = '27-14089-26755' ORDER BY order_seq",
    )
    assert len(rows) == 9
    first = rows[0]
    assert first["item_id"] == "168058590540"
    assert first["lot"] == 1
    assert first["item_price"] == "1.00"
    assert first["order_shipping"] == "15.50"
    assert first["base_shipping"] == "9.99"
    assert first["allocated_shipping"] == "0.96"
    assert first["shipping_reminder"] == "(9.99 / 9) * 0.862"

    second = rows[1]
    assert second["allocated_shipping"] == "1.82"
    assert second["shipping_reminder"] == "(9.99 / 9 + 1) * 0.862"

    # 最后一条取残值，运费之和严格等于实收 15.50
    total = sum((Decimal(row["allocated_shipping"]) for row in rows), Decimal("0"))
    assert total == Decimal("15.50")
    assert rows[-1]["allocated_shipping"] == "1.80"


def test_orders_payment_date_comes_from_order_level_row(app):
    """多物品订单的付款日期只写在订单级汇总行上，item 行必须继承。"""
    _import(app, ORDERS_KIND, ORDERS_FILE)
    rows = _query(app, "SELECT DISTINCT payment_date FROM ebay_item WHERE order_id='27-14089-26755'")
    assert [row["payment_date"] for row in rows] == [20260117]


def test_orders_item_without_tracking_uses_high_base_shipping(app):
    _import(app, ORDERS_KIND, ORDERS_FILE)
    rows = _query(
        app,
        "SELECT base_shipping, allocated_shipping, payment_date FROM ebay_item WHERE item_id='168063555851'",
    )
    assert rows[0]["base_shipping"] == "35.99"
    assert rows[0]["allocated_shipping"] == "0.00"  # 该订单实收运费为 0
    assert rows[0]["payment_date"] == 20260115  # 付款日期缺失时退回出售日期


# --------------------------------------------------------------------------- #
# 交易报告
# --------------------------------------------------------------------------- #
def test_transactions_guide_example_is_balanced(app):
    """guide：item 级 5 笔现金流汇总后应等于订单净额 24.35。"""
    _import(app, ORDERS_KIND, ORDERS_FILE)
    _import(app, TRANSACTIONS_KIND, TRANSACTIONS_FILE)

    rows = _query(
        app,
        "SELECT cashflow_type, amount FROM ebay_item_cashflow WHERE order_id='27-14089-26755'",
    )
    totals = {}
    for row in rows:
        totals[row["cashflow_type"]] = totals.get(row["cashflow_type"], Decimal("0")) + Decimal(row["amount"])

    assert totals["成交价"] == Decimal("13.41")
    assert totals["运费"] == Decimal("15.50")
    assert totals["成交费 — 固定"] == Decimal("-0.40")
    assert totals["成交费"] == Decimal("-3.87")
    assert totals["跨国交易费"] == Decimal("-0.29")
    assert sum(totals.values()) == Decimal("24.35")


def test_transactions_fixed_fee_reminder_and_shipping_source(app):
    _import(app, ORDERS_KIND, ORDERS_FILE)
    _import(app, TRANSACTIONS_KIND, TRANSACTIONS_FILE)
    row = _query(
        app,
        "SELECT amount, reminder FROM ebay_item_cashflow"
        " WHERE cashflow_id='EBAY-TAX-TRADEFIX-168058590540'",
    )[0]
    # Y 用我们按 lot 算出的 X（0.96），而不是交易报告自带的分摊运费（1.15）
    assert row["reminder"] == "(1+0.96)/(13.41+15.50) * 0.4"
    assert row["amount"] == "-0.03"


def test_transactions_item_level_fees(app):
    _import(app, ORDERS_KIND, ORDERS_FILE)
    _import(app, TRANSACTIONS_KIND, TRANSACTIONS_FILE)

    trade = _query(
        app, "SELECT amount, cashflow_source FROM ebay_item_cashflow WHERE cashflow_id='EBAY-TAX-TRADE-168058590540'"
    )[0]
    assert trade["amount"] == "-0.29"
    assert trade["cashflow_source"] == "ebay费用"

    inter = _query(
        app, "SELECT amount FROM ebay_item_cashflow WHERE cashflow_id='EBAY-TAX-INTER-168058590540'"
    )[0]
    assert inter["amount"] == "-0.02"


def test_insertion_fee_uses_payout_date(app):
    """guide：168066871033 的刊登费 -0.25 记 20260109，返还 +0.25 记 20260116。"""
    _import(app, TRANSACTIONS_KIND, TRANSACTIONS_FILE)
    rows = _query(
        app,
        "SELECT cashflow_id, amount, cashflow_date, cashflow_source, cashflow_type"
        " FROM ebay_item_cashflow WHERE item_id='168066871033'"
        " AND cashflow_type='刊登费' ORDER BY cashflow_date",
    )
    assert [row["cashflow_id"] for row in rows] == [
        "EBAY-TAX-PUB-168066871033",
        "EBAY-TAX-PUBRETURN-168066871033",
    ]
    assert [row["cashflow_date"] for row in rows] == [20260109, 20260116]
    assert [row["amount"] for row in rows] == ["-0.25", "0.25"]
    assert rows[0]["cashflow_source"] == "ebay其他费用"


def test_store_subscription_is_not_imported_as_insertion_fee(app):
    """Store 订阅费在交易报告里也要跳过，否则会与税费账单的会员费重复。"""
    _import(app, TRANSACTIONS_KIND, TRANSACTIONS_FILE)
    rows = _query(
        app,
        "SELECT COUNT(*) n FROM ebay_item_cashflow WHERE amount='-21.95' AND cashflow_type='刊登费'",
    )
    assert rows[0]["n"] == 0


def test_payout_fee_split_per_head(app):
    _import_all(app, participants=True)
    rows = _query(
        app,
        "SELECT cashflow_id, item_id, amount, reminder FROM ebay_item_cashflow"
        " WHERE cashflow_type='发款费' AND cashflow_date=20260117 ORDER BY cashflow_id",
    )
    assert len(rows) == 3
    assert {row["item_id"] for row in rows} == {
        "ebay账户-李楚吟", "ebay账户-张三", "ebay账户-王五"
    }
    assert all(row["amount"] == "-1.97" for row in rows)
    assert rows[0]["reminder"] == "银行参考编号 MZBIL0TEWF5T66I  5.91 / 3"
    assert sum(Decimal(row["amount"]) for row in rows) == Decimal("-5.91")


def test_payout_without_participants_reports_issue(app):
    result = _import(app, TRANSACTIONS_KIND, TRANSACTIONS_FILE)
    assert result.failed > 0
    assert any("均摊" in issue.reason for issue in result.issues)


def test_refund_single_item_matches_guide(app):
    """guide：退款编号 5180906651 对应 item 168063599242。"""
    _import(app, ORDERS_KIND, ORDERS_FILE)
    _import(app, TRANSACTIONS_KIND, TRANSACTIONS_FILE)
    rows = _query(
        app,
        "SELECT * FROM ebay_item_cashflow WHERE cashflow_id='EBAY-REFUND-5180906651'",
    )
    assert len(rows) == 1
    assert rows[0]["item_id"] == "168063599242"
    assert rows[0]["amount"] == "-6.91"
    assert rows[0]["cashflow_source"] == "ebay退款"
    assert rows[0]["reminder"] == "退款编号 5180906651"
    assert rows[0]["cashflow_date"] == 20260116


def test_refund_multi_item_is_split_and_keeps_ids_unique(app):
    _import(app, ORDERS_KIND, ORDERS_FILE)
    _import(app, TRANSACTIONS_KIND, TRANSACTIONS_FILE)
    rows = _query(
        app,
        "SELECT * FROM ebay_item_cashflow WHERE reminder='退款编号 5180900094'",
    )
    assert len(rows) == 2
    assert len({row["cashflow_id"] for row in rows}) == 2
    assert sum(Decimal(row["amount"]) for row in rows) == Decimal("-6.88")


def test_refund_of_unknown_order_is_reported_not_imported(app):
    """订单明细查不到时导入失败并提示人工处理（guide 的边界情况）。"""
    _import(app, ORDERS_KIND, ORDERS_FILE)
    result = _import(app, TRANSACTIONS_KIND, TRANSACTIONS_FILE)
    assert any("5179667382" in issue.reference for issue in result.issues)
    rows = _query(app, "SELECT COUNT(*) n FROM ebay_item_cashflow WHERE reminder LIKE '%5179667382%'")
    assert rows[0]["n"] == 0


# --------------------------------------------------------------------------- #
# 税费账单
# --------------------------------------------------------------------------- #
def test_invoice_only_imports_membership_fee(app):
    _import_all(app, participants=True)
    rows = _query(
        app,
        "SELECT cashflow_id, item_id, amount, cashflow_date, reminder, cashflow_source"
        " FROM ebay_item_cashflow WHERE cashflow_type='会员费' ORDER BY cashflow_id",
    )
    assert len(rows) == 3
    assert all(row["cashflow_source"] == "ebay账户" for row in rows)
    assert all(row["cashflow_date"] == 20260101 for row in rows)
    assert rows[0]["reminder"] == "01 月 01 日 - 01 月 31 日  21.95 / 3"
    assert sum(Decimal(row["amount"]) for row in rows) == Decimal("-21.95")

    # 账单里与交易报告重复的四类费用不应入库：刊登费只应来自交易报告的 772 行
    rows = _query(
        app,
        "SELECT COUNT(*) n, COUNT(DISTINCT item_id) d FROM ebay_item_cashflow"
        " WHERE cashflow_type='刊登费'",
    )
    assert (rows[0]["n"], rows[0]["d"]) == (772, 642)


# --------------------------------------------------------------------------- #
# 边界：只导入后两类文件
# --------------------------------------------------------------------------- #
def test_transactions_can_be_imported_without_orders_report(app):
    """guide 的边界情况：订单表缺失时，交易报告仍应能正常导入。"""
    result = _import(app, TRANSACTIONS_KIND, TRANSACTIONS_FILE)
    assert result.inserted_cashflows > 0
    row = _query(
        app,
        "SELECT amount, reminder FROM ebay_item_cashflow WHERE cashflow_id='EBAY-TAX-TRADEFIX-168058590540'",
    )[0]
    # 查不到 ebay_item，退回交易报告自带的运费与处理费 1.15 作为权重基数
    assert row["reminder"] == "(1+1.15)/(13.41+15.50) * 0.4"


# --------------------------------------------------------------------------- #
# 幂等
# --------------------------------------------------------------------------- #
def test_reimport_skips_everything(app):
    _import_all(app, participants=True)
    before = _query(
        app, "SELECT (SELECT COUNT(*) FROM ebay_item) a, (SELECT COUNT(*) FROM ebay_item_cashflow) b"
    )[0]
    results = _import_all(app, participants=True)
    after = _query(
        app, "SELECT (SELECT COUNT(*) FROM ebay_item) a, (SELECT COUNT(*) FROM ebay_item_cashflow) b"
    )[0]
    assert (before["a"], before["b"]) == (after["a"], after["b"])
    assert results[ORDERS_KIND].inserted_items == 0
    assert results[ORDERS_KIND].skipped_items == 311
    assert results[TRANSACTIONS_KIND].inserted_cashflows == 0
    assert results[INVOICE_KIND].inserted_cashflows == 0


def test_all_cashflow_amounts_are_exact_two_decimals(app):
    """金额一律以十进制字符串入库，不出现浮点误差。"""
    _import_all(app, participants=True)
    rows = _query(app, "SELECT cashflow_id, amount FROM ebay_item_cashflow")
    for row in rows:
        assert Decimal(row["amount"]) == Decimal(row["amount"]).quantize(Decimal("0.01"))
        assert "E" not in row["amount"].upper()


def test_placeholder_order_id_is_stored_as_null(app):
    """交易报告里刊登费行的订单编号是 '--'，不能当成真实订单号存起来。"""
    _import(app, TRANSACTIONS_KIND, TRANSACTIONS_FILE)
    rows = _query(
        app,
        "SELECT order_id FROM ebay_item_cashflow"
        " WHERE cashflow_id='EBAY-TAX-PUB-168122089854'",
    )
    assert rows[0]["order_id"] is None
