"""검증 규칙 엔진: 누락 / 중복 / 금액불일치.

각 함수는 이미 정규화된 레코드(dict의 list)를 입력받아 순수하게 동작한다.
DB 저장은 seed.py 또는 reviews.py에서 결과를 받아 처리한다.
"""


def normalize_employee_id(value):
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def normalize_amount(value):
    """콤마/원 접미사가 섞인 금액 문자열도 처리, 빈 값과 0을 구분해서 None 반환."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text == "" or text == "-":
        return None
    text = text.replace(",", "").replace("원", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return None


def detect_missing(base_records, compare_records, key="employee_id", exclude_keys=None):
    """base에는 있는데 compare에는 없는 키, 그리고 그 반대를 각각 찾는다.

    반환: [{"employee_id": ..., "missing_from": "compare"|"base"}, ...]
    """
    exclude_keys = exclude_keys or set()
    base_keys = {r[key] for r in base_records if r.get(key) and r[key] not in exclude_keys}
    compare_keys = {
        r[key] for r in compare_records if r.get(key) and r[key] not in exclude_keys
    }

    results = []
    for k in sorted(base_keys - compare_keys):
        results.append({"employee_id": k, "missing_from": "compare"})
    for k in sorted(compare_keys - base_keys):
        results.append({"employee_id": k, "missing_from": "base"})
    return results


def detect_duplicates(records, key_fields):
    """key_fields(예: ["employee_id"] 또는 ["employee_id", "period_month"]) 기준 중복 탐지."""
    groups = {}
    for idx, r in enumerate(records):
        key = tuple(r.get(f) for f in key_fields)
        if any(v is None for v in key):
            continue
        groups.setdefault(key, []).append((idx, r))

    results = []
    for key, rows in groups.items():
        if len(rows) > 1:
            results.append(
                {
                    "key": dict(zip(key_fields, key)),
                    "count": len(rows),
                    "rows": [r for _, r in rows],
                }
            )
    return results


def detect_amount_mismatch(
    records_a,
    records_b,
    key="employee_id",
    amount_field_a="amount",
    amount_field_b="amount",
    scale_a=1,
    scale_b=1,
    tolerance=0,
):
    """key로 매칭 후 금액을 정규화된 단위(scale 적용)로 비교, 허용오차 초과시 결과에 포함."""
    b_by_key = {r[key]: r for r in records_b if r.get(key)}

    results = []
    for a in records_a:
        k = a.get(key)
        if not k or k not in b_by_key:
            continue
        b = b_by_key[k]

        val_a = normalize_amount(a.get(amount_field_a))
        val_b = normalize_amount(b.get(amount_field_b))
        if val_a is None or val_b is None:
            continue

        norm_a = val_a * scale_a
        norm_b = val_b * scale_b
        diff = abs(norm_a - norm_b)
        if diff > tolerance:
            results.append(
                {
                    "employee_id": k,
                    "expected_value": norm_a,
                    "actual_value": norm_b,
                    "diff_amount": norm_a - norm_b,
                }
            )
    return results
