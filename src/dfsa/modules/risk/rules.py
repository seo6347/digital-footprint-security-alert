
"""DFSA Module C - R01~R05 risk rule trigger detection."""

from dataclasses import dataclass

from dfsa.contracts.common import ExposureType, RiskCategory
from dfsa.contracts.profiling import Exposure


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    triggers: frozenset[ExposureType]
    category: RiskCategory


RULES = (
    RuleDefinition(
        "R01",
        frozenset({ExposureType.RELATIONSHIP}),
        RiskCategory.AUTHORITY_IMPERSONATION,
    ),
    RuleDefinition(
        "R02",
        frozenset({
            ExposureType.AFFILIATION,
            ExposureType.INTEREST,
        }),
        RiskCategory.ACADEMIC_IMPERSONATION,
    ),
    RuleDefinition(
        "R03",
        frozenset({
            ExposureType.ACTIVITY,
            ExposureType.INTEREST,
        }),
        RiskCategory.RECRUITMENT_IMPERSONATION,
    ),
    RuleDefinition(
        "R04",
        frozenset({ExposureType.TEMPORAL}),
        RiskCategory.EVENT_IMPERSONATION,
    ),
    RuleDefinition(
        "R05",
        frozenset({ExposureType.ACCOUNT}),
        RiskCategory.ACCOUNT_IMPERSONATION,
    ),
)


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    category: RiskCategory
    exposure_ids: tuple[str, ...]


def match_rules(exposures: list[Exposure]) -> list[RuleMatch]:
    """Return rules whose required trigger types are present."""

    matches = []

    for rule in RULES:
        present_types = {exposure.type for exposure in exposures}

        if not rule.triggers.issubset(present_types):
            continue

        matched_ids = tuple(
            exposure.exposure_id
            for exposure in exposures
            if exposure.type in rule.triggers
        )

        matches.append(
            RuleMatch(
                rule_id=rule.rule_id,
                category=rule.category,
                exposure_ids=matched_ids,
            )
        )

    return matches

