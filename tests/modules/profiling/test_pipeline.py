"""Public B behavior with real Phase 1-5 and source-local failure boundaries."""

import socket
import ssl
from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from dfsa.contracts.common import ErrorDetail, ExposureType, IdentityStatus, ModuleStatus, Subject
from dfsa.contracts.profiling import Exposure, ProfilingRequest, ProfilingResponse, Source
from dfsa.modules.profiling import run_profiling
from dfsa.modules.profiling import deduplication, extraction, fetch, identity, parsing, pipeline
from dfsa.modules.profiling._types import (
    ExtractionResult, FetchError, FetchFailure, ParseError, ParseFailure,
)


def test_empty_request_still_deduplicates_once(phase6_request, monkeypatch):
    merge = Mock(wraps=deduplication.deduplicate_exposures)
    get = Mock(side_effect=AssertionError("Fetch must not run"))
    monkeypatch.setattr(deduplication, "deduplicate_exposures", merge)
    monkeypatch.setattr(fetch, "fetch_html", get)
    result = run_profiling(phase6_request(()))
    assert result.status == ModuleStatus.SUCCESS
    assert result.sources == result.exposures == result.errors == []
    merge.assert_called_once_with([])
    get.assert_not_called()
    payload = result.model_dump(mode="json")
    assert all(payload[key] == [] for key in ("sources", "exposures", "errors"))


@pytest.mark.parametrize("kind,status,identity_status,has_exposures", [
    ("confirmed", "success", "confirmed", True),
    ("uncertain", "success", "uncertain", False),
    ("rejected", "rejected", "rejected", False),
    ("zero", "success", "confirmed", False),
    ("empty", "success", "uncertain", False),
])
def test_real_identity_status_and_extraction_gate(
        phase6_request, phase6_html, phase6_transport, monkeypatch,
        kind, status, identity_status, has_exposures):
    request = phase6_request()
    phase6_transport([phase6_html[kind]])
    verify = Mock(wraps=identity.verify_identity)
    real_extract = extraction.extract_exposures
    extract = Mock(wraps=real_extract)
    monkeypatch.setattr(identity, "verify_identity", verify)
    monkeypatch.setattr(extraction, "extract_exposures", extract)
    result = run_profiling(request)
    assert result.status == ModuleStatus.SUCCESS
    assert result.sources[0].processing_status == status
    assert result.sources[0].identity_status == identity_status
    assert bool(result.exposures) == has_exposures
    assert result.errors == []
    verify.assert_called_once()
    assert extract.call_count == int(identity_status == "confirmed")
    if kind == "zero":
        # Capture the actual Phase 4 return without issuing a second fetch.
        doc, decision = extract.call_args.args
        real_result = real_extract(doc, decision)
        assert real_result.candidates == ()
        assert {d.code for d in real_result.diagnostics} == {"value_not_in_contiguous_evidence"}


@pytest.mark.parametrize("kind", list(FetchError))
def test_every_fetch_error_mapping_preserves_details_and_stops_source(
        phase6_request, monkeypatch, kind):
    request = phase6_request()
    src = request.search_results[0]
    detail = ErrorDetail(code=kind.value, message="Original external failure",
                        retryable=True, source_id=src.source_id, query_id="q_recorded")
    failure = FetchFailure(src.source_id, src.url, src.url, kind, detail)
    monkeypatch.setattr(fetch, "fetch_html", Mock(return_value=failure))
    parse = Mock(side_effect=AssertionError("Parse must not run"))
    verify = Mock(side_effect=AssertionError("Identity must not run"))
    extract = Mock(side_effect=AssertionError("Extraction must not run"))
    monkeypatch.setattr(parsing, "parse_html", parse)
    monkeypatch.setattr(identity, "verify_identity", verify)
    monkeypatch.setattr(extraction, "extract_exposures", extract)
    expected = ("unsupported" if kind in {FetchError.UNSUPPORTED_CONTENT_TYPE,
                                          FetchError.UNSUPPORTED_ENCODING}
                else "rejected" if kind == FetchError.BLOCKED_URL else "fetch_failed")
    result = run_profiling(request)
    assert result.status == ModuleStatus.FAILED
    assert result.sources[0].processing_status == expected
    assert result.sources[0].identity_status is None
    assert result.errors == [detail]
    assert ErrorDetail.model_validate_json(result.errors[0].model_dump_json()) == detail
    assert result.exposures == []
    for later in (parse, verify, extract):
        later.assert_not_called()


