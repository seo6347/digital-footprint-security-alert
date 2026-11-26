"""Common models and enums from the v0.1 team specification."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr

# ----------------------------------------------------------------------------
# Common Contract Models
# ----------------------------------------------------------------------------

# 모든 Public Contract가 공유하는 Pydantic 기반 모델
# 정의되지 않은 필드는 거부하고 기본값까지 검증해 모듈 간 Schema 불일치 방지
class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

# A/B/C 모듈의 request가 공유하는 필드.
# request_id는 Orchestrator가 생성하며, Contract는 구조와 타입만 정의함.
class RequestContract(ContractModel):
    schema_version: Literal["v0.1"]
    # Supplied by the Orchestrator; contracts never generate IDs.
    request_id: str

# ----------------------------------------------------------------------------
# Module Status Enums
# ----------------------------------------------------------------------------

# 실제 Module의 실행 결과로, 정상적인 0건 결과도 success일 수 있음.
class ModuleStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"

# Orchestrator의 단계별 실행 상태로, ModuleStatus와 비슷하나 조금 다름.
# 후속 Module을 호출하지 않은 경우 failed가 아닌 not_started로 표시함.
class StageStatus(str, Enum):
    NOT_STARTED = "not_started"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"

# 모듈 A 주로 사용, 개별 검색 Query 처리 결과
class QueryStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"

# 모듈 A 주로 사용, 검색 결과의 관련성 판단
class RelevanceStatus(str, Enum):
    CANDIDATE = "candidate"
    UNCERTAIN = "uncertain"

# 모듈 A 주로 사용, 검색 결과의 관련성 판단 근거
class RelevanceReason(str, Enum):
    NAME_MATCH = "name_match"
    ORGANIZATION_MATCH = "organization_match"
    EMAIL_EXACT_MATCH = "email_exact_match"
    OFFICIAL_DOMAIN_MATCH = "official_domain_match"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"

# 모듈 B 주로 사용, 검색 결과가 대상 인물의 정보인지 검증
class IdentityStatus(str, Enum):
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"
    REJECTED = "rejected"

# 모듈 B 주로 사용, 개별 Source 처리 결과
class ProcessingStatus(str, Enum):
    SUCCESS = "success"
    FETCH_FAILED = "fetch_failed"
    PARSE_FAILED = "parse_failed"
    UNSUPPORTED = "unsupported"
    REJECTED = "rejected"

# 모듈 B,C 주로 사용, 추출된 노출 정보의 종류
class ExposureType(str, Enum):
    IDENTITY = "identity"
    CONTACT = "contact"
    AFFILIATION = "affiliation"
    RELATIONSHIP = "relationship"
    ACTIVITY = "activity"
    INTEREST = "interest"
    ACCOUNT = "account"
    TEMPORAL = "temporal"

# 모듈 C 주로 사용, 위험 시나리오 유형
class RiskCategory(str, Enum):
    AUTHORITY_IMPERSONATION = "authority_impersonation"
    ACADEMIC_IMPERSONATION = "academic_impersonation"
    RECRUITMENT_IMPERSONATION = "recruitment_impersonation"
    EVENT_IMPERSONATION = "event_impersonation"
    ACCOUNT_IMPERSONATION = "account_impersonation"

# 모듈 C 주로 사용, 위험 경로의 판단 상태
class RiskPathStatus(str, Enum):
    CANDIDATE = "candidate"
    SUPPORTED = "supported"

# 모듈 C 주로 사용, 위험 평가 항목의 판단값
class EvaluationValue(str, Enum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"

# ----------------------------------------------------------------------------
# Common Contract Models
# ----------------------------------------------------------------------------

# 전체 pipeline에서 공유하는 분석 대상 정보.
# 형식 검증만 수행하며, 실제 인물과 정보의 일치 여부는 Module B에서 판단함.
class Subject(ContractModel):
    name: str
    organization: str
    email: EmailStr

# A/B/C 모듈이 공통으로 사용하는 오류 정보
# source_id와 query_id는 오류가 특정 Source나 Query에 연결되는 경우에만 제공한다.
class ErrorDetail(ContractModel):
    code: str
    message: str
    retryable: bool
    source_id: str | None = None
    query_id: str | None = None
