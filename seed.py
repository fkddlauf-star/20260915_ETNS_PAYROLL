"""최초 데모 데이터 적재 스크립트.

- 관리자/조직원(검토자) 계정 생성
- 실제 넥스트라인 급여 데이터 4종을 업로드 파일로 등록 + 파싱
- 정책 문서 기반 복리후생 지급내역을 시뮬레이션 생성해 업로드 파일로 등록
- 검증 엔진 실행 → 검토 대상 생성
- 신규 항목을 조직원 계정에 라운드로빈 배정

원본 데이터(data/ 폴더)는 읽기만 하고 그대로 복사해 Supabase Storage에 저장한다 (수정 없음).
"""

import io
import os
import time
import uuid

import pandas as pd
from werkzeug.security import generate_password_hash

from app import create_app
from app.db import execute, query
from app.engine import ingest_records, run_all_validations
from app.storage import upload_file

DATA_DIR = r"C:\workspace_claude\11_nextline_practice\data"

REAL_FILES = [
    {
        "path": os.path.join(DATA_DIR, "직원_근태_인사_데이터.xlsx"),
        "data_type": "급여",
        "template_key": "hr_master",
        "sheet_name": "직원근태인사데이터",
        "period_year": None,
        "period_month": None,
        "description": "HR 마스터 (정본)",
    },
    {
        "path": os.path.join(DATA_DIR, "임직원_급여_상세_데이터.xlsx"),
        "data_type": "급여",
        "template_key": "salary_detail",
        "sheet_name": "급여상세",
        "period_year": 2025,
        "period_month": 12,
        "description": "12월 급여상세",
    },
    {
        "path": os.path.join(DATA_DIR, "월별_인건비_이력_데이터.xlsx"),
        "data_type": "급여",
        "template_key": "monthly_payout",
        "sheet_name": "월별_지급내역",
        "period_year": 2025,
        "period_month": None,
        "description": "2025년 월별 지급내역 (전체월)",
    },
    {
        "path": os.path.join(DATA_DIR, "임직원_연봉_데이터.xlsx"),
        "data_type": "급여",
        "template_key": "annual_salary",
        "sheet_name": "연봉상세",
        "period_year": 2025,
        "period_month": None,
        "description": "2025년 연봉상세 (만원 단위)",
    },
]

GRADE_LIMITS = {
    "사원": 1_000_000,
    "주임": 1_000_000,
    "대리": 1_200_000,
    "과장": 1_500_000,
    "차장": 1_500_000,
    "부장": 2_000_000,
    "팀장": 2_000_000,
    "그룹장": 2_000_000,
    "본부장": 2_000_000,
}


