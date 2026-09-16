from flask import Blueprint, flash, redirect, render_template, request, url_for

from .auth import admin_required
from .db import execute, query
from .engine import TEMPLATES

bp = Blueprint("rules", __name__, url_prefix="/rules")

RULE_TYPES = ["누락", "중복", "금액불일치"]
DATA_TYPES = ["급여", "복리후생"]


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


def _read_rule_form(form):
    return {
        "rule_type": form.get("rule_type", "").strip(),
        "data_type": form.get("data_type", "").strip(),
        "label": form.get("label", "").strip(),
        "base_template_key": form.get("base_template_key") or None,
        "compare_template_key": form.get("compare_template_key") or None,
        "key_columns": form.get("key_columns", "").strip(),
        "amount_tolerance": form.get("amount_tolerance") or 0,
        "target_period_year": form.get("target_period_year") or None,
        "target_period_month": form.get("target_period_month") or None,
        "amount_field_base": form.get("amount_field_base") or None,
        "amount_field_compare": form.get("amount_field_compare") or None,
        "is_active": bool(form.get("is_active")),
    }


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new():
    if request.method == "POST":
        f = _read_rule_form(request.form)
        if not f["rule_type"] or not f["data_type"] or not f["label"] or not f["base_template_key"]:
            flash("유형, 데이터유형, 이름, 기준 파일은 필수입니다.")
            return redirect(url_for("rules.new"))

        execute(
            """
            INSERT INTO pr_review_rules
                (rule_type, data_type, label, key_columns, amount_tolerance, is_active,
                 base_template_key, compare_template_key, target_period_year, target_period_month,
                 amount_field_base, amount_field_compare)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                f["rule_type"], f["data_type"], f["label"], f["key_columns"], f["amount_tolerance"],
                f["is_active"], f["base_template_key"], f["compare_template_key"],
                f["target_period_year"], f["target_period_month"],
                f["amount_field_base"], f["amount_field_compare"],
            ),
        )
        flash(f"새 검증 규칙 '{f['label']}'을(를) 등록했습니다.")
        return redirect(url_for("rules.index"))

    return render_template(
        "rule_form.html", rule=None, rule_types=RULE_TYPES, data_types=DATA_TYPES, templates=TEMPLATES
    )


@bp.route("/<int:rule_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(rule_id):
    rule = query("SELECT * FROM pr_review_rules WHERE id = %s", (rule_id,), fetch="one")
    if not rule:
        flash("존재하지 않는 규칙입니다.")
        return redirect(url_for("rules.index"))

    if request.method == "POST":
        f = _read_rule_form(request.form)
        if not f["rule_type"] or not f["data_type"] or not f["label"] or not f["base_template_key"]:
            flash("유형, 데이터유형, 이름, 기준 파일은 필수입니다.")
            return redirect(url_for("rules.edit", rule_id=rule_id))

        execute(
            """
            UPDATE pr_review_rules
            SET rule_type = %s, data_type = %s, label = %s, key_columns = %s, amount_tolerance = %s,
                is_active = %s, base_template_key = %s, compare_template_key = %s,
                target_period_year = %s, target_period_month = %s,
                amount_field_base = %s, amount_field_compare = %s
            WHERE id = %s
            """,
            (
                f["rule_type"], f["data_type"], f["label"], f["key_columns"], f["amount_tolerance"],
                f["is_active"], f["base_template_key"], f["compare_template_key"],
                f["target_period_year"], f["target_period_month"],
                f["amount_field_base"], f["amount_field_compare"], rule_id,
            ),
        )
        flash(f"검증 규칙 '{f['label']}'을(를) 저장했습니다.")
        return redirect(url_for("rules.index"))

    return render_template(
        "rule_form.html", rule=rule, rule_types=RULE_TYPES, data_types=DATA_TYPES, templates=TEMPLATES
    )
