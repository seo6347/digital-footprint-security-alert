"""Real A -> real B -> real C, driven exclusively by offline HTTP payloads."""

import json
import socket
import urllib.request
from urllib.error import URLError

import pytest
from pydantic import ValidationError

from dfsa._v01.contracts import DFSAResult, Subject
from dfsa._v01 import orchestrator


EVALUATION_FIELDS = {"searchability", "cross_source_linkability", "attack_utility",
                     "sensitivity", "evidence_confidence"}
CATEGORIES = {"R01": "authority_impersonation", "R02": "academic_impersonation",
              "R03": "recruitment_impersonation", "R04": "event_impersonation",
              "R05": "account_impersonation"}
USED_TYPES = {"R01": {"relationship", "affiliation", "contact"},
              "R02": {"affiliation", "interest", "activity", "contact"},
              "R03": {"activity", "interest", "account", "contact"},
              "R04": {"temporal", "affiliation", "activity", "contact"},
              "R05": {"account", "contact", "identity"}}


def assert_summary(result, search, confirmed, exposures, paths):
    assert result.summary.model_dump() == {
        "search_result_count": search, "confirmed_source_count": confirmed,
        "total_exposures": exposures, "total_risk_paths": paths,
    }


def assert_contract(result):
    payload = json.loads(result.model_dump_json())
    assert set(payload) == {"schema_version", "request_id", "status", "subject", "stages",
                            "sources", "exposures", "risk_paths", "summary", "errors"}
    assert payload["schema_version"] == "v0.1"
    assert DFSAResult.model_validate(payload) == result
    assert DFSAResult.model_validate_json(result.model_dump_json()) == result
    for key in ("sources", "exposures", "risk_paths", "errors"):
        assert isinstance(payload[key], list)


def assert_links(result, pipeline):
    a = pipeline.outputs["A"][-1]
    b = pipeline.outputs["B"][-1]
    c = pipeline.outputs["C"][-1]
    assert pipeline.order == ["A", "B", "C"]
    for stage in ("A", "B", "C"):
        assert pipeline.inputs[stage][-1].request_id == result.request_id
        assert pipeline.outputs[stage][-1].request_id == result.request_id
        assert pipeline.outputs[stage][-1].schema_version == result.schema_version
    assert pipeline.inputs["B"][-1].search_results == a.results
    assert [s.source_id for s in result.sources] == [s.source_id for s in a.results]
    assert pipeline.inputs["C"][-1].exposures == b.exposures == result.exposures
    assert result.sources == b.sources
    assert result.risk_paths == c.risk_paths  # Includes untouched reason/recommendations.
    assert c.summary.total_exposures == len(result.exposures)
    assert c.summary.total_paths == len(result.risk_paths)
    source_ids = {source.source_id for source in result.sources if source.identity_status == "confirmed"}
    exposures = {exposure.exposure_id: exposure for exposure in result.exposures}
    assert len(exposures) == len(result.exposures)
    assert len({path.risk_path_id for path in result.risk_paths}) == len(result.risk_paths)
    for exposure in result.exposures:
        assert exposure.sources
        assert {ref.source_id for ref in exposure.sources} <= source_ids
        assert all(ref.evidence.strip() for ref in exposure.sources)
    for path in result.risk_paths:
        assert path.exposure_ids
        assert set(path.exposure_ids) <= exposures.keys()
        assert path.category == CATEGORIES[path.rule_id]
        assert path.exposure_ids == [e.exposure_id for e in result.exposures
                                     if e.type in USED_TYPES[path.rule_id]]
        assert set(path.evaluation.model_dump()) == EVALUATION_FIELDS
        assert all(value in {"YES", "NO", "UNKNOWN", "NOT_APPLICABLE"}
                   for value in path.evaluation.model_dump().values())
        assert path.reason.strip() and all(r.strip() for r in path.recommendations)


def test_e2e_01_full_pipeline(pipeline, happy, subject):
    result = orchestrator.run_pipeline(subject)
    assert result.status == "success"
    assert set(result.stages.model_dump().values()) == {"success"}
    assert result.errors == []
    assert {e.type for e in result.exposures} == {
        "identity", "contact", "affiliation", "relationship", "activity", "interest", "account", "temporal",
    }
    assert {p.rule_id for p in result.risk_paths} == set(CATEGORIES)
    assert_summary(result, 1, 1, 8, 5)
    assert_links(result, pipeline)
    assert_contract(result)
    assert len(happy.search_calls) == 2
    assert happy.html_calls == ["https://example.com/alice"]
    # Exact original HTML, never search snippets, supplies every quote.
    for exposure in result.exposures:
        assert all(ref.evidence in happy.pages["https://example.com/alice"] for ref in exposure.sources)


