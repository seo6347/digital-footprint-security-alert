
from runpy import run_path
from unittest.mock import patch

import pytest

from dfsa.contracts.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    PersonalProfile,
    ProfileItem,
)
from dfsa.contracts.common import Subject
from dfsa.contracts.profiling import Exposure

from dfsa.modules.risk.analysis import run_analysis


SUBJECT = Subject(
    name="Sample Researcher",
    organization="Example University",
)


def make_request(exposures=None):
    return AnalysisRequest(
        schema_version="v0.2",
        request_id="req_test",
        subject=SUBJECT,
        exposures=exposures or [],
    )


def make_exposure(
    exposure_id,
    exposure_type,
    value,
    subtype=None,
):
    return Exposure(
        exposure_id=exposure_id,
        type=exposure_type,
        subtype=subtype,
        value=value,
        sources=[
            {
                "source_id": "src_test",
                "evidence": f"Synthetic evidence: {value}",
            }
        ],
    )


def sample_request():
    return make_request([
        make_exposure(
            "exp_001",
            "identity",
            "Sample Researcher",
            "name",
        ),
        make_exposure(
            "exp_002",
            "affiliation",
            "Example University",
            "university",
        ),
        make_exposure(
            "exp_003",
            "contact",
            "sample@example.org",
            "email",
        ),
    ])


def test_successful_analysis():
    result = run_analysis(sample_request())

    assert result.status == "success"
    assert result.errors == []

    assert result.personal_profile is not None
    assert result.personal_profile.name
    assert result.personal_profile.university
    assert result.personal_profile.contact

    assert len(result.relationship_graph.nodes) == 2
    assert len(result.relationship_graph.edges) == 1

    assert len(result.phishing_risk_scenarios) == 3
    assert len(result.security_recommendations) == 4


def test_empty_exposures():
    result = run_analysis(make_request())

    assert result.status == "success"

    assert all(
        not items
        for items in
        result.personal_profile.model_dump().values()
    )

    assert result.relationship_graph.nodes == []
    assert result.relationship_graph.edges == []
    assert result.phishing_risk_scenarios == []

    assert len(result.security_recommendations) == 1


def test_request_metadata_preserved():
    request = sample_request()
    result = run_analysis(request)

    assert result.request_id == request.request_id
    assert result.schema_version == "v0.2"


def test_response_json_round_trip():
    result = run_analysis(sample_request())

    restored = AnalysisResponse.model_validate_json(
        result.model_dump_json()
    )

    assert restored == result


@pytest.mark.parametrize(
    "function_name,error_code",
    [
        (
            "build_personal_profile",
            "PROFILE_GENERATION_ERROR",
        ),
        (
            "build_relationship_graph",
            "GRAPH_GENERATION_ERROR",
        ),
        (
            "build_phishing_risk_scenarios",
            "SCENARIO_GENERATION_ERROR",
        ),
        (
            "build_security_recommendations",
            "RECOMMENDATION_GENERATION_ERROR",
        ),
    ],
)
def test_partial_success(function_name, error_code):
    target = (
        "dfsa.modules.risk.analysis."
        + function_name
    )

    with patch(
        target,
        side_effect=RuntimeError("Private error detail"),
    ):
        result = run_analysis(sample_request())

    assert result.status == "partial_success"
    assert len(result.errors) == 1
    assert result.errors[0].code == error_code

    assert "Private error detail" not in (
        result.model_dump_json()
    )


def test_all_features_failed():
    module = "dfsa.modules.risk.analysis"

    with (
        patch(
            module + ".build_personal_profile",
            side_effect=RuntimeError(),
        ),
        patch(
            module + ".build_relationship_graph",
            side_effect=RuntimeError(),
        ),
        patch(
            module + ".build_phishing_risk_scenarios",
            side_effect=RuntimeError(),
        ),
        patch(
            module + ".build_security_recommendations",
            side_effect=RuntimeError(),
        ),
    ):
        result = run_analysis(sample_request())

    assert result.status == "failed"
    assert len(result.errors) == 4
    assert result.personal_profile is None
    assert result.relationship_graph.nodes == []
    assert result.phishing_risk_scenarios == []
    assert result.security_recommendations == []


def test_invalid_exposure_reference():
    invalid_profile = PersonalProfile(
        name=[
            ProfileItem(
                label="Name",
                value="Synthetic Value",
                exposure_ids=["exp_unknown"],
            )
        ]
    )

    with patch(
        "dfsa.modules.risk.analysis.build_personal_profile",
        return_value=invalid_profile,
    ):
        result = run_analysis(sample_request())

    assert result.status == "failed"
    assert result.personal_profile is None

    assert any(
        error.code == "ANALYSIS_REFERENCE_ERROR"
        for error in result.errors
    )


def test_existing_v02_fixture():
    fixtures = run_path(
        "tests/fixtures/v02/stages.py"
    )

    request = fixtures["stage_requests"]()[3]

    result = run_analysis(request)

    assert result.status == "success"
    assert result.personal_profile.university

    assert (
        result.personal_profile
        .university[0].value
        == "Example University"
    )

    assert len(result.relationship_graph.nodes) == 2
    assert len(result.relationship_graph.edges) == 1


def test_orchestrator_with_real_module_c():
    from dfsa.service import (
        orchestrator,
        run_pipeline,
    )

    fixtures = run_path(
        "tests/fixtures/v02/stages.py"
    )

    handlers = fixtures["mock_handlers"]("success")

    # A, Explorer, B: existing synthetic mocks
    # C: actual implemented analysis function
    handlers["run_analysis"] = run_analysis

    with patch.multiple(orchestrator, **handlers):
        result = run_pipeline(
            fixtures["SUBJECT"]
        )

    assert result.status == "success"
    assert result.stages.analysis == "success"
    assert result.personal_profile.university
    assert result.relationship_graph.edges
    assert result.phishing_risk_scenarios
    assert result.security_recommendations
