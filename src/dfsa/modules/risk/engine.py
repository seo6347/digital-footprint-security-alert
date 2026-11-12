
"""DFSA Module C risk analysis engine."""

from dfsa.contracts.common import (
    EvaluationValue,
    ModuleStatus,
    RiskPathStatus,
)
from dfsa.contracts.risk import (
    RiskEvaluation,
    RiskPath,
    RiskRequest,
    RiskResponse,
    RiskSummary,
)

from .rules import match_rules
from .templates import generate_explanation
from .graph import build_exposure_graph
from .features import extract_features
from .evaluation import evaluate_risk


def run_risk(request: RiskRequest) -> RiskResponse:
    """Analyze validated exposures and return risk paths."""

    exposures = request.exposures

    # Step 1: R01-R05 rule matching
    matches = match_rules(exposures)

    # Step 2: Build the exposure-source graph
    graph = build_exposure_graph(exposures)

    risk_paths = []

    for index, match in enumerate(matches, start=1):

        # Step 3: Extract graph-based features
        features = extract_features(
            match,
            exposures,
            graph,
        )

        # Step 4: Evaluate available evidence
        assessment = evaluate_risk(features)

        # Step 5: Generate risk explanation
        reason, recommendations = generate_explanation(
            match.rule_id,
            match.category,
        )

        # Convert internal results to the team contract
        evaluation = RiskEvaluation(
            searchability=EvaluationValue(
                assessment.searchability.value
            ),
            cross_source_linkability=EvaluationValue(
                assessment.cross_source_linkability.value
            ),
            attack_utility=EvaluationValue(
                assessment.attack_utility.value
            ),
            sensitivity=EvaluationValue(
                assessment.sensitivity.value
            ),
            evidence_confidence=EvaluationValue(
                assessment.evidence_confidence.value
            ),
        )

        risk_path = RiskPath(
            risk_path_id=f"path_{index:03d}",
            rule_id=match.rule_id,
            category=match.category,
            path_status=RiskPathStatus(
                assessment.path_status
            ),
            exposure_ids=list(match.exposure_ids),
            evaluation=evaluation,
            reason=reason,
            recommendations=recommendations,
        )

        risk_paths.append(risk_path)

    return RiskResponse(
        schema_version=request.schema_version,
        request_id=request.request_id,
        status=ModuleStatus.SUCCESS,
        risk_paths=risk_paths,
        summary=RiskSummary(
            total_exposures=len(exposures),
            total_paths=len(risk_paths),
        ),
        errors=[],
    )

