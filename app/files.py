import io
import os
import time
import uuid
from urllib.parse import quote

import pandas as pd
from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from .auth import admin_required, current_user, login_required
from .db import execute, query
from .engine import TEMPLATES, ingest_records, run_all_validations
from .storage import download_file, upload_file

bp = Blueprint("files", __name__, url_prefix="/files")

ALLOWED_EXTENSIONS = {".xlsx", ".csv"}
CONTENT_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
}


@bp.route("/")
@login_required
def index():
    files = query("SELECT * FROM pr_source_files ORDER BY uploaded_at DESC")
    return render_template("files.html", files=files)


@bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        file = request.files.get("file")
        data_type = request.form.get("data_type", "").strip()
        period_year = request.form.get("period_year") or None
        period_month = request.form.get("period_month") or None
        department = request.form.get("department", "").strip()
        description = request.form.get("description", "").strip()

        if not file or file.filename == "":
            flash("업로드할 파일을 선택해주세요.")
            return redirect(url_for("files.upload"))

        filename = os.path.basename(file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            flash("Excel(.xlsx) 또는 CSV(.csv) 파일만 업로드할 수 있습니다.")
            return redirect(url_for("files.upload"))

        if not data_type:
            flash("데이터 유형을 선택해주세요.")
            return redirect(url_for("files.upload"))

        existing = query(
            """
            SELECT id FROM pr_source_files
            WHERE file_name = %s AND data_type = %s
              AND period_year IS NOT DISTINCT FROM %s
              AND period_month IS NOT DISTINCT FROM %s
            """,
            (filename, data_type, period_year, period_month),
            fetch="one",
        )
        if existing:
            flash("동일한 파일명·데이터유형·기간의 파일이 이미 업로드되어 있습니다.")
            return redirect(url_for("files.upload"))

        user = current_user()
        # Supabase Storage 오브젝트 경로는 원본 파일명(한글 포함)과 무관하게 ASCII로 생성해
        # 인코딩/특수문자 문제를 피한다. 원본 이름은 file_name 컬럼에 그대로 보존.
        storage_path = f"{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
        upload_file(storage_path, file.read(), CONTENT_TYPES.get(ext, "application/octet-stream"))

        row = execute(
            """
            INSERT INTO pr_source_files
                (file_name, stored_filename, data_type, period_year, period_month, department,
                 description, uploaded_by, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '업로드')
            RETURNING id
            """,
            (
                filename,
                storage_path,
                data_type,
                period_year,
                period_month,
                department,
                description,
                user["id"],
            ),
            returning=True,
        )
        return redirect(url_for("files.configure", file_id=row["id"]))

    return render_template("upload.html", templates=TEMPLATES)


@bp.route("/<int:file_id>/configure", methods=["GET", "POST"])
@login_required
def configure(file_id):
    source_file = query("SELECT * FROM pr_source_files WHERE id = %s", (file_id,), fetch="one")
    if not source_file:
        flash("파일을 찾을 수 없습니다.")
        return redirect(url_for("files.index"))

    storage_path = source_file["stored_filename"]
    is_xlsx = storage_path and storage_path.lower().endswith(".xlsx")

    sheet_names = []
    if is_xlsx:
        try:
            sheet_names = pd.ExcelFile(io.BytesIO(download_file(storage_path))).sheet_names
        except Exception as exc:  # noqa: BLE001
            flash(f"엑셀 파일을 읽는 중 오류가 발생했습니다: {exc}")

    if request.method == "POST":
        template_key = request.form.get("template_key")
        sheet_name = request.form.get("sheet_name") or None

        try:
            raw_bytes = download_file(storage_path)
            if is_xlsx:
                df = pd.read_excel(io.BytesIO(raw_bytes), sheet_name=sheet_name, dtype=str)
            else:
                df = pd.read_csv(io.BytesIO(raw_bytes), dtype=str, encoding="utf-8-sig")
        except Exception as exc:  # noqa: BLE001
            execute(
                "UPDATE pr_source_files SET status = '실패', error_message = %s WHERE id = %s",
                (str(exc), file_id),
            )
            flash(f"파일 처리에 실패했습니다: {exc}")
            return redirect(url_for("files.index"))

        result = ingest_records(file_id, sheet_name or "Sheet1", df, template_key)

        status = "완료" if result["error_count"] == 0 else "실패"
        execute(
            """
            UPDATE pr_source_files
            SET status = %s, row_count = %s, error_message = %s
            WHERE id = %s
            """,
            (status, result["rows_read"], result.get("error_detail"), file_id),
        )
        execute(
            """
            INSERT INTO pr_processing_jobs
                (source_file_id, status, rows_read, error_count, duration_ms, error_detail)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                file_id,
                status,
                result["rows_read"],
                result["error_count"],
                result["duration_ms"],
                result.get("error_detail"),
            ),
        )
        flash(f"파일 처리 완료: {result['rows_read']}건 저장됨")
        return redirect(url_for("files.index"))

    return render_template(
        "configure.html", source_file=source_file, sheet_names=sheet_names, templates=TEMPLATES,
    )


@bp.route("/run-validation", methods=["POST"])
@admin_required
def run_validation():
    summary = run_all_validations()
    flash(
        "검증 실행 완료 — 신규 등록: 누락 {missing}건, 중복 {duplicate}건, "
        "금액불일치 {mismatch}건".format(**summary)
    )
    return redirect(url_for("dashboard.admin_home"))


@bp.route("/<int:file_id>/download")
@admin_required
def download(file_id):
    source_file = query("SELECT * FROM pr_source_files WHERE id = %s", (file_id,), fetch="one")
    if not source_file or not source_file["stored_filename"]:
        flash("원본 파일을 찾을 수 없습니다.")
        return redirect(url_for("files.index"))

    ext = os.path.splitext(source_file["stored_filename"])[1].lower()
    data = download_file(source_file["stored_filename"])
    encoded_name = quote(source_file["file_name"])
    return Response(
        data,
        mimetype=CONTENT_TYPES.get(ext, "application/octet-stream"),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"
        },
    )
