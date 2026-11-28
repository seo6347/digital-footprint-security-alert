
"""Build a personal profile from verified v0.2 exposures."""

from dfsa.contracts.analysis import PersonalProfile, ProfileItem
from dfsa.contracts.profiling import Exposure


# Classification by exposure type and subtype
PROFILE_FIELDS = {
    ("identity", "name"): "name",
    ("identity", "role"): "role",
    ("affiliation", "university"): "university",
    ("affiliation", "laboratory"): "laboratory",
}

# Classification by exposure type
TYPE_FIELDS = {
    "contact": "contact",
    "interest": "research_interests",
    "relationship": "academic_relationships",
    "activity": "activities",
}


def build_personal_profile(
    exposures: list[Exposure],
) -> PersonalProfile:

    grouped = {}

    for exposure in exposures:
        exposure_type = exposure.type.value

        field = PROFILE_FIELDS.get(
            (exposure_type, exposure.subtype),
            TYPE_FIELDS.get(exposure_type, "additional"),
        )

        label = (
            exposure.subtype or exposure_type
        ).replace("_", " ").title()

        key = (
            field,
            label,
            exposure.value,
            exposure.relation,
        )

        if key not in grouped:
            grouped[key] = []

        if exposure.exposure_id not in grouped[key]:
            grouped[key].append(exposure.exposure_id)

    profile_data = {
        field: []
        for field in PersonalProfile.model_fields
    }

    for key, exposure_ids in grouped.items():
        field, label, value, _ = key

        item = ProfileItem(
            label=label,
            value=value,
            exposure_ids=exposure_ids,
        )

        profile_data[field].append(item)

    return PersonalProfile(**profile_data)
