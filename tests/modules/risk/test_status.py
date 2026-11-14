
import pytest
from types import SimpleNamespace

from dfsa.contracts.common import ExposureType, RiskPathStatus
from dfsa.modules.risk.rules import match_rules
from dfsa.modules.risk.status import determine_path_status


def make_exposure(index, exp_type, relation=None):
    return SimpleNamespace(
        exposure_id=f"exp_{index:03d}",
        type=exp_type,
        relation=relation,
    )


@pytest.mark.parametrize(
    "types,relations,expected_rule",
    [
        (
            [ExposureType.RELATIONSHIP, ExposureType.AFFILIATION],
            ["advisor", None],
            "R01",
        ),
        (
            [
                ExposureType.AFFILIATION,
                ExposureType.INTEREST,
                ExposureType.ACTIVITY,
            ],
            [None, None, None],
            "R02",
        ),
        (
            [
                ExposureType.ACTIVITY,
                ExposureType.INTEREST,
                ExposureType.ACCOUNT,
            ],
            [None, None, None],
            "R03",
        ),
        (
            [ExposureType.TEMPORAL, ExposureType.ACTIVITY],
            [None, None],
            "R04",
        ),
        (
            [ExposureType.ACCOUNT, ExposureType.CONTACT],
            [None, None],
            "R05",
        ),
    ],
)
def test_supported_rules(types, relations, expected_rule):
    exposures = [
        make_exposure(i, exp_type, relation)
        for i, (exp_type, relation)
        in enumerate(zip(types, relations), start=1)
    ]

    matches = match_rules(exposures)
    match = next(
        m for m in matches if m.rule_id == expected_rule
    )

    assert determine_path_status(
        match, exposures
    ) == RiskPathStatus.SUPPORTED


@pytest.mark.parametrize(
    "types,expected_rule",
    [
        ([ExposureType.RELATIONSHIP], "R01"),
        ([ExposureType.AFFILIATION, ExposureType.INTEREST], "R02"),
        ([ExposureType.ACTIVITY, ExposureType.INTEREST], "R03"),
        ([ExposureType.TEMPORAL], "R04"),
        ([ExposureType.ACCOUNT], "R05"),
    ],
)
def test_candidate_rules(types, expected_rule):
    exposures = [
        make_exposure(i, exp_type)
        for i, exp_type in enumerate(types, start=1)
    ]

    matches = match_rules(exposures)
    match = next(
        m for m in matches if m.rule_id == expected_rule
    )

    assert determine_path_status(
        match, exposures
    ) == RiskPathStatus.CANDIDATE

