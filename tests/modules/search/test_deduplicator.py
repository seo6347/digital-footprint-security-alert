"""Unit tests for search result deduplication."""

from copy import deepcopy

import pytest

from dfsa.modules.search.deduplicator import (
    QuerySearchResults,
    deduplicate_results,
)
from dfsa.modules.search.normalizer import URLNormalizationError
from dfsa.modules.search.provider import ProviderResult


def make_result(
    url: str = "https://example.com/profile",
    *,
    title: str | None = "프로필",
    snippet: str | None = "연구실 구성원 소개",
    rank: int | None = 1,
) -> ProviderResult:
    """Create an internal provider result for testing."""
    return ProviderResult(
        url=url,
        title=title,
        snippet=snippet,
        provider_rank=rank,
    )


def discovery_pairs(result):
    """Extract query IDs and provider ranks for easy comparison."""
    return [
        (discovery.query_id, discovery.provider_rank)
        for discovery in result.discovered_by
    ]


def test_empty_input():
    assert deduplicate_results([]) == []


def test_query_with_no_results():
    queries = [
        QuerySearchResults(query_id="q_001", results=[]),
    ]

    assert deduplicate_results(queries) == []


def test_single_result():
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[make_result(rank=2)],
        ),
    ]

    results = deduplicate_results(queries)

    assert len(results) == 1

    result = results[0]
    assert result.url == "https://example.com/profile"
    assert result.normalized_url == "https://example.com/profile"
    assert result.title == "프로필"
    assert result.snippet == "연구실 구성원 소개"
    assert discovery_pairs(result) == [("q_001", 2)]


def test_same_url_across_queries_is_merged():
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[make_result(rank=2)],
        ),
        QuerySearchResults(
            query_id="q_002",
            results=[make_result(rank=1)],
        ),
    ]

    results = deduplicate_results(queries)

    assert len(results) == 1
    assert discovery_pairs(results[0]) == [
        ("q_001", 2),
        ("q_002", 1),
    ]


def test_normalized_equivalent_urls_are_merged():
    first_url = "HTTPS://Example.COM:443/profile#intro"
    second_url = "https://example.com/profile#members"

    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[make_result(first_url)],
        ),
        QuerySearchResults(
            query_id="q_002",
            results=[make_result(second_url)],
        ),
    ]

    results = deduplicate_results(queries)

    assert len(results) == 1
    assert results[0].url == first_url
    assert results[0].normalized_url == "https://example.com/profile"
    assert discovery_pairs(results[0]) == [
        ("q_001", 1),
        ("q_002", 1),
    ]


def test_first_discovery_order_is_preserved():
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[
                make_result("https://example.com/b"),
                make_result("https://example.com/a"),
            ],
        ),
        QuerySearchResults(
            query_id="q_002",
            results=[
                make_result("https://example.com/a"),
                make_result("https://example.com/c"),
            ],
        ),
    ]

    results = deduplicate_results(queries)

    assert [result.normalized_url for result in results] == [
        "https://example.com/b",
        "https://example.com/a",
        "https://example.com/c",
    ]


def test_first_nonempty_metadata_is_preserved():
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[
                make_result(
                    title="첫 번째 제목",
                    snippet="첫 번째 요약",
                )
            ],
        ),
        QuerySearchResults(
            query_id="q_002",
            results=[
                make_result(
                    title="두 번째 제목",
                    snippet="두 번째 요약",
                )
            ],
        ),
    ]

    result = deduplicate_results(queries)[0]

    assert result.title == "첫 번째 제목"
    assert result.snippet == "첫 번째 요약"


@pytest.mark.parametrize("missing_value", [None, "", "   "])
def test_missing_metadata_is_filled(missing_value):
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[
                make_result(
                    title=missing_value,
                    snippet=missing_value,
                )
            ],
        ),
        QuerySearchResults(
            query_id="q_002",
            results=[
                make_result(
                    title="추가된 제목",
                    snippet="추가된 요약",
                )
            ],
        ),
    ]

    result = deduplicate_results(queries)[0]

    assert result.title == "추가된 제목"
    assert result.snippet == "추가된 요약"


