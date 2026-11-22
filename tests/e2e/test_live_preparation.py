"""Offline checks of the optional runner's opt-in and transport restrictions."""

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest


@pytest.fixture
def live():
    spec = importlib.util.spec_from_file_location("dfsa_live_e2e", Path(__file__).with_name("live_pipeline.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def live_transport(live, monkeypatch):
    """Replace DNS and HTTPS only; keep the real LiveHTTP/Response adapters."""
    from email.message import Message

    def install(outcomes, *, failure_at=None):
        pending = iter(outcomes)
        connections = []

        class Connection:
            def __init__(self, host, *, timeout, context):
                self.host = host
                self.closed = 0
                self.response_closed = 0
                self.outcome = next(pending)
                self.stream = io.BytesIO(self.outcome if isinstance(self.outcome, bytes) else b"")
                connections.append(self)

            def request(self, *args, **kwargs):
                if failure_at == "connect":
                    raise self.outcome

            def getresponse(self):
                if failure_at == "headers":
                    raise self.outcome
                if isinstance(self.outcome, live.http.client.HTTPResponse):
                    original_close = self.outcome.close
                    def close():
                        self.response_closed += 1
                        original_close()
                    self.outcome.close = close
                    return self.outcome
                headers = Message()
                headers["Content-Type"] = "text/html; charset=utf-8"
                return SimpleNamespace(status=200, headers=headers, read=self.read, close=self.close_response)

            def read(self, size=-1):
                if isinstance(self.outcome, Exception):
                    raise self.outcome
                if isinstance(self.outcome, list):
                    chunk = self.outcome.pop(0)
                    if isinstance(chunk, Exception):
                        raise chunk
                    return chunk
                return self.stream.read(size)

            def close_response(self):
                self.response_closed += 1

            def close(self):
                self.closed += 1

        monkeypatch.setattr(live.socket, "getaddrinfo", lambda host, port, **kwargs: [
            (live.socket.AF_INET, live.socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))])
        monkeypatch.setattr(live.http.client, "HTTPSConnection", Connection)
        return connections

    return install


@pytest.mark.parametrize("kind", ["timeout", "reset", "incomplete"])
@pytest.mark.parametrize("phase", ["connect", "headers", "body"])
def test_live_transport_converts_external_errors(live, live_transport, kind, phase):
    sensitive = "alice@example.com api_key=synthetic-secret"
    problem = {"timeout": lambda: TimeoutError(sensitive),
               "reset": lambda: ConnectionResetError(sensitive),
               "incomplete": lambda: live.http.client.IncompleteRead(sensitive.encode(), 100)}[kind]()
    connections = live_transport([problem], failure_at=phase)
    with pytest.raises(live.URLError) as caught:
        with live.LiveHTTP("example.com").request(Request("https://example.com/profile"), timeout=10) as response:
            response.read()
    assert isinstance(caught.value.reason, TimeoutError) == (kind == "timeout")
    assert sensitive not in str(caught.value)
    assert caught.value.__suppress_context__
    assert connections[0].closed == 1
    assert connections[0].response_closed == int(phase == "body")


def test_live_transport_normal_body_and_cleanup(live, live_transport):
    connections = live_transport([b"normal body"])
    with live.LiveHTTP("example.com").request(Request("https://example.com/profile"), timeout=10) as response:
        assert response.read(6) == b"normal"
        assert response.read() == b" body"
    assert connections[0].closed == connections[0].response_closed == 1


def test_live_read_internal_error_still_propagates(live, live_transport):
    problem = RuntimeError("synthetic internal bug")
    connections = live_transport([problem])
    with pytest.raises(RuntimeError) as caught:
        with live.LiveHTTP("example.com").request(Request("https://example.com/profile"), timeout=10) as response:
            response.read()
    assert caught.value is problem
    assert connections[0].closed == connections[0].response_closed == 1


def test_live_response_close_always_closes_connection(live):
    problem = RuntimeError("synthetic close bug")
    closed = []
    def close_response():
        raise problem
    response = live.Response(SimpleNamespace(status=200, headers={}, close=close_response),
                             SimpleNamespace(close=lambda: closed.append(True)))
    with pytest.raises(RuntimeError) as caught:
        response.close()
    assert caught.value is problem
    assert closed == [True]


@pytest.mark.parametrize("kind,code", [("timeout", "SEARCH_TIMEOUT"),
                                       ("reset", "SEARCH_NETWORK_ERROR"),
                                       ("incomplete", "SEARCH_NETWORK_ERROR")])
def test_live_read_failure_preserves_real_pipeline_results(
        live, live_transport, pipeline, subject, html_fixture, monkeypatch, capsys, kind, code):
    sensitive = "api_key=synthetic-secret alice@example.com"
    problem = {"timeout": lambda: TimeoutError(sensitive),
               "reset": lambda: ConnectionResetError(sensitive),
               "incomplete": lambda: live.http.client.IncompleteRead(sensitive.encode(), 100)}[kind]()
    search = json.dumps({"search_metadata": {"status": "Success"}, "organic_results": [
        {"link": "https://example.com/profile"}]}).encode()
    connections = live_transport([search, problem, html_fixture("profile").encode()])
    monkeypatch.setenv("DFSA_LIVE_SUBJECT_JSON", subject.model_dump_json())
    assert live.main(["--live", "--site-url", "https://example.com"]) == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == "partial_success"
    assert report["outcome"] == "external_failure"
    assert report["error_codes"] == [code]
    assert report["summary"] == {"search_result_count": 1, "confirmed_source_count": 1,
                                  "total_exposures": 8, "total_risk_paths": 5}
    assert report["search_requests"] == 2 and report["html_requests"] == 1
    assert pipeline.order == ["A", "B", "C"]
    error = pipeline.outputs["A"][0].errors[0]
    assert error.code == code and error.retryable and error.query_id == "q_002"
    assert all(value not in output + error.model_dump_json() for value in
               ("synthetic-secret", "alice@example.com", "Alice Kim"))
    assert all(c.closed == c.response_closed == 1 for c in connections)


@pytest.mark.parametrize("kind,code", [("timeout", "timeout"), ("reset", "network_error"),
                                       ("incomplete", "network_error")])
def test_live_partial_html_read_is_failed_not_success(
        live, live_transport, pipeline, subject, html_fixture, monkeypatch, capsys, kind, code):
    problem = {"timeout": lambda: TimeoutError("synthetic-secret"),
               "reset": lambda: ConnectionResetError("synthetic-secret"),
               "incomplete": lambda: live.http.client.IncompleteRead(b"synthetic-secret", 100)}[kind]()
    search = json.dumps({"search_metadata": {"status": "Success"}, "organic_results": [
        {"link": "https://example.com/profile"}]}).encode()
    # Even a complete-looking profile received before the next read fails must
    # never be parsed/extracted as a successful response.
    connections = live_transport([search, search, [html_fixture("profile").encode(), problem]])
    monkeypatch.setenv("DFSA_LIVE_SUBJECT_JSON", subject.model_dump_json())
    assert live.main(["--live", "--site-url", "https://example.com"]) == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == "failed" and report["error_codes"] == [code]
    assert report["summary"]["total_exposures"] == report["summary"]["total_risk_paths"] == 0
    assert pipeline.order == ["A", "B"]
    assert pipeline.outputs["B"][0].sources[0].processing_status == "fetch_failed"
    assert "synthetic-secret" not in output
    assert all(c.closed == c.response_closed == 1 for c in connections)


def test_live_read_errors_do_not_reset_request_budgets(live, live_transport):
    connections = live_transport([ConnectionResetError("synthetic")] * 5)
    http = live.LiveHTTP("example.com")
    for _ in range(2):
        with pytest.raises(live.URLError):
            http.search(Request("https://serpapi.com/search.json?q=synthetic&api_key=placeholder"), timeout=10)
    with pytest.raises(live.LivePolicyError, match="budget"):
        http.search(Request("https://serpapi.com/search.json?q=synthetic&api_key=placeholder"), timeout=10)
    for _ in range(3):
        with pytest.raises(live.URLError):
            with http.open(Request("https://example.com/profile"), timeout=10) as response:
                response.read()
    with pytest.raises(live.LivePolicyError, match="budget"):
        http.open(Request("https://example.com/profile"), timeout=10)
    assert http.search_count == 2 and http.html_count == 3
    assert len(connections) == 5
    assert all(c.closed == c.response_closed == 1 for c in connections)


def test_live_requires_explicit_opt_in(live, monkeypatch, capsys):
    monkeypatch.setenv("SERPAPI_API_KEY", "placeholder")
    assert live.main([]) == 2
    assert "Live execution disabled" in capsys.readouterr().out


def test_live_requires_environment_configuration(live, monkeypatch, capsys):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("DFSA_LIVE_SUBJECT_JSON", raising=False)
    assert live.main(["--live", "--site-url", "https://example.com"]) == 2
    assert "Invalid live configuration" in capsys.readouterr().out


def test_live_scopes_search_and_filters_other_sites(live, monkeypatch):
    http = live.LiveHTTP("example.com")
    observed = []
    def respond(request, *, timeout):
        observed.append(parse_qs(urlsplit(request.full_url).query))
        return SimpleNamespaceContext({"search_metadata": {"status": "Success"}, "organic_results": [
            {"link": "https://other.example.net/person"},
            {"link": "https://example.com/allowed"},
            {"link": "https://example.com/over-budget"},
        ]})
    monkeypatch.setattr(http, "request", respond)
    request = Request("https://serpapi.com/search.json?q=synthetic&api_key=placeholder")
    for _ in range(2):
        with http.search(request, timeout=20) as response:
            assert json.load(response)["organic_results"] == [{"link": "https://example.com/allowed"}]
    assert all(params["q"] == ["synthetic site:example.com"] and params["num"] == ["1"] for params in observed)
    with pytest.raises(live.LivePolicyError, match="budget"):
        http.search(request, timeout=10)
    assert len(observed) == 2


class SimpleNamespaceContext(io.BytesIO):
    def __init__(self, payload):
        from email.message import Message
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.code = 200
        self.headers = Message()


@pytest.fixture
def wire_response(live):
    """Use the stdlib HTTP parser on bytes, without opening a real socket."""
    def build(body, *, framing="exact"):
        if framing == "exact":
            headers = f"Content-Length: {len(body)}\r\n".encode()
        elif framing == "short":
            headers = f"Content-Length: {len(body) + 100}\r\n".encode()
        elif framing.startswith("chunked"):
            headers = b"Transfer-Encoding: chunked\r\n"
            declared = len(body) + (10 if framing == "chunked-short-data" else 0)
            body = f"{declared:x}\r\n".encode() + body + b"\r\n"
            if framing == "chunked":
                body += b"0\r\n\r\n"
        elif framing == "none":
            headers = b"Connection: close\r\n"
        else:
            raise AssertionError("Unknown test framing")
        stream = io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" + headers + b"\r\n" + body)
        response = live.http.client.HTTPResponse(SimpleNamespace(makefile=lambda *args: stream))
        response.begin()
        return response
    return build


@pytest.mark.parametrize("framing,success", [
    ("exact", True), ("short", False), ("chunked", True),
    ("chunked-no-end", False), ("chunked-short-data", False), ("none", True),
])
def test_live_search_real_http_framing(live, live_transport, wire_response, framing, success):
    body = json.dumps({"search_metadata": {"status": "Success"}, "organic_results": [
        {"link": "https://example.com/profile"}]}).encode()
    raw = wire_response(body, framing=framing)
    connections = live_transport([raw])
    http = live.LiveHTTP("example.com")
    request = Request("https://serpapi.com/search.json?q=synthetic&api_key=placeholder")
    if success:
        with http.search(request, timeout=10) as response:
            assert json.load(response)["organic_results"] == [{"link": "https://example.com/profile"}]
    else:
        with pytest.raises(live.URLError) as caught:
            http.search(request, timeout=10)
        assert "placeholder" not in str(caught.value)
    assert http.search_count == 1
    assert raw.isclosed()
    assert connections[0].closed == connections[0].response_closed == 1


@pytest.mark.parametrize("framing", ["exact", "chunked", "none"])
@pytest.mark.parametrize("extra", [0, 1])
def test_live_search_framed_size_limit(live, live_transport, wire_response, framing, extra):
    prefix = b'{"search_metadata":{"status":"Success"},"organic_results":[]}'
    body = prefix + b" " * (1024 * 1024 + extra - len(prefix))
    connections = live_transport([wire_response(body, framing=framing)])
    http = live.LiveHTTP("example.com")
    request = Request("https://serpapi.com/search.json?q=synthetic&api_key=placeholder")
    if extra:
        with pytest.raises(live.URLError, match="limit"):
            http.search(request, timeout=10)
    else:
        with http.search(request, timeout=10) as response:
            assert json.load(response)["organic_results"] == []
    assert connections[0].closed == connections[0].response_closed == 1


def test_live_truncated_json_preserves_prior_query_and_budget(
        live, live_transport, wire_response, pipeline, subject, html_fixture, monkeypatch, capsys):
    body = json.dumps({"search_metadata": {"status": "Success"}, "organic_results": [
        {"link": "https://example.com/profile"}]}).encode()
    connections = live_transport([wire_response(body), wire_response(body, framing="short"),
                                  html_fixture("profile").encode()])
    monkeypatch.setenv("DFSA_LIVE_SUBJECT_JSON", subject.model_dump_json())
    assert live.main(["--live", "--site-url", "https://example.com"]) == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == "partial_success"
    assert report["error_codes"] == ["SEARCH_NETWORK_ERROR"]
    assert report["search_requests"] == 2 and report["html_requests"] == 1
    assert pipeline.outputs["A"][0].queries[1].status == "failed"
    assert len(pipeline.outputs["A"][0].results) == 1
    assert report["summary"]["total_exposures"] == 8
    assert all(value not in output for value in ("alice@example.com", "Alice Kim", "offline-placeholder"))
    assert all(c.closed == c.response_closed == 1 for c in connections)


def test_live_truncation_does_not_allow_extra_search_requests(live, live_transport, wire_response):
    body = b'{"search_metadata":{"status":"Success"},"organic_results":[]}'
    connections = live_transport([wire_response(body, framing="short") for _ in range(2)])
    http = live.LiveHTTP("example.com")
    request = Request("https://serpapi.com/search.json?q=synthetic&api_key=placeholder")
    for _ in range(2):
        with pytest.raises(live.URLError):
            http.search(request, timeout=10)
    with pytest.raises(live.LivePolicyError, match="budget"):
        http.search(request, timeout=10)
    assert http.search_count == 2 and len(connections) == 2
    assert all(c.closed == c.response_closed == 1 for c in connections)


def test_live_html_limits_and_cross_site_redirect(live, monkeypatch):
    http = live.LiveHTTP("example.com")
    calls = []
    monkeypatch.setattr(http, "request", lambda request, **kwargs: calls.append(request.full_url))
    for _ in range(3):
        http.open(Request("https://example.com/allowed"), timeout=10)
    with pytest.raises(live.LivePolicyError, match="budget"):
        http.open(Request("https://example.com/over-budget"), timeout=10)
    with pytest.raises(live.LivePolicyError, match="approved site"):
        http.open(Request("https://other.example.net/redirect"), timeout=10)
    assert len(calls) == 3


@pytest.mark.parametrize("url", ["http://example.com", "https://localhost", "https://127.0.0.1", "https://10.0.0.1"])
def test_live_transport_blocks_nonpublic_urls(live, url):
    with pytest.raises(live.LivePolicyError):
        live.LiveHTTP(urlsplit(url).hostname).request(Request(url), timeout=10)


def test_live_pins_validated_dns_and_preserves_tls_host(live, monkeypatch):
    calls = []
    def dns(host, port, **kwargs):
        return [(live.socket.AF_INET, live.socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
    monkeypatch.setattr(live.socket, "getaddrinfo", dns)
    monkeypatch.setattr(live.socket, "create_connection", lambda destination, *args: calls.append(destination))

    class Connection:
        def __init__(self, host, *, timeout, context):
            assert host == "example.com"
            assert context.check_hostname and context.verify_mode == live.ssl.CERT_REQUIRED
            self.timeout = timeout
        def request(self, method, target, *, headers):
            assert method == "GET" and target == "/allowed"
            self._create_connection(("example.com", 443), self.timeout)
        def getresponse(self):
            return SimpleNamespace(status=200, headers={}, read=lambda size: b"ok", close=lambda: None)
        def close(self):
            pass

    monkeypatch.setattr(live.http.client, "HTTPSConnection", Connection)
    with live.LiveHTTP("example.com").request(Request("https://example.com/allowed"), timeout=10) as response:
        assert response.read() == b"ok"
    assert calls == [("93.184.216.34", 443)]


def test_live_rejects_mixed_private_dns_before_connection(live, monkeypatch):
    monkeypatch.setattr(live.socket, "getaddrinfo", lambda host, port, **kwargs: [
        (live.socket.AF_INET, live.socket.SOCK_STREAM, 6, "", (address, port))
        for address in ("93.184.216.34", "10.0.0.1")])
    with pytest.raises(live.LivePolicyError):
        live.LiveHTTP("example.com").request(Request("https://example.com"), timeout=10)


@pytest.mark.parametrize("outcome", ["zero", "failure"])
def test_live_distinguishes_empty_results_and_external_failure(
        live, pipeline, happy, subject, monkeypatch, capsys, outcome):
    monkeypatch.setenv("DFSA_LIVE_SUBJECT_JSON", subject.model_dump_json())
    happy.results = []
    if outcome == "failure":
        happy.query_outcomes = {'"Alice Kim" "Example University"': TimeoutError(),
                                '"alice@example.com"': TimeoutError()}
    monkeypatch.setattr(live.LiveHTTP, "search", lambda self, *args, **kwargs: happy.search(*args, **kwargs))
    assert live.main(["--live", "--site-url", "https://example.com"]) == (1 if outcome == "failure" else 0)
    report = json.loads(capsys.readouterr().out)
    assert report["outcome"] == ("external_failure" if outcome == "failure" else "no_search_results")
    assert report["error_codes"] == (["SEARCH_TIMEOUT", "SEARCH_TIMEOUT"] if outcome == "failure" else [])
    assert pipeline.order == ["A"]


def test_live_summary_contains_no_subject_key_or_documents(live, pipeline, happy, subject, monkeypatch, capsys):
    # The runner still calls the real modules; its transports are offline here.
    monkeypatch.setenv("DFSA_LIVE_SUBJECT_JSON", subject.model_dump_json())
    monkeypatch.setattr(live.LiveHTTP, "search", lambda self, *args, **kwargs: happy.search(*args, **kwargs))
    monkeypatch.setattr(live.LiveHTTP, "open", lambda self, *args, **kwargs: happy.open(*args, **kwargs))
    assert live.main(["--live", "--site-url", "https://example.com"]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == "success" and report["summary"]["total_exposures"] == 8
    assert all(value not in output for value in ("alice@example.com", "Alice Kim", "offline-placeholder", "Professor Example"))
