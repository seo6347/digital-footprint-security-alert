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


class Stages(ContractModel):
    search: StageStatus
    profiling: StageStatus
    risk_analysis: StageStatus


class ResultSummary(ContractModel):
    search_result_count: int
    confirmed_source_count: int
    total_exposures: int
    total_risk_paths: int


class DFSAResult(RequestContract):
    status: ModuleStatus
    subject: Subject
    stages: Stages
    sources: list[Source] = Field(default_factory=list)
    exposures: list[Exposure] = Field(default_factory=list)
    risk_paths: list[RiskPath] = Field(default_factory=list)
    summary: ResultSummary
    errors: list[ErrorDetail] = Field(default_factory=list)
