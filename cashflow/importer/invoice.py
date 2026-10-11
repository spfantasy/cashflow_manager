"""导入「付款 - 税费账单」：只取 費用組別=訂用服務及一次性費用 作为会员费。

实测该账单里还有 刊登費/成交費/跨國交易費/銀行提現費 四类，它们与交易报告重复
（銀行提現費与「发放款项」的發款編號逐条一致），因此按 guide 只取订阅费一类，
避免重复记账。

账单里费用以正数显示（21.95），按 guide 记为负数 -21.95，并在参与会员费均摊的
卖家之间等分。
"""

from __future__ import annotations

import sqlite3
from typing import Dict

from ..allocations import (
    CASHFLOW_SOURCE_EBAY_ACCOUNT,
    build_account_item_id,
    build_membership_cashflow_id,
    split_per_head,
)
from ..money import money, parse_date
from ..repository import insert_cashflow_checked, participants
from .base import Columns, ImportResult, Table, load_table

FILE_KIND = "invoice"

HEADER_KEYS = ("費用組別", "淨額")

MEMBERSHIP_GROUPS = ("訂用服務及一次性費用", "订用服务及一次性费用")

ALIASES: Dict[str, tuple] = {
    "date": ("日期", "Date"),
    "description": ("說明", "说明", "Description"),
    "remark": ("備註", "备注", "Note"),
    "order_id": ("訂單編號", "订单编号", "Order number"),
    "item_id": ("物品編號", "物品编号", "Item number"),
    "fee_group": ("費用組別", "费用组别", "Fee group"),
    "fee_type": ("費用類型", "费用类型", "Fee type"),
    "currency": ("貨幣", "货币", "Currency"),
    "net": ("淨額", "净额", "Net amount"),
    "total": ("總金額", "总金额", "Total"),
}


def import_invoice_file(
    conn: sqlite3.Connection, path: str, result: ImportResult, source_file: str
) -> None:
    table: Table = load_table(path, HEADER_KEYS)
    cols = Columns(table, ALIASES, required=("fee_group", "net", "date"))

    names = participants(conn)
    ignored_groups: Dict[str, int] = {}

    for row in table.rows:
        group = cols.text(row, "fee_group")
        if group not in MEMBERSHIP_GROUPS:
            ignored_groups[group] = ignored_groups.get(group, 0) + 1
            continue

        net = money(cols.raw(row, "net"))
        # 账单里费用是正数，现金流记负数
        total = -net
        cashflow_date = parse_date(cols.raw(row, "date")) or 0
        if not names:
            result.add_issue(
                "没有配置「参与会员费均摊」的用户，会员费无法均摊",
                reference=f"{group} {net}",
            )
            continue

        remark = cols.text(row, "remark")
        fee_type = cols.text(row, "fee_type")
        note = remark or fee_type
        for seller_name, amount, reminder in split_per_head(total, names, note):
            status = insert_cashflow_checked(
                conn,
                {
                    "cashflow_id": build_membership_cashflow_id(cashflow_date, seller_name),
                    "item_id": build_account_item_id(seller_name),
                    "order_id": "",
                    "cashflow_source": CASHFLOW_SOURCE_EBAY_ACCOUNT,
                    "cashflow_type": "会员费",
                    "amount": amount,
                    "cashflow_date": cashflow_date,
                    "reminder": reminder,
                    "source_file": source_file,
                },
            )
            if status == "inserted":
                result.inserted_cashflows += 1
            elif status == "duplicate":
                result.skipped_cashflows += 1
            else:
                result.add_issue(
                    f"{cashflow_date} 已存在金额不同的会员费现金流，同一天多笔账单无法自动分摊，请录入手工账",
                    reference=f"{group} {net}",
                )

    for group, count in ignored_groups.items():
        if group:
            result.note(f"費用組別「{group}」共 {count} 行按约定忽略（与交易报告重复）")
        else:
            result.note(f"有 {count} 行缺少費用組別，已忽略")
