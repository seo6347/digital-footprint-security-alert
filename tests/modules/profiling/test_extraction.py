"""Phase 4 end-to-end rules over real Phase 2/3 results, without live fetching."""

from dataclasses import FrozenInstanceError, asdict, replace
from html import unescape
from pathlib import Path

import pytest

from dfsa.contracts.common import ExposureType, IdentityStatus, Subject
from dfsa.modules.profiling import extraction
from dfsa.modules.profiling._types import ExtractionResult, ValidatedExposureCandidate
from dfsa.modules.profiling.identity import verify_identity


def values(result, kind):
    return [c.value for c in result.candidates if c.type == kind]


@pytest.mark.parametrize("kind,field,expected,relation", [
    ("identity", "", "Alice Kim", None),
    ("contact", "<p>Phone: +82 10-1234-5678</p>", "+82 10-1234-5678", None),
    ("affiliation", "<p>Affiliation: AI Laboratory</p>", "AI Laboratory", None),
    ("relationship", "<p>Advisor: Professor Bob Lee</p>", "Professor Bob Lee", "advisor"),
    ("activity", "<p>Presentation: Presented DFSA at Example Conference</p>", "Presented DFSA at Example Conference", None),
    ("interest", "<p>Research Interests: Artificial Intelligence</p>", "Artificial Intelligence", None),
    ("account", '<p>GitHub: <a href="https://github.com/alice">alice</a></p>', "alice", None),
    ("temporal", "<p>Project period: 2022–2024</p>", "2022–2024", None),
])
def test_eight_types_have_explicit_attributed_evidence(phase4_parse, phase4_card, phase4_subject, kind, field, expected, relation):
    document = phase4_parse(phase4_card(field))
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extraction.extract_exposures(document, identity)
    matches = [c for c in result.candidates if c.type == ExposureType(kind) and c.value == expected]
    assert matches and matches[0].relation == relation
    for candidate in result.candidates:
        assert isinstance(candidate, ValidatedExposureCandidate)
        assert candidate.source_id == document.source_id
        assert candidate.target_block_id in identity.target_block_ids
        assert candidate.attribution
        for ref in (candidate.evidence, *candidate.attribution):
            assert ref.quote == "".join(document.texts[i].raw_text for i in ref.text_indices)
            assert ref.start == document.texts[ref.text_indices[0]].start
            assert ref.end == document.texts[ref.text_indices[-1]].end
            assert unescape(document.html_text[ref.start:ref.end]) == ref.quote
        assert not hasattr(candidate, "exposure_id")


@pytest.mark.parametrize("kind,field", [
    ("identity", "<p>Nickname suggested by visitor: Bob Lee</p>"),
    ("contact", "<p>Assistant Bob: bob@example.com</p><p>example.com</p>"),
    ("affiliation", "<p>Website operated by Example University</p>"),
    ("relationship", "<p>Bob Lee is also on this page</p>"),
    ("activity", "<p>Conference menu</p>"),
    ("interest", "<p>Our lab's research interests: Robotics</p>"),
    ("account", '<p><a href="https://github.com/bob">External link</a></p>'),
    ("temporal", "<p>Last updated: 2024</p>"),
])
def test_similar_unowned_or_implicit_fields_are_not_exposures(phase4_parse, phase4_card, phase4_subject, kind, field):
    document = phase4_parse(phase4_card(field))
    identity = verify_identity(phase4_subject, document)
    result = extraction.extract_exposures(document, identity)
    # The target's actual name/email may be extracted, never the extra field.
    assert not any(c.type == ExposureType(kind) and c.evidence.quote.strip() in {
        "Bob Lee", "bob@example.com", "example.com", "Website operated by Example University",
        "Bob Lee is also on this page", "Conference menu", "Robotics", "External link", "2024",
    } for c in result.candidates)
    if kind not in {"identity", "contact"}:
        assert values(result, ExposureType(kind)) == []


