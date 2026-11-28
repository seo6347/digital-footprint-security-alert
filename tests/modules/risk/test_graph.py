
import pytest

from dfsa.contracts.common import Subject
from dfsa.contracts.profiling import Exposure
from dfsa.modules.risk.graph import build_relationship_graph


SUBJECT = Subject(
    name="Sample Researcher",
    organization="Example University",
)


def make_exposure(
    exposure_id,
    exposure_type,
    value,
    subtype=None,
    relation=None,
):
    return Exposure(
        exposure_id=exposure_id,
        type=exposure_type,
        subtype=subtype,
        relation=relation,
        value=value,
        sources=[
            {
                "source_id": "src_test",
                "evidence": f"Synthetic evidence: {value}",
            }
        ],
    )


@pytest.mark.parametrize(
    "exposure_type,subtype,relation,kind,edge_relation",
    [
        (
            "affiliation", "university", None,
            "university", "AFFILIATED_WITH",
        ),
        (
            "affiliation", "laboratory", None,
            "laboratory", "MEMBER_OF",
        ),
        (
            "relationship", "advisor", "advisor",
            "person", "ADVISED_BY",
        ),
        (
            "interest", None, None,
            "research_topic", "INTERESTED_IN",
        ),
        (
            "activity", None, None,
            "activity", "PARTICIPATED_IN",
        ),
    ],
)
def test_graph_rule_mapping(
    exposure_type,
    subtype,
    relation,
    kind,
    edge_relation,
):
    exposure = make_exposure(
        "exp_test",
        exposure_type,
        "Synthetic Value",
        subtype,
        relation,
    )

    graph = build_relationship_graph(
        SUBJECT, [exposure]
    )

    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1

    assert graph.nodes[0].origin == "input"
    assert graph.nodes[1].origin == "verified"
    assert graph.nodes[1].kind == kind
    assert graph.nodes[1].exposure_ids == ["exp_test"]

    assert graph.edges[0].relation == edge_relation
    assert graph.edges[0].exposure_ids == ["exp_test"]


def test_empty_graph():
    graph = build_relationship_graph(SUBJECT, [])

    assert graph.nodes == []
    assert graph.edges == []


def test_no_inferred_advisor():
    exposure = make_exposure(
        "exp_001",
        "affiliation",
        "Example Lab",
        "laboratory",
    )

    graph = build_relationship_graph(
        SUBJECT, [exposure]
    )

    assert len(graph.edges) == 1
    assert all(
        edge.relation != "ADVISED_BY"
        for edge in graph.edges
    )


def test_advisor_without_explicit_relation():
    exposure = make_exposure(
        "exp_001",
        "relationship",
        "Sample Professor",
        "advisor",
    )

    graph = build_relationship_graph(
        SUBJECT, [exposure]
    )

    assert len(graph.nodes) == 1
    assert graph.edges == []


def test_duplicate_nodes_merge_exposure_ids():
    exposures = [
        make_exposure(
            "exp_001", "affiliation",
            "Example Lab", "laboratory",
        ),
        make_exposure(
            "exp_002", "affiliation",
            "Example Lab", "laboratory",
        ),
    ]

    graph = build_relationship_graph(
        SUBJECT, exposures
    )

    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1

    assert graph.nodes[1].exposure_ids == [
        "exp_001", "exp_002"
    ]

    assert graph.edges[0].exposure_ids == [
        "exp_001", "exp_002"
    ]


def test_one_hop_structure():
    exposures = [
        make_exposure(
            "exp_001", "affiliation",
            "Example University", "university",
        ),
        make_exposure(
            "exp_002", "affiliation",
            "Example Lab", "laboratory",
        ),
        make_exposure(
            "exp_003", "interest", "Security",
        ),
    ]

    graph = build_relationship_graph(
        SUBJECT, exposures
    )

    assert len(graph.nodes) == 4
    assert len(graph.edges) == 3

    assert all(
        edge.source_node_id == "node_subject"
        for edge in graph.edges
    )


def test_contact_does_not_create_node():
    exposure = make_exposure(
        "exp_001",
        "contact",
        "sample@example.org",
        "email",
    )

    graph = build_relationship_graph(
        SUBJECT, [exposure]
    )

    assert len(graph.nodes) == 1
    assert graph.edges == []


def test_subject_information_is_not_verified():
    exposure = make_exposure(
        "exp_001",
        "interest",
        "Security",
    )

    graph = build_relationship_graph(
        SUBJECT, [exposure]
    )

    subject_node = graph.nodes[0]

    assert subject_node.label == SUBJECT.name
    assert subject_node.origin == "input"
    assert subject_node.exposure_ids == []

    assert all(
        node.kind != "university"
        for node in graph.nodes
    )
