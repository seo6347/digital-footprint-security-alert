
"""Graph construction for DFSA Module C."""

from dataclasses import dataclass, field

from dfsa.contracts.profiling import Exposure


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: str
    value: str


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    evidence: str | None = None


@dataclass
class ExposureGraph:
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)

    def add_node(self, node: GraphNode):
        self.nodes[node.node_id] = node

    def add_edge(self, edge: GraphEdge):
        if edge.source not in self.nodes:
            raise ValueError(f"Unknown source node: {edge.source}")

        if edge.target not in self.nodes:
            raise ValueError(f"Unknown target node: {edge.target}")

        if edge not in self.edges:
            self.edges.append(edge)


def build_exposure_graph(exposures: list[Exposure]) -> ExposureGraph:
    """Construct a graph using validated exposure-source relationships."""

    graph = ExposureGraph()

    subject_id = "subject"

    graph.add_node(
        GraphNode(
            node_id=subject_id,
            node_type="subject",
            value="analysis_subject",
        )
    )

    for exposure in exposures:
        exposure_node_id = f"exposure:{exposure.exposure_id}"

        graph.add_node(
            GraphNode(
                node_id=exposure_node_id,
                node_type=exposure.type.value,
                value=exposure.value,
            )
        )

        # Module B confirmed that this exposure belongs to the subject.
        graph.add_edge(
            GraphEdge(
                source=subject_id,
                target=exposure_node_id,
                relation="has_exposure",
            )
        )

        for source_info in exposure.sources:
            source_node_id = f"source:{source_info.source_id}"

            graph.add_node(
                GraphNode(
                    node_id=source_node_id,
                    node_type="source",
                    value=source_info.source_id,
                )
            )

            graph.add_edge(
                GraphEdge(
                    source=exposure_node_id,
                    target=source_node_id,
                    relation="found_in",
                    evidence=source_info.evidence,
                )
            )

    return graph

