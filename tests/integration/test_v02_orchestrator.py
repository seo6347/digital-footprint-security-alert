from dataclasses import replace
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dfsa.contracts import (
    AnalysisResponse, ErrorDetail, ExplorationResult, NavigationEntry, ProfilingResponse, Source, StageStatus,
)
from dfsa.service import orchestrator, run_pipeline


@pytest.fixture
def install(monkeypatch, v02_fixtures):
    def setup(case="success", **replacements):
        calls = []
        handlers = v02_fixtures["mock_handlers"](case) | replacements

        def record(name, handler):
            def invoke(request):
                calls.append((name, request))
                return handler(request)
            return invoke

        for name, handler in handlers.items():
            monkeypatch.setattr(orchestrator, name, record(name, handler))
        return calls
    return setup


@pytest.mark.parametrize("case,status,stages", [
    ("success", "success", ["success", "success", "success", "success"]),
    ("partial_success", "partial_success", ["success", "success", "success", "failed"]),
    ("failed", "failed", ["failed", "not_started", "not_started", "not_started"]),
    ("zero", "success", ["success", "not_started", "not_started", "not_started"]),
])
def test_pipeline_ui_scenarios(case, status, stages, install, monkeypatch, v02_fixtures):
    times = iter(value / 100 for value in range(10))
    monkeypatch.setattr(orchestrator, "perf_counter", lambda: next(times))
    calls = install(case)
    result = run_pipeline(v02_fixtures["SUBJECT"])
    assert result.status == status
    assert list(result.stages.model_dump(mode="json").values()) == stages
    assert [name for name, _ in calls] == [
        f"run_{stage}" for stage, status in zip(("search", "exploration", "profiling", "analysis"), stages)
        if status != "not_started"
    ]
    assert {request.request_id for _, request in calls} == {result.request_id}
    times = result.execution_time.model_dump()
    assert times.pop("total_ms") == pytest.approx((2 * len(calls) + 1) * 10)
    for stage, duration in zip(stages, times.values()):
        if stage == "not_started":
            assert duration is None
        else:
            assert duration == pytest.approx(10)
    if case == "partial_success":
        assert result.summary.total_exposures == 1
        assert result.summary.total_graph_nodes == 0
        assert result.errors[0].code == "MOCK_ANALYSIS_FAILURE"
    fixture = Path(__file__).parents[1] / "fixtures" / "v02" / "ui" / f"{case}.json"
    expected = json.loads(fixture.read_text(encoding="utf-8"))
    expected["request_id"] = result.request_id
    expected["execution_time"] = result.execution_time.model_dump()
    assert result.model_dump(mode="json") == expected


@pytest.mark.parametrize("stage,status", [
    ("exploration", "failed"), ("exploration", "success"),
    ("profiling", "failed"), ("profiling", "success"),
])
def test_empty_or_failed_stages_stop_downstream(stage, status, install, v02_fixtures):
    def response(request):
        if stage == "profiling" and status == "success":
            completed = v02_fixtures["stage_responses"](request.request_id)[2]
            return completed.model_copy(update={"exposures": []})
        model = ExplorationResult if stage == "exploration" else ProfilingResponse
        errors = [ErrorDetail(code="SYNTHETIC_FAILURE", message="Stage unavailable.", retryable=True)
                  ] if status == "failed" else []
        return model(schema_version="v0.2", request_id=request.request_id, status=status, errors=errors)

    calls = install(**{f"run_{stage}": response})
    result = run_pipeline(v02_fixtures["SUBJECT"])
    assert calls[-1][0] == f"run_{stage}"
    assert result.status == status
    assert result.stages.analysis == StageStatus.NOT_STARTED
    assert result.discovered_sources
    if stage == "profiling":
        assert result.navigation_history


def test_partial_search_and_exploration_continue_and_deduplicate_errors(install, v02_fixtures):
    error = ErrorDetail(code="SYNTHETIC_FAILURE", message="One item failed.", retryable=True)
    responses = v02_fixtures["stage_responses"]

    def search(request):
        return responses(request.request_id)[0].model_copy(update={"status": "partial_success", "errors": [error]})

    def exploration(request):
        return responses(request.request_id)[1].model_copy(update={
            "status": "partial_success", "limit_reached": True,
            "errors": [error, error.model_copy(update={"retryable": False})],
        })

    calls = install(run_search=search, run_exploration=exploration)
    result = run_pipeline(v02_fixtures["SUBJECT"])
    assert len(calls) == 4
    assert result.status == "partial_success"
    assert result.exploration_limit_reached
    assert [item.retryable for item in result.errors] == [True, False]


