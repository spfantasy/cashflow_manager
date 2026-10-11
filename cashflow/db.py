"""SQLite 连接与初始化。"""

from __future__ import annotations

import os
import sqlite3

from flask import g

from .resources import resource_path

SCHEMA_FILE = resource_path("cashflow", "schema.sql")

DEFAULT_SELLERS = [
    # (seller_name, match_regex, share_membership, sort_order)
    # TEST_USER 的示例规则：标题以「空格 + TEST_USER」结尾（正则文本本身即配置项）
    ("TEST_USER", r"^.* (TEST_USER)$", 0, 1),
    # Unknown 不匹配任何标题，只用作用户名匹配失败时的兜底，且不参与分摊
    ("Unknown", "", 0, 9999),
]


def connect(db_path: str) -> sqlite3.Connection:
    directory = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> sqlite3.Connection:
    """取得当前请求的连接（Flask g 缓存）。"""
    if "db" not in g:
        from flask import current_app

        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def close_db(_exception=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(db_path: str) -> None:
    """建表 + 写入初始卖家配置（幂等）。"""
    conn = connect(db_path)
    try:
        with open(SCHEMA_FILE, "r", encoding="utf-8") as handle:
            conn.executescript(handle.read())
        for name, regex, share, order in DEFAULT_SELLERS:
            conn.execute(
                "INSERT OR IGNORE INTO seller (seller_name, match_regex, share_membership, sort_order)"
                " VALUES (?, ?, ?, ?)",
                (name, regex, share, order),
            )
        conn.commit()
    finally:
        conn.close()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