@pytest.mark.parametrize("kind", list(ParseError))
def test_every_parse_error_is_parse_failed(
        phase6_request, phase6_html, phase6_transport, monkeypatch, kind):
    request = phase6_request()
    src = request.search_results[0]
    detail = ErrorDetail(code=kind.value, message="Original parse failure", retryable=False,
                        source_id=src.source_id)
    failure = ParseFailure(src.source_id, src.url, src.url, kind, detail)
    phase6_transport([phase6_html["confirmed"]])
    monkeypatch.setattr(parsing, "parse_html", Mock(return_value=failure))
    verify = Mock(side_effect=AssertionError("Identity must not run"))
    extract = Mock(side_effect=AssertionError("Extraction must not run"))
    monkeypatch.setattr(identity, "verify_identity", verify)
    monkeypatch.setattr(extraction, "extract_exposures", extract)
    result = run_profiling(request)
    assert result.status == ModuleStatus.FAILED
    assert result.sources[0].processing_status == "parse_failed"
    assert result.sources[0].identity_status is None
    assert result.errors == [detail]
    verify.assert_not_called()
    extract.assert_not_called()


@pytest.mark.parametrize("problem,code,retryable,status", [
    ("dns", "dns_error", True, "fetch_failed"),
    ("tls", "tls_error", False, "fetch_failed"),
    ("timeout", "timeout", True, "fetch_failed"),
    ("network", "network_error", True, "fetch_failed"),
    ("http404", "http_404", False, "fetch_failed"),
    ("http429", "http_429", True, "fetch_failed"),
    ("http503", "http_5xx", True, "fetch_failed"),
    ("content", "unsupported_content_type", False, "unsupported"),
    ("encoding", "unsupported_encoding", False, "unsupported"),
    ("blocked", "blocked_url", False, "rejected"),
    ("charset", "unsupported_charset", False, "parse_failed"),
    ("invalid_url", "invalid_url", False, "fetch_failed"),
    ("body", "body_too_large", False, "fetch_failed"),
    ("invalid_response", "invalid_response", False, "fetch_failed"),
    ("redirect", "redirect_limit", False, "fetch_failed"),
])
def test_actual_fetch_parse_failures_keep_original_error_policy(
        phase6_request, phase6_transport, response_factory, monkeypatch,
        problem, code, retryable, status):
    request = phase6_request()
    payloads = ["<p>HTML</p>"]
    if problem in {"tls", "timeout", "network"}:
        payloads = [{"tls": ssl.SSLError("TLS"), "timeout": TimeoutError(),
                     "network": OSError("network")}[problem]]
    elif problem.startswith("http"):
        payloads = [response_factory(code=int(problem[4:]))]
    elif problem == "content":
        payloads = [response_factory(headers={"Content-Type": "application/pdf"})]
    elif problem == "encoding":
        payloads = [response_factory(headers={"Content-Type": "text/html", "Content-Encoding": "gzip"})]
    elif problem == "charset":
        payloads = [response_factory(headers={"Content-Type": "text/html; charset=utf-16"})]
    elif problem == "body":
        payloads = [response_factory(headers={"Content-Type": "text/html", "Content-Length": "2097153"})]
    elif problem == "invalid_response":
        payloads = [response_factory(headers={"Content-Type": "text/html", "Content-Length": "oops"})]
    elif problem == "redirect":
        payloads = [response_factory(code=302, headers={"Location": request.search_results[0].url})]
    elif problem in {"blocked", "invalid_url"}:
        request.search_results[0].url = "http://127.0.0.1/" if problem == "blocked" else "file:///bad"
    opener = phase6_transport(payloads)
    if problem == "dns":
        def fail_dns(*args, **kwargs):
            raise socket.gaierror("no DNS")
        monkeypatch.setattr(socket, "getaddrinfo", fail_dns)
    result = run_profiling(request)
    assert result.status == ModuleStatus.FAILED
    assert result.sources[0].processing_status == status
    assert result.sources[0].identity_status is None
    assert result.errors[0].model_dump() == {
        "code": code, "message": result.errors[0].message, "retryable": retryable,
        "source_id": "src_001", "query_id": None,
    }
    assert result.errors[0].message
    if problem in {"blocked", "invalid_url", "dns"}:
        assert opener.calls == []


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("kinds,expected", [
    ((), "success"),
    (("confirmed", "confirmed"), "success"),
    (("uncertain", "uncertain"), "success"),
    (("rejected", "rejected"), "success"),
    (("zero", "zero"), "success"),
    (("confirmed", "uncertain"), "success"),
    (("confirmed", "rejected"), "success"),
    (("confirmed", "fetch"), "partial_success"),
    (("confirmed", "parse"), "partial_success"),
    (("confirmed", "unsupported"), "partial_success"),
    (("uncertain", "fetch"), "partial_success"),
    (("uncertain", "parse"), "partial_success"),
    (("rejected", "fetch"), "partial_success"),
    (("zero", "fetch"), "partial_success"),
    (("fetch", "fetch"), "failed"),
    (("parse", "parse"), "failed"),
    (("unsupported", "unsupported"), "failed"),
    (("fetch", "parse"), "failed"),
    (("blocked", "fetch"), "failed"),
    (("blocked", "blocked"), "failed"),
    (("confirmed", "fetch", "confirmed"), "partial_success"),
])
def test_module_status_uses_completed_decisions_not_exposure_count(
        phase6_request, phase6_html, phase6_transport, response_factory, kinds, expected, reverse):
    kinds = tuple(reversed(kinds)) if reverse else kinds
    request = phase6_request(tuple(f"src_{i}" for i in range(len(kinds))))
    payloads = []
    identities = []
    for source, kind in zip(request.search_results, kinds):
        if kind == "blocked":
            source.url = "http://127.0.0.1/"
        else:
            payloads.append({
                "fetch": TimeoutError(),
                "parse": response_factory(b"\xff"),
                "unsupported": response_factory(headers={"Content-Type": "application/pdf"}),
            }.get(kind, phase6_html.get(kind)))
        identities.append({"confirmed": "confirmed", "zero": "confirmed",
                           "uncertain": "uncertain", "rejected": "rejected"}.get(kind))
    phase6_transport(payloads)
    result = run_profiling(request)
    assert result.status == expected
    assert [s.source_id for s in result.sources] == [s.source_id for s in request.search_results]
    assert [s.identity_status for s in result.sources] == identities
    assert len(result.errors) == sum(kind in {"fetch", "parse", "unsupported", "blocked"} for kind in kinds)
    if "confirmed" not in kinds:
        assert result.exposures == []


