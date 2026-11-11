
import pytest

from dfsa.contracts.common import ExposureType
from dfsa.contracts.profiling import Exposure, ExposureSource
from dfsa.modules.risk.graph import build_exposure_graph
from dfsa.modules.risk.rules import match_rules
from dfsa.modules.risk.features import extract_features


def make_exposure(exp_id, exp_type, source_id):
    return Exposure(
        exposure_id=exp_id,
        type=exp_type,
        value="test",
        sources=[
            ExposureSource(
                source_id=source_id,
                evidence="test evidence",
            )
        ],
    )


def test_full_support_coverage():
    exposures = [
        make_exposure("exp_001", ExposureType.RELATIONSHIP, "src_001"),
        make_exposure("exp_002", ExposureType.AFFILIATION, "src_001"),
        make_exposure("exp_003", ExposureType.CONTACT, "src_002"),
    ]

    match = match_rules(exposures)[0]
    graph = build_exposure_graph(exposures)

    features = extract_features(match, exposures, graph)

    assert features.trigger_coverage == 1.0
    assert features.support_coverage == 1.0
    assert features.source_count == 2
    assert features.verified_edge_count == 0
    assert features.connected_support_count == 0


def test_partial_support_coverage():
    exposures = [
        make_exposure("exp_001", ExposureType.RELATIONSHIP, "src_001"),
        make_exposure("exp_002", ExposureType.CONTACT, "src_002"),
    ]

    match = match_rules(exposures)[0]
    graph = build_exposure_graph(exposures)

    features = extract_features(match, exposures, graph)

    assert features.trigger_coverage == 1.0
    assert features.support_coverage == 0.5


def test_no_support():
    exposures = [
        make_exposure("exp_001", ExposureType.RELATIONSHIP, "src_001"),
    ]

    match = match_rules(exposures)[0]
    graph = build_exposure_graph(exposures)

    features = extract_features(match, exposures, graph)

    assert features.support_coverage == 0.0
    assert features.source_count == 1


def test_unknown_rule():
    from dataclasses import replace

    exposures = [
        make_exposure("exp_001", ExposureType.RELATIONSHIP, "src_001"),
    ]

    match = replace(match_rules(exposures)[0], rule_id="R99")

    with pytest.raises(ValueError):
        extract_features(
            match,
            exposures,
            build_exposure_graph(exposures),
        )

