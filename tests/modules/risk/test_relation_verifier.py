
from dfsa.contracts.common import ExposureType
from dfsa.contracts.profiling import Exposure, ExposureSource

from dfsa.modules.risk.relation_verifier import (
    extract_relation_candidates,
)


def make_exposure(exp_id, exp_type, value, source_id, evidence):
    return Exposure(
        exposure_id=exp_id,
        type=exp_type,
        value=value,
        sources=[
            ExposureSource(
                source_id=source_id,
                evidence=evidence,
            )
        ],
    )


def test_explicit_relation_candidate():
    evidence = "홍길동은 AI 연구실에 소속되어 있다."

    exposures = [
        make_exposure(
            "exp_001",
            ExposureType.IDENTITY,
            "홍길동",
            "src_001",
            evidence,
        ),
        make_exposure(
            "exp_002",
            ExposureType.AFFILIATION,
            "AI 연구실",
            "src_001",
            evidence,
        ),
    ]

    candidates = extract_relation_candidates(exposures)

    assert len(candidates) == 1
    assert candidates[0].has_relation_cue is True
    assert candidates[0].has_negation_cue is False


def test_different_sources_are_not_linked():
    evidence = "홍길동은 AI 연구실에 소속되어 있다."

    exposures = [
        make_exposure(
            "exp_001",
            ExposureType.IDENTITY,
            "홍길동",
            "src_001",
            evidence,
        ),
        make_exposure(
            "exp_002",
            ExposureType.AFFILIATION,
            "AI 연구실",
            "src_002",
            evidence,
        ),
    ]

    assert extract_relation_candidates(exposures) == []


def test_missing_exposure_value():
    exposures = [
        make_exposure(
            "exp_001",
            ExposureType.IDENTITY,
            "홍길동",
            "src_001",
            "홍길동은 다른 연구실에 소속되어 있다.",
        ),
        make_exposure(
            "exp_002",
            ExposureType.AFFILIATION,
            "AI 연구실",
            "src_001",
            "AI 연구실 소속자가 있다.",
        ),
    ]

    assert extract_relation_candidates(exposures) == []


def test_negation_is_detected():
    evidence = "홍길동은 AI 연구실 소속이 아니다."

    exposures = [
        make_exposure(
            "exp_001",
            ExposureType.IDENTITY,
            "홍길동",
            "src_001",
            evidence,
        ),
        make_exposure(
            "exp_002",
            ExposureType.AFFILIATION,
            "AI 연구실",
            "src_001",
            evidence,
        ),
    ]

    candidates = extract_relation_candidates(exposures)

    assert len(candidates) == 1
    assert candidates[0].has_negation_cue is True


def test_no_automatic_verified_relation():
    evidence = "홍길동과 AI 연구실이 같은 행사에 참석했다."

    exposures = [
        make_exposure(
            "exp_001",
            ExposureType.IDENTITY,
            "홍길동",
            "src_001",
            evidence,
        ),
        make_exposure(
            "exp_002",
            ExposureType.AFFILIATION,
            "AI 연구실",
            "src_001",
            evidence,
        ),
    ]

    candidates = extract_relation_candidates(exposures)

    assert len(candidates) == 1
    assert candidates[0].has_relation_cue is False


import pytest

from dfsa.modules.risk.relation_types import RelationType


@pytest.mark.parametrize(
    "left_type,right_type,expected_relation",
    [
        (
            ExposureType.RELATIONSHIP,
            ExposureType.AFFILIATION,
            RelationType.AUTHORITY_AFFILIATION,
        ),
        (
            ExposureType.AFFILIATION,
            ExposureType.INTEREST,
            RelationType.ACADEMIC_AFFILIATION_INTEREST,
        ),
        (
            ExposureType.ACTIVITY,
            ExposureType.INTEREST,
            RelationType.CAREER_ACTIVITY_INTEREST,
        ),
        (
            ExposureType.TEMPORAL,
            ExposureType.ACTIVITY,
            RelationType.EVENT_ACTIVITY,
        ),
        (
            ExposureType.ACCOUNT,
            ExposureType.CONTACT,
            RelationType.ACCOUNT_CONTACT,
        ),
    ],
)
def test_relation_types_for_all_rules(
    left_type,
    right_type,
    expected_relation,
):
    evidence = "정보A와 정보B 사이의 관계를 확인하는 근거"

    exposures = [
        make_exposure(
            "exp_001",
            left_type,
            "정보A",
            "src_001",
            evidence,
        ),
        make_exposure(
            "exp_002",
            right_type,
            "정보B",
            "src_001",
            evidence,
        ),
    ]

    candidates = extract_relation_candidates(exposures)

    assert len(candidates) == 1
    assert expected_relation in candidates[0].relation_types

