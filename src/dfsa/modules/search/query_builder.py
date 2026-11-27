"""Build initial search queries from the subject."""

from dfsa.contracts.common import Subject


def _quote_term(value: str) -> str:
    """Normalize whitespace and quote a search term."""
    cleaned = " ".join(value.replace('"', " ").split())
    if not cleaned:
        raise ValueError("Search term must not be empty.")
    return f'"{cleaned}"'


def _get_org_variants(org: str) -> list[str]:
    """'숭실대학교' -> ['숭실대학교', '숭실대'] 약어 변환 지원."""
    cleaned = org.strip()
    variants = [cleaned]
    if cleaned.endswith("대학교"):
        variants.append(cleaned[:-3] + "대")
    elif cleaned.endswith("대학"):
        variants.append(cleaned[:-2] + "대")
    return list(dict.fromkeys(variants))


def build_queries(subject: Subject) -> list[str]:
    """이름, 소속(약어 포함), 이메일 정보를 바탕으로 중복 없는 검색어 리스트를 생성한다."""
    name_q = _quote_term(subject.name)
    org_variants = _get_org_variants(subject.organization)

    queries = []
    for org in org_variants:
        org_q = _quote_term(org)
        queries.append(f"{name_q} {org_q}")
        queries.append(f"{name_q} {org_q} 연구실")
        queries.append(f"{name_q} {org_q} lab")

    if subject.email and str(subject.email).strip():
        queries.append(_quote_term(str(subject.email).strip()))

    return list(dict.fromkeys(queries))