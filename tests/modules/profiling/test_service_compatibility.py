"""Mock A -> real B -> mock C through the unchanged public orchestrator."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dfsa.contracts import DFSAResult, ProfilingRequest, RiskRequest, RiskResponse, SearchResponse
from dfsa.contracts.common import ErrorDetail, IdentityStatus, ModuleStatus
from dfsa.modules.profiling import run_profiling
from dfsa.modules.profiling import identity
from dfsa.service import orchestrator


@pytest.fixture
def real_b_service(monkeypatch, phase6_request):
    def wire(source_ids, *, search_status="success"):
        template = phase6_request(source_ids)
        order = []
        b_responses = []
        search_errors = ([ErrorDetail(code="search_partial", message="One query failed", retryable=True)]
                         if search_status == "partial_success" else [])

        def search(request):
            order.append("A")
            return SearchResponse(
                schema_version=request.schema_version, request_id=request.request_id,
                status=search_status, searched_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
                results=template.search_results, errors=search_errors,
            )

        def profiling(request):
            order.append("B")
            result = run_profiling(request)
            b_responses.append(result)
            return result

        def risk(request):
            order.append("C")
            return RiskResponse(
                schema_version=request.schema_version, request_id=request.request_id,
                status="success", risk_paths=[{
                    "risk_path_id": "path_mock", "rule_id": "R01",
                    "category": "authority_impersonation", "path_status": "candidate",
                    "exposure_ids": [e.exposure_id for e in request.exposures],
                    "evaluation": {key: "UNKNOWN" for key in (
                        "searchability", "cross_source_linkability", "attack_utility",
                        "sensitivity", "evidence_confidence")},
                    "reason": "Original mock C explanation",
                    "recommendations": ["Original mock C recommendation"],
                }],
                summary={"total_exposures": len(request.exposures), "total_paths": 1},
            )

        a, b, c = Mock(side_effect=search), Mock(side_effect=profiling), Mock(side_effect=risk)
        monkeypatch.setattr(orchestrator, "run_search", a)
        monkeypatch.setattr(orchestrator, "run_profiling", b)
        monkeypatch.setattr(orchestrator, "run_risk", c)
        monkeypatch.setattr(orchestrator, "_new_request_id", lambda: "req_service_phase6")
        return SimpleNamespace(template=template, a=a, b=b, c=c, order=order,
                               responses=b_responses, search_errors=search_errors)
    return wire


@pytest.mark.parametrize("kinds,b_status,c_called", [
    (("confirmed",), "success", True),
    (("zero",), "success", False),
    (("uncertain",), "success", False),
    (("rejected",), "success", False),
    (("confirmed", "fetch"), "partial_success", True),
    (("zero", "fetch"), "partial_success", False),
    (("uncertain", "fetch"), "partial_success", False),
    (("rejected", "fetch"), "partial_success", False),
    (("fetch",), "failed", False),
    (("parse", "fetch"), "failed", False),
])
def test_real_b_pipeline_status_c_gate_and_final_result(
        real_b_service, phase6_html, phase6_transport, response_factory, kinds, b_status, c_called):
    modules = real_b_service(tuple(f"src_{i}" for i in range(len(kinds))))
    payloads = [TimeoutError() if kind == "fetch" else response_factory(b"\xff") if kind == "parse"
                else phase6_html[kind] for kind in kinds]
    phase6_transport(payloads)
    result = orchestrator.run_pipeline(modules.template.subject)
    b_response = modules.responses[0]
    assert b_response.status == b_status
    assert result.status == b_status
    assert result.stages.search == "success"
    assert result.stages.profiling == b_status
    assert result.stages.risk_analysis == ("success" if c_called else "not_started")
    assert modules.order == (["A", "B", "C"] if c_called else ["A", "B"])
    modules.a.assert_called_once()
    modules.b.assert_called_once()
    assert modules.c.call_count == int(c_called)
    assert isinstance(modules.b.call_args.args[0], ProfilingRequest)
    assert result.sources == b_response.sources
    assert result.exposures == b_response.exposures
    assert result.errors == b_response.errors
    assert result.summary.model_dump() == {
        "search_result_count": len(kinds),
        "confirmed_source_count": sum(s.identity_status == IdentityStatus.CONFIRMED
                                      for s in b_response.sources),
        "total_exposures": len(b_response.exposures),
        "total_risk_paths": int(c_called),
    }
    assert DFSAResult.model_validate_json(result.model_dump_json()) == result
    assert result.request_id == b_response.request_id == "req_service_phase6"
    assert modules.a.call_args.args[0].request_id == result.request_id
    assert modules.b.call_args.args[0].search_results == modules.template.search_results
    if c_called:
        risk_request = modules.c.call_args.args[0]
        assert isinstance(risk_request, RiskRequest)
        assert risk_request.request_id == result.request_id
        assert risk_request.schema_version == b_response.schema_version == result.schema_version
        assert risk_request.exposures == b_response.exposures
        assert result.risk_paths[0].exposure_ids == [e.exposure_id for e in b_response.exposures]
        assert result.risk_paths[0].reason == "Original mock C explanation"
        assert result.risk_paths[0].recommendations == ["Original mock C recommendation"]
    else:
        assert result.risk_paths == []


@pytest.mark.parametrize("kind", ["confirmed", "zero"])
def test_a_partial_success_is_preserved_with_real_b(
        real_b_service, phase6_html, phase6_transport, kind):
    modules = real_b_service(("src_001",), search_status="partial_success")
    phase6_transport([phase6_html[kind]])
    result = orchestrator.run_pipeline(modules.template.subject)
    assert modules.responses[0].status == ModuleStatus.SUCCESS
    assert result.status == ModuleStatus.PARTIAL_SUCCESS
    assert result.stages.search == "partial_success"
    assert result.stages.profiling == "success"
    assert result.errors == modules.search_errors
    assert modules.c.call_count == int(kind == "confirmed")


def test_real_b_errors_are_appended_after_a_errors(
        real_b_service, phase6_html, phase6_transport):
    modules = real_b_service(("src_good", "src_bad"), search_status="partial_success")
    phase6_transport([phase6_html["confirmed"], TimeoutError()])
    result = orchestrator.run_pipeline(modules.template.subject)
    assert result.status == "partial_success"
    assert result.errors == [*modules.search_errors, *modules.responses[0].errors]
    assert [e.code for e in result.errors] == ["search_partial", "timeout"]


def test_internal_real_b_exception_propagates_before_c(
        real_b_service, phase6_html, phase6_transport, monkeypatch):
    modules = real_b_service(("src_001",))
    phase6_transport([phase6_html["confirmed"]])
    problem = ValueError("invalid internal identity reference")
    monkeypatch.setattr(identity, "verify_identity", Mock(side_effect=problem))
    with pytest.raises(ValueError) as caught:
        orchestrator.run_pipeline(modules.template.subject)
    assert caught.value is problem
    assert modules.order == ["A", "B"]
    modules.c.assert_not_called()
    assert modules.responses == []


def test_c_input_mutation_does_not_change_real_b_response_or_subject(
        real_b_service, phase6_html, phase6_transport):
    modules = real_b_service(("src_001",))
    original = modules.template.subject.model_copy(deep=True)
    respond = modules.c.side_effect
    def mutating_risk(request):
        response = respond(request)
        request.exposures[0].sources.clear()
        request.subject.name = "changed in C"
        return response
    modules.c.side_effect = mutating_risk
    phase6_transport([phase6_html["confirmed"]])
    result = orchestrator.run_pipeline(modules.template.subject)
    assert result.subject == modules.template.subject == original
    assert modules.responses[0].exposures[0].sources
    assert result.exposures == modules.responses[0].exposures
