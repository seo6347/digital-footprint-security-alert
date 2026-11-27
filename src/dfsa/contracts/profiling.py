"""Service and Module B contracts."""

from typing import Self

from pydantic import Field, model_validator

from dfsa._documents import ParsedDocument

from .common import (
    ContractModel, ErrorDetail, ExposureID, ExposureType, IdentityStatus, ModuleStatus,
    NonEmpty, ProcessingStatus, RequestContract, SourceID, Subject, unique_ids,
)


class Source(ContractModel):
    source_id: SourceID
    url: str
    processing_status: ProcessingStatus
    identity_status: IdentityStatus | None = None


class ExposureSource(ContractModel):
    source_id: SourceID
    evidence: NonEmpty


_SUBTYPES = {
    ExposureType.IDENTITY: {"name", "role"},
    ExposureType.AFFILIATION: {"university", "laboratory"},
    ExposureType.CONTACT: {"email"},
    ExposureType.RELATIONSHIP: {"advisor"},
}


class Exposure(ContractModel):
    exposure_id: ExposureID
    type: ExposureType
    value: NonEmpty
    subtype: str | None = None
    relation: str | None = None
    sources: list[ExposureSource] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_subtype(self) -> Self:
        if self.subtype is not None and self.subtype not in _SUBTYPES.get(self.type, ()):
            raise ValueError("Unsupported exposure type and subtype combination")
        return self


def validate_exposure_references(sources: list[Source], exposures: list[Exposure]) -> None:
    unique_ids(sources, "source_id")
    unique_ids(exposures, "exposure_id")
    confirmed = {
        source.source_id for source in sources
        if source.identity_status == IdentityStatus.CONFIRMED
        and source.processing_status == ProcessingStatus.SUCCESS
    }
    for exposure in exposures:
        if any(reference.source_id not in confirmed for reference in exposure.sources):
            raise ValueError("Exposure must reference a successfully processed confirmed source")


class ProfilingRequest(RequestContract):
    subject: Subject
    documents: tuple[ParsedDocument, ...]


class ProfilingResponse(RequestContract):
    status: ModuleStatus
    sources: list[Source] = Field(default_factory=list)
    exposures: list[Exposure] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        validate_exposure_references(self.sources, self.exposures)
        failures = {ProcessingStatus.FETCH_FAILED, ProcessingStatus.PARSE_FAILED, ProcessingStatus.UNSUPPORTED}
        has_failures = self.errors or any(source.processing_status in failures for source in self.sources)
        expected = ModuleStatus.SUCCESS
        if has_failures:
            usable = any(
                source.identity_status is not None and source.processing_status not in failures
                for source in self.sources
            )
            expected = ModuleStatus.PARTIAL_SUCCESS if usable else ModuleStatus.FAILED
        if self.status != expected:
            raise ValueError("Profiling status does not match its completed decisions and failures")
        return self
