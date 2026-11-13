"""Internal fetch values; these do not extend the public profiling contract."""

from dataclasses import dataclass
from enum import Enum

from dfsa.contracts.common import ErrorDetail, ExposureType, IdentityStatus


class FetchError(str, Enum):
    INVALID_URL = "invalid_url"
    BLOCKED_URL = "blocked_url"
    DNS_ERROR = "dns_error"
    TLS_ERROR = "tls_error"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    HTTP_NOT_FOUND = "http_404"
    HTTP_RATE_LIMITED = "http_429"
    HTTP_SERVER_ERROR = "http_5xx"
    HTTP_ERROR = "http_error"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    UNSUPPORTED_ENCODING = "unsupported_encoding"
    BODY_TOO_LARGE = "body_too_large"
    REDIRECT_LIMIT = "redirect_limit"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True)
class FetchedHTML:
    source_id: str
    original_url: str
    final_url: str
    html: bytes
    content_type: str
    charset: str | None
    http_status: int


@dataclass(frozen=True)
class FetchFailure:
    source_id: str
    original_url: str
    final_url: str
    kind: FetchError
    error: ErrorDetail
    http_status: int | None = None


class FetchProblem(Exception):
    """Expected external failure, converted to a per-source result by fetch."""

    def __init__(self, kind: FetchError, message: str):
        super().__init__(message)
        self.kind = kind


class ParseError(str, Enum):
    INVALID_CHARSET = "invalid_charset"
    UNSUPPORTED_CHARSET = "unsupported_charset"
    DECODE_ERROR = "decode_error"
    INVALID_DOCUMENT = "invalid_document"
    STRUCTURE_LIMIT = "structure_limit"


@dataclass(frozen=True)
class ParsedText:
    """Entity-decoded text and its exact slice in ParsedDocument.html_text."""

    block_id: int
    raw_text: str
    normalized_text: str
    start: int
    end: int


@dataclass(frozen=True)
class ParsedBlock:
    """Structural container, never an inferred person or merged evidence quote."""

    block_id: int
    parent_id: int | None
    tag: str
    attributes: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class ParsedLink:
    block_id: int
    href: str
    text: str
    normalized_text: str
    text_indices: tuple[int, ...]
    attributes: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class ParsedMetadata:
    attributes: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class ParsedDocument:
    source_id: str
    original_url: str
    final_url: str
    encoding: str
    html_text: str
    title: str | None
    metadata: tuple[ParsedMetadata, ...]
    blocks: tuple[ParsedBlock, ...]
    texts: tuple[ParsedText, ...]
    links: tuple[ParsedLink, ...]

    @property
    def has_body_text(self) -> bool:
        return any(text.normalized_text for text in self.texts)


@dataclass(frozen=True)
class ParseFailure:
    source_id: str
    original_url: str
    final_url: str
    kind: ParseError
    error: ErrorDetail


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
