"""Module A v0.2 검색 및 예비 관련성 판단 진입점."""

from datetime import datetime, timezone

from dfsa.contracts.common import ErrorDetail, ModuleStatus
from dfsa.contracts.search import (
    QueryExecution,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from dfsa.modules.search.deduplicator_v2 import (
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
from dfsa.modules.search.query_builder_v2 import build_queries_v2
from dfsa.modules.search.relevance_v2 import assess_relevance


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
    """v0.2 검색, 중복 제거, 관련성 판단 및 응답을 생성한다."""
    queries: list[QueryExecution] = []
    query_results: list[QuerySearchResults] = []
    errors: list[ErrorDetail] = []

    def make_response(
        status: ModuleStatus,
        results: list[SearchResult] | None = None,
    ) -> SearchResponse:
        return SearchResponse(
            schema_version=request.schema_version,
            request_id=request.request_id,
            status=status,
            searched_at=datetime.now(timezone.utc),
            queries=queries,
            results=results if results is not None else [],
            errors=errors,
        )

    try:
        query_texts = build_queries_v2(request.subject)
    except ValueError:
        errors.append(
            ErrorDetail(
                code="SEARCH_INPUT_INVALID",
                message="검색어에 사용할 이름 또는 소속이 비어 있다.",
                retryable=False,
            )
        )
        return make_response(ModuleStatus("failed"))

    planned_queries = [
        (f"q_{index:03d}", text)
        for index, text in enumerate(query_texts, start=1)
    ]

    try:
        provider = SerpApiProvider()
        provider_name = (
            provider.name
            if isinstance(getattr(provider, "name", None), str)
            else "serpapi"
        )
    except SearchProviderError as exc:
        for query_id, text in planned_queries:
            queries.append(
                QueryExecution(
                    query_id=query_id,
                    text=text,
                    input_fields=["name", "organization"],
                    provider="serpapi",
                    status="failed",
                )
            )
            errors.append(_provider_error_detail(exc, query_id=query_id))

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
                    input_fields=["name", "organization"],
                    provider=provider_name,
                    status="failed",
                )
            )
            errors.append(_provider_error_detail(exc, query_id=query_id))
            continue

        successful_query_count += 1
        queries.append(
            QueryExecution(
                query_id=query_id,
                text=text,
                input_fields=["name", "organization"],
                provider=provider_name,
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
                            "URL을 정규화할 수 없어 검색 결과 한 건을 제외했다."
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

    merged_results = deduplicate_results(query_results)
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
        if not results:
            return make_response(ModuleStatus("failed"), results)
        return make_response(ModuleStatus("partial_success"), results)

    return make_response(ModuleStatus("success"), results)