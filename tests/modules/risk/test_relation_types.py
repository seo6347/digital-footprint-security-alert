
import pytest

from dfsa.contracts.common import ExposureType
from dfsa.modules.risk.relation_types import (
    RELATIONS,
    RelationType,
    get_relations_for_rule,
    is_valid_relation_pair,
)


@pytest.mark.parametrize(
    "rule_id, expected_count",
    [
        ("R01", 2),
        ("R02", 3),
        ("R03", 3),
        ("R04", 3),
        ("R05", 2),
    ],
)
def test_all_rules_have_relations(rule_id, expected_count):
    relations = get_relations_for_rule(rule_id)

    assert len(relations) == expected_count


def test_all_relation_types_defined():
    assert len(RELATIONS) == 13
    assert len({r.relation_type for r in RELATIONS}) == 13
    assert set(RelationType) == {r.relation_type for r in RELATIONS}


def test_valid_authority_affiliation():
    assert is_valid_relation_pair(
        RelationType.AUTHORITY_AFFILIATION,
        ExposureType.RELATIONSHIP,
        ExposureType.AFFILIATION,
    )


def test_reversed_pair_is_valid():
    assert is_valid_relation_pair(
        RelationType.ACCOUNT_CONTACT,
        ExposureType.CONTACT,
        ExposureType.ACCOUNT,
    )


def test_invalid_authority_pair():
    assert not is_valid_relation_pair(
        RelationType.AUTHORITY_AFFILIATION,
        ExposureType.ACCOUNT,
        ExposureType.TEMPORAL,
    )


def test_academic_activity_supports_two_pairs():
    for left in (
        ExposureType.INTEREST,
        ExposureType.AFFILIATION,
    ):
        assert is_valid_relation_pair(
            RelationType.ACADEMIC_ACTIVITY,
            left,
            ExposureType.ACTIVITY,
        )


def test_unknown_rule_has_no_relations():
    assert get_relations_for_rule("R99") == []

