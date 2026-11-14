"""Unit tests for the SerpApi provider without real network calls."""

import json
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from dfsa.modules.search import provider as provider_module
from dfsa.modules.search.provider import (
    ProviderResult,
    SearchProviderError,
    SerpApiProvider,
)


@pytest.fixture
def mock_urlopen(monkeypatch):
    """Replace the network function used by provider.py."""
    mock = MagicMock()
    monkeypatch.setattr(provider_module, "urlopen", mock)
    return mock


@pytest.fixture
def client():
    return SerpApiProvider(
        api_key="test-secret-key",
        timeout=15.0,
    )


@pytest.fixture
def success_data():
    """Return fresh response data for each test."""
    return {
        "search_metadata": {
            "status": "Success",
        },
        "organic_results": [
            {
                "position": 2,
                "title": "숭실대학교 연구실",
                "link": "https://example.com/lab",
                "snippet": "연구실 구성원 소개",
            }
        ],
    }


def set_json_response(mock_urlopen, data):
    """Configure the mocked HTTP context manager."""
    response = mock_urlopen.return_value.__enter__.return_value
    response.read.return_value = json.dumps(data).encode("utf-8")


def test_search_returns_results(client, mock_urlopen, success_data):
    set_json_response(mock_urlopen, success_data)

    results = client.search('"홍길동" "숭실대학교"')

    assert results == [
        ProviderResult(
            url="https://example.com/lab",
            title="숭실대학교 연구실",
            snippet="연구실 구성원 소개",
            provider_rank=2,
        )
    ]


def test_search_sends_expected_parameters(
    client, mock_urlopen, success_data
):
    set_json_response(mock_urlopen, success_data)

    client.search('  "홍길동" "숭실대학교"  ')

    mock_urlopen.assert_called_once()
    args, kwargs = mock_urlopen.call_args
    request = args[0]

    url = urlparse(request.full_url)
    params = parse_qs(url.query)

    assert url.scheme == "https"
    assert url.netloc == "serpapi.com"
    assert url.path == "/search.json"
    assert params == {
        "engine": ["google"],
        "q": ['"홍길동" "숭실대학교"'],
        "hl": ["ko"],
        "gl": ["kr"],
        "api_key": ["test-secret-key"],
    }
    assert kwargs["timeout"] == 15.0
    assert request.get_header("Accept") == "application/json"


def test_provider_reads_environment_key(monkeypatch, mock_urlopen):
    monkeypatch.setenv("SERPAPI_API_KEY", "environment-key")
    set_json_response(
        mock_urlopen,
        {
            "search_metadata": {"status": "Success"},
            "organic_results": [],
        },
    )

    client = SerpApiProvider()
    client.search("숭실대학교")

    request = mock_urlopen.call_args.args[0]
    params = parse_qs(urlparse(request.full_url).query)

    assert params["api_key"] == ["environment-key"]


def test_explicit_key_overrides_environment(
    monkeypatch, mock_urlopen
):
    monkeypatch.setenv("SERPAPI_API_KEY", "environment-key")
    set_json_response(
        mock_urlopen,
        {
            "search_metadata": {"status": "Success"},
            "organic_results": [],
        },
    )

    client = SerpApiProvider(api_key="explicit-key")
    client.search("숭실대학교")

    request = mock_urlopen.call_args.args[0]
    params = parse_qs(urlparse(request.full_url).query)

    assert params["api_key"] == ["explicit-key"]


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    with pytest.raises(SearchProviderError) as exc_info:
        SerpApiProvider()

    assert exc_info.value.code == "SEARCH_API_KEY_MISSING"
    assert exc_info.value.retryable is False


@pytest.mark.parametrize("api_key", ["", "   "])
def test_blank_api_key(api_key):
    with pytest.raises(SearchProviderError) as exc_info:
        SerpApiProvider(api_key=api_key)

    assert exc_info.value.code == "SEARCH_API_KEY_MISSING"


@pytest.mark.parametrize("timeout", [0, -1])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        SerpApiProvider(api_key="test-key", timeout=timeout)


@pytest.mark.parametrize("query", ["", "   ", None, 123])
def test_invalid_query_does_not_call_api(
    client, mock_urlopen, query
):
    with pytest.raises(SearchProviderError) as exc_info:
        client.search(query)

    assert exc_info.value.code == "SEARCH_QUERY_INVALID"
    assert exc_info.value.retryable is False
    mock_urlopen.assert_not_called()


def test_empty_results(client, mock_urlopen):
    set_json_response(
        mock_urlopen,
        {
            "search_metadata": {"status": "Success"},
            "organic_results": [],
        },
    )

    assert client.search("검색 결과 없는 검색어") == []


@pytest.mark.parametrize(
    "information",
    [
        {"total_results": 0},
        {
            "organic_results_state":
                "Fully empty — No results for exact spelling."
        },
    ],
)
def test_explicit_no_results_without_organic_results(
    client, mock_urlopen, information
):
    set_json_response(
        mock_urlopen,
        {
            "search_metadata": {"status": "Success"},
            "search_information": information,
        },
    )

    assert client.search("검색 결과 없는 검색어") == []


def test_optional_result_fields(client, mock_urlopen):
    set_json_response(
        mock_urlopen,
        {
            "search_metadata": {"status": "Success"},
            "organic_results": [
                {"link": "https://example.com/profile"}
            ],
        },
    )

    results = client.search("홍길동")

    assert results == [
        ProviderResult(
            url="https://example.com/profile",
            title=None,
            snippet=None,
            provider_rank=None,
        )
    ]