def test_request_local_deduplication_evidence_and_determinism(
        phase6_request, phase6_transport, phase4_card, monkeypatch):
    fields = ('<p>Lab: AI &amp; Security Lab</p><p>Lab: AI &amp; Security Lab</p>'
              '<p>Phone: 02-1234-5678</p><p>Advisor: Bob Lee</p>'
              '<p>Activity: Presented DFSA</p><p>Research Interests: AI</p>'
              '<p>GitHub: <a href="https://github.com/alice">alice</a></p>'
              '<p>Project period: 2022–2024</p>')
    htmls = [phase4_card(fields), phase4_card(fields.replace("AI &amp; Security Lab", "AI & Security Lab"))]
    request = phase6_request(("src_z", "src_a"))
    before = deepcopy(request)
    merge = Mock(wraps=deduplication.deduplicate_exposures)
    monkeypatch.setattr(deduplication, "deduplicate_exposures", merge)
    phase6_transport(htmls)
    first = run_profiling(request)
    merge.assert_called_once()
    candidates = merge.call_args.args[0]
    assert {c.source_id for c in candidates} == {"src_z", "src_a"}
    assert [c.source_id for c in candidates] == (
        ["src_z"] * sum(c.source_id == "src_z" for c in candidates)
        + ["src_a"] * sum(c.source_id == "src_a" for c in candidates))
    assert {e.type for e in first.exposures} == set(ExposureType)
    assert [s.source_id for s in first.sources] == ["src_z", "src_a"]
    for exposure in first.exposures:
        assert {s.source_id for s in exposure.sources} == {"src_z", "src_a"}
        pairs = [(s.source_id, s.evidence) for s in exposure.sources]
        assert pairs == sorted(set(pairs))
        assert all("SNIPPET" not in s.evidence for s in exposure.sources)
        assert Exposure.model_validate_json(exposure.model_dump_json()) == exposure
    lab = next(e for e in first.exposures if e.type == ExposureType.AFFILIATION)
    assert lab.value == "AI & Security Lab"
    assert len(lab.sources) == 2
    phase6_transport(htmls)
    assert run_profiling(request) == first
    assert request == before
    first.exposures[0].sources.clear()
    first.sources[0].url = "changed"
    phase6_transport(htmls)
    assert run_profiling(request).exposures[0].sources
    assert request == before


