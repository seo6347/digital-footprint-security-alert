
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

