import json

import pytest
from pydantic import ValidationError

from dfsa.contracts import (
    DFSAResult, ProfilingRequest, ProfilingResponse, RiskRequest, RiskResponse,
    SearchRequest, SearchResponse,
)
from dfsa.contracts.common import StageStatus
from dfsa.contracts.profiling import Exposure, Source
from dfsa.contracts.risk import RiskPath
from dfsa.contracts.search import SearchResult


RESPONSES = [
    (SearchResponse, "search_response", ["queries", "results", "errors"]),
    (ProfilingResponse, "profiling_response", ["sources", "exposures", "errors"]),
    (RiskResponse, "risk_response", ["risk_paths", "errors"]),
    (DFSAResult, "dfsa_result", ["sources", "exposures", "risk_paths", "errors"]),
]


@pytest.mark.parametrize(("model", "fixture_name", "collections"), RESPONSES)
def test_valid_response_fixtures(model, fixture_name, collections, responses):
    original = responses[fixture_name]
    instance = model.model_validate(original)
    assert json.loads(instance.model_dump_json()) == original
    assert model.model_validate_json(instance.model_dump_json()) == instance


@pytest.mark.parametrize(("model", "fixture_name", "collections"), RESPONSES)
def test_response_collections_default_and_serialize(model, fixture_name, collections, responses):
    data = responses[fixture_name]
    for field in collections:
        del data[field]
    if "summary" in data:
        data["summary"] = dict.fromkeys(data["summary"], 0)
    if "stages" in data:
        data["stages"].update(profiling="not_started", risk_analysis="not_started")
    instance = model.model_validate(data)
    for payload in (instance.model_dump(mode="json"), json.loads(instance.model_dump_json())):
        assert all(payload[field] == [] for field in collections)


@pytest.mark.parametrize(("model", "fixture_name", "collections"), RESPONSES)
def test_all_responses_use_common_error(model, fixture_name, collections, responses):
    data = responses[fixture_name]
    error = {"code": "ERROR", "message": "Failure", "retryable": False}
    data["errors"] = [error]
    instance = model.model_validate(data)
    assert instance.errors[0].source_id is None
    assert instance.errors[0].query_id is None
    error["unexpected"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        model.model_validate(data)


@pytest.mark.parametrize(("model", "fixture_name", "collections"), RESPONSES)
def test_collections_are_lists_not_null(model, fixture_name, collections, responses):
    for field in collections:
        data = {**responses[fixture_name], field: None}
        with pytest.raises(ValidationError, match=field):
            model.model_validate(data)


@pytest.mark.parametrize(("model", "fixture_name", "collections"), RESPONSES)
@pytest.mark.parametrize("version", ["v0.2", "v1.0", None])
def test_wrong_response_version_rejected(model, fixture_name, collections, version, responses):
    data = {**responses[fixture_name], "schema_version": version}
    with pytest.raises(ValidationError, match="schema_version"):
        model.model_validate(data)


@pytest.mark.parametrize("model", [SearchRequest, ProfilingRequest, RiskRequest])
def test_request_version_rejected(model, subject_data):
    data = {"schema_version": "v0.2", "request_id": "req_001", "subject": subject_data}
    if model is ProfilingRequest:
        data["search_results"] = []
    with pytest.raises(ValidationError, match="schema_version"):
        model.model_validate(data)


@pytest.mark.parametrize(("model", "fixture_name", "collections"), RESPONSES)
@pytest.mark.parametrize("field", ["schema_version", "request_id", "status"])
def test_response_core_fields_required(model, fixture_name, collections, field, responses):
    data = responses[fixture_name]
    del data[field]
    with pytest.raises(ValidationError, match=field):
        model.model_validate(data)


@pytest.mark.parametrize(("model", "fixture_name"), [(RiskResponse, "risk_response"), (DFSAResult, "dfsa_result")])
def test_summary_required(model, fixture_name, responses):
    data = responses[fixture_name]
    del data["summary"]
    with pytest.raises(ValidationError, match="summary"):
        model.model_validate(data)
    data["summary"] = {}
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("field", ["stages", "search", "profiling", "risk_analysis"])
def test_stages_and_all_stage_fields_required(field, responses):
    data = responses["dfsa_result"]
    if field == "stages":
        del data["stages"]
    else:
        del data["stages"][field]
    with pytest.raises(ValidationError, match=field):
        DFSAResult.model_validate(data)


def test_not_started_is_stage_only(responses):
    data = responses["dfsa_result"]
    data["stages"]["risk_analysis"] = "not_started"
    assert DFSAResult.model_validate(data).stages.risk_analysis is StageStatus.NOT_STARTED
    data["status"] = "not_started"
    with pytest.raises(ValidationError):
        DFSAResult.model_validate(data)


@pytest.mark.parametrize("field", ["evaluation", "searchability", "cross_source_linkability",
                                    "attack_utility", "sensitivity", "evidence_confidence"])
def test_risk_evaluation_required(field, responses):
    data = responses["risk_response"]["risk_paths"][0]
    if field == "evaluation":
        del data["evaluation"]
    else:
        del data["evaluation"][field]
    with pytest.raises(ValidationError, match=field):
        RiskPath.model_validate(data)


def test_shared_models_reused(responses, subject_data):
    result = DFSAResult.model_validate(responses["dfsa_result"])
    profiling = ProfilingResponse.model_validate(responses["profiling_response"])
    risk = RiskResponse.model_validate(responses["risk_response"])
    request = RiskRequest(schema_version="v0.1", request_id="req_001", subject=subject_data,
                          exposures=profiling.exposures)
    assert type(result.sources[0]) is type(profiling.sources[0]) is Source
    assert type(result.exposures[0]) is type(request.exposures[0]) is Exposure
    assert type(result.risk_paths[0]) is type(risk.risk_paths[0]) is RiskPath
    assert ProfilingRequest.model_fields["search_results"].annotation == list[SearchResult]
