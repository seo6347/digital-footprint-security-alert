
"""R01~R05 trigger and supporting exposure matching."""

from dataclasses import dataclass

from dfsa.contracts.common import ExposureType, RiskCategory
from dfsa.contracts.profiling import Exposure


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    triggers: frozenset[ExposureType]
    supporting: frozenset[ExposureType]
    category: RiskCategory


RULES = (
    RuleDefinition(
        "R01",
        frozenset({ExposureType.RELATIONSHIP}),
        frozenset({
            ExposureType.AFFILIATION,
            ExposureType.CONTACT,
        }),
        RiskCategory.AUTHORITY_IMPERSONATION,
    ),
    RuleDefinition(
        "R02",
        frozenset({
            ExposureType.AFFILIATION,
            ExposureType.INTEREST,
        }),
        frozenset({
            ExposureType.ACTIVITY,
            ExposureType.CONTACT,
        }),
        RiskCategory.ACADEMIC_IMPERSONATION,
    ),
    RuleDefinition(
        "R03",
        frozenset({
            ExposureType.ACTIVITY,
            ExposureType.INTEREST,
        }),
        frozenset({
            ExposureType.ACCOUNT,
            ExposureType.CONTACT,
        }),
        RiskCategory.RECRUITMENT_IMPERSONATION,
    ),
    RuleDefinition(
        "R04",
        frozenset({ExposureType.TEMPORAL}),
        frozenset({
            ExposureType.AFFILIATION,
            ExposureType.ACTIVITY,
            ExposureType.CONTACT,
        }),
        RiskCategory.EVENT_IMPERSONATION,
    ),
    RuleDefinition(
        "R05",
        frozenset({ExposureType.ACCOUNT}),
        frozenset({
            ExposureType.CONTACT,
            ExposureType.IDENTITY,
        }),
        RiskCategory.ACCOUNT_IMPERSONATION,
    ),
)


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    category: RiskCategory
    exposure_ids: tuple[str, ...]
    trigger_ids: tuple[str, ...]
    supporting_ids: tuple[str, ...]


def match_rules(exposures: list[Exposure]) -> list[RuleMatch]:
    """Find rule triggers and collect supporting exposure candidates."""

    present_types = {exp.type for exp in exposures}
    matches = []

    for rule in RULES:
        if not rule.triggers.issubset(present_types):
            continue

        trigger_ids = tuple(
            exp.exposure_id
            for exp in exposures
            if exp.type in rule.triggers
        )

        supporting_ids = tuple(
            exp.exposure_id
            for exp in exposures
            if exp.type in rule.supporting
        )

        used_ids = set(trigger_ids) | set(supporting_ids)

        exposure_ids = tuple(dict.fromkeys(
            exp.exposure_id
            for exp in exposures
            if exp.exposure_id in used_ids
        ))

        matches.append(
            RuleMatch(
                rule_id=rule.rule_id,
                category=rule.category,
                exposure_ids=exposure_ids,
                trigger_ids=trigger_ids,
                supporting_ids=supporting_ids,
            )
        )

    return matches

