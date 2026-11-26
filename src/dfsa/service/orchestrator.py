"""Coordinate the four v0.2 callable boundaries and assemble the UI result."""

from collections.abc import Callable
from time import perf_counter
from typing import NoReturn, TypeVar
from uuid import uuid4

from dfsa.contracts import (
    AnalysisRequest, AnalysisResponse, DFSAResult, ErrorDetail, ExecutionTime, ExplorationRequest,
    ExplorationResult, IdentityStatus, ModuleStatus, ProfilingRequest, ProfilingResponse,
    RelationshipGraph, ResultSummary, SearchRequest, SearchResponse, StageStatus, Stages, Subject,
)
from dfsa.contracts.analysis import validate_analysis_references
from dfsa.contracts.common import RequestContract
from dfsa.contracts.exploration import validate_navigation


def _not_connected(request: RequestContract) -> NoReturn:
    raise RuntimeError(f"No v0.2 module connected for {type(request).__name__}")


run_search: Callable[[SearchRequest], SearchResponse] = _not_connected
run_exploration: Callable[[ExplorationRequest], ExplorationResult] = _not_connected
run_profiling: Callable[[ProfilingRequest], ProfilingResponse] = _not_connected
run_analysis: Callable[[AnalysisRequest], AnalysisResponse] = _not_connected

Request = TypeVar("Request", bound=RequestContract)
Response = TypeVar("Response", bound=RequestContract)


def _call(
    module: Callable[[Request], Response], request: Request, model: type[Response],
) -> tuple[Response, float]:
    local_request = request.model_copy(deep=True)
    request_id = local_request.request_id
    start = perf_counter()
    response = module(local_request)
    duration = (perf_counter() - start) * 1000
    validated = model.model_validate(response)
    if validated.request_id != request_id:
        raise ValueError(f"{model.__name__} request_id does not match the pipeline")
    return validated, duration


def _stage(response: SearchResponse | ExplorationResult | ProfilingResponse | AnalysisResponse | None) -> StageStatus:
    return StageStatus.NOT_STARTED if response is None else StageStatus(response.status.value)


def run_pipeline(subject: Subject) -> DFSAResult:
    """Run the connected v0.2 modules and preserve each completed stage's results."""
    start = perf_counter()
    subject = Subject.model_validate(subject)
    request_id = f"req_{uuid4().hex}"
    scope = {"schema_version": "v0.2", "request_id": request_id}
    search, search_ms = _call(run_search, SearchRequest(**scope, subject=subject), SearchResponse)

    exploration = profiling = analysis = None
    exploration_ms = profiling_ms = analysis_ms = None
    if search.status != ModuleStatus.FAILED and search.results:
        exploration, exploration_ms = _call(
            run_exploration,
            ExplorationRequest(**scope, subject=subject, search_results=search.results),
            ExplorationResult,
        )
        validate_navigation(exploration.navigation_history, search.results)

    if exploration is not None and exploration.status != ModuleStatus.FAILED and exploration.documents:
        profiling, profiling_ms = _call(
            run_profiling,
            ProfilingRequest(**scope, subject=subject, documents=exploration.documents),
            ProfilingResponse,
        )
        source_urls = {document.source_id: document.final_url for document in exploration.documents}
        for source in profiling.sources:
            if source_urls.get(source.source_id) != source.url:
                raise ValueError("Profiling source must match the acquired document and final URL")
        missing_ids = source_urls.keys() - {source.source_id for source in profiling.sources}
        if profiling.status == ModuleStatus.PARTIAL_SUCCESS:
            missing_ids.difference_update(error.source_id for error in profiling.errors)
        if missing_ids and profiling.status != ModuleStatus.FAILED:
            raise ValueError("Profiling response omitted processing results for acquired documents")
        if profiling.status == ModuleStatus.SUCCESS and any(
            source.identity_status is None for source in profiling.sources
        ):
            raise ValueError("Successful profiling must complete identity decisions for acquired documents")

    if profiling is not None and profiling.status != ModuleStatus.FAILED and profiling.exposures:
        analysis, analysis_ms = _call(
            run_analysis,
            AnalysisRequest(**scope, subject=subject, exposures=profiling.exposures),
            AnalysisResponse,
        )
        validate_analysis_references(analysis.personal_profile, analysis.relationship_graph, profiling.exposures)

    stages = Stages(
        search=_stage(search), exploration=_stage(exploration),
        profiling=_stage(profiling), analysis=_stage(analysis),
    )
    errors: list[ErrorDetail] = []
    for response in (search, exploration, profiling, analysis):
        if response is not None:
            for error in response.errors:
                if error not in errors:
                    errors.append(error)

    sources = profiling.sources if profiling is not None else []
    exposures = profiling.exposures if profiling is not None else []
    graph = analysis.relationship_graph if analysis is not None else RelationshipGraph()
    scenarios = analysis.phishing_risk_scenarios if analysis is not None else []
    recommendations = analysis.security_recommendations if analysis is not None else []
    summary = ResultSummary(
        search_result_count=len(search.results),
        visited_page_count=len(set(exploration.attempted_source_ids)) if exploration is not None else 0,
        confirmed_source_count=sum(source.identity_status == IdentityStatus.CONFIRMED for source in sources),
        total_exposures=len(exposures), total_graph_nodes=len(graph.nodes), total_graph_edges=len(graph.edges),
        total_scenarios=len(scenarios), total_recommendations=len(recommendations),
    )
    return DFSAResult(
        **scope,
        status=stages.overall_status(),
        subject=subject,
        stages=stages,
        search_history=search.queries,
        discovered_sources=search.results,
        navigation_history=exploration.navigation_history if exploration is not None else [],
        exploration_limit_reached=exploration.limit_reached if exploration is not None else False,
        sources=sources,
        exposures=exposures,
        personal_profile=analysis.personal_profile if analysis is not None else None,
        relationship_graph=graph,
        phishing_risk_scenarios=scenarios,
        security_recommendations=recommendations,
        execution_time=ExecutionTime(
            total_ms=(perf_counter() - start) * 1000, search_ms=search_ms, exploration_ms=exploration_ms,
            profiling_ms=profiling_ms, analysis_ms=analysis_ms,
        ),
        summary=summary,
        errors=errors,
    )
