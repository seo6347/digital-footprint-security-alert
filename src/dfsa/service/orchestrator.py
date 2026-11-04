"""Coordinate contract-based modules; no search, profiling or risk business logic.

Wire run_search, run_profiling and run_risk once at application startup, before
calling run_pipeline. Tests replace these same callables with contract-valid
mocks. Unconnected modules and unexpected exceptions fail explicitly instead
of being converted to invented module statuses or ErrorDetail codes.
"""

from collections.abc import Callable
from typing import NoReturn
from uuid import uuid4

from dfsa.contracts import (
    DFSAResult,
    ProfilingRequest,
    ProfilingResponse,
    RiskRequest,
    RiskResponse,
    SearchRequest,
    SearchResponse,
    Subject,
)
from dfsa.contracts.common import ErrorDetail, IdentityStatus, ModuleStatus, StageStatus
from dfsa.contracts.result import ResultSummary, Stages

# 실제 Module 함수가 연결되지 않았을 때 명시적으로 실패하도록 하는 기본 함수.
# 미연결 상태를 정상 결과나 임의의 ModuleStatus로 처리하지 않는다.
def _not_connected(request: object) -> NoReturn:
    raise RuntimeError(f"No module connected for {type(request).__name__}")


# Dependency wiring only: assign matching public module functions at startup.
# A/B/C의 Public Interface를 연결하는 지점.
# 현재는 미연결 상태이며, 실제 구현 또는 Mock 함수로 교체하여 사용한다.
run_search: Callable[[SearchRequest], SearchResponse] = _not_connected
run_profiling: Callable[[ProfilingRequest], ProfilingResponse] = _not_connected
run_risk: Callable[[RiskRequest], RiskResponse] = _not_connected

# Pipeline 실행 단위의 request_id를 생성한다.
# 동일한 ID를 A/B/C 요청과 최종 DFSAResult에서 공유한다.
def _new_request_id() -> str:
    return f"req_{uuid4().hex}"

# 명세의 우선순위에 따라 전체 Pipeline 상태를 결정한다.
# A/B 실패는 전체 실패, C 실패는 부분 성공으로 처리한다.
def _overall_status(stages: Stages) -> ModuleStatus:
    """Apply spec section 24, including the special case for C failure."""
    if StageStatus.FAILED in (stages.search, stages.profiling): # A나 B가 실패하면 C가 실패하든 안하든 전체 실패
        return ModuleStatus.FAILED
    if stages.risk_analysis == StageStatus.FAILED: # C가 실패했을 때 A와 B가 모두 성공했으면 전체는 부분 성공
        return ModuleStatus.PARTIAL_SUCCESS
    if StageStatus.PARTIAL_SUCCESS in ( # A, B, C 중 하나라도 부분 성공이면 전체는 부분 성공
        stages.search, stages.profiling, stages.risk_analysis
    ):
        return ModuleStatus.PARTIAL_SUCCESS
    return ModuleStatus.SUCCESS

# A→B→C 순서로 ErrorDetail을 수집한다.
# 호출되지 않은 단계는 제외하고, 모든 필드가 동일한 오류는 한 번만 보존한다.
def _collect_errors(
    search: SearchResponse,
    profiling: ProfilingResponse | None,
    risk: RiskResponse | None,
) -> list[ErrorDetail]:
    """Preserve stage order and distinct details; do not append duplicates."""
    errors: list[ErrorDetail] = []
    for response in (search, profiling, risk):
        if response is not None:
            for error in response.errors:
                if error not in errors: # 완전히 같은 ErrorDetail이면 중복 제거
                    errors.append(error)
    return errors


def run_pipeline(subject: Subject) -> DFSAResult:
    """Run A -> B -> C with early termination and return the shared UI result.

    Each module must return its public response, including errors/status for
    expected failures. Module exceptions and invalid responses propagate to
    the caller; this skeleton does not define a new exception-to-error policy.
    """

    # subject 최초 입력 검증 및 deep copy(Module의 입력 변경으로부터 보호)
    subject = Subject.model_validate(subject).model_copy(deep=True)

    # request_id 생성 및 SearchRequest 생성 [사용자 입력을 바탕으로 모듈 A input 생성]
    request_id = _new_request_id()
    search_request = SearchRequest(
        schema_version="v0.1", request_id=request_id,
        subject=subject.model_copy(deep=True),
    )
    # A 모듈 호출하여 output 검증 후 SearchResponse 생성 [모듈 A output 생성]
    search = SearchResponse.model_validate(run_search(search_request))
    profiling: ProfilingResponse | None = None
    risk: RiskResponse | None = None

    if search.status != ModuleStatus.FAILED and search.results: # 모듈 A가 실패하지 않았고, 결과가 존재할 때만 B 호출
        # ProfilingRequest 생성 [A output를 바탕으로 모듈 B input 생성]
        profiling_request = ProfilingRequest(
            schema_version="v0.1", request_id=request_id,
            subject=subject, search_results=search.results,
        ).model_copy(deep=True)

        # 모듈 B 호출하여 output 검증 후 ProfilingResponse 생성 [모듈 B output 생성]
        profiling = ProfilingResponse.model_validate(run_profiling(profiling_request))

        if profiling.status != ModuleStatus.FAILED and profiling.exposures: # 모듈 B가 실패하지 않았고, 결과가 존재할 때만 C 호출
            # RiskRequest 생성 [B output를 바탕으로 모듈 C input 생성]
            risk_request = RiskRequest(
                schema_version="v0.1", request_id=request_id,
                subject=subject, exposures=profiling.exposures,
            ).model_copy(deep=True)

            # 모듈 C 호출하여 output 검증 후 RiskResponse 생성 [모듈 C output 생성]
            risk = RiskResponse.model_validate(run_risk(risk_request))

    # 실제 실행한 Module은 응답 상태를 사용하고, 호출하지 않은 단계는 not_started로 표시한다.
    stages = Stages(
        search=StageStatus(search.status.value),
        profiling=(
            StageStatus(profiling.status.value) if profiling is not None
            else StageStatus.NOT_STARTED
        ),
        risk_analysis=(
            StageStatus(risk.status.value) if risk is not None
            else StageStatus.NOT_STARTED
        ),
    )
    sources = profiling.sources if profiling is not None else []
    exposures = profiling.exposures if profiling is not None else []
    risk_paths = risk.risk_paths if risk is not None else []
    return DFSAResult(
        schema_version="v0.1",
        request_id=request_id,
        status=_overall_status(stages),
        subject=subject,
        stages=stages,
        sources=sources,
        exposures=exposures,
        risk_paths=risk_paths,
        summary=ResultSummary(
            search_result_count=len(search.results),
            confirmed_source_count=sum(
                source.identity_status == IdentityStatus.CONFIRMED for source in sources
            ),
            total_exposures=len(exposures),
            total_risk_paths=len(risk_paths),
        ),
        errors=_collect_errors(search, profiling, risk),
    )
