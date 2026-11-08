"""Conservative URL/DNS preflight for Module B.

This does NOT pin urllib's connection to validated DNS answers. DNS rebinding
between preflight and connection remains possible. Production use of untrusted
URLs needs reviewed egress isolation or an IP-pinned transport preserving TLS
hostname verification. getaddrinfo also has no portable per-call timeout.
"""

import ipaddress
import re
import socket
from collections.abc import Callable
from urllib.parse import quote, urlsplit, urlunsplit

from ._types import FetchError, FetchProblem

Resolver = Callable[..., list]

# Explicit exclusions make conservative policy stable on older Python patches.
_DENIED_NETWORKS = tuple(map(ipaddress.ip_network, (
    "0.0.0.0/8", "100.64.0.0/10", "192.0.0.0/24", "192.0.2.0/24",
    "192.88.99.0/24", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "240.0.0.0/4",
    "168.63.129.16/32",  # Azure platform virtual address
    "64:ff9b::/96", "64:ff9b:1::/48", "100::/64", "2001::/23",
    "2001:db8::/32", "2002::/16", "3fff::/20",
)))
_INTERNAL_SUFFIXES = ("localhost", "local", "internal", "lan", "home", "home.arpa")


def check_url_text(url: str) -> None:
    """Check before urlsplit/urljoin can silently discard characters."""
    if not url or any(ord(c) <= 32 or ord(c) == 127 or c.isspace() for c in url) or "\\" in url:
        raise FetchProblem(FetchError.INVALID_URL, "URL contains ambiguous characters")
    if re.search(r"%(?![0-9a-fA-F]{2})", url):
        raise FetchProblem(FetchError.INVALID_URL, "Malformed URL escape")


def _check_ip(value: str) -> None:
    if "%" in value:
        raise FetchProblem(FetchError.BLOCKED_URL, "Scoped DNS address")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise FetchProblem(FetchError.DNS_ERROR, "Unusable DNS address") from exc
    forbidden = (
        not address.is_global or address.is_private or address.is_reserved
        or address.is_loopback or address.is_link_local or address.is_multicast
        or address.is_unspecified
        or any(address.version == net.version and address in net for net in _DENIED_NETWORKS)
    )
    if isinstance(address, ipaddress.IPv6Address):
        # Reject mapped and transition forms rather than delegating their routing.
        forbidden |= address.ipv4_mapped is not None or address.sixtofour is not None or address.teredo is not None
    if forbidden:
        raise FetchProblem(FetchError.BLOCKED_URL, "Non-public or platform IP address")


def validate_url(url: str, *, resolver: Resolver | None = None) -> str:
    """Return the exact normalized URL to request, or fail closed before HTTP."""
    check_url_text(url)
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in ("http", "https"):
            raise ValueError("Only HTTP(S) is supported")
        if not parts.netloc or not parts.hostname or "@" in parts.netloc or "%" in parts.netloc:
            raise ValueError("Missing or ambiguous host, userinfo or zone identifier")
        port = parts.port
        expected_port = 443 if parts.scheme.lower() == "https" else 80
        if port is not None and port != expected_port:
            raise ValueError("Only default HTTP(S) ports are supported")
        if parts.netloc.endswith(":"):
            raise ValueError("Empty port")
        host = parts.hostname
        # Brackets must describe an IPv6 literal, with nothing after the port.
        if ":" in host:
            address = ipaddress.IPv6Address(host)
            host = str(address)
            authority = f"[{host}]"
        else:
            host = host.removesuffix(".").encode("idna").decode("ascii").lower()
            if len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
                raise ValueError("Invalid hostname")
            authority = host
        if parts.netloc.startswith("["):
            suffix = parts.netloc[parts.netloc.index("]") + 1:]
            if suffix and suffix != f":{expected_port}":
                raise ValueError("Ambiguous IPv6 authority")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is None:
            labels = host.split(".")
            if len(labels) < 2 or any(host == s or host.endswith("." + s) for s in _INTERNAL_SUFFIXES):
                raise FetchProblem(FetchError.BLOCKED_URL, "Internal hostname")
            if all(re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", label) for label in labels):
                raise ValueError("Non-standard numeric IP representation")
        else:
            _check_ip(str(literal))
        if literal is None:
            answers = (resolver or socket.getaddrinfo)(host, expected_port, type=socket.SOCK_STREAM)
            if not answers:
                raise FetchProblem(FetchError.DNS_ERROR, "DNS returned no addresses")
            for family, _, _, _, sockaddr in answers:
                if family not in (socket.AF_INET, socket.AF_INET6) or not sockaddr:
                    raise FetchProblem(FetchError.DNS_ERROR, "Unsupported DNS address family")
                _check_ip(sockaddr[0])
        return urlunsplit((parts.scheme.lower(), authority,
                           quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                           quote(parts.query, safe="/%?:@!$&'()*+,;=-._~"), ""))
    except (ValueError, UnicodeError) as exc:
        raise FetchProblem(FetchError.INVALID_URL, "Malformed URL or unsupported port") from exc
