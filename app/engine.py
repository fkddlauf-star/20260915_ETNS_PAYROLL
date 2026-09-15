"""파일 템플릿 정의 + 수집(ingest) + 검증 실행 오케스트레이션.

실제 넥스트라인 데이터 4종 + 시뮬레이션 복리후생 파일을 기준으로 한
템플릿을 코드로 등록해둔다. (규칙 커스터마이징 UI는 이번 단계 범위 밖)
"""

import json
import time

from .db import execute, get_db, query
from .validation import (
    detect_duplicates,
    detect_missing,
    normalize_amount,
    normalize_employee_id,
)

TEMPLATES = {
    "hr_master": {
        "label": "HR 마스터 (직원_근태_인사_데이터)",
        "data_type": "급여",
        "id_col": "사원번호",
        "name_col": "성명",
        "dept_col": "부서",
        "amount_cols": {"annual_salary": "연봉(원)", "monthly_salary": "월급여(원)"},
        "file_match": "직원_근태_인사",
    },
    "salary_detail": {
        "label": "급여상세 (임직원_급여_상세_데이터)",
        "data_type": "급여",
        "id_col": "사원번호",
        "name_col": "성명",
        "dept_col": "본부",
        "amount_cols": {
            "monthly_total": "월_지급합계(원)",
            "annual_contract_salary": "연봉(계약/원)",
        },
        "file_match": "임직원_급여_상세",
    },
    "monthly_payout": {
        "label": "월별 지급내역 (월별_인건비_이력_데이터)",
        "data_type": "급여",
        "id_col": "사원번호",
        "name_col": "성명",
        "dept_col": "본부",
        "amount_cols": {"monthly_total": "월_지급합계(원)"},
        "year_col": "연도",
        "month_col": "월",
        "file_match": "월별_인건비_이력",
    },
    "annual_salary": {
        "label": "연봉상세 - 만원단위 (임직원_연봉_데이터)",
        "data_type": "급여",
        "id_col": "사원번호",
        "name_col": "성명",
        "dept_col": "본부",
        "amount_cols": {"annual_salary_10k": "기본연봉(만원)"},
        "file_match": "임직원_연봉",
    },
    "benefits_payout": {
        "label": "복리후생 지급내역",
        "data_type": "복리후생",
        "id_col": "사번",
        "name_col": "성명",
        "dept_col": "부서",
        "amount_cols": {"benefit_amount": "지급액(원)", "benefit_limit": "한도액(원)"},
        "file_match": "복리후생",
    },
    "auto": {
        "label": "기타 (자동 인식 시도)",
        "data_type": "급여",
        "id_col": None,
        "name_col": None,
        "dept_col": None,
        "amount_cols": {},
        "file_match": None,
    },
}

ID_COL_CANDIDATES = ["사원번호", "사번", "employee_id", "EmployeeID"]


def _detect_id_column(columns):
    for cand in ID_COL_CANDIDATES:
        if cand in columns:
            return cand
    return None