def test_partial_profiling_continues_with_verified_exposures(install, v02_fixtures):
    def profiling(request):
        response = v02_fixtures["stage_responses"](request.request_id)[2]
        error = ErrorDetail(code="MOCK_PARTIAL", message="One extraction step failed.", retryable=True)
        return response.model_copy(update={"status": "partial_success", "errors": [error]})

    calls = install(run_profiling=profiling)
    result = run_pipeline(v02_fixtures["SUBJECT"])
    assert calls[-1][0] == "run_analysis"
    assert result.stages.profiling == result.status == "partial_success"
    assert result.relationship_graph.edges


def test_visited_pages_count_attempted_ids_once_with_policy_blocks(install, v02_fixtures):
    def exploration(request):
        success = v02_fixtures["stage_responses"](request.request_id)[1]
        blocked = [
            NavigationEntry(
                navigation_id=f"nav_blocked_{label}", source_id=f"nav_src_{label}",
                parent_source_id="src_profile", root_source_id="src_profile",
                status="blocked", url=f"https://lab.example.org/{label}", depth=1,
            )
            for label in ("pre_request", "after_request")
        ]
        retained_path = success.navigation_history[0].model_copy(update={
            "navigation_id": "nav_duplicate_path", "status": "skipped",
        })
        return success.model_copy(update={
            "navigation_history": [*success.navigation_history, retained_path, *blocked],
            "attempted_source_ids": ("src_profile", "src_profile", "nav_src_after_request"),
        })

    install(run_exploration=exploration)
    result = run_pipeline(v02_fixtures["SUBJECT"])
    assert len(result.navigation_history) == 4
    assert result.summary.visited_page_count == 2
    assert "attempted_source_ids" not in result.model_dump()


@pytest.mark.parametrize("changes_seed", [True, False])
def test_seed_url_provenance_preserves_valid_redirects(changes_seed, install, v02_fixtures):
    final_url = "https://lab.example.org/redirected"
    responses = v02_fixtures["stage_responses"]

    def exploration(request):
        response = responses(request.request_id)[1]
        seed_url = final_url if changes_seed else request.search_results[0].url
        entry = response.navigation_history[0].model_copy(update={"url": seed_url, "final_url": final_url})
        document = replace(response.documents[0], original_url=seed_url, final_url=final_url)
        return response.model_copy(update={"navigation_history": [entry], "documents": (document,)})

    def profiling(request):
        response = responses(request.request_id)[2]
        source = response.sources[0].model_copy(update={"url": request.documents[0].final_url})
        return response.model_copy(update={"sources": [source]})

    calls = install(run_exploration=exploration, run_profiling=profiling)
    if changes_seed:
        with pytest.raises(ValueError, match="Seed navigation URL"):
            run_pipeline(v02_fixtures["SUBJECT"])
        assert calls[-1][0] == "run_exploration"
    else:
        result = run_pipeline(v02_fixtures["SUBJECT"])
        assert result.status == "success"
        assert result.navigation_history[0].url == result.discovered_sources[0].url
        assert result.navigation_history[0].final_url == result.sources[0].url == final_url
        assert result.summary.visited_page_count == 1


@pytest.mark.parametrize("identity_status,processing_status", [
    ("uncertain", "success"), ("rejected", "rejected"), ("confirmed", "success"),
    (None, "success"),
])
def test_profiling_zero_exposures_requires_a_completed_decision(
    identity_status, processing_status, install, v02_fixtures,
):
    def profiling(request):
        document = request.documents[0]
        source = Source(source_id=document.source_id, url=document.final_url,
                        processing_status=processing_status, identity_status=identity_status)
        return ProfilingResponse(schema_version="v0.2", request_id=request.request_id,
                                 status="success", sources=[source])

    install(run_profiling=profiling)
    if identity_status is None:
        with pytest.raises(ValueError, match="complete identity decisions"):
            run_pipeline(v02_fixtures["SUBJECT"])
    else:
        result = run_pipeline(v02_fixtures["SUBJECT"])
        assert result.status == "success"
        assert result.stages.analysis == StageStatus.NOT_STARTED
        assert result.sources[0].identity_status == identity_status
        assert result.exposures == []


@pytest.mark.parametrize("status,reported", [("success", False), ("partial_success", False), ("partial_success", True)])
def test_profiling_cannot_silently_drop_an_acquired_document(status, reported, install, v02_fixtures):
    responses = v02_fixtures["stage_responses"]
    other_id = "nav_src_other"
    other_url = "https://lab.example.org/other"

    def exploration(request):
        response = responses(request.request_id)[1]
        entry = NavigationEntry(
            navigation_id="nav_other", source_id=other_id, root_source_id="src_profile",
            parent_source_id="src_profile", depth=1, status="success", url=other_url, final_url=other_url,
        )
        document = replace(response.documents[0], source_id=other_id, original_url=other_url, final_url=other_url)
        return response.model_copy(update={
            "navigation_history": [*response.navigation_history, entry],
            "documents": (*response.documents, document),
            "attempted_source_ids": (*response.attempted_source_ids, other_id),
        })

    def profiling(request):
        if status == "success":
            return ProfilingResponse(schema_version="v0.2", request_id=request.request_id, status=status)
        response = responses(request.request_id)[2]
        error = ErrorDetail(code="MOCK_FAILURE", message="Processing failed.",
                            retryable=True, source_id=other_id if reported else None)
        return response.model_copy(update={"status": status, "errors": [error]})

    replacements = {"run_profiling": profiling}
    if status == "partial_success":
        replacements["run_exploration"] = exploration
    calls = install(**replacements)
    if not reported:
        with pytest.raises(ValueError, match="omitted processing results"):
            run_pipeline(v02_fixtures["SUBJECT"])
        assert calls[-1][0] == "run_profiling"
    else:
        result = run_pipeline(v02_fixtures["SUBJECT"])
        assert result.status == "partial_success"
        assert result.stages.analysis == StageStatus.SUCCESS
        assert result.errors[0].source_id == other_id


