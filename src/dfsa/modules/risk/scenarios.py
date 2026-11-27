
"""Generate defensive educational scenarios for v0.2."""

from dfsa.contracts.analysis import PhishingRiskScenario
from dfsa.contracts.profiling import Exposure


SCENARIO_TEMPLATES = {
    "identity": {
        "title": "Identity impersonation risk",
        "explanation": (
            "Public identity information may increase "
            "the risk of impersonation."
        ),
        "educational_example": (
            "A fictional security lesson demonstrates "
            "why a familiar name does not establish identity."
        ),
        "safety_checks": [
            "Verify the person's identity independently.",
            "Do not trust a request based only on a name.",
        ],
    },
    "contact": {
        "title": "Public contact information risk",
        "explanation": (
            "Public contact information may increase "
            "exposure to unwanted or fraudulent communication."
        ),
        "educational_example": (
            "A fictional training participant learns "
            "to recognize unsolicited communication."
        ),
        "safety_checks": [
            "Review publicly available contact information.",
            "Report suspicious communication.",
        ],
    },
    "affiliation": {
        "title": "Organization impersonation risk",
        "explanation": (
            "Public affiliation information may increase "
            "exposure to institutional impersonation."
        ),
        "educational_example": (
            "A fictional university security exercise "
            "teaches participants to verify institutional claims."
        ),
        "safety_checks": [
            "Verify requests through official channels.",
            "Check the organization's official directory.",
        ],
    },
    "relationship": {
        "title": "Trust relationship risk",
        "explanation": (
            "Public relationship information may increase "
            "exposure to trust-based social engineering."
        ),
        "educational_example": (
            "A fictional awareness exercise demonstrates "
            "that claimed relationships require verification."
        ),
        "safety_checks": [
            "Independently confirm unexpected requests.",
            "Do not rely solely on claimed relationships.",
        ],
    },
    "activity": {
        "title": "Public activity information risk",
        "explanation": (
            "Public activity information may reveal "
            "more personal context than intended."
        ),
        "educational_example": (
            "A fictional participant reviews the privacy "
            "implications of publishing activity information."
        ),
        "safety_checks": [
            "Review publicly shared activity details.",
            "Verify unfamiliar communications.",
        ],
    },
    "interest": {
        "title": "Public interest information risk",
        "explanation": (
            "Public interests may increase exposure "
            "to personalized social engineering."
        ),
        "educational_example": (
            "A fictional training lesson explains why "
            "relevant-looking content is not necessarily safe."
        ),
        "safety_checks": [
            "Check the legitimacy of unfamiliar content.",
            "Avoid opening unverified links.",
        ],
    },
    "account": {
        "title": "Online account exposure risk",
        "explanation": (
            "Public account information may increase "
            "exposure to account-related security threats."
        ),
        "educational_example": (
            "A fictional security exercise teaches "
            "safe handling of account notifications."
        ),
        "safety_checks": [
            "Enable multi-factor authentication.",
            "Access accounts through official websites.",
        ],
    },
    "temporal": {
        "title": "Public schedule information risk",
        "explanation": (
            "Public schedule information may reveal "
            "personal routines or availability."
        ),
        "educational_example": (
            "A fictional privacy lesson demonstrates "
            "the importance of limiting schedule visibility."
        ),
        "safety_checks": [
            "Review publicly accessible schedule information.",
            "Avoid sharing unnecessary real-time details.",
        ],
    },
}


def build_phishing_risk_scenarios(
    exposures: list[Exposure],
) -> list[PhishingRiskScenario]:

    discovered_types = {
        exposure.type.value
        for exposure in exposures
    }

    scenarios = []

    for exposure_type, template in SCENARIO_TEMPLATES.items():
        if exposure_type not in discovered_types:
            continue

        scenarios.append(
            PhishingRiskScenario(
                scenario_id=f"scenario_{exposure_type}",
                title=template["title"],
                explanation=template["explanation"],
                educational_example=template[
                    "educational_example"
                ],
                exposure_types=[exposure_type],
                safety_checks=template["safety_checks"].copy(),
            )
        )

    return scenarios
