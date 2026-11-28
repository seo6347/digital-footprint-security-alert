"""Request-local v0.2 page exploration."""

import heapq
import http.client
import os
import re
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic, sleep
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request

from protego import Protego

from dfsa.contracts import ErrorDetail, ExplorationRequest, ExplorationResult, NavigationEntry, NavigationStatus

from ._types import FetchError, FetchFailure, FetchProblem, ParseFailure
from .fetch import fetch_html
from .parsing import parse_html
from .transport import USER_AGENT, DeadlineExceeded, PinnedHTTPS, SiteScope, remaining
from .url_policy import check_url_text

_ROBOTS_LIMIT = 512 * 1024
_SECTIONS = frozenset({
    "about", "about us", "people", "members", "lab members", "our team", "team", "research",
    "publications", "projects", "lab", "laboratory", "contact", "contact us", "news",
    "소개", "연구실", "연구실 소개", "구성원", "연구실 구성원", "연구", "연구 분야",
    "연구실 소식", "논문", "프로젝트", "연락처",
})
_PERSON_CARDS = {
    "member", "member-card", "member-profile", "person", "person-card", "profile",
    "profile-card", "staff-card", "faculty-card",
}
_PROFILE_LABELS = {"profile", "website", "homepage", "프로필", "홈페이지", "상세 보기"}
_ROBOTS_AGENT = USER_AGENT.split("/", 1)[0]
_UNSUPPORTED = {FetchError.UNSUPPORTED_CONTENT_TYPE, FetchError.UNSUPPORTED_ENCODING}
_approval = ContextVar("explorer_approval", default=None)


@dataclass(frozen=True)
class Limits:
    max_depth: int = 3
    max_pages: int = 30
    max_requests: int = 40
    page_timeout: float = 10
    deadline: float = 90


@dataclass(frozen=True)
class _Candidate:
    url: str
    root: str
    parent: str | None
    depth: int
    rank: int


class _LimitReached(Exception):
    pass


class _AcquiredPage(Exception):
    def __init__(self, url):
        self.url = url


@contextmanager
def approved_exploration(scope, *, robots_approved, network, observer=None):
    """Bind startup approval and transport at the existing callable boundary."""
    token = _approval.set((scope, robots_approved, network, observer))
    try:
        yield
    finally:
        _approval.reset(token)


