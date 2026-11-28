"""Synthetic v0.2 exploration through the real parser and result contracts."""

import io
import socket
import threading
from email.message import Message
from time import monotonic
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from dfsa.contracts import (
    DFSAResult, ExplorationRequest, ProfilingResponse, SearchResult, Source, Subject,
)
from dfsa.contracts.exploration import validate_navigation
from dfsa.modules.explorer import runner
from dfsa.modules.explorer.transport import DeadlineExceeded, PinnedHTTPS, SiteScope, _bounded_dns
from dfsa.service import orchestrator, run_pipeline

HOST = "https://lab.example.org"
ROBOTS = HOST + "/robots.txt"
PEOPLE = HOST + "/pages/people"
RULES = b"User-agent: DFSA\nAllow: /pages/\nUser-agent: *\nDisallow: /\n"


class Reply(io.BytesIO):
    def __init__(self, body=b"", *, code=200, media="text/html", location=None):
        super().__init__(body)
        self.code = code
        self.headers = Message()
        self.headers["Content-Type"] = media
        self.headers["Content-Length"] = str(len(body))
        if location is not None:
            self.headers["Location"] = location


class Network:
    def __init__(self, pages=None, *, robots=RULES):
        self.pages = {ROBOTS: robots if isinstance(robots, Reply) else Reply(robots, media="text/plain")}
        self.pages.update(pages or {})
        self.calls = []

    def request(self, url, *, headers, deadline, on_request):
        self.calls.append((url, headers["User-Agent"], deadline))
        assert url in self.pages, f"Unexpected HTTP request for {url}"
        reply = self.pages.pop(url)
        if isinstance(reply, Exception):
            raise reply
        on_request()
        return reply


def make_request(*urls):
    return ExplorationRequest(
        schema_version="v0.2", request_id="req_explorer",
        subject=Subject(name="Alex Kim", organization="Example University"),
        search_results=[
            SearchResult(
                source_id=f"src_{i}", url=url, normalized_url=url, rank=i,
                relevance={"status": "uncertain", "reasons": ["insufficient_evidence"]},
                discovered_by=[{"query_id": "q_001"}],
            )
            for i, url in enumerate(urls, 1)
        ],
    )


def run(network, *urls, approved=True, limits=runner.Limits(), clock=monotonic, scope=HOST + "/pages/"):
    request = make_request(*urls)
    result = runner.explore(
        request, scope=SiteScope(scope), robots_approved=approved, network=network, limits=limits, clock=clock,
    )
    validate_navigation(result.navigation_history, request.search_results)
    return result


def test_bfs_uses_uncertain_seed_and_target_links_without_collecting_other_profiles():
    seed = b"""<title>People</title><p>Original &amp; exact</p>
    <a href="news?view=current">News</a><a href="a">Alex Kim</a>
    <a href="other">Jamie Lee</a><a href="https://other.example.org/about">About</a>
    <a href="/outside/team">People</a><a href="news?view=current#tab">News</a>
    """
    network = Network({
        PEOPLE: Reply(seed),
        HOST + "/pages/a": Reply(b'<a href="research">Research</a><p>Alex Kim</p>'),
        HOST + "/pages/news?view=current": Reply(b"<p>News</p>"),
        HOST + "/pages/research": Reply(b"<p>Research</p>"),
    })
    result = run(network, PEOPLE, "https://other.example.org/people")
    assert result.status == "success"
    assert [url for url, _, _ in network.calls] == [
        ROBOTS, PEOPLE, HOST + "/pages/a", HOST + "/pages/news?view=current", HOST + "/pages/research",
    ]
    assert {agent for _, agent, _ in network.calls} == {"DFSA/0.2"}
    assert result.navigation_history[1].status == "blocked"
    assert result.navigation_history[-1].depth == 2
    skipped = [entry for entry in result.navigation_history if entry.reason == "duplicate_page"]
    assert len(skipped) == 1
    assert skipped[0].source_id == result.documents[2].source_id
    assert result.documents[0].source_id == "src_1"
    assert result.documents[0].html_text == seed.decode("utf-8")
    assert "&amp;" in result.documents[0].html_text
    assert any(seed.decode("utf-8")[text.start:text.end] == "&amp;" for text in result.documents[0].texts)


