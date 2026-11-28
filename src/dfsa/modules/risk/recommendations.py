
"""Generate defensive security recommendations for v0.2."""

from dfsa.contracts.analysis import SecurityRecommendation
from dfsa.contracts.profiling import Exposure


RECOMMENDATION_TEMPLATES = {
    "identity": {
        "title": "Verify personal identity",
        "description": (
            "Independently verify the identity of people "
            "making unexpected requests. Do not rely "
            "solely on familiar names or job titles."
        ),
    },
    "contact": {
        "title": "Minimize public contact information",
        "description": (
            "Review publicly accessible contact details "
            "and remove unnecessary personal information. "
            "Use institutional contact channels when appropriate."
        ),
    },
    "affiliation": {
        "title": "Verify institutional requests",
        "description": (
            "Confirm unexpected requests through official "
            "institutional websites or established "
            "communication channels."
        ),
    },
    "relationship": {
        "title": "Verify trust-based requests",
        "description": (
            "Independently confirm unusual requests "
            "involving colleagues or academic relationships "
            "before sharing information or taking action."
        ),
    },
    "activity": {
        "title": "Review public activity information",
        "description": (
            "Regularly review publicly shared activity "
            "details and limit unnecessary disclosure."
        ),
    },
    "interest": {
        "title": "Verify unfamiliar external content",
        "description": (
            "Check the legitimacy of unfamiliar links, "
            "attachments, and invitations even when "
            "they appear relevant to your interests."
        ),
    },
    "account": {
        "title": "Strengthen account security",
        "description": (
            "Enable multi-factor authentication, use "
            "unique passwords, and review account "
            "privacy and security settings."
        ),
    },
    "temporal": {
        "title": "Limit public schedule information",
        "description": (
            "Review the visibility of personal schedules "
            "and avoid publishing unnecessary real-time "
            "location or availability information."
        ),
    },
}


def build_security_recommendations(
    exposures: list[Exposure],
) -> list[SecurityRecommendation]:

    discovered_types = {
        exposure.type.value
        for exposure in exposures
    }

    recommendations = []

    for exposure_type, template in (
        RECOMMENDATION_TEMPLATES.items()
    ):
        if exposure_type not in discovered_types:
            continue

        recommendations.append(
            SecurityRecommendation(
                recommendation_id=f"rec_{exposure_type}",
                title=template["title"],
                description=template["description"],
                exposure_types=[exposure_type],
            )
        )

    recommendations.append(
        SecurityRecommendation(
            recommendation_id="rec_general",
            title="Maintain general security awareness",
            description=(
                "Keep software updated, review privacy "
                "settings regularly, and report suspicious "
                "communications through official channels."
            ),
            exposure_types=[],
        )
    )

    return recommendations
