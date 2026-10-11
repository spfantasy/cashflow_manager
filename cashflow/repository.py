"""数据访问层（直接使用 sqlite3，避免引入 ORM 以便 PyInstaller 打包）。"""

from __future__ import annotations

import re
import sqlite3
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence

from .allocations import UNKNOWN_SELLER
from .money import ZERO, cell_is_empty, money, to_db

PROTECTED_SELLERS = {UNKNOWN_SELLER}


# --------------------------------------------------------------------------- #
# 卖家配置
# --------------------------------------------------------------------------- #
def list_sellers(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM seller ORDER BY sort_order ASC, id ASC"
        )
    )


def participants(conn: sqlite3.Connection) -> List[str]:
    """参与会员费/发款费均摊的卖家名（按配置顺序）。"""
    rows = conn.execute(
        "SELECT seller_name FROM seller WHERE share_membership = 1"
        " ORDER BY sort_order ASC, id ASC"
    )
    return [row["seller_name"] for row in rows]


def get_seller(conn: sqlite3.Connection, seller_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM seller WHERE id = ?", (seller_id,)).fetchone()


def save_seller(
    conn: sqlite3.Connection,
    seller_name: str,
    match_regex: str,
    share_membership: bool,
    sort_order: int,
    seller_id: Optional[int] = None,
) -> None:
    """新增或更新卖家配置。Unknown 不允许改名为其它名字。"""
    name = (seller_name or "").strip()
    if not name:
        raise ValueError("用户名不能为空")
    if seller_id:
        current = get_seller(conn, seller_id)
        if current is not None and current["seller_name"] in PROTECTED_SELLERS and name != current["seller_name"]:
            raise ValueError(f"内置用户 {current['seller_name']} 不允许改名")
        conn.execute(
            "UPDATE seller SET seller_name = ?, match_regex = ?, share_membership = ?,"
            " sort_order = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (name, match_regex or "", 1 if share_membership else 0, int(sort_order), seller_id),
        )
    else:
        conn.execute(
            "INSERT INTO seller (seller_name, match_regex, share_membership, sort_order)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(seller_name) DO UPDATE SET"
            " match_regex = excluded.match_regex,"
            " share_membership = excluded.share_membership,"
            " sort_order = excluded.sort_order,"
            " updated_at = datetime('now','localtime')",
            (name, match_regex or "", 1 if share_membership else 0, int(sort_order)),
        )


def delete_seller(conn: sqlite3.Connection, seller_id: int) -> None:
    row = get_seller(conn, seller_id)
    if row is None:
        return
    if row["seller_name"] in PROTECTED_SELLERS:
        raise ValueError(f"内置用户 {row['seller_name']} 不允许删除")
    conn.execute("DELETE FROM seller WHERE id = ?", (seller_id,))


class SellerMatcher:
    """按配置顺序用正则匹配物品标题，全部不命中则为 Unknown。"""

    def __init__(self, conn: sqlite3.Connection):
        self.rules: List[tuple] = []
        self.errors: List[str] = []
        for row in list_sellers(conn):
            if row["seller_name"] == UNKNOWN_SELLER:
                continue
            pattern = (row["match_regex"] or "").strip()
            if not pattern:
                continue
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                self.errors.append(f"用户 {row['seller_name']} 的正则无效：{exc}")
                continue
            self.rules.append((row["seller_name"], compiled))

    def match(self, item_name: Optional[str]) -> str:
        title = item_name or ""
        for seller_name, pattern in self.rules:
            if pattern.search(title):
                return seller_name
        return UNKNOWN_SELLER


# --------------------------------------------------------------------------- #
# ebay_item
# --------------------------------------------------------------------------- #
ITEM_COLUMNS = (
    "item_id", "order_id", "record_id", "buyer_username", "buyer_country",
    "item_name", "seller_name", "seller_manual", "track_id", "lot",
    "item_price", "order_shipping", "base_shipping", "allocated_shipping",
    "shipping_reminder", "payment_date", "order_seq", "source_file",
)


def insert_item(conn: sqlite3.Connection, data: dict) -> bool:
    """插入 ebay_item，已存在（主键冲突）则跳过。返回是否真的写入。"""
    payload = dict(data)
    payload.setdefault("seller_name", UNKNOWN_SELLER)
    payload["seller_name"] = payload.get("seller_name") or UNKNOWN_SELLER
    payload.setdefault("lot", 1)
    payload["lot"] = payload.get("lot") or 1
    payload.setdefault("seller_manual", 0)
    payload.setdefault("order_seq", 0)
    payload["payment_date"] = (
        int(payload["payment_date"]) if payload.get("payment_date") else 0
    )
    for column in ITEM_COLUMNS:
        payload.setdefault(column, None)
    values = [payload.get(column) for column in ITEM_COLUMNS]
    placeholders = ", ".join("?" for _ in ITEM_COLUMNS)
    return _insert_ignoring_duplicates(
        conn,
        f"INSERT INTO ebay_item ({', '.join(ITEM_COLUMNS)}) VALUES ({placeholders})",
        values,
    )


def get_item(conn: sqlite3.Connection, item_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM ebay_item WHERE item_id = ?", (item_id,)
    ).fetchone()


def order_items(conn: sqlite3.Connection, order_id: str) -> List[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM ebay_item WHERE order_id = ? ORDER BY order_seq ASC, item_id ASC",
            (order_id,),
        )
    )


