
"""Feature extraction for DFSA Module C."""

from dataclasses import dataclass

from dfsa.contracts.profiling import Exposure

from .graph import ExposureGraph
from .rules import RULES, RuleMatch


@dataclass(frozen=True)
class RiskFeatures:
    trigger_coverage: float
    support_coverage: float
    source_count: int
    verified_edge_count: int
    cross_source_link_count: int
    connected_support_count: int


def extract_features(
    match: RuleMatch,
    exposures: list[Exposure],
    graph: ExposureGraph,
) -> RiskFeatures:
    """Extract evidence features for one risk path candidate."""

    rule = next(
        (rule for rule in RULES if rule.rule_id == match.rule_id),
        None,
    )

    if rule is None:
        raise ValueError(f"Unknown rule: {match.rule_id}")

    exposure_map = {
        exp.exposure_id: exp for exp in exposures
    }

    # Count only valid IDs from the current exposure collection.
    trigger_ids = set(match.trigger_ids) & set(exposure_map)
    supporting_ids = set(match.supporting_ids) & set(exposure_map)

    trigger_types = {
        exposure_map[exp_id].type
        for exp_id in trigger_ids
    }

    support_types = {
        exposure_map[exp_id].type
        for exp_id in supporting_ids
    }

    trigger_coverage = (
        len(trigger_types & rule.triggers) / len(rule.triggers)
    )

    support_coverage = (
        len(support_types & rule.supporting) / len(rule.supporting)
    )

    used_ids = trigger_ids | supporting_ids

    source_sets = {
        exp_id: {
            source.source_id
            for source in exposure_map[exp_id].sources
        }
        for exp_id in used_ids
    }

    all_sources = set().union(*source_sets.values()) if source_sets else set()

    # Only explicit, evidence-backed exposure relations count.
    verified_pairs = set()

    for edge in graph.edges:
        if edge.relation != "verified_relation" or not edge.evidence:
            continue

        if not (
            edge.source.startswith("exposure:")
            and edge.target.startswith("exposure:")
        ):
            continue

        left = edge.source.removeprefix("exposure:")
        right = edge.target.removeprefix("exposure:")

        if left == right or left not in used_ids or right not in used_ids:
            continue

        verified_pairs.add(frozenset((left, right)))

    cross_source_links = sum(
        1
        for pair in verified_pairs
        if len(pair) == 2
        and not set.intersection(
            *(source_sets[exp_id] for exp_id in pair)
        )
    )

    connected_support = {
        support_id
        for pair in verified_pairs
        for support_id in supporting_ids
        if support_id in pair
        and bool(pair & trigger_ids)
    }

    return RiskFeatures(
        trigger_coverage=trigger_coverage,
        support_coverage=support_coverage,
        source_count=len(all_sources),
        verified_edge_count=len(verified_pairs),
        cross_source_link_count=cross_source_links,
        connected_support_count=len(connected_support),
    )

