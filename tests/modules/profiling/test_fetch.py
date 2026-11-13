import http.client
import socket
import ssl
from email.message import Message
from urllib.error import HTTPError, URLError
from urllib.request import AbstractHTTPHandler, HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request

import pytest

from dfsa.modules.profiling import fetch, url_policy
from dfsa.modules.profiling._types import FetchError, FetchFailure, FetchedHTML


@pytest.mark.parametrize("content_type, charset", [
    ("text/html", None), ("TEXT/HTML; Charset=UTF-8", "utf-8"),
    ('application/xhtml+xml; charset="euc-kr"', "euc-kr"),
    ("text/html; charset=unknown-encoding", "unknown-encoding"),
])
def test_html_bytes_metadata_and_input_preserved(source, public_dns, response_factory, opener_factory, content_type, charset):
    original = source.model_dump()
    response = response_factory(b"\xff<html/>", headers={"Content-Type": content_type})
    opener = opener_factory(response)
    result = fetch.fetch_html(source, opener=opener, resolver=public_dns)
    assert isinstance(result, FetchedHTML)
    assert result.html == b"\xff<html/>"
    assert result.charset == charset
    assert result.original_url == result.final_url == source.url
    assert result.source_id == source.source_id
    assert result.http_status == 200
    assert source.model_dump() == original
    request, timeout = opener.calls[0]
    assert request.full_url == source.url
    assert request.get_method() == "GET" and timeout == 10
    assert request.get_header("Accept-encoding") == "identity"
    assert response.closed


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_relative_redirect(source, public_dns, response_factory, opener_factory, code):
    first = response_factory(code=code, headers={"Location": "../final"})
    last = response_factory()
    opener = opener_factory(first, last)
    result = fetch.fetch_html(source, opener=opener, resolver=public_dns)
    assert result.final_url == "https://example.com/final"
    assert result.original_url == source.url
    assert len(opener.calls) == 2
    assert first.closed and last.closed


@pytest.mark.parametrize("status, kind", [(404, FetchError.HTTP_NOT_FOUND), (429, FetchError.HTTP_RATE_LIMITED),
    (500, FetchError.HTTP_SERVER_ERROR), (503, FetchError.HTTP_SERVER_ERROR), (403, FetchError.HTTP_ERROR)])
@pytest.mark.parametrize("raised", [False, True])
def test_http_errors(source, public_dns, response_factory, opener_factory, status, kind, raised):
    response = response_factory(code=status)
    item = HTTPError(source.url, status, "failure", response.headers, response) if raised else response
    result = fetch.fetch_html(source, opener=opener_factory(item), resolver=public_dns)
    assert isinstance(result, FetchFailure)
    assert result.kind == kind and result.http_status == status
    assert result.error.source_id == source.source_id
    assert response.closed and not response.read_sizes


@pytest.mark.parametrize("error, kind", [
    (TimeoutError(), FetchError.TIMEOUT), (URLError(TimeoutError()), FetchError.TIMEOUT),
    (socket.gaierror(), FetchError.DNS_ERROR), (URLError(socket.gaierror()), FetchError.DNS_ERROR),
    (ssl.SSLError(), FetchError.TLS_ERROR), (URLError(ssl.SSLCertVerificationError()), FetchError.TLS_ERROR),
    (ConnectionResetError(), FetchError.NETWORK_ERROR), (URLError("failure"), FetchError.NETWORK_ERROR),
    (http.client.IncompleteRead(b"partial"), FetchError.NETWORK_ERROR),
])
def test_network_errors(source, public_dns, opener_factory, error, kind):
    result = fetch.fetch_html(source, opener=opener_factory(error), resolver=public_dns)
    assert result.kind == kind


@pytest.mark.parametrize("headers, kind", [
    ({}, FetchError.UNSUPPORTED_CONTENT_TYPE),
    ({"Content-Type": "application/pdf"}, FetchError.UNSUPPORTED_CONTENT_TYPE),
    ({"Content-Type": "application/json"}, FetchError.UNSUPPORTED_CONTENT_TYPE),
    ({"Content-Type": "text/html", "Content-Encoding": "gzip"}, FetchError.UNSUPPORTED_ENCODING),
    ({"Content-Type": "text/html", "Content-Length": "-1"}, FetchError.INVALID_RESPONSE),
    ({"Content-Type": "text/html", "Content-Length": "n/a"}, FetchError.INVALID_RESPONSE),
])
def test_unsupported_and_invalid_headers(source, public_dns, response_factory, opener_factory, headers, kind):
    response = response_factory(headers=headers)
    result = fetch.fetch_html(source, opener=opener_factory(response), resolver=public_dns)
    assert result.kind == kind
    assert response.closed and not response.read_sizes


