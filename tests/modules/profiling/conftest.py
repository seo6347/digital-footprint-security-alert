import socket

import pytest

from dfsa.contracts.search import SearchResult


@pytest.fixture(autouse=True)
def no_real_network(deny_unit_network):
    """Apply the shared network guard to this test package."""


@pytest.fixture
def phase4_subject():
    from dfsa.contracts.common import Subject

    return Subject(name="Alice Kim", organization="Example University", email="alice@example.com")


@pytest.fixture
def phase4_parse():
    from dfsa._documents import ParsedDocument
    from dfsa.modules.explorer._types import FetchedHTML
    from dfsa.modules.explorer.parsing import parse_html

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


@pytest.fixture
def phase6_request(phase4_subject):
    from dfsa.contracts.profiling import ProfilingRequest

    def build(source_ids=("src_001",), *, subject=None, request_id="req_phase6"):
        return ProfilingRequest(
            schema_version="v0.1", request_id=request_id,
            subject=(subject or phase4_subject).model_copy(deep=True),
            search_results=[SearchResult(
                source_id=source_id, url=f"https://example.com/{source_id}",
                normalized_url="https://example.com/not-the-fetch-target", rank=index,
                title="Untrusted search title", snippet="SNIPPET IS NOT EVIDENCE",
                relevance={"status": "candidate", "reasons": ["name_match"]},
                discovered_by=[{"query_id": "q_first"}, {"query_id": "q_second"}],
            ) for index, source_id in enumerate(source_ids, 1)],
        )
    return build


@pytest.fixture
def phase6_html(phase4_card):
    return {
        "confirmed": phase4_card('<p>Lab: AI &amp; Security Lab</p>'),
        "uncertain": '<div class="profile-card"><h2>Alice Kim</h2></div>',
        "rejected": ('<div class="profile-card"><p>Name: Bob Lee</p>'
                     '<p>Email: bob@example.net</p></div>'),
        # Identity can join inline text for comparison; Phase 4 cannot fabricate
        # a contiguous evidence quotation across the intervening HTML tags.
        "zero": ('<div class="profile-card"><h2>Alice <b>Kim</b></h2>'
                 '<p>Email: alice<b>@</b>example.com</p></div>'),
        "empty": "",
    }


@pytest.fixture
def phase6_transport(monkeypatch, public_dns, response_factory, opener_factory):
    from dfsa.modules.explorer import fetch

    def install(payloads):
        responses = [response_factory(item.encode("utf-8") if isinstance(item, str) else item)
                     if isinstance(item, (str, bytes)) else item for item in payloads]
        opener = opener_factory(*responses)
        monkeypatch.setattr(socket, "getaddrinfo", public_dns)
        monkeypatch.setattr(fetch, "_build_opener", lambda: opener)
        return opener
    return install
