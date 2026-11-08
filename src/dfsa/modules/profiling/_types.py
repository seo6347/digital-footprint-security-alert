"""Internal fetch values; these do not extend the public profiling contract."""

from dataclasses import dataclass
from enum import Enum

from dfsa.contracts.common import ErrorDetail


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