@pytest.mark.parametrize("payload", [
    {"search_metadata": {"status": "Success"}, "organic_results": []},
    {"search_metadata": {"status": "Success"}, "search_information": {"total_results": 0}},
], ids=["empty-array", "explicit-zero"])
def test_e2e_02_search_zero(pipeline, offline, subject, payload):
    offline.query_outcomes = {'"Alice Kim" "Example University"': payload, '"alice@example.com"': payload}
    result = orchestrator.run_pipeline(subject)
    assert pipeline.order == ["A"]
    assert pipeline.inputs["B"] == pipeline.inputs["C"] == []
    assert len(offline.search_calls) == 2
    assert offline.html_calls == offline.dns_calls == []
    assert result.status == "success"
    assert result.stages.model_dump() == {"search": "success", "profiling": "not_started", "risk_analysis": "not_started"}
    assert result.sources == result.exposures == result.risk_paths == result.errors == []
    assert_summary(result, 0, 0, 0, 0)
    assert_contract(result)


@pytest.mark.parametrize("failure,code", [
    (TimeoutError("synthetic timeout"), "SEARCH_TIMEOUT"),
    (URLError("synthetic unavailable"), "SEARCH_NETWORK_ERROR"),
    ({"error": "synthetic provider failure"}, "SEARCH_API_ERROR"),
    (b"not-json", "SEARCH_INVALID_RESPONSE"),
])
def test_e2e_03_search_failed(pipeline, offline, subject, failure, code):
    offline.query_outcomes = {'"Alice Kim" "Example University"': failure, '"alice@example.com"': failure}
    result = orchestrator.run_pipeline(subject)
    assert pipeline.order == ["A"]
    assert pipeline.outputs["A"][0].status == result.status == "failed"
    assert result.errors == pipeline.outputs["A"][0].errors
    assert [e.code for e in result.errors] == [code, code]
    assert [e.query_id for e in result.errors] == ["q_001", "q_002"]
    assert result.stages.profiling == result.stages.risk_analysis == "not_started"
    assert offline.html_calls == []
    assert_summary(result, 0, 0, 0, 0)
    assert_contract(result)


@pytest.mark.parametrize("failed_query,query_id", [
    ('"Alice Kim" "Example University"', "q_001"), ('"alice@example.com"', "q_002"),
])
def test_e2e_04_search_partial(pipeline, happy, subject, failed_query, query_id):
    happy.query_outcomes[failed_query] = TimeoutError()
    result = orchestrator.run_pipeline(subject)
    assert result.status == result.stages.search == "partial_success"
    assert result.stages.profiling == result.stages.risk_analysis == "success"
    assert result.errors == pipeline.outputs["A"][0].errors
    assert len(result.errors) == 1
    assert result.errors[0].code == "SEARCH_TIMEOUT"
    assert result.errors[0].query_id == query_id
    assert_summary(result, 1, 1, 8, 5)
    assert_links(result, pipeline)


@pytest.mark.parametrize("page,identity,confirmed", [
    ("fragmented", "confirmed", 1), ("empty", "uncertain", 0),
    ("uncertain", "uncertain", 0), ("other", "rejected", 0),
])
def test_e2e_05_profiling_zero(pipeline, happy, subject, html_fixture, page, identity, confirmed):
    happy.pages["https://example.com/alice"] = html_fixture(page)
    result = orchestrator.run_pipeline(subject)
    assert pipeline.order == ["A", "B"]
    assert pipeline.inputs["C"] == []
    assert result.status == result.stages.profiling == "success"
    assert result.stages.risk_analysis == "not_started"
    assert result.sources[0].identity_status == identity
    assert result.exposures == result.risk_paths == result.errors == []
    assert_summary(result, 1, confirmed, 0, 0)
    assert_contract(result)


