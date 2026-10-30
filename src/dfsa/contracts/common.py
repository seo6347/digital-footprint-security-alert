"""Common models and enums from the v0.1 team specification."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class RequestContract(ContractModel):
    schema_version: Literal["v0.1"]
    # Supplied by the Orchestrator; contracts never generate IDs.
    request_id: str


class ModuleStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


class StageStatus(str, Enum):
    NOT_STARTED = "not_started"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


class QueryStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class RelevanceStatus(str, Enum):
    CANDIDATE = "candidate"
    UNCERTAIN = "uncertain"


class RelevanceReason(str, Enum):
    NAME_MATCH = "name_match"
    ORGANIZATION_MATCH = "organization_match"
    EMAIL_EXACT_MATCH = "email_exact_match"
    OFFICIAL_DOMAIN_MATCH = "official_domain_match"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class IdentityStatus(str, Enum):
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"
    REJECTED = "rejected"


class ProcessingStatus(str, Enum):
    SUCCESS = "success"
    FETCH_FAILED = "fetch_failed"
    PARSE_FAILED = "parse_failed"
    UNSUPPORTED = "unsupported"
    REJECTED = "rejected"


class ExposureType(str, Enum):
    IDENTITY = "identity"
    CONTACT = "contact"
    AFFILIATION = "affiliation"
    RELATIONSHIP = "relationship"
    ACTIVITY = "activity"
    INTEREST = "interest"
    ACCOUNT = "account"
    TEMPORAL = "temporal"


class RiskCategory(str, Enum):
    AUTHORITY_IMPERSONATION = "authority_impersonation"
    ACADEMIC_IMPERSONATION = "academic_impersonation"
    RECRUITMENT_IMPERSONATION = "recruitment_impersonation"
    EVENT_IMPERSONATION = "event_impersonation"
    ACCOUNT_IMPERSONATION = "account_impersonation"


class RiskPathStatus(str, Enum):
    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    UNVERIFIED = "unverified"
    NOT_ASSESSED = "not_assessed"


class EvaluationValue(str, Enum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Subject(ContractModel):
    name: str
    organization: str
    email: EmailStr


class ErrorDetail(ContractModel):
    code: str
    message: str
    retryable: bool
    source_id: str | None = None
    query_id: str | None = None
