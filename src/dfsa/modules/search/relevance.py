"""Assess preliminary relevance using search-result metadata."""

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


def _contains_exact_email(text: str, email: str | None) -> bool:
    """Match an email without accepting part of a longer address."""
    if email is None:
        return False

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


def _get_org_variants(org: str) -> list[str]:
    """'숭실대학교' -> ['숭실대학교', '숭실대'] 약어 변환 지원."""
    cleaned = org.strip()
    variants = [cleaned]
    if cleaned.endswith("대학교"):
        variants.append(cleaned[:-3] + "대")
    elif cleaned.endswith("대학"):
        variants.append(cleaned[:-2] + "대")
    return list(dict.fromkeys(variants))


def assess_relevance(
    subject: Subject,
    *,
    url: str,
    title: str | None = None,
    snippet: str | None = None,
) -> Relevance:
    """Assess preliminary relevance from URL, title, and snippet."""
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

    org_variants = _get_org_variants(subject.organization)
    organization_match = any(
        _contains_term(field, org_var)
        for field in fields
        for org_var in org_variants
    )

    email_exact_match = False
    if subject.email is not None and subject.email.strip():
        email_exact_match = any(
            _contains_exact_email(field, subject.email)
            for field in fields
        )

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