def test_redirect_convergence_and_rediscovery_through_orchestrator(monkeypatch, v02_fixtures):
    first = HOST + "/pages/first"
    alias = HOST + "/pages/alias"
    child = HOST + "/pages/another-alias"
    group = HOST + "/pages/group"
    network = Network({
        first: Reply(code=302, location="people"),
        PEOPLE: Reply(b'<a href="another-alias">Research</a><a href="alias">About</a>'),
        alias: Reply(code=302, location="people"),
        child: Reply(code=301, location=PEOPLE),
        group: Reply(b'<a href="another-alias">Research</a><a href="people">People</a>'),
    })
    seed_request = make_request(first, alias, group, PEOPLE)
    result_by_stage = {}
    counts = []

    def search(request):
        response = v02_fixtures["stage_responses"](request.request_id)[0]
        query_id = next(query.query_id for query in response.queries if query.status == "success")
        return response.model_copy(update={"results": [
            seed.model_copy(update={"discovered_by": [{"query_id": query_id}]})
            for seed in seed_request.search_results
        ]})

    def exploration(request):
        result = runner.run_exploration(request)
        result_by_stage["exploration"] = result
        return result

    def profiling(request):
        assert [(doc.source_id, doc.original_url, doc.final_url) for doc in request.documents] == [
            ("src_1", first, PEOPLE), ("src_3", group, group),
        ]
        return ProfilingResponse(
            schema_version=request.schema_version, request_id=request.request_id, status="success",
            sources=[
                Source(source_id=doc.source_id, url=doc.final_url, processing_status="success",
                       identity_status="uncertain")
                for doc in request.documents
            ],
        )

    monkeypatch.setattr(orchestrator, "run_search", search)
    monkeypatch.setattr(orchestrator, "run_exploration", exploration)
    monkeypatch.setattr(orchestrator, "run_profiling", profiling)
    with runner.approved_exploration(
        SiteScope(HOST + "/pages/"), robots_approved=True, network=network,
        observer=lambda requests, robots: counts.append((requests, robots)),
    ):
        result = run_pipeline(seed_request.subject)
    exploration_result = result_by_stage["exploration"]
    assert result.status == "success" and not result.errors
    assert result.stages.analysis == "not_started"
    assert result.summary.visited_page_count == 4
    assert [source.source_id for source in result.sources] == ["src_1", "src_3"]
    assert len(exploration_result.documents) == 2
    assert exploration_result.attempted_source_ids == ("src_1", "src_2", "src_3", "nav_src_0001")
    assert [(entry.source_id, entry.parent_source_id, entry.root_source_id, entry.depth,
             entry.url, entry.final_url, entry.status, entry.reason)
            for entry in result.navigation_history] == [
        ("src_1", None, "src_1", 0, first, PEOPLE, "success", None),
        ("src_2", None, "src_2", 0, alias, PEOPLE, "blocked", "duplicate_redirect"),
        ("src_3", None, "src_3", 0, group, group, "success", None),
        ("src_4", None, "src_4", 0, PEOPLE, PEOPLE, "skipped", "duplicate_page"),
        ("nav_src_0001", "src_1", "src_1", 1, child, PEOPLE, "blocked", "duplicate_redirect"),
        ("src_2", "src_1", "src_1", 1, alias, PEOPLE, "skipped", "duplicate_page"),
        ("nav_src_0001", "src_3", "src_3", 1, child, PEOPLE, "skipped", "duplicate_page"),
        ("src_1", "src_3", "src_3", 1, PEOPLE, PEOPLE, "skipped", "duplicate_page"),
    ]
    assert DFSAResult.model_validate_json(result.model_dump_json()) == result
    assert [url for url, _, _ in network.calls] == [ROBOTS, first, PEOPLE, alias, group, child]
    assert counts == [(6, 1)]


def test_relative_link_uses_redirect_final_path_and_keeps_discovery_url():
    final = HOST + "/pages/lab/index"
    child = HOST + "/pages/lab/about"
    network = Network({
        PEOPLE: Reply(code=302, location="lab/index"),
        final: Reply(b'<a href="about">About</a>'),
        child: Reply(b"<p>About</p>"),
    })
    result = run(network, PEOPLE)
    assert result.documents[0].original_url == PEOPLE
    assert result.documents[0].final_url == final
    assert result.navigation_history[1].url == child


@pytest.mark.parametrize(("robots", "expected_status", "reason"), [
    (Reply(b"User-agent: DFSA\nDisallow: /pages/\n", media="text/plain"), "success", "robots_disallowed"),
    (Reply(code=403), "success", "robots_access_denied"),
    (Reply(code=302, location="https://other.example.org/robots.txt"), "success", "robots_access_denied"),
    (Reply(code=503), "failed", "network_error"),
    (Reply(b"<html>not rules</html>"), "failed", "invalid_response"),
])
def test_robots_fail_closed_and_never_counts_as_a_page(robots, expected_status, reason):
    network = Network(robots=robots)
    result = run(network, PEOPLE)
    assert result.status == expected_status
    assert result.navigation_history[0].reason == reason
    assert not result.documents and not result.attempted_source_ids
    assert [url for url, _, _ in network.calls] == [ROBOTS]


