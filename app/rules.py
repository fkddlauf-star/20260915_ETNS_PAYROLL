from flask import Blueprint, flash, redirect, render_template, request, url_for

from .auth import admin_required
from .db import execute, query
from .engine import TEMPLATES

bp = Blueprint("rules", __name__, url_prefix="/rules")


@bp.route("/")
@admin_required
def index():
    rules = query("SELECT * FROM pr_review_rules ORDER BY id")
    return render_template("rules.html", rules=rules, templates=TEMPLATES)


@bp.route("/<int:rule_id>/update", methods=["POST"])
@admin_required
def update(rule_id):
    key_columns = request.form.get("key_columns", "").strip()
    amount_tolerance = request.form.get("amount_tolerance") or 0
    target_period_year = request.form.get("target_period_year") or None
    target_period_month = request.form.get("target_period_month") or None

    execute(
        """
        UPDATE pr_review_rules
        SET key_columns = %s, amount_tolerance = %s,
            target_period_year = %s, target_period_month = %s
        WHERE id = %s
        """,
        (key_columns, amount_tolerance, target_period_year, target_period_month, rule_id),
    )
    flash("검증 규칙이 저장되었습니다.")
    return redirect(url_for("rules.index"))


@bp.route("/<int:rule_id>/toggle", methods=["POST"])
@admin_required
def toggle(rule_id):
    execute("UPDATE pr_review_rules SET is_active = NOT is_active WHERE id = %s", (rule_id,))
    return redirect(url_for("rules.index"))
