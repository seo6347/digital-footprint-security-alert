import pytest
from pydantic import ValidationError

from dfsa.contracts.common import (
    ErrorDetail,
    EvaluationValue,
    ExposureType,
    IdentityStatus,
    ModuleStatus,
    ProcessingStatus,
    QueryStatus,
    RelevanceReason,
    RelevanceStatus,
    RiskCategory,
    RiskPathStatus,
    StageStatus,
    Subject,
)


def test_valid_subject(subject_data):
    subject = Subject.model_validate(subject_data)
    assert subject.model_dump() == subject_data


@pytest.mark.parametrize("email", ["invalid", "user@", "@univ.ac.kr", "user name@univ.ac.kr"])
def test_invalid_email_rejected(subject_data, email):
    with pytest.raises(ValidationError):
        Subject.model_validate({**subject_data, "email": email})


@pytest.mark.parametrize("field", ["name", "organization", "email"])
def test_subject_fields_required(subject_data, field):
    del subject_data[field]
    with pytest.raises(ValidationError, match=field):
        Subject.model_validate(subject_data)


def test_extra_subject_field_rejected(subject_data):
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Subject.model_validate({**subject_data, "subjects": []})


@pytest.mark.parametrize(("enum", "values"), [
    (ModuleStatus, {"success", "partial_success", "failed"}),
    (StageStatus, {"not_started", "success", "partial_success", "failed"}),
    (QueryStatus, {"success", "failed"}),
    (RelevanceStatus, {"candidate", "uncertain"}),
    (RelevanceReason, {"name_match", "organization_match", "email_exact_match",
                       "official_domain_match", "insufficient_evidence"}),
    (IdentityStatus, {"confirmed", "uncertain", "rejected"}),
    (ProcessingStatus, {"success", "fetch_failed", "parse_failed", "unsupported", "rejected"}),
    (ExposureType, {"identity", "contact", "affiliation", "relationship", "activity",
                    "interest", "account", "temporal"}),
    (RiskCategory, {"authority_impersonation", "academic_impersonation",
                    "recruitment_impersonation", "event_impersonation", "account_impersonation"}),
    (RiskPathStatus, {"candidate", "supported", "unverified", "not_assessed"}),
    (EvaluationValue, {"YES", "NO", "UNKNOWN", "NOT_APPLICABLE"}),
])
def test_enum_values_match_frozen_contract(enum, values):
    assert {item.value for item in enum} == values


def test_common_error_defaults():
    error = ErrorDetail(code="FETCH_FAILED", message="Unable to fetch", retryable=True)
    assert error.model_dump() == {
        "code": "FETCH_FAILED", "message": "Unable to fetch", "retryable": True,
        "source_id": None, "query_id": None,
    }


@pytest.mark.parametrize("field", ["code", "message", "retryable"])
def test_error_core_fields_required(field):
    data = {"code": "ERROR", "message": "Failed", "retryable": False}
    del data[field]
    with pytest.raises(ValidationError, match=field):
        ErrorDetail.model_validate(data)
