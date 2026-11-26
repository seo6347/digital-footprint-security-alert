"""Internal Explorer document handoff and public navigation metadata."""

from collections import defaultdict
from enum import Enum
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from dfsa._documents import ParsedDocument

from .common import (
    ContractModel, ErrorDetail, ModuleStatus, NavigationID, RequestContract, SearchSourceID,
    SourceID, Subject, unique_ids,
)
from .search import SearchResult


class NavigationStatus(str, Enum):
    SUCCESS = "success"
    FETCH_FAILED = "fetch_failed"
    PARSE_FAILED = "parse_failed"
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


# These outcomes require acquisition. A fetch failure or policy block can
# occur either before an HTTP request or after one, including at a redirect.
_REQUIRES_PAGE_REQUEST = {
    NavigationStatus.SUCCESS, NavigationStatus.PARSE_FAILED, NavigationStatus.UNSUPPORTED,
}
_PageURL = tuple[str, str, int | None, str, str] | str


def _page_url_key(url: str) -> _PageURL:
    """Compare equivalent HTTP URLs without resolving or rewriting a link."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return url
    if (
        parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None
        or any(char.isspace() or ord(char) < 32 for char in url) or "\\" in url
    ):
        return url
    default_port = 443 if parts.scheme == "https" else 80
    return parts.scheme, parts.hostname, None if port == default_port else port, parts.path or "/", parts.query


class NavigationEntry(ContractModel):
    navigation_id: NavigationID
    source_id: SourceID
    parent_source_id: SourceID | None = None
    root_source_id: SearchSourceID
    url: str
    final_url: str | None = None
    depth: int = Field(ge=0)
    status: NavigationStatus
    reason: str | None = None

    @field_validator("navigation_id")
    @classmethod
    def validate_namespace(cls, value: str) -> str:
        if value.startswith("nav_src_"):
            raise ValueError("Navigation ID cannot use the navigation source namespace")
        return value

    @model_validator(mode="after")
    def validate_final_url(self) -> Self:
        if self.status == NavigationStatus.SUCCESS and self.final_url is None:
            raise ValueError("Successful navigation requires a final URL")
        if self.final_url is not None and isinstance(_page_url_key(self.final_url), str):
            raise ValueError("Navigation final URL must be an absolute HTTP(S) URL")
        return self


def has_technical_navigation_failure(history: list[NavigationEntry]) -> bool:
    failure_statuses = {
        NavigationStatus.FETCH_FAILED, NavigationStatus.PARSE_FAILED, NavigationStatus.UNSUPPORTED,
    }
    return any(entry.status in failure_statuses for entry in history)


def navigation_request_bounds(history: list[NavigationEntry]) -> tuple[set[str], set[str]]:
    """Return source IDs known to have been requested and those possibly requested."""
    required = {entry.source_id for entry in history if entry.status in _REQUIRES_PAGE_REQUEST}
    eligible = {entry.source_id for entry in history if entry.status != NavigationStatus.SKIPPED}
    return required, eligible


def _navigation_page_urls(history: list[NavigationEntry]) -> dict[str, set[_PageURL]]:
    known_urls: defaultdict[str, set[_PageURL]] = defaultdict(set)
    final_urls: dict[str, _PageURL] = {}
    for entry in history:
        if entry.final_url is None:
            continue
        final_url = _page_url_key(entry.final_url)
        if final_url != final_urls.setdefault(entry.source_id, final_url):
            raise ValueError("Navigation records for the same source must agree on the final URL")
        if entry.status != NavigationStatus.SKIPPED:
            # An unvisited path can reuse a known redirect alias but cannot establish one.
            known_urls[entry.source_id].update((_page_url_key(entry.url), final_url))
    for entry in history:
        url = _page_url_key(entry.url)
        if url not in known_urls.setdefault(entry.source_id, {url}):
            raise ValueError("Navigation records for the same source must reference the same page")
    return dict(known_urls)


def validate_navigation(history: list[NavigationEntry], seeds: list[SearchResult]) -> None:
    unique_ids(history, "navigation_id")
    seed_urls = {seed.source_id: seed.url for seed in seeds}
    paths = {(entry.source_id, entry.root_source_id, entry.depth) for entry in history}
    for entry in history:
        if entry.root_source_id not in seed_urls:
            raise ValueError("Navigation root must reference a discovered source")
        if entry.depth == 0:
            if entry.parent_source_id is not None or entry.source_id != entry.root_source_id:
                raise ValueError("Seed navigation must use its search source ID and have no parent")
            if entry.url != seed_urls[entry.root_source_id]:
                raise ValueError("Seed navigation URL must match the discovered search URL")
        elif (entry.source_id in seed_urls) != entry.source_id.startswith("src_"):
            raise ValueError("Navigation must reuse known search source IDs")
        elif (entry.parent_source_id, entry.root_source_id, entry.depth - 1) not in paths:
            raise ValueError("Navigation parent must appear on the same path at the preceding depth")
    for source_id, urls in _navigation_page_urls(history).items():
        if source_id in seed_urls and _page_url_key(seed_urls[source_id]) not in urls:
            raise ValueError("Navigation records must reference the page identified by the search source")


class ExplorationRequest(RequestContract):
    subject: Subject
    search_results: list[SearchResult]


class ExplorationResult(RequestContract):
    status: ModuleStatus
    documents: tuple[ParsedDocument, ...] = ()
    navigation_history: list[NavigationEntry] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)
    limit_reached: bool = False
    attempted_source_ids: tuple[SourceID, ...] = Field(default=(), exclude=True)

    @model_validator(mode="after")
    def validate_documents(self) -> Self:
        unique_ids(self.navigation_history, "navigation_id")
        _navigation_page_urls(self.navigation_history)
        document_ids = unique_ids(self.documents, "source_id")
        successful = [entry for entry in self.navigation_history if entry.status == NavigationStatus.SUCCESS]
        if document_ids != {entry.source_id for entry in successful}:
            raise ValueError("Successful navigation must correspond to an acquired document")
        final_urls = {document.source_id: document.final_url for document in self.documents}
        for entry in successful:
            if entry.final_url != final_urls[entry.source_id]:
                raise ValueError("Successful navigation final URL must match the acquired document")
        original_urls = {(entry.source_id, entry.url) for entry in successful}
        for document in self.documents:
            if (document.source_id, document.original_url) not in original_urls:
                raise ValueError("Acquired document original URL must match successful navigation")
        required_ids, eligible_ids = navigation_request_bounds(self.navigation_history)
        attempted_ids = set(self.attempted_source_ids)
        if not attempted_ids <= eligible_ids:
            raise ValueError("Attempted source IDs must reference non-skipped navigation")
        if not document_ids <= attempted_ids:
            raise ValueError("Acquired documents must reference attempted sources")
        if not required_ids <= attempted_ids:
            raise ValueError("Navigation processing results must reference attempted sources")
        has_failures = bool(self.errors) or has_technical_navigation_failure(self.navigation_history)
        expected = ModuleStatus.SUCCESS
        if self.documents and (has_failures or self.limit_reached):
            expected = ModuleStatus.PARTIAL_SUCCESS
        elif not self.documents and has_failures:
            expected = ModuleStatus.FAILED
        if self.status != expected:
            raise ValueError("Exploration status does not match its documents and failures")
        return self
