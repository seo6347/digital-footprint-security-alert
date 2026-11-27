"""Manually gated live smoke runner. Never collected or run by pytest.

Run only with separate approval for the target site and SerpApi. No response
documents, subjects, credential-bearing URLs or exception messages are printed.
"""

import argparse
import http.client
import io
import json
import os
from pathlib import Path
import socket
import ssl
import sys
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import Request

# Direct script execution does not inherit pytest's pythonpath setting.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dfsa._v01.contracts import Subject
from dfsa.modules.explorer import fetch
from dfsa.modules.explorer._types import FetchError, FetchProblem
from dfsa.modules.explorer.url_policy import validate_url
from dfsa.modules.profiling.pipeline import run_profiling
from dfsa.modules.risk.engine import run_risk
from dfsa.modules.search import provider
from dfsa.modules.search.runner import run_search
from dfsa._v01 import orchestrator


class LivePolicyError(RuntimeError):
    """A runner limit or allowlist check stopped a request before HTTP."""


class Response:
    def __init__(self, response, connection):
        self.response = response
        self.connection = connection
        self.code = response.status
        self.headers = response.headers

    def read(self, size=-1):
        try:
            return self.response.read(size)
        except (OSError, http.client.HTTPException) as exc:
            # Reading happens after LiveHTTP.request returns. Keep the same
            # safe external-error interface through the entire response body.
            reason = (TimeoutError("Live HTTPS timeout") if isinstance(exc, TimeoutError)
                      else "Live HTTPS transport failed")
            raise URLError(reason) from None

    def close(self):
        try:
            self.response.close()
        finally:
            self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class LiveHTTP:
    """One approved HTTPS host, two search calls, three HTML hops maximum.

    The existing B URL policy checks every DNS answer. The connection is pinned
    to one of those answers while TLS still verifies the original hostname.
    This closes the preflight/connection DNS rebinding gap of the default B
    transport. No proxies, retries, pagination or automatic redirects are used.
    """

    def __init__(self, approved_host):
        self.approved_host = approved_host
        self.search_count = 0
        self.html_count = 0

    def request(self, request, *, timeout):
        parts = urlsplit(request.full_url)
        if parts.scheme != "https":
            raise LivePolicyError("Only HTTPS is allowed")
        answers = []

        def resolve(host, port, **kwargs):
            result = socket.getaddrinfo(host, port, **kwargs)
            answers.extend(result)
            return result

        try:
            normalized = validate_url(request.full_url, resolver=resolve)
        except FetchProblem as exc:
            if exc.kind == FetchError.DNS_ERROR:
                raise URLError("Live DNS lookup failed") from None
            raise LivePolicyError("URL policy rejected the request") from None
        except OSError:
            raise URLError("Live DNS lookup failed") from None
        parts = urlsplit(normalized)
        # Literal addresses are validated by validate_url without DNS.
        address = answers[0][4][0] if answers else parts.hostname
        connection = http.client.HTTPSConnection(parts.hostname, timeout=timeout,
                                                  context=ssl.create_default_context())

        def connect_pinned(destination, connection_timeout, source_address=None):
            return socket.create_connection((address, destination[1]), connection_timeout, source_address)

        connection._create_connection = connect_pinned
        try:
            connection.request("GET", urlunsplit(("", "", parts.path, parts.query, "")),
                               headers=dict(request.header_items()))
            return Response(connection.getresponse(), connection)
        except (OSError, http.client.HTTPException) as exc:
            connection.close()
            reason = (TimeoutError("Live HTTPS timeout") if isinstance(exc, TimeoutError)
                      else "Live HTTPS transport failed")
            raise URLError(reason) from None

    def search(self, request, *, timeout):
        parts = urlsplit(request.full_url)
        if (parts.scheme, parts.netloc, parts.path) != ("https", "serpapi.com", "/search.json"):
            raise LivePolicyError("Unexpected search endpoint")
        if self.search_count >= 2:
            raise LivePolicyError("Search request budget exhausted")
        self.search_count += 1
        params = parse_qs(parts.query)
        params["q"] = [params["q"][0] + " site:" + self.approved_host]
        params["num"] = ["1"]
        scoped = Request(urlunsplit((parts.scheme, parts.netloc, parts.path,
                                    urlencode(params, doseq=True), "")),
                         headers=dict(request.header_items()))
        with self.request(scoped, timeout=min(timeout, 10)) as response:
            if not 200 <= response.code < 300:
                raise HTTPError(provider.SERPAPI_ENDPOINT, response.code, "Search HTTP failure",
                                response.headers, None)
            # Sized HTTPResponse.read() can silently return a short body on
            # EOF. Consume the framing to completion within the existing cap.
            limit = 1024 * 1024
            expected_length = None
            # HTTPResponse decodes chunked framing and ignores Content-Length
            # in that case. Missing terminal chunks raise through Response.read.
            if response.headers.get("Transfer-Encoding", "").lower() != "chunked":
                lengths = response.headers.get_all("Content-Length", [])
                if len(lengths) > 1:
                    raise URLError("Invalid search response length")
                if lengths:
                    length = lengths[0].strip(" \t")
                    if not length.isascii() or not length.isdecimal():
                        raise URLError("Invalid search response length")
                    if len(length) > 20 or int(length) > limit:
                        raise URLError("Search response exceeded runner limit")
                    expected_length = int(length)
            body = bytearray()
            while True:
                chunk = response.read(min(65536, limit + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > limit:
                    raise URLError("Search response exceeded runner limit")
            if expected_length is not None and len(body) != expected_length:
                raise URLError("Incomplete search response body")
            # Without a declared length or chunked framing, EOF delimits the
            # body; an otherwise silent premature close cannot be distinguished.
            raw = bytes(body)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            return io.BytesIO(raw)  # Let the actual provider report invalid JSON.
        if isinstance(payload, dict) and isinstance(payload.get("organic_results"), list):
            items = payload["organic_results"]
            if all(isinstance(item, dict) and isinstance(item.get("link"), str) for item in items):
                # Enforce the approved site even if SerpApi ignores site:/num.
                payload["organic_results"] = [item for item in items
                    if urlsplit(item["link"]).hostname == self.approved_host
                    and urlsplit(item["link"]).scheme == "https"][:1]
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    def open(self, request, *, timeout):
        parts = urlsplit(request.full_url)
        if parts.hostname != self.approved_host:
            raise LivePolicyError("HTML or redirect left the approved site")
        if self.html_count >= 3:
            raise LivePolicyError("HTML request budget exhausted")
        self.html_count += 1
        # B retains content validation, body limits and manual redirect policy.
        return self.request(request, timeout=min(timeout, 10))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly enable approved live network use")
    parser.add_argument("--site-url", help="One approved public HTTPS site")
    args = parser.parse_args(argv)
    if not args.live:
        print("Live execution disabled. Separate approval and --live are required.")
        return 2
    # Subjects/keys stay in the environment, away from command-line history.
    try:
        if not os.environ.get("SERPAPI_API_KEY", "").strip():
            raise ValueError()
        subject = Subject.model_validate_json(os.environ["DFSA_LIVE_SUBJECT_JSON"])
        parts = urlsplit(args.site_url or "")
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)
                or parts.query or parts.fragment):
            raise ValueError()
    except (KeyError, ValueError):
        print("Invalid live configuration; require a key, subject JSON and approved HTTPS site URL.")
        return 2

    http = LiveHTTP(parts.hostname)
    try:
        with patch.object(provider, "urlopen", http.search), patch.object(fetch, "_build_opener", lambda: http), \
                patch.object(orchestrator, "run_search", run_search), \
                patch.object(orchestrator, "run_profiling", run_profiling), \
                patch.object(orchestrator, "run_risk", run_risk):
            result = orchestrator.run_pipeline(subject)
        outcome = ("external_failure" if result.errors else
                   "no_search_results" if result.summary.search_result_count == 0 else
                   "no_exposures" if not result.exposures else
                   "no_risk_paths" if not result.risk_paths else "completed")
        print(json.dumps({"status": result.status.value, "outcome": outcome,
                          "summary": result.summary.model_dump(),
                          "error_codes": [e.code for e in result.errors],
                          "search_requests": http.search_count, "html_requests": http.html_count}))
        return 1 if result.errors or result.status != "success" else 0
    except LivePolicyError:
        print("Live request stopped by site, URL or request-budget policy.")
        return 1
    except Exception:
        # Never print raw exceptions: they may carry subjects or key-bearing URLs.
        print("Unexpected live runner failure; no response data was logged.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