def update_seller_name(
    conn: sqlite3.Connection, item_id: str, seller_name: str, manual: bool = True
) -> bool:
    cursor = conn.execute(
        "UPDATE ebay_item SET seller_name = ?, seller_manual = ? WHERE item_id = ?",
        (seller_name, 1 if manual else 0, item_id),
    )
    return cursor.rowcount > 0


def rematch_sellers(conn: sqlite3.Connection) -> int:
    """按当前配置重新匹配所有非人工调整过的 item 的 seller_name。"""
    matcher = SellerMatcher(conn)
    rows = conn.execute(
        "SELECT item_id, item_name FROM ebay_item WHERE seller_manual = 0"
    ).fetchall()
    changed = 0
    for row in rows:
        seller_name = matcher.match(row["item_name"])
        cursor = conn.execute(
            "UPDATE ebay_item SET seller_name = ? WHERE item_id = ? AND seller_name <> ?",
            (seller_name, row["item_id"], seller_name),
        )
        changed += cursor.rowcount
    return changed


# --------------------------------------------------------------------------- #
# ebay_item_cashflow
# --------------------------------------------------------------------------- #
def _insert_ignoring_duplicates(conn: sqlite3.Connection, sql: str, values: list) -> bool:
    """插入一行，主键冲突则跳过；其它约束错误必须抛出。

    注意：这里刻意不用 ``INSERT OR IGNORE``，因为它会把 NOT NULL / 类型等错误
    一起吞掉，导致数据静默丢失。
    """
    try:
        cursor = conn.execute(sql, values)
    except sqlite3.IntegrityError as exc:
        message = str(exc).upper()
        if "UNIQUE" in message or "PRIMARY KEY" in message:
            return False
        raise
    return cursor.rowcount > 0


def insert_cashflow(conn: sqlite3.Connection, data: dict) -> bool:
    """插入 ebay_item_cashflow，cashflow_id 已存在则跳过。返回是否真的写入。"""
    columns = (
        "cashflow_id", "item_id", "order_id", "cashflow_source", "cashflow_type",
        "amount", "cashflow_date", "reminder", "source_file",
    )
    payload = {key: data.get(key) for key in columns}
    for key in ("item_id", "cashflow_source", "cashflow_type", "reminder", "source_file"):
        payload[key] = payload.get(key) or ""
    # 空的订单号（含 '--' 这类占位符）存 NULL，
    # 这样 COALESCE(c.order_id, i.order_id) 才能回退到物品的订单号
    order_id = payload.get("order_id")
    payload["order_id"] = None if cell_is_empty(order_id) else str(order_id).strip()
    payload["cashflow_date"] = int(payload.get("cashflow_date") or 0)

    amount = payload.get("amount")
    payload["amount"] = to_db(ZERO if amount is None else amount)
    placeholders = ", ".join("?" for _ in columns)
    return _insert_ignoring_duplicates(
        conn,
        f"INSERT INTO ebay_item_cashflow ({', '.join(columns)}) VALUES ({placeholders})",
        [payload[key] for key in columns],
    )


def insert_cashflows(conn: sqlite3.Connection, rows: Sequence[dict]) -> tuple:
    """批量插入，返回 (写入数, 跳过数)。"""
    inserted = skipped = 0
    for row in rows:
        if insert_cashflow(conn, row):
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


def get_cashflow(conn: sqlite3.Connection, cashflow_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM ebay_item_cashflow WHERE cashflow_id = ?", (cashflow_id,)
    ).fetchone()


CONFLICT_FIELDS = ("amount", "cashflow_date", "item_id", "cashflow_type")


