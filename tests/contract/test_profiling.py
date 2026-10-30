import pytest
from pydantic import ValidationError

from dfsa.contracts.profiling import Exposure, ProfilingRequest, ProfilingResponse, Source
from dfsa.contracts.risk import RiskRequest


def test_profiling_request_uses_search_results(subject_data, responses):
    request = ProfilingRequest(
        schema_version="v0.1", request_id="req_001", subject=subject_data,
        search_results=responses["search_response"]["results"],
    )
    assert request.search_results[0].source_id == "src_001"
    with pytest.raises(ValidationError):
        ProfilingRequest(schema_version="v0.1", request_id="req_001", subject=subject_data)


@pytest.mark.parametrize("field", ["exposureId", "id", "subtype"])
def test_extra_exposure_fields_rejected(responses, field):
    data = responses["profiling_response"]["exposures"][0]
    data[field] = "unexpected"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Exposure.model_validate(data)


def test_invalid_exposure_type_rejected(responses):
    data = responses["profiling_response"]["exposures"][0]
    data["type"] = "location"
    with pytest.raises(ValidationError):
        Exposure.model_validate(data)


@pytest.mark.parametrize("omit", [True, False])
def test_exposure_requires_at_least_one_source(responses, omit):
    data = responses["profiling_response"]["exposures"][0]
    if omit:
        del data["sources"]
    else:
        data["sources"] = []
    with pytest.raises(ValidationError, match="sources"):
        Exposure.model_validate(data)


def test_relation_omitted_or_null(responses):
    data = responses["profiling_response"]["exposures"][0]
    assert Exposure.model_validate(data).relation is None
    del data["relation"]
    assert Exposure.model_validate(data).relation is None


@pytest.mark.parametrize("processing_status", ["fetch_failed", "parse_failed", "unsupported"])
def test_unprocessed_source_allows_null_identity(processing_status):
    data = {"source_id": "src_001", "url": "https://example.com/profile",
            "processing_status": processing_status}
    assert Source(**data).identity_status is None
    assert Source(**data, identity_status=None).identity_status is None


def test_profiling_response_does_not_return_subject(subject_data, responses):
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ProfilingResponse.model_validate({**responses["profiling_response"], "subject": subject_data})


def test_risk_request_has_no_collection_status(subject_data):
    data = {"schema_version": "v0.1", "request_id": "req_001", "subject": subject_data}
    assert RiskRequest(**data).exposures == []
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RiskRequest(**data, collection_status="success")
