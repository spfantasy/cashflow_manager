"""页面6：配置（卖家列表、匹配正则、是否参与会员费均摊）。"""

from __future__ import annotations

import re

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..db import get_db
from ..repository import (
    PROTECTED_SELLERS,
    delete_seller,
    list_sellers,
    rematch_sellers,
    save_seller,
)

bp = Blueprint("settings", __name__)


@bp.route("/settings")
def index():
    conn = get_db()
    return render_template(
        "settings.html",
        sellers=list_sellers(conn),
        protected=PROTECTED_SELLERS,
    )


@bp.route("/settings/seller/save", methods=["POST"])
def save():
    conn = get_db()
    seller_id = request.form.get("seller_id", "").strip()
    seller_name = request.form.get("seller_name", "").strip()
    match_regex = request.form.get("match_regex", "").strip()
    share_membership = request.form.get("share_membership") == "1"
    sort_order = request.form.get("sort_order", "100").strip() or "100"

    if match_regex:
        try:
            re.compile(match_regex)
        except re.error as exc:
            flash(f"正则表达式无效：{exc}", "error")
            return redirect(url_for("settings.index"))

    try:
        save_seller(
            conn,
            seller_name=seller_name,
            match_regex=match_regex,
            share_membership=share_membership,
            sort_order=int(sort_order) if sort_order.isdigit() else 100,
            seller_id=int(seller_id) if seller_id.isdigit() else None,
        )
        conn.commit()
        flash(f"已保存用户「{seller_name}」的配置", "success")
    except Exception as exc:
        conn.rollback()
        flash(str(exc), "error")
    return redirect(url_for("settings.index"))


@bp.route("/settings/seller/delete", methods=["POST"])
def delete():
    conn = get_db()
    seller_id = request.form.get("seller_id", "").strip()
    try:
        delete_seller(conn, int(seller_id))
        conn.commit()
        flash("已删除该用户配置", "success")
    except Exception as exc:
        conn.rollback()
        flash(str(exc), "error")
    return redirect(url_for("settings.index"))


@bp.route("/settings/rematch", methods=["POST"])
def rematch():
    conn = get_db()
    changed = rematch_sellers(conn)
    conn.commit()
    flash(f"已按当前配置重新匹配，共更新 {changed} 个物品的用户（人工调整过的物品已跳过）", "success")
    return redirect(url_for("settings.index"))
