"""Offline checks for the approved v0.2 Live Runner."""

import io
import json
import logging
import socket
from email.message import Message
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest

import live_v02
import live_v02_transport
from dfsa.contracts import ErrorDetail
from dfsa.service import orchestrator

APPROVALS = ("--live", "--consent-confirmed", "--scope-approved")
SITE = "https://lab.example.org/people/"


@pytest.fixture
def configure(monkeypatch, v02_fixtures):
    monkeypatch.setenv("DFSA_V02_LIVE_SUBJECT_JSON", v02_fixtures["SUBJECT"].model_dump_json())
    imports = []
    inputs = []
    handlers = v02_fixtures["mock_handlers"]()

    def load(path):
        stage = next(stage for stage, module in live_v02.MODULES.items() if module == path)
        imports.append(stage)

        def run(request):
            inputs.append(request)
            response = handlers[f"run_{stage}"](request)
            return response

        if f"run_{stage}" not in handlers:
            raise ModuleNotFoundError(name=path)
        return SimpleNamespace(**{f"run_{stage}": run})

    monkeypatch.setattr(live_v02, "import_module", load)
    return imports, inputs, handlers


def invoke(until, capsys, *, site=SITE):
    code = live_v02.main([*APPROVALS, "--site-url", site, "--until", until])
    output = capsys.readouterr()
    assert not output.err
    return code, json.loads(output.out)


@pytest.mark.parametrize("omitted", APPROVALS)
def test_each_approval_is_required_before_config_or_import(omitted, monkeypatch, capsys):
    monkeypatch.delenv("DFSA_V02_LIVE_SUBJECT_JSON", raising=False)
    monkeypatch.setattr(live_v02, "import_module", lambda *args: pytest.fail("Module imported"))
    assert live_v02.main(["--until", "search", *(flag for flag in APPROVALS if flag != omitted)]) == 2
    assert "requires --live" in capsys.readouterr().out


@pytest.mark.parametrize("until", live_v02.STAGES)
def test_selected_prefix_passes_real_outputs_through_orchestrator(until, configure, capsys, v02_fixtures):
    imports, inputs, _ = configure
    original_callables = [getattr(orchestrator, f"run_{stage}") for stage in live_v02.STAGES]
    code, report = invoke(until, capsys)
    assert code == 0
    expected = live_v02.STAGES[:live_v02.STAGES.index(until) + 1]
    assert imports == list(expected)
    assert [getattr(orchestrator, f"run_{stage}") for stage in live_v02.STAGES] == original_callables
    assert {request.request_id for request in inputs} == {inputs[0].request_id}
    search, exploration, profiling, _ = v02_fixtures["stage_responses"](inputs[0].request_id)
    for request, field, expected_payload in zip(
        inputs[1:], ("search_results", "documents", "exposures"),
        (search.results, exploration.documents, profiling.exposures),
    ):
        assert getattr(request, field) == expected_payload
    assert report["outcome"] == ("completed" if until == "analysis" else "reached_requested_stage")
    assert report["pipeline_status"] == ("success" if until == "analysis" else None)
    for stage in expected:
        assert report["stages"][stage]["status"] == "success"
        assert report["stages"][stage]["elapsed_ms"] >= 0
        assert report["stages"][stage]["output"]
    for stage in live_v02.STAGES[len(expected):]:
        assert report["stages"][stage] == {"status": "out_of_scope", "elapsed_ms": None}


def test_missing_module_only_blocks_when_needed(configure, capsys):
    imports, _, handlers = configure
    del handlers["run_exploration"]
    code, report = invoke("analysis", capsys)
    assert code == 2
    assert imports == ["search", "exploration"]
    assert report["outcome"] == "not_connected"
    assert report["stage"] == "exploration"
    assert report["expected_callable"] == "dfsa.modules.explorer.runner.run_exploration"
    assert report["stages"]["search"]["status"] == "success"
    assert report["stages"]["profiling"]["status"] == "not_started"


@pytest.mark.parametrize("case,outcome,exit_code", [
    ("zero", "no_input_for_next_stage", 0), ("failed", "failed", 1),
])
def test_orchestrator_still_handles_zero_and_failed_search(
    case, outcome, exit_code, configure, capsys, v02_fixtures,
):
    imports, _, handlers = configure
    handlers.update(v02_fixtures["mock_handlers"](case))
    code, report = invoke("analysis", capsys)
    assert code == exit_code
    assert imports == ["search"]
    assert report["outcome"] == outcome
    assert report["stages"]["exploration"]["status"] == "not_started"


def test_cutoff_keeps_cross_stage_validation(configure, capsys, v02_fixtures):
    imports, _, handlers = configure

    def wrong_scope(request):
        response = v02_fixtures["stage_responses"](request.request_id)[1]
        entry = response.navigation_history[0].model_copy(update={"root_source_id": "src_unrelated"})
        return response.model_copy(update={"navigation_history": [entry]})

    handlers["run_exploration"] = wrong_scope
    code, report = invoke("exploration", capsys)
    assert code == 1
    assert imports == ["search", "exploration"]
    assert report["stages"]["search"]["status"] == "success"
    assert report["stages"]["exploration"]["status"] == "invalid_response"
    assert "src_unrelated" not in json.dumps(report)