@pytest.mark.parametrize("failure,processing,code", [
    (TimeoutError(), "fetch_failed", "timeout"),
    (b"\xff", "parse_failed", "decode_error"),
    ({"body": b"%PDF-synthetic", "content_type": "application/pdf"}, "unsupported", "unsupported_content_type"),
])
def test_e2e_06_profiling_partial(pipeline, happy, subject, item, failure, processing, code):
    happy.results.append(item("/broken", position=2))
    happy.pages["https://example.com/broken"] = failure
    result = orchestrator.run_pipeline(subject)
    assert result.status == result.stages.profiling == "partial_success"
    assert result.stages.search == result.stages.risk_analysis == "success"
    assert result.sources[0].identity_status == "confirmed"
    assert result.sources[1].processing_status == processing
    assert result.sources[1].identity_status is None
    assert result.errors == pipeline.outputs["B"][0].errors
    assert len(result.errors) == 1
    assert result.errors[0].code == code and result.errors[0].source_id == "src_002"
    assert_summary(result, 2, 1, 8, 5)
    assert_links(result, pipeline)


def test_e2e_07_profiling_failed(pipeline, offline, subject, item):
    offline.results = [item("/timeout"), item("/decode", position=2)]
    offline.pages = {"https://example.com/timeout": TimeoutError(), "https://example.com/decode": b"\xff"}
    result = orchestrator.run_pipeline(subject)
    assert pipeline.order == ["A", "B"]
    assert pipeline.inputs["C"] == []
    assert result.status == result.stages.profiling == "failed"
    assert result.stages.risk_analysis == "not_started"
    assert [s.processing_status for s in result.sources] == ["fetch_failed", "parse_failed"]
    assert [e.code for e in result.errors] == ["timeout", "decode_error"]
    assert result.errors == pipeline.outputs["B"][0].errors
    assert result.exposures == result.risk_paths == []
    assert_summary(result, 2, 0, 0, 0)
    assert_contract(result)


def test_e2e_08_other_people_excluded(pipeline, happy, subject, item, html_fixture):
    # Both a separate other profile and a sibling card on the target page.
    happy.pages["https://example.com/alice"] += html_fixture("other")
    happy.results.extend([
        item("/other", title="Bob Lee", snippet="bob@example.net", position=2),
        item("/uncertain", title="Alice Kim", snippet="Unverified", position=3),
        item("/unrelated", title="Weather", snippet="Public weather", position=4),
    ])
    for name, fixture in (("other", "other"), ("uncertain", "uncertain"), ("unrelated", "empty")):
        happy.pages[f"https://example.com/{name}"] = html_fixture(fixture)
    result = orchestrator.run_pipeline(subject)
    assert result.status == "success"
    assert [s.identity_status for s in result.sources] == ["confirmed", "rejected", "uncertain", "uncertain"]
    assert [s.relevance.status for s in pipeline.outputs["A"][0].results] == ["candidate", "uncertain", "uncertain", "uncertain"]
    assert {ref.source_id for e in result.exposures for ref in e.sources} == {"src_001"}
    content = " ".join(e.value + " " + " ".join(s.evidence for s in e.sources) for e in result.exposures)
    for forbidden in ("Bob Lee", "bob@example.net", "Professor Other", "dfsa-synthetic-bob", "Professor Unverified"):
        assert forbidden not in content
    assert_summary(result, 4, 1, 8, 5)
    assert_links(result, pipeline)


def test_e2e_09_duplicate_exposures_preserve_sources(pipeline, happy, subject, item, html_fixture):
    happy.results.extend([item("/alice?utm_source=synthetic#bio", position=2), item("/mirror", position=3)])
    happy.pages["https://example.com/mirror"] = html_fixture("mirror")
    result = orchestrator.run_pipeline(subject)
    a = pipeline.outputs["A"][0]
    assert len(a.results) == 2
    assert len(a.results[0].discovered_by) == 2
    assert {d.query_id for d in a.results[0].discovered_by} == {"q_001", "q_002"}
    assert happy.html_calls == ["https://example.com/alice", "https://example.com/mirror"]
    contacts = [e for e in result.exposures if e.type == "contact"]
    assert len(contacts) == 1 and contacts[0].value == "alice@example.com"
    assert {(s.source_id, s.evidence) for s in contacts[0].sources} == {
        ("src_001", "Email: alice@example.com"), ("src_002", "E-mail: alice@example.com"),
    }
    assert_summary(result, 2, 2, 8, 5)
    assert_links(result, pipeline)


