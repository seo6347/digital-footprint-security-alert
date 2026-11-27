"""Scoped HTTP adapters for the v0.2 development runner."""

import http.client
import io
import json
import math
import re
import socket
import ssl
from contextlib import ExitStack, contextmanager
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import Request

from dfsa.modules.explorer import fetch
from dfsa.modules.explorer._types import FetchError, FetchProblem
from dfsa.modules.explorer.url_policy import check_url_text, validate_url
from dfsa.modules.search import provider


class LivePolicyError(RuntimeError):
    """The live runner stopped an operation outside its approval or budget."""


_SEARCH_PARAMETERS = {"api_key", "engine", "gl", "hl", "num", "q"}


def _https_parts(url):
    try:
        check_url_text(url)
        parts = urlsplit(url)
        host = parts.hostname
        if (parts.scheme != "https" or not host or parts.port not in (None, 443)
                or parts.netloc.lower() not in (host, f"{host}:443")
                or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host)):
            raise ValueError
    except (FetchProblem, ValueError):
        raise LivePolicyError("An exact HTTPS hostname is required") from None
    return parts


def _site_path(path):
    # Encoded separators, repeated escapes and path parameters can be routed
    # differently by a server or proxy. Do not treat them as scoped paths.
    path = path or "/"
    if re.search("%(?:2f|5c|25)", path, re.IGNORECASE):
        raise LivePolicyError("Ambiguous site path")
    try:
        decoded = unquote(path, errors="strict")
    except UnicodeError:
        raise LivePolicyError("Ambiguous site path") from None
    if (any(part in {".", ".."} for part in decoded.split("/")) or "//" in decoded
            or any(char in "\\;?#" or ord(char) <= 32 or ord(char) == 127 for char in decoded)):
        raise LivePolicyError("Ambiguous site path")
    return decoded


class SiteScope:
    """A single approved HTTPS page, or a subtree when the path ends in /."""

    def __init__(self, site_url):
        parts = _https_parts(site_url)
        if parts.query or parts.fragment or parts.hostname == "serpapi.com":
            raise LivePolicyError("Invalid approved site URL")
        self.host = parts.hostname
        self.path = _site_path(parts.path)
        self.subtree = self.path.endswith("/")

    def contains(self, url):
        try:
            parts = _https_parts(url)
            path = _site_path(parts.path)
        except LivePolicyError:
            return False
        return parts.hostname == self.host and (
            path.startswith(self.path) if self.subtree else path == self.path
        )


