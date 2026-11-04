"""Service -> UI contract. Pipeline execution belongs to Phase 2."""

from pydantic import Field

from .common import (
    ContractModel,
    ErrorDetail,
    ModuleStatus,
    RequestContract,
    StageStatus,
    Subject,
)
from .profiling import Exposure, Source
from .risk import RiskPath

# 전체 Pipeline의 단계별 실행 상태.
# 호출하지 않은 Module은 failed가 아니라 not_started로 기록한다.
class Stages(ContractModel):
    search: StageStatus
    profiling: StageStatus
    risk_analysis: StageStatus

# A/B/C의 결과를 종합한 최종 개수 요약.
# 각 값은 Orchestrator가 실제 Module 결과를 기준으로 계산한다.
class ResultSummary(ContractModel):
    search_result_count: int
    confirmed_source_count: int
    total_exposures: int
    total_risk_paths: int

# Orchestrator가 생성하여 UI에 전달하는 최종 통합 결과.
# 각 Module의 Public Contract 모델을 재사용하며 별도 UI 전용 Schema를 만들지 않는다.
class DFSAResult(RequestContract):

    # 전체 Pipeline 상태와 단계별 실행 상태는 구분한다.
    status: ModuleStatus
    subject: Subject
    stages: Stages

    # Module B/C의 결과 모델을 재사용하여 출처 → 공개 정보 → 위험 경로의 근거 관계를 보존한다.
    sources: list[Source] = Field(default_factory=list)
    exposures: list[Exposure] = Field(default_factory=list)
    risk_paths: list[RiskPath] = Field(default_factory=list)

    # 전체 결과 개수와 Module별 오류를 Orchestrator가 집계한다.
    summary: ResultSummary
    errors: list[ErrorDetail] = Field(default_factory=list)
