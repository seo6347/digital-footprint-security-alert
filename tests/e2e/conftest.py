"""Offline HTTP/DNS boundaries; all public module callables remain real."""

import io
import json
import socket
import sys
import urllib.request
from dataclasses import dataclass, field
from email.message import Message
from html import escape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from dfsa.contracts import Subject
from dfsa.modules.explorer import fetch
from dfsa.modules.profiling import run_profiling
from dfsa.modules.risk.engine import run_risk
from dfsa.modules.search import provider, run_search
from dfsa.service import orchestrator


class Reply(io.BytesIO):
    def __init__(self, body, *, code=200, content_type="text/html; charset=utf-8", location=None):
        super().__init__(body)
        self.code = code
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if location is not None:
            self.headers["Location"] = location


@dataclass
class OfflineHTTP:
    # Values are HTTP payloads or external exceptions, never public responses.
    results: list = field(default_factory=list)
    pages: dict = field(default_factory=dict)
    query_outcomes: dict = field(default_factory=dict)
    dns_answers: dict = field(default_factory=dict)
    search_calls: list = field(default_factory=list)
    html_calls: list = field(default_factory=list)
    dns_calls: list = field(default_factory=list)

    def search(self, request, *, timeout):
        parts = urlsplit(request.full_url)
        assert (parts.scheme, parts.netloc, parts.path) == ("https", "serpapi.com", "/search.json")
        assert timeout > 0
        params = parse_qs(parts.query)
        assert params["api_key"] == ["offline-placeholder-not-a-secret"]
        query = params["q"][0]
        self.search_calls.append(query)  # Never retain the credential-bearing URL.
        outcome = self.query_outcomes.get(query, {
            "search_metadata": {"status": "Success"}, "organic_results": self.results,
        })
        if isinstance(outcome, Exception):
            raise outcome
        body = outcome if isinstance(outcome, bytes) else json.dumps(outcome).encode("utf-8")
        return Reply(body, content_type="application/json")

    def open(self, request, *, timeout):
        assert timeout > 0
        url = request.full_url
        self.html_calls.append(url)
        if url not in self.pages:
            pytest.fail("Unexpected HTML request escaped the offline route table")
        outcome = self.pages[url]
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, dict):
            return Reply(**outcome)
        return Reply(outcome.encode("utf-8") if isinstance(outcome, str) else outcome)

    def resolve(self, host, port, **kwargs):
        self.dns_calls.append((host, port))
        allowed = {urlsplit(url).hostname for url in self.pages}
        if host not in allowed:
            pytest.fail("Unexpected DNS lookup escaped the offline route table")
        addresses = self.dns_answers.get(host, ["93.184.216.34"])
        if isinstance(addresses, Exception):
            raise addresses
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
                for address in addresses]


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    """Fail closed even if an adapter accidentally uses another stdlib client."""
    def forbidden(*args, **kwargs):
        pytest.fail("Real network access is forbidden in offline E2E")

    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "create_connection"):
        monkeypatch.setattr(socket, name, forbidden)
    for name in ("connect", "connect_ex", "sendto", "sendall"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    monkeypatch.setattr(provider, "urlopen", forbidden)
    # An existing developer key is never used or copied into fixtures.
    monkeypatch.setenv("SERPAPI_API_KEY", "offline-placeholder-not-a-secret")


@pytest.fixture
def offline(monkeypatch, deny_network):
    http = OfflineHTTP()
    monkeypatch.setattr(provider, "urlopen", http.search)
    monkeypatch.setattr(fetch, "_build_opener", lambda: http)
    monkeypatch.setattr(socket, "getaddrinfo", http.resolve)
    return http


@pytest.fixture
def pipeline(monkeypatch, offline):
    """Observe calls with a profiler, without replacing/wrapping A, B or C.

    Snapshots prove the actual stage boundaries, including skipped stages and
    unchanged IDs/explanations. The previous profiler and wiring are restored.
    """
    functions = {"A": run_search, "B": run_profiling, "C": run_risk}
    trace = SimpleNamespace(order=[], inputs={stage: [] for stage in functions},
                            outputs={stage: [] for stage in functions})
    codes = {function.__code__: stage for stage, function in functions.items()}
    for name, function in zip(("run_search", "run_profiling", "run_risk"), functions.values()):
        monkeypatch.setattr(orchestrator, name, function)
        assert getattr(orchestrator, name) is function

    previous = sys.getprofile()

    def observe(frame, event, value):
        stage = codes.get(frame.f_code)
        if stage is not None:
            if event == "call":
                trace.order.append(stage)
                trace.inputs[stage].append(frame.f_locals["request"].model_copy(deep=True))
            elif event == "return" and value is not None:
                trace.outputs[stage].append(value.model_copy(deep=True))
        if previous is not None:
            previous(frame, event, value)

    sys.setprofile(observe)
    try:
        yield trace
    finally:
        sys.setprofile(previous)


@pytest.fixture
def subject():
    return Subject(name="Alice Kim", organization="Example University", email="alice@example.com")


@pytest.fixture
def html_fixture():
    def read(name):
        return (Path(__file__).parent / "fixtures" / f"{name}.html").read_text(encoding="utf-8")
    return read


@pytest.fixture
def card():
    def build(*fields, name="Alice Kim", email="alice@example.com", organization=None):
        text = f'<article class="profile-card"><h2>{escape(name)}</h2>'
        if email is not None:
            text += f"<p>Email: {escape(email)}</p>"
        if organization is not None:
            text += f"<p>Organization: {escape(organization)}</p>"
        return text + "".join(fields) + "</article>"
    return build


@pytest.fixture
def item():
    def build(path="/alice", *, title="Alice Kim — Example University", snippet="alice@example.com", position=1):
        return {"link": "https://example.com" + path, "title": title,
                "snippet": snippet, "position": position}
    return build


@pytest.fixture
def happy(offline, html_fixture, item):
    offline.results = [item()]
    offline.pages["https://example.com/alice"] = html_fixture("profile")
    return offline
