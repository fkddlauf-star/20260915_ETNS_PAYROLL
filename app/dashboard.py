from flask import Blueprint, jsonify, render_template

from .auth import admin_required, current_user, login_required
from .db import query

bp = Blueprint("dashboard", __name__)


def _summary():
    totals = query(
        """
        SELECT
            (SELECT COUNT(*) FROM pr_source_files) AS file_count,
            (SELECT COUNT(*) FROM pr_source_records) AS record_count,
            (SELECT COUNT(*) FROM pr_review_items) AS review_count,
            (SELECT COUNT(*) FROM pr_review_items WHERE status = '신규') AS new_count,
            (SELECT COUNT(*) FROM pr_review_items WHERE status = '검토중') AS in_progress_count,
            (SELECT COUNT(*) FROM pr_review_items WHERE status = '해결완료') AS resolved_count,
            (SELECT COUNT(*) FROM pr_review_items WHERE status = '정상예외') AS exception_count,
            (SELECT COUNT(*) FROM pr_review_items WHERE review_type = '누락') AS missing_count,
            (SELECT COUNT(*) FROM pr_review_items WHERE review_type = '중복') AS duplicate_count,
            (SELECT COUNT(*) FROM pr_review_items WHERE review_type = '금액불일치') AS mismatch_count,
            (SELECT COALESCE(SUM(ABS(diff_amount)), 0) FROM pr_review_items WHERE review_type = '금액불일치') AS mismatch_total
        """,
        fetch="one",
    )
    total = totals["review_count"] or 0
    done = (totals["resolved_count"] or 0) + (totals["exception_count"] or 0)
    totals["completion_rate"] = round(done / total * 100, 1) if total else 0.0
    return totals


def _chart_data():
    by_type = query(
        "SELECT review_type, COUNT(*) AS cnt FROM pr_review_items GROUP BY review_type"
    )
    by_status = query(
        "SELECT status, COUNT(*) AS cnt FROM pr_review_items GROUP BY status"
    )
    by_dept = query(
        """
        SELECT COALESCE(department, '미분류') AS department, COUNT(*) AS cnt
        FROM pr_review_items GROUP BY department ORDER BY cnt DESC LIMIT 10
        """
    )
    monthly_trend = query(
        """
        SELECT period_year, period_month, COUNT(*) AS cnt
        FROM pr_review_items
        WHERE period_year IS NOT NULL
        GROUP BY period_year, period_month
        ORDER BY period_year, period_month
        """
    )
    return {
        "by_type": by_type,
        "by_status": by_status,
        "by_dept": by_dept,
        "monthly_trend": monthly_trend,
    }


@bp.route("/")
@login_required
def home():
    user = current_user()
    if user["role"] == "admin":
        return admin_home()
    return employee_home()


@bp.route("/admin")
@admin_required
def admin_home():
    return render_template("dashboard.html", summary=_summary(), charts=_chart_data())


@bp.route("/me")
@login_required
def employee_home():
    user = current_user()
    my_summary = query(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = '신규') AS new_count,
            COUNT(*) FILTER (WHERE status = '검토중') AS in_progress_count,
            COUNT(*) FILTER (WHERE status = '해결완료') AS resolved_count,
            COUNT(*) FILTER (WHERE status = '정상예외') AS exception_count
        FROM pr_review_items WHERE assignee_id = %s
        """,
        (user["id"],),
        fetch="one",
    )
    recent = query(
        """
        SELECT * FROM pr_review_items WHERE assignee_id = %s
        ORDER BY created_at DESC LIMIT 10
        """,
        (user["id"],),
    )
    return render_template("employee_home.html", summary=my_summary, recent=recent)


@bp.route("/api/summary")
@login_required
def api_summary():
    return jsonify(dict(_summary()))
