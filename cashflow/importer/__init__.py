"""导入入口：按文件类型分发。"""

from __future__ import annotations

import os
import sqlite3
from typing import Iterable, List

from ..repository import log_import
from .base import ImportIssue, ImportResult
from .invoice import FILE_KIND as INVOICE_KIND
from .invoice import import_invoice_file
from .orders import FILE_KIND as ORDERS_KIND
from .orders import import_orders_file
from .transactions import FILE_KIND as TRANSACTIONS_KIND
from .transactions import import_transactions_file

__all__ = [
    "ImportResult",
    "ImportIssue",
    "ORDERS_KIND",
    "TRANSACTIONS_KIND",
    "INVOICE_KIND",
    "KIND_LABELS",
    "import_file",
    "import_files",
]

KIND_LABELS = {
    ORDERS_KIND: "订单表（报告-所有订单）",
    TRANSACTIONS_KIND: "交易报告（付款-交易报告）",
    INVOICE_KIND: "税费账单（付款-税费账单）",
}

_HANDLERS = {
    ORDERS_KIND: import_orders_file,
    TRANSACTIONS_KIND: import_transactions_file,
    INVOICE_KIND: import_invoice_file,
}


def import_file(conn: sqlite3.Connection, kind: str, path: str) -> ImportResult:
    """导入单个文件并提交（每个文件一个事务）。"""
    if kind not in _HANDLERS:
        raise ValueError(f"未知的导入类型：{kind}")
    source_file = os.path.basename(path)
    result = ImportResult(file_name=source_file, file_kind=kind)
    try:
        _HANDLERS[kind](conn, path, result, source_file)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    log_import(
        conn,
        source_file,
        kind,
        result.inserted_items + result.inserted_cashflows,
        result.skipped_items + result.skipped_cashflows,
        result.failed,
        detail="\n".join(result.notes[:20]),
    )
    conn.commit()
    return result


def import_files(conn: sqlite3.Connection, kind: str, paths: Iterable[str]) -> List[ImportResult]:
    results: List[ImportResult] = []
    for path in paths:
        results.append(import_file(conn, kind, path))
    return results
