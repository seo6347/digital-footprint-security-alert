
import pytest

from dfsa.modules.risk.relation_types import RelationType
from dfsa.modules.risk.relation_patterns import (
    RELATION_PATTERNS,
    get_relation_pattern,
)
from dfsa.modules.risk.relation_verifier import (
    RelationCandidate,
    RelationEvidenceStatus,
    classify_typed_relation,
)


def make_candidate(relation_type, evidence):
    return RelationCandidate(
        exposure_id_1="exp_001",
        exposure_id_2="exp_002",
        source_id="src_001",
        evidence=evidence,
        has_relation_cue=False,
        has_negation_cue=False,
        relation_types=(relation_type,),
    )


def test_all_relation_types_have_patterns():
    assert set(RELATION_PATTERNS) == set(RelationType)


@pytest.mark.parametrize(
    "relation_type, evidence",
    [
        (
            RelationType.AUTHORITY_AFFILIATION,
            "홍길동의 지도교수는 김철수이다.",
        ),
        (
            RelationType.ACADEMIC_AFFILIATION_INTEREST,
            "AI 연구실의 연구 분야는 보안이다.",
        ),
        (
            RelationType.CAREER_ACTIVITY_INTEREST,
            "홍길동은 보안 프로젝트를 개발했다.",
        ),
        (
            RelationType.EVENT_ACTIVITY,
            "홍길동은 학회 발표 예정이다.",
        ),
        (
            RelationType.ACCOUNT_CONTACT,
            "GitHub 계정의 이메일은 sample@example.com이다.",
        ),
    ],
)
def test_positive_patterns(relation_type, evidence):
    candidate = make_candidate(relation_type, evidence)

    result = classify_typed_relation(candidate, relation_type)

    assert result == RelationEvidenceStatus.SUPPORTED_CANDIDATE


def test_negative_pattern():
    relation_type = RelationType.ACCOUNT_IDENTITY
    candidate = make_candidate(
        relation_type,
        "홍길동의 본인 계정이 아니다.",
    )

    result = classify_typed_relation(candidate, relation_type)

    assert result == RelationEvidenceStatus.CONTRADICTED


def test_unrelated_keyword_is_not_sufficient():
    relation_type = RelationType.ACCOUNT_CONTACT
    candidate = make_candidate(
        relation_type,
        "홍길동의 지도교수는 김철수이다.",
    )

    result = classify_typed_relation(candidate, relation_type)

    assert result == RelationEvidenceStatus.UNCERTAIN


def test_mismatched_relation_type():
    candidate = make_candidate(
        RelationType.ACCOUNT_CONTACT,
        "학교 이메일이 공개되어 있다.",
    )

    assert classify_typed_relation(
        candidate,
        RelationType.EVENT_ACTIVITY,
    ) == RelationEvidenceStatus.UNCERTAIN

