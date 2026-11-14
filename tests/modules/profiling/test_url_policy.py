import socket

import pytest

from dfsa.modules.profiling._types import FetchError, FetchProblem
from dfsa.modules.profiling.url_policy import validate_url


@pytest.mark.parametrize("url, expected", [
    ("HTTPS://EXAMPLE.COM.:443/한글?q=안녕#fragment", "https://example.com/%ED%95%9C%EA%B8%80?q=%EC%95%88%EB%85%95"),
    ("http://example.com:80", "http://example.com/"),
    ("https://예시.com", "https://xn--vv4b11d.com/"),
    ("https://8.8.8.8/", "https://8.8.8.8/"),
    ("https://[2606:4700:4700::1111]:443/", "https://[2606:4700:4700::1111]/"),
])
def test_normalization(url, expected, public_dns):
    assert validate_url(url, resolver=public_dns) == expected


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/", "javascript:alert(1)", "//example.com/",
    "https:///missing", "https://user:pass@example.com/", "https://example.com:8443/",
    "http://example.com:443/", "https://example.com:/", "https://example.com:abc/",
    "https://example.com:99999/", "https://[::1", "https://[::1]suffix/",
    "https://[fe80::1%25eth0]/", "https://example.com\\@127.0.0.1/",
    " https://example.com/", "https://example.com/\n", "https://example.com/\x00",
    "https://example.com/a b", "https://example.com/%xx", "https://%31%32%37.0.0.1/",
    "https://-example.com/", "https://example..com/", "https://a_b.com/",
    "http://127.1/", "http://2130706433/", "http://0x7f000001/",
    "http://0177.0.0.1/", "http://0x7f.0.0.1/",
])
def test_malformed_urls_never_resolve(url):
    with pytest.raises(FetchProblem):
        validate_url(url)


@pytest.mark.parametrize("host", [
    "localhost", "LOCALHOST.", "host.localhost", "intranet", "service.internal",
    "router.local", "app.lan", "app.home", "router.home.arpa",
    "127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254",
    "0.0.0.0", "224.0.0.1", "240.0.0.1", "100.100.100.200", "168.63.129.16",
    "192.0.0.8", "192.0.0.9", "192.0.2.1", "198.18.0.1", "203.0.113.1",
    "[::]", "[::1]", "[fc00::1]", "[fe80::1]", "[ff02::1]", "[2001:db8::1]",
    "[::ffff:127.0.0.1]", "[::ffff:8.8.8.8]", "[64:ff9b::808:808]",
    "[64:ff9b:1::1]", "[2002:0808:0808::1]", "[2001::1]", "[3fff::1]",
])
def test_internal_and_special_addresses_blocked_before_dns(host):
    with pytest.raises(FetchProblem) as error:
        validate_url(f"http://{host}/")
    assert error.value.kind == FetchError.BLOCKED_URL


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"], ["93.184.216.34", "10.0.0.1"],
    ["2606:4700:4700::1111", "::1"], ["not-an-ip"], [],
])
def test_dns_all_answers_must_be_public(addresses):
    def dns(host, port, **kwargs):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, 1, 6, "", (ip, port)) for ip in addresses]
    with pytest.raises(FetchProblem):
        validate_url("https://example.com/", resolver=dns)


def test_dns_failure_propagates_for_fetch_classification():
    def dns(*args, **kwargs):
        raise socket.gaierror("no host")
    with pytest.raises(socket.gaierror):
        validate_url("https://example.com/", resolver=dns)
