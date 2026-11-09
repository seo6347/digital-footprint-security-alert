"""Unit tests for conservative search URL normalization."""

import pytest

from dfsa.modules.search.normalizer import (
    URLNormalizationError,
    normalize_url,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "  https://Example.COM/profile  ",
            "https://example.com/profile",
        ),
        (
            "HTTPS://Example.COM/Profile",
            "https://example.com/Profile",
        ),
        (
            "https://example.com",
            "https://example.com/",
        ),
        (
            "http://example.com:80/profile",
            "http://example.com/profile",
        ),
        (
            "https://example.com:443/profile",
            "https://example.com/profile",
        ),
        (
            "https://example.com:8443/profile",
            "https://example.com:8443/profile",
        ),
        (
            "https://example.com/profile#members",
            "https://example.com/profile",
        ),
        (
            "https://example.com/profile?id=123&lang=ko",
            "https://example.com/profile?id=123&lang=ko",
        ),
        (
            "https://example.com/profile/",
            "https://example.com/profile/",
        ),
        (
            "https://example.com/search?q=%ED%99%8D",
            "https://example.com/search?q=%ED%99%8D",
        ),
        (
            "https://[2001:db8::1]:443/profile",
            "https://[2001:db8::1]/profile",
        ),
    ],
)
def test_normalize_url(url, expected):
    assert normalize_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        None,
        123,
        "/profile",
        "//example.com/profile",
        "ftp://example.com/profile",
        "javascript:alert(1)",
        "https:///profile",
        "https://example.com:invalid/profile",
        "https://example.com:99999/profile",
        "https://user:password@example.com/profile",
        "https://example.com/a b",
        "https://example.com/pro\nfile",
        "https://example.com/\x00profile",
        "https://example.com\\profile",
    ],
)
def test_invalid_url_rejected(url):
    with pytest.raises(URLNormalizationError):
        normalize_url(url)


def test_query_values_are_not_merged():
    first = normalize_url("https://example.com/profile?id=1")
    second = normalize_url("https://example.com/profile?id=2")

    assert first != second


def test_path_case_is_preserved():
    first = normalize_url("https://example.com/Profile")
    second = normalize_url("https://example.com/profile")

    assert first != second


def test_trailing_slash_is_preserved():
    first = normalize_url("https://example.com/profile")
    second = normalize_url("https://example.com/profile/")

    assert first != second


def test_http_and_https_remain_distinct():
    first = normalize_url("http://example.com/profile")
    second = normalize_url("https://example.com/profile")

    assert first != second


def test_fragments_are_removed_for_comparison():
    first = normalize_url("https://example.com/profile#intro")
    second = normalize_url("https://example.com/profile#members")

    assert first == second


def test_query_order_is_preserved():
    first = normalize_url("https://example.com/?a=1&b=2")
    second = normalize_url("https://example.com/?b=2&a=1")

    assert first != second


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://example.com/profile?utm_source=google",
            "https://example.com/profile",
        ),
        (
            "https://example.com/profile"
            "?utm_source=google&utm_medium=email&utm_campaign=test",
            "https://example.com/profile",
        ),
        (
            "https://example.com/profile"
            "?id=123&utm_source=google&page=2",
            "https://example.com/profile?id=123&page=2",
        ),
        (
            "https://example.com/profile?UTM_SOURCE=google",
            "https://example.com/profile",
        ),
        (
            "https://example.com/profile?%75tm_source=google",
            "https://example.com/profile",
        ),
        (
            "https://example.com/profile?utm_source",
            "https://example.com/profile",
        ),
        (
            "https://example.com/profile"
            "?q=a%20b&utm_source=google&tag=x&tag=y&empty=",
            "https://example.com/profile"
            "?q=a%20b&tag=x&tag=y&empty=",
        ),
        (
            "https://example.com/profile?id=123&page=2",
            "https://example.com/profile?id=123&page=2",
        ),
        (
            "https://example.com/profile?note=utm_source",
            "https://example.com/profile?note=utm_source",
        ),
    ],
)
def test_tracking_parameters_are_removed(url, expected):
    assert normalize_url(url) == expected
