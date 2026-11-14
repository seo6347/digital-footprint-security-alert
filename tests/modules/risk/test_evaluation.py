
import pytest

from dfsa.contracts.common import ExposureType
from dfsa.contracts.profiling import Exposure, ExposureSource
from dfsa.modules.risk.rules import match_rules
from dfsa.modules.risk.evaluation import evaluate_risk


def make_exposure(index, exp_type, relation=None):
    return Exposure(
        exposure_id=f"exp_{index:03d}",
        type=exp_type,
        value=f"value_{index}",
        relation=relation,
        sources=[
            ExposureSource(
                source_id=f"src_{index:03d}",
                evidence=f"Evidence for value_{index}",
            )
        ],
    )


def evaluate_rule(rule_id, exposures):
    match = next(
        match
        for match in match_rules(exposures)
        if match.rule_id == rule_id
    )
    return evaluate_risk(match, exposures)


def test_r01_explicit_advisor_evidence():
    exposures = [
        make_exposure(
            1, ExposureType.RELATIONSHIP, "advisor"
        ),
        make_exposure(
            2, ExposureType.AFFILIATION
        ),
        make_exposure(
            3, ExposureType.CONTACT
        ),
    ]

    result = evaluate_rule("R01", exposures)

    assert result.searchability.value == "YES"
    assert result.attack_utility.value == "YES"
    assert result.sensitivity.value == "YES"
    assert result.evidence_confidence.value == "YES"
    assert result.cross_source_linkability.value == "UNKNOWN"


def test_r01_without_advisor_relation():
    exposures = [
        make_exposure(1, ExposureType.RELATIONSHIP),
        make_exposure(2, ExposureType.AFFILIATION),
    ]

    result = evaluate_rule("R01", exposures)

    assert result.attack_utility.value == "YES"
    assert result.evidence_confidence.value == "UNKNOWN"


@pytest.mark.parametrize(
    "rule_id, types",
    [
        (
            "R02",
            [
                ExposureType.AFFILIATION,
                ExposureType.INTEREST,
                ExposureType.ACTIVITY,
            ],
        ),
        (
            "R03",
            [
                ExposureType.ACTIVITY,
                ExposureType.INTEREST,
                ExposureType.ACCOUNT,
            ],
        ),
        (
            "R04",
            [
                ExposureType.TEMPORAL,
                ExposureType.ACTIVITY,
            ],
        ),
        (
            "R05",
            [
                ExposureType.ACCOUNT,
                ExposureType.CONTACT,
            ],
        ),
    ],
)
def test_other_rules_do_not_assume_verified_relations(
    rule_id, types
):
    exposures = [
        make_exposure(i, exp_type)
        for i, exp_type in enumerate(types, start=1)
    ]

    result = evaluate_rule(rule_id, exposures)

    assert result.searchability.value == "YES"
    assert result.attack_utility.value == "YES"
    assert result.evidence_confidence.value == "UNKNOWN"
    assert result.cross_source_linkability.value == "UNKNOWN"


def test_trigger_only_has_unknown_attack_utility():
    exposures = [
        make_exposure(1, ExposureType.ACCOUNT)
    ]

    result = evaluate_rule("R05", exposures)

    assert result.attack_utility.value == "UNKNOWN"
    assert result.evidence_confidence.value == "UNKNOWN"

