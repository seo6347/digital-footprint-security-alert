import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dfsa.contracts import (
    DFSAResult, ExecutionTime, ExplorationResult, NavigationEntry, ProfilingRequest,
    SearchRequest, SearchResponse, Subject,
)

UI_FIXTURES = Path(__file__).parents[1] / "fixtures" / "v02" / "ui"


@pytest.mark.parametrize("email", [{}, {"email": None}, {"email": "fixture@example.org"}])
def test_optional_email_and_trimmed_required_fields(email):
    subject = Subject(name=" Sample ", organization=" Example University ", **email)
    assert subject.name == "Sample"
    assert subject.organization == "Example University"
    assert subject.email == email.get("email")
    assert Subject.model_validate_json(subject.model_dump_json()) == subject


@pytest.mark.parametrize("updates", [{"name": " "}, {"organization": ""}, {"email": "invalid"}, {"extra": 1}])
def test_subject_rejects_invalid_fields(updates):
    with pytest.raises(ValidationError):
        Subject(**({"name": "Sample", "organization": "Example"} | updates))


@pytest.mark.parametrize("name,status", [
    ("success", "success"), ("partial_success", "partial_success"), ("failed", "failed"), ("zero", "success"),
])
def test_ui_payload_round_trip(name, status):
    payload = json.loads((UI_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    result = DFSAResult.model_validate(payload)
    assert result.status == status
    assert DFSAResult.model_validate_json(result.model_dump_json()) == result
    assert {"search_history", "discovered_sources", "navigation_history", "personal_profile",
            "relationship_graph", "phishing_risk_scenarios", "security_recommendations",
            "execution_time"} <= payload.keys()
    assert not {"documents", "html_text", "attempted_source_ids", "risk_paths"} & payload.keys()


@pytest.mark.parametrize("field", ["execution_time", "stages", "summary"])
def test_result_required_fields(field):
    data = json.loads((UI_FIXTURES / "success.json").read_text(encoding="utf-8"))
    del data[field]
    with pytest.raises(ValidationError, match=field):
        DFSAResult.model_validate(data)


@pytest.mark.parametrize("time", [-1, float("nan"), float("inf")])
def test_invalid_execution_time(time):
    with pytest.raises(ValidationError, match="total_ms"):
        ExecutionTime(total_ms=time, search_ms=None, exploration_ms=None, profiling_ms=None, analysis_ms=None)


@pytest.mark.parametrize("case", ["version", "risk_paths", "summary", "profile", "graph", "source", "evidence", "subtype"])
def test_public_result_rejects_invalid_contract(case):
    data = json.loads((UI_FIXTURES / "success.json").read_text(encoding="utf-8"))
    if case == "version":
        data["schema_version"] = "v0.1"
    elif case == "risk_paths":
        data["risk_paths"] = []
    elif case == "summary":
        data["summary"]["total_exposures"] = 0
    elif case == "profile":
        data["personal_profile"]["university"][0]["exposure_ids"] = ["exp_unknown"]
    elif case == "graph":
        data["relationship_graph"]["edges"][0]["target_node_id"] = "node_unknown"
    elif case == "source":
        data["sources"][0]["identity_status"] = "uncertain"
    elif case == "subtype":
        data["exposures"][0]["subtype"] = "name"
    else:
        data["exposures"][0]["sources"][0]["evidence"] = " "
    with pytest.raises(ValidationError):
        DFSAResult.model_validate(data)


def test_stage_fixtures_use_public_endpoints_and_share_document(v02_fixtures):
    requests = v02_fixtures["stage_requests"]()
    responses = v02_fixtures["stage_responses"]()
    assert all(value.__class__.model_validate(value) == value for value in (*requests, *responses))
    assert requests[2].documents == responses[1].documents
    with pytest.raises(ValidationError, match="documents"):
        ProfilingRequest(schema_version="v0.2", request_id="req_fixture", subject=requests[0].subject)
    assert SearchRequest.model_validate(requests[0]).options.top_k == 10


def test_search_reference_and_status_validation(v02_fixtures):
    search = v02_fixtures["stage_responses"]()[0]
    with pytest.raises(ValidationError, match="recorded query"):
        SearchResponse.model_validate(search.model_copy(update={"queries": []}))
    with pytest.raises(ValidationError, match="Search status"):
        SearchResponse.model_validate(search.model_copy(update={"status": "failed"}))


def test_explorer_rejects_attempts_to_unrecorded_or_skipped_sources(v02_fixtures):
    exploration = v02_fixtures["stage_responses"]()[1]
    skipped = NavigationEntry(
        navigation_id="nav_skipped", source_id="nav_src_skipped", root_source_id="src_profile",
        parent_source_id="src_profile", status="skipped", depth=1, url="https://lab.example.org/other",
    )
    for invalid_id in ("nav_src_missing", skipped.source_id):
        candidate = exploration.model_copy(update={
            "navigation_history": [*exploration.navigation_history, skipped],
            "attempted_source_ids": ("src_profile", invalid_id),
        })
        with pytest.raises(ValidationError, match="Attempted source IDs"):
            ExplorationResult.model_validate(candidate)
    with pytest.raises(ValidationError, match="Acquired documents must reference attempted sources"):
        ExplorationResult.model_validate(exploration.model_copy(update={"attempted_source_ids": ()}))


@pytest.mark.parametrize("navigation_status", ["fetch_failed", "parse_failed", "unsupported"])
def test_explorer_technical_failures_are_not_normal_zero(navigation_status, v02_fixtures):
    exploration = v02_fixtures["stage_responses"]()[1]
    seed = exploration.navigation_history[0]
    failed_page = seed.model_copy(update={"status": navigation_status, "final_url": None})
    failed = exploration.model_copy(update={"documents": (), "navigation_history": [failed_page]})
    with pytest.raises(ValidationError, match="Exploration status"):
        ExplorationResult.model_validate(failed)
    assert ExplorationResult.model_validate(failed.model_copy(update={"status": "failed"})).errors == []

    failed_child = NavigationEntry(
        navigation_id="nav_failed_child", source_id="nav_src_failed", parent_source_id=seed.source_id,
        root_source_id=seed.source_id, depth=1, url="https://lab.example.org/child",
        status=navigation_status,
    )
    partial = exploration.model_copy(update={
        "status": "partial_success",
        "navigation_history": [seed, failed_child],
        "attempted_source_ids": (seed.source_id, failed_child.source_id),
    })
    assert ExplorationResult.model_validate(partial).status == "partial_success"


@pytest.mark.parametrize("navigation_status", ["blocked", "skipped"])
def test_explorer_policy_exclusions_remain_normal_zero(navigation_status, v02_fixtures):
    seed = v02_fixtures["stage_responses"]()[1].navigation_history[0]
    result = ExplorationResult(
        schema_version="v0.2", request_id="req_fixture", status="success",
        navigation_history=[seed.model_copy(update={"status": navigation_status, "final_url": None})],
    )
    assert result.documents == ()
    assert result.attempted_source_ids == ()


@pytest.mark.parametrize("empty_stage", ["search", "exploration", "profiling"])
def test_public_result_rejects_running_a_stage_without_input(empty_stage):
    zero = json.loads((UI_FIXTURES / "zero.json").read_text(encoding="utf-8"))
    success = json.loads((UI_FIXTURES / "success.json").read_text(encoding="utf-8"))
    if empty_stage in {"exploration", "profiling"}:
        zero["discovered_sources"] = success["discovered_sources"]
        zero["summary"]["search_result_count"] = 1
    if empty_stage == "profiling":
        zero["navigation_history"] = success["navigation_history"]
        zero["sources"] = success["sources"]
        zero["summary"]["visited_page_count"] = 1
        zero["summary"]["confirmed_source_count"] = 1
    zero["stages"] = success["stages"]
    zero["execution_time"] = success["execution_time"]
    with pytest.raises(ValidationError, match="Stage execution must match"):
        DFSAResult.model_validate(zero)


def test_public_result_rejects_technical_exploration_failure_as_success():
    zero = json.loads((UI_FIXTURES / "zero.json").read_text(encoding="utf-8"))
    success = json.loads((UI_FIXTURES / "success.json").read_text(encoding="utf-8"))
    zero["discovered_sources"] = success["discovered_sources"]
    zero["summary"]["search_result_count"] = 1
    zero["summary"]["visited_page_count"] = 1
    zero["navigation_history"] = [success["navigation_history"][0] | {"status": "fetch_failed", "final_url": None}]
    zero["stages"]["exploration"] = "success"
    zero["execution_time"]["exploration_ms"] = 0
    with pytest.raises(ValidationError, match="Successful exploration cannot contain technical failures"):
        DFSAResult.model_validate(zero)

    zero["status"] = zero["stages"]["exploration"] = "failed"
    assert DFSAResult.model_validate(zero).stages.profiling == "not_started"