@pytest.mark.parametrize(
    ("status", "expected_code", "retryable"),
    [
        (400, "SEARCH_HTTP_ERROR", False),
        (401, "SEARCH_AUTH_ERROR", False),
        (403, "SEARCH_AUTH_ERROR", False),
        (429, "SEARCH_LIMIT_ERROR", True),
        (500, "SEARCH_HTTP_ERROR", True),
        (503, "SEARCH_HTTP_ERROR", True),
    ],
)
def test_http_errors(
    client,
    mock_urlopen,
    status,
    expected_code,
    retryable,
):
    mock_urlopen.side_effect = HTTPError(
        url="https://serpapi.com/search.json?api_key=test-secret-key",
        code=status,
        msg="Request failed",
        hdrs=None,
        fp=None,
    )

    with pytest.raises(SearchProviderError) as exc_info:
        client.search("숭실대학교")

    error = exc_info.value
    assert error.code == expected_code
    assert error.retryable is retryable
    assert "test-secret-key" not in str(error)
    assert "api_key=" not in str(error)
    mock_urlopen.assert_called_once()


@pytest.mark.parametrize(
    ("network_error", "expected_code"),
    [
        (TimeoutError("timeout"), "SEARCH_TIMEOUT"),
        (URLError(TimeoutError("timeout")), "SEARCH_TIMEOUT"),
        (
            URLError("DNS lookup failed"),
            "SEARCH_NETWORK_ERROR",
        ),
    ],
)
def test_network_errors(
    client, mock_urlopen, network_error, expected_code
):
    mock_urlopen.side_effect = network_error

    with pytest.raises(SearchProviderError) as exc_info:
        client.search("숭실대학교")

    assert exc_info.value.code == expected_code
    assert exc_info.value.retryable is True
    mock_urlopen.assert_called_once()


def test_api_error_body_is_not_exposed(client, mock_urlopen):
    set_json_response(
        mock_urlopen,
        {
            "error":
                "Invalid request with api_key=test-secret-key",
        },
    )

    with pytest.raises(SearchProviderError) as exc_info:
        client.search("숭실대학교")

    assert exc_info.value.code == "SEARCH_API_ERROR"
    assert exc_info.value.retryable is False
    assert "test-secret-key" not in str(exc_info.value)


@pytest.mark.parametrize("raw_body", [b"not JSON", b"\xff"])
def test_invalid_json(client, mock_urlopen, raw_body):
    response = mock_urlopen.return_value.__enter__.return_value
    response.read.return_value = raw_body

    with pytest.raises(SearchProviderError) as exc_info:
        client.search("숭실대학교")

    assert exc_info.value.code == "SEARCH_INVALID_RESPONSE"


@pytest.mark.parametrize(
    "data",
    [
        [],
        None,
        {},
        {"search_metadata": {"status": "Processing"}},
        {"search_metadata": {"status": "Success"}},
        {
            "search_metadata": {"status": "Success"},
            "organic_results": None,
        },
        {
            "search_metadata": {"status": "Success"},
            "organic_results": {},
        },
    ],
)
def test_invalid_response_structure(client, mock_urlopen, data):
    set_json_response(mock_urlopen, data)

    with pytest.raises(SearchProviderError) as exc_info:
        client.search("숭실대학교")

    assert exc_info.value.code == "SEARCH_INVALID_RESPONSE"


@pytest.mark.parametrize(
    "item",
    [
        None,
        {},
        {"link": ""},
        {"link": "   "},
        {"link": 123},
        {"link": "https://example.com", "title": 123},
        {"link": "https://example.com", "snippet": []},
        {"link": "https://example.com", "position": 0},
        {"link": "https://example.com", "position": True},
        {"link": "https://example.com", "position": "1"},
    ],
)
def test_invalid_result_items(client, mock_urlopen, item):
    set_json_response(
        mock_urlopen,
        {
            "search_metadata": {"status": "Success"},
            "organic_results": [item],
        },
    )

    with pytest.raises(SearchProviderError) as exc_info:
        client.search("숭실대학교")

    assert exc_info.value.code == "SEARCH_INVALID_RESPONSE"
@pytest.mark.parametrize(
    ("options", "expected_timeout"),
    [
        ({}, 10.0),
        ({"timeout": 3.0}, 3.0),
    ],
)
def test_timeout_is_passed_to_urlopen(
    monkeypatch,
    options,
    expected_timeout,
):
    import json
    from unittest.mock import MagicMock

    from dfsa.modules.search import provider as provider_module

    response = MagicMock()
    response.read.return_value = json.dumps(
        {
            "search_metadata": {"status": "Success"},
            "organic_results": [],
        }
    ).encode("utf-8")

    mocked_urlopen = MagicMock()
    mocked_urlopen.return_value.__enter__.return_value = response

    monkeypatch.setattr(
        provider_module,
        "urlopen",
        mocked_urlopen,
    )

    client = provider_module.SerpApiProvider(
        api_key="test-key",
        **options,
    )

    assert client.search("테스트 검색") == []

    mocked_urlopen.assert_called_once()
    assert (
        mocked_urlopen.call_args.kwargs["timeout"]
        == expected_timeout
    )
