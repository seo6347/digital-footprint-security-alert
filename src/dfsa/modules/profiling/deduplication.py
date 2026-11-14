"""Phase 5 request-local merging of Phase 4 validated candidates.

Only comparison keys are normalized; displayed values and evidence stay exact.
No identity/extraction rules, global cache, or public response assembly live here.
"""

from collections.abc import Iterable

from dfsa.contracts.common import ExposureType
from dfsa.contracts.profiling import Exposure, ExposureSource

from ._types import EvidenceReference, ValidatedExposureCandidate

_Key = tuple[ExposureType, str, str | None]


def _require_text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid or empty {field}")


def _check_reference(ref: EvidenceReference) -> None:
    """Check the boundary shape, without repeating Phase 4 HTML validation."""
    if not isinstance(ref, EvidenceReference):
        raise ValueError("Invalid evidence reference")
    # A separate attribution span can legitimately contain only whitespace
    # around an inline field; it must still remain an exact original quote.
    if not isinstance(ref.quote, str) or not ref.quote:
        raise ValueError("Invalid or empty evidence quote")
    if (type(ref.block_id) is not int or ref.block_id < 0
            or type(ref.start) is not int or type(ref.end) is not int
            or not 0 <= ref.start < ref.end):
        raise ValueError("Invalid evidence block or offsets")
    indices = ref.text_indices
    if (not isinstance(indices, tuple) or not indices
            or any(type(i) is not int or i < 0 for i in indices)
            or tuple(sorted(set(indices))) != indices):
        raise ValueError("Invalid evidence text indices")


def _check_candidate(candidate: ValidatedExposureCandidate) -> None:
    if not isinstance(candidate, ValidatedExposureCandidate):
        raise ValueError("Expected a Phase 4 ValidatedExposureCandidate")
    _require_text(candidate.source_id, "source_id")
    _require_text(candidate.value, "value")
    if not isinstance(candidate.type, ExposureType):
        raise ValueError("Invalid ExposureType")
    if type(candidate.target_block_id) is not int or candidate.target_block_id < 0:
        raise ValueError("Invalid target_block_id")
    if candidate.relation is not None:
        _require_text(candidate.relation, "relation")
    _check_reference(candidate.evidence)
    _require_text(candidate.evidence.quote, "value evidence quote")
    if not isinstance(candidate.attribution, tuple) or not candidate.attribution:
        raise ValueError("Missing or invalid attribution references")
    for ref in candidate.attribution:
        _check_reference(ref)


def _normalize_value(kind: ExposureType, value: str) -> str:
    # Preserve internal identifier characters, case and spacing. In particular,
    # do not apply email plus/dot rules, phone punctuation rules or URL rewriting.
    if kind in {ExposureType.CONTACT, ExposureType.ACCOUNT}:
        return value.strip()
    return " ".join(value.split())


def _comparison_key(candidate: ValidatedExposureCandidate) -> _Key:
    relation = None if candidate.relation is None else " ".join(candidate.relation.split())
    return candidate.type, _normalize_value(candidate.type, candidate.value), relation


def _key_order(key: _Key) -> tuple[str, str, bool, str]:
    kind, value, relation = key
    return kind.value, value, relation is not None, relation or ""


def _collect_sources(candidates: list[ValidatedExposureCandidate]) -> list[ExposureSource]:
    # An identical public pair may have several document positions; callers
    # retain the Phase 4 candidates for those positions and attribution refs.
    pairs = {(candidate.source_id, candidate.evidence.quote) for candidate in candidates}
    return [ExposureSource(source_id=source_id, evidence=quote)
            for source_id, quote in sorted(pairs)]


def deduplicate_exposures(candidates: Iterable[ValidatedExposureCandidate]) -> list[Exposure]:
    """Merge candidates from exactly ONE profiling request/subject per call.

    The caller must supply only Phase 4 results for that request. Candidates
    carry no request/subject identity, so mixed-request batches cannot be
    detected here. Nothing is cached or reused across calls.

    Groups and sources are sorted by comparison key and exact (source, quote).
    IDs are exp_001, exp_002, ... in that sorted order (width grows past 999).
    Permuting the same keys preserves IDs and source order. Adding/removing a
    key can renumber IDs; they have no meaning outside the current request.

    Per the approved plan, the first candidate supplies the exact displayed
    value/relation. Reordering whitespace variants can therefore change their
    displayed spelling, but not their comparison key or ID. Supply candidates
    in discovery order to preserve the first-discovered representation.

    Public evidence is the exact value quote, never a join of attribution or
    separate spans. Public models cannot carry positions, target blocks or
    attribution refs: retain the original ExtractionResult/ParsedDocument for
    that audit trail. Inputs are not modified. Invalid boundary data raises
    ValueError; no partial/empty success is substituted for malformed input.
    """
    groups: dict[_Key, list[ValidatedExposureCandidate]] = {}
    for candidate in candidates:
        _check_candidate(candidate)
        groups.setdefault(_comparison_key(candidate), []).append(candidate)

    exposures = []
    for number, key in enumerate(sorted(groups, key=_key_order), start=1):
        group = groups[key]
        representative = group[0]
        exposures.append(Exposure(
            exposure_id=f"exp_{number:03d}",
            type=representative.type,
            value=representative.value,
            relation=representative.relation,
            sources=_collect_sources(group),
        ))
    return exposures
