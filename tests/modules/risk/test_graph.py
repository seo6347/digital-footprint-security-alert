
import pytest

from dfsa.contracts.common import ExposureType
from dfsa.contracts.profiling import Exposure, ExposureSource
from dfsa.modules.risk.graph import (
    GraphEdge,
    GraphNode,
    ExposureGraph,
    build_exposure_graph,
)


def make_exposure(exposure_id, exposure_type, source_id):
    return Exposure(
        exposure_id=exposure_id,
        type=exposure_type,
        value="test value",
        sources=[
            ExposureSource(
                source_id=source_id,
                evidence="test evidence",
            )
        ],
    )


def test_graph_construction():
    exposures = [
        make_exposure("exp_001", ExposureType.RELATIONSHIP, "src_001"),
        make_exposure("exp_002", ExposureType.AFFILIATION, "src_001"),
        make_exposure("exp_003", ExposureType.CONTACT, "src_002"),
    ]

    graph = build_exposure_graph(exposures)

    assert len(graph.nodes) == 6
    assert len(graph.edges) == 6

    assert "subject" in graph.nodes
    assert "exposure:exp_001" in graph.nodes
    assert "source:src_001" in graph.nodes
    assert "source:src_002" in graph.nodes


def test_source_evidence_tracking():
    exposure = make_exposure(
        "exp_001",
        ExposureType.RELATIONSHIP,
        "src_001",
    )

    graph = build_exposure_graph([exposure])

    assert GraphEdge(
        source="exposure:exp_001",
        target="source:src_001",
        relation="found_in",
        evidence="test evidence",
    ) in graph.edges


def test_no_unverified_exposure_relationship():
    exposures = [
        make_exposure("exp_001", ExposureType.RELATIONSHIP, "src_001"),
        make_exposure("exp_002", ExposureType.AFFILIATION, "src_001"),
    ]

    graph = build_exposure_graph(exposures)

    assert not any(
        edge.source.startswith("exposure:")
        and edge.target.startswith("exposure:")
        for edge in graph.edges
    )


def test_empty_graph():
    graph = build_exposure_graph([])

    assert len(graph.nodes) == 1
    assert graph.edges == []


def test_duplicate_source_node():
    exposures = [
        make_exposure("exp_001", ExposureType.CONTACT, "src_001"),
        make_exposure("exp_002", ExposureType.ACCOUNT, "src_001"),
    ]

    graph = build_exposure_graph(exposures)

    source_nodes = [
        node for node in graph.nodes.values()
        if node.node_type == "source"
    ]

    assert len(source_nodes) == 1


def test_invalid_edge():
    graph = ExposureGraph()
    graph.add_node(GraphNode("subject", "subject", "test"))

    with pytest.raises(ValueError):
        graph.add_edge(
            GraphEdge("subject", "missing_node", "has_exposure")
        )

