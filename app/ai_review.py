"""검토 항목에 대한 AI 스타일 검토 의견 생성기.

외부 AI API를 호출하지 않고, 검증유형/데이터유형/차액 등 이미 알고 있는 정보를
바탕으로 원인 분석 + 확인 항목 + 권장 조치를 규칙 기반으로 조립한다.
실시간으로 계산만 하고 저장은 하지 않으므로, 규칙이 바뀌면 다음 조회부터 바로 반영된다.
"""


def _amount(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _missing_opinion(item):
    from_base = "비교 파일" in (item.get("detail") or "")
    cause = (
        f"{item.get('source_file_name') or '기준 파일'}과(와) "
        f"{item.get('compare_file_name') or '비교 파일'} 사이에서 사번 매칭이 되지 않아 "
        f"{'비교 파일' if from_base else '기준 파일'} 쪽에서 데이터가 발견되지 않았습니다."
    )
    checklist = [
        "해당 사번이 이 기간에 실제로 재직 중이었는지 인사 마스터에서 확인",
        "최근 입사/퇴사/휴직으로 한쪽 파일에만 반영된 것은 아닌지 확인",
        "두 파일의 사번 표기 형식(하이픈, 앞자리 0, 공백 등)이 다르지 않은지 확인",
    ]
    action = "정정 대상이면 누락된 파일에 데이터를 추가 요청하고, 입퇴사 등 정당한 사유가 있다면 '정상예외'로 처리하세요."
    return cause, checklist, action


def _duplicate_opinion(item):
    cause = f"{item.get('detail') or '동일 키 기준'}으로 같은 데이터가 2건 이상 중복 등록되어 있습니다."
    checklist = [
        "동일 파일이 실수로 두 번 업로드되지 않았는지 확인",
        "부서 이동/직급 변경 등으로 같은 기간에 이력이 두 줄 생긴 것은 아닌지 확인",
        "중복 건들의 금액이 서로 같은지, 다르다면 어느 쪽이 최신본인지 확인",
    ]
    action = "중복 레코드 중 오래된/오입력 건을 정정 요청하고, 둘 다 유효한 사유가 있다면 '정상예외'로 처리하세요."
    return cause, checklist, action


def _mismatch_opinion(item):
    diff = _amount(item.get("diff_amount"))
    data_type = item.get("data_type")
    detail = item.get("detail") or ""

    if diff is None:
        direction = "차액"
    elif diff > 0:
        direction = f"기준값보다 실제값이 {diff:,.0f}원 많습니다 (초과)"
    elif diff < 0:
        direction = f"기준값보다 실제값이 {abs(diff):,.0f}원 적습니다 (미달)"
    else:
        direction = "차액이 0에 가깝지만 허용오차를 벗어났습니다"

    if "한도" in detail:
        cause = f"지급액이 정해진 한도액을 초과했습니다 ({direction})."
        checklist = [
            "규정상 한도 예외 대상(직급/근속연수 등)에 해당하는지 확인",
            "이번 달에 추가 지급된 특별 항목이 섞여 있는지 확인",
            "한도 기준 자체가 최근에 개정되지 않았는지 확인",
        ]
        action = "예외 사유가 확인되면 '정상예외', 오지급이면 환수·정정 처리 후 '수정 필요'로 표시하세요."
    elif data_type == "급여":
        cause = f"급여 관련 두 데이터 간 지급액 차이가 발견되었습니다 ({direction})."
        checklist = [
            "최근 연봉 계약 변경/연봉 협상 이력 확인",
            "해당 월 상여금·수당·공제 항목이 반영된 시점 차이인지 확인",
            "입력 시 단위(원/만원) 오기입 여부 확인",
        ]
        action = "차액 근거자료(계약서, 인사발령 등)를 확인한 뒤 실제 오류면 '수정 필요', 정상 사유면 '정상예외'로 처리하세요."
    else:
        cause = f"복리후생 지급액이 기준과 다릅니다 ({direction})."
        checklist = [
            "복지 포인트/항목별 지급 기준이 이번 달에 변경되지 않았는지 확인",
            "중복 신청이나 자격 요건 미충족 가능성 확인",
        ]
        action = "지급 근거를 확인한 뒤 오지급이면 정정, 정상 사유면 '정상예외'로 처리하세요."

    return cause, checklist, action


_HANDLERS = {
    "누락": _missing_opinion,
    "중복": _duplicate_opinion,
    "금액불일치": _mismatch_opinion,
}


def generate_opinion(item):
    """item: pr_review_items 조인 row(dict형). 반환: {cause, checklist, action}."""
    handler = _HANDLERS.get(item.get("review_type"))
    if not handler:
        return {
            "cause": item.get("detail") or "검증 로직에서 이상이 감지되었습니다.",
            "checklist": ["상세 내용을 참고하여 원본 데이터를 확인하세요."],
            "action": "확인 후 적절한 상태로 처리하세요.",
        }
    cause, checklist, action = handler(item)
    return {"cause": cause, "checklist": checklist, "action": action}