def test_same_source_distinct_quotes_survive_and_subject_is_not_evidence(
        phase6_request, phase6_transport, phase4_card):
    html = phase4_card('<p>Research Interests: AI\n  Security</p>'
                       '<p>Research Interests: AI Security</p>')
    phase6_transport([html])
    result = run_profiling(phase6_request())
    interest = next(e for e in result.exposures if e.type == ExposureType.INTEREST)
    assert {s.evidence for s in interest.sources} == {
        "Research Interests: AI\n  Security", "Research Interests: AI Security"}
    assert not any(e.value == "Example University" for e in result.exposures)


def test_redirect_preserves_original_url_and_ignores_normalized_url(
        phase6_request, phase6_html, phase6_transport, response_factory):
    request = phase6_request()
    opener = phase6_transport([
        response_factory(code=302, headers={"Location": "/new-profile"}),
        phase6_html["confirmed"],
    ])
    result = run_profiling(request)
    assert [call[0].full_url for call in opener.calls] == [request.search_results[0].url,
                                                         "https://example.com/new-profile"]
    assert result.sources[0].url == request.search_results[0].url
    assert {s.source_id for e in result.exposures for s in e.sources} == {"src_001"}


def test_different_subject_requests_never_share_candidates(phase6_request, phase6_transport):
    results = []
    for name, source_id in [("Alice Kim", "src_alice"), ("Bob Lee", "src_bob")]:
        subject = Subject(name=name, organization="Example University", email="shared@example.com")
        request = phase6_request((source_id,), subject=subject, request_id=f"req_{source_id}")
        phase6_transport([f'<div class=profile-card><h2>{name}</h2>'
                          '<p>Email: shared@example.com</p></div>'])
        result = run_profiling(request)
        results.append(result)
        assert result.request_id == request.request_id
        assert result.exposures[0].exposure_id == "exp_001"
        assert {s.source_id for e in result.exposures for s in e.sources} == {source_id}
    assert {e.value for e in results[0].exposures} != {e.value for e in results[1].exposures}


@pytest.mark.parametrize("field,value", [
    ("message", "different"), ("retryable", False), ("code", "other"),
    ("query_id", "q_other"), ("source_id", "src_other"),
])
def test_error_dedup_uses_all_fields_in_source_order(field, value):
    original = ErrorDetail(code="timeout", message="original", retryable=True, source_id="src_001")
    other = original.model_copy(update={field: value})
    source = Source(source_id="src_001", url="https://example.com/a", processing_status="fetch_failed")
    outcomes = [pipeline._SourceOutcome(source, errors=(original, original.model_copy())),
                pipeline._SourceOutcome(source, errors=(other, original))]
    assert pipeline._collect_errors(outcomes) == [original, other]


def test_public_errors_are_preserved_in_input_source_order(
        phase6_request, phase6_transport, response_factory):
    phase6_transport([TimeoutError(), response_factory(code=404), ssl.SSLError("tls")])
    result = run_profiling(phase6_request(("src_c", "src_a", "src_b")))
    assert [(e.source_id, e.code, e.query_id) for e in result.errors] == [
        ("src_c", "timeout", None), ("src_a", "http_404", None), ("src_b", "tls_error", None)]


