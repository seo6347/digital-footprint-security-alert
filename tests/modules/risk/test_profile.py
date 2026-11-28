
import pytest

from dfsa.contracts.profiling import Exposure
from dfsa.modules.risk.profile import build_personal_profile


def make_exposure(
    exposure_id,
    exposure_type,
    value,
    subtype=None,
):
    return Exposure(
        exposure_id=exposure_id,
        type=exposure_type,
        subtype=subtype,
        value=value,
        sources=[
            {
                "source_id": "src_test",
                "evidence": f"Synthetic evidence: {value}",
            }
        ],
    )


@pytest.mark.parametrize(
    "exposure_type,subtype,field",
    [
        ("identity", "name", "name"),
        ("identity", "role", "role"),
        ("affiliation", "university", "university"),
        ("affiliation", "laboratory", "laboratory"),
        ("contact", "email", "contact"),
        ("interest", None, "research_interests"),
        ("relationship", "advisor", "academic_relationships"),
        ("activity", None, "activities"),
        ("account", None, "additional"),
        ("temporal", None, "additional"),
        ("identity", None, "additional"),
        ("affiliation", None, "additional"),
    ],
)
def test_profile_classification(
    exposure_type, subtype, field
):
    exposure = make_exposure(
        "exp_test",
        exposure_type,
        "Synthetic Value",
        subtype,
    )

    profile = build_personal_profile([exposure])
    items = getattr(profile, field)

    assert len(items) == 1
    assert items[0].value == "Synthetic Value"
    assert items[0].exposure_ids == ["exp_test"]


def test_empty_profile():
    profile = build_personal_profile([])

    assert all(
        not items
        for items in profile.model_dump().values()
    )


def test_duplicate_values_merge_exposure_ids():
    exposures = [
        make_exposure(
            "exp_001",
            "affiliation",
            "Example University",
            "university",
        ),
        make_exposure(
            "exp_002",
            "affiliation",
            "Example University",
            "university",
        ),
    ]

    profile = build_personal_profile(exposures)

    assert len(profile.university) == 1
    assert profile.university[0].exposure_ids == [
        "exp_001",
        "exp_002",
    ]


def test_different_values_are_preserved():
    exposures = [
        make_exposure(
            "exp_001", "interest", "Security"
        ),
        make_exposure(
            "exp_002", "interest", "Compilers"
        ),
    ]

    profile = build_personal_profile(exposures)

    assert len(profile.research_interests) == 2

    assert {
        item.value
        for item in profile.research_interests
    } == {"Security", "Compilers"}


def test_unverified_fields_remain_empty():
    exposure = make_exposure(
        "exp_001",
        "affiliation",
        "Example University",
        "university",
    )

    profile = build_personal_profile([exposure])

    assert profile.name == []
    assert profile.contact == []
    assert profile.laboratory == []
    assert profile.academic_relationships == []
