
"""Public entry point for Module C v0.2 analysis."""

from dfsa.contracts.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    RelationshipGraph,
    validate_analysis_references,
)
from dfsa.contracts.common import (
    ErrorDetail,
    ModuleStatus,
)

from .profile import build_personal_profile
from .graph import build_relationship_graph
from .scenarios import build_phishing_risk_scenarios
from .recommendations import build_security_recommendations


def run_analysis(
    request: AnalysisRequest,
) -> AnalysisResponse:

    profile = None
    graph = RelationshipGraph()
    scenarios = []
    recommendations = []
    errors = []

    exposures = request.exposures

    # 1. Personal Profile
    try:
        profile = build_personal_profile(exposures)

    except Exception:
        errors.append(
            ErrorDetail(
                code="PROFILE_GENERATION_ERROR",
                message="Personal profile generation failed.",
                retryable=False,
            )
        )

    # 2. Relationship Graph
    try:
        graph = build_relationship_graph(
            request.subject,
            exposures,
        )

    except Exception:
        errors.append(
            ErrorDetail(
                code="GRAPH_GENERATION_ERROR",
                message="Relationship graph generation failed.",
                retryable=False,
            )
        )

    # 3. Educational Risk Scenarios
    try:
        scenarios = build_phishing_risk_scenarios(
            exposures
        )

    except Exception:
        errors.append(
            ErrorDetail(
                code="SCENARIO_GENERATION_ERROR",
                message="Educational scenario generation failed.",
                retryable=False,
            )
        )

    # 4. Security Recommendations
    try:
        recommendations = build_security_recommendations(
            exposures
        )

    except Exception:
        errors.append(
            ErrorDetail(
                code="RECOMMENDATION_GENERATION_ERROR",
                message="Security recommendation generation failed.",
                retryable=False,
            )
        )

    # 5. Validate output references
    try:
        validate_analysis_references(
            profile,
            graph,
            exposures,
            scenarios=scenarios,
            recommendations=recommendations,
        )

    except Exception:
        errors.append(
            ErrorDetail(
                code="ANALYSIS_REFERENCE_ERROR",
                message="Analysis reference validation failed.",
                retryable=False,
            )
        )

        return AnalysisResponse(
            schema_version=request.schema_version,
            request_id=request.request_id,
            status=ModuleStatus.FAILED,
            errors=errors,
        )

    # 6. Determine response status
    has_results = bool(
        profile is not None
        or graph.nodes
        or scenarios
        or recommendations
    )

    if not errors:
        status = ModuleStatus.SUCCESS

    elif has_results:
        status = ModuleStatus.PARTIAL_SUCCESS

    else:
        status = ModuleStatus.FAILED

    # 7. Build final response
    return AnalysisResponse(
        schema_version=request.schema_version,
        request_id=request.request_id,
        status=status,
        personal_profile=profile,
        relationship_graph=graph,
        phishing_risk_scenarios=scenarios,
        security_recommendations=recommendations,
        errors=errors,
    )
