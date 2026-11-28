
"""Build a subject-centered relationship graph for v0.2."""

from dfsa.contracts.analysis import (
    GraphNode,
    GraphEdge,
    RelationshipGraph,
    NodeKind,
    NodeOrigin,
    GraphRelation,
)
from dfsa.contracts.common import Subject
from dfsa.contracts.profiling import Exposure


GRAPH_RULES = {
    ("affiliation", "university"): (
        NodeKind.UNIVERSITY,
        GraphRelation.AFFILIATED_WITH,
    ),
    ("affiliation", "laboratory"): (
        NodeKind.LABORATORY,
        GraphRelation.MEMBER_OF,
    ),
    ("interest", None): (
        NodeKind.RESEARCH_TOPIC,
        GraphRelation.INTERESTED_IN,
    ),
    ("activity", None): (
        NodeKind.ACTIVITY,
        GraphRelation.PARTICIPATED_IN,
    ),
}


def get_graph_rule(exposure: Exposure):
    exposure_type = exposure.type.value

    if exposure_type == "relationship":
        if (
            exposure.subtype in (None, "advisor")
            and exposure.relation == "advisor"
        ):
            return (
                NodeKind.PERSON,
                GraphRelation.ADVISED_BY,
            )

        return None

    return GRAPH_RULES.get(
        (exposure_type, exposure.subtype)
    )


def build_relationship_graph(
    subject: Subject,
    exposures: list[Exposure],
) -> RelationshipGraph:

    if not exposures:
        return RelationshipGraph()

    nodes = [
        GraphNode(
            node_id="node_subject",
            label=subject.name,
            kind=NodeKind.PERSON,
            origin=NodeOrigin.INPUT,
            exposure_ids=[],
        )
    ]

    edges = []
    groups = {}

    for exposure in exposures:
        rule = get_graph_rule(exposure)

        if rule is None:
            continue

        kind, relation = rule

        key = (
            kind,
            relation,
            exposure.value,
        )

        if key not in groups:
            groups[key] = []

        if exposure.exposure_id not in groups[key]:
            groups[key].append(exposure.exposure_id)

    for index, (key, exposure_ids) in enumerate(
        groups.items(), start=1
    ):
        kind, relation, value = key

        node_id = f"node_{index}"
        edge_id = f"edge_{index}"

        nodes.append(
            GraphNode(
                node_id=node_id,
                label=value,
                kind=kind,
                origin=NodeOrigin.VERIFIED,
                exposure_ids=exposure_ids.copy(),
            )
        )

        edges.append(
            GraphEdge(
                edge_id=edge_id,
                source_node_id="node_subject",
                target_node_id=node_id,
                relation=relation,
                exposure_ids=exposure_ids.copy(),
            )
        )

    return RelationshipGraph(
        nodes=nodes,
        edges=edges,
    )