@pytest.mark.parametrize("code", [404, 410])
def test_unavailable_robots_allows_only_approved_pages(code):
    network = Network({PEOPLE: Reply()}, robots=Reply(code=code))
    result = run(network, PEOPLE, "https://outside.example.org/people")
    assert len(result.documents) == 1
    assert result.attempted_source_ids == ("src_1",)


def test_no_robots_approval_schedules_no_network():
    net = Network()
    assert run(net, PEOPLE, approved=False).navigation_history[0].reason == "robots_not_approved"
    assert not net.calls


def test_blocked_redirect_records_the_page_request_without_connecting_to_target():
    net = Network({PEOPLE: Reply(code=302, location="https://other.example.org/profile")})
    result = run(net, PEOPLE)
    assert result.navigation_history[-1].status == "blocked"
    assert result.attempted_source_ids == ("src_1",)
    assert result.navigation_history[-1].final_url is None


@pytest.mark.parametrize("limits", [
    runner.Limits(max_depth=0), runner.Limits(max_pages=1), runner.Limits(max_requests=2),
])
def test_limits_keep_results_with_unexecuted_pending_work(limits):
    network = Network({PEOPLE: Reply(b'<a href="about">About</a>')})
    result = run(network, PEOPLE, limits=limits)
    assert result.status == "partial_success" and result.limit_reached
    assert result.navigation_history[-1].status == "skipped"
    assert result.attempted_source_ids == ("src_1",)
    assert len(network.calls) == 2


def test_request_limit_includes_robots_and_redirect_hops():
    network = Network({PEOPLE: Reply(code=302, location="other")})
    result = run(network, PEOPLE, limits=runner.Limits(max_requests=2))
    assert result.limit_reached
    assert result.status == "failed"
    assert result.navigation_history[-1].reason == "http_budget"
    assert result.attempted_source_ids == ("src_1",)


def test_shared_deadline_discards_late_documents_and_stops_new_pages():
    now = [0]
    other = HOST + "/pages/other"

    class Slow(Network):
        def request(self, url, **kwargs):
            reply = super().request(url, **kwargs)
            if url == PEOPLE:
                now[0] = 90
            return reply

    network = Slow({PEOPLE: Reply(b"<p>Too late</p>")})
    result = run(network, PEOPLE, other, clock=lambda: now[0])
    assert result.limit_reached and result.status == "failed"
    assert not result.documents
    assert result.attempted_source_ids == ("src_1",)
    assert [status.status for status in result.navigation_history] == ["parse_failed", "skipped"]
    assert {deadline for _, _, deadline in network.calls} == {10}


def test_dns_wait_has_a_deadline_even_when_os_lookup_is_still_running():
    release = threading.Event()
    try:
        with pytest.raises(DeadlineExceeded, match="DNS deadline"):
            _bounded_dns(lambda *args, **kwargs: release.wait(2), "lab.example.org", 443, 0.01)
    finally:
        release.set()


def test_target_member_card_context_does_not_open_another_members_generic_links():
    body = b"""
    <div class="member-card"><h2>Jamie Lee</h2><a href="other" title="With Alex Kim">Research</a></div>
    <div class="profile-card"><h2>Alex <span>Kim</span></h2><a href="target">Profile</a></div>
    <a href="lab">Research</a>
    """
    network = Network({
        PEOPLE: Reply(body), HOST + "/pages/target": Reply(), HOST + "/pages/lab": Reply(),
    })
    assert len(run(network, PEOPLE).documents) == 3
    assert [url for url, _, _ in network.calls] == [ROBOTS, PEOPLE, HOST + "/pages/target", HOST + "/pages/lab"]


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_https_drops_response_when_deadline_elapses_during_io(monkeypatch, phase):
    now = [0]
    closes = []

    class Socket:
        def settimeout(self, timeout):
            assert 0 < timeout <= 5

        def shutdown(self, operation):
            pass

    def late_body(size):
        now[0] = 5
        return b"late"

    class Connection:
        def __init__(self, host, *, timeout, context):
            self.sock = Socket()

        def connect(self):
            pass

        def request(self, method, path, *, headers):
            pass

        def getresponse(self):
            if phase == "headers":
                now[0] = 5
            return SimpleNamespace(status=200, headers=Message(), read=late_body, close=lambda: None)

        def close(self):
            closes.append(True)

    monkeypatch.setattr(runner.http.client, "HTTPSConnection", Connection)
    network = PinnedHTTPS(clock=lambda: now[0], resolve=lambda host, port, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
    ])
    with pytest.raises(DeadlineExceeded):
        with network.request(PEOPLE, deadline=5, headers={}) as response:
            response.read(4)
    assert closes == [True]


