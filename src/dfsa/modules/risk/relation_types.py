
"""Relation taxonomy shared by R01-R05."""

from dataclasses import dataclass
from enum import Enum

from dfsa.contracts.common import ExposureType


class RelationType(str, Enum):
    AUTHORITY_AFFILIATION = "authority_affiliation"
    AUTHORITY_CONTACT = "authority_contact"

    ACADEMIC_AFFILIATION_INTEREST = "academic_affiliation_interest"
    ACADEMIC_ACTIVITY = "academic_activity"
    ACADEMIC_CONTACT = "academic_contact"

    CAREER_ACTIVITY_INTEREST = "career_activity_interest"
    CAREER_ACCOUNT = "career_account"
    CAREER_CONTACT = "career_contact"

    EVENT_AFFILIATION = "event_affiliation"
    EVENT_ACTIVITY = "event_activity"
    EVENT_CONTACT = "event_contact"

    ACCOUNT_CONTACT = "account_contact"
    ACCOUNT_IDENTITY = "account_identity"


@dataclass(frozen=True)
class RelationDefinition:
    relation_type: RelationType
    rule_id: str
    allowed_pairs: frozenset[frozenset[ExposureType]]
    description: str


def pair(
    left: ExposureType,
    right: ExposureType,
) -> frozenset[ExposureType]:
    return frozenset((left, right))


RELATIONS = (
    RelationDefinition(
        RelationType.AUTHORITY_AFFILIATION,
        "R01",
        frozenset({
            pair(ExposureType.RELATIONSHIP, ExposureType.AFFILIATION),
        }),
        "권위자 관계와 소속 기관 사이의 명시적 연결",
    ),
    RelationDefinition(
        RelationType.AUTHORITY_CONTACT,
        "R01",
        frozenset({
            pair(ExposureType.RELATIONSHIP, ExposureType.CONTACT),
        }),
        "권위자 관계와 연락처 사이의 명시적 연결",
    ),
    RelationDefinition(
        RelationType.ACADEMIC_AFFILIATION_INTEREST,
        "R02",
        frozenset({
            pair(ExposureType.AFFILIATION, ExposureType.INTEREST),
        }),
        "소속 기관과 연구 관심 분야의 연결",
    ),
    RelationDefinition(
        RelationType.ACADEMIC_ACTIVITY,
        "R02",
        frozenset({
            pair(ExposureType.INTEREST, ExposureType.ACTIVITY),
            pair(ExposureType.AFFILIATION, ExposureType.ACTIVITY),
        }),
        "연구 관심 분야 또는 소속과 학술 활동의 연결",
    ),
    RelationDefinition(
        RelationType.ACADEMIC_CONTACT,
        "R02",
        frozenset({
            pair(ExposureType.AFFILIATION, ExposureType.CONTACT),
        }),
        "학술 소속과 연락처의 연결",
    ),
    RelationDefinition(
        RelationType.CAREER_ACTIVITY_INTEREST,
        "R03",
        frozenset({
            pair(ExposureType.ACTIVITY, ExposureType.INTEREST),
        }),
        "활동 이력과 관심 분야의 연결",
    ),
    RelationDefinition(
        RelationType.CAREER_ACCOUNT,
        "R03",
        frozenset({
            pair(ExposureType.ACTIVITY, ExposureType.ACCOUNT),
            pair(ExposureType.INTEREST, ExposureType.ACCOUNT),
        }),
        "활동 또는 관심 분야와 공개 계정의 연결",
    ),
    RelationDefinition(
        RelationType.CAREER_CONTACT,
        "R03",
        frozenset({
            pair(ExposureType.ACTIVITY, ExposureType.CONTACT),
        }),
        "활동 이력과 연락처의 연결",
    ),
    RelationDefinition(
        RelationType.EVENT_AFFILIATION,
        "R04",
        frozenset({
            pair(ExposureType.TEMPORAL, ExposureType.AFFILIATION),
        }),
        "일정과 소속 기관의 연결",
    ),
    RelationDefinition(
        RelationType.EVENT_ACTIVITY,
        "R04",
        frozenset({
            pair(ExposureType.TEMPORAL, ExposureType.ACTIVITY),
        }),
        "일정과 활동의 연결",
    ),
    RelationDefinition(
        RelationType.EVENT_CONTACT,
        "R04",
        frozenset({
            pair(ExposureType.TEMPORAL, ExposureType.CONTACT),
        }),
        "일정과 연락처의 연결",
    ),
    RelationDefinition(
        RelationType.ACCOUNT_CONTACT,
        "R05",
        frozenset({
            pair(ExposureType.ACCOUNT, ExposureType.CONTACT),
        }),
        "공개 계정과 연락처의 연결",
    ),
    RelationDefinition(
        RelationType.ACCOUNT_IDENTITY,
        "R05",
        frozenset({
            pair(ExposureType.ACCOUNT, ExposureType.IDENTITY),
        }),
        "공개 계정과 사용자 신원의 연결",
    ),
)


def get_relations_for_rule(rule_id: str) -> list[RelationDefinition]:
    """Return relation definitions used by one rule."""
    return [
        relation
        for relation in RELATIONS
        if relation.rule_id == rule_id
    ]


def is_valid_relation_pair(
    relation_type: RelationType,
    left: ExposureType,
    right: ExposureType,
) -> bool:
    """Check whether exposure types are valid for a relation."""

    for relation in RELATIONS:
        if relation.relation_type == relation_type:
            return pair(left, right) in relation.allowed_pairs

    return False

