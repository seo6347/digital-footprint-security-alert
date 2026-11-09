"""Build initial search queries from the subject."""

from dfsa.contracts.common import Subject


def _quote_term(value: str) -> str:
    """Normalize whitespace and quote a search term."""
    cleaned = " ".join(value.replace('"', " ").split())
    if not cleaned:
        raise ValueError("Search term must not be empty.")
    return f'"{cleaned}"'


def build_queries(subject: Subject) -> list[str]:
    """Build distinct name/organization and exact-email queries."""
    queries = [
        f"{_quote_term(subject.name)} {_quote_term(subject.organization)}",
        _quote_term(str(subject.email)),
    ]

    # Preserve query order while removing duplicates.
    return list(dict.fromkeys(queries))