@pytest.mark.parametrize("body, length, kind", [
    (b"", "0", None), (b"abcd", "4", None), (b"abcd", None, None),
    (b"abcd", " 4", None), (b"abcd", "4 \t", None),
    (b"abcd", "\t 4 \t", None), (b"", " \t0\t ", None),
    (b"abcd", " \t0004\t ", None),
    (b"abcde", None, FetchError.BODY_TOO_LARGE),
    (b"", "5", FetchError.BODY_TOO_LARGE),
    (b"", " \t5\t ", FetchError.BODY_TOO_LARGE),
    (b"abcde", "1", FetchError.BODY_TOO_LARGE),
    (b"a", "4", FetchError.INVALID_RESPONSE),
    (b"a", " \t4\t ", FetchError.INVALID_RESPONSE),
])
def test_body_boundaries(source, public_dns, response_factory, opener_factory, body, length, kind):
    headers = {"Content-Type": "text/html"}
    if length is not None:
        headers["Content-Length"] = length
    response = response_factory(body, headers=headers)
    result = fetch.fetch_html(source, opener=opener_factory(response), resolver=public_dns, max_body_bytes=4)
    if kind is None:
        assert result.html == body
    else:
        assert result.kind == kind
    assert response.closed
    assert all(0 < size <= 5 for size in response.read_sizes)


@pytest.mark.parametrize("length", [
    "", " \t ", " -4\t", " +4 ", " 4.0 ", " 4,4 ", " 4 0 ", " 4\t0 ",
    " n/a ", "\u00a04\u00a0", "\v4\v", "\r\n4\r\n", " ４ ",
])
def test_invalid_content_length_with_whitespace(source, public_dns, response_factory, opener_factory, length):
    response = response_factory(b"abcd", headers={
        "Content-Type": "text/html", "Content-Length": length,
    })
    result = fetch.fetch_html(source, opener=opener_factory(response), resolver=public_dns)
    assert result.kind == FetchError.INVALID_RESPONSE
    assert response.closed and not response.read_sizes


def test_partial_reads_and_read_failure_cleanup(source, public_dns, response_factory, opener_factory):
    response = response_factory(b"hello")
    read = response.read
    response.read = lambda size: read(min(size, 1))
    assert fetch.fetch_html(source, opener=opener_factory(response), resolver=public_dns).html == b"hello"
    broken = response_factory()
    def fail(size):
        raise TimeoutError()
    broken.read = fail
    assert fetch.fetch_html(source, opener=opener_factory(broken), resolver=public_dns).kind == FetchError.TIMEOUT
    assert broken.closed


@pytest.mark.parametrize("location", ["http://127.0.0.1/", "https://10.0.0.1/", "file:///etc/passwd", "https://user@example.com/", "\nhttps://example.com/", "https://example.com:8443/", "http://["])
def test_blocked_redirect_never_connects(source, public_dns, response_factory, opener_factory, location):
    response = response_factory(code=302, headers={"Location": location})
    opener = opener_factory(response)
    result = fetch.fetch_html(source, opener=opener, resolver=public_dns)
    assert isinstance(result, FetchFailure)
    assert len(opener.calls) == 1 and response.closed


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://10.0.0.1/", "file:///secret", "https://[::1]/"])
def test_blocked_initial_url_never_connects(source, opener_factory, url):
    opener = opener_factory()
    result = fetch.fetch_html(source.model_copy(update={"url": url}), opener=opener)
    assert isinstance(result, FetchFailure) and not opener.calls


def test_same_host_redirect_rechecks_dns(source, public_dns, response_factory, opener_factory):
    calls = []
    def dns(host, port, **kwargs):
        calls.append(host)
        return public_dns(host, port) if len(calls) == 1 else [(socket.AF_INET, 1, 6, "", ("10.0.0.1", port))]
    response = response_factory(code=302, headers={"Location": "/next"})
    opener = opener_factory(response)
    result = fetch.fetch_html(source, opener=opener, resolver=dns)
    assert result.kind == FetchError.BLOCKED_URL
    assert len(calls) == 2 and len(opener.calls) == 1 and response.closed


