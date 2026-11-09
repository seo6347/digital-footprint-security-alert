"""Assess preliminary relevance using search-result metadata.

A candidate result does not confirm identity.
Final identity verification belongs to Module B.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlsplit


from dfsa.contracts.common import Subject
from dfsa.contracts.search import Relevance


def _normalize_text(value: str) -> str:
    """Normalize Unicode, letter case, and whitespace."""
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.casefold().split())


def _contains_term(text: str, term: str) -> bool:
    """Match a term without matching inside a longer word."""
    normalized_text = _normalize_text(text)
    normalized_term = _normalize_text(term)

    if not normalized_term:
        return False

    pattern = (
        r"(?<!\w)"
        + re.escape(normalized_term)
        + r"(?!\w)"
    )

    return re.search(pattern, normalized_text) is not None


def _contains_exact_email(text: str, email: str) -> bool:
    """Match an email without accepting part of a longer address."""
    normalized_text = _normalize_text(text)
    normalized_email = _normalize_text(email)

    if not normalized_email:
        return False

    pattern = (
        r"(?<![\w.!#$%&'*+/=?^`{|}~@-])"
        + re.escape(normalized_email)
        + r"(?![\w@.-])"
    )

    return re.search(pattern, normalized_text) is not None


def assess_relevance(
    subject: Subject,
    *,
    url: str,
    title: str | None = None,
    snippet: str | None = None,
) -> Relevance:
    """Assess preliminary relevance from URL, title, and snippet.

    Policy:
    - Exact email match -> candidate
    - Name and organization match -> candidate
    - Otherwise -> uncertain

    No page fetching or identity verification is performed.
    """
        # Parse query values separately so URL separators such as "="
    # do not interfere with email boundary checks.
    # parse_qsl already decodes percent-encoded query values.
    query_values = [
        value
        for _, value in parse_qsl(
            urlsplit(url).query,
            keep_blank_values=True,
        )
    ]

    fields = (
        unquote(url),
        title or "",
        snippet or "",
        *query_values,
    )


    name_match = any(
        _contains_term(field, subject.name)
        for field in fields
    )

    organization_match = any(
        _contains_term(field, subject.organization)
        for field in fields
    )

    email_exact_match = any(
        _contains_exact_email(field, str(subject.email))
        for field in fields
    )

    # Let the existing contract validate reason and status values.
    reasons = []

    if name_match:
        reasons.append("name_match")

    if organization_match:
        reasons.append("organization_match")

    if email_exact_match:
        reasons.append("email_exact_match")

    if email_exact_match or (name_match and organization_match):
        return Relevance(
            status="candidate",
            reasons=reasons,
        )

    reasons.append("insufficient_evidence")

    return Relevance(
        status="uncertain",
        reasons=reasons,
    )
