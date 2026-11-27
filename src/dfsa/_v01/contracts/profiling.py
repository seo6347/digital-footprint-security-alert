"""Service <-> Module B contracts and shared Source / Exposure models."""

from pydantic import Field

from .common import (
    ContractModel,
    ErrorDetail,
    ExposureType,
    IdentityStatus,
    ModuleStatus,
    ProcessingStatus,
    RequestContract,
    Subject,
)
from .search import SearchResult

# Module B가 처리한 출처의 상태와 동일인 검증 결과.
# source_id는 A에서 생성한 값을 유지하며, identity_status=None은 검증 미완료를 의미한다.
class Source(ContractModel):
    source_id: str
    url: str
    processing_status: ProcessingStatus
    # Producers must supply a non-null enum once identity verification completes.
    identity_status: IdentityStatus | None = None

# 추출한 Exposure를 실제 출처와 연결하는 증거 정보.
# 검색 결과 snippet이 아니라 B가 처리한 출처에서 확인한 근거를 기록한다.
class ExposureSource(ContractModel):
    source_id: str
    evidence: str

# Module B가 동일인 확인 후 추출한 공식 공개 정보.
# 각 Exposure는 최소 하나 이상의 출처·증거를 보유해야 하며 Module C의 입력으로 사용된다.
class Exposure(ContractModel):
    exposure_id: str  # Owned by Module B.
    type: ExposureType
    value: str
    relation: str | None = None
    sources: list[ExposureSource] = Field(default_factory=list, min_length=1)

# Orchestrator가 Module B에 전달하는 입력.
# 대상 정보와 A가 발견한 검색 후보만 전달하며, 검색 실행 상태는 Orchestrator가 관리한다.
class ProfilingRequest(RequestContract):
    subject: Subject
    search_results: list[SearchResult]

# Module B의 전체 실행 결과.
class ProfilingResponse(RequestContract):
    status: ModuleStatus
    sources: list[Source] = Field(default_factory=list)
    exposures: list[Exposure] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)
