"""Shared policy and pinned HTTPS for v0.2 Explorer and its Live Runner."""

import http.client
import ipaddress
import math
import re
import socket
import ssl
from contextlib import contextmanager
from queue import Empty, Queue
from threading import Thread, Timer
from time import monotonic
from urllib.error import URLError
from urllib.parse import unquote, urlsplit, urlunsplit

from ._types import FetchError, FetchProblem
from .url_policy import check_url_text, validate_url


USER_AGENT = "DFSA/0.2"


class DeadlineExceeded(TimeoutError):
    """The waiting HTTP client or DNS caller reached its absolute deadline."""


def remaining(deadline, clock=monotonic):
    seconds = deadline - clock()
    if seconds <= 0:
        raise DeadlineExceeded("Explorer deadline exceeded")
    return seconds


def _bounded_dns(resolve, host, port, timeout, **kwargs):
    result = Queue(maxsize=1)

    def lookup():
        try:
            result.put((resolve(host, port, **kwargs), None))
        except Exception as exc:
            result.put((None, exc))

    Thread(target=lookup, daemon=True).start()
    try:
        answers, error = result.get(timeout=timeout)
    except Empty:
        raise DeadlineExceeded("DNS deadline exceeded") from None
    if error is not None:
        raise error
    return answers


def _https_url(url):
    check_url_text(url)
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.port not in (None, 443)
            or "@" in parts.netloc or "%" in parts.netloc or parts.netloc.endswith(":")):
        raise ValueError("An exact HTTPS host is required")
    normalized = validate_url(url, resolve=False)
    parts = urlsplit(normalized)
    try:
        ipaddress.ip_address(parts.hostname)
    except ValueError:
        return normalized, parts
    raise ValueError("A named HTTPS host is required")


def _scope_path(path):
    if re.search("%(?:2f|5c|25)", path, re.IGNORECASE):
        raise ValueError("Ambiguous path escapes")
    decoded = unquote(path, errors="strict")
    if (any(part in {".", ".."} for part in decoded.split("/")) or "//" in decoded
            or any(char in "\\;?#" or ord(char) <= 32 or ord(char) == 127 for char in decoded)):
        raise ValueError("Ambiguous URL path")
    return decoded


class SiteScope:
    """A reviewed HTTPS page, or a subtree when the configured path ends in /."""

    def __init__(self, site_url):
        try:
            supplied = urlsplit(site_url)
            _, parts = _https_url(site_url)
            if supplied.query or supplied.fragment or parts.hostname == "serpapi.com":
                raise ValueError("Invalid approved site URL")
            self.host = parts.hostname
            self.path = _scope_path(parts.path)
        except (FetchProblem, UnicodeError, ValueError):
            raise ValueError("Expected an approved HTTPS page or subtree") from None

    @property
    def robots_url(self):
        return f"https://{self.host}/robots.txt"

    def prepare(self, url):
        """Validate path/host before DNS or network access."""
        try:
            normalized, parts = _https_url(url)
            path = _scope_path(parts.path)
            if parts.hostname == self.host and (
                path.startswith(self.path) if self.path.endswith("/") else path == self.path
            ):
                return normalized
        except (FetchProblem, UnicodeError, ValueError):
            pass
        raise FetchProblem(FetchError.BLOCKED_URL, "Page is outside the approved HTTPS scope")

    def contains(self, url):
        try:
            self.prepare(url)
        except FetchProblem:
            return False
        return True


class _HopResponse:
    def __init__(self, response, connection, deadline, clock, watchdog):
        self._response = response
        self._connection = connection
        self._deadline = deadline
        self._clock = clock
        self._watchdog = watchdog
        self.code = response.status
        self.headers = response.headers

    def read(self, size=-1):
        remaining(self._deadline, self._clock)
        try:
            chunk = self._response.read(size)
        except TimeoutError:
            raise URLError(TimeoutError("HTTPS body read timed out")) from None
        except (OSError, http.client.HTTPException):
            remaining(self._deadline, self._clock)
            raise URLError("HTTPS body read failed") from None
        remaining(self._deadline, self._clock)
        return chunk

    def close(self):
        self._watchdog.cancel()
        try:
            self._response.close()
        finally:
            self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class PinnedHTTPS:
    """A single GET hop with public DNS checks, pinned IP, and hostname TLS."""

    def __init__(self, *, resolve=None, connect=None, clock=monotonic):
        self._resolve = resolve or socket.getaddrinfo
        self._connect = connect or socket.socket.connect
        self.clock = clock

    def request(self, url, *, deadline, headers, on_request=lambda: None):
        answers = []

        def resolve(host, port, **kwargs):
            answers.extend(_bounded_dns(self._resolve, host, port, remaining(deadline, self.clock), **kwargs))
            return answers

        _, approved = _https_url(url)
        validate_url(url, resolver=resolve)
        if not answers:
            raise FetchProblem(FetchError.DNS_ERROR, "No public DNS answer")
        family, kind, protocol, _, address = answers[0]

        def connect_pinned(destination, timeout, source_address=None):
            sock = socket.socket(family, kind, protocol)
            try:
                sock.settimeout(remaining(deadline, self.clock))
                self._connect(sock, address)
                sock.settimeout(remaining(deadline, self.clock))
                return sock
            except BaseException:
                sock.close()
                raise

        conn = http.client.HTTPSConnection(
            approved.hostname, timeout=remaining(deadline, self.clock), context=ssl.create_default_context(),
        )
        conn._create_connection = connect_pinned
        watchdog = None
        response = None
        handed_off = False
        try:
            conn.connect()
            tls_socket = conn.sock

            def interrupt_read():
                try:
                    tls_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            timeout = remaining(deadline, self.clock)
            tls_socket.settimeout(timeout)
            watchdog = Timer(timeout, interrupt_read)
            watchdog.daemon = True
            watchdog.start()
            on_request()
            # A's already encoded request target is forwarded intact.
            conn.request("GET", urlunsplit(("", "", approved.path or "/", approved.query, "")), headers=headers)
            response = conn.getresponse()
            remaining(deadline, self.clock)
            handed_off = True
            return _HopResponse(response, conn, deadline, self.clock, watchdog)
        except (OSError, http.client.HTTPException):
            remaining(deadline, self.clock)
            raise
        finally:
            if not handed_off:
                if watchdog is not None:
                    watchdog.cancel()
                try:
                    if response is not None:
                        response.close()
                finally:
                    conn.close()
