
"""Conservative risk evaluation for DFSA Module C."""

from dataclasses import dataclass
from enum import Enum

from .features import RiskFeatures


class EvaluationValue(str, Enum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class RiskAssessment:
    path_status: str
    searchability: EvaluationValue
    cross_source_linkability: EvaluationValue
    attack_utility: EvaluationValue
    sensitivity: EvaluationValue
    evidence_confidence: EvaluationValue


def evaluate_risk(features: RiskFeatures) -> RiskAssessment:
    """Evaluate evidence without assuming unverified relations."""

    # 공개 출처가 존재하는지 확인
    searchability = (
        EvaluationValue.YES
        if features.source_count > 0
        else EvaluationValue.UNKNOWN
    )

    # 서로 다른 출처 사이에 검증된 연결이 있는지 확인
    cross_source_linkability = (
        EvaluationValue.YES
        if features.cross_source_link_count > 0
        else EvaluationValue.UNKNOWN
    )

    # 현재는 공격 활용 가능성과 민감성을 확정하지 않음
    attack_utility = EvaluationValue.UNKNOWN
    sensitivity = EvaluationValue.UNKNOWN

    # 관계 후보 추출만으로 근거가 검증됐다고 판단하지 않음
    evidence_confidence = EvaluationValue.UNKNOWN

    # 검증되지 않은 위험 경로는 candidate 유지
    path_status = "candidate"

    return RiskAssessment(
        path_status=path_status,
        searchability=searchability,
        cross_source_linkability=cross_source_linkability,
        attack_utility=attack_utility,
        sensitivity=sensitivity,
        evidence_confidence=evidence_confidence,
    )

