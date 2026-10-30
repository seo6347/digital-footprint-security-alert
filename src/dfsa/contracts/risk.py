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


class RiskEvaluation(ContractModel):
    searchability: EvaluationValue
    cross_source_linkability: EvaluationValue
    attack_utility: EvaluationValue
    sensitivity: EvaluationValue
    evidence_confidence: EvaluationValue


class RiskPath(ContractModel):
    risk_path_id: str  # Owned by Module C.
    rule_id: Literal["R01", "R02", "R03", "R04", "R05"]
    category: RiskCategory
    path_status: RiskPathStatus
    exposure_ids: list[str]
    evaluation: RiskEvaluation
    reason: str
    recommendations: list[str] = Field(min_length=1)


class RiskSummary(ContractModel):
    total_exposures: int
    total_paths: int


class RiskRequest(RequestContract):
    subject: Subject
    exposures: list[Exposure] = Field(default_factory=list)


class RiskResponse(RequestContract):
    status: ModuleStatus
    risk_paths: list[RiskPath] = Field(default_factory=list)
    summary: RiskSummary
    errors: list[ErrorDetail] = Field(default_factory=list)
