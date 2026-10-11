"""导入「报告 - 下载 - 所有订单」：写入 ebay_item，并派生成交价/运费两笔现金流。

关于文件结构（实测）：
- 多物品订单会先有一行「订单级汇总行」：物品编号为空，数量=物品数，
  成交价=订单总价，运费与处理费=订单实收运费，付款日期只出现在这一行；
  其后每个 item 一行（有追踪号码，成交价是单件价，运费与付款日期为空）。
- 单物品订单只有一行，同时带订单级与物品级数据。
"""

from __future__ import annotations

import sqlite3
from typing import Dict, List

from ..allocations import (
    build_trade_cashflow_id,
    build_transport_cashflow_id,
    base_shipping,
    allocate_shipping,
    parse_lot,
)
from ..money import money, parse_date, to_db
from ..repository import SellerMatcher, insert_cashflow, insert_item
from .base import Columns, ImportResult, Table, load_table

FILE_KIND = "orders"

HEADER_KEYS = ("销售记录编号", "物品编号")

ALIASES: Dict[str, tuple] = {
    "item_id": ("物品编号", "Item ID", "Item number"),
    "order_id": ("订单编号", "Order number", "Order ID"),
    "record_id": ("销售记录编号", "Sales record number"),
    "buyer_username": ("买家用户名", "Buyer username"),
    "buyer_country": ("买家所在国家/地区", "Buyer country"),
    "item_name": ("物品标题", "Item title"),
    "track_id": ("追踪号码", "Tracking number"),
    "item_price": ("成交价", "Sold for", "Item subtotal"),
    "order_shipping": ("运费与处理费", "Shipping and handling"),
    "payment_date": ("付款日期", "Paid on date"),
    "sale_date": ("出售日期", "Sold on date"),
}


def _group_key(order_id: str, record_id: str) -> str:
    # 实测存在订单编号为空的行（历史数据），此时用销售记录编号区分不同订单
    if order_id:
        return f"order:{order_id}"
    return f"record:{record_id}"


def import_orders_file(
    conn: sqlite3.Connection, path: str, result: ImportResult, source_file: str
) -> None:
    table: Table = load_table(path, HEADER_KEYS)
    cols = Columns(table, ALIASES, required=("item_id", "order_id", "item_name"))
    matcher = SellerMatcher(conn)
    for error in matcher.errors:
        result.note(error)

    # 按订单分组，保持文件内的先后顺序（「第一笔」依赖表格顺序）
    groups: "Dict[str, List[tuple]]" = {}
    for position, row in enumerate(table.rows, start=1):
        item_id = cols.text(row, "item_id")
        order_id = cols.text(row, "order_id")
        record_id = cols.text(row, "record_id")
        if not item_id and not order_id and not record_id:
            continue  # 尾部统计行之类
        key = _group_key(order_id, record_id)
        groups.setdefault(key, []).append((position, row))

    for key, entries in groups.items():
        order_level = [entry for entry in entries if not cols.text(entry[1], "item_id")]
        item_entries = [entry for entry in entries if cols.text(entry[1], "item_id")]
        if not item_entries:
            result.note(f"订单分组 {key} 没有物品明细行，已跳过（共 {len(entries)} 行）")
            continue

        def pick(field: str) -> str:
            """订单级字段优先取汇总行，其次取物品行。"""
            for _position, row in order_level + item_entries:
                value = cols.text(row, field)
                if value:
                    return value
            return ""

        order_shipping = cols.text(order_level[0][1], "order_shipping") if order_level else ""
        if not order_shipping:
            order_shipping = pick("order_shipping")
        shipping_amount = money(order_shipping)

        payment_date = parse_date(pick("payment_date")) or parse_date(pick("sale_date"))
        if not payment_date:
            result.note(
                f"订单 {pick('order_id') or key} 的付款日期与出售日期都为空，现金流日期记为 0"
            )
            payment_date = 0

        track_id = pick("track_id")
        base = base_shipping(track_id)
        names = [cols.text(row, "item_name") for _position, row in item_entries]
        lots = [parse_lot(name) for name in names]
        shipping_parts = allocate_shipping(lots, shipping_amount, track_id, base)

        for seq, ((position, row), lot, shipping_part) in enumerate(
            zip(item_entries, lots, shipping_parts)
        ):
            item_id = cols.text(row, "item_id")
            order_id = cols.text(row, "order_id")
            price = money(cols.text(row, "item_price"))
            seller_name = matcher.match(cols.text(row, "item_name"))

            payload = {
                "item_id": item_id,
                "order_id": order_id,
                "record_id": cols.text(row, "record_id"),
                "buyer_username": cols.text(row, "buyer_username"),
                "buyer_country": cols.text(row, "buyer_country"),
                "item_name": cols.text(row, "item_name"),
                "seller_name": seller_name,
                "seller_manual": 0,
                "track_id": track_id,
                "lot": lot,
                "item_price": to_db(price),
                "order_shipping": to_db(shipping_amount),
                "base_shipping": to_db(base),
                "allocated_shipping": to_db(shipping_part.amount),
                "shipping_reminder": shipping_part.reminder,
                "payment_date": payment_date,
                "order_seq": seq,
                "source_file": source_file,
            }
            if insert_item(conn, payload):
                result.inserted_items += 1
            else:
                result.skipped_items += 1

            cashflows = [
                {
                    "cashflow_id": build_trade_cashflow_id(item_id),
                    "item_id": item_id,
                    "order_id": order_id,
                    "cashflow_source": "ebay费用",
                    "cashflow_type": "成交价",
                    "amount": price,
                    "cashflow_date": payment_date,
                    "reminder": "",
                    "source_file": source_file,
                },
                {
                    "cashflow_id": build_transport_cashflow_id(item_id),
                    "item_id": item_id,
                    "order_id": order_id,
                    "cashflow_source": "ebay费用",
                    "cashflow_type": "运费",
                    "amount": shipping_part.amount,
                    "cashflow_date": payment_date,
                    "reminder": shipping_part.reminder,
                    "source_file": source_file,
                },
            ]
            for cashflow in cashflows:
                if insert_cashflow(conn, cashflow):
                    result.inserted_cashflows += 1
                else:
                    result.skipped_cashflows += 1
