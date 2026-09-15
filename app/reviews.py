import io

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from .auth import current_user, login_required
from .db import execute, query

bp = Blueprint("reviews", __name__, url_prefix="/reviews")

STATUS_CHOICES = ["신규", "검토중", "해결완료", "정상예외"]


def _build_filters(args, user):
    where = ["1=1"]
    params = []

    if user["role"] != "admin":
        where.append("assignee_id = %s")
        params.append(user["id"])

    if args.get("q"):
        where.append("(employee_id ILIKE %s OR employee_name ILIKE %s)")
        like = f"%{args['q']}%"
        params.extend([like, like])
    if args.get("data_type"):
        where.append("data_type = %s")
        params.append(args["data_type"])
    if args.get("review_type"):
        where.append("review_type = %s")
        params.append(args["review_type"])
    if args.get("status"):
        where.append("status = %s")
        params.append(args["status"])
    if args.get("assignee_id") and user["role"] == "admin":
        where.append("assignee_id = %s")
        params.append(args["assignee_id"])
    if args.get("period_year"):
        where.append("period_year = %s")
        params.append(args["period_year"])
    if args.get("period_month"):
        where.append("period_month = %s")
        params.append(args["period_month"])

    return " AND ".join(where), params


@bp.route("/")
@login_required
def index():
    user = current_user()
    where, params = _build_filters(request.args, user)
    sort = request.args.get("sort", "created_at")
    sort_col = {"created_at": "created_at", "diff_amount": "diff_amount"}.get(sort, "created_at")

    items = query(
        f"""
        SELECT ri.*, u.display_name AS assignee_name, sf.file_name AS source_file_name
        FROM pr_review_items ri
        LEFT JOIN pr_users u ON u.id = ri.assignee_id
        LEFT JOIN pr_source_files sf ON sf.id = ri.source_file_id
        WHERE {where}
        ORDER BY {sort_col} DESC NULLS LAST
        LIMIT 300
        """,
        tuple(params),
    )
    assignees = query("SELECT id, display_name FROM pr_users WHERE role = 'employee' ORDER BY display_name")
    return render_template(
        "review_list.html", items=items, assignees=assignees, statuses=STATUS_CHOICES, filters=request.args
    )


@bp.route("/<int:item_id>")
@login_required
def detail(item_id):
    user = current_user()
    item = query(
        """
        SELECT ri.*, u.display_name AS assignee_name,
               sf.file_name AS source_file_name, cf.file_name AS compare_file_name
        FROM pr_review_items ri
        LEFT JOIN pr_users u ON u.id = ri.assignee_id
        LEFT JOIN pr_source_files sf ON sf.id = ri.source_file_id
        LEFT JOIN pr_source_files cf ON cf.id = ri.compare_file_id
        WHERE ri.id = %s
        """,
        (item_id,),
        fetch="one",
    )
    if not item:
        flash("검토 항목을 찾을 수 없습니다.")
        return redirect(url_for("reviews.index"))
    if user["role"] != "admin" and item["assignee_id"] != user["id"]:
        flash("배정되지 않은 검토 항목입니다.")
        return redirect(url_for("reviews.index"))

    history = query(
        """
        SELECT h.*, u.display_name AS changed_by_name
        FROM pr_review_history h
        LEFT JOIN pr_users u ON u.id = h.changed_by
        WHERE h.review_item_id = %s
        ORDER BY h.changed_at DESC
        """,
        (item_id,),
    )
    assignees = query("SELECT id, display_name FROM pr_users WHERE role = 'employee' ORDER BY display_name")
    return render_template(
        "review_detail.html", item=item, history=history, statuses=STATUS_CHOICES, assignees=assignees
    )


@bp.route("/<int:item_id>/update", methods=["POST"])
@login_required
def update(item_id):
    user = current_user()
    item = query("SELECT * FROM pr_review_items WHERE id = %s", (item_id,), fetch="one")
    if not item:
        flash("검토 항목을 찾을 수 없습니다.")
        return redirect(url_for("reviews.index"))
    if user["role"] != "admin" and item["assignee_id"] != user["id"]:
        flash("배정되지 않은 검토 항목입니다.")
        return redirect(url_for("reviews.index"))

    new_status = request.form.get("status")
    new_comment = request.form.get("comment", "")
    new_assignee = request.form.get("assignee_id") or None

    if new_status and new_status != item["status"]:
        execute(
            """
            INSERT INTO pr_review_history (review_item_id, changed_by, field_changed, old_value, new_value)
            VALUES (%s, %s, 'status', %s, %s)
            """,
            (item_id, user["id"], item["status"], new_status),
        )
    if new_comment and new_comment != (item["comment"] or ""):
        execute(
            """
            INSERT INTO pr_review_history (review_item_id, changed_by, field_changed, old_value, new_value, comment)
            VALUES (%s, %s, 'comment', %s, %s, %s)
            """,
            (item_id, user["id"], item["comment"], new_comment, new_comment),
        )
    if user["role"] == "admin" and str(new_assignee or "") != str(item["assignee_id"] or ""):
        execute(
            """
            INSERT INTO pr_review_history (review_item_id, changed_by, field_changed, old_value, new_value)
            VALUES (%s, %s, 'assignee_id', %s, %s)
            """,
            (item_id, user["id"], item["assignee_id"], new_assignee),
        )

    execute(
        """
        UPDATE pr_review_items
        SET status = %s, comment = %s, assignee_id = %s, updated_at = NOW()
        WHERE id = %s
        """,
        (new_status or item["status"], new_comment, new_assignee, item_id),
    )
    flash("검토 항목이 저장되었습니다.")
    return redirect(url_for("reviews.detail", item_id=item_id))


@bp.route("/export")
@login_required
def export():
    import pandas as pd  # 엑셀 내보내기 경로에서만 필요 (콜드스타트 시간 절약을 위해 지연 임포트)

    user = current_user()
    where, params = _build_filters(request.args, user)
    items = query(
        f"""
        SELECT id AS 검토ID, review_type AS 검토유형, data_type AS 데이터유형,
               period_year AS 연도, period_month AS 월, employee_id AS 사번,
               employee_name AS 성명, department AS 부서, expected_value AS 기준값,
               actual_value AS 실제값, diff_amount AS 차액, status AS 검토상태,
               comment AS 검토의견, created_at AS 등록일시, updated_at AS 수정일시
        FROM pr_review_items
        WHERE {where}
        ORDER BY created_at DESC
        """,
        tuple(params),
    )
    df = pd.DataFrame(items)
    for col in ("등록일시", "수정일시"):
        if col in df.columns:
            df[col] = df[col].apply(lambda v: v.strftime("%Y-%m-%d %H:%M") if v else None)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="검토결과")
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name="검토결과.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
