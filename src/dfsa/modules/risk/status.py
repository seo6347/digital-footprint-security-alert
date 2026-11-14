
"""Rule-based risk path status for DFSA v0.1."""

from dfsa.contracts.common import ExposureType, RiskPathStatus
from dfsa.contracts.profiling import Exposure

from .rules import RuleMatch


def determine_path_status(
    match: RuleMatch,
    exposures: list[Exposure],
) -> RiskPathStatus:
    """Classify the evidentiary support for a risk scenario."""

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

    trigger_types = {exp.type for exp in triggers}
    support_types = {exp.type for exp in supports}

    if match.rule_id == "R01":
        advisor = any(
            exp.type == ExposureType.RELATIONSHIP
            and (exp.relation or "").strip().casefold() == "advisor"
            for exp in triggers
        )
        if advisor and support_types & {
            ExposureType.AFFILIATION,
            ExposureType.CONTACT,
        }:
            return RiskPathStatus.SUPPORTED

    elif match.rule_id == "R02":
        if (
            {ExposureType.AFFILIATION, ExposureType.INTEREST}
            <= trigger_types
            and support_types & {
                ExposureType.ACTIVITY,
                ExposureType.CONTACT,
            }
        ):
            return RiskPathStatus.SUPPORTED

    elif match.rule_id == "R03":
        if (
            {ExposureType.ACTIVITY, ExposureType.INTEREST}
            <= trigger_types
            and support_types & {
                ExposureType.ACCOUNT,
                ExposureType.CONTACT,
            }
        ):
            return RiskPathStatus.SUPPORTED

    elif match.rule_id == "R04":
        if (
            ExposureType.TEMPORAL in trigger_types
            and ExposureType.ACTIVITY in support_types
        ):
            return RiskPathStatus.SUPPORTED

    elif match.rule_id == "R05":
        if (
            ExposureType.ACCOUNT in trigger_types
            and support_types & {
                ExposureType.CONTACT,
                ExposureType.IDENTITY,
            }
        ):
            return RiskPathStatus.SUPPORTED

    return RiskPathStatus.CANDIDATE

