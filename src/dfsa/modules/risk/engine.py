
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
from .status import determine_path_status

def run_risk(request: RiskRequest) -> RiskResponse:
    """Analyze validated exposures and return risk paths."""

    matches = match_rules(request.exposures)
    risk_paths = []

    for index, match in enumerate(matches, start=1):
        reason, recommendations = generate_explanation(
            match.rule_id,
            match.category,
        )

        evaluation = RiskEvaluation(
            searchability=EvaluationValue.UNKNOWN,
            cross_source_linkability=EvaluationValue.UNKNOWN,
            attack_utility=EvaluationValue.UNKNOWN,
            sensitivity=EvaluationValue.UNKNOWN,
            evidence_confidence=EvaluationValue.UNKNOWN,
        )

        risk_path = RiskPath(
            risk_path_id=f"path_{index:03d}",
            rule_id=match.rule_id,
            category=match.category,
            path_status=determine_path_status(match,request.exposures,),
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
            total_exposures=len(request.exposures),
            total_paths=len(risk_paths),
        ),
        errors=[],
    )

