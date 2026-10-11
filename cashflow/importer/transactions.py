"""导入「付款 - 交易报告」：按类型拆成 ebay_item_cashflow。

类型处理（guide + 实测数据）：
- 订单      -> 成交费（成交费 — 因品类而异）、跨国交易费（跨国交易费用），
               以及按收入分摊的「成交费 — 固定」。物品编号为空的订单级汇总行跳过。
- 其他费用  -> 刊登费（描述=Insertion Fee）。负数记 EBAY-TAX-PUB，正数（返还）记
               EBAY-TAX-PUBRETURN。Store 订阅费在此跳过，会员费只从税费账单导入。
- 发放款项  -> 发款费，从描述「已扣除发款费 $X」解析金额，按人头均摊给参与会员费
               均摊的卖家。
- 退款      -> 订单级退款，按 Y 权重分摊到该订单的各个 item；只要出现多个卖家
               （或多个买家）就跳过并在导入结束后提示人工处理。
- 收费      -> 忽略（信用卡相关扣费）。
"""

from __future__ import annotations

import re
import sqlite3
from decimal import Decimal
from typing import Dict, List, Sequence

from ..allocations import (
    CASHFLOW_SOURCE_EBAY_ACCOUNT,
    CASHFLOW_SOURCE_EBAY_FEE,
    CASHFLOW_SOURCE_EBAY_OTHER_FEE,
    CASHFLOW_SOURCE_EBAY_REFUND,
    allocate_order_fixed_fee,
    build_account_item_id,
    build_pub_cashflow_id,
    build_pub_return_cashflow_id,
    build_tax_inter_cashflow_id,
    build_tax_trade_cashflow_id,
    build_tax_tradefix_cashflow_id,
    build_transaction_fee_cashflow_id,
    split_by_weight,
    split_per_head,
)
from ..money import ZERO, money, parse_date, parse_money
from ..repository import (
    get_item,
    insert_cashflow,
    insert_cashflow_checked,
    order_items,
    participants,
)
from .base import Columns, ImportResult, Table, load_table

FILE_KIND = "transactions"

HEADER_KEYS = ("交易创建日期", "类型")

ALIASES: Dict[str, tuple] = {
    "created_date": ("交易创建日期", "Transaction creation date"),
    "type": ("类型", "Type"),
    "order_id": ("订单编号", "Order number"),
    "legacy_order_id": ("旧订单编号", "Legacy order ID"),
    "buyer_username": ("买家用户名", "Buyer username"),
    "net": ("净额", "Net amount"),
    "payout_currency": ("发款货币", "Payout currency"),
    "payout_date": ("发款日期", "Payout date"),
    "payout_id": ("发款编号", "Payout ID"),
    "reference": ("参考编号", "Reference ID"),
    "description": ("描述", "Description"),
    "item_id": ("物品编号", "Item number"),
    "item_name": ("物品标题", "Item title"),
    "quantity": ("数量", "Quantity"),
    "item_subtotal": ("物品小计", "Item subtotal"),
    "shipping": ("运费与处理费", "Shipping and handling"),
    "fixed_fee": ("成交费 — 固定", "成交费—固定", "Final value fee - fixed"),
    "category_fee": ("成交费 — 因品类而异", "成交费—因品类而异", "Final value fee - variable"),
    "cross_border_fee": ("跨国交易费用", "International fee"),
    "ebay_tax": ("eBay 收取的税费", "eBay collected tax"),
    "transaction_total": ("交易总金额", "Total"),
}

TYPE_ORDER = "订单"
TYPE_OTHER_FEE = "其他费用"
TYPE_PAYOUT = "发放款项"
TYPE_REFUND = "退款"
TYPE_CHARGE = "收费"

PAYOUT_FEE_PATTERN = re.compile(r"已扣除发款费\s*[$￥]?\s*([0-9]+(?:\.[0-9]+)?)")
REFUND_REF_PATTERN = re.compile(r"(\d{6,})")
INSERTION_FEE_KEY = "insertionfee"


def _date_of(cols: Columns, row: Sequence) -> int:
    """现金流日期：优先发款日期，缺失时退回交易创建日期。"""
    return parse_date(cols.raw(row, "payout_date")) or parse_date(
        cols.raw(row, "created_date")
    ) or 0


def _weight_of(conn: sqlite3.Connection, item_id: str, fallback_shipping) -> Decimal:
    """item 的收入权重基数：优先用 ebay_item 里我们按 lot 算出的 X。"""
    item = get_item(conn, item_id) if item_id else None
    if item is not None:
        allocated = parse_money(item["allocated_shipping"])
        if allocated is not None:
            return allocated
    return money(fallback_shipping)


