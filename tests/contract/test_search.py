import json

import pytest
from pydantic import ValidationError

from dfsa.contracts.common import ErrorDetail
from dfsa.contracts.search import QueryExecution, SearchOptions, SearchRequest, SearchResponse


def test_search_request_defaults(subject_data):
    request = SearchRequest(schema_version="v0.1", request_id="req_001", subject=subject_data)
    assert request.options.top_k == 10
    assert SearchOptions().top_k == 10


@pytest.mark.parametrize("top_k", [1, 20])
def test_top_k_boundaries(top_k):
    assert SearchOptions(top_k=top_k).top_k == top_k


@pytest.mark.parametrize("top_k", [0, 21, 1.5, True, "10"])
def test_invalid_top_k_rejected(top_k):
    with pytest.raises(ValidationError):
        SearchOptions(top_k=top_k)


def test_query_cannot_be_partial_success(responses):
    query = responses["search_response"]["queries"][0]
    query["status"] = "partial_success"
    with pytest.raises(ValidationError):
        QueryExecution.model_validate(query)


def test_optional_search_fields(responses):
    data = responses["search_response"]
    result = data["results"][0]
    del result["title"]
    result["snippet"] = None
    del result["discovered_by"][0]["provider_rank"]
    model = SearchResponse.model_validate(data)
    assert model.results[0].title is None
    assert model.results[0].snippet is None
    assert model.results[0].discovered_by[0].provider_rank is None


def test_searched_at_requires_timezone(responses):
    data = responses["search_response"]
    data["searched_at"] = "2026-10-30T08:00:00"
    with pytest.raises(ValidationError):
        SearchResponse.model_validate(data)


def test_searched_at_serializes_as_utc(responses):
    data = responses["search_response"]
    data["searched_at"] = "2026-10-30T17:00:00+09:00"
    model = SearchResponse.model_validate(data)
    assert model.model_dump(mode="json")["searched_at"] == "2026-10-30T08:00:00Z"
    assert json.loads(model.model_dump_json())["searched_at"] == "2026-10-30T08:00:00Z"


def test_default_lists_are_independent():
    data = {"schema_version": "v0.1", "request_id": "req_001", "status": "success",
            "searched_at": "2026-10-30T08:00:00Z"}
    first, second = SearchResponse(**data), SearchResponse(**data)
    first.errors.append(ErrorDetail(code="ERROR", message="Failure", retryable=False))
    assert second.errors == []