def _normalize(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _priority(link, name, card, named_cards, target_cards):
    labels = [_normalize(link.text)]
    labels.extend(_normalize(value) for key, value in link.attributes if key == "title" and value)
    if card in named_cards and card not in target_cards:
        return None
    if any(name.search(label) for label in labels):
        return 0
    if card is not None:
        if card in target_cards and any(label in _PROFILE_LABELS or label in _SECTIONS for label in labels):
            return 0
        return None
    if any(label in _SECTIONS for label in labels):
        return 1
    return None


def _person_cards(document, name):
    """Use explicit card markup and headings without guessing other names."""
    card_for_block = {}
    heading_for_block = {}
    heading_text = {}
    for block in document.blocks:
        markers = {
            token.replace("_", "-")
            for key, value in block.attributes if key in {"class", "id"} and value
            for token in value.casefold().split()
        }
        parent_card = card_for_block.get(block.parent_id)
        card_for_block[block.block_id] = block.block_id if markers & _PERSON_CARDS else parent_card
        heading_for_block[block.block_id] = (
            block.block_id if block.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
            else heading_for_block.get(block.parent_id)
        )

    for text in document.texts:
        card = card_for_block[text.block_id]
        heading = heading_for_block[text.block_id]
        if card is not None and heading is not None:
            heading_text.setdefault((card, heading), []).append(text.raw_text)
    named_cards = {card for (card, _), parts in heading_text.items() if _normalize("".join(parts))}
    target_cards = {
        card for (card, _), parts in heading_text.items() if name.fullmatch(_normalize("".join(parts)))
    }
    return card_for_block, named_cards, target_cards


class _Session:
    def __init__(self, scope, robots_approved, network, clock, limits, wait):
        self.scope = scope
        self.robots_approved = robots_approved
        self.network = network
        self.clock = clock
        self.wait = wait
        self.limits = limits
        self.deadline = clock() + limits.deadline
        self.page_deadline = self.deadline
        self.pages = 0
        self.requests = 0
        self.robots_requests = 0
        self.page_requested = False
        self.limit_reached = False
        self.successful = set()
        self.rules = None
        self.rules_failure = None
        self.last_request = None

    def page(self):
        self.page_requested = False
        self.page_deadline = min(self.deadline, self.clock() + self.limits.page_timeout)

    def request(self, url, *, robots=False):
        if self.requests >= self.limits.max_requests:
            raise _LimitReached("http_budget")
        remaining(self.page_deadline, self.clock)

        def started():
            remaining(self.page_deadline, self.clock)
            self.requests += 1
            if robots:
                self.robots_requests += 1
            else:
                if not self.page_requested:
                    self.pages += 1
                self.page_requested = True
                self.last_request = self.clock()

        return self.network.request(
            url, deadline=self.page_deadline, on_request=started,
            headers={
                "User-Agent": USER_AGENT, "Accept-Encoding": "identity",
                "Accept": "text/plain" if robots else "text/html, application/xhtml+xml",
            },
        )

    def _check_robots(self, url):
        if not self.robots_approved:
            raise FetchProblem(FetchError.BLOCKED_URL, "robots_not_approved")
        if self.rules_failure is not None:
            kind, message = self.rules_failure
            raise FetchProblem(kind, message)
        if self.rules is None:
            try:
                self.rules = self._read_robots()
            except FetchProblem as exc:
                self.rules_failure = (exc.kind, str(exc))
                raise
            except (OSError, http.client.HTTPException) as exc:
                cause = exc.reason if isinstance(exc, URLError) else exc
                self.rules_failure = (
                    (FetchError.TIMEOUT, "robots_timeout") if isinstance(cause, TimeoutError)
                    else (FetchError.NETWORK_ERROR, "robots_unavailable")
                )
                raise FetchProblem(*self.rules_failure) from None
        if not self.rules.can_fetch(url, _ROBOTS_AGENT):
            raise FetchProblem(FetchError.BLOCKED_URL, "robots_disallowed")
        rate = self.rules.request_rate(_ROBOTS_AGENT)
        if self.rules.visit_time(_ROBOTS_AGENT) or (rate and (rate.start_time or rate.end_time)):
            raise FetchProblem(FetchError.BLOCKED_URL, "robots_time_window")
        interval = self.rules.crawl_delay(_ROBOTS_AGENT) or 0
        if rate and rate.requests is not None and rate.seconds is not None:
            if rate.requests <= 0:
                raise FetchProblem(FetchError.BLOCKED_URL, "robots_request_rate")
            interval = max(interval, rate.seconds / rate.requests)
        if self.last_request is not None:
            delay = interval - (self.clock() - self.last_request)
            if delay > 0:
                if delay >= remaining(self.page_deadline, self.clock):
                    raise _LimitReached("robots_delay")
                self.wait(delay)

    def _read_robots(self):
        # Approval covers exactly this control resource, outside the page subtree.
        # Redirects cannot expand that approval to another resource or origin.
        with self.request(self.scope.robots_url, robots=True) as response:
            if response.code in (404, 410):
                return Protego.parse("")
            if response.code in (401, 403) or 300 <= response.code < 400:
                raise FetchProblem(FetchError.BLOCKED_URL, "robots_access_denied")
            if not 200 <= response.code < 300:
                raise FetchProblem(FetchError.NETWORK_ERROR, "robots_unavailable")
            if (len(response.headers.get_all("Content-Type", [])) != 1
                    or response.headers.get_content_type() != "text/plain"
                    or response.headers.get("Content-Encoding", "identity").lower() != "identity"):
                raise FetchProblem(FetchError.INVALID_RESPONSE, "robots_invalid_response")
            body = bytearray()
            while chunk := response.read(min(65536, _ROBOTS_LIMIT + 1 - len(body))):
                body.extend(chunk)
                if len(body) > _ROBOTS_LIMIT:
                    raise FetchProblem(FetchError.BODY_TOO_LARGE, "robots_body_too_large")
            lengths = response.headers.get_all("Content-Length", [])
            if lengths and (len(lengths) != 1 or lengths[0].strip() != str(len(body))):
                raise FetchProblem(FetchError.INVALID_RESPONSE, "robots_invalid_length")
            try:
                text = body.decode("utf-8-sig")
            except UnicodeError:
                raise FetchProblem(FetchError.INVALID_RESPONSE, "robots_invalid_encoding") from None
            if "\x00" in text:
                raise FetchProblem(FetchError.INVALID_RESPONSE, "robots_invalid_encoding")
            return Protego.parse(text)

    def open(self, request, *, timeout):
        remaining(self.page_deadline, self.clock)
        normalized = self.scope.prepare(request.full_url)
        if normalized in self.successful:
            raise _AcquiredPage(normalized)
        self._check_robots(normalized)
        return self.request(normalized)


def explore(request, *, scope, robots_approved, network, limits=Limits(), clock=monotonic, wait=sleep, observer=None):
    """Explore one approved scope; all execution state belongs to this request."""
    session = _Session(scope, robots_approved, network, clock, limits, wait)
    queue = []
    history = []
    documents = {}
    errors = []
    attempts = {}
    seen = {}
    duplicate_redirects = {}
    order = 0
    next_source = 0
    name = re.compile(r"(?<!\w)" + re.escape(_normalize(request.subject.name)) + r"(?!\w)")

    def enqueue(candidate, priority):
        nonlocal order
        heapq.heappush(queue, (candidate.depth, priority, candidate.rank, order, candidate))
        order += 1

    def record(item, source_id, status, *, final_url=None, reason=None):
        history.append(NavigationEntry(
            navigation_id=f"nav_{len(history) + 1:04d}", source_id=source_id,
            parent_source_id=item.parent, root_source_id=item.root, url=item.url,
            final_url=final_url, depth=item.depth, status=status, reason=reason,
        ))

    def children(document, item):
        cards, named, targets = _person_cards(document, name)
        for link in document.links:
            priority = _priority(link, name, cards.get(link.block_id), named, targets)
            if priority is None:
                continue
            try:
                href = link.href.strip(" ")
                check_url_text(href)
                url = scope.prepare(urljoin(document.final_url, href))
            except (FetchProblem, ValueError):
                continue
            enqueue(_Candidate(url, item.root, document.source_id, item.depth + 1, item.rank), priority)

    for seed in sorted(request.search_results, key=lambda seed: (seed.rank, seed.source_id)):
        enqueue(_Candidate(seed.url, seed.source_id, None, 0, seed.rank), 0)

    while queue:
        _, _, _, _, item = heapq.heappop(queue)
        source_id = item.root if item.depth == 0 else None
        if scope is None or not scope.contains(item.url):
            # Out-of-scope child links are not carried into public history.
            if source_id is not None:
                record(item, source_id, NavigationStatus.BLOCKED, reason="outside_approved_scope")
            continue
        key = scope.prepare(item.url)
        if source_id is None:
            source_id = seen.get(key)
            if source_id is None:
                next_source += 1
                source_id = f"nav_src_{next_source:04d}"
        if key in seen:
            previous = documents.get(seen[key])
            record(item, source_id, NavigationStatus.SKIPPED,
                   final_url=previous.final_url if previous else duplicate_redirects.get(key),
                   reason="duplicate_page")
            continue
        if (item.depth > limits.max_depth or session.pages >= limits.max_pages
                or session.requests >= limits.max_requests or clock() >= session.deadline):
            session.limit_reached = True
            record(item, source_id, NavigationStatus.SKIPPED, reason="exploration_limit")
            continue

        seen[key] = source_id
        session.page()
        try:
            fetched = fetch_html(
                _FetchTarget(source_id, item.url), opener=session, prepare_url=scope.prepare,
                user_agent=USER_AGENT, timeout=limits.page_timeout,
            )
        except _AcquiredPage as alias:
            # The redirecting URL was requested, but policy stopped the chain
            # before a second acquisition. Keep its own ID and resolved alias.
            attempts[source_id] = None
            duplicate_redirects[key] = alias.url
            record(item, source_id, NavigationStatus.BLOCKED, final_url=alias.url, reason="duplicate_redirect")
            continue
        except _LimitReached as exc:
            session.limit_reached = True
            if session.page_requested:
                attempts[source_id] = None
                record(item, source_id, NavigationStatus.FETCH_FAILED, reason=str(exc))
                errors.append(ErrorDetail(code="exploration_limit", message="Page did not finish within exploration limits",
                                          retryable=False, source_id=source_id))
            else:
                record(item, source_id, NavigationStatus.SKIPPED, reason=str(exc))
            continue
        if session.page_requested:
            attempts[source_id] = None
        if clock() >= session.deadline:
            session.limit_reached = True
        if isinstance(fetched, FetchFailure):
            if fetched.kind == FetchError.BLOCKED_URL:
                record(item, source_id, NavigationStatus.BLOCKED, reason=fetched.error.message)
            else:
                status = NavigationStatus.UNSUPPORTED if fetched.kind in _UNSUPPORTED else NavigationStatus.FETCH_FAILED
                record(item, source_id, status, reason=fetched.kind.value)
                errors.append(fetched.error)
            continue
        try:
            remaining(session.page_deadline, clock)
            document = parse_html(fetched)
            remaining(session.page_deadline, clock)
        except DeadlineExceeded:
            if clock() >= session.deadline:
                session.limit_reached = True
            record(item, source_id, NavigationStatus.PARSE_FAILED, reason="parse_deadline")
            errors.append(ErrorDetail(code="parse_deadline", message="Parsing exceeded its deadline",
                                      retryable=False, source_id=source_id))
            continue
        if isinstance(document, ParseFailure):
            record(item, source_id, NavigationStatus.PARSE_FAILED, reason=document.kind.value)
            errors.append(document.error)
        else:
            documents[source_id] = document
            final_key = scope.prepare(document.final_url)
            session.successful.add(final_key)
            seen[final_key] = source_id
            record(item, source_id, NavigationStatus.SUCCESS, final_url=document.final_url)
            children(document, item)

    status = "success"
    if documents and (errors or session.limit_reached):
        status = "partial_success"
    elif errors:
        status = "failed"
    if observer is not None:
        observer(session.requests, session.robots_requests)
    return ExplorationResult(
        schema_version=request.schema_version, request_id=request.request_id, status=status,
        documents=tuple(documents.values()), navigation_history=history, errors=errors,
        limit_reached=session.limit_reached, attempted_source_ids=tuple(attempts),
    )


@dataclass(frozen=True)
class _FetchTarget:
    source_id: str
    url: str


def run_exploration(request: ExplorationRequest) -> ExplorationResult:
    approval = _approval.get()
    if approval is None:
        endpoint = os.environ.get("DFSA_V02_EXPLORER_SCOPE")
        scope = SiteScope(endpoint) if endpoint else None
        approval = (scope, os.environ.get("DFSA_V02_EXPLORER_ROBOTS_APPROVED") == "1", PinnedHTTPS(), None)
    scope, robots_approved, network, observer = approval
    return explore(request, scope=scope, robots_approved=robots_approved, network=network, observer=observer)
