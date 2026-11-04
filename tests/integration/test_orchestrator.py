"""Exercise the pipeline using public-contract mocks, without real modules."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from dfsa.contracts import (
    DFSAResult,
    ProfilingRequest,
    ProfilingResponse,
    RiskRequest,
    RiskResponse,
    SearchRequest,
    SearchResponse,
    Subject,
)
from dfsa.service import orchestrator, run_pipeline


@pytest.fixture
def modules(monkeypatch):
    directory = Path(__file__).parents[1] / "fixtures"
    data = {
        stage: json.loads((directory / f"{filename}.json").read_text(encoding="utf-8"))
        for stage, filename in (
            ("search", "search_response"),
            ("profiling", "profiling_response"),
            ("risk", "risk_response"),
        )
    }
    subject = Subject(
        name="홍길동", organization="OO대학교", email="gildong@univ.ac.kr"
    )
    order = []

    def mock_module(stage, model):
        def respond(request):
            order.append(stage)
            return model.model_validate({**data[stage], "request_id": request.request_id})

        return Mock(side_effect=respond)

    search = mock_module("search", SearchResponse)
    profiling = mock_module("profiling", ProfilingResponse)
    risk = mock_module("risk", RiskResponse)
    monkeypatch.setattr(orchestrator, "run_search", search)
    monkeypatch.setattr(orchestrator, "run_profiling", profiling)
    monkeypatch.setattr(orchestrator, "run_risk", risk)
    return SimpleNamespace(
        subject=subject, data=data, order=order,
        search=search, profiling=profiling, risk=risk,
    )


# All reachable stage/early-termination combinations under spec section 24.
@pytest.mark.parametrize(
    ("a", "b", "c", "empty_a", "empty_b", "overall"),
    [
        ("failed", None, None, False, False, "failed"),
        ("success", None, None, True, False, "success"),
        ("success", "failed", None, False, False, "failed"),
        ("success", "success", None, False, True, "success"),
        ("success", "success", "success", False, False, "success"),
        ("success", "success", "partial_success", False, False, "partial_success"),
        ("success", "success", "failed", False, False, "partial_success"),
        ("success", "partial_success", "success", False, False, "partial_success"),
        ("success", "partial_success", "partial_success", False, False, "partial_success"),
        ("success", "partial_success", "failed", False, False, "partial_success"),
        ("partial_success", "failed", None, False, False, "failed"),
        ("partial_success", "success", None, False, True, "partial_success"),
        ("partial_success", "success", "success", False, False, "partial_success"),
        ("partial_success", "success", "partial_success", False, False, "partial_success"),
        ("partial_success", "success", "failed", False, False, "partial_success"),
        ("partial_success", "partial_success", "success", False, False, "partial_success"),
        ("partial_success", "partial_success", "partial_success", False, False, "partial_success"),
        ("partial_success", "partial_success", "failed", False, False, "partial_success"),
    ],
)
def test_pipeline_cases(modules, a, b, c, empty_a, empty_b, overall):
    expected_errors = []
    for stage, status in (("search", a), ("profiling", b), ("risk", c)):
        if status is not None:
            modules.data[stage]["status"] = status
            if status != "success":
                error = {"code": stage.upper() + "_ERROR", "message": stage + " failed in part",
                         "retryable": False, "source_id": None, "query_id": None}
                modules.data[stage]["errors"] = [error]
                expected_errors.append(error)
    if empty_a or a == "failed":
        modules.data["search"]["results"] = []
    if empty_b or b == "failed":
        modules.data["profiling"]["exposures"] = []
    if c == "failed":
        modules.data["risk"]["risk_paths"] = []
    # Keep mock summaries consistent; Orchestrator must calculate its own summary.
    modules.data["risk"]["summary"] = {
        "total_exposures": len(modules.data["profiling"]["exposures"]),
        "total_paths": len(modules.data["risk"]["risk_paths"]),
    }

    result = run_pipeline(modules.subject)

    assert result.status.value == overall
    assert result.stages.model_dump(mode="json") == {
        "search": a,
        "profiling": b or "not_started",
        "risk_analysis": c or "not_started",
    }
    modules.search.assert_called_once()
    assert modules.profiling.call_count == int(b is not None)
    assert modules.risk.call_count == int(c is not None)
    assert modules.order == [
        stage for stage, status in (("search", a), ("profiling", b), ("risk", c))
        if status is not None
    ]
    expected_sources = modules.data["profiling"]["sources"] if b else []
    expected_exposures = modules.data["profiling"]["exposures"] if b else []
    expected_paths = modules.data["risk"]["risk_paths"] if c else []
    payload = result.model_dump(mode="json")
    assert payload["sources"] == expected_sources
    assert payload["exposures"] == expected_exposures
    assert payload["risk_paths"] == expected_paths
    assert payload["errors"] == expected_errors
    assert payload["summary"] == {
        "search_result_count": len(modules.data["search"]["results"]),
        "confirmed_source_count": sum(
            source["identity_status"] == "confirmed" for source in expected_sources
        ),
        "total_exposures": len(expected_exposures),
        "total_risk_paths": len(expected_paths),
    }
    assert DFSAResult.model_validate_json(result.model_dump_json()) == result


def test_request_transformations_and_shared_context(modules, monkeypatch):
    generator = Mock(return_value="req_deterministic")
    monkeypatch.setattr(orchestrator, "_new_request_id", generator)

    result = run_pipeline(modules.subject)

    generator.assert_called_once_with()
    search_request = modules.search.call_args.args[0]
    profiling_request = modules.profiling.call_args.args[0]
    risk_request = modules.risk.call_args.args[0]
    assert isinstance(search_request, SearchRequest)
    assert isinstance(profiling_request, ProfilingRequest)
    assert isinstance(risk_request, RiskRequest)
    assert search_request.options.top_k == 10
    for request in (search_request, profiling_request, risk_request):
        assert request.schema_version == "v0.1"
        assert request.request_id == result.request_id == "req_deterministic"
        assert request.subject == result.subject == modules.subject
    assert [item.model_dump(mode="json") for item in profiling_request.search_results] == modules.data["search"]["results"]
    assert [item.model_dump(mode="json") for item in risk_request.exposures] == modules.data["profiling"]["exposures"]
    assert result.risk_paths[0].reason == modules.data["risk"]["risk_paths"][0]["reason"]
    assert result.risk_paths[0].recommendations == modules.data["risk"]["risk_paths"][0]["recommendations"]


def test_request_ids_are_generated_per_run(modules):
    first = run_pipeline(modules.subject)
    second = run_pipeline(modules.subject)
    assert first.request_id.startswith("req_")
    assert first.request_id != second.request_id


def test_errors_preserve_order_and_distinct_details_without_duplicates(modules):
    common = {"code": "RETRY", "message": "Try again", "retryable": True,
              "source_id": "src_001", "query_id": None}
    other_source = {**common, "source_id": "src_002"}
    last = {"code": "RISK_ERROR", "message": "Some paths unavailable", "retryable": False}
    for stage in ("search", "profiling", "risk"):
        modules.data[stage]["status"] = "partial_success"
    modules.data["search"]["errors"] = [common, common]
    modules.data["profiling"]["errors"] = [common, other_source]
    modules.data["risk"]["errors"] = [last]

    result = run_pipeline(modules.subject)

    assert [error.model_dump() for error in result.errors] == [
        common, other_source, {**last, "source_id": None, "query_id": None}
    ]


def test_summary_counts_confirmed_sources_only(modules):
    source = modules.data["profiling"]["sources"][0]
    modules.data["profiling"]["sources"] += [
        {**source, "source_id": "src_002", "identity_status": "uncertain"},
        {**source, "source_id": "src_003", "identity_status": "rejected"},
        {**source, "source_id": "src_004", "processing_status": "fetch_failed", "identity_status": None},
    ]
    result = run_pipeline(modules.subject)
    assert len(result.sources) == 4
    assert result.summary.confirmed_source_count == 1


def test_cannot_mutate_owned_subject_or_prior_stage_data_via_requests(modules):
    original_subject = modules.subject.model_copy(deep=True)
    respond = modules.profiling.side_effect

    def mutate_then_respond(request):
        request.subject.name = "Changed inside B"
        request.search_results.clear()
        return respond(request)

    modules.profiling.side_effect = mutate_then_respond
    result = run_pipeline(modules.subject)
    assert result.subject == modules.subject == original_subject
    assert result.summary.search_result_count == 1
    assert modules.risk.call_args.args[0].subject == original_subject


def test_unconnected_module_fails_explicitly(modules, monkeypatch):
    monkeypatch.setattr(orchestrator, "run_search", orchestrator._not_connected)
    with pytest.raises(RuntimeError, match="SearchRequest"):
        run_pipeline(modules.subject)
    modules.profiling.assert_not_called()
    modules.risk.assert_not_called()


def test_unexpected_module_exception_is_not_silently_rewritten(modules):
    modules.search.side_effect = RuntimeError("Unexpected failure")
    with pytest.raises(RuntimeError, match="Unexpected failure"):
        run_pipeline(modules.subject)
    modules.profiling.assert_not_called()
    modules.risk.assert_not_called()


def test_invalid_module_response_is_rejected_before_downstream_call(modules):
    modules.search.side_effect = None
    modules.search.return_value = {**modules.data["search"], "unexpected_field": True}
    with pytest.raises(ValidationError, match="extra_forbidden"):
        run_pipeline(modules.subject)
    modules.profiling.assert_not_called()
    modules.risk.assert_not_called()