def test_metadata_fields_are_filled_independently():
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[
                make_result(
                    title="기존 제목",
                    snippet=None,
                )
            ],
        ),
        QuerySearchResults(
            query_id="q_002",
            results=[
                make_result(
                    title="새 제목",
                    snippet="새 요약",
                )
            ],
        ),
    ]

    result = deduplicate_results(queries)[0]

    assert result.title == "기존 제목"
    assert result.snippet == "새 요약"


@pytest.mark.parametrize("blank_value", [None, "", "   "])
def test_blank_metadata_becomes_none(blank_value):
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[
                make_result(
                    title=blank_value,
                    snippet=blank_value,
                )
            ],
        ),
    ]

    result = deduplicate_results(queries)[0]

    assert result.title is None
    assert result.snippet is None


@pytest.mark.parametrize(
    ("first_rank", "second_rank", "expected_rank"),
    [
        (5, 2, 2),
        (2, 5, 2),
        (2, 2, 2),
        (None, 3, 3),
        (3, None, 3),
        (None, None, None),
    ],
)
def test_same_query_keeps_one_discovery_with_best_rank(
    first_rank,
    second_rank,
    expected_rank,
):
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[
                make_result(rank=first_rank),
                make_result(rank=second_rank),
            ],
        ),
    ]

    results = deduplicate_results(queries)

    assert len(results) == 1
    assert discovery_pairs(results[0]) == [
        ("q_001", expected_rank),
    ]


def test_repeated_query_batches_merge_discovery():
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[make_result(rank=5)],
        ),
        QuerySearchResults(
            query_id="q_002",
            results=[make_result(rank=4)],
        ),
        QuerySearchResults(
            query_id="q_001",
            results=[make_result(rank=2)],
        ),
    ]

    result = deduplicate_results(queries)[0]

    assert discovery_pairs(result) == [
        ("q_001", 2),
        ("q_002", 4),
    ]


@pytest.mark.parametrize(
    ("first_url", "second_url"),
    [
        (
            "https://example.com/profile?id=1",
            "https://example.com/profile?id=2",
        ),
        (
            "https://example.com/Profile",
            "https://example.com/profile",
        ),
        (
            "https://example.com/profile",
            "https://example.com/profile/",
        ),
        (
            "http://example.com/profile",
            "https://example.com/profile",
        ),
    ],
)
def test_distinct_pages_are_not_merged(first_url, second_url):
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[
                make_result(first_url),
                make_result(second_url),
            ],
        ),
    ]

    results = deduplicate_results(queries)

    assert len(results) == 2


def test_input_is_not_modified():
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[
                make_result(
                    "HTTPS://Example.COM:443/profile#intro",
                    title=None,
                    snippet=None,
                    rank=5,
                )
            ],
        ),
        QuerySearchResults(
            query_id="q_002",
            results=[
                make_result(
                    "https://example.com/profile",
                    title="추가 제목",
                    snippet="추가 요약",
                    rank=1,
                )
            ],
        ),
    ]
    original = deepcopy(queries)

    deduplicate_results(queries)

    assert queries == original


def test_discovery_lists_are_independent():
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[
                make_result("https://example.com/a"),
                make_result("https://example.com/b"),
            ],
        ),
    ]

    results = deduplicate_results(queries)

    assert results[0].discovered_by is not results[1].discovered_by

    results[0].discovered_by.clear()

    assert discovery_pairs(results[1]) == [("q_001", 1)]


def test_separate_calls_return_independent_results():
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[make_result()],
        ),
    ]

    first = deduplicate_results(queries)
    second = deduplicate_results(queries)

    first[0].title = "변경된 제목"
    first[0].discovered_by.clear()

    assert second[0].title == "프로필"
    assert discovery_pairs(second[0]) == [("q_001", 1)]


def test_invalid_url_raises_instead_of_silently_skipping():
    queries = [
        QuerySearchResults(
            query_id="q_001",
            results=[
                make_result("https://example.com/valid"),
                make_result("not-a-valid-url"),
            ],
        ),
    ]

    with pytest.raises(URLNormalizationError):
        deduplicate_results(queries)