class _HopResponse:
    def __init__(self, response, connection, limit):
        self._response = response
        self._connection = connection
        self._remaining = limit
        self.code = response.status
        self.headers = response.headers

    def read(self, size=-1):
        budget = self._remaining
        size = budget + 1 if size < 0 else min(size, budget + 1)
        try:
            chunk = self._response.read(size)
        except TimeoutError:
            raise URLError(TimeoutError("Live response read timed out")) from None
        except (OSError, http.client.HTTPException):
            raise URLError("Live response read failed") from None
        if len(chunk) > budget:
            raise LivePolicyError("Live response exceeded the byte limit")
        self._remaining -= len(chunk)
        return chunk

    def close(self):
        try:
            self._response.close()
        finally:
            self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class LiveTransport:
    def __init__(self, scope):
        self.scope = scope
        self.stage = None
        self.search_requests = 0
        self.html_requests = 0
        self._resolve = socket.getaddrinfo
        self._connect = socket.socket.connect

    @contextmanager
    def install(self):
        """Expose only the reviewed adapters in this single-process CLI."""
        def denied(*args, **kwargs):
            raise LivePolicyError("Direct network access is disabled")

        def scoped_dns(host, port, *args, **kwargs):
            if self.stage != "exploration" or host != self.scope.host or port != 443:
                raise LivePolicyError("DNS lookup outside the active stage or approved host")
            return self._resolve(host, port, *args, **kwargs)

        with ExitStack() as stack:
            for name in ("create_connection", "gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
                stack.enter_context(patch.object(socket, name, denied))
            for name in ("connect", "connect_ex", "sendto", "sendmsg"):
                if hasattr(socket.socket, name):
                    stack.enter_context(patch.object(socket.socket, name, denied))
            stack.enter_context(patch.object(socket, "getaddrinfo", scoped_dns))
            stack.enter_context(patch.object(provider, "urlopen", self.search))
            stack.enter_context(patch.object(fetch, "_build_opener", lambda: self))
            yield

    def _request(self, url, timeout, limit, headers):
        answers = []

        def resolve(host, port, **kwargs):
            answers.extend(self._resolve(host, port, **kwargs))
            return answers

        if not math.isfinite(timeout) or timeout <= 0:
            raise LivePolicyError("Invalid live timeout")
        try:
            parts = urlsplit(validate_url(url, resolver=resolve))
            if not answers:
                raise LivePolicyError("Live requests require a public DNS hostname")
            family, kind, protocol, _, address = answers[0]

            def connect_pinned(destination, connection_timeout, source_address=None):
                connection = socket.socket(family, kind, protocol)
                try:
                    connection.settimeout(connection_timeout)
                    self._connect(connection, address)
                    return connection
                except BaseException:
                    connection.close()
                    raise

            connection = http.client.HTTPSConnection(
                parts.hostname, timeout=min(timeout, 10), context=ssl.create_default_context(),
            )
            connection._create_connection = connect_pinned
            try:
                connection.request("GET", urlunsplit(("", "", parts.path, parts.query, "")), headers=headers)
                return _HopResponse(connection.getresponse(), connection, limit)
            except BaseException:
                connection.close()
                raise
        except FetchProblem as exc:
            if exc.kind == FetchError.DNS_ERROR:
                raise URLError("Live DNS lookup failed") from None
            raise LivePolicyError("Public DNS or URL policy rejected the request") from None
        except TimeoutError:
            raise URLError(TimeoutError("Live HTTPS timed out")) from None
        except (OSError, http.client.HTTPException):
            raise URLError("Live HTTPS failed") from None

    def open(self, request, *, timeout):
        if self.stage != "exploration" or request.get_method() != "GET" or not self.scope.contains(request.full_url):
            raise LivePolicyError("Page request or redirect is outside the approved HTTPS scope")
        if self.html_requests >= 40:
            raise LivePolicyError("HTML request budget exhausted")
        self.html_requests += 1
        return self._request(request.full_url, timeout, 2 * 1024 * 1024,
                             {"Accept": "text/html, application/xhtml+xml", "Accept-Encoding": "identity"})

    def search(self, request, *, timeout):
        parts = _https_parts(request.full_url)
        if (
            self.stage != "search" or request.get_method() != "GET"
            or (parts.hostname, parts.path) != ("serpapi.com", "/search.json") or parts.fragment
        ):
            raise LivePolicyError("Only the approved search endpoint is allowed")
        if self.search_requests >= 1:
            raise LivePolicyError("Search request budget exhausted")
        params = parse_qs(parts.query)
        query = params.get("q", [])
        if (
            len(query) != 1 or params.get("engine", ["google"]) != ["google"]
            or not params.keys() <= _SEARCH_PARAMETERS
            or any(len(values) != 1 for values in params.values())
        ):
            raise LivePolicyError("Unexpected search request parameters")
        params["q"] = [query[0] + f" site:{self.scope.host}"]
        url = urlunsplit(("https", "serpapi.com", "/search.json", urlencode(params, doseq=True), ""))
        self.search_requests += 1
        with self._request(url, timeout, 1024 * 1024, {"Accept": "application/json"}) as response:
            if not 200 <= response.code < 300:
                raise HTTPError(provider.SERPAPI_ENDPOINT, response.code, "Search HTTP failure",
                                response.headers, None)
            body = bytearray()
            while chunk := response.read(65536):
                body.extend(chunk)
            lengths = response.headers.get_all("Content-Length", [])
            if lengths and response.headers.get("Transfer-Encoding", "").lower() != "chunked":
                length = lengths[0].strip()
                if (len(lengths) != 1 or not length.isascii() or not length.isdecimal()
                        or len(length) > 20 or len(body) != int(length)):
                    raise URLError("Invalid search response length")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            return io.BytesIO(body)
        if isinstance(payload, dict) and isinstance(payload.get("organic_results"), list):
            results = payload["organic_results"]
            if all(isinstance(item, dict) and isinstance(item.get("link"), str) for item in results):
                payload["organic_results"] = [item for item in results if self.scope.contains(item["link"])]
        return io.BytesIO(json.dumps(payload).encode("utf-8"))
