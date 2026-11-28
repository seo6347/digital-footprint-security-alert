"""Scoped HTTP adapters for the v0.2 development runner."""

import http.client
import io
import math
import socket
from contextlib import ExitStack, contextmanager
from enum import StrEnum
from time import monotonic
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from dfsa.modules.explorer._types import FetchError, FetchProblem
from dfsa.modules.explorer.transport import PinnedHTTPS
from dfsa.modules.explorer.url_policy import check_url_text
from dfsa.modules.search import provider


class PolicyReason(StrEnum):
    POLICY = "approval_policy"
    DIRECT_NETWORK = "direct_network_disabled"
    PAGE_SCOPE = "page_outside_approved_scope"
    DNS = "public_dns_or_url_rejected"
    SEARCH_ENDPOINT = "unapproved_search_endpoint"
    BUDGET = "request_budget_exhausted"
    BODY_LIMIT = "response_body_limit"


class LivePolicyError(RuntimeError):
    """The live runner stopped an operation outside its approval or budget."""

    def __init__(self, message, reason=PolicyReason.POLICY):
        super().__init__(message)
        self.reason = reason


class LiveTransport:
    def __init__(self, scope):
        self.scope = scope
        self.stage = None
        self.search_requests = 0
        self.html_requests = 0
        self.robots_requests = 0
        self._resolve = socket.getaddrinfo
        self._connect = socket.socket.connect

    def network(self):
        return PinnedHTTPS(resolve=self._resolve, connect=self._connect)

    def record_exploration(self, requests, robots_requests):
        self.html_requests = requests - robots_requests
        self.robots_requests = robots_requests

    @contextmanager
    def install(self):
        """Disable raw network access. Callables use the approved transports."""
        def denied(*args, **kwargs):
            raise LivePolicyError("Direct network access is disabled", PolicyReason.DIRECT_NETWORK)

        with ExitStack() as stack:
            for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
                stack.enter_context(patch.object(socket, name, denied))
            for name in ("connect", "connect_ex", "sendto", "sendmsg"):
                if hasattr(socket.socket, name):
                    stack.enter_context(patch.object(socket.socket, name, denied))
            stack.enter_context(patch.object(provider, "urlopen", self.search))
            yield

    def _request(self, url, timeout, headers):
        if not math.isfinite(timeout) or timeout <= 0:
            raise LivePolicyError("Invalid live timeout")
        try:
            return self.network().request(url, deadline=monotonic() + min(timeout, 10), headers=headers)
        except FetchProblem as exc:
            if exc.kind == FetchError.DNS_ERROR:
                raise URLError("Live DNS lookup failed") from None
            raise LivePolicyError("Public DNS or URL policy rejected the request", PolicyReason.DNS) from None
        except TimeoutError:
            raise URLError(TimeoutError("Live HTTPS timed out")) from None
        except (OSError, http.client.HTTPException):
            raise URLError("Live HTTPS failed") from None

    def search(self, request, *, timeout):
        try:
            check_url_text(request.full_url)
            parts = urlsplit(request.full_url)
        except (FetchProblem, ValueError):
            raise LivePolicyError("Only the approved search endpoint is allowed", PolicyReason.SEARCH_ENDPOINT) from None
        if (
            self.stage != "search" or request.get_method() != "GET"
            or (parts.scheme, parts.netloc, parts.path) != ("https", "serpapi.com", "/search.json")
            or parts.fragment
        ):
            raise LivePolicyError("Only the approved search endpoint is allowed", PolicyReason.SEARCH_ENDPOINT)
        if self.search_requests >= 1:
            raise LivePolicyError("Search request budget exhausted", PolicyReason.BUDGET)
        self.search_requests += 1
        with self._request(request.full_url, timeout, {"Accept": "application/json"}) as response:
            if not 200 <= response.code < 300:
                raise HTTPError(provider.SERPAPI_ENDPOINT, response.code, "Search HTTP failure",
                                response.headers, None)
            body = bytearray()
            limit = 1024 * 1024
            while chunk := response.read(min(65536, limit + 1 - len(body))):
                body.extend(chunk)
                if len(body) > limit:
                    raise LivePolicyError("Live response exceeded the byte limit", PolicyReason.BODY_LIMIT)
            lengths = response.headers.get_all("Content-Length", [])
            if lengths and response.headers.get("Transfer-Encoding", "").lower() != "chunked":
                length = lengths[0].strip()
                if (len(lengths) != 1 or not length.isascii() or not length.isdecimal()
                        or len(length) > 20 or len(body) != int(length)):
                    raise URLError("Invalid search response length")
        return io.BytesIO(body)
