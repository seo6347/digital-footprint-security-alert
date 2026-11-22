
"""Conservative rule-based risk path status for DFSA v0.1."""

from dfsa.contracts.common import ExposureType, RiskPathStatus
from dfsa.contracts.profiling import Exposure

from .rules import RuleMatch


def determine_path_status(
    match: RuleMatch,
    exposures: list[Exposure],
) -> RiskPathStatus:
    """Determine scenario support without inventing relationships."""

    exposure_map = {
        exp.exposure_id: exp
        for exp in exposures
    }

    triggers = [
        exposure_map[exp_id]
        for exp_id in match.trigger_ids
        if exp_id in exposure_map
    ]

    supports = [
        exposure_map[exp_id]
        for exp_id in match.supporting_ids
        if exp_id in exposure_map
    ]

    # R01: Explicit advisor relationship.
    if match.rule_id == "R01":
        has_advisor = any(
            exp.type == ExposureType.RELATIONSHIP
            and (exp.relation or "").strip().casefold() == "advisor"
            for exp in triggers
        )

        has_support = any(
            exp.type in {
                ExposureType.AFFILIATION,
                ExposureType.CONTACT,
            }
            for exp in supports
        )

        if has_advisor and has_support:
            return RiskPathStatus.SUPPORTED

    # R02-R05: Exposure type combinations can identify
    # attack scenarios, but do not independently establish
    # semantic relationships between exposures.
    return RiskPathStatus.CANDIDATE

