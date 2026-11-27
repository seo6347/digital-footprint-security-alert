"""Build initial search queries from the subject."""

from dfsa._v01.contracts.common import Subject


def _quote_term(value: str) -> str:
    """Normalize whitespace and quote a search term."""
    cleaned = " ".join(value.replace('"', " ").split())
    if not cleaned:
        raise ValueError("Search term must not be empty.")
    return f'"{cleaned}"'

# query_builder.py

def build_queries(subject: Subject) -> list[str]:
    """Subject 정보를 바탕으로 중복 없는 검색어 리스트를 생성한다."""
    name_q = _quote_term(subject.name)
    org_q = _quote_term(subject.organization)

    queries = [
        f"{name_q} {org_q}",
        f"{name_q} {org_q} 연구실",
        f"{name_q} {org_q} lab",
    ]

    # subject.email이 None이 아니고 공백이 아닌 경우에만 쿼리 추가
    if subject.email is not None and subject.email.strip():
        queries.append(_quote_term(subject.email.strip()))

    return list(dict.fromkeys(queries))