@pytest.mark.parametrize("violation", ["request_id", "root", "attempt", "source", "analysis"])
def test_invalid_stage_responses_never_advance(install, v02_fixtures, violation):
    responses = v02_fixtures["stage_responses"]
    if violation in {"request_id", "root", "attempt"}:
        stage = "run_exploration"

        def broken(request):
            response = responses(request.request_id)[1]
            if violation == "request_id":
                return response.model_copy(update={"request_id": "req_other"})
            if violation == "attempt":
                return response.model_copy(update={"attempted_source_ids": ("nav_src_missing",)})
            entry = response.navigation_history[0].model_copy(update={
                "source_id": "src_other", "root_source_id": "src_other",
            })
            document = replace(response.documents[0], source_id="src_other")
            return response.model_copy(update={
                "navigation_history": [entry], "documents": (document,), "attempted_source_ids": ("src_other",),
            })
    elif violation == "source":
        stage = "run_profiling"

        def broken(request):
            response = responses(request.request_id)[2]
            return response.model_copy(update={
                "sources": [response.sources[0].model_copy(update={"url": "https://lab.example.org/wrong"})],
            })
    else:
        stage = "run_analysis"

        def broken(request):
            return AnalysisResponse(
                schema_version="v0.2", request_id=request.request_id, status="success",
                personal_profile={"name": [{"label": "Name", "value": "Sample", "exposure_ids": ["exp_wrong"]}]},
            )

    calls = install(**{stage: broken})
    with pytest.raises((ValidationError, ValueError)):
        run_pipeline(v02_fixtures["SUBJECT"])
    assert calls[-1][0] == stage


def test_downstream_mutation_does_not_change_published_upstream_result(install, v02_fixtures):
    def analysis(request):
        request.subject.name = "Mutated"
        request.exposures[0].value = "Mutated"
        return v02_fixtures["stage_responses"](request.request_id)[3]
    install(run_analysis=analysis)
    subject = v02_fixtures["SUBJECT"]
    result = run_pipeline(subject)
    assert result.subject.name == subject.name == "Sample Researcher"
    assert result.exposures[0].value == "Example University"


def test_unconnected_pipeline_raises_explicitly(v02_fixtures):
    with pytest.raises(RuntimeError, match="No v0.2 module connected for SearchRequest"):
        run_pipeline(v02_fixtures["SUBJECT"])


@pytest.mark.parametrize("attempted", [False, True])
def test_fetch_failure_counts_only_explicit_http_attempts(attempted, install, v02_fixtures):
    def exploration(request):
        seed = v02_fixtures["stage_responses"](request.request_id)[1].navigation_history[0]
        entry = seed.model_copy(update={"status": "fetch_failed", "final_url": None})
        return ExplorationResult(
            schema_version="v0.2", request_id=request.request_id, status="failed",
            navigation_history=[entry], attempted_source_ids=(seed.source_id,) if attempted else (),
        )

    calls = install(run_exploration=exploration)
    result = run_pipeline(v02_fixtures["SUBJECT"])
    assert [name for name, _ in calls] == ["run_search", "run_exploration"]
    assert result.status == "failed"
    assert result.summary.visited_page_count == int(attempted)


@pytest.mark.parametrize("field,types", [
    ("phishing_risk_scenarios", ["affiliation", "contact"]),
    ("security_recommendations", ["contact"]),
    ("security_recommendations", []),
])
def test_analysis_exposure_types_are_validated_against_the_profiling_output(
    field, types, install, v02_fixtures,
):
    def analysis(request):
        response = v02_fixtures["stage_responses"](request.request_id)[3]
        item = getattr(response, field)[0].model_copy(update={"exposure_types": types})
        return response.model_copy(update={field: [item]})

    install(run_analysis=analysis)
    if types:
        with pytest.raises(ValueError, match="undiscovered exposure type"):
            run_pipeline(v02_fixtures["SUBJECT"])
    else:
        result = run_pipeline(v02_fixtures["SUBJECT"])
        assert result.security_recommendations[0].exposure_types == []