@pytest.mark.parametrize("kind,field", [
    ("identity", "<p>Name: Bob Lee</p>"),
    ("contact", "<p>Phone: 02-1234-5678</p>"),
    ("affiliation", "<p>Affiliation: Other University</p>"),
    ("relationship", "<p>Advisor: Carol Park</p>"),
    ("activity", "<p>Project: Bob's project</p>"),
    ("interest", "<p>Research Interests: Robotics</p>"),
    ("account", '<p>GitHub: <a href="https://github.com/bob">bob</a></p>'),
    ("temporal", "<p>Project period: 2020–2021</p>"),
])
def test_every_type_excludes_other_person_card(phase4_parse, phase4_card, phase4_subject, kind, field):
    other = '<div class="profile-card"><h2>Bob Lee</h2><p>bob@example.com</p>' + field + '</div>'
    document = phase4_parse(phase4_card() + other)
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extraction.extract_exposures(document, identity)
    assert [(c.type.value, c.value) for c in result.candidates] == [
        ("identity", "Alice Kim"), ("contact", "alice@example.com"),
    ]


@pytest.mark.parametrize("kind", list(ExposureType))
def test_absent_type_does_not_force_a_candidate(phase4_parse, phase4_subject, kind):
    if kind == ExposureType.IDENTITY:
        html = '<div><h2>Alice <b>Kim</b></h2><p>alice@example.com</p></div>'
    elif kind == ExposureType.CONTACT:
        html = '<div><h2>Alice Kim</h2><p>Example University</p></div>'
    else:
        html = '<div><h2>Alice Kim</h2><p>alice@example.com</p></div>'
    document = phase4_parse(html)
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    assert values(extraction.extract_exposures(document, identity), kind) == []


@pytest.mark.parametrize("status", [IdentityStatus.UNCERTAIN, IdentityStatus.REJECTED])
def test_nonconfirmed_even_with_target_ids_returns_empty(phase4_parse, phase4_card, phase4_subject, status):
    document = phase4_parse(phase4_card())
    identity = replace(verify_identity(phase4_subject, document), identity_status=status)
    assert extraction.extract_exposures(document, identity) == ExtractionResult()


def test_confirmed_empty_target_is_diagnostic_not_page_fallback(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card())
    identity = replace(verify_identity(phase4_subject, document), target_block_ids=())
    result = extraction.extract_exposures(document, identity)
    assert not result.candidates and result.diagnostics[0].code == "missing_target_blocks"


@pytest.mark.parametrize("root", [0, 999, -1])
def test_invalid_target_reference_is_explicit_error(phase4_parse, phase4_card, phase4_subject, root):
    document = phase4_parse(phase4_card())
    identity = replace(verify_identity(phase4_subject, document), target_block_ids=(root,))
    with pytest.raises(ValueError, match="target"):
        extraction.extract_exposures(document, identity)


@pytest.mark.parametrize("chrome", ["footer", "nav", "aside", 'div role="contentinfo"', 'span class="footer"'])
def test_chrome_outside_target_never_contributes(phase4_parse, phase4_card, phase4_subject, chrome):
    tag = chrome.split()[0]
    document = phase4_parse(phase4_card() + f'<{chrome}>Phone: 02-9999-9999</{tag}>')
    result = extraction.extract_exposures(document, verify_identity(phase4_subject, document))
    assert "02-9999-9999" not in values(result, ExposureType.CONTACT)


@pytest.mark.parametrize("other", [
    '<div class=card><p>Name: Bob Lee</p><p>bob@example.com</p></div>',
    '<table><tr><td>Bob Lee</td><td>bob@example.com</td></tr></table>',
    '<dl><dt>Name</dt><dd>Bob Lee</dd><dt>Email</dt><dd>bob@example.com</dd></dl>',
])
def test_forged_ancestor_scope_cannot_borrow_other_person_fields(phase4_parse, phase4_card, phase4_subject, other):
    document = phase4_parse('<section id=wrapper>' + phase4_card() + other + '</section>')
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    wrapper = next(b.block_id for b in document.blocks if dict(b.attributes).get("id") == "wrapper")
    result = extraction.extract_exposures(document, replace(identity, target_block_ids=(wrapper,)))
    assert not result.candidates and result.diagnostics


