
import pytest

from dfsa.contracts.common import RiskCategory
from dfsa.modules.risk.templates import generate_explanation


@pytest.mark.parametrize(
    "rule_id, category",
    [
        ("R01", RiskCategory.AUTHORITY_IMPERSONATION),
        ("R02", RiskCategory.ACADEMIC_IMPERSONATION),
        ("R03", RiskCategory.RECRUITMENT_IMPERSONATION),
        ("R04", RiskCategory.EVENT_IMPERSONATION),
        ("R05", RiskCategory.ACCOUNT_IMPERSONATION),
    ],
)
def test_generate_explanation(rule_id, category):
    reason, recommendations = generate_explanation(rule_id, category)

    assert isinstance(reason, str)
    assert len(reason) > 0

    assert isinstance(recommendations, list)
    assert len(recommendations) >= 1

    assert all(
        isinstance(item, str) and item.strip()
        for item in recommendations
    )


def test_invalid_rule_id():
    with pytest.raises(ValueError):
        generate_explanation(
            "R99",
            RiskCategory.AUTHORITY_IMPERSONATION,
        )


def test_category_mismatch():
    with pytest.raises(ValueError):
        generate_explanation(
            "R01",
            RiskCategory.ACCOUNT_IMPERSONATION,
        )

