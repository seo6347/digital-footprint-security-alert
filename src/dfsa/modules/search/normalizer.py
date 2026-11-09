"""Conservative URL normalization for search result deduplication."""

from urllib.parse import urlsplit, urlunsplit, unquote_plus


class URLNormalizationError(ValueError):
    """Raised when a URL cannot be safely normalized."""

def _remove_tracking_params(query: str) -> str:
    """utm_* 파라미터만 제거하고 나머지 항목은 원형을 보존한다."""
    if not query:
        return query

    kept_parts: list[str] = []

    for part in query.split("&"):
        # 값이 아닌 파라미터 이름만 확인한다.
        raw_name = part.partition("=")[0]
        name = unquote_plus(raw_name).casefold()

        if name.startswith("utm_"):
            continue

        kept_parts.append(part)

    return "&".join(kept_parts)

def normalize_url(url: str) -> str:
    """Create a comparison URL while preserving page-identifying data.

    Rules:
    - Accept absolute HTTP and HTTPS URLs only.
    - Remove surrounding whitespace.
    - Lowercase the scheme and hostname.
    - Remove default ports.
    - Convert an empty path to "/".
    - Remove fragments.
    - Preserve path case, trailing slashes, and query parameters.
    """
    if not isinstance(url, str) or not url.strip():
        raise URLNormalizationError("URL must not be empty.")

    cleaned = url.strip()

    # Check before parsing because URL parsers may silently remove
    # some control characters.
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127
           for char in cleaned):
        raise URLNormalizationError(
            "URL must not contain whitespace or control characters."
        )

    if "\\" in cleaned:
        raise URLNormalizationError(
            "URL must not contain backslashes."
        )

    try:
        parts = urlsplit(cleaned)

        if parts.scheme not in ("http", "https"):
            raise URLNormalizationError(
                "Only HTTP and HTTPS URLs are supported."
            )

        hostname = parts.hostname

        if not hostname:
            raise URLNormalizationError(
                "URL must include a hostname."
            )

        # Search result URLs should not contain embedded credentials.
        if parts.username is not None or parts.password is not None:
            raise URLNormalizationError(
                "URLs with embedded credentials are not supported."
            )

        # Accessing .port validates malformed and out-of-range ports.
        port = parts.port

    except ValueError as exc:
        # Preserve our own errors while hiding raw URL parser details.
        if isinstance(exc, URLNormalizationError):
            raise

        raise URLNormalizationError(
            "URL has an invalid structure."
        ) from None

    hostname = hostname.lower()

    # IPv6 addresses require brackets in the reconstructed URL.
    host = f"[{hostname}]" if ":" in hostname else hostname

    is_default_port = (
        parts.scheme == "http" and port == 80
    ) or (
        parts.scheme == "https" and port == 443
    )

    if port is not None and not is_default_port:
        host = f"{host}:{port}"

    return urlunsplit(
        (
            parts.scheme.lower(),
            host,
            parts.path or "/",
            _remove_tracking_params(parts.query),
            "",  # Fragment is excluded from the comparison URL.
        )
    )
