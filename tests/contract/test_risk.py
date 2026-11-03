import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dfsa.contracts import DFSAResult, RiskResponse
from dfsa.contracts.risk import RiskPath


@pytest.mark.parametrize("status", ["candidate", "supported"])
@pytest.mark.parametrize("model", [RiskPath, RiskResponse, DFSAResult])
def test_current_path_statuses_are_valid(status, model, responses):
    fixture = "dfsa_result" if model is DFSAResult else "risk_response"
    data = responses[fixture]
    data["risk_paths"][0]["path_status"] = status
    if model is RiskPath:
        data = data["risk_paths"][0]
    model.model_validate(data)


@pytest.mark.parametrize("status", ["unverified", "not_assessed"])
@pytest.mark.parametrize("model", [RiskPath, RiskResponse, DFSAResult])
def test_removed_path_statuses_are_rejected(status, model, responses):
    fixture = "dfsa_result" if model is DFSAResult else "risk_response"
    data = responses[fixture]
    data["risk_paths"][0]["path_status"] = status
    if model is RiskPath:
        data = data["risk_paths"][0]
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(data)
    assert any(
        error["loc"][-1] == "path_status" and error["type"] == "enum"
        for error in exc_info.value.errors()
    )


@pytest.mark.parametrize("value", ["UNKNOWN", "NOT_APPLICABLE"])
def test_evaluation_values_are_not_removed_with_path_statuses(value, responses):
    data = responses["risk_response"]["risk_paths"][0]
    data["evaluation"] = dict.fromkeys(data["evaluation"], value)
    path = RiskPath.model_validate(data)
    assert set(path.evaluation.model_dump(mode="json").values()) == {value}


def test_candidate_response_fixture():
    fixture = Path(__file__).parents[1] / "fixtures" / "risk_response_candidate.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    response = RiskResponse.model_validate(data)
    assert response.risk_paths[0].path_status.value == "candidate"
    assert json.loads(response.model_dump_json()) == data
