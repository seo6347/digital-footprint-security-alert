"""Module A 전체 검색 흐름의 단위 테스트."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from dfsa.contracts.search import SearchRequest, SearchResponse
from dfsa.modules.search import runner
from dfsa.modules.search.provider import (
    ProviderResult,
    SearchProviderError,
)


@pytest.fixture
def request_model():
    return SearchRequest(
        schema_version="v0.1",
        request_id="req_001",
        subject={
            "name": "홍길동",
            "organization": "숭실대학교",
            "email": "hong@ssu.ac.kr",
        },
    )


@pytest.fixture
def provider_mock(monkeypatch):
    """실제 Provider 생성과 네트워크 호출을 모두 차단한다."""
    provider = Mock()
    provider.name = "serpapi"

    # 각 테스트에서 검색어별 반환값 또는 예외를 설정한다.
    provider.search.side_effect = [[], []]

    constructor = Mock(return_value=provider)
    constructor.name = "serpapi"

    monkeypatch.setattr(
        runner,
        "SerpApiProvider",
        constructor,
    )

    return provider


def make_result(
    url="https://example.com/profile",
    *,
    title="숭실대학교 홍길동",
    snippet="연구실 구성원 소개",
    rank=1,
):
    return ProviderResult(
        url=url,
        title=title,
        snippet=snippet,
        provider_rank=rank,
    )


def make_error():
    return SearchProviderError(
        "SEARCH_TIMEOUT",
        "검색 요청 시간이 초과되었다.",
        retryable=True,
    )


def test_successful_search(request_model, provider_mock):
    provider_mock.search.side_effect = [
        [make_result()],
        [
            make_result(
                "https://example.com/contact",
                title="연락처",
                snippet="hong@ssu.ac.kr",
            )
        ],
    ]

    response = runner.run_search(request_model)

    assert isinstance(response, SearchResponse)
    assert response.status == "success"
    assert response.errors == []
    assert len(response.queries) == 2
    assert len(response.results) == 2

    assert all(
        query.status == "success"
        for query in response.queries
    )
    assert all(
        result.relevance.status == "candidate"
        for result in response.results
    )


def test_queries_are_executed_in_order(request_model, provider_mock):
    response = runner.run_search(request_model)

    assert [
        call.args[0]
        for call in provider_mock.search.call_args_list
    ] == [
        '"홍길동" "숭실대학교"',
        '"hong@ssu.ac.kr"',
    ]

    assert [
        (query.query_id, query.text, query.provider)
        for query in response.queries
    ] == [
        (
            "q_001",
            '"홍길동" "숭실대학교"',
            "serpapi",
        ),
        (
            "q_002",
            '"hong@ssu.ac.kr"',
            "serpapi",
        ),
    ]


def test_empty_results_are_success(request_model, provider_mock):
    response = runner.run_search(request_model)

    assert response.status == "success"
    assert response.results == []
    assert response.errors == []
    assert len(response.queries) == 2
    assert all(
        query.status == "success"
        for query in response.queries
    )


def test_duplicate_urls_are_merged(request_model, provider_mock):
    provider_mock.search.side_effect = [
        [
            make_result(
                "HTTPS://Example.COM:443/profile#intro",
                rank=3,
            )
        ],
        [
            make_result(
                "https://example.com/profile#contact",
                rank=1,
            )
        ],
    ]

    response = runner.run_search(request_model)

    assert response.status == "success"
    assert len(response.results) == 1

    result = response.results[0]

    assert result.url == "HTTPS://Example.COM:443/profile#intro"
    assert result.normalized_url == "https://example.com/profile"
    assert [
        (discovery.query_id, discovery.provider_rank)
        for discovery in result.discovered_by
    ] == [
        ("q_001", 3),
        ("q_002", 1),
    ]


def test_top_k_is_applied_after_deduplication(
    request_model,
    provider_mock,
):
    request_model.options.top_k = 2

    provider_mock.search.side_effect = [
        [
            make_result("https://example.com/a"),
            make_result("https://example.com/a#section"),
        ],
        [
            make_result("https://example.com/b"),
            make_result("https://example.com/c"),
        ],
    ]

    response = runner.run_search(request_model)

    assert response.status == "success"
    assert [
        result.normalized_url
        for result in response.results
    ] == [
        "https://example.com/a",
        "https://example.com/b",
    ]

    assert [
        result.rank
        for result in response.results
    ] == [1, 2]

    assert [
        result.source_id
        for result in response.results
    ] == ["src_001", "src_002"]


def test_uncertain_results_are_preserved(
    request_model,
    provider_mock,
):
    provider_mock.search.side_effect = [
        [
            make_result(
                title="일반 뉴스",
                snippet="관련 없는 내용",
            )
        ],
        [],
    ]

    response = runner.run_search(request_model)

    assert response.status == "success"
    assert len(response.results) == 1
    assert response.results[0].relevance.status == "uncertain"
    assert response.results[0].relevance.reasons == [
        "insufficient_evidence",
    ]


@pytest.mark.parametrize("failed_index", [0, 1])
def test_one_query_failure_is_partial_success(
    request_model,
    provider_mock,
    failed_index,
):
    outcomes = [
        [make_result("https://example.com/a")],
        [make_result("https://example.com/b")],
    ]
    outcomes[failed_index] = make_error()

    provider_mock.search.side_effect = outcomes

    response = runner.run_search(request_model)

    assert response.status == "partial_success"
    assert provider_mock.search.call_count == 2
    assert len(response.results) == 1
    assert len(response.errors) == 1

    failed_query_id = f"q_{failed_index + 1:03d}"

    assert response.queries[failed_index].status == "failed"
    assert response.errors[0].query_id == failed_query_id
    assert response.errors[0].code == "SEARCH_TIMEOUT"
    assert response.errors[0].retryable is True


def test_successful_empty_query_and_failed_query_are_partial(
    request_model,
    provider_mock,
):
    provider_mock.search.side_effect = [
        [],
        make_error(),
    ]

    response = runner.run_search(request_model)

    assert response.status == "partial_success"
    assert response.results == []
    assert [
        query.status
        for query in response.queries
    ] == ["success", "failed"]
    assert len(response.errors) == 1


def test_all_query_failures_are_failed(
    request_model,
    provider_mock,
):
    provider_mock.search.side_effect = [
        make_error(),
        make_error(),
    ]

    response = runner.run_search(request_model)

    assert response.status == "failed"
    assert response.results == []
    assert provider_mock.search.call_count == 2
    assert len(response.errors) == 2

    assert all(
        query.status == "failed"
        for query in response.queries
    )

    assert [
        error.query_id
        for error in response.errors
    ] == ["q_001", "q_002"]


def test_provider_initialization_failure(
    request_model,
    provider_mock,
    monkeypatch,
):
    constructor = Mock(
        side_effect=SearchProviderError(
            "SEARCH_API_KEY_MISSING",
            "SERPAPI_API_KEY is not configured.",
            retryable=False,
        )
    )
    constructor.name = "serpapi"

    monkeypatch.setattr(
        runner,
        "SerpApiProvider",
        constructor,
    )

    response = runner.run_search(request_model)

    constructor.assert_called_once_with()
    provider_mock.search.assert_not_called()

    assert response.status == "failed"
    assert response.results == []
    assert len(response.queries) == 2
    assert len(response.errors) == 2

    assert all(
        query.status == "failed"
        for query in response.queries
    )
    assert all(
        error.code == "SEARCH_API_KEY_MISSING"
        and error.retryable is False
        for error in response.errors
    )
    assert [
        error.query_id
        for error in response.errors
    ] == ["q_001", "q_002"]


def test_invalid_url_is_skipped_and_recorded(
    request_model,
    provider_mock,
):
    provider_mock.search.side_effect = [
        [
            make_result("ftp://example.com/file"),
            make_result("https://example.com/profile"),
        ],
        [],
    ]

    response = runner.run_search(request_model)

    assert response.status == "partial_success"
    assert len(response.results) == 1
    assert response.results[0].url == "https://example.com/profile"
    assert response.results[0].rank == 1

    # 검색 호출은 성공했으며 URL 처리 오류는 별도로 기록한다.
    assert response.queries[0].status == "success"

    assert len(response.errors) == 1
    error = response.errors[0]

    assert error.code == "SEARCH_RESULT_URL_INVALID"
    assert error.query_id == "q_001"
    assert error.retryable is False


def test_all_invalid_urls_are_partial_success(
    request_model,
    provider_mock,
):
    provider_mock.search.side_effect = [
        [make_result("ftp://example.com/a")],
        [make_result("ftp://example.com/b")],
    ]

    response = runner.run_search(request_model)

    assert response.status == "partial_success"
    assert response.results == []
    assert len(response.errors) == 2
    assert all(
        query.status == "success"
        for query in response.queries
    )


def test_request_metadata_and_timestamp(
    request_model,
    provider_mock,
):
    response = runner.run_search(request_model)

    assert response.schema_version == request_model.schema_version
    assert response.request_id == request_model.request_id
    assert response.searched_at.tzinfo is not None
    assert response.searched_at.utcoffset() is not None

    data = response.model_dump(mode="json")

    assert data["searched_at"].endswith("Z")

    # JSON 형태로 변환한 결과도 기존 Contract를 만족해야 한다.
    validated = SearchResponse.model_validate(data)

    assert validated.request_id == request_model.request_id


def test_request_is_not_modified(request_model, provider_mock):
    original = deepcopy(request_model.model_dump())

    runner.run_search(request_model)

    assert request_model.model_dump() == original


def test_provider_results_are_not_modified(
    request_model,
    provider_mock,
):
    first_results = [
        make_result(
            "https://example.com/profile",
            title=None,
            snippet=None,
            rank=3,
        )
    ]
    second_results = [
        make_result(
            "https://example.com/profile#intro",
            title="숭실대학교 홍길동",
            snippet="hong@ssu.ac.kr",
            rank=1,
        )
    ]

    original_first = deepcopy(first_results)
    original_second = deepcopy(second_results)

    provider_mock.search.side_effect = [
        first_results,
        second_results,
    ]

    response = runner.run_search(request_model)

    assert response.status == "success"
    assert first_results == original_first
    assert second_results == original_second


def test_empty_query_list_fails_without_provider_call(
    request_model,
    provider_mock,
    monkeypatch,
):
    monkeypatch.setattr(
        runner,
        "build_queries",
        lambda subject: [],
    )

    response = runner.run_search(request_model)

    provider_mock.search.assert_not_called()

    assert response.status == "failed"
    assert response.queries == []
    assert response.results == []
    assert len(response.errors) == 1
    assert response.errors[0].code == "SEARCH_QUERY_EMPTY"


def test_query_builder_validation_error(
    request_model,
    provider_mock,
    monkeypatch,
):
    builder = Mock(
        side_effect=ValueError("Search term must not be empty.")
    )
    monkeypatch.setattr(
        runner,
        "build_queries",
        builder,
    )

    response = runner.run_search(request_model)

    provider_mock.search.assert_not_called()

    assert response.status == "failed"
    assert response.queries == []
    assert response.results == []
    assert len(response.errors) == 1
    assert response.errors[0].code == "SEARCH_INPUT_INVALID"
    assert response.errors[0].retryable is False
