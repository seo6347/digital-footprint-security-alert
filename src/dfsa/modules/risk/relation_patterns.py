
"""Relation-specific evidence cue patterns for R01-R05."""

from dataclasses import dataclass

from .relation_types import RelationType


@dataclass(frozen=True)
class RelationPattern:
    positive: tuple[str, ...]
    negative: tuple[str, ...]


RELATION_PATTERNS = {
    # R01: Authority impersonation
    RelationType.AUTHORITY_AFFILIATION: RelationPattern(
        positive=(
            "지도교수", "지도받", "소속",
            "supervised by", "advisor",
        ),
        negative=(
            "지도교수가 아니", "소속이 아니",
            "소속되어 있지 않", "not supervised",
        ),
    ),
    RelationType.AUTHORITY_CONTACT: RelationPattern(
        positive=(
            "연락처", "이메일", "contact email",
        ),
        negative=(
            "연락처가 아니", "이메일이 아니",
            "not contact",
        ),
    ),

    # R02: Academic impersonation
    RelationType.ACADEMIC_AFFILIATION_INTEREST: RelationPattern(
        positive=(
            "연구 분야", "연구 주제", "전공",
            "research area", "specializes in",
        ),
        negative=(
            "연구 분야가 아니", "전공이 아니",
            "does not specialize",
        ),
    ),
    RelationType.ACADEMIC_ACTIVITY: RelationPattern(
        positive=(
            "논문", "연구 수행", "학술 활동",
            "published", "research project",
        ),
        negative=(
            "참여하지 않", "수행하지 않",
            "did not participate",
        ),
    ),
    RelationType.ACADEMIC_CONTACT: RelationPattern(
        positive=(
            "학교 이메일", "연구실 이메일",
            "contact email",
        ),
        negative=(
            "연락처가 아니", "이메일이 아니",
            "not contact",
        ),
    ),

    # R03: Recruitment impersonation
    RelationType.CAREER_ACTIVITY_INTEREST: RelationPattern(
        positive=(
            "프로젝트", "개발", "기술",
            "worked on", "developed",
        ),
        negative=(
            "참여하지 않", "개발하지 않",
            "did not work on",
        ),
    ),
    RelationType.CAREER_ACCOUNT: RelationPattern(
        positive=(
            "github", "포트폴리오", "프로필",
            "repository", "portfolio",
        ),
        negative=(
            "본인 계정이 아니", "소유하지 않",
            "does not own",
        ),
    ),
    RelationType.CAREER_CONTACT: RelationPattern(
        positive=(
            "연락처", "이메일", "contact",
        ),
        negative=(
            "연락처가 아니", "이메일이 아니",
            "not contact",
        ),
    ),

    # R04: Event impersonation
    RelationType.EVENT_AFFILIATION: RelationPattern(
        positive=(
            "주최", "소속", "행사 일정",
            "organized by", "hosted by",
        ),
        negative=(
            "주최하지 않", "소속이 아니",
            "not hosted by",
        ),
    ),
    RelationType.EVENT_ACTIVITY: RelationPattern(
        positive=(
            "참석", "참여", "발표 예정",
            "scheduled to", "participating",
        ),
        negative=(
            "참석하지 않", "참여하지 않",
            "did not attend",
        ),
    ),
    RelationType.EVENT_CONTACT: RelationPattern(
        positive=(
            "행사 문의", "담당자 연락처",
            "registration email", "contact email",
        ),
        negative=(
            "담당자가 아니", "연락처가 아니",
            "not contact",
        ),
    ),

    # R05: Account impersonation
    RelationType.ACCOUNT_CONTACT: RelationPattern(
        positive=(
            "연락처", "이메일", "contact email",
            "email address",
        ),
        negative=(
            "이메일이 아니", "연락처가 아니",
            "not associated with",
        ),
    ),
    RelationType.ACCOUNT_IDENTITY: RelationPattern(
        positive=(
            "본인 계정", "운영하는 계정",
            "account belongs to", "owned by",
        ),
        negative=(
            "본인 계정이 아니", "소유하지 않",
            "does not belong to",
        ),
    ),
}


def get_relation_pattern(
    relation_type: RelationType,
) -> RelationPattern:
    """Return evidence cues for a relation type."""

    return RELATION_PATTERNS[relation_type]

