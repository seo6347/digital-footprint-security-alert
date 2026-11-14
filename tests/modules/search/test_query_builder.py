import pytest

from dfsa.contracts.common import Subject
from dfsa.modules.search.query_builder import build_queries


def test_build_queries():
    subject = Subject(
        name="홍길동",
        organization="OO대학교",
        email="gildong@example.ac.kr",
    )

    assert build_queries(subject) == [
        '"홍길동" "OO대학교"',
        '"gildong@example.ac.kr"',
    ]


def test_build_queries_normalizes_whitespace():
    subject = Subject(
        name="  홍길동  ",
        organization="  OO대학교   컴퓨터학부  ",
        email="gildong@example.ac.kr",
    )

    assert build_queries(subject)[0] == '"홍길동" "OO대학교 컴퓨터학부"'


def test_build_queries_handles_embedded_quotes():
    subject = Subject(
        name='홍"길동',
        organization='"OO대학교"',
        email="gildong@example.ac.kr",
    )

    assert build_queries(subject)[0] == '"홍 길동" "OO대학교"'


@pytest.mark.parametrize("field", ["name", "organization"])
def test_build_queries_rejects_blank_terms(field):
    data = {
        "name": "홍길동",
        "organization": "OO대학교",
        "email": "gildong@example.ac.kr",
    }
    data[field] = "   "
    subject = Subject(**data)

    with pytest.raises(ValueError, match="must not be empty"):
        build_queries(subject)


def test_build_queries_does_not_modify_subject():
    subject = Subject(
        name="  홍길동  ",
        organization="OO대학교",
        email="gildong@example.ac.kr",
    )
    original = subject.model_dump()

    build_queries(subject)

    assert subject.model_dump() == original