def import_transactions_file(
    conn: sqlite3.Connection, path: str, result: ImportResult, source_file: str
) -> None:
    table: Table = load_table(path, HEADER_KEYS)
    cols = Columns(
        table,
        ALIASES,
        required=("created_date", "type", "net", "item_id", "description"),
    )

    order_rows: "Dict[str, List[Sequence]]" = {}
    for row in table.rows:
        row_type = cols.text(row, "type")
        if row_type == TYPE_ORDER and cols.present(row, "item_id"):
            order_rows.setdefault(cols.text(row, "order_id"), []).append(row)

    for row in table.rows:
        row_type = cols.text(row, "type")
        if row_type == TYPE_ORDER:
            _handle_order_row(conn, cols, row, result, source_file, order_rows)
        elif row_type == TYPE_OTHER_FEE:
            _handle_other_fee(conn, cols, row, result, source_file)
        elif row_type == TYPE_PAYOUT:
            _handle_payout(conn, cols, row, result, source_file)
        elif row_type == TYPE_REFUND:
            _handle_refund(conn, cols, row, result, source_file)
        elif row_type == TYPE_CHARGE:
            result.note("类型=收费（信用卡相关扣费）按约定忽略")
        else:
            result.note(f"未识别的交易类型「{row_type}」已忽略")


# --------------------------------------------------------------------------- #
# 类型=订单
# --------------------------------------------------------------------------- #
def _handle_order_row(
    conn: sqlite3.Connection,
    cols: Columns,
    row: Sequence,
    result: ImportResult,
    source_file: str,
    order_rows: "Dict[str, List[Sequence]]",
) -> None:
    item_id = cols.text(row, "item_id")
    if not cols.present(row, "item_id"):
        # 物品编号为空或 '--' 的是订单级汇总行，其净额已由各 item 现金流汇总得到
        return

    order_id = cols.text(row, "order_id")
    cashflow_date = _date_of(cols, row)

    # 成交费（因品类而异）与跨国交易费逐行读取
    direct_rows = [
        (
            build_tax_trade_cashflow_id(item_id),
            "成交费",
            cols.raw(row, "category_fee"),
        ),
        (
            build_tax_inter_cashflow_id(item_id),
            "跨国交易费",
            cols.raw(row, "cross_border_fee"),
        ),
    ]
    for cashflow_id, cashflow_type, raw_amount in direct_rows:
        amount = parse_money(raw_amount)
        if amount is None:
            result.note(f"物品 {item_id} 的「{cashflow_type}」为空，未生成现金流")
            continue
        if insert_cashflow(
            conn,
            {
                "cashflow_id": cashflow_id,
                "item_id": item_id,
                "order_id": order_id,
                "cashflow_source": CASHFLOW_SOURCE_EBAY_FEE,
                "cashflow_type": cashflow_type,
                "amount": amount,
                "cashflow_date": cashflow_date,
                "reminder": "",
                "source_file": source_file,
            },
        ):
            result.inserted_cashflows += 1
        else:
            result.skipped_cashflows += 1

    # 成交费 — 固定：订单级汇总后按收入分摊
    group = order_rows.get(order_id) or [row]
    fixed_total = sum(
        (parse_money(cols.raw(group_row, "fixed_fee")) or ZERO) for group_row in group
    )
    if fixed_total == 0:
        result.note(f"订单 {order_id} 的「成交费 — 固定」合计为 0，未生成分摊现金流")
        return

    revenues = []
    for group_row in group:
        group_item_id = cols.text(group_row, "item_id")
        price = money(cols.text(group_row, "item_subtotal"))
        shipping = _weight_of(conn, group_item_id, cols.raw(group_row, "shipping"))
        revenues.append((price, shipping))

    price_total = sum((price for price, _shipping in revenues), ZERO)
    shipping_total = sum((shipping for _price, shipping in revenues), ZERO)
    allocations = allocate_order_fixed_fee(
        revenues, fixed_total, price_total, shipping_total
    )

    current_index = group.index(row) if row in group else -1
    if current_index < 0:
        return
    allocation = allocations[current_index]
    if insert_cashflow(
        conn,
        {
            "cashflow_id": build_tax_tradefix_cashflow_id(item_id),
            "item_id": item_id,
            "order_id": order_id,
            "cashflow_source": CASHFLOW_SOURCE_EBAY_FEE,
            "cashflow_type": "成交费 — 固定",
            "amount": allocation.amount,
            "cashflow_date": cashflow_date,
            "reminder": allocation.reminder,
            "source_file": source_file,
        },
    ):
        result.inserted_cashflows += 1
    else:
        result.skipped_cashflows += 1


