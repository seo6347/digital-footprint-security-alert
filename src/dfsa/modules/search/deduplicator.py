"""Merge search results while preserving query discovery records."""

from dataclasses import dataclass, field

from dfsa.contracts.search import DiscoveredBy
from dfsa.modules.search.normalizer import normalize_url
from dfsa.modules.search.provider import ProviderResult


@dataclass(frozen=True)
class QuerySearchResults:
    """Provider results belonging to one executed query."""

    query_id: str
    results: list[ProviderResult]


@dataclass
class MergedSearchResult:
    """Internal merged result before building a SearchResult."""

    url: str
    normalized_url: str
    title: str | None
    snippet: str | None
    discovered_by: list[DiscoveredBy] = field(default_factory=list)


def _has_text(value: str | None) -> bool:
    """Return whether an optional string contains non-whitespace text."""
    return value is not None and bool(value.strip())


def _merge_discovery(
    discoveries: list[DiscoveredBy],
    query_id: str,
    provider_rank: int | None,
) -> None:
    """Keep one discovery per query, preferring the best known rank."""
    for index, discovery in enumerate(discoveries):
        if discovery.query_id != query_id:
            continue

        current_rank = discovery.provider_rank

        if provider_rank is not None and (
            current_rank is None or provider_rank < current_rank
        ):
            discoveries[index] = DiscoveredBy(
                query_id=query_id,
                provider_rank=provider_rank,
            )

        return

    discoveries.append(
        DiscoveredBy(
            query_id=query_id,
            provider_rank=provider_rank,
        )
    )


def deduplicate_results(
    query_results: list[QuerySearchResults],
) -> list[MergedSearchResult]:
    """Merge results by normalized URL in first-discovery order.

    The input order determines which URL, title, and snippet are preferred.
    Input provider results are never modified.

    Raises:
        URLNormalizationError:
            An input URL cannot be normalized. Invalid URLs are not
            silently discarded.
    """
    merged_by_url: dict[str, MergedSearchResult] = {}

    for query_result in query_results:
        for result in query_result.results:
            normalized = normalize_url(result.url)
            merged = merged_by_url.get(normalized)

            if merged is None:
                merged = MergedSearchResult(
                    url=result.url,
                    normalized_url=normalized,
                    title=result.title if _has_text(result.title) else None,
                    snippet=(
                        result.snippet
                        if _has_text(result.snippet)
                        else None
                    ),
                )
                merged_by_url[normalized] = merged

            else:
                # Fill missing metadata without replacing an earlier
                # non-empty title or snippet.
                if not _has_text(merged.title) and _has_text(result.title):
                    merged.title = result.title

                if (
                    not _has_text(merged.snippet)
                    and _has_text(result.snippet)
                ):
                    merged.snippet = result.snippet

            _merge_discovery(
                discoveries=merged.discovered_by,
                query_id=query_result.query_id,
                provider_rank=result.provider_rank,
            )

    return list(merged_by_url.values())