@pytest.mark.parametrize("rule,fields,status", [
    ("R01", '<p>Advisor: Professor Example</p>', "supported"),
    ("R01", '<p>Collaborator: Professor Example</p>', "candidate"),
    ("R02", '<p>Organization: Example University</p><p>Research interests: Privacy</p>', "candidate"),
    ("R03", '<p>Activity: Synthetic Project</p><p>Research interests: Privacy</p>', "candidate"),
    ("R04", '<p>Project period: 2025-2026</p>', "candidate"),
    ("R05", '<p>GitHub: <a href="https://github.com/dfsa-synthetic-alice">dfsa-synthetic-alice</a></p>', "candidate"),
])
def test_e2e_10_individual_rules(pipeline, happy, subject, card, rule, fields, status):
    happy.pages["https://example.com/alice"] = card(fields)
    result = orchestrator.run_pipeline(subject)
    assert result.status == "success"
    assert len(result.risk_paths) == 1
    path = result.risk_paths[0]
    assert path.rule_id == rule and path.path_status == status
    assert path.evaluation.model_dump() == {
        "searchability": "YES", "cross_source_linkability": "UNKNOWN",
        "attack_utility": "YES", "sensitivity": "YES",
        "evidence_confidence": "YES" if status == "supported" else "UNKNOWN",
    }
    assert_links(result, pipeline)


def test_e2e_10_missing_triggers_generate_no_paths(pipeline, happy, subject, card):
    happy.pages["https://example.com/alice"] = card()
    result = orchestrator.run_pipeline(subject)
    assert {e.type for e in result.exposures} == {"identity", "contact"}
    assert result.risk_paths == []
    assert result.stages.risk_analysis == "success"  # C ran; no triggers is not a skipped stage.
    assert_links(result, pipeline)


def test_e2e_11_ids_across_real_stage_boundaries(pipeline, happy, subject):
    result = orchestrator.run_pipeline(subject)
    assert_links(result, pipeline)
    assert result.request_id.startswith("req_")
    assert [s.source_id for s in result.sources] == ["src_001"]
    assert [e.exposure_id for e in result.exposures] == [f"exp_{i:03}" for i in range(1, 9)]
    assert [p.risk_path_id for p in result.risk_paths] == [f"path_{i:03}" for i in range(1, 6)]


@pytest.mark.parametrize("mutation", ["extra", "missing-evaluation", "missing-summary", "missing-stage"])
def test_e2e_12_public_contract_roundtrip_and_rejection(pipeline, happy, subject, mutation):
    result = orchestrator.run_pipeline(subject)
    assert_contract(result)
    payload = json.loads(result.model_dump_json())
    if mutation == "extra":
        payload["exposures"][0]["exposureId"] = "invalid-field"
    elif mutation == "missing-evaluation":
        del payload["risk_paths"][0]["evaluation"]["sensitivity"]
    elif mutation == "missing-summary":
        del payload["summary"]
    else:
        del payload["stages"]["profiling"]
    with pytest.raises(ValidationError):
        DFSAResult.model_validate_json(json.dumps(payload))


def test_e2e_13_subject_and_consecutive_requests_isolated(pipeline, happy, subject, card, item):
    before = subject.model_copy(deep=True)
    first = orchestrator.run_pipeline(subject)
    first_json = first.model_dump_json()
    other = Subject(name="Bob Lee", organization="Other University", email="bob@example.net")
    other_before = other.model_copy(deep=True)
    happy.results = [item("/bob", title="Bob Lee — Other University", snippet="bob@example.net")]
    happy.pages["https://example.com/bob"] = card('<p>Activity: Bob Synthetic Project</p>', name=other.name,
                                                 email=str(other.email), organization=other.organization)
    second = orchestrator.run_pipeline(other)
    assert subject == before and other == other_before
    assert first.request_id != second.request_id
    assert {e.value for e in first.exposures}.isdisjoint({e.value for e in second.exposures})
    assert all("Alice" not in ref.evidence and "alice@example.com" not in ref.evidence
               for e in second.exposures for ref in e.sources)
    assert first.model_dump_json() == first_json
    # A third empty request must not inherit the preceding populated responses.
    happy.results = []
    third = orchestrator.run_pipeline(subject)
    assert len({first.request_id, second.request_id, third.request_id}) == 3
    assert third.sources == third.exposures == third.risk_paths == []
    assert pipeline.order == ["A", "B", "C", "A", "B", "C", "A"]
    assert_summary(third, 0, 0, 0, 0)


