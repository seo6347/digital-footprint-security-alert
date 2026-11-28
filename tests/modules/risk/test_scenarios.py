
import pytest

from dfsa.contracts.profiling import Exposure
from dfsa.modules.risk.scenarios import (
    build_phishing_risk_scenarios,
)


EXPOSURE_TYPES = [
    "identity",
    "contact",
    "affiliation",
    "relationship",
    "activity",
    "interest",
    "account",
    "temporal",
]


def make_exposure(
    exposure_id,
    exposure_type,
    value="Synthetic Value",
):
    return Exposure(
        exposure_id=exposure_id,
        type=exposure_type,
        value=value,
        sources=[
            {
                "source_id": "src_test",
                "evidence": f"Synthetic evidence: {value}",
            }
        ],
    )


@pytest.mark.parametrize(
    "exposure_type", EXPOSURE_TYPES
)
def test_scenario_type_mapping(exposure_type):
    exposure = make_exposure(
        "exp_test", exposure_type
    )

    scenarios = build_phishing_risk_scenarios(
        [exposure]
    )

    assert len(scenarios) == 1
    assert scenarios[0].exposure_types == [
        exposure_type
    ]
    assert scenarios[0].title
    assert scenarios[0].explanation
    assert scenarios[0].educational_example
    assert scenarios[0].safety_checks


def test_empty_exposures():
    scenarios = build_phishing_risk_scenarios([])

    assert scenarios == []


def test_duplicate_types():
    exposures = [
        make_exposure("exp_001", "contact"),
        make_exposure("exp_002", "contact"),
    ]

    scenarios = build_phishing_risk_scenarios(
        exposures
    )

    assert len(scenarios) == 1


def test_multiple_types():
    exposures = [
        make_exposure("exp_001", "identity"),
        make_exposure("exp_002", "affiliation"),
        make_exposure("exp_003", "contact"),
    ]

    scenarios = build_phishing_risk_scenarios(
        exposures
    )

    assert len(scenarios) == 3

    actual_types = {
        exposure_type
        for scenario in scenarios
        for exposure_type in scenario.exposure_types
    }

    assert actual_types == {
        "identity", "affiliation", "contact"
    }


def test_all_exposure_types():
    exposures = [
        make_exposure(
            f"exp_{index}", exposure_type
        )
        for index, exposure_type
        in enumerate(EXPOSURE_TYPES)
    ]

    scenarios = build_phishing_risk_scenarios(
        exposures
    )

    assert len(scenarios) == 8


def test_unique_scenario_ids():
    exposures = [
        make_exposure(
            f"exp_{index}", exposure_type
        )
        for index, exposure_type
        in enumerate(EXPOSURE_TYPES)
    ]

    scenarios = build_phishing_risk_scenarios(
        exposures
    )

    ids = [
        scenario.scenario_id
        for scenario in scenarios
    ]

    assert len(ids) == len(set(ids))
    assert all(
        scenario_id.startswith("scenario_")
        for scenario_id in ids
    )


def test_private_values_are_not_inserted():
    private_values = [
        "UniqueSyntheticPerson987",
        "private987@example.org",
        "UniqueSyntheticLab987",
    ]

    exposures = [
        make_exposure(
            "exp_001", "identity",
            private_values[0],
        ),
        make_exposure(
            "exp_002", "contact",
            private_values[1],
        ),
        make_exposure(
            "exp_003", "affiliation",
            private_values[2],
        ),
    ]

    scenarios = build_phishing_risk_scenarios(
        exposures
    )

    output = " ".join(
        scenario.model_dump_json()
        for scenario in scenarios
    )

    for value in private_values:
        assert value not in output


def test_deterministic_scenario_generation():
    exposures = [
        make_exposure("exp_001", "contact"),
        make_exposure("exp_002", "identity"),
    ]

    first = build_phishing_risk_scenarios(
        exposures
    )

    second = build_phishing_risk_scenarios(
        list(reversed(exposures))
    )

    assert first == second