def test_public_response_deduplicates_identical_errors_without_changing_fields(
        phase6_request, monkeypatch):
    common = ErrorDetail(code="network_error", message="Original failure", retryable=True)
    distinct = common.model_copy(update={"message": "Another failure"})
    details = iter((common, common.model_copy(), distinct))
    def fail(source):
        return FetchFailure(source.source_id, source.url, source.url,
                            FetchError.NETWORK_ERROR, next(details))
    monkeypatch.setattr(fetch, "fetch_html", fail)
    result = run_profiling(phase6_request(("src_1", "src_2", "src_3")))
    assert result.status == "failed"
    assert result.errors == [common, distinct]
    assert all(e.source_id is None and e.query_id is None for e in result.errors)


@pytest.mark.parametrize("bad", ["unvalidated", "empty_value", "malformed_evidence"])
def test_malformed_extraction_candidates_raise(
        phase6_request, phase6_html, phase6_transport, monkeypatch, bad):
    from dfsa.modules.profiling._types import ExposureCandidate

    phase6_transport([phase6_html["confirmed"]])
    original = extraction.extract_exposures
    def broken(document, decision):
        candidate = original(document, decision).candidates[0]
        if bad == "unvalidated":
            candidate = ExposureCandidate(candidate.source_id, candidate.target_block_id,
                                          candidate.type, candidate.value, candidate.evidence)
        elif bad == "empty_value":
            candidate = replace(candidate, value="")
        else:
            candidate = replace(candidate, evidence=replace(candidate.evidence, text_indices=()))
        return ExtractionResult((candidate,))
    monkeypatch.setattr(extraction, "extract_exposures", broken)
    with pytest.raises(ValueError):
        run_profiling(phase6_request())


@pytest.mark.parametrize("change", ["null_status", "empty_scope", "missing_block"])
def test_invalid_identity_completion_cannot_become_normal_zero(
        phase6_request, phase6_html, phase6_transport, monkeypatch, change):
    phase6_transport([phase6_html["confirmed"]])
    original = identity.verify_identity
    def broken(subject, document):
        decision = original(subject, document)
        changes = {"null_status": {"identity_status": None},
                   "empty_scope": {"target_block_ids": ()},
                   "missing_block": {"target_block_ids": (99999,)}}
        return replace(decision, **changes[change])
    monkeypatch.setattr(identity, "verify_identity", broken)
    with pytest.raises(ValueError):
        run_profiling(phase6_request())


def test_input_is_detached_from_internal_stage_arguments(
        phase6_request, phase6_html, phase6_transport, monkeypatch):
    request = phase6_request()
    before = request.model_copy(deep=True)
    phase6_transport([phase6_html["confirmed"]])
    original = identity.verify_identity
    def verify_then_mutate(subject, document):
        result = original(subject, document)
        subject.name = "Changed in internal stage"
        return result
    monkeypatch.setattr(identity, "verify_identity", verify_then_mutate)
    assert run_profiling(request).status == "success"
    assert request == before


def test_search_snippet_cannot_confirm_an_empty_document(phase6_request, phase6_transport):
    request = phase6_request()
    request.search_results[0].snippet = "Alice Kim Email: alice@example.com Example University"
    request.search_results[0].title = request.search_results[0].snippet
    phase6_transport([""])
    result = run_profiling(request)
    assert result.status == "success"
    assert result.sources[0].identity_status == "uncertain"
    assert result.exposures == []


def test_real_phase4_ownership_rules_are_preserved(
        phase6_request, phase6_transport, phase4_card):
    phase6_transport([phase4_card('<p>Advisor Bob Lee phone: 02-9999-8888</p>')])
    result = run_profiling(phase6_request())
    assert result.sources[0].identity_status == "confirmed"
    assert all("02-9999-8888" not in e.value for e in result.exposures)
    assert result.errors == []


@pytest.mark.parametrize("stage", ["fetch", "parse", "identity", "extraction", "deduplication"])
def test_unexpected_errors_propagate_without_public_response(
        phase6_request, phase6_html, phase6_transport, monkeypatch, stage):
    phase6_transport([phase6_html["confirmed"]])
    owner, name = {"fetch": (fetch, "fetch_html"), "parse": (parsing, "parse_html"),
                   "identity": (identity, "verify_identity"),
                   "extraction": (extraction, "extract_exposures"),
                   "deduplication": (deduplication, "deduplicate_exposures")}[stage]
    problem = RuntimeError("unexpected implementation error")
    monkeypatch.setattr(owner, name, Mock(side_effect=problem))
    with pytest.raises(RuntimeError) as caught:
        run_profiling(phase6_request())
    assert caught.value is problem


