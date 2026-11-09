
"""Predefined explanation and recommendation templates for Module C."""

from dfsa.contracts.common import RiskCategory


TEMPLATES = {
    "R01": {
        "reason": (
            "공개된 인물 관계 정보를 활용하여 "
            "지도교수나 연구실 관계자 등 권위자를 사칭하는 "
            "접근이 가능할 수 있습니다."
        ),
        "recommendations": [
            "교수나 연구실 관계자의 요청은 공식 채널을 통해 확인하세요.",
            "공개된 관계 정보와 연락처의 노출 범위를 검토하세요.",
        ],
    },
    "R02": {
        "reason": (
            "공개된 소속과 관심 분야를 조합하여 "
            "학술 관계자나 연구 협력 기관을 사칭하는 "
            "접근이 가능할 수 있습니다."
        ),
        "recommendations": [
            "학술 협력 요청은 해당 기관의 공식 연락처로 확인하세요.",
            "연구 관련 링크나 첨부파일을 열기 전에 발신자를 검증하세요.",
        ],
    },
    "R03": {
        "reason": (
            "공개된 활동과 관심 분야를 활용하여 "
            "채용 또는 연구 참여 기회를 사칭하는 "
            "접근이 가능할 수 있습니다."
        ),
        "recommendations": [
            "채용 및 연구 참여 제안은 공식 모집 공고와 비교하세요.",
            "제안받은 링크에서 계정 정보나 개인정보를 입력하기 전에 확인하세요.",
        ],
    },
    "R04": {
        "reason": (
            "공개된 일정 정보를 활용하여 "
            "학술 행사나 회의 관련 안내를 사칭하는 "
            "접근이 가능할 수 있습니다."
        ),
        "recommendations": [
            "행사 일정과 안내는 공식 홈페이지에서 확인하세요.",
            "행사 관련 이메일의 링크와 첨부파일을 주의하세요.",
        ],
    },
    "R05": {
        "reason": (
            "공개된 계정 정보를 활용하여 "
            "계정 관리자나 서비스 운영자를 사칭하는 "
            "접근이 가능할 수 있습니다."
        ),
        "recommendations": [
            "계정 관련 알림은 해당 서비스에 직접 접속해 확인하세요.",
            "비밀번호와 인증 코드를 이메일이나 외부 링크에 입력하지 마세요.",
        ],
    },
}


def generate_explanation(
    rule_id: str,
    category: RiskCategory,
) -> tuple[str, list[str]]:
    """Generate a predefined reason and recommendations for a rule."""

    if rule_id not in TEMPLATES:
        raise ValueError(f"Unsupported risk rule: {rule_id}")

    expected_categories = {
        "R01": RiskCategory.AUTHORITY_IMPERSONATION,
        "R02": RiskCategory.ACADEMIC_IMPERSONATION,
        "R03": RiskCategory.RECRUITMENT_IMPERSONATION,
        "R04": RiskCategory.EVENT_IMPERSONATION,
        "R05": RiskCategory.ACCOUNT_IMPERSONATION,
    }

    if category != expected_categories[rule_id]:
        raise ValueError(
            f"Category mismatch for {rule_id}: {category}"
        )

    template = TEMPLATES[rule_id]

    return (
        template["reason"],
        list(template["recommendations"]),
    )