@pytest.mark.parametrize("name,email", [("Professor A", "a@example.com"), ("Professor B", "b@example.com"),
                                       ("Member C", "c@example.com"), ("Member D", "d@example.com")])
def test_phase2_people_fixture_through_identity_to_extraction(phase4_parse, name, email):
    html = (Path(__file__).parent / "fixtures/html/people.html").read_text(encoding="utf-8")
    document = phase4_parse(html)
    identity = verify_identity(Subject(name=name, email=email, organization="Example University"), document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extraction.extract_exposures(document, identity)
    assert values(result, ExposureType.IDENTITY) == [name]
    assert values(result, ExposureType.CONTACT) == [email]
    if name == "Professor A":
        assert values(result, ExposureType.INTEREST) == ["Artificial Intelligence"]


def test_single_definition_name_and_labeled_fields(phase4_parse, phase4_subject):
    document = phase4_parse('<dl><dt>Name</dt><dd>Alice Kim</dd><dt>Email</dt><dd>alice@example.com</dd>'
                            '<dt>Research Interests</dt><dd>Artificial Intelligence</dd>'
                            '<dt>Advisor</dt><dd>Bob Lee</dd></dl>')
    result = extraction.extract_exposures(document, verify_identity(phase4_subject, document))
    assert values(result, ExposureType.IDENTITY) == ["Alice Kim"]
    assert values(result, ExposureType.CONTACT) == ["alice@example.com"]
    assert values(result, ExposureType.INTEREST) == ["Artificial Intelligence"]
    relation = next(c for c in result.candidates if c.type == ExposureType.RELATIONSHIP)
    assert relation.value == "Bob Lee" and relation.relation == "advisor"
    assert any(ref.quote == "Advisor" for ref in relation.attribution)


@pytest.mark.parametrize("names", ["<dd>Alice Kim</dd><dd>Bob Lee</dd>", "<dd>Alice Kim</dd><dd>Alice Kim</dd>"])
def test_multiple_definition_names_do_not_get_combined(phase4_parse, phase4_subject, names):
    document = phase4_parse('<dl><dt>Name</dt>' + names + '<dt>Email</dt><dd>alice@example.com</dd></dl>')
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.UNCERTAIN
    assert not extraction.extract_exposures(document, identity).candidates


@pytest.mark.parametrize("html", ["", "<title>Alice Kim alice@example.com</title>",
                                  '<meta name=description content="Alice Kim alice@example.com">',
                                  '<p>Unrelated body</p>'])
def test_empty_title_metadata_or_no_exposures(phase4_parse, phase4_subject, html):
    document = phase4_parse(html)
    assert not extraction.extract_exposures(document, verify_identity(phase4_subject, document)).candidates


def test_subject_only_values_and_url_never_supply_evidence(phase4_parse, phase4_subject):
    document = phase4_parse('<div><h2>Alice Kim</h2><p>Example University</p></div>')
    document = replace(document, final_url="https://example.com/alice@example.com/github/bob")
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extraction.extract_exposures(document, identity)
    assert values(result, ExposureType.CONTACT) == []
    assert values(result, ExposureType.ACCOUNT) == []


def test_repeated_candidates_preserved_no_early_deduplication(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>Research Interests: AI</p><p>Research Interests: AI</p>'))
    result = extraction.extract_exposures(document, verify_identity(phase4_subject, document))
    interests = [c for c in result.candidates if c.type == ExposureType.INTEREST]
    assert len(interests) == 2 and interests[0].evidence.start != interests[1].evidence.start


def test_multiple_roots_repeated_values_remain_distinct(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card() + phase4_card())
    identity = verify_identity(phase4_subject, document)
    result = extraction.extract_exposures(document, identity)
    assert len(identity.target_block_ids) == 2
    assert values(result, ExposureType.CONTACT) == ["alice@example.com", "alice@example.com"]


def test_input_immutability_reproducibility_frozen_results(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card())
    identity = verify_identity(phase4_subject, document)
    before = asdict(document), asdict(identity), phase4_subject.model_dump()
    result = extraction.extract_exposures(document, identity)
    assert result == extraction.extract_exposures(document, identity)
    assert before == (asdict(document), asdict(identity), phase4_subject.model_dump())
    with pytest.raises(FrozenInstanceError):
        result.candidates = ()


def test_unexpected_implementation_error_is_not_hidden(phase4_parse, phase4_card, phase4_subject, monkeypatch):
    document = phase4_parse(phase4_card())
    identity = verify_identity(phase4_subject, document)

    def broken(*args, **kwargs):
        raise RuntimeError("implementation bug")
    monkeypatch.setattr(extraction, "validate_candidate", broken)
    with pytest.raises(RuntimeError, match="implementation bug"):
        extraction.extract_exposures(document, identity)


def test_confirmed_document_with_no_public_ready_values(phase4_parse, phase4_subject):
    document = phase4_parse('<div><h2>Alice <b>Kim</b></h2><p>Example <b>University</b></p></div>')
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extraction.extract_exposures(document, identity)
    assert not result.candidates
    assert all(d.code == "value_not_in_contiguous_evidence" for d in result.diagnostics)


@pytest.mark.parametrize("tag", ["html", "body", "main"])
def test_page_scope_cannot_be_used_even_with_valid_name_ref(phase4_parse, phase4_card, phase4_subject, tag):
    document = phase4_parse(f'<{tag}>' + phase4_card() + f'</{tag}>')
    identity = verify_identity(phase4_subject, document)
    root = next(b.block_id for b in document.blocks if b.tag == tag)
    with pytest.raises(ValueError, match="target"):
        extraction.extract_exposures(document, replace(identity, target_block_ids=(root,)))


@pytest.mark.parametrize("roots", ["duplicate", "overlap"])
def test_duplicate_or_overlapping_scope_roots_are_malformed(phase4_parse, phase4_card, phase4_subject, roots):
    document = phase4_parse('<section>' + phase4_card() + '</section>')
    identity = verify_identity(phase4_subject, document)
    root = identity.target_block_ids[0]
    other = root if roots == "duplicate" else next(b.block_id for b in document.blocks if b.tag == "section")
    with pytest.raises(ValueError):
        extraction.extract_exposures(document, replace(identity, target_block_ids=(root, other)))


def test_multi_type_results_in_one_person_profile(phase4_parse, phase4_card, phase4_subject):
    fields = ('<p>Phone: 02-1234-5678</p><p>Lab: AI Lab</p><p>Advisor: Bob Lee</p>'
              '<p>Activity: Presented DFSA</p><p>Research Areas: Security</p>'
              '<p>GitHub: <a class=account href="https://github.com/alice">@alice</a></p>'
              '<p>Project period: 2024–present</p>')
    document = phase4_parse(phase4_card(fields))
    identity = verify_identity(phase4_subject, document)
    assert identity.identity_status == IdentityStatus.CONFIRMED
    result = extraction.extract_exposures(document, identity)
    assert {c.type for c in result.candidates} == set(ExposureType)
    assert not result.diagnostics


def test_noncontiguous_block_ids_are_preserved(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>Research Interests: AI</p>'))
    mapping = {b.block_id: 100 + b.block_id * 3 for b in document.blocks}
    shifted = replace(document,
                      blocks=tuple(replace(b, block_id=mapping[b.block_id], parent_id=mapping.get(b.parent_id))
                                   for b in document.blocks),
                      texts=tuple(replace(t, block_id=mapping[t.block_id]) for t in document.texts))
    original = extraction.extract_exposures(document, verify_identity(phase4_subject, document))
    result = extraction.extract_exposures(shifted, verify_identity(phase4_subject, shifted))
    assert [(c.type, c.value) for c in result.candidates] == [(c.type, c.value) for c in original.candidates]
    for before, after in zip(original.candidates, result.candidates):
        assert after.target_block_id == mapping[before.target_block_id]
        assert after.evidence.block_id == mapping[before.evidence.block_id]