def test_production_entrypoint_uses_the_approved_scope(monkeypatch):
    network = Network({PEOPLE: Reply(b"<p>Approved page</p>")})
    monkeypatch.setenv("DFSA_V02_EXPLORER_SCOPE", HOST + "/pages/")
    monkeypatch.setenv("DFSA_V02_EXPLORER_ROBOTS_APPROVED", "1")
    monkeypatch.setattr(runner, "PinnedHTTPS", lambda: network)
    request = make_request(PEOPLE)
    response = runner.run_exploration(request)
    assert response.request_id == request.request_id
    assert response.documents[0].source_id == "src_1"
    assert [url for url, _, _ in network.calls] == [ROBOTS, PEOPLE]


def test_preflight_dns_timeout_does_not_count_as_an_http_attempt():
    network = Network({PEOPLE: DeadlineExceeded("DNS deadline exceeded")})
    result = run(network, PEOPLE)
    assert result.status == "failed"
    assert result.errors[0].code == "timeout"
    assert not result.attempted_source_ids


@pytest.mark.parametrize(("phase", "requests", "attempted", "error"), [
    ("dns", [ROBOTS], (), "timeout"),
    ("robots", [ROBOTS], (), "timeout"),
    ("http", [ROBOTS, PEOPLE], ("src_1",), "timeout"),
    ("redirect", [ROBOTS, PEOPLE], ("src_1",), "timeout"),
    ("parse", [ROBOTS, PEOPLE], ("src_1",), "parse_deadline"),
    ("parse_signal", [ROBOTS, PEOPLE], ("src_1",), "parse_deadline"),
])
def test_deadline_at_each_phase_is_reported_without_starting_more_work(
    monkeypatch, phase, requests, attempted, error,
):
    now = [0]
    target = HOST + "/pages/target"
    parser = runner.parse_html

    class ExpiringReply(Reply):
        def read(self, size=-1):
            now[0] = 5
            # The HTTPS body reader wraps a socket timeout in URLError.
            raise URLError(TimeoutError("HTTPS body read timed out"))

    class LateRedirect(Reply):
        def close(self):
            super().close()
            now[0] = 5

    class ExpiringNetwork(Network):
        def request(self, url, *, on_request, **kwargs):
            if url == PEOPLE and phase == "dns":
                now[0] = 5
                raise DeadlineExceeded("DNS deadline exceeded")
            return super().request(url, on_request=on_request, **kwargs)

    def parse(fetched):
        assert phase in ("parse", "parse_signal"), "Parsing started after a failed fetch"
        now[0] = 5
        if phase == "parse_signal":
            raise DeadlineExceeded("Parsing deadline exceeded")
        return parser(fetched)

    monkeypatch.setattr(runner, "parse_html", parse)
    if phase == "http":
        page = ExpiringReply(b"<p>Late body</p>")
    elif phase == "redirect":
        page = LateRedirect(code=302, location=target)
    else:
        page = Reply(b"<p>Profile</p>")
    robots = ExpiringReply(RULES, media="text/plain") if phase == "robots" else RULES
    network = ExpiringNetwork({PEOPLE: page}, robots=robots)
    counts = []
    result = runner.explore(
        make_request(PEOPLE, target), scope=SiteScope(HOST + "/pages/"),
        robots_approved=True, network=network, limits=runner.Limits(deadline=5),
        clock=lambda: now[0], observer=lambda requests, robots: counts.append((requests, robots)),
    )
    assert result.status == "failed" and result.limit_reached
    assert not result.documents
    assert result.attempted_source_ids == attempted
    assert [detail.code for detail in result.errors] == [error]
    expected_status = "parse_failed" if phase.startswith("parse") else "fetch_failed"
    assert [(entry.source_id, entry.status) for entry in result.navigation_history] == [
        ("src_1", expected_status), ("src_2", "skipped"),
    ]
    assert [url for url, _, _ in network.calls] == requests
    assert counts == [(len(requests), 1)]


def test_shared_page_keeps_both_seed_paths_without_a_second_fetch():
    other_seed = HOST + "/pages/group"
    shared_url = HOST + "/pages/about"
    network = Network({
        PEOPLE: Reply(b'<a href="about">About</a>'),
        other_seed: Reply(b'<a href="about">About</a>'),
        shared_url: Reply(b"<p>Lab context</p>"),
    })
    result = run(network, PEOPLE, other_seed)
    paths = [entry for entry in result.navigation_history if entry.url == shared_url]
    assert [(entry.root_source_id, entry.parent_source_id, entry.status) for entry in paths] == [
        ("src_1", "src_1", "success"), ("src_2", "src_2", "skipped"),
    ]
    assert paths[0].source_id == paths[1].source_id == result.documents[-1].source_id
    assert result.attempted_source_ids == ("src_1", "src_2", paths[0].source_id)
    assert [url for url, _, _ in network.calls] == [ROBOTS, PEOPLE, other_seed, shared_url]
