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
    # detail은 규칙 라벨 문구가 바뀌면 같이 바뀌는 설명 텍스트일 뿐이라, 동일 발견 여부를
    # 판단하는 중복 체크 키에서는 제외한다 (텍스트만 다르고 실질은 같은 항목이 재검증마다
    # 계속 새로 생기는 걸 방지).
    dup = query(
        """
        SELECT id FROM pr_review_items
        WHERE review_type = %s AND data_type = %s AND employee_id IS NOT DISTINCT FROM %s
          AND source_file_id IS NOT DISTINCT FROM %s
          AND compare_file_id IS NOT DISTINCT FROM %s
          AND period_year IS NOT DISTINCT FROM %s AND period_month IS NOT DISTINCT FROM %s
        """,
        (
            review_type,
            data_type,
            employee_id,
            source_file_id,
            compare_file_id,
            period_year,
            period_month,
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


EXCLUDE_EXEC = {"-"}


def _resolve_file(template_key):
    """template_key가 가리키는 파일을 찾는다. 데이터유형 필터는 룰의 data_type이 아니라
    그 템플릿 자신의 고유 data_type을 쓴다 (예: HR마스터는 '급여'로 업로드되지만
    '복리후생' 규칙의 기준 파일로도 쓰이므로, 룰의 data_type을 그대로 쓰면 못 찾는다)."""
    template = TEMPLATES.get(template_key)
    if not template:
        return None
    return _latest_file(template["file_match"], template.get("data_type"))


def _run_missing_rule(rule, names):
    base = _resolve_file(rule["base_template_key"])
    compare = _resolve_file(rule["compare_template_key"])
    if not base or not compare:
        return 0

    base_records = _records_for_file(base["id"])
    compare_records = _records_for_file(compare["id"])
    if rule["target_period_year"] is not None:
        compare_records = [
            r
            for r in compare_records
            if r.get("period_year") == rule["target_period_year"]
            and r.get("period_month") == rule["target_period_month"]
        ]

    period_year = rule["target_period_year"] or compare.get("period_year") or base.get("period_year")
    period_month = rule["target_period_month"] or compare.get("period_month") or base.get("period_month")

    created_count = 0
    for item in detect_missing(base_records, compare_records, exclude_keys=EXCLUDE_EXEC):
        from_base = item["missing_from"] == "compare"  # base엔 있는데 compare엔 없음
        created = _create_review_item(
            "누락",
            rule["data_type"],
            item["employee_id"],
            base["id"] if from_base else compare["id"],
            compare_file_id=compare["id"] if from_base else base["id"],
            period_year=period_year,
            period_month=period_month,
            detail=f"{rule['label']} — {'비교 파일' if from_base else '기준 파일'}에서 누락",
            names=names,
        )
        if created:
            created_count += 1
    return created_count


def _run_duplicate_rule(rule, names):
    base = _resolve_file(rule["base_template_key"])
    if not base:
        return 0

    key_columns = [c.strip() for c in (rule["key_columns"] or "").split(",") if c.strip()]
    if not key_columns:
        key_columns = ["employee_id"]

    records = _records_for_file(base["id"])
    created_count = 0
    for dup in detect_duplicates(records, key_columns):
        period_year = dup["key"].get("period_year") or base.get("period_year")
        period_month = dup["key"].get("period_month") or base.get("period_month")
        created = _create_review_item(
            "중복",
            rule["data_type"],
            dup["key"].get("employee_id"),
            base["id"],
            period_year=period_year,
            period_month=period_month,
            detail=f"{rule['label']} — 동일 키 {dup['count']}건 중복",
            names=names,
        )
        if created:
            created_count += 1
    return created_count


def _run_mismatch_rule(rule, names):
    base = _resolve_file(rule["base_template_key"])
    if not base:
        return 0
    tolerance = float(rule["amount_tolerance"] or 0)
    field_base = rule["amount_field_base"]
    field_compare = rule["amount_field_compare"]
    if not field_base or not field_compare:
        return 0

    records = _records_for_file(base["id"])
    created_count = 0

    if rule["compare_template_key"]:
        # 다른 파일과 사번 기준으로 매칭해서 비교 (현재 기본 규칙에는 없지만 확장 대비)
        compare = _resolve_file(rule["compare_template_key"])
        if not compare:
            return 0
        compare_records = _records_for_file(compare["id"])
        compare_by_id = {r["employee_id"]: r for r in compare_records if r.get("employee_id")}
        for r in records:
            other = compare_by_id.get(r.get("employee_id"))
            if not other:
                continue
            base_val, cmp_val = r.get(field_base), other.get(field_compare)
            if base_val is None or cmp_val is None:
                continue
            diff = base_val - cmp_val
            if abs(diff) > tolerance:
                created = _create_review_item(
                    "금액불일치", rule["data_type"], r.get("employee_id"), base["id"],
                    compare_file_id=compare["id"], expected_value=cmp_val, actual_value=base_val,
                    diff_amount=diff, detail=rule["label"], names=names,
                )
                if created:
                    created_count += 1
    else:
        # 같은 레코드(같은 파일) 안의 두 컬럼끼리 비교
        for r in records:
            base_val, cmp_val = r.get(field_base), r.get(field_compare)
            if base_val is None or cmp_val is None:
                continue
            diff = base_val - cmp_val
            if diff > tolerance:  # 실제값이 기준값을 초과하는 경우만 (예: 한도 초과)
                created = _create_review_item(
                    "금액불일치", rule["data_type"], r.get("employee_id"), base["id"],
                    period_year=r.get("period_year") or base.get("period_year"),
                    period_month=r.get("period_month") or base.get("period_month"),
                    expected_value=cmp_val, actual_value=base_val, diff_amount=diff,
                    detail=rule["label"], names=names,
                )
                if created:
                    created_count += 1
    return created_count


def run_all_validations():
    """활성화된 pr_review_rules를 순회하며 검증을 실행하고 review_items를 채운다."""
    names = _name_lookup()
    counts = {"missing": 0, "duplicate": 0, "mismatch": 0}

    rules = query("SELECT * FROM pr_review_rules WHERE is_active = TRUE ORDER BY id")
    for rule in rules:
        if rule["rule_type"] == "누락":
            counts["missing"] += _run_missing_rule(rule, names)
        elif rule["rule_type"] == "중복":
            counts["duplicate"] += _run_duplicate_rule(rule, names)
        elif rule["rule_type"] == "금액불일치":
            counts["mismatch"] += _run_mismatch_rule(rule, names)

    return counts
