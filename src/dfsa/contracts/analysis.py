"""Module C analysis and public profile, graph, and education contracts."""

from enum import Enum
from typing import Self

from pydantic import Field, model_validator

from .common import (
    ContractModel, EdgeID, ErrorDetail, ExposureID, ExposureType, ModuleStatus, NodeID,
    RecommendationID, RequestContract, ScenarioID, Subject, unique_ids,
)
from .profiling import Exposure


class ProfileItem(ContractModel):
    label: str
    value: str
    exposure_ids: list[ExposureID] = Field(min_length=1)


class PersonalProfile(ContractModel):
    name: list[ProfileItem] = Field(default_factory=list)
    university: list[ProfileItem] = Field(default_factory=list)
    laboratory: list[ProfileItem] = Field(default_factory=list)
    role: list[ProfileItem] = Field(default_factory=list)
    contact: list[ProfileItem] = Field(default_factory=list)
    research_interests: list[ProfileItem] = Field(default_factory=list)
    academic_relationships: list[ProfileItem] = Field(default_factory=list)
    activities: list[ProfileItem] = Field(default_factory=list)
    additional: list[ProfileItem] = Field(default_factory=list)


class NodeKind(str, Enum):
    PERSON = "person"
    UNIVERSITY = "university"
    LABORATORY = "laboratory"
    RESEARCH_TOPIC = "research_topic"
    ACTIVITY = "activity"


class NodeOrigin(str, Enum):
    INPUT = "input"
    VERIFIED = "verified"


class GraphRelation(str, Enum):
    AFFILIATED_WITH = "AFFILIATED_WITH"
    MEMBER_OF = "MEMBER_OF"
    ADVISED_BY = "ADVISED_BY"
    INTERESTED_IN = "INTERESTED_IN"
    PARTICIPATED_IN = "PARTICIPATED_IN"


class GraphNode(ContractModel):
    node_id: NodeID
    label: str
    kind: NodeKind
    origin: NodeOrigin
    exposure_ids: list[ExposureID]

    @model_validator(mode="after")
    def validate_origin(self) -> Self:
        if self.origin == NodeOrigin.INPUT and self.kind != NodeKind.PERSON:
            raise ValueError("Input graph node must represent the subject")
        if self.origin == NodeOrigin.VERIFIED and not self.exposure_ids:
            raise ValueError("Verified graph node must reference exposures")
        return self


class GraphEdge(ContractModel):
    edge_id: EdgeID
    source_node_id: NodeID
    target_node_id: NodeID
    relation: GraphRelation
    exposure_ids: list[ExposureID] = Field(min_length=1)


class RelationshipGraph(ContractModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        node_ids = unique_ids(self.nodes, "node_id")
        unique_ids(self.edges, "edge_id")
        inputs = [node.node_id for node in self.nodes if node.origin == NodeOrigin.INPUT]
        if self.nodes and len(inputs) != 1:
            raise ValueError("Nonempty graph must contain exactly one input node")
        for edge in self.edges:
            endpoints = {edge.source_node_id, edge.target_node_id}
            if not endpoints <= node_ids:
                raise ValueError("Graph edge must reference existing nodes")
            if inputs[0] not in endpoints or len(endpoints) != 2:
                raise ValueError("Graph edges must connect the input node to another node")
        return self


class PhishingRiskScenario(ContractModel):
    scenario_id: ScenarioID
    title: str
    explanation: str
    educational_example: str
    exposure_types: list[ExposureType] = Field(min_length=1)
    safety_checks: list[str] = Field(min_length=1)


class SecurityRecommendation(ContractModel):
    recommendation_id: RecommendationID
    title: str
    description: str
    exposure_types: list[ExposureType] = Field(default_factory=list)


def validate_analysis_references(
    profile: PersonalProfile | None,
    graph: RelationshipGraph,
    exposures: list[Exposure],
    *,
    scenarios: list[PhishingRiskScenario],
    recommendations: list[SecurityRecommendation],
) -> None:
    known_ids = {exposure.exposure_id for exposure in exposures}
    if profile is not None:
        for field in PersonalProfile.model_fields:
            for item in getattr(profile, field):
                if not set(item.exposure_ids) <= known_ids:
                    raise ValueError("Profile item references an unknown exposure")
    for item in (*graph.nodes, *graph.edges):
        if not set(item.exposure_ids) <= known_ids:
            raise ValueError("Graph references an unknown exposure")
    known_types = {exposure.type for exposure in exposures}
    for scenario in scenarios:
        if not set(scenario.exposure_types) <= known_types:
            raise ValueError("Phishing scenario references an undiscovered exposure type")
    for recommendation in recommendations:
        if not set(recommendation.exposure_types) <= known_types:
            raise ValueError("Security recommendation references an undiscovered exposure type")


class AnalysisRequest(RequestContract):
    subject: Subject
    exposures: list[Exposure] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_exposures(self) -> Self:
        unique_ids(self.exposures, "exposure_id")
        return self


class AnalysisResponse(RequestContract):
    status: ModuleStatus
    personal_profile: PersonalProfile | None = None
    relationship_graph: RelationshipGraph = Field(default_factory=RelationshipGraph)
    phishing_risk_scenarios: list[PhishingRiskScenario] = Field(default_factory=list)
    security_recommendations: list[SecurityRecommendation] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_response(self) -> Self:
        unique_ids(self.phishing_risk_scenarios, "scenario_id")
        unique_ids(self.security_recommendations, "recommendation_id")
        has_results = (
            self.personal_profile is not None or self.relationship_graph.nodes
            or self.phishing_risk_scenarios or self.security_recommendations
        )
        expected = ModuleStatus.SUCCESS
        if self.errors:
            expected = ModuleStatus.PARTIAL_SUCCESS if has_results else ModuleStatus.FAILED
        if self.status != expected:
            raise ValueError("Analysis status does not match its results and errors")
        return self
