"""费用分摊算法（对应 guide「费用分摊规则」）。

三条规则：
- X 按 lot 分配：把订单实收运费按「基础运费 + 合单附加运费」的应收比例摊到各 item。
- Y 按收入分配：把订单级「成交费 — 固定」按 item 收入（物品小计 + X）占比摊到各 item。
- W 按人头均摊：发款费 / 会员费在「参与会员费均摊」的卖家之间等分。

共同约定：参与方为 N>1 时，前 N-1 个四舍五入到 0.01，最后一个取残值，
保证分摊结果之和与原始总额严格相等（Decimal，不出现 float 误差）。
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence, Tuple

from .money import ZERO, fmt2, parse_money, q2, q3, trim

# --------------------------------------------------------------------------- #
# 基础常量
# --------------------------------------------------------------------------- #
LOT_PATTERN = re.compile(r"lot\s*\(?\s*(\d+)\s*\)?", re.IGNORECASE)
TRACK_13_PATTERN = re.compile(r"^[A-Z]{2}\d{9}[A-Z]{2}$")

BASE_SHIPPING_LOW = Decimal("9.99")   # ES 开头 28 位 / XX123456789XX 形式
BASE_SHIPPING_HIGH = Decimal("35.99")  # 其余情况
UNKNOWN_SELLER = "Unknown"

CASHFLOW_SOURCE_EBAY_FEE = "ebay费用"
CASHFLOW_SOURCE_EBAY_OTHER_FEE = "ebay其他费用"
CASHFLOW_SOURCE_EBAY_ACCOUNT = "ebay账户"
CASHFLOW_SOURCE_EBAY_REFUND = "ebay退款"
CASHFLOW_SOURCE_MANUAL = "手工帐"


# --------------------------------------------------------------------------- #
# lot / 基础运费
# --------------------------------------------------------------------------- #
def parse_lot(item_name: Optional[str]) -> int:
    """从物品标题里解析 lot 数量，匹配失败记 1（guide：Lot(3) 或 Lot3）。"""
    if not item_name:
        return 1
    match = LOT_PATTERN.search(item_name)
    if not match:
        return 1
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return 1
    return value if value > 0 else 1


def lot_surcharge(lot: int) -> Decimal:
    """合单附加运费：0<lot<=5 -> 1；5<lot<=10 -> 2；lot>10 -> 3。"""
    if lot <= 0:
        return Decimal("1")
    if lot <= 5:
        return Decimal("1")
    if lot <= 10:
        return Decimal("2")
    return Decimal("3")


def base_shipping(track_id: Optional[str]) -> Decimal:
    """按追踪号码判定基础运费。

    - ES 开头且共 28 位 -> 9.99
    - XX123456789XX（2 位字母 + 9 位数字 + 2 位字母，共 13 位）-> 9.99
    - 其余（含缺失）-> 35.99
    """
    track = (track_id or "").strip().upper()
    if not track:
        return BASE_SHIPPING_HIGH
    if track.startswith("ES") and len(track) == 28:
        return BASE_SHIPPING_LOW
    if TRACK_13_PATTERN.match(track):
        return BASE_SHIPPING_LOW
    return BASE_SHIPPING_HIGH


# --------------------------------------------------------------------------- #
# 通用分摊
# --------------------------------------------------------------------------- #
def residual_split(total: Decimal, first_n_minus_one: Sequence[Decimal]) -> List[Decimal]:
    """前 N-1 个用给定值，最后一个取残值，使总和严格等于 total。"""
    amounts = [q2(value) for value in first_n_minus_one]
    amounts.append(q2(total) - sum(amounts, ZERO))
    return amounts


def split_equal(total: Decimal, count: int) -> List[Decimal]:
    """W 均摊：等分 total 给 count 个人，最后一人取残值。"""
    total = q2(total)
    if count <= 0:
        return []
    if count == 1:
        return [total]
    per = q2(total / count)
    return residual_split(total, [per] * (count - 1))


def split_by_weight(total: Decimal, weights: Sequence[Decimal]) -> List[Decimal]:
    """按权重占比分摊 total，最后一个取残值。"""
    total = q2(total)
    if not weights:
        return []
    weight_sum = sum(weights, ZERO)
    if weight_sum == 0:
        return [q2(total)] + [ZERO] * (len(weights) - 1)
    parts = [q2(total * weight / weight_sum) for weight in weights[:-1]]
    return residual_split(total, parts)


# --------------------------------------------------------------------------- #
# X：按 lot 分配订单运费
# --------------------------------------------------------------------------- #
class ShippingAllocation:
    """单个 item 的运费分配结果。"""

    __slots__ = ("amount", "reminder", "weight")

    def __init__(self, amount: Decimal, reminder: str, weight: Decimal):
        self.amount = amount
        self.reminder = reminder
        self.weight = weight


def allocate_shipping(
    lots: Sequence[int],
    order_shipping,
    track_id: Optional[str] = None,
    base: Optional[Decimal] = None,
) -> List[ShippingAllocation]:
    """按 guide 的 X 规则把订单实收运费摊到同一订单的各个 item。

    应收运费 = 基础运费 / N + 该 item 的合单附加运费（表格顺序上的第一笔没有附加运费），
    系数 = 实收运费 / 应收运费之和，分摊额 = 应收运费 * 系数。
    """
    shipping = q2(parse_money(order_shipping) or ZERO)
    base = base if base is not None else base_shipping(track_id)
    count = len(lots)
    if count == 0:
        return []

    if count == 1:
        # 只有一个 item，不用分摊，全额给它
        return [ShippingAllocation(shipping, "", shipping)]

    share = base / count
    weights: List[Decimal] = []
    reminders: List[str] = []
    for index, lot in enumerate(lots):
        if index == 0:
            weight = share
            reminders.append(f"({fmt2(base)} / {count})")
        else:
            extra = lot_surcharge(lot)
            weight = share + extra
            reminders.append(f"({fmt2(base)} / {count} + {trim(extra)})")
        weights.append(weight)

    weight_sum = sum(weights, ZERO)
    coefficient = (shipping / weight_sum) if weight_sum else ZERO
    coefficient_text = format(q3(coefficient), "f")  # 保留 3 位小数，如 0.862

    results: List[ShippingAllocation] = []
    amounts = [q2(weight * coefficient) for weight in weights[:-1]]
    amounts = residual_split(shipping, amounts)
    for index, (amount, weight) in enumerate(zip(amounts, weights)):
        results.append(
            ShippingAllocation(amount, f"{reminders[index]} * {coefficient_text}", weight)
        )
    return results


# --------------------------------------------------------------------------- #
# Y：按收入分配订单级固定成交费
# --------------------------------------------------------------------------- #
class FeeAllocation:
    __slots__ = ("amount", "reminder")

    def __init__(self, amount: Decimal, reminder: str):
        self.amount = amount
        self.reminder = reminder


def allocate_order_fixed_fee(
    revenues: Sequence[Tuple[Decimal, Decimal]],
    fixed_fee,
    order_price_total: Decimal,
    order_shipping_total: Decimal,
) -> List[FeeAllocation]:
    """按 guide 的 Y 规则分摊「成交费 — 固定」。

    :param revenues: 每个 item 的 (物品小计, 摊到的运费 X)
    :param fixed_fee: 该订单「成交费 — 固定」合计（负数）
    :param order_price_total: 订单下所有 item 的成交价之和
    :param order_shipping_total: 订单下所有 item 摊到的运费之和（= 实收运费）
    """
    fee = q2(parse_money(fixed_fee) or ZERO)
    weights = [q2(price) + q2(shipping) for price, shipping in revenues]
    if sum(weights, ZERO) == 0:
        # 订单收入全为 0（理论上不该出现）：退化为等分，保证费用不丢
        amounts = split_equal(fee, len(revenues))
    else:
        amounts = split_by_weight(fee, weights)

    results: List[FeeAllocation] = []
    for (price, shipping), amount in zip(revenues, amounts):
        ratio = (
            f"({trim(price)}+{trim(shipping)})"
            f"/({fmt2(order_price_total)}+{fmt2(order_shipping_total)})"
        )
        # reminder 里的费用写成绝对值：guide 里订单级费用是 -0.4，示例写的是 * 0.4
        results.append(FeeAllocation(amount, f"{ratio} * {trim(abs(fee))}"))
    return results


# --------------------------------------------------------------------------- #
# W：按人头均摊
# --------------------------------------------------------------------------- #
def split_per_head(total, participants: Iterable[str], note: str = "") -> List[Tuple[str, Decimal, str]]:
    """把 total 等分给 participants。

    返回 [(用户名, 金额, reminder)]，reminder 形如
    "银行参考编号 MZBIL0TEWF5T66I  5.91 / 3"。
    """
    names = list(participants)
    amount = q2(parse_money(total) or ZERO)
    if not names:
        return []
    amounts = split_equal(amount, len(names))
    reminder_note = f"{trim(abs(amount))} / {len(names)}"
    if note:
        reminder_note = f"{note}  {reminder_note}"
    return [(name, value, reminder_note) for name, value in zip(names, amounts)]


def build_trade_cashflow_id(item_id: str) -> str:
    return f"EBAY-TRADE-{item_id}"


def build_transport_cashflow_id(item_id: str) -> str:
    return f"EBAY-TRANSPORT-{item_id}"


def build_tax_trade_cashflow_id(item_id: str) -> str:
    return f"EBAY-TAX-TRADE-{item_id}"


def build_tax_inter_cashflow_id(item_id: str) -> str:
    return f"EBAY-TAX-INTER-{item_id}"


def build_tax_tradefix_cashflow_id(item_id: str) -> str:
    return f"EBAY-TAX-TRADEFIX-{item_id}"


def build_pub_cashflow_id(item_id: str) -> str:
    return f"EBAY-TAX-PUB-{item_id}"


def build_pub_return_cashflow_id(item_id: str) -> str:
    return f"EBAY-TAX-PUBRETURN-{item_id}"


def build_transaction_fee_cashflow_id(date_int: int, seller_name: str) -> str:
    return f"EBAY-TRANSACTIONFEE-{date_int}-{seller_name}"


def build_membership_cashflow_id(date_int: int, seller_name: str) -> str:
    return f"EBAY-MEMBERSHIP-{date_int}-{seller_name}"


def build_account_item_id(seller_name: str) -> str:
    return f"ebay账户-{seller_name}"