def insert_cashflow_checked(conn: sqlite3.Connection, data: dict) -> str:
    """插入现金流，返回 'inserted' / 'duplicate' / 'conflict'。

    用于 cashflow_id 由「日期 + 用户」拼出来的聚合类现金流（发款费、会员费）：
    如果同一天出现多笔金额不同的费用，主键会撞车，此时必须报冲突交人工处理，
    不能像普通重复导入那样静默跳过。
    """
    payload = dict(data)
    if insert_cashflow(conn, payload):
        return "inserted"
    existing = get_cashflow(conn, payload["cashflow_id"])
    if existing is None:
        return "inserted"
    for field in CONFLICT_FIELDS:
        wanted = payload.get(field)
        if field == "amount":
            wanted = to_db(ZERO if wanted is None else wanted)
        elif field == "cashflow_date":
            wanted = int(wanted or 0)
        current = existing[field]
        if (current or "") != (wanted or ""):
            return "conflict"
    return "duplicate"


def delete_cashflows(conn: sqlite3.Connection, cashflow_ids: Iterable[str]) -> int:
    ids = [str(value) for value in cashflow_ids if str(value).strip()]
    if not ids:
        return 0
    deleted = 0
    for chunk_start in range(0, len(ids), 400):
        chunk = ids[chunk_start:chunk_start + 400]
        placeholders = ", ".join("?" for _ in chunk)
        cursor = conn.execute(
            f"DELETE FROM ebay_item_cashflow WHERE cashflow_id IN ({placeholders})",
            chunk,
        )
        deleted += cursor.rowcount
    return deleted


CASHFLOW_SELECT = """
SELECT c.cashflow_id, c.item_id, c.cashflow_source, c.cashflow_type, c.amount,
       c.cashflow_date, c.reminder,
       COALESCE(NULLIF(c.order_id, ''), i.order_id) AS order_id,
       i.item_name, i.seller_name, i.buyer_username, i.track_id, i.lot,
       i.item_price, i.allocated_shipping, i.payment_date
  FROM ebay_item_cashflow c
  LEFT JOIN ebay_item i ON i.item_id = c.item_id
"""

ORDER_EXPR = "COALESCE(NULLIF(c.order_id, ''), i.order_id)"


def query_flows(
    conn: sqlite3.Connection,
    start_date: Optional[int] = None,
    end_date: Optional[int] = None,
    seller_name: Optional[str] = None,
) -> List[sqlite3.Row]:
    """页面1 流水查询：日期范围 + 用户（item 的 seller_name 或账户级 item_id）。"""
    sql = CASHFLOW_SELECT
    conditions: List[str] = []
    params: List = []
    if start_date:
        conditions.append("c.cashflow_date >= ?")
        params.append(int(start_date))
    if end_date:
        conditions.append("c.cashflow_date <= ?")
        params.append(int(end_date))
    if seller_name:
        conditions.append("(i.seller_name = ? OR c.item_id = ?)")
        params.extend([seller_name, f"ebay账户-{seller_name}"])
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY c.cashflow_date DESC, c.cashflow_id ASC"
    return list(conn.execute(sql, params))


def query_details(
    conn: sqlite3.Connection,
    item_id: Optional[str] = None,
    order_id: Optional[str] = None,
) -> List[sqlite3.Row]:
    """页面2 详情查询：item_id 与 order_id 为「或」关系。"""
    item_id = (item_id or "").strip()
    order_id = (order_id or "").strip()
    sql = CASHFLOW_SELECT
    conditions: List[str] = []
    params: List = []
    if item_id and order_id:
        conditions.append(f"(c.item_id = ? OR {ORDER_EXPR} = ?)")
        params.extend([item_id, order_id])
    elif item_id:
        conditions.append("c.item_id = ?")
        params.append(item_id)
    elif order_id:
        conditions.append(f"{ORDER_EXPR} = ?")
        params.append(order_id)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY c.cashflow_date ASC, c.cashflow_id ASC"
    return list(conn.execute(sql, params))


def sum_amounts(rows: Sequence[sqlite3.Row]) -> Decimal:
    total = ZERO
    for row in rows:
        total += money(row["amount"])
    return total


# --------------------------------------------------------------------------- #
# 导入日志
# --------------------------------------------------------------------------- #
def log_import(
    conn: sqlite3.Connection,
    file_name: str,
    file_kind: str,
    inserted: int,
    skipped: int,
    failed: int,
    detail: str = "",
) -> None:
    conn.execute(
        "INSERT INTO import_log (file_name, file_kind, inserted, skipped, failed, detail)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (file_name, file_kind, inserted, skipped, failed, detail),
    )


def recent_imports(conn: sqlite3.Connection, limit: int = 20) -> List[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM import_log ORDER BY id DESC LIMIT ?", (int(limit),)
        )
    )