@pytest.mark.parametrize("stage", ["fetch", "parse", "identity", "candidate", "scope", "evidence"])
def test_broken_internal_source_scope_or_evidence_raises(
        phase6_request, phase6_html, phase6_transport, monkeypatch, stage):
    phase6_transport([phase6_html["confirmed"]])
    if stage in {"fetch", "parse", "identity"}:
        owner, name = {"fetch": (fetch, "fetch_html"), "parse": (parsing, "parse_html"),
                       "identity": (identity, "verify_identity")}[stage]
        original = getattr(owner, name)
        def wrong_source(*args):
            return replace(original(*args), source_id="src_wrong")
        monkeypatch.setattr(owner, name, wrong_source)
    elif stage in {"candidate", "scope"}:
        original = extraction.extract_exposures
        def corrupted(document, decision):
            result = original(document, decision)
            change = {"source_id": "src_wrong"} if stage == "candidate" else {"target_block_id": 99999}
            return replace(result, candidates=(replace(result.candidates[0], **change),))
        monkeypatch.setattr(extraction, "extract_exposures", corrupted)
    else:
        original = extraction.validate_candidate
        def invalid_reference(document, decision, candidate, **kwargs):
            candidate = replace(candidate, evidence=replace(candidate.evidence, start=99999))
            return original(document, decision, candidate, **kwargs)
        monkeypatch.setattr(extraction, "validate_candidate", invalid_reference)
    with pytest.raises(ValueError):
        run_profiling(phase6_request())


@pytest.mark.parametrize("change", ["unknown_source", "unconfirmed_source", "evidence", "contract"])
def test_invalid_deduplication_output_is_not_returned(
        phase6_request, phase6_html, phase6_transport, monkeypatch, change):
    phase6_transport([phase6_html["confirmed"], phase6_html["uncertain"]])
    original = deduplication.deduplicate_exposures
    def broken(candidates):
        result = original(candidates)
        if change == "contract":
            result[0].sources.clear()
        elif change == "evidence":
            result[0].sources[0].evidence = "fabricated quote"
        else:
            result[0].sources[0].source_id = "src_unknown" if change == "unknown_source" else "src_uncertain"
        return result
    monkeypatch.setattr(deduplication, "deduplicate_exposures", broken)
    with pytest.raises(ValidationError if change == "contract" else ValueError):
        run_profiling(phase6_request(("src_confirmed", "src_uncertain")))


def test_public_contract_roundtrip_and_owned_fields(phase6_request, phase6_html, phase6_transport):
    request = phase6_request(request_id="req_owned")
    assert ProfilingRequest.model_validate_json(request.model_dump_json()) == request
    phase6_transport([phase6_html["confirmed"]])
    response = run_profiling(request)
    assert response.request_id == request.request_id
    assert response.schema_version == request.schema_version
    assert ProfilingResponse.model_validate_json(response.model_dump_json()) == response
    for source in response.sources:
        assert Source.model_validate_json(source.model_dump_json()) == source
        assert source.identity_status is not None
    for exposure in response.exposures:
        assert exposure.sources
        assert {s.source_id for s in exposure.sources} <= {s.source_id for s in response.sources
                                                          if s.identity_status == IdentityStatus.CONFIRMED}


@pytest.mark.parametrize("change", ["version", "missing", "extra", "mutated_nested"])
def test_invalid_request_is_rejected_before_fetch(phase6_request, monkeypatch, change):
    request = phase6_request()
    get = Mock(side_effect=AssertionError("Fetch must not run"))
    monkeypatch.setattr(fetch, "fetch_html", get)
    data = request.model_dump()
    if change == "version":
        data["schema_version"] = "v0.2"
    elif change == "missing":
        del data["search_results"]
    elif change == "extra":
        data["subject_copy"] = data["subject"]
    else:
        request.subject.email = "invalid"
        data = request
    with pytest.raises(ValidationError):
        run_profiling(data)
    get.assert_not_called()
