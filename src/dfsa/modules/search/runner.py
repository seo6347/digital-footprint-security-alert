"""Module A의 검색 및 예비 관련성 판단 진입점."""

from datetime import datetime, timezone

from dfsa.contracts.common import ErrorDetail, ModuleStatus
from dfsa.contracts.search import (
    QueryExecution,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from dfsa.modules.search.deduplicator import (
    QuerySearchResults,
    deduplicate_results,
)
from dfsa.modules.search.normalizer import (
    URLNormalizationError,
    normalize_url,
)
from dfsa.modules.search.provider import (
    ProviderResult,
    SearchProviderError,
    SerpApiProvider,
)
from dfsa.modules.search.query_builder import build_queries
from dfsa.modules.search.relevance import assess_relevance


def _provider_error_detail(
    error: SearchProviderError,
    *,
    query_id: str | None = None,
) -> ErrorDetail:
    """Provider 오류를 공개 응답의 ErrorDetail로 변환한다."""
    return ErrorDetail(
        code=error.code,
        message=error.message,
        retryable=error.retryable,
        query_id=query_id,
    )


def run_search(request: SearchRequest) -> SearchResponse:
    """검색부터 중복 제거, 관련성 판단, 응답 생성까지 수행한다.

    입력 request는 변경하지 않는다.
    검색 결과가 0건인 정상 응답도 성공으로 처리한다.
    candidate는 동일인 확정을 의미하지 않는다.
    """
    queries: list[QueryExecution] = []
    query_results: list[QuerySearchResults] = []
    errors: list[ErrorDetail] = []

    def make_response(
        status: ModuleStatus,
        results: list[SearchResult] | None = None,
    ) -> SearchResponse:
        """현재까지의 실행 기록으로 응답을 생성한다."""
        return SearchResponse(
            schema_version=request.schema_version,
            request_id=request.request_id,
            status=status,
            searched_at=datetime.now(timezone.utc),
            queries=queries,
            results=results if results is not None else [],
            errors=errors,
        )

    # 공백뿐인 이름이나 소속은 검색어 생성 단계에서 거부한다.
    try:
        query_texts = build_queries(request.subject)
    except ValueError:
        errors.append(
            ErrorDetail(
                code="SEARCH_INPUT_INVALID",
                message="검색어에 사용할 이름 또는 소속이 비어 있다.",
                retryable=False,
            )
        )
        return make_response(ModuleStatus("failed"))

    if not query_texts:
        errors.append(
            ErrorDetail(
                code="SEARCH_QUERY_EMPTY",
                message="검색어가 생성되지 않았다.",
                retryable=False,
            )
        )
        return make_response(ModuleStatus("failed"))

    # query_id는 단일 응답 안에서 순서대로 부여한다.
    planned_queries = [
        (f"q_{index:03d}", text)
        for index, text in enumerate(query_texts, start=1)
    ]

    try:
        provider = SerpApiProvider()
    except SearchProviderError as exc:
        # API 키 누락 등으로 Provider를 초기화하지 못하면
        # 실행 예정이던 검색어를 모두 실패로 기록한다.
        for query_id, text in planned_queries:
            queries.append(
                QueryExecution(
                    query_id=query_id,
                    text=text,
                    provider=SerpApiProvider.name,
                    status="failed",
                )
            )
            errors.append(
                _provider_error_detail(exc, query_id=query_id)
            )

        return make_response(ModuleStatus("failed"))

    successful_query_count = 0

    for query_id, text in planned_queries:
        try:
            provider_results = provider.search(text)
        except SearchProviderError as exc:
            queries.append(
                QueryExecution(
                    query_id=query_id,
                    text=text,
                    provider=provider.name,
                    status="failed",
                )
            )
            errors.append(
                _provider_error_detail(exc, query_id=query_id)
            )
            continue

        # Query 상태는 검색 서비스 호출의 성공 여부를 나타낸다.
        # 이후 URL 처리 오류는 별도 오류로 기록한다.
        successful_query_count += 1

        queries.append(
            QueryExecution(
                query_id=query_id,
                text=text,
                provider=provider.name,
                status="success",
            )
        )

        valid_results: list[ProviderResult] = []

        for result in provider_results:
            try:
                normalize_url(result.url)
            except URLNormalizationError:
                errors.append(
                    ErrorDetail(
                        code="SEARCH_RESULT_URL_INVALID",
                        message=(
                            "URL을 정규화할 수 없어 "
                            "검색 결과 한 건을 제외했다."
                        ),
                        retryable=False,
                        query_id=query_id,
                    )
                )
                continue

            valid_results.append(result)

        query_results.append(
            QuerySearchResults(
                query_id=query_id,
                results=valid_results,
            )
        )

    if successful_query_count == 0:
        return make_response(ModuleStatus("failed"))

    # 위에서 검증한 URL들을 기준으로 중복을 제거한다.
    # 최초 발견 순서와 각 검색어의 발견 경로를 보존한다.
    merged_results = deduplicate_results(query_results)

    # 관련성 상태로 결과를 제외하지 않고 최초 발견 순서로 선택한다.
    selected_results = merged_results[: request.options.top_k]

    results: list[SearchResult] = []

    for rank, merged in enumerate(selected_results, start=1):
        relevance = assess_relevance(
            request.subject,
            url=merged.url,
            title=merged.title,
            snippet=merged.snippet,
        )

        results.append(
            SearchResult(
                source_id=f"src_{rank:03d}",
                url=merged.url,
                normalized_url=merged.normalized_url,
                title=merged.title,
                snippet=merged.snippet,
                rank=rank,
                relevance=relevance,
                discovered_by=merged.discovered_by,
            )
        )

    if errors:
        return make_response(
            ModuleStatus("partial_success"),
            results,
        )

    return make_response(ModuleStatus("success"), results)