def register_and_ingest(admin_id, spec):
    file_name = os.path.basename(spec["path"])
    existing = query(
        "SELECT id FROM pr_source_files WHERE file_name = %s AND data_type = %s",
        (file_name, spec["data_type"]),
        fetch="one",
    )
    if existing:
        print(f"  - 이미 등록됨, 건너뜀: {file_name}")
        return

    ext = os.path.splitext(file_name)[1].lower()
    saved_name = f"{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
    with open(spec["path"], "rb") as fh:
        upload_file(
            saved_name,
            fh.read(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    row = execute(
        """
        INSERT INTO pr_source_files
            (file_name, stored_filename, data_type, period_year, period_month, description, uploaded_by, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, '업로드')
        RETURNING id
        """,
        (
            file_name,
            saved_name,
            spec["data_type"],
            spec["period_year"],
            spec["period_month"],
            spec["description"],
            admin_id,
        ),
        returning=True,
    )
    file_id = row["id"]

    df = pd.read_excel(spec["path"], sheet_name=spec["sheet_name"], dtype=str)
    result = ingest_records(file_id, spec["sheet_name"], df, spec["template_key"])
    status = "완료" if result["error_count"] == 0 else "실패"
    execute(
        "UPDATE pr_source_files SET status = %s, row_count = %s WHERE id = %s",
        (status, result["rows_read"], file_id),
    )
    print(f"  - {file_name}: {result['rows_read']}건 적재 완료")


def build_benefits_file(admin_id):
    file_name = "복리후생_지급내역_시뮬레이션.xlsx"
    existing = query(
        "SELECT id FROM pr_source_files WHERE file_name = %s", (file_name,), fetch="one"
    )
    if existing:
        print("  - 이미 등록됨, 건너뜀: 복리후생 지급내역")
        return

    hr = pd.read_excel(
        os.path.join(DATA_DIR, "직원_근태_인사_데이터.xlsx"),
        sheet_name="직원근태인사데이터",
        dtype=str,
    )

    rows = []
    for i, r in hr.iterrows():
        emp_id = r["사원번호"]
        grade = r.get("직급", "사원")
        limit = GRADE_LIMITS.get(grade, 1_000_000)

        # 의도적 이상치 시딩: 10명마다 하나씩 순환 (초과지급 / 중복 / 누락)
        anomaly = i % 25

        if anomaly == 1:
            continue  # 누락 케이스: 이 사번은 복리후생 파일에서 아예 제외

        payout = limit
        if anomaly == 2:
            payout = int(limit * 1.4)  # 한도 초과 지급 (금액불일치)

        rows.append(
            {
                "사번": emp_id,
                "성명": r["성명"],
                "부서": r.get("부서"),
                "직급": grade,
                "항목": "카페테리아 포인트",
                "지급액(원)": payout,
                "한도액(원)": limit,
                "지급일": "2025-12-15",
            }
        )
        if anomaly == 3:
            # 중복 지급 케이스: 동일 사번 행을 한 번 더 추가
            rows.append(
                {
                    "사번": emp_id,
                    "성명": r["성명"],
                    "부서": r.get("부서"),
                    "직급": grade,
                    "항목": "카페테리아 포인트(중복입력)",
                    "지급액(원)": payout,
                    "한도액(원)": limit,
                    "지급일": "2025-12-15",
                }
            )

    df = pd.DataFrame(rows)
    saved_name = f"{int(time.time())}_{uuid.uuid4().hex[:8]}.xlsx"
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="복리후생지급내역")
    upload_file(
        saved_name,
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    row = execute(
        """
        INSERT INTO pr_source_files
            (file_name, stored_filename, data_type, period_year, period_month, description, uploaded_by, status)
        VALUES (%s, %s, '복리후생', 2025, 12, %s, %s, '업로드')
        RETURNING id
        """,
        (file_name, saved_name, "정책 기반 시뮬레이션 데이터 (실제 원장 파일 없음)", admin_id),
        returning=True,
    )
    file_id = row["id"]
    result = ingest_records(file_id, "복리후생지급내역", df, "benefits_payout")
    execute(
        "UPDATE pr_source_files SET status = '완료', row_count = %s WHERE id = %s",
        (result["rows_read"], file_id),
    )
    print(f"  - {file_name}: {result['rows_read']}건 적재 완료 (시뮬레이션)")


def ensure_users():
    admin = query("SELECT * FROM pr_users WHERE username = 'admin'", fetch="one")
    if not admin:
        row = execute(
            """
            INSERT INTO pr_users (username, password_hash, display_name, role, is_active)
            VALUES ('admin', %s, '김관리', 'admin', TRUE) RETURNING id
            """,
            (generate_password_hash("admin1234!"),),
            returning=True,
        )
        admin_id = row["id"]
        print("  - 관리자 계정 생성: admin / admin1234!")
    else:
        admin_id = admin["id"]
        print("  - 관리자 계정 이미 존재")

    reviewer_ids = []
    for uname, name in [("reviewer1", "박검토"), ("reviewer2", "이확인")]:
        existing = query("SELECT id FROM pr_users WHERE username = %s", (uname,), fetch="one")
        if existing:
            reviewer_ids.append(existing["id"])
            continue
        row = execute(
            """
            INSERT INTO pr_users (username, password_hash, display_name, role, is_active)
            VALUES (%s, %s, %s, 'employee', TRUE) RETURNING id
            """,
            (uname, generate_password_hash("review1234!"), name),
            returning=True,
        )
        reviewer_ids.append(row["id"])
        print(f"  - 조직원(검토자) 계정 생성: {uname} / review1234!")

    return admin_id, reviewer_ids


def auto_assign(reviewer_ids):
    unassigned = query(
        "SELECT id FROM pr_review_items WHERE assignee_id IS NULL ORDER BY id"
    )
    for idx, item in enumerate(unassigned):
        reviewer_id = reviewer_ids[idx % len(reviewer_ids)]
        execute(
            "UPDATE pr_review_items SET assignee_id = %s WHERE id = %s",
            (reviewer_id, item["id"]),
        )
    print(f"  - 신규 검토 항목 {len(unassigned)}건 자동 배정 완료")


def main():
    app = create_app()
    with app.app_context():
        print("[1/4] 계정 생성")
        admin_id, reviewer_ids = ensure_users()

        print("[2/4] 실제 급여 데이터 파일 등록/적재")
        for spec in REAL_FILES:
            register_and_ingest(admin_id, spec)

        print("[3/4] 복리후생 지급내역 시뮬레이션 생성")
        build_benefits_file(admin_id)

        print("[4/4] 검증 실행 + 자동 배정")
        counts = run_all_validations()
        print(f"  - 검증 결과: {counts}")
        auto_assign(reviewer_ids)

    print("\n완료. admin / admin1234! 로 로그인해 대시보드를 확인하세요.")


if __name__ == "__main__":
    main()