@pytest.mark.parametrize("stage,order", [("A", ["A"]), ("B", ["A", "B"])])
def test_e2e_14_unexpected_exception_propagates(pipeline, happy, subject, stage, order):
    # Unexpected adapter bugs propagate through real public functions. No
    # business function is replaced merely to synthesize an internal failure.
    problem = RuntimeError("synthetic unexpected transport bug")
    if stage == "A":
        happy.query_outcomes['"Alice Kim" "Example University"'] = problem
    else:
        happy.pages["https://example.com/alice"] = problem
    with pytest.raises(RuntimeError) as caught:
        orchestrator.run_pipeline(subject)
    assert caught.value is problem
    assert pipeline.order == order
    assert pipeline.outputs[stage] == []
    assert pipeline.inputs["C"] == []


def test_e2e_15_socket_dns_http_fail_closed(deny_network):
    operations = [lambda: socket.getaddrinfo("example.com", 443),
                  lambda: socket.gethostbyname("example.com"),
                  lambda: socket.create_connection(("93.184.216.34", 443)),
                  lambda: urllib.request.urlopen("https://example.com"),
                  lambda: urllib.request.build_opener().open("https://example.com")]
    for operation in operations:
        with pytest.raises(pytest.fail.Exception, match="Real network access is forbidden"):
            operation()
    with socket.socket() as client:
        for operation in (client.connect, client.connect_ex):
            with pytest.raises(pytest.fail.Exception, match="Real network access is forbidden"):
                operation(("93.184.216.34", 443))


def test_e2e_15_unknown_routes_fail_closed(pipeline, offline, subject, item):
    offline.results = [item("/unregistered")]
    with pytest.raises(pytest.fail.Exception, match="Unexpected DNS lookup"):
        orchestrator.run_pipeline(subject)
    assert offline.html_calls == []


def test_e2e_15_missing_api_key_is_explicit_failure(pipeline, happy, subject, monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    result = orchestrator.run_pipeline(subject)
    assert result.status == "failed"
    assert pipeline.order == ["A"]
    assert happy.search_calls == happy.html_calls == []
    assert {e.code for e in result.errors} == {"SEARCH_API_KEY_MISSING"}


@pytest.mark.parametrize("target", ["http://127.0.0.1/private", "http://localhost/private", "http://10.0.0.1/private"])
def test_e2e_15_redirect_cannot_reach_private_network(pipeline, happy, subject, target):
    happy.pages["https://example.com/alice"] = {"body": b"", "code": 302, "location": target}
    result = orchestrator.run_pipeline(subject)
    assert result.status == "failed"
    assert pipeline.order == ["A", "B"]
    assert happy.html_calls == ["https://example.com/alice"]
    assert {e.code for e in result.errors} == {"blocked_url"}
    assert result.sources[0].processing_status == "rejected"


def test_e2e_15_private_dns_answer_blocks_before_http(pipeline, happy, subject):
    happy.dns_answers["example.com"] = ["93.184.216.34", "10.0.0.1"]
    result = orchestrator.run_pipeline(subject)
    assert result.status == "failed"
    assert {e.code for e in result.errors} == {"blocked_url"}
    assert happy.html_calls == []


def test_public_redirect_preserves_original_source(pipeline, happy, subject, html_fixture):
    happy.pages["https://example.com/alice"] = {"body": b"", "code": 302, "location": "/final"}
    happy.pages["https://example.com/final"] = html_fixture("profile")
    result = orchestrator.run_pipeline(subject)
    assert result.sources[0].url == "https://example.com/alice"
    assert happy.html_calls == ["https://example.com/alice", "https://example.com/final"]
    assert result.status == "success"
    assert_links(result, pipeline)


def test_search_and_profiling_errors_keep_stage_order(pipeline, happy, subject, item):
    happy.query_outcomes['"alice@example.com"'] = TimeoutError()
    happy.results.append(item("/broken", position=2))
    happy.pages["https://example.com/broken"] = TimeoutError()
    result = orchestrator.run_pipeline(subject)
    assert result.status == "partial_success"
    assert [e.code for e in result.errors] == ["SEARCH_TIMEOUT", "timeout"]
    assert result.errors == [*pipeline.outputs["A"][0].errors, *pipeline.outputs["B"][0].errors]
    assert_links(result, pipeline)
