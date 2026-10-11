"""页面4：刊登调整（调整某个 item 的 seller_name）。"""

from __future__ import annotations

from flask import Blueprint, flash, render_template, request

from ..db import get_db
from ..repository import get_item, list_sellers, update_seller_name

bp = Blueprint("listings", __name__)


@bp.route("/listings", methods=["GET", "POST"])
def index():
    conn = get_db()
    item_id = request.form.get("item_id", request.args.get("item_id", "")).strip()

    if request.method == "POST":
        seller_name = request.form.get("seller_name", "").strip()
        if not item_id or not seller_name:
            flash("物品编号和用户名都必须填写", "error")
        elif update_seller_name(conn, item_id, seller_name):
            conn.commit()
            flash(f"物品 {item_id} 的用户已调整为「{seller_name}」", "success")
        else:
            flash(f"没有找到物品 {item_id}", "error")

    item = get_item(conn, item_id) if item_id else None
    return render_template(
        "listings.html",
        item=item,
        item_id=item_id,
        sellers=[row["seller_name"] for row in list_sellers(conn)],
    )
