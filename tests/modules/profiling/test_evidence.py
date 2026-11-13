"""Validate original HTML spans independently of candidate discovery."""

from dataclasses import replace
from html import unescape

import pytest

from dfsa.contracts.common import ExposureType, IdentityStatus, Subject
from dfsa.modules.profiling._types import ExtractionDiagnostic, ValidatedExposureCandidate
from dfsa.modules.profiling.evidence import EvidenceContext, validate_candidate
from dfsa.modules.profiling.extraction import extract_exposures
from dfsa.modules.profiling.identity import verify_identity


@pytest.fixture
def sample(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>Research Interests: AI</p>'))
    identity = verify_identity(phase4_subject, document)
    result = extract_exposures(document, identity)
    candidate = next(c for c in result.candidates if c.type == ExposureType.INTEREST)
    return document, identity, candidate


def test_accepted_candidate_can_be_revalidated(sample):
    document, identity, candidate = sample
    assert validate_candidate(document, identity, candidate) == candidate


@pytest.mark.parametrize("change", [{"source_id": "wrong"}, {"type": "interest"}, {"value": " "}])
def test_malformed_candidate_is_not_disguised_as_no_evidence(sample, change):
    document, identity, candidate = sample
    with pytest.raises(ValueError):
        validate_candidate(document, identity, replace(candidate, **change))


@pytest.mark.parametrize("indices", [(), (-1,), (999,), (True,), (2, 1), (1, 1)])
def test_invalid_evidence_text_indices_raise(sample, indices):
    document, identity, candidate = sample
    with pytest.raises(ValueError, match="indices"):
        validate_candidate(document, identity, replace(candidate, evidence=replace(candidate.evidence, text_indices=indices)))


@pytest.mark.parametrize("field,value", [("block_id", 999), ("block_id", 0), ("start", 0),
                                         ("end", 99999), ("quote", "Alice Kim is an AI expert")])
def test_wrong_block_offsets_or_invented_quote_raise(sample, field, value):
    document, identity, candidate = sample
    with pytest.raises(ValueError):
        validate_candidate(document, identity, replace(candidate, evidence=replace(candidate.evidence, **{field: value})))


@pytest.mark.parametrize("change", [
    {"value": "Robotics"}, {"type": ExposureType.RELATIONSHIP, "relation": "advisor"},
    {"relation": "advisor"}, {"value": "alice@example.com"},
])
def test_real_quote_does_not_validate_wrong_type_value_or_relation(sample, change):
    document, identity, candidate = sample
    result = validate_candidate(document, identity, replace(candidate, **change))
    assert isinstance(result, ExtractionDiagnostic) and result.code == "unsupported_type_or_value"


@pytest.mark.parametrize("status", [IdentityStatus.UNCERTAIN, IdentityStatus.REJECTED])
def test_validation_independently_requires_confirmation(sample, status):
    document, identity, candidate = sample
    result = validate_candidate(document, replace(identity, identity_status=status), candidate)
    assert result.code == "outside_confirmed_scope"


def test_wrong_identity_source_rejected_in_both_entrypoints(sample):
    document, identity, candidate = sample
    identity = replace(identity, source_id="other")
    for function, args in ((extract_exposures, (document, identity)),
                           (validate_candidate, (document, identity, candidate))):
        with pytest.raises(ValueError, match="source_id"):
            function(*args)


def test_correct_evidence_in_another_person_scope_is_excluded(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card() + phase4_card('<p>Research Interests: Robotics</p>', "Bob Lee"))
    alice = verify_identity(phase4_subject, document)
    bob = verify_identity(Subject(name="Bob Lee", email="alice@example.com", organization="Example University"), document)
    foreign = next(c for c in extract_exposures(document, bob).candidates if c.type == ExposureType.INTEREST)
    result = validate_candidate(document, alice, replace(foreign, target_block_id=alice.target_block_ids[0]))
    assert result.code == "outside_confirmed_scope"


@pytest.mark.parametrize("html,expected", [
    ("Artificial &amp; Computational Intelligence", "Artificial & Computational Intelligence"),
    ("AI &amp;lt; ML", "AI &lt; ML"),
    ("AI &#38; ML", "AI & ML"),
    ("AI &nbsp; ML", "AI ML"),
    ("  Artificial\n   Intelligence  ", "Artificial Intelligence"),
    ("&#54620;&#44544; AI", "한글 AI"),
])
def test_entities_and_normalized_value_keep_exact_original_span(phase4_parse, phase4_card, phase4_subject, html, expected):
    document = phase4_parse(phase4_card(f'<p>Research Interests: {html}</p>'))
    identity = verify_identity(phase4_subject, document)
    candidate = next(c for c in extract_exposures(document, identity).candidates if c.type == ExposureType.INTEREST)
    assert candidate.value == expected
    ref = candidate.evidence
    assert unescape(document.html_text[ref.start:ref.end]) == ref.quote
    assert ref.quote == "".join(document.texts[i].raw_text for i in ref.text_indices)
    assert validate_candidate(document, identity, candidate) == candidate


def test_normalized_text_is_never_substituted_for_raw_quote(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>Research Interests:  Artificial\n Intelligence</p>'))
    identity = verify_identity(phase4_subject, document)
    candidate = next(c for c in extract_exposures(document, identity).candidates if c.type == ExposureType.INTEREST)
    assert candidate.evidence.quote != candidate.value
    bad = replace(candidate, evidence=replace(candidate.evidence, quote=candidate.evidence.quote.casefold()))
    with pytest.raises(ValueError):
        validate_candidate(document, identity, bad)


@pytest.mark.parametrize("field", [
    '<p>Research Interests: Artificial <b>Intelligence</b></p>',
    '<p>Research Interests: Artificial<!-- gap --> Intelligence</p>',
    '<p>Research Interests: Artificial<br>Intelligence</p>',
])
def test_noncontiguous_value_never_becomes_synthetic_quote(phase4_parse, phase4_card, phase4_subject, field):
    document = phase4_parse(phase4_card(field))
    result = extract_exposures(document, verify_identity(phase4_subject, document))
    assert not any(c.type == ExposureType.INTEREST for c in result.candidates)
    # Other valid fields continue when one candidate lacks a contiguous quote.
    assert any(c.type == ExposureType.CONTACT for c in result.candidates)


def test_separate_inline_label_context_never_borrows_matching_word(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>Research Interests: <strong>Research</strong></p>'))
    identity = verify_identity(phase4_subject, document)
    candidate = next(c for c in extract_exposures(document, identity).candidates if c.type == ExposureType.INTEREST)
    assert candidate.value == candidate.evidence.quote == "Research"
    ctx = EvidenceContext(document, identity)
    unit = ctx.by_index[candidate.evidence.text_indices[0]]
    label_ref = ctx.references(unit)[0]
    assert "Research" in label_ref.quote
    result = validate_candidate(document, identity, replace(candidate, evidence=label_ref))
    assert result.code == "value_not_in_contiguous_evidence"


def test_multispan_name_attribution_does_not_invent_identity_quote(phase4_parse):
    subject = Subject(name="Anne & Kim", email="anne@example.com", organization="Example University")
    document = phase4_parse('<div class=profile-card><h2>Anne <b>&amp;</b> Kim</h2><p>anne@example.com</p></div>')
    identity = verify_identity(subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extract_exposures(document, identity)
    assert not any(c.type == ExposureType.IDENTITY for c in result.candidates)
    contact = next(c for c in result.candidates if c.type == ExposureType.CONTACT)
    assert len(contact.attribution) == 3
    assert [ref.quote for ref in contact.attribution] == ["Anne ", "&", " Kim"]
    assert result.diagnostics[0].code == "value_not_in_contiguous_evidence"


@pytest.mark.parametrize("mutation", ["raw", "start", "parent", "cycle", "duplicate", "text_block"])
def test_corrupt_parsed_document_is_explicit_error(sample, mutation):
    document, identity, candidate = sample
    index = candidate.evidence.text_indices[0]
    if mutation in {"raw", "start", "text_block"}:
        changes = {"raw": {"raw_text": "Invented evidence"}, "start": {"start": 0}, "text_block": {"block_id": 999}}
        texts = list(document.texts)
        texts[index] = replace(texts[index], **changes[mutation])
        document = replace(document, texts=tuple(texts))
    else:
        blocks = list(document.blocks)
        if mutation == "duplicate":
            blocks.append(blocks[-1])
        else:
            blocks[-1] = replace(blocks[-1], parent_id=999 if mutation == "parent" else blocks[-1].block_id)
        document = replace(document, blocks=tuple(blocks))
    with pytest.raises(ValueError):
        validate_candidate(document, identity, candidate)


@pytest.mark.parametrize("indices", [(), (999,), (-1,)])
def test_bad_phase3_name_reference_not_accepted_as_exposure_evidence(sample, indices):
    document, identity, _ = sample
    refs = tuple(replace(ref, text_indices=indices) if ref.kind == "name_match" else ref for ref in identity.evidence)
    with pytest.raises(ValueError):
        extract_exposures(document, replace(identity, evidence=refs))


def test_missing_name_evidence_excludes_automatic_attribution(sample):
    document, identity, _ = sample
    result = extract_exposures(document, replace(identity, evidence=()))
    assert not result.candidates and result.diagnostics[0].code == "ambiguous_attribution"


def test_context_from_another_input_is_rejected(sample):
    document, identity, candidate = sample
    context = EvidenceContext(document, identity)
    with pytest.raises(ValueError, match="context"):
        validate_candidate(replace(document), identity, candidate, context=context)


@pytest.mark.parametrize("field", [
    '<p>GitHub: <a href="https://github.com/bob">alice</a></p>',
    '<p><a href="https://github.com/alice">GitHub</a></p>',
    '<p>GitHub: <a href="https://github.com/alice/repo">alice</a></p>',
    '<p>GitHub: <a href="https://github.com/features">features</a></p>',
    '<p>GitHub: <a href="https://github.com.evil.example/alice">alice</a></p>',
    '<p>GitHub: <a href="javascript:alice">alice</a></p>',
    '<p>GitHub: <a href="https://github.com/alice?tab=repositories">alice</a></p>',
    '<p>GitHub: <a href="https://alice@github.com/alice">alice</a></p>',
    '<p>GitHub: <a href="https://[">alice</a></p>',
    '<p><a href="https://github.com/alice"></a></p>',
    '<p><a href="https://github.com/alice">https://github.com/alice</a></p>',
    '<p>GitHub: <a href="https://github.com//alice//">alice</a></p>',
    '<p>GitHub: <a href="https://github.com/\nalice">alice</a></p>',
])
def test_account_requires_displayed_username_and_profile_url(phase4_parse, phase4_card, phase4_subject, field):
    document = phase4_parse(phase4_card(field))
    result = extract_exposures(document, verify_identity(phase4_subject, document))
    assert not any(c.type == ExposureType.ACCOUNT for c in result.candidates)


def test_explicit_visible_github_profile_url(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>GitHub: <a href="https://github.com/alice">https://github.com/alice</a></p>'))
    result = extract_exposures(document, verify_identity(phase4_subject, document))
    assert [c.value for c in result.candidates if c.type == ExposureType.ACCOUNT] == ["https://github.com/alice"]


@pytest.mark.parametrize("field", [
    '<p>Email: example.com</p>', '<p>Email: alice</p>',
    '<p>Phone: 123</p>', '<p>Phone: 12345678901234567</p>',
    '<p>Assistant phone: 02-1234-5678</p>', '<p>Phone: Bob 02-1234-5678</p>',
])
def test_partial_contacts_and_foreign_phone_labels_excluded(phase4_parse, phase4_card, phase4_subject, field):
    document = phase4_parse(phase4_card(field))
    result = extract_exposures(document, verify_identity(phase4_subject, document))
    assert [c.value for c in result.candidates if c.type == ExposureType.CONTACT] == ["alice@example.com"]


@pytest.mark.parametrize("field", [
    '<p>Copyright: 2024</p>', '<p>Updated: 2024</p>', '<p>Year: 2024</p>',
    '<p>Project period: sometime</p>', '<p>Project period: 2024-99</p>',
])
def test_dates_need_explicit_personal_activity_context(phase4_parse, phase4_card, phase4_subject, field):
    document = phase4_parse(phase4_card(field))
    result = extract_exposures(document, verify_identity(phase4_subject, document))
    assert not any(c.type == ExposureType.TEMPORAL for c in result.candidates)


@pytest.mark.parametrize("field,kind,value", [
    ("이름: 홍길동", ExposureType.IDENTITY, "홍길동"),
    ("전화번호: 02-1234-5678", ExposureType.CONTACT, "02-1234-5678"),
    ("소속: 인공지능 연구실", ExposureType.AFFILIATION, "인공지능 연구실"),
    ("지도교수: 김교수", ExposureType.RELATIONSHIP, "김교수"),
    ("발표: 보안 학회 발표", ExposureType.ACTIVITY, "보안 학회 발표"),
    ("연구 관심 분야: 인공지능", ExposureType.INTEREST, "인공지능"),
    ("재직 기간: 2022–현재", ExposureType.TEMPORAL, "2022–현재"),
])
def test_korean_explicit_labels(phase4_parse, field, kind, value):
    subject = Subject(name="홍길동", email="hong@example.com", organization="예시대학교")
    name = '<p>이름: 홍길동</p>' if kind == ExposureType.IDENTITY else '<h2>홍길동</h2>'
    extra = '' if kind == ExposureType.IDENTITY else f'<p>{field}</p>'
    document = phase4_parse(f'<div class=profile-card>{name}<p>hong@example.com</p>{extra}</div>')
    identity = verify_identity(subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extract_exposures(document, identity)
    assert any(c.type == kind and c.value == value for c in result.candidates)


def test_invalid_evidence_does_not_fall_back_to_phase3_match(sample):
    document, identity, candidate = sample
    # Corrupt the extraction quote while all Phase 3 identity evidence remains.
    with pytest.raises(ValueError):
        validate_candidate(document, identity, replace(candidate, evidence=replace(candidate.evidence, quote="AI")))


def test_inline_field_label_kept_as_separate_attribution_ref(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>Research Interests: <strong>AI</strong></p>'))
    identity = verify_identity(phase4_subject, document)
    candidate = next(c for c in extract_exposures(document, identity).candidates if c.type == ExposureType.INTEREST)
    assert candidate.evidence.quote == "AI"
    assert [ref.quote for ref in candidate.attribution] == ["Alice Kim", "Research Interests: "]
    for ref in candidate.attribution:
        assert unescape(document.html_text[ref.start:ref.end]) == ref.quote


def test_bad_inline_label_original_offsets_cannot_validate_value(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>Research Interests: <strong>AI</strong></p>'))
    identity = verify_identity(phase4_subject, document)
    candidate = next(c for c in extract_exposures(document, identity).candidates if c.type == ExposureType.INTEREST)
    index = candidate.attribution[-1].text_indices[0]
    texts = list(document.texts)
    texts[index] = replace(texts[index], start=0)
    with pytest.raises(ValueError, match="offsets"):
        validate_candidate(replace(document, texts=tuple(texts)), identity, candidate)


@pytest.mark.parametrize("change", [{"text": "forged"}, {"block_id": 999}, {"href": "https://github.com/other"}])
def test_corrupt_account_link_is_not_normal_absence(phase4_parse, phase4_card, phase4_subject, change):
    document = phase4_parse(phase4_card('<p>GitHub: <a href="https://github.com/alice">alice</a></p>'))
    identity = verify_identity(phase4_subject, document)
    bad = replace(document, links=(replace(document.links[0], **change),))
    with pytest.raises(ValueError, match="link"):
        extract_exposures(bad, identity)


def test_contact_ref_cannot_be_reused_as_identity_name_match(sample):
    document, identity, _ = sample
    email = next(ref for ref in identity.evidence if ref.kind == "email_exact_match")
    forged = replace(identity, evidence=(replace(email, kind="name_match"),))
    with pytest.raises(ValueError, match="name"):
        extract_exposures(document, forged)


def test_mixed_emails_need_independent_ownership_validation(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>Assistant Bob: bob@example.com</p>'))
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.UNCERTAIN
    # Even a claimed confirmed scope cannot bypass the Phase 4 contact rule.
    root = next(b.block_id for b in document.blocks if dict(b.attributes).get("class") == "profile-card")
    claimed = replace(identity, identity_status=IdentityStatus.CONFIRMED, target_block_ids=(root,))
    result = extract_exposures(document, claimed)
    assert not any(c.type == ExposureType.CONTACT for c in result.candidates)


def test_nested_footer_fields_remain_excluded_independently(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<footer>Phone: 02-9999-9999</footer>'))
    identity = verify_identity(phase4_subject, document)
    root = next(b.block_id for b in document.blocks if dict(b.attributes).get("class") == "profile-card")
    claimed = replace(identity, identity_status=IdentityStatus.CONFIRMED, target_block_ids=(root,))
    result = extract_exposures(document, claimed)
    assert not any(c.value == "02-9999-9999" for c in result.candidates)


@pytest.mark.parametrize("prop,value,kind", [
    ("email", "alice@example.com", ExposureType.CONTACT),
    ("telephone", "02-1234-5678", ExposureType.CONTACT),
    ("affiliation", "AI &amp; Security Lab", ExposureType.AFFILIATION),
])
@pytest.mark.parametrize("surround", [False, True])
def test_inline_semantic_value_keeps_own_block_and_offsets(phase4_parse, phase4_card, phase4_subject, prop, value, kind, surround):
    content = f'<span itemprop="{prop}">{value}</span>'
    if surround:
        label = {'email': 'Email', 'telephone': 'Phone', 'affiliation': 'Affiliation'}[prop]
        content = label + ': (' + content + ')'
    document = phase4_parse(phase4_card(f'<p>{content}</p>'))
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extract_exposures(document, identity)
    block = next(b for b in document.blocks if dict(b.attributes).get('itemprop') == prop)
    candidate = next(c for c in result.candidates if c.type == kind and c.evidence.block_id == block.block_id)
    assert candidate.value == unescape(value)
    assert candidate.evidence.quote == unescape(value)
    assert all(document.texts[i].block_id == block.block_id for i in candidate.evidence.text_indices)
    assert unescape(document.html_text[candidate.evidence.start:candidate.evidence.end]) == candidate.evidence.quote
    assert validate_candidate(document, identity, candidate) == candidate


def test_inline_name_and_email_use_real_identity_flow(phase4_parse, phase4_subject):
    document = phase4_parse('<div class=profile-card><p>Person: <span itemprop=name>Alice Kim</span></p>'
                            '<p><span itemprop=email>alice@example.com</span></p></div>')
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extract_exposures(document, identity)
    assert [(c.type, c.value) for c in result.candidates] == [
        (ExposureType.IDENTITY, 'Alice Kim'), (ExposureType.CONTACT, 'alice@example.com')]


@pytest.mark.parametrize("prop", ['telephone', 'affiliation'])
def test_plain_inline_text_does_not_acquire_semantics(phase4_parse, phase4_card, phase4_subject, prop):
    value = '02-1234-5678' if prop == 'telephone' else 'AI Lab'
    document = phase4_parse(phase4_card(f'<p><span>{value}</span></p>'))
    result = extract_exposures(document, verify_identity(phase4_subject, document))
    assert not any(c.value == value for c in result.candidates)


def test_multiple_semantic_fields_with_ambiguous_prose_are_excluded(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>Office <span itemprop=telephone>02-1234-5678</span>'
                                       ' affiliation <span itemprop=affiliation>AI Lab</span> notes</p>'))
    identity = verify_identity(phase4_subject, document)
    result = extract_exposures(document, identity)
    assert [c.value for c in result.candidates] == ['Alice Kim', 'alice@example.com']


@pytest.mark.parametrize("field", [
    '<span itemprop=telephone>02-<b>1234</b>-5678</span>',
    '<span itemprop="telephone affiliation">02-1234-5678</span>',
    '<span itemprop=affiliation>AI <span itemprop=telephone>02-1234-5678</span></span>',
])
def test_complex_semantic_structure_does_not_invent_quote(phase4_parse, phase4_card, phase4_subject, field):
    document = phase4_parse(phase4_card(f'<p>{field}</p>'))
    result = extract_exposures(document, verify_identity(phase4_subject, document))
    assert [c.value for c in result.candidates] == ['Alice Kim', 'alice@example.com']


def test_other_person_inline_fields_remain_outside_scope(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card() + '<div class=profile-card><span itemprop=name>Bob Lee</span>'
                            '<p><span itemprop=email>bob@example.com</span></p>'
                            '<p><span itemprop=telephone>02-9999-9999</span></p></div>')
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extract_exposures(document, identity)
    assert [c.value for c in result.candidates] == ['Alice Kim', 'alice@example.com']


@pytest.mark.parametrize("status", [IdentityStatus.UNCERTAIN, IdentityStatus.REJECTED])
def test_semantic_fields_still_require_confirmed(phase4_parse, phase4_card, phase4_subject, status):
    document = phase4_parse(phase4_card('<p><span itemprop=telephone>02-1234-5678</span></p>'))
    identity = replace(verify_identity(phase4_subject, document), identity_status=status)
    assert not extract_exposures(document, identity).candidates


def test_root_analysis_runs_once_for_many_candidates(phase4_parse, phase4_card, phase4_subject, monkeypatch):
    calls = []
    original = EvidenceContext._analyze_root
    def counted(self, root):
        calls.append((id(self), root))
        return original(self, root)
    monkeypatch.setattr(EvidenceContext, '_analyze_root', counted)
    document = phase4_parse(phase4_card('<p>Research Interests: AI</p>' * 100))
    identity = verify_identity(phase4_subject, document)
    result = extract_exposures(document, identity)
    assert len(result.candidates) == 102
    assert len(calls) == 1
    ctx = EvidenceContext(document, identity)
    for candidate in result.candidates:
        assert validate_candidate(document, identity, candidate, context=ctx) == candidate
    assert len(calls) == 2
    assert len(ctx._addresses) == 1


def test_cached_rejection_and_context_isolation(sample, phase4_parse, phase4_card, phase4_subject, monkeypatch):
    document, identity, _ = sample
    from dataclasses import asdict
    before = asdict(document), asdict(identity)
    first = EvidenceContext(document, identity)
    root = identity.target_block_ids[0]
    assert first.safe_root(root)
    second = EvidenceContext(document, replace(identity, evidence=()))
    assert second.safe_root(root) is False
    assert second.safe_root(root) is False
    other = phase4_parse(phase4_card('<p><span itemprop=telephone>02-1234-5678</span></p>'))
    other_identity = verify_identity(phase4_subject, other)
    result = extract_exposures(other, other_identity)
    candidate = result.candidates[-1]
    with pytest.raises(ValueError, match='context'):
        validate_candidate(other, other_identity, candidate, context=first)
    assert before == (asdict(document), asdict(identity))
    assert result == extract_exposures(other, other_identity)


@pytest.mark.parametrize('prop', ['alternateName', 'description'])
def test_original_name_attribution_survives_unsupported_inline_property(phase4_parse, phase4_subject, prop):
    document = phase4_parse(f'<div class=profile-card><h2><span itemprop="{prop}">Alice Kim</span></h2>'
                            '<p>Email: alice@example.com</p></div>')
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extract_exposures(document, identity)
    candidate = next(c for c in result.candidates if c.type == ExposureType.CONTACT)
    assert candidate.value == 'alice@example.com'
    assert candidate.target_block_id == identity.target_block_ids[0]
    name = next(ref for ref in identity.evidence if ref.kind == 'name_match')
    assert candidate.attribution[0].text_indices == name.text_indices
    assert candidate.attribution[0].block_id == name.block_id
    assert validate_candidate(document, identity, candidate) == candidate


def test_original_definition_label_survives_semantic_filtering(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<dl><dt><span itemprop=description>Research Interests</span></dt>'
                                      '<dd>AI</dd></dl>'))
    identity = verify_identity(phase4_subject, document)
    candidate = next(c for c in extract_exposures(document, identity).candidates if c.type == ExposureType.INTEREST)
    assert candidate.value == candidate.evidence.quote == 'AI'
    assert any(ref.quote == 'Research Interests' for ref in candidate.attribution)
    assert candidate.target_block_id == identity.target_block_ids[0]
    assert validate_candidate(document, identity, candidate) == candidate


@pytest.mark.parametrize('prop,value,prefix', [
    ('telephone', '02-9999-9999', 'Advisor Bob Lee phone:'),
    ('affiliation', 'Other Lab', 'Advisor Bob Lee affiliation:'),
    ('telephone', '02-9999-9999', 'Someone else phone:'),
    ('telephone', '02-9999-9999', 'Public field ('),
    ('affiliation', 'Other Lab', 'Unclear information:'),
    ('telephone', '02-9999-9999', 'Email:'),
])
def test_inline_semantics_cannot_override_ownership_context(phase4_parse, phase4_card, phase4_subject, prop, value, prefix):
    document = phase4_parse(phase4_card(f'<p>{prefix} <span itemprop="{prop}">{value}</span></p>'
                                       '<p>Phone: <span itemprop=telephone>02-1234-5678</span></p>'))
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extract_exposures(document, identity)
    assert not any(c.value == value for c in result.candidates)
    contact = next(c for c in result.candidates if c.value == '02-1234-5678')
    assert contact.type == ExposureType.CONTACT
    assert contact.target_block_id == identity.target_block_ids[0]
    assert contact.evidence.quote == '02-1234-5678'
    assert validate_candidate(document, identity, contact) == contact


def test_advisor_name_never_becomes_target_identity(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>Advisor: <span itemprop=name>Bob Lee</span></p>'))
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.UNCERTAIN
    assert not extract_exposures(document, identity).candidates
    root = next(b.block_id for b in document.blocks if dict(b.attributes).get('class') == 'profile-card')
    claimed = replace(identity, identity_status=IdentityStatus.CONFIRMED, target_block_ids=(root,))
    assert not extract_exposures(document, claimed).candidates


def test_foreign_inline_email_does_not_borrow_target_name(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>Advisor email: <span itemprop=email>bob@example.com</span></p>'))
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.UNCERTAIN
    assert not extract_exposures(document, identity).candidates
    root = next(b.block_id for b in document.blocks if dict(b.attributes).get('class') == 'profile-card')
    claimed = replace(identity, identity_status=IdentityStatus.CONFIRMED, target_block_ids=(root,))
    assert not any(c.type == ExposureType.CONTACT for c in extract_exposures(document, claimed).candidates)


def test_value_and_attribution_indices_validate_separately(phase4_parse, phase4_card, phase4_subject):
    from dataclasses import asdict
    document = phase4_parse(phase4_card('<p>Affiliation: <span itemprop=affiliation>AI &amp; Security Lab</span></p>'))
    identity = verify_identity(phase4_subject, document)
    before = asdict(document), asdict(identity)
    ctx = EvidenceContext(document, identity)
    result = extract_exposures(document, identity)
    candidate = next(c for c in result.candidates if c.type == ExposureType.AFFILIATION)
    assert candidate.value == candidate.evidence.quote == 'AI & Security Lab'
    assert candidate.target_block_id == identity.target_block_ids[0]
    assert ctx.validate_reference(candidate.evidence).block_id == candidate.evidence.block_id
    for ref in candidate.attribution:
        ctx.validate_reference(ref, attribution=True)
        assert unescape(document.html_text[ref.start:ref.end]) == ref.quote
        assert ref.quote == ''.join(document.texts[i].raw_text for i in ref.text_indices)
    assert any(ref.quote == 'Affiliation: ' for ref in candidate.attribution)
    assert validate_candidate(document, identity, candidate, context=ctx) == candidate
    with pytest.raises(ValueError, match='context'):
        validate_candidate(replace(document), identity, candidate, context=ctx)
    assert before == (asdict(document), asdict(identity))
    assert result == extract_exposures(document, identity)


def test_tampered_original_attribution_still_raises(phase4_parse, phase4_subject):
    document = phase4_parse('<div class=profile-card><h2><span itemprop=alternateName>Alice Kim</span></h2>'
                            '<p>alice@example.com</p></div>')
    identity = verify_identity(phase4_subject, document)
    candidate = next(c for c in extract_exposures(document, identity).candidates if c.type == ExposureType.CONTACT)
    name_index = candidate.attribution[0].text_indices[0]
    texts = list(document.texts)
    texts[name_index] = replace(texts[name_index], start=0)
    with pytest.raises(ValueError):
        validate_candidate(replace(document, texts=tuple(texts)), identity, candidate)
