
import pytest

from dfsa.contracts.common import ExposureType
from dfsa.contracts.profiling import Exposure, ExposureSource
from dfsa.modules.risk.rules import match_rules


def make_exposure(exposure_id, exposure_type):
    return Exposure(
        exposure_id=exposure_id,
        type=exposure_type,
        value="test value",
        sources=[
            ExposureSource(
                source_id="src_001",
                evidence="test evidence",
            )
        ],
    )


@pytest.mark.parametrize(
    "types, expected_rules",
    [
        ([ExposureType.RELATIONSHIP], ["R01"]),
        ([ExposureType.AFFILIATION, ExposureType.INTEREST], ["R02"]),
        ([ExposureType.ACTIVITY, ExposureType.INTEREST], ["R03"]),
        ([ExposureType.TEMPORAL], ["R04"]),
        ([ExposureType.ACCOUNT], ["R05"]),
        ([ExposureType.CONTACT], []),
        ([], []),
    ],
)
def test_rule_matching(types, expected_rules):
    exposures = [
        make_exposure(f"exp_{i:03d}", exposure_type)
        for i, exposure_type in enumerate(types, start=1)
    ]

    matches = match_rules(exposures)

    assert [match.rule_id for match in matches] == expected_rules

def test_r01_supporting_evidence():
    exposures = [
        make_exposure("exp_001", ExposureType.RELATIONSHIP),
        make_exposure("exp_002", ExposureType.AFFILIATION),
        make_exposure("exp_003", ExposureType.CONTACT),
    ]

    matches = match_rules(exposures)

    assert len(matches) == 1

    match = matches[0]

    assert match.rule_id == "R01"
    assert match.trigger_ids == ("exp_001",)
    assert match.supporting_ids == (
        "exp_002",
        "exp_003",
    )
    assert match.exposure_ids == (
        "exp_001",
        "exp_002",
        "exp_003",
    )


def test_supporting_only_does_not_trigger():
    exposures = [
        make_exposure("exp_001", ExposureType.AFFILIATION),
        make_exposure("exp_002", ExposureType.CONTACT),
    ]

    assert match_rules(exposures) == []

