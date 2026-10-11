"""金额、日期与字符串的小工具。

设计约定（重要）：
- 所有金额一律使用 ``decimal.Decimal``，绝不使用 ``float``。SQLite 没有
  DECIMAL 类型（NUMERIC 亲和性会把 '15.50' 这种字符串转成 REAL 从而丢精度），
  因此金额在库里以「精确十进制字符串」保存，聚合时在 Python 侧用 Decimal 相加。
- 金额统一量化到 0.01（ROUND_HALF_UP），与 guide 中「四舍五入到 0.01」一致。
"""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

ZERO = Decimal("0")
CENT = Decimal("0.01")

_MONEY_CLEAN = re.compile(r"[^0-9.\-]")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_EMPTY_TOKENS = {"", "--", "-", "n/a", "na", "null", "none", "—", "－"}


# --------------------------------------------------------------------------- #
# 金额
# --------------------------------------------------------------------------- #
def parse_money(value) -> Optional[Decimal]:
    """把 'US $15.50' / '15.5' / '-0.29' / '--' 解析成 Decimal。

    无法解析或空值返回 ``None``（调用方自行决定当作 0 还是跳过）。
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int,)):
        return Decimal(value)
    if isinstance(value, float):  # 仅在 xlsx 单元格回退时可能出现
        return Decimal(repr(value))
    text = str(value).strip()
    if text.lower() in _EMPTY_TOKENS:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = _MONEY_CLEAN.sub("", text)
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        amount = Decimal(cleaned)
    except Exception:
        return None
    if negative and amount > 0:
        amount = -amount
    return amount


def money(value) -> Decimal:
    """解析金额，解析不到时返回 0。"""
    parsed = parse_money(value)
    return ZERO if parsed is None else parsed


def q2(value: Decimal) -> Decimal:
    """量化到 0.01，四舍五入（ROUND_HALF_UP）。"""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def q3(value: Decimal) -> Decimal:
    """量化到 0.001，用于 reminder 里展示的分配系数。"""
    return Decimal(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def to_db(value) -> str:
    """转成入库用的精确十进制字符串（固定 2 位小数，且不会出现 '-0.00'）。"""
    amount = q2(money(value))
    if amount == 0:
        amount = amount.copy_abs()  # 避免出现 '-0.00'，同时保留 2 位小数
    return format(amount, "f")


def trim(value) -> str:
    """去掉多余的尾随 0：1.00 -> '1'，0.40 -> '0.4'，15.50 -> '15.5'。

    仅用于 reminder 文案（与 guide 中 `(9.99 / 9 + 1)`、`* 0.4` 的写法一致）。
    """
    text = format(q2(money(value)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def fmt2(value) -> str:
    """固定 2 位小数：15.5 -> '15.50'。"""
    return format(q2(money(value)), "f")


def parse_int(value, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    text = str(value).strip()
    if text.lower() in _EMPTY_TOKENS:
        return default
    try:
        return int(Decimal(_MONEY_CLEAN.sub("", text) or "0"))
    except Exception:
        return default


# --------------------------------------------------------------------------- #
# 日期：统一以 YYYYMMDD 整数入库
# --------------------------------------------------------------------------- #
def parse_date(value) -> Optional[int]:
    """解析 Excel/CSV 里出现的各种日期写法，返回 YYYYMMDD。

    支持：Jan-17-26 / 17-Jan-26 / 2026-01-01 08:29:00 PDT / 2026-01-01 /
    01/17/2026 / 17/01/2026（按美股报表习惯优先月在前）/ 20260117，
    以及 xlsx 读出来的 datetime/date 对象。
    """
    if value is None:
        return None
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return _build(int(value.year), int(value.month), int(value.day))
    text = str(value).strip()
    if text.lower() in _EMPTY_TOKENS:
        return None

    # 2026-01-01 08:29:00 PDT -> 2026-01-01
    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        return _build(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    # 20260117
    if re.fullmatch(r"\d{8}", text):
        return _build(int(text[:4]), int(text[4:6]), int(text[6:]))

    # Jan-17-26 / Jan-17-2026 / Jan 17, 2026
    m = re.match(r"^([A-Za-z]{3,4})[\-\s/]+(\d{1,2})[\-\s,/]+(\d{2,4})$", text)
    if m:
        month = _MONTHS.get(m.group(1).lower())
        if month:
            return _build(_year(m.group(3)), month, int(m.group(2)))

    # 17-Jan-26 / 17 Jan 2026
    m = re.match(r"^(\d{1,2})[\-\s/]+([A-Za-z]{3,4})[\-\s,/]+(\d{2,4})$", text)
    if m:
        month = _MONTHS.get(m.group(2).lower())
        if month:
            return _build(_year(m.group(3)), month, int(m.group(1)))

    # 01/17/2026 或 2026/01/17
    m = re.match(r"^(\d{1,4})/(\d{1,2})/(\d{1,4})$", text)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 31:  # yyyy/mm/dd
            return _build(a, b, c)
        return _build(_year(str(c)), a, b)

    return None


def _year(token: str) -> int:
    year = int(token)
    return year + 2000 if year < 100 else year


def _build(year: int, month: int, day: int) -> Optional[int]:
    if not (1900 <= year <= 2200 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return year * 10000 + month * 100 + day


def parse_date_input(value) -> Optional[int]:
    """解析页面上的日期输入：支持 <input type=date> 的 2026-01-17 与 20260117。"""
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}", text):
        return int(text)
    return parse_date(text)


def fmt_date(value: Optional[int]) -> str:
    """YYYYMMDD -> '2026-01-17'（用于页面展示）。"""
    if not value:
        return ""
    text = str(int(value))
    if len(text) != 8:
        return text
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def compact(text) -> str:
    """去掉所有空白，用于宽松比较表头/描述。"""
    return re.sub(r"\s+", "", str(text or ""))


def cell_str(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def cell_is_empty(value) -> bool:
    return cell_str(value).lower() in _EMPTY_TOKENS
