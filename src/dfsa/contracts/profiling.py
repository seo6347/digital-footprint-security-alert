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


class Source(ContractModel):
    source_id: str
    url: str
    processing_status: ProcessingStatus
    # Producers must supply a non-null enum once identity verification completes.
    identity_status: IdentityStatus | None = None


class ExposureSource(ContractModel):
    source_id: str
    evidence: str


class Exposure(ContractModel):
    exposure_id: str  # Owned by Module B.
    type: ExposureType
    value: str
    relation: str | None = None
    sources: list[ExposureSource] = Field(default_factory=list, min_length=1)


class ProfilingRequest(RequestContract):
    subject: Subject
    search_results: list[SearchResult]


class ProfilingResponse(RequestContract):
    status: ModuleStatus
    sources: list[Source] = Field(default_factory=list)
    exposures: list[Exposure] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)
