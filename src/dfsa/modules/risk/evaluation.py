
"""Rule-based risk evaluation for DFSA v0.1."""

from dfsa.contracts.common import EvaluationValue, ExposureType
from dfsa.contracts.profiling import Exposure
from dfsa.contracts.risk import RiskEvaluation

from .rules import RuleMatch


def evaluate_risk(
    match: RuleMatch,
    exposures: list[Exposure],
) -> RiskEvaluation:
    """Evaluate a risk path using Module B's confirmed exposures."""

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

    used_exposures = triggers + supports

    # 1. Source presence, not independently verified searchability.
    searchability = (
        EvaluationValue.YES
        if any(exp.sources for exp in used_exposures)
        else EvaluationValue.UNKNOWN
    )

    # 2. Cross-source semantic links are not represented
    # explicitly in the v0.1 contract.
    cross_source_linkability = EvaluationValue.UNKNOWN

    # 3. Information combination available for the rule.
    attack_utility = (
        EvaluationValue.YES
        if triggers and supports
        else EvaluationValue.UNKNOWN
    )

    # 4. Contact exposure as a limited privacy relevance signal.
    sensitivity = (
        EvaluationValue.YES
        if any(
            exp.type == ExposureType.CONTACT
            for exp in used_exposures
        )
        else EvaluationValue.UNKNOWN
    )

    # 5. Explicit advisor relation plus supporting information.
    # This indicates scenario support, not independent truth checking.
    explicit_advisor = (
        match.rule_id == "R01"
        and bool(supports)
        and any(
            exp.type == ExposureType.RELATIONSHIP
            and (exp.relation or "").strip().casefold() == "advisor"
            for exp in triggers
        )
    )

    evidence_confidence = (
        EvaluationValue.YES
        if explicit_advisor
        and all(exp.sources for exp in used_exposures)
        else EvaluationValue.UNKNOWN
    )

    return RiskEvaluation(
        searchability=searchability,
        cross_source_linkability=cross_source_linkability,
        attack_utility=attack_utility,
        sensitivity=sensitivity,
        evidence_confidence=evidence_confidence,
    )

