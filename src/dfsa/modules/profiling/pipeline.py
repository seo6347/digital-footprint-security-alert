"""Request-local Phase 1-5 composition using the team-approved DR-1 to DR-4.

Expected external failures stay source-local. Identity decisions, including
uncertain/rejected and confirmed zero-exposure results, are usable outcomes.
Programming/contract errors propagate; no exception-to-public-error policy is
invented here. Original documents are retained only for this call's lifetime.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from dfsa.contracts.common import ErrorDetail, IdentityStatus, ModuleStatus, ProcessingStatus, Subject
from dfsa.contracts.profiling import Exposure, ProfilingRequest, ProfilingResponse, Source
from dfsa.contracts.search import SearchResult

from . import deduplication, extraction, fetch, identity, parsing
from ._types import (
    ExtractionResult, FetchError, FetchFailure, FetchedHTML, IdentityDecision,
    ParseFailure, ParsedDocument, ValidatedExposureCandidate,
)


@dataclass(frozen=True)
class _SourceOutcome:
    source: Source
    errors: tuple[ErrorDetail, ...] = ()
    document: ParsedDocument | None = None
    identity: IdentityDecision | None = None
    extraction: ExtractionResult | None = None


def _failed_source(
    source: SearchResult,
    failure: FetchFailure | ParseFailure,
    status: ProcessingStatus,
) -> _SourceOutcome:
    if (failure.source_id != source.source_id or failure.original_url != source.url
            or failure.error.source_id not in (None, source.source_id)):
        raise ValueError("Failure references another source")
    return _SourceOutcome(
        Source(source_id=source.source_id, url=source.url,
               processing_status=status, identity_status=None),
        errors=(failure.error,),
    )


def _process_source(subject: Subject, source: SearchResult) -> _SourceOutcome:
    fetched = fetch.fetch_html(source)
    if isinstance(fetched, FetchFailure):
        if not isinstance(fetched.kind, FetchError):
            raise ValueError("Invalid FetchError")
        if fetched.kind in {FetchError.UNSUPPORTED_CONTENT_TYPE, FetchError.UNSUPPORTED_ENCODING}:
            status = ProcessingStatus.UNSUPPORTED
        elif fetched.kind == FetchError.BLOCKED_URL:
            status = ProcessingStatus.REJECTED
        else:
            status = ProcessingStatus.FETCH_FAILED
        return _failed_source(source, fetched, status)
    if not isinstance(fetched, FetchedHTML):
        raise TypeError("Expected FetchedHTML or FetchFailure")
    if fetched.source_id != source.source_id or fetched.original_url != source.url:
        raise ValueError("Fetched document references another source")

    document = parsing.parse_html(fetched)
    if isinstance(document, ParseFailure):
        if document.final_url != fetched.final_url:
            raise ValueError("Parse failure references another document")
        return _failed_source(source, document, ProcessingStatus.PARSE_FAILED)
    if not isinstance(document, ParsedDocument):
        raise TypeError("Expected ParsedDocument or ParseFailure")
    if (document.source_id != source.source_id or document.original_url != source.url
            or document.final_url != fetched.final_url):
        raise ValueError("Parsed document references another source")

    decision = identity.verify_identity(subject, document)
    if not isinstance(decision, IdentityDecision):
        raise TypeError("Expected IdentityDecision")
    if decision.source_id != source.source_id:
        raise ValueError("Identity references another source")
    if not isinstance(decision.identity_status, IdentityStatus):
        raise ValueError("Identity verification must return a completed status")
    status = (ProcessingStatus.REJECTED if decision.identity_status == IdentityStatus.REJECTED
              else ProcessingStatus.SUCCESS)
    public_source = Source(source_id=source.source_id, url=source.url,
                           processing_status=status, identity_status=decision.identity_status)
    result = None
    if decision.identity_status == IdentityStatus.CONFIRMED:
        if not decision.target_block_ids:
            raise ValueError("Confirmed identity has no target blocks")
        result = extraction.extract_exposures(document, decision)
        if not isinstance(result, ExtractionResult):
            raise TypeError("Expected ExtractionResult")
        for candidate in result.candidates:
            if not isinstance(candidate, ValidatedExposureCandidate):
                raise ValueError("Expected a Phase 4 ValidatedExposureCandidate")
            if candidate.source_id != source.source_id:
                raise ValueError("Candidate references another source")
            if candidate.target_block_id not in decision.target_block_ids:
                raise ValueError("Candidate references another identity scope")
    return _SourceOutcome(public_source, document=document, identity=decision, extraction=result)


def _aggregate_status(outcomes: Sequence[_SourceOutcome]) -> ModuleStatus:
    # Count actual completed decisions, never exposure count or 'rejected' alone.
    completed = sum(outcome.identity is not None for outcome in outcomes)
    if completed == len(outcomes):
        return ModuleStatus.SUCCESS  # Also the explicitly supported empty request.
    if completed:
        return ModuleStatus.PARTIAL_SUCCESS
    return ModuleStatus.FAILED


def _validate_exposure_sources(
    outcomes: Sequence[_SourceOutcome], exposures: Sequence[Exposure],
) -> None:
    confirmed = {outcome.source.source_id for outcome in outcomes
                 if outcome.source.identity_status == IdentityStatus.CONFIRMED}
    evidence = {(candidate.source_id, candidate.evidence.quote)
                for outcome in outcomes if outcome.extraction is not None
                for candidate in outcome.extraction.candidates}
    for exposure in exposures:
        for ref in exposure.sources:
            if ref.source_id not in confirmed:
                raise ValueError("Exposure references a source without confirmed identity")
            if (ref.source_id, ref.evidence) not in evidence:
                raise ValueError("Exposure evidence does not match a validated candidate")


def _collect_errors(outcomes: Sequence[_SourceOutcome]) -> list[ErrorDetail]:
    errors: list[ErrorDetail] = []
    for outcome in outcomes:
        for error in outcome.errors:
            if error not in errors:
                errors.append(error)
    return errors


def run_profiling(request: ProfilingRequest) -> ProfilingResponse:
    """Analyze one request, without modifying input or sharing state across calls.

    Fetch uses SearchResult.url. Public sources preserve that original URL and
    input order; exposure order/IDs/evidence follow Phase 5. A completed identity
    is usable even with zero exposures. Only returned Fetch/Parse failures are
    public errors. Malformed inputs/internal results and unexpected bugs raise.
    """
    # Reconstruct nested models: model_validate(instance) alone would skip
    # revalidation of mutable Pydantic instances and retain input aliases.
    validated = ProfilingRequest.model_validate(request)
    local = ProfilingRequest.model_validate(validated.model_dump(mode="python"))
    outcomes = [_process_source(local.subject, source) for source in local.search_results]
    candidates = [candidate for outcome in outcomes if outcome.extraction is not None
                  for candidate in outcome.extraction.candidates]
    exposures = deduplication.deduplicate_exposures(candidates)
    # Validate nested public instances too, including results of module callables.
    exposures = [Exposure.model_validate(item.model_dump(mode="python")) for item in exposures]
    _validate_exposure_sources(outcomes, exposures)
    return ProfilingResponse.model_validate({
        "schema_version": local.schema_version,
        "request_id": local.request_id,
        "status": _aggregate_status(outcomes),
        "sources": [outcome.source.model_dump(mode="python") for outcome in outcomes],
        "exposures": [item.model_dump(mode="python") for item in exposures],
        "errors": [item.model_dump(mode="python") for item in _collect_errors(outcomes)],
    })
