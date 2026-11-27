
import pytest

from dfsa.contracts.profiling import Exposure
from dfsa.modules.risk.recommendations import (
    build_security_recommendations,
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
def test_recommendation_type_mapping(exposure_type):
    exposure = make_exposure(
        "exp_test", exposure_type
    )

    recommendations = build_security_recommendations(
        [exposure]
    )

    assert len(recommendations) == 2

    specific = [
        item for item in recommendations
        if item.exposure_types
    ]

    assert len(specific) == 1
    assert specific[0].exposure_types == [
        exposure_type
    ]
    assert specific[0].title
    assert specific[0].description


def test_empty_exposures():
    recommendations = build_security_recommendations(
        []
    )

    assert len(recommendations) == 1
    assert recommendations[0].exposure_types == []
    assert recommendations[0].recommendation_id == (
        "rec_general"
    )


def test_duplicate_types():
    exposures = [
        make_exposure("exp_001", "contact"),
        make_exposure("exp_002", "contact"),
    ]

    recommendations = build_security_recommendations(
        exposures
    )

    assert len(recommendations) == 2


def test_multiple_types():
    exposures = [
        make_exposure("exp_001", "identity"),
        make_exposure("exp_002", "contact"),
        make_exposure("exp_003", "affiliation"),
    ]

    recommendations = build_security_recommendations(
        exposures
    )

    assert len(recommendations) == 4

    actual_types = {
        exposure_type
        for item in recommendations
        for exposure_type in item.exposure_types
    }

    assert actual_types == {
        "identity", "contact", "affiliation"
    }


def test_all_exposure_types():
    exposures = [
        make_exposure(
            f"exp_{index}", exposure_type
        )
        for index, exposure_type
        in enumerate(EXPOSURE_TYPES)
    ]

    recommendations = build_security_recommendations(
        exposures
    )

    assert len(recommendations) == 9


def test_unique_recommendation_ids():
    exposures = [
        make_exposure(
            f"exp_{index}", exposure_type
        )
        for index, exposure_type
        in enumerate(EXPOSURE_TYPES)
    ]

    recommendations = build_security_recommendations(
        exposures
    )

    ids = [
        item.recommendation_id
        for item in recommendations
    ]

    assert len(ids) == len(set(ids))
    assert all(
        item_id.startswith("rec_")
        for item_id in ids
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

    recommendations = build_security_recommendations(
        exposures
    )

    output = " ".join(
        item.model_dump_json()
        for item in recommendations
    )

    for value in private_values:
        assert value not in output


def test_deterministic_recommendations():
    exposures = [
        make_exposure("exp_001", "contact"),
        make_exposure("exp_002", "identity"),
    ]

    first = build_security_recommendations(
        exposures
    )

    second = build_security_recommendations(
        list(reversed(exposures))
    )

    assert first == second


def test_general_recommendation_is_not_duplicated():
    exposures = [
        make_exposure(
            f"exp_{index}", exposure_type
        )
        for index, exposure_type
        in enumerate(EXPOSURE_TYPES)
    ]

    recommendations = build_security_recommendations(
        exposures
    )

    general = [
        item for item in recommendations
        if not item.exposure_types
    ]

    assert len(general) == 1
