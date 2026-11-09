"""SerpApi Google search client for Module A.

This module only handles the search provider.
URL normalization, deduplication, relevance, and public response construction
are handled elsewhere.
"""

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SERPAPI_ENDPOINT = "https://serpapi.com/search.json"


@dataclass(frozen=True)
class ProviderResult:
    """Internal search result, not a public DFSA Contract."""

    url: str
    title: str | None
    snippet: str | None
    provider_rank: int | None


class SearchProviderError(Exception):
    """Provider failure that can later be converted to ErrorDetail."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class SerpApiProvider:
    """Fetch one Google search results page through SerpApi."""

    name = "serpapi"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = 60.0,
    ) -> None:
        key = api_key if api_key is not None else os.getenv(
            "SERPAPI_API_KEY"
        )

        if not isinstance(key, str) or not key.strip():
            raise SearchProviderError(
                "SEARCH_API_KEY_MISSING",
                "SERPAPI_API_KEY is not configured.",
                retryable=False,
            )

        if timeout <= 0:
            raise ValueError("timeout must be greater than zero.")

        self._api_key = key.strip()
        self._timeout = timeout

    def search(self, query: str) -> list[ProviderResult]:
        """Run one search request and return organic results.

        No automatic retries or pagination are performed.
        A successful search with no organic results returns an empty list.
        """
        if not isinstance(query, str) or not query.strip():
            raise SearchProviderError(
                "SEARCH_QUERY_INVALID",
                "Search query must not be empty.",
                retryable=False,
            )

        params = {
            "engine": "google",
            "q": query.strip(),
            "hl": "ko",
            "gl": "kr",
            "api_key": self._api_key,
        }

        request = Request(
            f"{SERPAPI_ENDPOINT}?{urlencode(params)}",
            headers={"Accept": "application/json"},
        )

        try:
            with urlopen(request, timeout=self._timeout) as response:
                raw_body = response.read()

        except HTTPError as exc:
            status = exc.code

            if status in (401, 403):
                code = "SEARCH_AUTH_ERROR"
                message = "SerpApi authentication or access was rejected."
                retryable = False

            elif status == 429:
                code = "SEARCH_LIMIT_ERROR"
                message = "SerpApi quota or rate limit was exceeded."
                retryable = True

            else:
                code = "SEARCH_HTTP_ERROR"
                message = f"SerpApi returned HTTP {status}."
                retryable = 500 <= status < 600

            # Do not expose the request URL, which contains the API key.
            raise SearchProviderError(
                code,
                message,
                retryable=retryable,
            ) from None

        except TimeoutError:
            raise SearchProviderError(
                "SEARCH_TIMEOUT",
                "SerpApi request timed out.",
                retryable=True,
            ) from None

        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                code = "SEARCH_TIMEOUT"
                message = "SerpApi request timed out."
            else:
                code = "SEARCH_NETWORK_ERROR"
                message = "Could not connect to SerpApi."

            raise SearchProviderError(
                code,
                message,
                retryable=True,
            ) from None

        try:
            data = json.loads(raw_body)
        except (ValueError, UnicodeError):
            raise SearchProviderError(
                "SEARCH_INVALID_RESPONSE",
                "SerpApi returned invalid JSON.",
                retryable=False,
            ) from None

        return self._parse_response(data)

    @staticmethod
    def _parse_response(data: object) -> list[ProviderResult]:
        """Validate provider response and extract organic results."""
        if not isinstance(data, dict):
            raise SearchProviderError(
                "SEARCH_INVALID_RESPONSE",
                "SerpApi response must be a JSON object.",
                retryable=False,
            )

        # Do not forward raw provider messages, which may contain
        # request details or sensitive information.
        if "error" in data:
            raise SearchProviderError(
                "SEARCH_API_ERROR",
                "SerpApi reported a search error.",
                retryable=False,
            )

        metadata = data.get("search_metadata")

        if (
            not isinstance(metadata, dict)
            or metadata.get("status") != "Success"
        ):
            raise SearchProviderError(
                "SEARCH_INVALID_RESPONSE",
                "SerpApi did not report a completed successful search.",
                retryable=False,
            )

        # SerpApi may omit organic_results when there are no results.
        # Accept that only when search information explicitly indicates
        # that the search returned no results.
        if "organic_results" not in data:
            information = data.get("search_information")
            state = (
                information.get("organic_results_state")
                if isinstance(information, dict)
                else None
            )
            total = (
                information.get("total_results")
                if isinstance(information, dict)
                else None
            )

            no_results = (
                isinstance(state, str)
                and "no results" in state.casefold()
            ) or (
                type(total) is int and total == 0
            )

            if no_results:
                return []

            raise SearchProviderError(
                "SEARCH_INVALID_RESPONSE",
                "SerpApi response is missing organic search results.",
                retryable=False,
            )

        items = data["organic_results"]

        if not isinstance(items, list):
            raise SearchProviderError(
                "SEARCH_INVALID_RESPONSE",
                "SerpApi organic_results must be a list.",
                retryable=False,
            )

        results = []

        for item in items:
            if not isinstance(item, dict):
                raise SearchProviderError(
                    "SEARCH_INVALID_RESPONSE",
                    "SerpApi search result must be an object.",
                    retryable=False,
                )

            url = item.get("link")
            title = item.get("title")
            snippet = item.get("snippet")
            rank = item.get("position")

            if not isinstance(url, str) or not url.strip():
                raise SearchProviderError(
                    "SEARCH_INVALID_RESPONSE",
                    "SerpApi search result is missing a valid link.",
                    retryable=False,
                )

            if title is not None and not isinstance(title, str):
                raise SearchProviderError(
                    "SEARCH_INVALID_RESPONSE",
                    "SerpApi result title must be a string or null.",
                    retryable=False,
                )

            if snippet is not None and not isinstance(snippet, str):
                raise SearchProviderError(
                    "SEARCH_INVALID_RESPONSE",
                    "SerpApi result snippet must be a string or null.",
                    retryable=False,
                )

            if rank is not None and (
                type(rank) is not int or rank < 1
            ):
                raise SearchProviderError(
                    "SEARCH_INVALID_RESPONSE",
                    "SerpApi result position must be a positive integer.",
                    retryable=False,
                )

            results.append(
                ProviderResult(
                    url=url.strip(),
                    title=title,
                    snippet=snippet,
                    provider_rank=rank,
                )
            )

        return results
