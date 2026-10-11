"""应用配置。"""

from __future__ import annotations

import os

from .resources import app_base_dir, resource_path


class Config:
    SECRET_KEY = os.environ.get("CASHFLOW_SECRET_KEY", "cashflow-manager-local")

    # 数据库文件：默认放在程序目录下的 data/cashflow.db，可用环境变量覆盖
    DB_PATH = os.environ.get(
        "CASHFLOW_DB", os.path.join(app_base_dir(), "data", "cashflow.db")
    )

    # 上传文件先落到临时目录
    UPLOAD_DIR = os.environ.get(
        "CASHFLOW_UPLOAD_DIR", os.path.join(app_base_dir(), "data", "uploads")
    )

    MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 单个请求最大 64MB（一次可拖多个文件）

    TEMPLATE_FOLDER = resource_path("cashflow", "templates")
    STATIC_FOLDER = resource_path("cashflow", "static")

    # 明细页一次最多删除的行数，防止误操作
    MAX_DELETE_ROWS = 500
