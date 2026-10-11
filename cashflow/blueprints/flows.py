"""页面1：流水。"""

from __future__ import annotations

from flask import Blueprint, render_template, request, send_file
from werkzeug.utils import secure_filename

from ..db import get_db
from ..exporters import build_flow_workbook, export_filename, workbook_bytes
from ..money import parse_date_input
from ..repository import list_sellers, query_flows, sum_amounts

bp = Blueprint("flows", __name__)


def _filters():
    start = parse_date_input(request.args.get("start", ""))
    end = parse_date_input(request.args.get("end", ""))
    seller = request.args.get("seller", "").strip()
    return start, end, seller


@bp.route("/")
@bp.route("/flows")
def index():
    conn = get_db()
    start, end, seller = _filters()
    rows = query_flows(conn, start, end, seller)
    return render_template(
        "flows.html",
        rows=rows,
        total=sum_amounts(rows),
        sellers=[row["seller_name"] for row in list_sellers(conn)],
        filters={
            "start": request.args.get("start", "").strip(),
            "end": request.args.get("end", "").strip(),
            "seller": seller,
        },
    )


@bp.route("/flows/export")
def export():
    conn = get_db()
    start, end, seller = _filters()
    rows = query_flows(conn, start, end, seller)
    workbook = build_flow_workbook(rows, "流水")
    prefix = "流水"
    if seller:
        prefix += f"-{secure_filename(seller)}"
    return send_file(
        workbook_bytes(workbook),
        as_attachment=True,
        download_name=export_filename(prefix),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
