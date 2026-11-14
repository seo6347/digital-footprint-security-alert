"""Phase 1 HTML fetch only; no parsing or public status aggregation.

URL policy is preflight only: see url_policy for the DNS rebinding limitation.
Timeout bounds individual socket operations, not total fetch duration or DNS.
"""

import http.client
import math
import socket
import ssl
from contextlib import closing
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import (
    HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener,
)

from dfsa.contracts.common import ErrorDetail
from dfsa.contracts.search import SearchResult

from ._types import FetchError, FetchFailure, FetchedHTML, FetchProblem
from .url_policy import Resolver, check_url_text, validate_url


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

    # Return raw redirect responses, without urllib sanitizing Location first.
    def http_error_302(self, req, fp, code, msg, headers):
        return fp

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _build_opener():
    return build_opener(ProxyHandler({}), _NoRedirect(),
                        HTTPSHandler(context=ssl.create_default_context()))


def _header(headers, name: str) -> str | None:
    values = headers.get_all(name, [])
    if len(values) > 1:
        raise FetchProblem(FetchError.INVALID_RESPONSE, f"Duplicate {name} headers")
    return values[0] if values else None


def _http_problem(status: int) -> FetchError:
    if status == 404:
        return FetchError.HTTP_NOT_FOUND
    if status == 429:
        return FetchError.HTTP_RATE_LIMITED
    if 500 <= status <= 599:
        return FetchError.HTTP_SERVER_ERROR
    return FetchError.HTTP_ERROR


def fetch_html(
    source: SearchResult, *, timeout: float = 10, max_redirects: int = 5,
    max_body_bytes: int = 2 * 1024 * 1024, opener=None,
    resolver: Resolver | None = None,
) -> FetchedHTML | FetchFailure:
    """Fetch one source without mutating it; expected failures are return values.

    Injected openers must return a raw single-hop response (no auto redirects or
    proxies) and honor the supplied timeout. Resolver/opener injection is for
    trusted callers/tests, not user-supplied settings. Unexpected bugs propagate.
    Bytes are not decoded, sniffed or decompressed. Missing Content-Type and
    non-identity Content-Encoding are unsupported. Empty HTML is a valid fetch.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if type(max_redirects) is not int or max_redirects < 0:
        raise ValueError("max_redirects must be a nonnegative integer")
    if type(max_body_bytes) is not int or max_body_bytes < 1:
        raise ValueError("max_body_bytes must be a positive integer")
    current = source.url
    status = None

    def failure(kind: FetchError, message: str) -> FetchFailure:
        return FetchFailure(
            source.source_id, source.url, current, kind,
            ErrorDetail(code=kind.value, message=message,
                        retryable=kind in {FetchError.TIMEOUT, FetchError.DNS_ERROR,
                                          FetchError.NETWORK_ERROR, FetchError.HTTP_RATE_LIMITED,
                                          FetchError.HTTP_SERVER_ERROR},
                        source_id=source.source_id), status,
        )

    try:
        client = opener if opener is not None else _build_opener()
        seen: set[str] = set()
        redirects = 0
        while True:
            status = None
            current = validate_url(current, resolver=resolver)
            if current in seen:
                raise FetchProblem(FetchError.REDIRECT_LIMIT, "Redirect cycle")
            seen.add(current)
            request = Request(current, method="GET", headers={
                "Accept": "text/html, application/xhtml+xml", "Accept-Encoding": "identity",
                "User-Agent": "DFSA/0.1",
            })
            try:
                response = client.open(request, timeout=timeout)
            except HTTPError as exc:
                response = exc
            with closing(response):
                status = response.code
                if status in (301, 302, 303, 307, 308):
                    if redirects >= max_redirects:
                        raise FetchProblem(FetchError.REDIRECT_LIMIT, "Too many redirects")
                    location = _header(response.headers, "Location")
                    if location is None:
                        raise FetchProblem(FetchError.INVALID_RESPONSE, "Redirect without Location")
                    check_url_text(location)
                    try:
                        current = urljoin(current, location)
                    except ValueError as exc:
                        raise FetchProblem(FetchError.INVALID_URL, "Malformed redirect URL") from exc
                    redirects += 1
                    continue
                if not 200 <= status < 300:
                    return failure(_http_problem(status), f"HTTP {status}")
                media_type = _header(response.headers, "Content-Type")
                if media_type is None:
                    raise FetchProblem(FetchError.UNSUPPORTED_CONTENT_TYPE, "Missing Content-Type")
                media_type = media_type.split(";", 1)[0].strip().lower()
                if media_type not in ("text/html", "application/xhtml+xml"):
                    raise FetchProblem(FetchError.UNSUPPORTED_CONTENT_TYPE, "Expected HTML or XHTML")
                encoding = _header(response.headers, "Content-Encoding")
                if encoding is not None and encoding.strip().lower() != "identity":
                    raise FetchProblem(FetchError.UNSUPPORTED_ENCODING, "Encoded bodies are unsupported")
                length = _header(response.headers, "Content-Length")
                if length is not None:
                    length = length.strip(" \t")
                    if not length.isascii() or not length.isdecimal():
                        raise FetchProblem(FetchError.INVALID_RESPONSE, "Invalid Content-Length")
                    if len(length) > 20 or int(length) > max_body_bytes:
                        raise FetchProblem(FetchError.BODY_TOO_LARGE, "HTML exceeds body limit")
                body = bytearray()
                while True:
                    chunk = response.read(min(65536, max_body_bytes + 1 - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > max_body_bytes:
                        raise FetchProblem(FetchError.BODY_TOO_LARGE, "HTML exceeds body limit")
                if length is not None and len(body) != int(length):
                    raise FetchProblem(FetchError.INVALID_RESPONSE, "Truncated response body")
                return FetchedHTML(source.source_id, source.url, current, bytes(body),
                                   media_type, response.headers.get_content_charset(), status)
    except FetchProblem as exc:
        return failure(exc.kind, str(exc))
    except (URLError, OSError, http.client.HTTPException) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(reason, (TimeoutError, socket.timeout)):
            kind = FetchError.TIMEOUT
        elif isinstance(reason, socket.gaierror):
            kind = FetchError.DNS_ERROR
        elif isinstance(reason, ssl.SSLError):
            kind = FetchError.TLS_ERROR
        else:
            kind = FetchError.NETWORK_ERROR
        return failure(kind, "Network operation failed")
