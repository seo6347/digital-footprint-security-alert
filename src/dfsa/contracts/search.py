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


class SearchOptions(ContractModel):
    top_k: int = Field(default=10, ge=1, le=20, strict=True)


class SearchRequest(RequestContract):
    subject: Subject
    options: SearchOptions = Field(default_factory=SearchOptions)


class QueryExecution(ContractModel):
    query_id: str  # Owned by Module A.
    text: str
    provider: str
    status: QueryStatus


class Relevance(ContractModel):
    status: RelevanceStatus
    reasons: list[RelevanceReason]


class DiscoveredBy(ContractModel):
    query_id: str
    provider_rank: int | None = None


class SearchResult(ContractModel):
    source_id: str  # Owned by Module A.
    url: str
    normalized_url: str
    title: str | None = None
    snippet: str | None = None
    rank: int
    relevance: Relevance
    discovered_by: list[DiscoveredBy]


class SearchResponse(RequestContract):
    status: ModuleStatus
    searched_at: AwareDatetime
    queries: list[QueryExecution] = Field(default_factory=list)
    results: list[SearchResult] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)

    @field_serializer("searched_at", when_used="json")
    def serialize_searched_at(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
