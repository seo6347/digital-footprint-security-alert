from unittest.mock import MagicMock, patch
import pytest

from dfsa.contracts.common import ModuleStatus, Subject
from dfsa.contracts.search import SearchOptions, SearchRequest
from dfsa.modules.search.provider import ProviderResult, SearchProviderError
from dfsa.modules.search.query_builder import build_queries
from dfsa.modules.search.relevance import assess_relevance
from dfsa.modules.search.runner import run_search


def test_build_queries_with_email_and_org_variants():
    """'숭실대학교' 입력 시 약어 '숭실대' 조합 및 이메일을 포함한 쿼리가 생성되는지 확인."""
    subject = Subject(
        name="서동균",
        organization="숭실대학교",
        email="donggyun@ssu.ac.kr",
    )
    queries = build_queries(subject)

    assert '"서동균" "숭실대학교"' in queries
    assert '"서동균" "숭실대"' in queries
    assert '"서동균" "숭실대" 연구실' in queries
    assert '"donggyun@ssu.ac.kr"' in queries


def test_build_queries_without_email():
    """email이 None인 경우 숭실대학교 및 숭실대 쿼리가 생성되고 이메일 쿼리는 생략된다."""
    subject = Subject(
        name="서동균",
        organization="숭실대학교",
        email=None,
    )
    queries = build_queries(subject)

    assert '"서동균" "숭실대학교"' in queries
    assert '"서동균" "숭실대"' in queries
    assert '"donggyun@ssu.ac.kr"' not in queries


def test_assess_relevance_short_org_name_match():
    """웹페이지에 '숭실대학교' 대신 '숭실대'로 적혀있어도 candidate로 정상 판단된다."""
    subject = Subject(name="서동균", organization="숭실대학교", email=None)

    rel = assess_relevance(
        subject,
        url="https://lab.ssu.ac.kr/members/seo-donggyun",
        title="숭실대 연구실 멤버 - 서동균",
        snippet="AI소프트웨어학부 서동균 연구원 프로필",
    )

    assert rel.status == "candidate"
    assert "name_match" in rel.reasons
    assert "organization_match" in rel.reasons


def test_assess_relevance_uncertain():
    """연관 정보가 부족한 경우 uncertain 상태와 insufficient_evidence 이유를 반환한다."""
    subject = Subject(name="서동균", organization="숭실대학교", email=None)

    rel = assess_relevance(
        subject,
        url="https://example.com/news/123",
        title="일반 뉴스 기사",
        snippet="내용 없음",
    )

    assert rel.status == "uncertain"
    assert "insufficient_evidence" in rel.reasons


@patch("dfsa.modules.search.runner.SerpApiProvider")
def test_run_search_success_with_results(mock_provider_cls):
    """정상적으로 검색 결과를 수집하여 candidate 검색 결과를 반환하는 케이스."""
    mock_provider = MagicMock()
    mock_provider_cls.return_value = mock_provider
    mock_provider.name = "serpapi"
    mock_provider.search.return_value = [
        ProviderResult(
            url="https://lab.ssu.ac.kr/member/donggyun",
            title="서동균 - 숭실대 연구실",
            snippet="숭실대 AI 연구실 서동균",
            provider_rank=1,
        )
    ]

    request = SearchRequest(
        schema_version="v0.2",
        request_id="req_001",
        subject=Subject(name="서동균", organization="숭실대학교", email=None),
        options=SearchOptions(top_k=5),
    )

    response = run_search(request)

    assert response.status == ModuleStatus("success")
    assert len(response.results) == 1
    assert response.results[0].url == "https://lab.ssu.ac.kr/member/donggyun"
    assert response.results[0].relevance.status == "candidate"


@patch("dfsa.modules.search.runner.SerpApiProvider")
def test_run_search_zero_results_is_success(mock_provider_cls):
    """v0.2 명세: 검색 조회는 성공했으나 결과가 0건인 경우 success 및 빈 리스트 반환."""
    mock_provider = MagicMock()
    mock_provider_cls.return_value = mock_provider
    mock_provider.name = "serpapi"
    mock_provider.search.return_value = []

    request = SearchRequest(
        schema_version="v0.2",
        request_id="req_002",
        subject=Subject(name="서동균", organization="존재하지않는학과", email=None),
        options=SearchOptions(top_k=5),
    )

    response = run_search(request)

    assert response.status == ModuleStatus("success")
    assert response.results == []
    assert len(response.errors) == 0


@patch("dfsa.modules.search.runner.SerpApiProvider")
def test_run_search_provider_failed(mock_provider_cls):
    """API 키 미설정 또는 네트워크 오류로 검색을 수행하지 못한 경우 failed 상태 반환."""
    mock_provider_cls.side_effect = SearchProviderError(
        code="SEARCH_API_KEY_MISSING",
        message="SERPAPI_API_KEY is not configured.",
        retryable=False,
    )

    request = SearchRequest(
        schema_version="v0.2",
        request_id="req_003",
        subject=Subject(name="서동균", organization="숭실대학교", email=None),
        options=SearchOptions(top_k=5),
    )

    response = run_search(request)

    assert response.status == ModuleStatus("failed")
    assert len(response.errors) > 0
    assert response.errors[0].code == "SEARCH_API_KEY_MISSING"


@patch("dfsa.modules.search.runner.build_queries")
def test_run_search_empty_input(mock_build_queries):
    """검색어 생성 실패(ValueError) 시 runner가 failed 상태와 SEARCH_INPUT_INVALID 오류를 반환한다."""
    mock_build_queries.side_effect = ValueError("Search term must not be empty.")

    request = SearchRequest(
        schema_version="v0.2",
        request_id="req_004",
        subject=Subject(name="서동균", organization="숭실대학교", email=None),
        options=SearchOptions(top_k=5),
    )

    response = run_search(request)

    assert response.status == ModuleStatus("failed")
    assert len(response.errors) > 0
    assert response.errors[0].code == "SEARCH_INPUT_INVALID"