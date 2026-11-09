"""Unit tests for preliminary search-result relevance."""

import pytest

from dfsa.contracts.common import Subject
from dfsa.contracts.search import Relevance
from dfsa.modules.search.relevance import assess_relevance


@pytest.fixture
def subject():
    return Subject(
        name="홍길동",
        organization="숭실대학교",
        email="hong@ssu.ac.kr",
    )


def test_name_and_organization_match_is_candidate(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/profile",
        title="숭실대학교 연구실",
        snippet="홍길동 연구원 소개",
    )

    assert result.status == "candidate"
    assert result.reasons == [
        "name_match",
        "organization_match",
    ]


def test_exact_email_match_is_candidate(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/contact",
        snippet="문의: hong@ssu.ac.kr",
    )

    assert result.status == "candidate"
    assert result.reasons == ["email_exact_match"]


def test_all_matches_are_recorded(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/profile",
        title="숭실대학교 홍길동",
        snippet="이메일: hong@ssu.ac.kr",
    )

    assert result.status == "candidate"
    assert result.reasons == [
        "name_match",
        "organization_match",
        "email_exact_match",
    ]


def test_name_only_is_uncertain(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/profile",
        title="홍길동 소개",
    )

    assert result.status == "uncertain"
    assert result.reasons == [
        "name_match",
        "insufficient_evidence",
    ]


def test_organization_only_is_uncertain(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/lab",
        title="숭실대학교 연구실",
    )

    assert result.status == "uncertain"
    assert result.reasons == [
        "organization_match",
        "insufficient_evidence",
    ]


def test_no_matches_is_uncertain(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/news",
        title="일반 뉴스",
        snippet="관련 없는 검색 결과",
    )

    assert result.status == "uncertain"
    assert result.reasons == ["insufficient_evidence"]


@pytest.mark.parametrize("blank_value", [None, "", "   "])
def test_missing_metadata_is_uncertain(subject, blank_value):
    result = assess_relevance(
        subject,
        url="https://example.com/",
        title=blank_value,
        snippet=blank_value,
    )

    assert result.status == "uncertain"
    assert result.reasons == ["insufficient_evidence"]


def test_name_inside_longer_word_does_not_match(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/profile",
        title="숭실대학교",
        snippet="홍길동영 소개",
    )

    assert result.status == "uncertain"
    assert result.reasons == [
        "organization_match",
        "insufficient_evidence",
    ]


def test_organization_inside_longer_word_does_not_match(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/profile",
        title="홍길동",
        snippet="숭실대학교병원 안내",
    )

    assert result.status == "uncertain"
    assert result.reasons == [
        "name_match",
        "insufficient_evidence",
    ]


def test_organization_abbreviation_is_not_inferred(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/profile",
        title="숭실대 홍길동",
    )

    assert result.status == "uncertain"
    assert result.reasons == [
        "name_match",
        "insufficient_evidence",
    ]


def test_email_matching_is_case_insensitive(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/contact",
        snippet="연락처: HONG@SSU.AC.KR",
    )

    assert result.status == "candidate"
    assert result.reasons == ["email_exact_match"]


@pytest.mark.parametrize(
    "email_text",
    [
        "otherhong@ssu.ac.kr",
        "first.hong@ssu.ac.kr",
        "hong@ssu.ac.kr.evil",
        "hong@ssu.ac.kr-example.com",
        "hong@ssu.ac.kr_extra",
    ],
)
def test_email_substring_is_not_exact_match(subject, email_text):
    result = assess_relevance(
        subject,
        url="https://example.com/contact",
        snippet=f"연락처: {email_text}",
    )

    assert result.status == "uncertain"
    assert result.reasons == ["insufficient_evidence"]


