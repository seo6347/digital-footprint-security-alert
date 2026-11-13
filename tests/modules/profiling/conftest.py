import io
import socket
from email.message import Message

import pytest

from dfsa.contracts.search import SearchResult


class FakeResponse(io.BytesIO):
    def __init__(self, body=b"<html>hello</html>", *, code=200, headers=None):
        super().__init__(body)
        self.code = code
        self.headers = Message()
        for key, value in (headers if headers is not None else {"Content-Type": "text/html"}).items():
            self.headers[key] = value
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)

    def info(self):
        return self.headers


class FakeOpener:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unit tests must not access the network")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def public_dns():
    def resolve(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", port, 0, 0))]
    return resolve


@pytest.fixture
def source():
    return SearchResult(
        source_id="src_001", url="https://example.com/profile",
        normalized_url="https://example.com/untrusted-normalized", rank=1,
        relevance={"status": "candidate", "reasons": ["name_match"]},
        discovered_by=[{"query_id": "q_001"}],
    )


@pytest.fixture
def response_factory():
    return FakeResponse


@pytest.fixture
def opener_factory():
    return FakeOpener


@pytest.fixture
def phase4_subject():
    from dfsa.contracts.common import Subject

    return Subject(name="Alice Kim", organization="Example University", email="alice@example.com")


@pytest.fixture
def phase4_parse():
    from dfsa.modules.profiling._types import FetchedHTML, ParsedDocument
    from dfsa.modules.profiling.parsing import parse_html

    def parse(html):
        result = parse_html(FetchedHTML(
            "src_phase4", "https://example.com/old", "https://example.com/profile",
            html.encode("utf-8"), "text/html", None, 200,
        ))
        assert isinstance(result, ParsedDocument)
        return result
    return parse


@pytest.fixture
def phase4_card():
    def card(fields="", name="Alice Kim"):
        return (f'<div class="profile-card"><h2>{name}</h2>'
                f'<p>Email: alice@example.com</p>{fields}</div>')
    return card
