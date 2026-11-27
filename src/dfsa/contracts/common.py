"""Shared DFSA v0.2 models and values."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints

ID = Annotated[str, StringConstraints(pattern=r"\S")]
NonEmpty = Annotated[str, StringConstraints(pattern=r"\S")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
QueryID = Annotated[str, StringConstraints(pattern=r"^q_\S+$")]
SearchSourceID = Annotated[str, StringConstraints(pattern=r"^src_\S+$")]
SourceID = Annotated[str, StringConstraints(pattern=r"^(?:src_|nav_src_)\S+$")]
NavigationID = Annotated[str, StringConstraints(pattern=r"^nav_\S+$")]
ExposureID = Annotated[str, StringConstraints(pattern=r"^exp_\S+$")]
NodeID = Annotated[str, StringConstraints(pattern=r"^node_\S+$")]
EdgeID = Annotated[str, StringConstraints(pattern=r"^edge_\S+$")]
ScenarioID = Annotated[str, StringConstraints(pattern=r"^scenario_\S+$")]
RecommendationID = Annotated[str, StringConstraints(pattern=r"^rec_\S+$")]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True, revalidate_instances="always")


class RequestContract(ContractModel):
    schema_version: Literal["v0.2"]
    request_id: ID


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


class Subject(ContractModel):
    name: Name
    organization: Name
    email: EmailStr | None = None


class ErrorDetail(ContractModel):
    code: str
    message: str
    retryable: bool
    source_id: ID | None = None
    query_id: ID | None = None


def unique_ids(values, field: str) -> set[str]:
    identifiers: set[str] = set()
    for value in values:
        identifier = getattr(value, field)
        if identifier in identifiers:
            raise ValueError(f"Duplicate {field}")
        identifiers.add(identifier)
    return identifiers
