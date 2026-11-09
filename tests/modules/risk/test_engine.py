
import pytest

from dfsa.contracts.common import (
    EvaluationValue,
    ExposureType,
    RiskPathStatus,
    Subject,
)
from dfsa.contracts.profiling import Exposure, ExposureSource
from dfsa.contracts.risk import RiskRequest, RiskResponse
from dfsa.modules.risk.engine import run_risk


def make_exposure(exposure_id, exposure_type):
    return Exposure(
        exposure_id=exposure_id,
        type=exposure_type,
        value="test value",
        sources=[
            ExposureSource(
                source_id="src_001",
                evidence="test evidence",
            )
        ],
    )


def make_request(exposures):
    return RiskRequest(
        schema_version="v0.1",
        request_id="req_001",
        subject=Subject(
            name="홍길동",
            organization="OO대학교",
            email="gildong@univ.ac.kr",
        ),
        exposures=exposures,
    )


def test_r01_risk_path():
    request = make_request([
        make_exposure("exp_001", ExposureType.RELATIONSHIP),
        make_exposure("exp_002", ExposureType.AFFILIATION),
    ])

    response = run_risk(request)

    assert isinstance(response, RiskResponse)
    assert response.status.value == "success"
    assert response.request_id == "req_001"
    assert len(response.risk_paths) == 1

    path = response.risk_paths[0]

    assert path.risk_path_id == "path_001"
    assert path.rule_id == "R01"
    assert path.path_status == RiskPathStatus.CANDIDATE
    assert path.exposure_ids == ["exp_001"]
    assert path.reason
    assert len(path.recommendations) >= 1


def test_multiple_risk_paths():
    request = make_request([
        make_exposure("exp_001", ExposureType.RELATIONSHIP),
        make_exposure("exp_002", ExposureType.AFFILIATION),
        make_exposure("exp_003", ExposureType.INTEREST),
        make_exposure("exp_004", ExposureType.TEMPORAL),
    ])

    response = run_risk(request)

    assert [path.rule_id for path in response.risk_paths] == [
        "R01", "R02", "R04"
    ]

    assert [path.risk_path_id for path in response.risk_paths] == [
        "path_001", "path_002", "path_003"
    ]

    assert response.summary.total_exposures == 4
    assert response.summary.total_paths == 3


def test_empty_exposures():
    response = run_risk(make_request([]))

    assert response.status.value == "success"
    assert response.risk_paths == []
    assert response.summary.total_exposures == 0
    assert response.summary.total_paths == 0
    assert response.errors == []


def test_no_matching_rule():
    request = make_request([
        make_exposure("exp_001", ExposureType.CONTACT)
    ])

    response = run_risk(request)

    assert response.risk_paths == []
    assert response.summary.total_exposures == 1
    assert response.summary.total_paths == 0


def test_evaluation_fields():
    request = make_request([
        make_exposure("exp_001", ExposureType.ACCOUNT)
    ])

    response = run_risk(request)
    evaluation = response.risk_paths[0].evaluation

    assert evaluation.searchability == EvaluationValue.UNKNOWN
    assert evaluation.cross_source_linkability == EvaluationValue.UNKNOWN
    assert evaluation.attack_utility == EvaluationValue.UNKNOWN
    assert evaluation.sensitivity == EvaluationValue.UNKNOWN
    assert evaluation.evidence_confidence == EvaluationValue.UNKNOWN


def test_response_contract_validation():
    request = make_request([
        make_exposure("exp_001", ExposureType.RELATIONSHIP)
    ])

    response = run_risk(request)

    # Public Contract에 맞게 직렬화한 후 다시 검증한다.
    data = response.model_dump(mode="json")
    validated = RiskResponse.model_validate(data)

    assert validated == response

