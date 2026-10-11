"""页面2：详情。"""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from ..db import get_db
from ..exporters import build_flow_workbook, export_filename, workbook_bytes
from ..repository import delete_cashflows, query_details, sum_amounts

bp = Blueprint("details", __name__)


def _filters():
    return request.args.get("item_id", "").strip(), request.args.get("order_id", "").strip()


@bp.route("/details")
def index():
    conn = get_db()
    item_id, order_id = _filters()
    rows = query_details(conn, item_id, order_id)
    return render_template(
        "details.html",
        rows=rows,
        total=sum_amounts(rows),
        filters={"item_id": item_id, "order_id": order_id},
        max_delete_rows=current_app.config["MAX_DELETE_ROWS"],
    )


@bp.route("/details/export")
def export():
    conn = get_db()
    item_id, order_id = _filters()
    rows = query_details(conn, item_id, order_id)
    workbook = build_flow_workbook(rows, "详情")
    prefix = "详情"
    if item_id:
        prefix += f"-{secure_filename(item_id)}"
    elif order_id:
        prefix += f"-{secure_filename(order_id)}"
    return send_file(
        workbook_bytes(workbook),
        as_attachment=True,
        download_name=export_filename(prefix),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/details/delete", methods=["POST"])
def delete():
    conn = get_db()
    cashflow_ids = request.form.getlist("cashflow_id")
    if not cashflow_ids:
        flash("没有选中任何行", "warning")
    elif len(cashflow_ids) > current_app.config["MAX_DELETE_ROWS"]:
        flash(
            f"一次最多删除 {current_app.config['MAX_DELETE_ROWS']} 行，当前选中 {len(cashflow_ids)} 行",
            "error",
        )
    else:
        deleted = delete_cashflows(conn, cashflow_ids)
        conn.commit()
        flash(f"已删除 {deleted} 行现金流", "success")

    item_id, order_id = _filters()
    arguments = {}
    if item_id:
        arguments["item_id"] = item_id
    if order_id:
        arguments["order_id"] = order_id
    return redirect(url_for("details.index", **arguments))