def ingest_records(file_id, sheet_name, df, template_key):
    import pandas as pd  # 파일 업로드 처리 경로에서만 필요 (콜드스타트 시간 절약을 위해 지연 임포트)

    start = time.time()
    template = TEMPLATES.get(template_key) or TEMPLATES["auto"]
    id_col = template["id_col"] or _detect_id_column(df.columns)

    rows_read = 0
    error_count = 0
    error_detail = None

    for idx, row in df.iterrows():
        rows_read += 1
        raw = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}

        emp_id = normalize_employee_id(raw.get(id_col)) if id_col else None

        normalized = {"employee_id": emp_id}
        for logical, col in template["amount_cols"].items():
            if col in raw:
                normalized[logical] = normalize_amount(raw.get(col))
        if template.get("year_col") and template["year_col"] in raw:
            try:
                normalized["period_year"] = int(raw[template["year_col"]])
            except (TypeError, ValueError):
                normalized["period_year"] = None
        if template.get("month_col") and template["month_col"] in raw:
            try:
                normalized["period_month"] = int(raw[template["month_col"]])
            except (TypeError, ValueError):
                normalized["period_month"] = None
        if template["name_col"] and template["name_col"] in raw:
            normalized["name"] = raw[template["name_col"]]
        if template["dept_col"] and template["dept_col"] in raw:
            normalized["department"] = raw[template["dept_col"]]

        try:
            execute(
                """
                INSERT INTO pr_source_records
                    (source_file_id, sheet_name, row_number, employee_id, raw, normalized)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    file_id,
                    sheet_name,
                    int(idx) + 2,  # 헤더 다음 줄부터가 실제 1행이므로 +2
                    emp_id,
                    json.dumps(raw, default=str, ensure_ascii=False),
                    json.dumps(normalized, default=str, ensure_ascii=False),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            get_db().rollback()
            error_count += 1
            error_detail = str(exc)

    duration_ms = int((time.time() - start) * 1000)
    return {
        "rows_read": rows_read,
        "error_count": error_count,
        "error_detail": error_detail,
        "duration_ms": duration_ms,
    }


def _latest_file(file_match, data_type=None):
    sql = "SELECT * FROM pr_source_files WHERE file_name LIKE %s AND status = '완료'"
    params = [f"%{file_match}%"]
    if data_type:
        sql += " AND data_type = %s"
        params.append(data_type)
    sql += " ORDER BY uploaded_at DESC LIMIT 1"
    return query(sql, tuple(params), fetch="one")


def _records_for_file(source_file_id):
    rows = query(
        "SELECT row_number, normalized FROM pr_source_records WHERE source_file_id = %s",
        (source_file_id,),
    )
    out = []
    for r in rows:
        norm = r["normalized"] if isinstance(r["normalized"], dict) else json.loads(r["normalized"])
        norm["_row_number"] = r["row_number"]
        out.append(norm)
    return out


def _name_lookup():
    hr = _latest_file("직원_근태_인사")
    if not hr:
        return {}
    records = _records_for_file(hr["id"])
    return {
        r["employee_id"]: {"name": r.get("name"), "department": r.get("department")}
        for r in records
        if r.get("employee_id")
    }


def _create_review_item(
    review_type,
    data_type,
    employee_id,
    source_file_id,
    compare_file_id=None,
    period_year=None,
    period_month=None,
    expected_value=None,
    actual_value=None,
    diff_amount=None,
    detail=None,
    names=None,
):
    dup = query(
        """
        SELECT id FROM pr_review_items
        WHERE review_type = %s AND data_type = %s AND employee_id IS NOT DISTINCT FROM %s
          AND source_file_id IS NOT DISTINCT FROM %s
          AND compare_file_id IS NOT DISTINCT FROM %s
          AND period_year IS NOT DISTINCT FROM %s AND period_month IS NOT DISTINCT FROM %s
          AND detail IS NOT DISTINCT FROM %s
        """,
        (
            review_type,
            data_type,
            employee_id,
            source_file_id,
            compare_file_id,
            period_year,
            period_month,
            detail,
        ),
        fetch="one",
    )
    if dup:
        return False

    names = names or {}
    info = names.get(employee_id, {})
    execute(
        """
        INSERT INTO pr_review_items
            (review_type, data_type, period_year, period_month, employee_id, employee_name,
             department, source_file_id, compare_file_id, expected_value, actual_value,
             diff_amount, detail, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '신규')
        """,
        (
            review_type,
            data_type,
            period_year,
            period_month,
            employee_id,
            info.get("name"),
            info.get("department"),
            source_file_id,
            compare_file_id,
            str(expected_value) if expected_value is not None else None,
            str(actual_value) if actual_value is not None else None,
            diff_amount,
            detail,
        ),
    )
    return True


def run_all_validations():
    """등록된 실제 파일 조합에 대해 누락/중복/금액불일치를 실행하고 review_items를 채운다."""
    names = _name_lookup()
    counts = {"missing": 0, "duplicate": 0, "mismatch": 0}

    hr = _latest_file("직원_근태_인사")
    salary_detail = _latest_file("임직원_급여_상세")
    monthly_payout = _latest_file("월별_인건비_이력")
    annual_salary = _latest_file("임직원_연봉")
    benefits = _latest_file("복리후생")

    EXCLUDE_EXEC = {"-"}

    # --- 급여 Pair 1: HR 마스터 vs 급여상세 (누락) ---
    if hr and salary_detail:
        hr_records = _records_for_file(hr["id"])
        salary_records = _records_for_file(salary_detail["id"])
        for item in detect_missing(hr_records, salary_records, exclude_keys=EXCLUDE_EXEC):
            created = _create_review_item(
                "누락",
                "급여",
                item["employee_id"],
                hr["id"] if item["missing_from"] == "compare" else salary_detail["id"],
                compare_file_id=salary_detail["id"] if item["missing_from"] == "compare" else hr["id"],
                detail=f"{'급여상세' if item['missing_from']=='compare' else 'HR마스터'}에서 누락",
                names=names,
            )
            if created:
                counts["missing"] += 1

    # --- 급여 Pair 1b: 급여상세 vs 월별지급내역 (특정 월 기준 누락) ---
    if salary_detail and monthly_payout:
        salary_records = _records_for_file(salary_detail["id"])
        monthly_records = _records_for_file(monthly_payout["id"])
        target_month_records = [
            r for r in monthly_records if r.get("period_year") == 2025 and r.get("period_month") == 12
        ]
        for item in detect_missing(salary_records, target_month_records, exclude_keys=EXCLUDE_EXEC):
            created = _create_review_item(
                "누락",
                "급여",
                item["employee_id"],
                salary_detail["id"] if item["missing_from"] == "compare" else monthly_payout["id"],
                compare_file_id=monthly_payout["id"] if item["missing_from"] == "compare" else salary_detail["id"],
                period_year=2025,
                period_month=12,
                detail=f"{'월별지급내역(12월)' if item['missing_from']=='compare' else '급여상세'}에서 누락",
                names=names,
            )
            if created:
                counts["missing"] += 1

    # --- 급여 중복: 월별지급내역 내 (사번+연도+월) 중복 ---
    if monthly_payout:
        monthly_records = _records_for_file(monthly_payout["id"])
        for dup in detect_duplicates(monthly_records, ["employee_id", "period_year", "period_month"]):
            emp_id = dup["key"]["employee_id"]
            created = _create_review_item(
                "중복",
                "급여",
                emp_id,
                monthly_payout["id"],
                period_year=dup["key"]["period_year"],
                period_month=dup["key"]["period_month"],
                detail=f"동일 사번·기간 {dup['count']}건 중복",
                names=names,
            )
            if created:
                counts["duplicate"] += 1

    # 참고: 급여상세(연봉(계약/원)) vs 연봉상세(기본연봉(만원))는 실제 데이터 확인 결과
    # 임원 2명을 제외한 일반 직원은 두 금액이 애초에 다른 개념(계약연봉 vs 기본연봉)이라
    # 거의 전원이 불일치로 잡혀 검증 규칙으로 부적합함이 확인되어 이번 단계에서는 제외했다.
    # (아래 복리후생 한도초과 검증으로 금액불일치 시나리오를 시연한다)
    _ = (salary_detail, annual_salary)

    # --- 복리후생: 누락 / 중복 / 한도초과(금액불일치) ---
    if hr and benefits:
        hr_records = _records_for_file(hr["id"])
        benefit_records = _records_for_file(benefits["id"])

        b_year, b_month = benefits["period_year"], benefits["period_month"]

        for item in detect_missing(hr_records, benefit_records, exclude_keys=EXCLUDE_EXEC):
            if item["missing_from"] == "compare":
                created = _create_review_item(
                    "누락",
                    "복리후생",
                    item["employee_id"],
                    hr["id"],
                    compare_file_id=benefits["id"],
                    period_year=b_year,
                    period_month=b_month,
                    detail="복리후생 지급내역에서 누락",
                    names=names,
                )
                if created:
                    counts["missing"] += 1

        for dup in detect_duplicates(benefit_records, ["employee_id"]):
            emp_id = dup["key"]["employee_id"]
            created = _create_review_item(
                "중복",
                "복리후생",
                emp_id,
                benefits["id"],
                period_year=b_year,
                period_month=b_month,
                detail=f"동일 사번 복리후생 지급 {dup['count']}건 중복",
                names=names,
            )
            if created:
                counts["duplicate"] += 1

        for r in benefit_records:
            amt = r.get("benefit_amount")
            limit = r.get("benefit_limit")
            if amt is not None and limit is not None and amt > limit:
                created = _create_review_item(
                    "금액불일치",
                    "복리후생",
                    r.get("employee_id"),
                    benefits["id"],
                    period_year=b_year,
                    period_month=b_month,
                    expected_value=limit,
                    actual_value=amt,
                    diff_amount=amt - limit,
                    detail="직급별 한도 초과 지급",
                    names=names,
                )
                if created:
                    counts["mismatch"] += 1

    return counts
