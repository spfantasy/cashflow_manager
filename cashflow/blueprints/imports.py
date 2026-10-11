"""页面3：导入数据。

三个拖入框分别对应三类文件，一次可拖入多个文件；点击导入后按规则入库，
导入结束后若存在需要人工处理的项（例如多用户退款），页面会弹出对话框提示。
"""

from __future__ import annotations

import os
import uuid

from flask import Blueprint, current_app, render_template, request
from werkzeug.utils import secure_filename

from ..db import get_db
from ..importer import (
    INVOICE_KIND,
    KIND_LABELS,
    ORDERS_KIND,
    TRANSACTIONS_KIND,
    ImportResult,
    import_file,
)
from ..repository import recent_imports

bp = Blueprint("imports", __name__)

KIND_FIELDS = (
    (ORDERS_KIND, "orders_files"),
    (TRANSACTIONS_KIND, "transactions_files"),
    (INVOICE_KIND, "invoice_files"),
)

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xlsm"}


def _save_uploads(files) -> list:
    """把上传文件落到临时目录，返回 [(原文件名, 临时路径)]。"""
    upload_dir = current_app.config["UPLOAD_DIR"]
    saved = []
    for storage in files:
        if not storage or not storage.filename:
            continue
        extension = os.path.splitext(storage.filename)[1].lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型：{storage.filename}（请使用 csv 或 xlsx）")
        safe = secure_filename(storage.filename) or "upload"
        temp_path = os.path.join(upload_dir, f"{uuid.uuid4().hex}_{safe}")
        storage.save(temp_path)
        saved.append((storage.filename, temp_path))
    return saved


@bp.route("/imports", methods=["GET", "POST"])
def index():
    conn = get_db()
    results = []
    errors = []
    issues = []

    if request.method == "POST":
        for kind, field in KIND_FIELDS:
            try:
                saved = _save_uploads(request.files.getlist(field))
            except ValueError as exc:
                errors.append(str(exc))
                continue

            merged = ImportResult(file_name="", file_kind=kind)
            for original_name, temp_path in saved:
                try:
                    single = import_file(conn, kind, temp_path)
                except Exception as exc:  # 单个文件失败不影响其它文件
                    errors.append(f"{original_name}：{exc}")
                    continue
                finally:
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
                single.file_name = original_name
                merged.file_name = merged.file_name or original_name
                merged.merge(single)
            if saved:
                results.append(merged)
                issues.extend(
                    {"file": merged.file_name, "kind": kind, **issue.as_dict()}
                    for issue in merged.issues
                )

    return render_template(
        "imports.html",
        kind_labels=KIND_LABELS,
        field_map={kind: field for kind, field in KIND_FIELDS},
        results=results,
        errors=errors,
        issues=issues,
        logs=recent_imports(conn, 20),
    )
