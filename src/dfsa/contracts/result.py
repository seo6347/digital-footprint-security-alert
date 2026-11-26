"""Public v0.2 result consumed by the UI."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from .analysis import (
    PersonalProfile, PhishingRiskScenario, RelationshipGraph, SecurityRecommendation,
    validate_analysis_references,
)
from .common import (
    ContractModel, ErrorDetail, IdentityStatus, ModuleStatus, RequestContract, StageStatus,
    Subject, unique_ids,
)
from .exploration import (
    NavigationEntry, NavigationStatus, has_technical_navigation_failure, validate_navigation,
)
from .profiling import Exposure, Source, validate_exposure_references
from .search import QueryExecution, SearchResult, validate_search_references

Milliseconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]


class Stages(ContractModel):
    search: StageStatus
    exploration: StageStatus
    profiling: StageStatus
    analysis: StageStatus

    def overall_status(self) -> ModuleStatus:
        if StageStatus.FAILED in (self.search, self.exploration, self.profiling):
            return ModuleStatus.FAILED
        if self.analysis == StageStatus.FAILED or (
            StageStatus.PARTIAL_SUCCESS in (self.search, self.exploration, self.profiling, self.analysis)
        ):
            return ModuleStatus.PARTIAL_SUCCESS
        return ModuleStatus.SUCCESS


class ExecutionTime(ContractModel):
    total_ms: Milliseconds
    search_ms: Milliseconds | None
    exploration_ms: Milliseconds | None
    profiling_ms: Milliseconds | None
    analysis_ms: Milliseconds | None


class ResultSummary(ContractModel):
    search_result_count: Count
    visited_page_count: Count
    confirmed_source_count: Count
    total_exposures: Count
    total_graph_nodes: Count
    total_graph_edges: Count
    total_scenarios: Count
    total_recommendations: Count


class DFSAResult(RequestContract):
    status: ModuleStatus
    subject: Subject
    stages: Stages
    search_history: list[QueryExecution] = Field(default_factory=list)
    discovered_sources: list[SearchResult] = Field(default_factory=list)
    navigation_history: list[NavigationEntry] = Field(default_factory=list)
    exploration_limit_reached: bool = False
    sources: list[Source] = Field(default_factory=list)
    exposures: list[Exposure] = Field(default_factory=list)
    personal_profile: PersonalProfile | None = None
    relationship_graph: RelationshipGraph = Field(default_factory=RelationshipGraph)
    phishing_risk_scenarios: list[PhishingRiskScenario] = Field(default_factory=list)
    security_recommendations: list[SecurityRecommendation] = Field(default_factory=list)
    execution_time: ExecutionTime
    summary: ResultSummary
    errors: list[ErrorDetail] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        validate_search_references(self.search_history, self.discovered_sources)
        validate_navigation(self.navigation_history, self.discovered_sources)
        validate_exposure_references(self.sources, self.exposures)
        validate_analysis_references(self.personal_profile, self.relationship_graph, self.exposures)
        unique_ids(self.phishing_risk_scenarios, "scenario_id")
        unique_ids(self.security_recommendations, "recommendation_id")
        successful_sources = {
            (entry.source_id, entry.final_url) for entry in self.navigation_history
            if entry.status == NavigationStatus.SUCCESS
        }
        for source in self.sources:
            if (source.source_id, source.url) not in successful_sources and (
                source.source_id, None
            ) not in successful_sources:
                raise ValueError("Source must match successful navigation")
        if self.status != self.stages.overall_status():
            raise ValueError("Overall status does not match stage statuses")
        stages = self.stages
        if stages.search == StageStatus.NOT_STARTED:
            raise ValueError("A pipeline result requires an executed search stage")
        runnable = {StageStatus.SUCCESS, StageStatus.PARTIAL_SUCCESS}
        for upstream, downstream, has_input in (
            (stages.search, stages.exploration, bool(self.discovered_sources)),
            (stages.exploration, stages.profiling, bool(successful_sources)),
            (stages.profiling, stages.analysis, bool(self.exposures)),
        ):
            should_run = upstream in runnable and has_input
            if (downstream != StageStatus.NOT_STARTED) != should_run:
                raise ValueError("Stage execution must match upstream status and available input")
        if stages.search == StageStatus.FAILED and self.discovered_sources:
            raise ValueError("Failed search cannot publish discovered sources")
        if stages.search == StageStatus.PARTIAL_SUCCESS and not self.discovered_sources:
            raise ValueError("Partial search requires discovered sources")
        if stages.exploration not in runnable and successful_sources:
            raise ValueError("Failed or skipped exploration cannot publish acquired pages")
        if stages.exploration == StageStatus.NOT_STARTED and (self.navigation_history or self.exploration_limit_reached):
            raise ValueError("Skipped exploration cannot publish navigation output")
        if stages.exploration == StageStatus.PARTIAL_SUCCESS and not successful_sources:
            raise ValueError("Partial exploration requires an acquired page")
        if stages.exploration == StageStatus.SUCCESS and (
            has_technical_navigation_failure(self.navigation_history)
            or (successful_sources and self.exploration_limit_reached)
        ):
            raise ValueError("Successful exploration cannot contain technical failures or incomplete acquisition")
        if stages.profiling not in runnable and self.exposures:
            raise ValueError("Failed or skipped profiling cannot publish exposures")
        if stages.profiling == StageStatus.NOT_STARTED and self.sources:
            raise ValueError("Skipped profiling cannot publish sources")
        if stages.analysis not in runnable and (
            self.personal_profile is not None or self.relationship_graph.nodes
            or self.phishing_risk_scenarios or self.security_recommendations
        ):
            raise ValueError("Failed or skipped analysis cannot publish analysis output")
        for stage in Stages.model_fields:
            duration = getattr(self.execution_time, f"{stage}_ms")
            not_started = getattr(self.stages, stage) == StageStatus.NOT_STARTED
            if (duration is None) != not_started:
                raise ValueError("Stage duration must be present only for executed stages")
            if duration is not None and duration > self.execution_time.total_ms:
                raise ValueError("Stage duration cannot exceed total duration")
        counts = {
            "search_result_count": len(self.discovered_sources),
            "confirmed_source_count": sum(
                source.identity_status == IdentityStatus.CONFIRMED for source in self.sources
            ),
            "total_exposures": len(self.exposures),
            "total_graph_nodes": len(self.relationship_graph.nodes),
            "total_graph_edges": len(self.relationship_graph.edges),
            "total_scenarios": len(self.phishing_risk_scenarios),
            "total_recommendations": len(self.security_recommendations),
        }
        if any(getattr(self.summary, field) != count for field, count in counts.items()):
            raise ValueError("Summary counts do not match result collections")
        eligible_visits = {
            item.source_id for item in self.navigation_history if item.status != NavigationStatus.SKIPPED
        }
        if self.summary.visited_page_count > len(eligible_visits):
            raise ValueError("Visited page count exceeds unique navigation sources")
        return self
