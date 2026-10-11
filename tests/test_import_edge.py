"""不依赖 description/ 样例数据的导入测试（含 xlsx 与异常处理）。"""

from __future__ import annotations

import csv

from decimal import Decimal

import pytest
from openpyxl import Workbook

from cashflow.db import connect
from cashflow.importer import (
    INVOICE_KIND,
    ORDERS_KIND,
    TRANSACTIONS_KIND,
    import_file,
)
from cashflow.repository import save_seller

TRANSACTION_HEADER = [
    "交易创建日期", "类型", "订单编号", "净额", "发款日期", "发款编号",
    "参考编号", "描述", "物品编号", "物品小计", "运费与处理费",
    "成交费 — 因品类而异", "跨国交易费用", "成交费 — 固定",
]


def _write_csv(path, header, rows, encoding="utf-8-sig"):
    with open(path, "w", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return str(path)


def _connect(app):
    return connect(app.config["DB_PATH"])


def test_same_day_payouts_with_different_fees_are_reported_not_dropped(app, tmp_path):
    """cashflow_id 是「日期-用户」，同一天多笔金额不同的发款必须报冲突而不是静默丢账。"""
    connection = _connect(app)
    try:
        save_seller(connection, "李楚吟", "", True, 10)
        connection.commit()
    finally:
        connection.close()

    rows = [
        ["17-Jan-26", "发放款项", "--", "-738.33", "--", "7289004921",
         "银行参考编号 AAA", "预定发款。已扣除发款费 $5.91，$732.42 已发放。", ""],
        ["17-Jan-26", "发放款项", "--", "-100.00", "--", "7289004999",
         "银行参考编号 BBB", "预定发款。已扣除发款费 $1.00，$99.00 已发放。", ""],
    ]
    path = _write_csv(tmp_path / "txn.csv", TRANSACTION_HEADER, rows)

    connection = _connect(app)
    try:
        result = import_file(connection, TRANSACTIONS_KIND, path)
        stored = connection.execute(
            "SELECT cashflow_id, amount FROM ebay_item_cashflow"
        ).fetchall()
    finally:
        connection.close()

    assert result.inserted_cashflows == 1
    assert len(stored) == 1
    assert stored[0]["amount"] == "-5.91"
    assert result.failed == 1
    assert "同一天多笔发款" in result.issues[0].reason


def test_reimport_same_payout_is_a_plain_skip(app, tmp_path):
    connection = _connect(app)
    try:
        save_seller(connection, "李楚吟", "", True, 10)
        connection.commit()
    finally:
        connection.close()

    rows = [
        ["17-Jan-26", "发放款项", "--", "-738.33", "--", "7289004921",
         "银行参考编号 AAA", "预定发款。已扣除发款费 $5.91，$732.42 已发放。", ""],
    ]
    path = _write_csv(tmp_path / "txn.csv", TRANSACTION_HEADER, rows)

    connection = _connect(app)
    try:
        first = import_file(connection, TRANSACTIONS_KIND, path)
        second = import_file(connection, TRANSACTIONS_KIND, path)
    finally:
        connection.close()

    assert first.inserted_cashflows == 1
    assert second.inserted_cashflows == 0
    assert second.skipped_cashflows == 1
    assert second.failed == 0


def test_orders_xlsx_is_supported(app, tmp_path):
    """guide 说的是 Excel 文件，所以 .xlsx 必须能直接导。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["报告", "", ""])
    sheet.append(["销售记录编号", "订单编号", "物品编号", "物品标题", "买家用户名",
                  "买家所在国家/地区", "成交价", "运费与处理费", "追踪号码", "付款日期", "出售日期"])
    sheet.append([100, "01-11111-11111", "168000000001", "Player Lot(3) Card", "buyer1",
                  "United States", "US $10.00", "US $8.99", "ES10031058475954X0101242300N",
                  "Jan-17-26", "Jan-15-26"])
    sheet.append([100, "01-11111-11111", "168000000002", "Other Card", "buyer1",
                  "United States", "US $5.00", "", "ES10031058475954X0101242300N",
                  "Jan-17-26", "Jan-15-26"])
    path = str(tmp_path / "orders.xlsx")
    workbook.save(path)

    connection = _connect(app)
    try:
        result = import_file(connection, ORDERS_KIND, path)
        items = connection.execute(
            "SELECT * FROM ebay_item ORDER BY order_seq"
        ).fetchall()
        cashflows = connection.execute(
            "SELECT COUNT(*) n FROM ebay_item_cashflow"
        ).fetchone()
    finally:
        connection.close()

    assert result.inserted_items == 2
    assert result.failed == 0
    assert cashflows["n"] == 4
    assert [item["lot"] for item in items] == [3, 1]
    # 实收运费 8.99 按 lot 摊：基础运费 9.99 / 2 起算
    total_shipping = sum(Decimal(item["allocated_shipping"]) for item in items)
    assert total_shipping == Decimal("8.99")
    assert items[0]["payment_date"] == 20260117
    assert items[0]["shipping_reminder"].startswith("(9.99 / 2)")


def test_gb18030_csv_is_supported(app, tmp_path):
    """Windows 中文 Excel 另存为 CSV 时常见 gb18030 编码。"""
    rows = [["17-Jan-26", "订单", "01-11111-11111", "8.99", "20-Jan-26", "", "",
             "", "168000000003", "10.00", "8.99", "-1.00", "-0.10", "-0.40"]]
    path = _write_csv(tmp_path / "txn.csv", TRANSACTION_HEADER, rows, encoding="gb18030")

    connection = _connect(app)
    try:
        result = import_file(connection, TRANSACTIONS_KIND, path)
        stored = connection.execute(
            "SELECT cashflow_id, amount FROM ebay_item_cashflow ORDER BY cashflow_id"
        ).fetchall()
    finally:
        connection.close()

    assert result.failed == 0
    assert [row["cashflow_id"] for row in stored] == [
        "EBAY-TAX-INTER-168000000003",
        "EBAY-TAX-TRADE-168000000003",
        "EBAY-TAX-TRADEFIX-168000000003",
    ]
    # 订单明细不存在时，用交易报告自带的运费 8.99 作为权重基数，全额摊给唯一 item
    assert [row["amount"] for row in stored] == ["-0.10", "-1.00", "-0.40"]


def test_missing_columns_raise_readable_error(app, tmp_path):
    path = _write_csv(tmp_path / "bad.csv", ["随便", "几列"], [["a", "b"]])
    connection = _connect(app)
    try:
        with pytest.raises(ValueError) as excinfo:
            import_file(connection, ORDERS_KIND, path)
    finally:
        connection.close()
    assert "没有找到预期的表头" in str(excinfo.value)


def test_unknown_kind_raises(app):
    connection = _connect(app)
    try:
        with pytest.raises(ValueError):
            import_file(connection, "unknown", "whatever.csv")
    finally:
        connection.close()


def test_invoice_xlsx_membership_split(app, tmp_path):
    connection = _connect(app)
    try:
        save_seller(connection, "甲", "", True, 10)
        save_seller(connection, "乙", "", True, 11)
        connection.commit()
    finally:
        connection.close()

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["賬單日期：2026-01-31"])
    sheet.append(["日期", "說明", "備註", "訂單編號", "物品編號", "費用組別",
                  "費用類型", "貨幣", "淨額"])
    sheet.append(["2026-01-01 08:29:00 PDT", "-", "01 月 01 日 - 01 月 31 日", "-", "-",
                  "訂用服務及一次性費用", "商店（一般）：訂用費", "USD", "21.95"])
    sheet.append(["2026-01-02 16:15:06 PDT", "-", "-", "-", "-",
                  "銀行提現費", "銀行提現費", "USD", "0.39"])
    path = str(tmp_path / "invoice.xlsx")
    workbook.save(path)

    connection = _connect(app)
    try:
        result = import_file(connection, INVOICE_KIND, path)
        rows = connection.execute(
            "SELECT cashflow_id, amount, reminder FROM ebay_item_cashflow ORDER BY cashflow_id"
        ).fetchall()
    finally:
        connection.close()

    assert result.inserted_cashflows == 2
    amounts = sorted(Decimal(row["amount"]) for row in rows)
    assert amounts == [Decimal("-10.98"), Decimal("-10.97")]
    assert sum(amounts) == Decimal("-21.95")
    assert all(row["reminder"] == "01 月 01 日 - 01 月 31 日  21.95 / 2" for row in rows)


def _refund_csv(tmp_path, order_id, net):
    rows = [["15-Jan-26", "退款", order_id, net, "16-Jan-26", "7287329841",
             "退款编号 5180906651", "", "--", "--", "--", "1.00", "0.08", "--"]]
    return _write_csv(tmp_path / "refund.csv", TRANSACTION_HEADER, rows)


def test_refund_multiple_sellers_is_rejected_for_manual_entry(app, tmp_path):
    """订单下物品属于多个卖家时，退款无法确定分摊逻辑，必须跳过并提示人工处理。"""
    from cashflow.repository import insert_item

    connection = _connect(app)
    try:
        insert_item(connection, {"item_id": "168000000011", "order_id": "04-14114-71411",
                                 "seller_name": "甲", "item_price": "10.00",
                                 "allocated_shipping": "1.00"})
        insert_item(connection, {"item_id": "168000000012", "order_id": "04-14114-71411",
                                 "seller_name": "乙", "item_price": "10.00",
                                 "allocated_shipping": "1.00"})
        connection.commit()
    finally:
        connection.close()

    connection = _connect(app)
    try:
        result = import_file(
            connection, TRANSACTIONS_KIND, _refund_csv(tmp_path, "04-14114-71411", "-6.91")
        )
        count = connection.execute(
            "SELECT COUNT(*) n FROM ebay_item_cashflow"
        ).fetchone()["n"]
    finally:
        connection.close()

    assert result.inserted_cashflows == 0
    assert count == 0
    assert result.failed == 1
    assert "涉及多个用户" in result.issues[0].reason


def test_refund_multiple_buyers_is_rejected_for_manual_entry(app, tmp_path):
    """同一卖家但多个买家时同样按 guide 拒绝，交人工处理。"""
    from cashflow.repository import insert_item

    connection = _connect(app)
    try:
        insert_item(connection, {"item_id": "168000000021", "order_id": "05-14114-71412",
                                 "seller_name": "甲", "buyer_username": "buyer1",
                                 "item_price": "10.00", "allocated_shipping": "1.00"})
        insert_item(connection, {"item_id": "168000000022", "order_id": "05-14114-71412",
                                 "seller_name": "甲", "buyer_username": "buyer2",
                                 "item_price": "10.00", "allocated_shipping": "1.00"})
        connection.commit()
    finally:
        connection.close()

    connection = _connect(app)
    try:
        result = import_file(
            connection, TRANSACTIONS_KIND, _refund_csv(tmp_path, "05-14114-71412", "-6.91")
        )
    finally:
        connection.close()

    assert result.inserted_cashflows == 0
    assert result.failed == 1
    assert "涉及多个用户" in result.issues[0].reason


def test_refund_single_seller_multi_item_is_split(app, tmp_path):
    from cashflow.repository import insert_item

    connection = _connect(app)
    try:
        insert_item(connection, {"item_id": "168000000031", "order_id": "06-14114-71413",
                                 "seller_name": "甲", "buyer_username": "buyer1",
                                 "item_price": "10.00", "allocated_shipping": "1.00"})
        insert_item(connection, {"item_id": "168000000032", "order_id": "06-14114-71413",
                                 "seller_name": "甲", "buyer_username": "buyer1",
                                 "item_price": "30.00", "allocated_shipping": "3.00"})
        connection.commit()
    finally:
        connection.close()

    connection = _connect(app)
    try:
        result = import_file(
            connection, TRANSACTIONS_KIND, _refund_csv(tmp_path, "06-14114-71413", "-6.91")
        )
        rows = connection.execute(
            "SELECT cashflow_id, item_id, amount, reminder FROM ebay_item_cashflow"
            " ORDER BY cashflow_id"
        ).fetchall()
    finally:
        connection.close()

    assert result.inserted_cashflows == 2
    assert len(rows) == 2
    # cashflow_id 追加 item_id 以保证主键唯一
    assert rows[0]["cashflow_id"] == "EBAY-REFUND-5180906651-168000000031"
    assert rows[1]["cashflow_id"] == "EBAY-REFUND-5180906651-168000000032"
    # 按收入权重 (10+1):(30+3) 分摊，合计等于净额
    assert sum(Decimal(row["amount"]) for row in rows) == Decimal("-6.91")
    assert Decimal(rows[0]["amount"]) > Decimal(rows[1]["amount"])
    assert all(row["reminder"] == "退款编号 5180906651" for row in rows)