# --------------------------------------------------------------------------- #
# 类型=其他费用（刊登费）
# --------------------------------------------------------------------------- #
def _handle_other_fee(
    conn: sqlite3.Connection,
    cols: Columns,
    row: Sequence,
    result: ImportResult,
    source_file: str,
) -> None:
    description = cols.text(row, "description")
    if INSERTION_FEE_KEY not in description.replace(" ", "").lower():
        # Store 订阅费在税费账单里以会员费形式导入，这里跳过避免重复记账
        result.note(f"类型=其他费用 且描述为「{description}」的行已跳过（非刊登费）")
        return

    item_id = cols.text(row, "item_id")
    if not cols.present(row, "item_id"):
        result.add_issue("刊登费缺少物品编号，无法入账", reference=description)
        return

    amount = parse_money(cols.raw(row, "net"))
    if amount is None:
        result.add_issue("刊登费净额为空，无法入账", reference=f"物品 {item_id}")
        return

    is_return = amount > 0
    cashflow_id = (
        build_pub_return_cashflow_id(item_id) if is_return else build_pub_cashflow_id(item_id)
    )
    if insert_cashflow(
        conn,
        {
            "cashflow_id": cashflow_id,
            "item_id": item_id,
            "order_id": cols.text(row, "order_id"),
            "cashflow_source": CASHFLOW_SOURCE_EBAY_OTHER_FEE,
            "cashflow_type": "刊登费",
            "amount": amount,
            "cashflow_date": _date_of(cols, row),
            "reminder": "",
            "source_file": source_file,
        },
    ):
        result.inserted_cashflows += 1
    else:
        result.skipped_cashflows += 1


# --------------------------------------------------------------------------- #
# 类型=发放款项（发款费均摊）
# --------------------------------------------------------------------------- #
def _handle_payout(
    conn: sqlite3.Connection,
    cols: Columns,
    row: Sequence,
    result: ImportResult,
    source_file: str,
) -> None:
    description = cols.text(row, "description")
    match = PAYOUT_FEE_PATTERN.search(description)
    if not match:
        result.add_issue(
            f"无法从描述解析发款费：{description}",
            reference=cols.text(row, "payout_id"),
        )
        return

    fee = money(match.group(1))
    cashflow_date = parse_date(cols.raw(row, "created_date")) or 0
    names = participants(conn)
    if not names:
        result.add_issue(
            "没有配置「参与会员费均摊」的用户，发款费无法均摊",
            reference=cols.text(row, "payout_id"),
        )
        return

    reference = cols.text(row, "reference")
    for seller_name, amount, reminder in split_per_head(-fee, names, reference):
        status = insert_cashflow_checked(
            conn,
            {
                "cashflow_id": build_transaction_fee_cashflow_id(cashflow_date, seller_name),
                "item_id": build_account_item_id(seller_name),
                "order_id": "",
                "cashflow_source": CASHFLOW_SOURCE_EBAY_ACCOUNT,
                "cashflow_type": "发款费",
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
                f"{cashflow_date} 已存在金额不同的发款费现金流，同一天多笔发款无法自动分摊，请录入手工账",
                reference=cols.text(row, "payout_id"),
            )


# --------------------------------------------------------------------------- #
# 类型=退款
# --------------------------------------------------------------------------- #
def _handle_refund(
    conn: sqlite3.Connection,
    cols: Columns,
    row: Sequence,
    result: ImportResult,
    source_file: str,
) -> None:
    order_id = cols.text(row, "order_id")
    reference = cols.text(row, "reference")
    match = REFUND_REF_PATTERN.search(reference)
    refund_no = match.group(1) if match else ""
    label = f"退款编号 {refund_no}" if refund_no else reference

    amount = parse_money(cols.raw(row, "net"))
    if amount is None:
        result.add_issue("退款净额为空，无法入账", reference=label)
        return

    items = order_items(conn, order_id) if order_id else []
    if not items:
        result.add_issue(
            f"退款订单 {order_id} 在 ebay_item 中查不到物品明细，无法分摊退款，请录入手工账",
            reference=label,
        )
        return

    seller_names = sorted({(item["seller_name"] or "Unknown") for item in items})
    buyer_names = sorted(
        {(item["buyer_username"] or "") for item in items if (item["buyer_username"] or "").strip()}
    )
    if len(seller_names) > 1 or len(buyer_names) > 1:
        result.add_issue(
            f"退款订单 {order_id} 涉及多个用户（卖家 {'、'.join(seller_names)}"
            f"{'；买家 ' + '、'.join(buyer_names) if len(buyer_names) > 1 else ''}），"
            "无法确定分摊逻辑，请录入手工账",
            reference=label,
        )
        return

    weights = [
        money(item["item_price"]) + money(item["allocated_shipping"]) for item in items
    ]
    amounts = split_by_weight(amount, weights)
    multi_item = len(items) > 1
    for item, item_amount in zip(items, amounts):
        item_id = item["item_id"]
        cashflow_id = (
            f"EBAY-REFUND-{refund_no}-{item_id}" if multi_item else f"EBAY-REFUND-{refund_no}"
        )
        if insert_cashflow(
            conn,
            {
                "cashflow_id": cashflow_id,
                "item_id": item_id,
                "order_id": order_id,
                "cashflow_source": CASHFLOW_SOURCE_EBAY_REFUND,
                "cashflow_type": "退款",
                "amount": item_amount,
                "cashflow_date": _date_of(cols, row),
                "reminder": reference,
                "source_file": source_file,
            },
        ):
            result.inserted_cashflows += 1
        else:
            result.skipped_cashflows += 1
