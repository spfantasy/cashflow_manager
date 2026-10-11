"""页面5：手工帐。"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, flash, render_template, request

from ..allocations import CASHFLOW_SOURCE_MANUAL
from ..db import get_db
from ..money import parse_date_input, parse_money, to_db
from ..repository import insert_cashflow, query_details, sum_amounts

bp = Blueprint("manual", __name__)


def build_manual_cashflow_id(item_id: str) -> str:
    """item_id 开头 + 毫秒级 datetime：168063599242-20260117_143022123。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-3]
    return f"{item_id}-{stamp}"


@bp.route("/manual", methods=["GET", "POST"])
def index():
    conn = get_db()
    form = {"item_id": "", "amount": "", "cashflow_date": "", "reminder": ""}
    created = None

    if request.method == "POST":
        form = {
            "item_id": request.form.get("item_id", "").strip(),
            "amount": request.form.get("amount", "").strip(),
            "cashflow_date": request.form.get("cashflow_date", "").strip(),
            "reminder": request.form.get("reminder", "").strip(),
        }
        item_id = form["item_id"]
        amount = parse_money(form["amount"])
        cashflow_date = parse_date_input(form["cashflow_date"])

        if not item_id:
            flash("物品编号必须填写", "error")
        elif amount is None:
            flash("金额必须填写且为数字", "error")
        elif not cashflow_date:
            flash("日期必须填写", "error")
        else:
            cashflow_id = build_manual_cashflow_id(item_id)
            if insert_cashflow(
                conn,
                {
                    "cashflow_id": cashflow_id,
                    "item_id": item_id,
                    "order_id": "",
                    "cashflow_source": CASHFLOW_SOURCE_MANUAL,
                    "cashflow_type": CASHFLOW_SOURCE_MANUAL,
                    "amount": to_db(amount),
                    "cashflow_date": cashflow_date,
                    "reminder": form["reminder"],
                    "source_file": "",
                },
            ):
                conn.commit()
                created = cashflow_id
                flash(f"已创建手工帐 {cashflow_id}", "success")
                form = {"item_id": "", "amount": "", "cashflow_date": "", "reminder": ""}
            else:
                flash(f"现金流 {cashflow_id} 已存在，未重复写入", "warning")

    recent = query_details(conn, item_id=form["item_id"]) if form["item_id"] else []
    return render_template(
        "manual.html",
        form=form,
        created=created,
        recent=recent[:200],
        recent_total=sum_amounts(recent),
    )
