"""Service <-> Module C contracts; RiskPath is also used by the UI result."""

from typing import Literal

from pydantic import Field

from .common import (
    ContractModel,
    ErrorDetail,
    EvaluationValue,
    ModuleStatus,
    RequestContract,
    RiskCategory,
    RiskPathStatus,
    Subject,
)
from .profiling import Exposure

# 각 RiskPath를 다섯 가지 기준으로 평가한 결과.
# 모든 항목은 필수이며 판단 불가·적용 불가는 지정된 Enum 값으로 표현한다.
class RiskEvaluation(ContractModel):
    searchability: EvaluationValue
    cross_source_linkability: EvaluationValue
    attack_utility: EvaluationValue
    sensitivity: EvaluationValue
    evidence_confidence: EvaluationValue

# Module C가 생성하는 개별 위험 시나리오.
# Exposure를 참조하여 위험 유형·판단 상태·평가·설명·대응 방안을 제공한다.
class RiskPath(ContractModel):
    """Schema only; Module C decides path status and generates explanations."""

    risk_path_id: str  # Owned by Module C.

    # v0.1에서 지원하는 위험 규칙은 R01~R05로 제한된다.
    rule_id: Literal["R01", "R02", "R03", "R04", "R05"]

    category: RiskCategory
    path_status: RiskPathStatus

    # 위험 판단의 근거로 사용된 Exposure ID 목록.
    exposure_ids: list[str]

    evaluation: RiskEvaluation

    # 설명 및 대응 방안은 Module C가 생성한다.
    reason: str
    recommendations: list[str] = Field(min_length=1)

# Module C의 분석 규모를 나타내는 요약 정보.
# 전체 Pipeline의 DFSAResult.summary와는 구분한다.
class RiskSummary(ContractModel):
    total_exposures: int
    total_paths: int

# Orchestrator가 C에 전달하는 분석 입력.
# B가 반환한 공식 Exposure를 재사용하며, 정상 Pipeline에서는 Exposure가 있을 때 C를 호출한다.
class RiskRequest(RequestContract):
    subject: Subject
    exposures: list[Exposure] = Field(default_factory=list)

# Module C의 전체 분석 결과.
# RiskPath와 분석 요약을 반환하며, Orchestrator가 최종 DFSAResult에 반영한다.
class RiskResponse(RequestContract):
    status: ModuleStatus
    risk_paths: list[RiskPath] = Field(default_factory=list)
    summary: RiskSummary
    errors: list[ErrorDetail] = Field(default_factory=list)
