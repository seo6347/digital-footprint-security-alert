"""Build initial search queries for Module A v0.2."""

from dfsa.contracts.common import Subject


def build_queries_v2(subject: Subject) -> list[str]:
    """v0.2 명세 §5.2 규격: 이름 + 공백 + 소속 단일 검색어를 생성한다."""
    name = subject.name.strip()
    org = subject.organization.strip()

    if not name or not org:
        raise ValueError("Name and organization must not be empty.")

    return [f"{name} {org}"]