"""Service <-> Module A contracts."""

from datetime import datetime, timezone

from pydantic import AwareDatetime, Field, field_serializer

from .common import (
    ContractModel,
    ErrorDetail,
    ModuleStatus,
    QueryStatus,
    RelevanceReason,
    RelevanceStatus,
    RequestContract,
    Subject,
)

# 검색 결과 수를 제어하는 옵션. 기본 10개이며 1~20 사이의 정수만 허용
class SearchOptions(ContractModel):
    top_k: int = Field(default=10, ge=1, le=20, strict=True)

# Orchestrator가 Module A에 전달하는 request.
# schema_version과 request_id는 RequestContract에서 상속한다.
class SearchRequest(RequestContract):
    subject: Subject
    options: SearchOptions = Field(default_factory=SearchOptions)

# Module A가 실행한 개별 검색어와 실행 결과
# Query 단위의 성공과 실패는 Module 전체 상태와 구분한다.
class QueryExecution(ContractModel):
    query_id: str  # Owned by Module A.
    text: str
    provider: str
    status: QueryStatus

# 검색 결과와 대상 인물의 관련성에 대한 Module A의 예비 판단.
# candidate는 동일인 확인을 의미하지 않으며, 최종 검증은 Module B가 담당한다.
class Relevance(ContractModel):
    status: RelevanceStatus
    reasons: list[RelevanceReason]

# 검색 결과가 발견된 Query와 검색 서비스 내 순위를 기록한다.
# 동일 URL이 여러 Query에서 발견되더라도 발견 경로를 보존할 수 있다.
class DiscoveredBy(ContractModel):
    query_id: str
    provider_rank: int | None = None

# Module A가 발견한 개별 검색 결과.
# 관련성 판단과 발견 경로를 포함하지만, 동일인 확인이나 Exposure 검증은 수행하지 않는다.
class SearchResult(ContractModel):
    source_id: str  # Owned by Module A.
    url: str
    normalized_url: str
    title: str | None = None
    snippet: str | None = None
    rank: int
    relevance: Relevance
    discovered_by: list[DiscoveredBy]

# Module A의 전체 실행 결과.
# 개별 Query 기록, 검색 후보, 오류를 포함하며 빈 리스트는 정상적인 0건 결과도 표현한다.
class SearchResponse(RequestContract):
    status: ModuleStatus
    searched_at: AwareDatetime
    queries: list[QueryExecution] = Field(default_factory=list)
    results: list[SearchResult] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)

    # JSON 직렬화 시 검색 시각을 UTC ISO 8601 형식으로 통일한다.
    @field_serializer("searched_at", when_used="json")
    def serialize_searched_at(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
