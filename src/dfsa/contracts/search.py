"""Service and Module A contracts."""

from datetime import datetime, timezone
from typing import Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .common import (
    ContractModel, ErrorDetail, ModuleStatus, QueryID, QueryStatus, RelevanceReason,
    RelevanceStatus, RequestContract, SearchSourceID, Subject, unique_ids,
)


class SearchOptions(ContractModel):
    top_k: int = Field(default=10, ge=1, le=20, strict=True)


class SearchRequest(RequestContract):
    subject: Subject
    options: SearchOptions = Field(default_factory=SearchOptions)


class QueryExecution(ContractModel):
    query_id: QueryID
    text: str
    provider: str
    status: QueryStatus
    input_fields: list[str]


class Relevance(ContractModel):
    status: RelevanceStatus
    reasons: list[RelevanceReason] = Field(default_factory=list)


class DiscoveredBy(ContractModel):
    query_id: QueryID
    provider_rank: int | None = None


class SearchResult(ContractModel):
    source_id: SearchSourceID
    url: str
    normalized_url: str
    title: str | None = None
    snippet: str | None = None
    rank: int
    relevance: Relevance
    discovered_by: list[DiscoveredBy] = Field(default_factory=list)


def validate_search_references(queries: list[QueryExecution], results: list[SearchResult]) -> None:
    query_ids = unique_ids(queries, "query_id")
    successful_query_ids = {query.query_id for query in queries if query.status == QueryStatus.SUCCESS}
    unique_ids(results, "source_id")
    for result in results:
        discovered_by = {item.query_id for item in result.discovered_by}
        if not discovered_by or not discovered_by <= query_ids:
            raise ValueError("Search result must reference a recorded query")
        if discovered_by.isdisjoint(successful_query_ids):
            raise ValueError("Search result must reference at least one successful query")


def has_failed_search_query(queries: list[QueryExecution]) -> bool:
    return any(query.status == QueryStatus.FAILED for query in queries)


class SearchResponse(RequestContract):
    status: ModuleStatus
    searched_at: AwareDatetime
    queries: list[QueryExecution] = Field(default_factory=list)
    results: list[SearchResult] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)

    @field_validator("searched_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_response(self) -> Self:
        validate_search_references(self.queries, self.results)
        expected = ModuleStatus.SUCCESS
        if self.errors or has_failed_search_query(self.queries):
            expected = ModuleStatus.PARTIAL_SUCCESS if self.results else ModuleStatus.FAILED
        if self.status != expected:
            raise ValueError("Search status does not match its results and query failures")
        return self