@pytest.mark.parametrize(
    "email_text",
    [
        "<hong@ssu.ac.kr>",
        "(hong@ssu.ac.kr)",
        "이메일: hong@ssu.ac.kr, 연락 가능",
    ],
)
def test_email_with_surrounding_punctuation_matches(subject, email_text):
    result = assess_relevance(
        subject,
        url="https://example.com/contact",
        snippet=email_text,
    )

    assert result.status == "candidate"
    assert result.reasons == ["email_exact_match"]


def test_percent_encoded_email_in_url_matches(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/contact?email=hong%40ssu.ac.kr",
    )

    assert result.status == "candidate"
    assert result.reasons == ["email_exact_match"]


def test_percent_encoded_name_and_organization_in_url_match(subject):
    result = assess_relevance(
        subject,
        url=(
            "https://example.com/"
            "%ED%99%8D%EA%B8%B8%EB%8F%99/"
            "%EC%88%AD%EC%8B%A4%EB%8C%80%ED%95%99%EA%B5%90"
        ),
    )

    assert result.status == "candidate"
    assert result.reasons == [
        "name_match",
        "organization_match",
    ]


def test_english_terms_ignore_case_and_normalize_whitespace():
    subject = Subject(
        name="Hong Gildong",
        organization="Soongsil University",
        email="hong@ssu.ac.kr",
    )

    result = assess_relevance(
        subject,
        url="https://example.com/profile",
        title="HONG   GILDONG",
        snippet="SOONGSIL\tUNIVERSITY",
    )

    assert result.status == "candidate"
    assert result.reasons == [
        "name_match",
        "organization_match",
    ]


def test_unicode_compatibility_characters_are_normalized():
    subject = Subject(
        name="Hong",
        organization="SSU",
        email="hong@ssu.ac.kr",
    )

    result = assess_relevance(
        subject,
        url="https://example.com/profile",
        title="Ｈｏｎｇ",
        snippet="ＳＳＵ",
    )

    assert result.status == "candidate"
    assert result.reasons == [
        "name_match",
        "organization_match",
    ]


def test_term_is_not_created_by_joining_metadata_fields():
    subject = Subject(
        name="Hong Gildong",
        organization="Soongsil University",
        email="hong@ssu.ac.kr",
    )

    result = assess_relevance(
        subject,
        url="https://example.com/profile",
        title="Hong",
        snippet="Gildong",
    )

    assert result.status == "uncertain"
    assert result.reasons == ["insufficient_evidence"]


def test_email_domain_alone_does_not_imply_official_domain(subject):
    result = assess_relevance(
        subject,
        url="https://ssu.ac.kr/",
        title="대학 홈페이지",
    )

    assert result.status == "uncertain"
    assert result.reasons == ["insufficient_evidence"]
    assert "official_domain_match" not in result.reasons


def test_duplicate_matches_do_not_duplicate_reasons(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/profile",
        title="숭실대학교 홍길동",
        snippet="홍길동 / 숭실대학교 / 홍길동 / hong@ssu.ac.kr",
    )

    assert result.status == "candidate"
    assert result.reasons == [
        "name_match",
        "organization_match",
        "email_exact_match",
    ]


def test_returns_existing_contract_model(subject):
    result = assess_relevance(
        subject,
        url="https://example.com/contact",
        snippet="hong@ssu.ac.kr",
    )

    assert isinstance(result, Relevance)
    assert result.model_dump(mode="json") == {
        "status": "candidate",
        "reasons": ["email_exact_match"],
    }


def test_subject_is_not_modified(subject):
    original = subject.model_dump()

    assess_relevance(
        subject,
        url="https://example.com/profile",
        title="숭실대학교 홍길동",
        snippet="hong@ssu.ac.kr",
    )

    assert subject.model_dump() == original


def test_returned_reason_lists_are_independent(subject):
    first = assess_relevance(
        subject,
        url="https://example.com/first",
    )
    second = assess_relevance(
        subject,
        url="https://example.com/second",
    )

    assert first is not second
    assert first.reasons is not second.reasons

    first.reasons.clear()

    assert second.reasons == ["insufficient_evidence"]
