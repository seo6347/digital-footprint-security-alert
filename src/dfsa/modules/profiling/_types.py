"""Internal identity, evidence, and exposure values for profiling."""

from dataclasses import dataclass

from dfsa.contracts.common import ExposureType, IdentityStatus


@dataclass(frozen=True)
class IdentityEvidence:
    """Comparison diagnostic pointing to original ParsedDocument text runs.

    These references are not validated Exposure evidence or generated quotes.
    Indices address document.texts; block_id identifies their structural unit.
    """

    kind: str
    block_id: int
    text_indices: tuple[int, ...]


@dataclass(frozen=True)
class IdentityDecision:
    """Phase 3 result; only confirmed decisions provide extraction scope roots.

    Each target ID refers to a ParsedBlock in the input source. Its descendants
    form one bounded person region. Empty IDs never authorize page-wide use.
    """

    source_id: str
    identity_status: IdentityStatus
    reasons: tuple[str, ...]
    evidence: tuple[IdentityEvidence, ...] = ()
    target_block_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class EvidenceReference:
    """One contiguous, entity-decoded text span; HTML offsets remain separate.

    quote is never synthesized from separated spans. block_id is the enclosing
    Phase 2 text unit; text_indices address the original document.texts tuple.
    """

    block_id: int
    text_indices: tuple[int, ...]
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class ExposureCandidate:
    """Untrusted internal proposal, without a public Exposure ID."""

    source_id: str
    target_block_id: int
    type: ExposureType
    value: str
    evidence: EvidenceReference
    relation: str | None = None


@dataclass(frozen=True)
class ValidatedExposureCandidate(ExposureCandidate):
    """Validated value plus separate ownership/field-context references."""

    attribution: tuple[EvidenceReference, ...] = ()


@dataclass(frozen=True)
class ExtractionDiagnostic:
    code: str
    block_id: int


@dataclass(frozen=True)
class ExtractionResult:
    """Only validated candidates are returned; omissions are not module status."""

    candidates: tuple[ValidatedExposureCandidate, ...] = ()
    diagnostics: tuple[ExtractionDiagnostic, ...] = ()