def test_dns_preflight_failure_no_http(source, opener_factory):
    opener = opener_factory()
    def dns(*args, **kwargs):
        raise socket.gaierror()
    assert fetch.fetch_html(source, opener=opener, resolver=dns).kind == FetchError.DNS_ERROR
    assert not opener.calls


def test_redirect_limits_and_cycles(source, public_dns, response_factory, opener_factory):
    responses = [response_factory(code=302, headers={"Location": f"/{i}"}) for i in range(6)]
    opener = opener_factory(*responses)
    assert fetch.fetch_html(source, opener=opener, resolver=public_dns).kind == FetchError.REDIRECT_LIMIT
    assert len(opener.calls) == 6 and all(r.closed for r in responses)
    responses = [response_factory(code=302, headers={"Location": "/next"}),
                 response_factory(code=302, headers={"Location": "/profile"})]
    opener = opener_factory(*responses)
    assert fetch.fetch_html(source, opener=opener, resolver=public_dns).kind == FetchError.REDIRECT_LIMIT
    assert len(opener.calls) == 2 and all(r.closed for r in responses)


def test_exactly_five_redirects_allowed(source, public_dns, response_factory, opener_factory):
    responses = [response_factory(code=302, headers={"Location": f"/{i}"}) for i in range(5)]
    responses.append(response_factory())
    assert isinstance(fetch.fetch_html(source, opener=opener_factory(*responses), resolver=public_dns), FetchedHTML)


def test_missing_redirect_location(source, public_dns, response_factory, opener_factory):
    response = response_factory(code=302, headers={})
    assert fetch.fetch_html(source, opener=opener_factory(response), resolver=public_dns).kind == FetchError.INVALID_RESPONSE
    assert response.closed


@pytest.mark.parametrize("name", ["Content-Type", "Content-Length", "Location"])
def test_duplicate_headers_fail_closed(source, public_dns, response_factory, opener_factory, name):
    response = response_factory(code=302 if name == "Location" else 200)
    response.headers[name] = "/next" if name == "Location" else "text/html" if name == "Content-Type" else "1"
    if name != "Content-Type":
        response.headers[name] = "/other" if name == "Location" else "2"
    assert fetch.fetch_html(source, opener=opener_factory(response), resolver=public_dns).kind == FetchError.INVALID_RESPONSE
    assert response.closed


def test_real_opener_configuration_and_redirect_handler(monkeypatch):
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:8080")
    opener = fetch._build_opener()
    assert not any(isinstance(handler, ProxyHandler) for handler in opener.handlers)
    handlers = [h for h in opener.handlers if isinstance(h, HTTPRedirectHandler)]
    assert len(handlers) == 1 and isinstance(handlers[0], fetch._NoRedirect)
    https = next(h for h in opener.handlers if isinstance(h, HTTPSHandler))
    assert https._context.check_hostname and https._context.verify_mode == ssl.CERT_REQUIRED
    response = object()
    headers = Message()
    headers["Location"] = "http://127.0.0.1/"
    assert handlers[0].http_error_302(Request("https://example.com/"), response, 302, "Found", headers) is response


def test_default_opener_dispatches_raw_redirect_without_network(source, public_dns, response_factory, monkeypatch):
    responses = [response_factory(code=302, headers={"Location": "/next"}), response_factory()]
    calls = []
    def do_open(handler, connection, request, **kwargs):
        calls.append(request.full_url)
        response = responses[len(calls) - 1]
        response.msg = "OK"
        return response
    monkeypatch.setattr(AbstractHTTPHandler, "do_open", do_open)
    result = fetch.fetch_html(source, resolver=public_dns)
    assert result.final_url == "https://example.com/next"
    assert len(calls) == 2 and all(r.closed for r in responses)


@pytest.mark.parametrize("kwargs", [{"timeout": 0}, {"timeout": float("inf")}, {"max_redirects": -1}, {"max_body_bytes": 0}])
def test_invalid_configuration_is_not_hidden(source, kwargs):
    with pytest.raises(ValueError):
        fetch.fetch_html(source, **kwargs)


def test_programming_errors_propagate(source, public_dns, opener_factory):
    with pytest.raises(RuntimeError, match="bug"):
        fetch.fetch_html(source, resolver=public_dns, opener=opener_factory(RuntimeError("bug")))


def test_rebinding_limit_documented():
    assert "does NOT pin" in url_policy.__doc__
    assert "rebinding" in url_policy.__doc__
