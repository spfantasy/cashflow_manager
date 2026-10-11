"""pytest 公共夹具。"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cashflow import create_app  # noqa: E402
from cashflow.config import Config  # noqa: E402

DESCRIPTION_DIR = os.path.join(ROOT, "description")
ORDERS_FILE = os.path.join(
    DESCRIPTION_DIR,
    "报告 - 下载 - 所有订单 - 1月",
    "ebay-all-orders-report-2026-01-01-2026-01-31-11337623604.csv",
)
TRANSACTIONS_FILE = os.path.join(
    DESCRIPTION_DIR,
    "付款 - 交易报告 - 1月",
    "Transaction-Sep-27-2026-19_18_46-0700-12348903035.csv",
)
INVOICE_FILE = os.path.join(
    DESCRIPTION_DIR,
    "付款 - 税费账单 - 1月",
    "invoiceId-2421824073_2026-1.csv",
)

samples_available = pytest.mark.skipif(
    not all(os.path.exists(path) for path in (ORDERS_FILE, TRANSACTIONS_FILE, INVOICE_FILE)),
    reason="description/ 下的样例数据不存在（该目录未纳入版本控制）",
)


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test"


@pytest.fixture()
def app(tmp_path):
    class _Config(TestConfig):
        DB_PATH = str(tmp_path / "test.db")
        UPLOAD_DIR = str(tmp_path / "uploads")

    return create_app(_Config)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def conn(app):
    from cashflow.db import connect

    connection = connect(app.config["DB_PATH"])
    yield connection
    connection.close()
