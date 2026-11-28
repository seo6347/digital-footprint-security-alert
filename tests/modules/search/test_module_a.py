from unittest.mock import MagicMock, patch
import pytest

from dfsa.contracts.common import ModuleStatus, Subject
from dfsa.contracts.search import SearchOptions, SearchRequest
from dfsa.modules.search.provider import ProviderResult, SearchProviderError
from dfsa.modules.search.query_builder_v2 import build_queries_v2
from dfsa.modules.search.relevance_v2 import assess_relevance
from dfsa.modules.search.runner_v2 import run_search_v2


def test_build_queries_v2_spec_p0():
    """v0.2 명세 §5.2 규격: 이름 + 공백 + 소속 단일 검색어가 생성되는지 확인."""
    subject = Subject(
        name="김철수",
        organization="한국대학교",
        email="chulsoo@example.com",
    )
    queries = build_queries_v2(subject)

    assert len(queries) == 1
    assert queries[0] == "김철수 한국대학교"


def test_assess_relevance_synthetic_candidate():
    """합성 데이터를 통한 예비 관련성 candidate 판단 검증."""
    subject = Subject(name="김철수", organization="한국대학교", email=None)

    rel = assess_relevance(
        subject,
        url="https://lab.example.ac.kr/members/chulsoo",
        title="한국대학교 연구실 멤버 - 김철수",
        snippet="컴퓨터공학과 김철수 연구원 프로필",
    )

    assert rel.status == "candidate"
    assert "name_match" in rel.reasons
    assert "organization_match" in rel.reasons


def test_assess_relevance_uncertain():
    """연관 정보가 부족한 경우 uncertain 상태와 insufficient_evidence 이유를 반환한다."""
    subject = Subject(name="김철수", organization="한국대학교", email=None)

    rel = assess_relevance(
        subject,
        url="https://example.com/news/123",
        title="일반 뉴스 기사",
        snippet="내용 없음",
    )

    assert rel.status == "uncertain"
    assert "insufficient_evidence" in rel.reasons


@patch("dfsa.modules.search.runner_v2.SerpApiProvider")
def test_run_search_v2_success_with_results(mock_provider_cls):
    """v0.2 Runner 정상 수집 전체 흐름 검증."""
    mock_provider = MagicMock()
    mock_provider_cls.return_value = mock_provider
    mock_provider.name = "serpapi"
    mock_provider.search.return_value = [
        ProviderResult(
            url="https://lab.example.ac.kr/member/chulsoo",
            title="김철수 - 한국대학교 연구실",
            snippet="한국대 연구실 김철수",
            provider_rank=1,
        )
    ]

    request = SearchRequest(
        schema_version="v0.2",
        request_id="req_001",
        subject=Subject(name="김철수", organization="한국대학교", email=None),
        options=SearchOptions(top_k=5),
    )

    response = run_search_v2(request)

    assert response.status == ModuleStatus("success")
    assert len(response.results) == 1
    assert response.results[0].url == "https://lab.example.ac.kr/member/chulsoo"
    assert response.results[0].relevance.status == "candidate"


@patch("dfsa.modules.search.runner_v2.SerpApiProvider")
def test_run_search_v2_zero_results_is_success(mock_provider_cls):
    """v0.2 명세: 검색 조회는 성공했으나 결과가 0건인 경우 success 및 빈 리스트 반환."""
    mock_provider = MagicMock()
    mock_provider_cls.return_value = mock_provider
    mock_provider.name = "serpapi"
    mock_provider.search.return_value = []

    request = SearchRequest(
        schema_version="v0.2",
        request_id="req_002",
        subject=Subject(name="김철수", organization="존재하지않는학과", email=None),
        options=SearchOptions(top_k=5),
    )

    response = run_search_v2(request)

    assert response.status == ModuleStatus("success")
    assert response.results == []
    assert len(response.errors) == 0


@patch("dfsa.modules.search.runner_v2.SerpApiProvider")
def test_run_search_v2_error_without_results_is_failed(mock_provider_cls):
    """v0.2 계약 규격: 에러가 발생하고 유효 결과가 0건이면 partial_success가 아닌 failed 반환."""
    mock_provider = MagicMock()
    mock_provider_cls.return_value = mock_provider
    mock_provider.name = "serpapi"
    mock_provider.search.return_value = [
        ProviderResult(
            url="invalid-url-format",
            title="잘못된 링크",
            snippet="내용",
            provider_rank=1,
        )
    ]

    request = SearchRequest(
        schema_version="v0.2",
        request_id="req_003",
        subject=Subject(name="김철수", organization="한국대학교", email=None),
        options=SearchOptions(top_k=5),
    )

    response = run_search_v2(request)

    assert response.status == ModuleStatus("failed")
    assert response.results == []
    assert len(response.errors) > 0


@patch("dfsa.modules.search.runner_v2.SerpApiProvider")
def test_run_search_v2_provider_failed(mock_provider_cls):
    """API 키 미설정 또는 네트워크 오류로 검색을 수행하지 못한 경우 failed 상태 반환."""
    mock_provider_cls.side_effect = SearchProviderError(
        code="SEARCH_API_KEY_MISSING",
        message="SERPAPI_API_KEY is not configured.",
        retryable=False,
    )

    request = SearchRequest(
        schema_version="v0.2",
        request_id="req_004",
        subject=Subject(name="김철수", organization="한국대학교", email=None),
        options=SearchOptions(top_k=5),
    )

    response = run_search_v2(request)

    assert response.status == ModuleStatus("failed")
    assert len(response.errors) > 0
    assert response.errors[0].code == "SEARCH_API_KEY_MISSING"


@patch("dfsa.modules.search.runner_v2.build_queries_v2")
def test_run_search_v2_empty_input(mock_build_queries):
    """검색어 생성 실패(ValueError) 시 runner가 failed 상태와 SEARCH_INPUT_INVALID 오류를 반환한다."""
    mock_build_queries.side_effect = ValueError("Search term must not be empty.")

    request = SearchRequest(
        schema_version="v0.2",
        request_id="req_005",
        subject=Subject(name="김철수", organization="한국대학교", email=None),
        options=SearchOptions(top_k=5),
    )

    response = run_search_v2(request)

    assert response.status == ModuleStatus("failed")
    assert len(response.errors) > 0
    assert response.errors[0].code == "SEARCH_INPUT_INVALID"