def test_output_never_echoes_sensitive_data(configure, capsys, v02_fixtures):
    _, _, handlers = configure
    private = "fake-key private-person@example.org <p>Private HTML</p>"

    def analysis(request):
        print(private, flush=True)
        logging.warning(private)
        response = v02_fixtures["stage_responses"](request.request_id)[3]
        return response.model_copy(update={
            "status": "partial_success", "errors": [
                ErrorDetail(code=private, message=private, retryable=False),
            ],
        })

    handlers["run_analysis"] = analysis
    code, report = invoke("analysis", capsys)
    assert code == 1
    assert report["stages"]["analysis"]["errors"] == [{"code": "MODULE_ERROR", "retryable": False}]
    output = json.dumps(report)
    assert all(secret not in output for secret in (private, "Sample Researcher", "Sample Researcher Example University"))


def test_out_of_scope_search_output_does_not_reach_explorer(configure, capsys, v02_fixtures):
    imports, _, handlers = configure

    def search(request):
        response = v02_fixtures["stage_responses"](request.request_id)[0]
        result = response.results[0].model_copy(update={"url": "https://unapproved.example.org/profile"})
        return response.model_copy(update={"results": [result]})

    handlers["run_search"] = search
    code, report = invoke("analysis", capsys)
    assert code == 1
    assert imports == ["search"]
    assert report["outcome"] == "policy_blocked"


@pytest.mark.parametrize("url", [
    "http://lab.example.org/people/a", "https://lab.example.org.evil.example/people/a",
    "https://lab.example.org/people-elsewhere/a", "https://lab.example.org/people/%2e%2E/outside",
    "https://lab.example.org/people/a%2Fb", "https://lab.example.org/people/%252e%252e/outside",
])
def test_redirect_scope_is_checked_before_transport(url, monkeypatch):
    transport = live_v02_transport.LiveTransport(live_v02_transport.SiteScope(SITE))
    transport.stage = "exploration"
    monkeypatch.setattr(transport, "_request", lambda *args: pytest.fail("HTTP attempted"))
    with pytest.raises(live_v02_transport.LivePolicyError):
        transport.open(Request(url), timeout=3)
    assert transport.html_requests == 0


def test_host_pinning_uses_checked_dns_preserving_tls_hostname(monkeypatch):
    transport = live_v02_transport.LiveTransport(live_v02_transport.SiteScope(SITE))
    transport.stage = "exploration"
    addresses = []
    tls_hosts = []
    monkeypatch.setattr(transport, "_resolve", lambda host, port, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
    ])
    monkeypatch.setattr(transport, "_connect", lambda proxy_socket, address: addresses.append(address))

    class Connection:
        def __init__(self, host, *, timeout, context):
            tls_hosts.append(host)
            self.sock = None

        def request(self, method, path, *, headers):
            assert method == "GET" and path == "/people/profile"
            self.sock = self._create_connection(("lab.example.org", 443), 3)

        def getresponse(self):
            return SimpleNamespace(status=200, headers=Message(), read=lambda size: b"", close=lambda: None)

        def close(self):
            if self.sock is not None:
                self.sock.close()

    monkeypatch.setattr(live_v02_transport.http.client, "HTTPSConnection", Connection)
    with transport.install():
        with transport.open(Request("https://lab.example.org/people/profile"), timeout=3):
            with pytest.raises(live_v02_transport.LivePolicyError):
                socket.create_connection(("unapproved.example.org", 443))
    assert tls_hosts == ["lab.example.org"]
    assert addresses == [("93.184.216.34", 443)]


def test_search_scope_is_applied_before_request_and_results_are_filtered(monkeypatch):
    transport = live_v02_transport.LiveTransport(live_v02_transport.SiteScope(SITE))
    transport.stage = "search"
    responses = [
        "https://lab.example.org/people/a", "https://lab.example.org/other",
        "https://unapproved.example.org/people/a",
    ]
    body = io.BytesIO(json.dumps({"organic_results": [{"link": url} for url in responses]}).encode())
    body.code = 200
    body.headers = Message()

    def request(url, timeout, limit, headers):
        parts = urlsplit(url)
        assert parts.hostname == "serpapi.com"
        assert parse_qs(parts.query)["q"] == ["synthetic name site:lab.example.org"]
        return body

    monkeypatch.setattr(transport, "_request", request)
    request = Request("https://serpapi.com/search.json?q=synthetic+name")
    with transport.search(request, timeout=3) as payload:
        assert json.load(payload)["organic_results"] == [{"link": responses[0]}]
    with pytest.raises(live_v02_transport.LivePolicyError, match="budget"):
        transport.search(request, timeout=3)


def test_argument_errors_do_not_echo_raw_arguments(capsys):
    with pytest.raises(SystemExit, match="2"):
        live_v02.main(["--until", "secret=value"])
    assert "secret=value" not in capsys.readouterr().err


def test_private_dns_fails_before_https_connection(monkeypatch):
    transport = live_v02_transport.LiveTransport(live_v02_transport.SiteScope(SITE))
    transport.stage = "exploration"
    monkeypatch.setattr(transport, "_resolve", lambda host, port, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
    ])
    monkeypatch.setattr(live_v02_transport.http.client, "HTTPSConnection",
                        lambda *args, **kwargs: pytest.fail("HTTPS connection created"))
    with pytest.raises(live_v02_transport.LivePolicyError, match="DNS"):
        transport.open(Request("https://lab.example.org/people/profile"), timeout=3)


def test_scope_can_allow_one_page_and_blocks_network_in_profiling():
    scope = live_v02_transport.SiteScope("https://lab.example.org/people/profile")
    assert scope.contains("https://lab.example.org/people/profile")
    assert not scope.contains("https://lab.example.org/people/profile/related")
    transport = live_v02_transport.LiveTransport(scope)
    transport.stage = "profiling"
    request = Request("https://lab.example.org/people/profile")
    with transport.install(), pytest.raises(live_v02_transport.LivePolicyError):
        transport.open(request, timeout=3)
