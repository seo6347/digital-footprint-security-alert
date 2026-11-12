
from dataclasses import replace

from dfsa.modules.risk.evaluation import (
    EvaluationValue,
    evaluate_risk,
)
from dfsa.modules.risk.features import RiskFeatures


def make_features():
    return RiskFeatures(
        trigger_coverage=1.0,
        support_coverage=0.5,
        source_count=2,
        verified_edge_count=0,
        cross_source_link_count=0,
        connected_support_count=0,
    )


def test_public_source_is_searchable():
    result = evaluate_risk(make_features())

    assert result.searchability == EvaluationValue.YES
    assert result.path_status == "candidate"


def test_no_source_is_unknown():
    features = replace(make_features(), source_count=0)

    result = evaluate_risk(features)

    assert result.searchability == EvaluationValue.UNKNOWN


def test_cross_source_link():
    features = replace(
        make_features(),
        verified_edge_count=1,
        cross_source_link_count=1,
        connected_support_count=1,
    )

    result = evaluate_risk(features)

    assert result.cross_source_linkability == EvaluationValue.YES

    # 검증된 간선이 있어도 현재는 supported로 자동 승격하지 않음
    assert result.path_status == "candidate"
    assert result.evidence_confidence == EvaluationValue.UNKNOWN


def test_full_coverage_does_not_imply_supported():
    features = replace(
        make_features(),
        support_coverage=1.0,
    )

    result = evaluate_risk(features)

    assert result.path_status == "candidate"
    assert result.attack_utility == EvaluationValue.UNKNOWN
    assert result.sensitivity == EvaluationValue.UNKNOWN


from dfsa.modules.risk.evaluation import determine_path_status


def test_candidate_without_verified_evidence():
    features = replace(
        make_features(),
        support_coverage=1.0,
        connected_support_count=1,
    )

    assert determine_path_status(features) == "candidate"


def test_supported_with_verified_evidence():
    features = replace(
        make_features(),
        support_coverage=1.0,
        connected_support_count=1,
    )

    assert determine_path_status(
        features,
        evidence_verified=True,
    ) == "supported"


def test_candidate_without_connected_support():
    features = replace(
        make_features(),
        support_coverage=1.0,
        connected_support_count=0,
    )

    assert determine_path_status(
        features,
        evidence_verified=True,
    ) == "candidate"


def test_candidate_without_support():
    features = replace(
        make_features(),
        support_coverage=0.0,
        connected_support_count=0,
    )

    assert determine_path_status(
        features,
        evidence_verified=True,
    ) == "candidate"

