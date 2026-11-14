"""Phase 3 attribution regressions; all HTML is parsed by the Phase 2 parser."""

from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest

from dfsa.contracts.common import IdentityStatus, Subject
from dfsa.modules.profiling._types import FetchedHTML, IdentityDecision, ParsedDocument
from dfsa.modules.profiling.identity import verify_identity
from dfsa.modules.profiling.parsing import parse_html


@pytest.fixture
def subject():
    return Subject(name="Alice Kim", organization="Example University", email="alice@example.com")


def parse(html):
    result = parse_html(FetchedHTML(
        "src_identity", "https://example.com/old", "https://example.com/profile",
        html.encode("utf-8"), "text/html", None, 200,
    ))
    assert isinstance(result, ParsedDocument)
    return result


def card(name="Alice Kim", fields="<p>Email: alice@example.com</p>", marker="profile-card"):
    return f'<div class="{marker}"><h2>{name}</h2>{fields}</div>'


def block_id(document, *, tag=None, cls=None, element_id=None):
    return next(b.block_id for b in document.blocks
                if (tag is None or b.tag == tag)
                and (cls is None or dict(b.attributes).get("class") == cls)
                and (element_id is None or dict(b.attributes).get("id") == element_id))


def target_text(document, decision):
    selected = set(decision.target_block_ids)
    for block in document.blocks:
        if block.parent_id in selected:
            selected.add(block.block_id)
    return " ".join(text.raw_text for text in document.texts if text.block_id in selected)


def assert_refs(document, result):
    assert isinstance(result, IdentityDecision)
    assert isinstance(result.identity_status, IdentityStatus)
    assert result.source_id == document.source_id
    assert result.reasons
    ids = {b.block_id for b in document.blocks}
    assert set(result.target_block_ids) <= ids
    assert 0 not in result.target_block_ids
    for evidence in result.evidence:
        assert evidence.block_id in ids
        assert evidence.text_indices
        for index in evidence.text_indices:
            assert 0 <= index < len(document.texts)
    if result.identity_status != IdentityStatus.CONFIRMED:
        assert result.target_block_ids == ()


@pytest.mark.parametrize("fields,reason", [
    ("<p>Email: alice@example.com</p>", "linked_name_email"),
    ("<p>alice@example.com</p>", "linked_name_email"),
    ('<p><a href="mailto:alice@example.com">alice@example.com</a></p>', "linked_name_email"),
    ("<p>Example University</p>", "linked_name_university"),
    ("<p>Affiliation: Example University</p>", "linked_name_university"),
    ("<p>Organization: Example University</p>", "linked_name_university"),
])
def test_same_card_independent_fields(subject, fields, reason):
    document = parse(card(fields=fields))
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.CONFIRMED
    assert result.reasons == (reason,)
    assert result.target_block_ids == (block_id(document, cls="profile-card"),)
    assert {e.kind for e in result.evidence} == {
        "name_match", "email_exact_match" if "email" in reason else "organization_match",
    }
    assert_refs(document, result)


@pytest.mark.parametrize("html,tag", [
    ('<div><h2>Alice Kim</h2><p>Email: alice@example.com</p></div>', "div"),
    ('<section><h1>Alice Kim</h1><p>Example University</p></section>', "section"),
    ('<article><header><h2>Alice Kim</h2></header><p>alice@example.com</p></article>', "article"),
    ('<ul><li>Alice Kim<p>alice@example.com</p></li></ul>', "li"),
    ('<table><tr><td>Alice Kim</td><td>alice@example.com</td></tr></table>', "tr"),
    ('<div><p>Name: Alice Kim</p><p>Email: alice@example.com</p></div>', "div"),
    ('<div itemscope itemtype="https://schema.org/Person"><span itemprop="name">Alice Kim</span>'
     '<p>alice@example.com</p></div>', "div"),
    ('<span class="profile-card">Alice Kim<p>alice@example.com</p></span>', "span"),
])
def test_supported_containment_layouts(subject, html, tag):
    document = parse(html)
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.CONFIRMED
    assert result.target_block_ids == (block_id(document, tag=tag),)
    assert_refs(document, result)


@pytest.mark.parametrize("html", [
    "", " \n ", "<html><body></body></html>",
    "<head><title>Alice Kim alice@example.com Example University</title></head>",
    '<meta name="description" content="Alice Kim alice@example.com Example University">',
    "<p>Alice Kim</p>", "<h2>Alice Kim</h2>", card(fields=""),
    card(fields="<p>Research: AI</p>"), "<p>Unrelated page</p>",
    card("Bob Lee", ""), card("Bob Lee", "<p>Example University</p>"),
    card("Bob Lee", "<p>alice@example.com</p>"),
    card(fields='<a href="mailto:alice@example.com">Email</a>'),
    card(fields="<p>Contact someone at example.com</p>"),
    '<div class="profile-card"><h2>Alice Kim</h2><p>Works with Bob at Example University</p></div>',
    card(fields="<p>Company: Example Corp</p>"),
    '<p>Alice Kim works at Example University; email alice@example.com</p>',
])
def test_insufficient_body_evidence_never_confirms_or_rejects(subject, html):
    document = parse(html)
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert_refs(document, result)


@pytest.mark.parametrize("html", [
    '<h2>Alice Kim</h2><p>Example University</p>',
    '<main><h2>Alice Kim</h2><p>alice@example.com</p></main>',
    card(fields="") + '<footer><p>alice@example.com</p></footer>',
    '<div>' + card(fields="") + '<footer>alice@example.com</footer></div>',
    '<section>' + card(fields="") + '<div>Example University</div></section>',
    '<section><div><h2>Alice Kim</h2></div><div>Example University</div></section>',
    '<div><h2>Alice Kim</h2><div>alice@example.com</div></div>',
    card(fields="<footer>Email: alice@example.com</footer>"),
    '<div><h2>Alice Kim</h2><h2>Bob Lee</h2><p>alice@example.com</p></div>',
    '<div class="profile-card"><h2>Alice Kim</h2>' + card("Bob Lee") + '</div>',
    '<nav>' + card() + '</nav>', '<footer>' + card() + '</footer>',
    '<aside>' + card() + '</aside>',
])
def test_unrelated_or_ambiguous_regions_remain_uncertain(subject, html):
    document = parse(html)
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert_refs(document, result)


@pytest.mark.parametrize("fields", [
    '<p>Email: other-alice@example.com</p>',
    '<p>Email: alice@example.com.evil</p>',
    '<p>Email: xalice@example.com</p>',
    '<p>Email: alice+tag@example.com</p>',
    '<p>Email: alice@other.example.com</p>',
    '<p>Email: alice@example.com.invalid</p>',
    '<p>Email: alice@example.com / bob@example.com</p>',
    '<p>Ask Bob: alice@example.com</p>',
    '<p>Email: alice@example.com?subject=hello</p>',
    '<p>Email: alice@example.com</p><p>Email: bob@example.com</p>',
])
def test_email_must_be_a_complete_local_field(subject, fields):
    document = parse(card(fields=fields))
    assert verify_identity(subject, document).identity_status == IdentityStatus.UNCERTAIN


@pytest.mark.parametrize("suffix", ["", "<p>Affiliation: Example University</p>"])
def test_another_person_email_cannot_be_used_for_target(subject, suffix):
    document = parse('<section>' + card(fields="")
                     + card("Bob Lee", "<p>Email: alice@example.com</p>" + suffix)
                     + '</section>')
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert {e.kind for e in result.evidence} == {"name_match"}
    assert_refs(document, result)


@pytest.mark.parametrize("other_first", [True, False])
def test_selects_target_card_and_excludes_other_person(subject, other_first):
    target = '<div class="profile-card" id="target"><h2>Alice Kim</h2><p>alice@example.com</p></div>'
    other = '<div class="profile-card" id="other"><h2>Bob Lee</h2><p>bob@example.com</p></div>'
    document = parse('<section>' + (other + target if other_first else target + other) + '</section>')
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.CONFIRMED
    assert result.target_block_ids == (block_id(document, element_id="target"),)
    assert "Bob Lee" not in target_text(document, result)
    assert "bob@example.com" not in target_text(document, result)
    assert_refs(document, result)


@pytest.mark.parametrize("fields", ["", "<p>Example University</p>"])
def test_indistinguishable_namesakes_remain_uncertain(subject, fields):
    document = parse('<section>' + card(fields=fields) + card(fields=fields) + '</section>')
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.reasons == ("ambiguous_namesakes",)
    assert_refs(document, result)


def test_exact_email_disambiguates_namesakes_without_widening_scope(subject):
    document = parse('<section>' + card(fields="<p>Example University</p><p>other@example.com</p>")
                     + '<div class="profile-card" id="target"><h2>Alice Kim</h2>'
                     '<p>alice@example.com</p></div></section>')
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.CONFIRMED
    assert result.target_block_ids == (block_id(document, element_id="target"),)
    assert "other@example.com" not in target_text(document, result)


def test_multiple_independently_confirmed_regions_are_returned(subject):
    document = parse('<section>' + card() + card() + '</section>')
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.CONFIRMED
    expected = tuple(b.block_id for b in document.blocks if dict(b.attributes).get("class") == "profile-card")
    assert result.target_block_ids == expected
    assert len(result.target_block_ids) == 2
    assert_refs(document, result)


@pytest.mark.parametrize("fields", [
    '<p>Affiliation: Another University</p>',
    '<p>Email: other@example.com</p>',
    '<p>Example University</p><p>Email: other@example.com</p>',
    '<p>Another University</p><p>Email: alice@example.com</p>',
])
def test_conflicts_in_target_region_do_not_force_confirmation_or_rejection(subject, fields):
    document = parse(card(fields=fields))
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert_refs(document, result)


@pytest.mark.parametrize("name_html,expected", [
    ("<h2>Bob Lee</h2>", IdentityStatus.UNCERTAIN),
    ("<p>Name: Bob Lee</p>", IdentityStatus.REJECTED),
    ('<span itemprop="name">Bob Lee</span>', IdentityStatus.REJECTED),
])
def test_single_explicit_other_profile_requires_labeled_name(subject, name_html, expected):
    document = parse('<div class="profile-card">' + name_html
                     + '<p>Email: bob@example.com</p><p>Another University</p></div>')
    result = verify_identity(subject, document)
    assert result.identity_status == expected
    if expected == IdentityStatus.REJECTED:
        assert result.reasons == ("explicit_other_profile",)
        assert {e.kind for e in result.evidence} == {"name_conflict", "email_conflict"}
    assert_refs(document, result)


@pytest.mark.parametrize("html", [
    card("Bob Lee", '<p>Email: bob@example.com</p>') + card("Carol Park", '<p>Email: carol@example.com</p>'),
    '<section><h2>Bob Lee</h2><p>Email: bob@example.com</p></section>',
    card("Bob Lee", '<p>bob@example.com</p>'),
    card("Bob Lee", '<p>Email: bob@example.com</p><p>Email: carol@example.com</p>'),
    card("Bob Lee", '<p>Email: bob@example.com</p>') + '<p>alice@example.com</p>',
    card("Bob Lee", '<p>Email: bob@example.com</p>') + '<h2>Alice Kim</h2>',
])
def test_other_candidates_or_insufficient_conflicts_do_not_reject_page(subject, html):
    document = parse(html)
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert_refs(document, result)


@pytest.mark.parametrize("name", ["A. Kim", "앨리스 김", "Kim Alice", "Alice", "Alice Kim Jr"])
def test_no_alias_transliteration_reordering_or_partial_name_matching(subject, name):
    document = parse(card(name, '<p>alice@example.com</p>'))
    assert verify_identity(subject, document).identity_status == IdentityStatus.UNCERTAIN


def test_entities_inline_runs_case_and_whitespace_preserve_references():
    subject = Subject(name="Anne & Kim", organization="예시대학교", email="anne@example.com")
    document = parse('<div class="profile-card"><h2> ANNE <b>&amp;</b>\n Kim </h2>'
                     '<p> Email: ANNE@example.com </p><p>소속: 예시대학교</p></div>')
    before = asdict(document)
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.CONFIRMED
    name_ref = next(e for e in result.evidence if e.kind == "name_match")
    assert len(name_ref.text_indices) >= 3
    assert "&" in "".join(document.texts[i].raw_text for i in name_ref.text_indices)
    assert "&amp;" in document.html_text
    assert asdict(document) == before
    assert_refs(document, result)


@pytest.mark.parametrize("field", ["예시대학교", "소속: 예시대학교", "대학교: 예시대학교"])
def test_exact_korean_university_affiliation(field):
    subject = Subject(name="홍길동", organization="예시대학교", email="hong@example.com")
    document = parse(card("홍길동", f"<p>{field}</p>"))
    assert verify_identity(subject, document).identity_status == IdentityStatus.CONFIRMED


@pytest.mark.parametrize("field", ["Other Example University", "Example University Hospital",
                                   "Example Univ.", "example.com", "Example Corp"])
def test_organization_substrings_aliases_and_domains_are_not_matches(subject, field):
    document = parse(card(fields=f"<p>{field}</p>"))
    assert verify_identity(subject, document).identity_status == IdentityStatus.UNCERTAIN


def test_non_university_organization_is_not_p0_corroboration(subject):
    subject = subject.model_copy(update={"organization": "Example Corp"})
    document = parse(card(fields="<p>Organization: Example Corp</p>"))
    assert verify_identity(subject, document).identity_status == IdentityStatus.UNCERTAIN


def test_subject_only_information_cannot_become_document_evidence(subject):
    document = parse(card(fields=""))
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert {e.kind for e in result.evidence} == {"name_match"}
    assert all("alice@example.com" not in document.texts[i].raw_text
               for e in result.evidence for i in e.text_indices)


def test_title_url_and_metadata_do_not_supply_missing_body_confirmation(subject):
    document = parse('<title>Alice Kim alice@example.com Example University</title>'
                     '<meta name="description" content="alice@example.com">' + card(fields=""))
    document = replace(document, original_url="https://example.com/alice@example.com",
                       final_url="https://example.com/Alice-Kim/Example-University")
    assert verify_identity(subject, document).identity_status == IdentityStatus.UNCERTAIN


@pytest.mark.parametrize("name,email,expected", [
    ("Professor A", "a@example.com", IdentityStatus.CONFIRMED),
    ("Professor B", "b@example.com", IdentityStatus.CONFIRMED),
    ("Professor A", "b@example.com", IdentityStatus.UNCERTAIN),
    ("Member C", "c@example.com", IdentityStatus.CONFIRMED),
    ("Member C", "d@example.com", IdentityStatus.UNCERTAIN),
    ("Student A", "a@example.com", IdentityStatus.UNCERTAIN),
])
def test_phase2_people_fixture_preserves_person_scope(name, email, expected):
    html = (Path(__file__).parent / "fixtures/html/people.html").read_text(encoding="utf-8")
    document = parse(html)
    subject = Subject(name=name, organization="Example University", email=email)
    result = verify_identity(subject, document)
    assert result.identity_status == expected
    assert_refs(document, result)
    if expected == IdentityStatus.CONFIRMED:
        selected = target_text(document, result)
        assert name in selected and email in selected
        for other in ("a@example.com", "b@example.com", "c@example.com", "d@example.com"):
            if other != email:
                assert other not in selected


def test_input_immutability_determinism_and_frozen_result(subject):
    document = parse(card())
    before = subject.model_dump(), asdict(document)
    result = verify_identity(subject, document)
    assert result == verify_identity(subject, document)
    assert before == (subject.model_dump(), asdict(document))
    with pytest.raises(FrozenInstanceError):
        result.target_block_ids = ()


@pytest.mark.parametrize("name", ["", " \n "])
def test_empty_subject_name_never_confirms(subject, name):
    document = parse(card())
    result = verify_identity(subject.model_copy(update={"name": name}), document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.reasons == ("missing_subject_name",)


def test_empty_internal_document(subject):
    document = replace(parse(""), blocks=(), texts=())
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.reasons == ("no_body_text",)


@pytest.mark.parametrize("name,organization,html", [
    ("alice@example.com", "Example University",
     card("alice@example.com", "")),
    ("alice@example.com", "Example University",
     card("alice@example.com", "<p>alice@example.com</p>")),
    ("Example University", "Example University",
     card("Example University", "")),
    ("Example University", "Example University",
     card("Example University", "<p>Example University</p>")),
])
def test_a_single_value_cannot_supply_two_independent_identifiers(subject, name, organization, html):
    subject = subject.model_copy(update={"name": name, "organization": organization})
    result = verify_identity(subject, parse(html))
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()


@pytest.mark.parametrize("wrapper", ["<div>{}</div>", "<section>{}</section>",
                                     '<div class="profile-card">{}</div>'])
def test_does_not_return_wrapper_containing_another_person_region(subject, wrapper):
    html = '<h2>Alice Kim</h2><p>alice@example.com</p>' + card("Bob Lee", "<p>bob@example.com</p>")
    result = verify_identity(subject, parse(wrapper.format(html)))
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()


def test_namesakes_with_just_one_university_match_are_still_ambiguous(subject):
    document = parse('<section>' + card(fields="<p>Example University</p>")
                     + card(fields="<p>Another University</p>") + '</section>')
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.reasons == ("ambiguous_namesakes",)


def test_references_keep_original_noncontiguous_block_ids(subject):
    document = parse(card())
    mapping = {block.block_id: block.block_id + 100 for block in document.blocks}
    shifted = replace(document,
                      blocks=tuple(replace(block, block_id=mapping[block.block_id],
                                           parent_id=mapping.get(block.parent_id))
                                   for block in document.blocks),
                      texts=tuple(replace(text, block_id=mapping[text.block_id]) for text in document.texts))
    original = verify_identity(subject, document)
    result = verify_identity(subject, shifted)
    assert result.identity_status == IdentityStatus.CONFIRMED
    assert result.target_block_ids == tuple(mapping[bid] for bid in original.target_block_ids)
    assert result.evidence == tuple(replace(evidence, block_id=mapping[evidence.block_id])
                                    for evidence in original.evidence)


def test_unexpected_implementation_errors_propagate(subject, monkeypatch):
    from dfsa.modules.profiling import identity

    def broken(document):
        raise RuntimeError("implementation bug")

    monkeypatch.setattr(identity, "_Document", broken)
    with pytest.raises(RuntimeError, match="implementation bug"):
        verify_identity(subject, parse(card()))


@pytest.mark.parametrize("tag", ["html", "body", "main"])
def test_page_level_card_marker_never_authorizes_whole_document(subject, tag):
    document = parse(f'<{tag} class="profile-card"><h2>Alice Kim</h2>'
                     f'<p>alice@example.com</p></{tag}>')
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()


@pytest.mark.parametrize("marker", ['role="contentinfo"', 'role="navigation"',
                                   'class="footer"', 'id="site-footer"'])
def test_shared_inline_landmark_email_cannot_confirm_person(subject, marker):
    document = parse(card(fields=f'<span {marker}>alice@example.com</span>'))
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()


@pytest.mark.parametrize("name_field", ["<dt>Name</dt><dd>Bob Lee</dd>",
                                       "<dt>이름:</dt><dd>Bob Lee</dd>",
                                       "<dt>Name</dt>"])
def test_review_definition_list_cannot_donate_another_person_email(subject, name_field):
    document = parse(card(fields=f'<dl>{name_field}<dt>Email</dt><dd>alice@example.com</dd></dl>'))
    before = asdict(document), subject.model_dump()
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()
    assert result == verify_identity(subject, document)
    assert before == (asdict(document), subject.model_dump())


@pytest.mark.parametrize("heading", ["Contact Information", "Research Interests", "Education",
                                      "Publications", "연락처", "Unknown Section"])
def test_review_general_heading_is_not_a_conflicting_person_name(subject, heading):
    result = verify_identity(subject, parse(card(heading, '<p>Email: alice@personal.example.com</p>')))
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()


@pytest.mark.parametrize("other", [
    '<ul><li>Carol Park<p>Email: carol@example.com</p></li></ul>',
    '<table><tr><td>Carol Park</td><td>carol@example.com</td></tr></table>',
    '<dl><dt>Name</dt><dd>Carol Park</dd><dt>Email</dt><dd>carol@example.com</dd></dl>',
    '<p>Additional person information</p>',
])
def test_review_other_visible_candidate_prevents_page_rejection(subject, other):
    result = verify_identity(subject, parse(card('Bob Lee', '<p>Email: bob@example.com</p>') + other))
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()


def test_definition_list_selects_its_own_person_region(subject):
    document = parse('<section><dl id="target"><dt>Name</dt><dd>Alice Kim</dd>'
                     '<dt>Email</dt><dd>alice@example.com</dd></dl>'
                     '<dl><dt>Name</dt><dd>Bob Lee</dd><dt>Email</dt><dd>bob@example.com</dd></dl></section>')
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.CONFIRMED
    assert result.target_block_ids == (block_id(document, element_id="target"),)
    assert 'Bob Lee' not in target_text(document, result)
    assert_refs(document, result)


def test_definition_list_same_names_cannot_share_email(subject):
    document = parse('<dl><dt>Name</dt><dd>Alice Kim</dd><dt>Name</dt><dd>Alice Kim</dd>'
                     '<dt>Email</dt><dd>alice@example.com</dd></dl>')
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()


def test_ordinary_contact_definition_list_preserves_confirmed_card(subject):
    document = parse(card(fields='<dl><dt>Email</dt><dd>alice@example.com</dd></dl>'))
    assert verify_identity(subject, document).identity_status == IdentityStatus.CONFIRMED


@pytest.mark.parametrize("heading,local", [("Contact Information", "contact"),
                                          ("Research Interests", "research"),
                                          ("Education", "education")])
def test_generic_heading_email_token_is_not_name_evidence(subject, heading, local):
    result = verify_identity(subject, parse(card(heading, f'<p>Email: {local}@example.com</p>')))
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()


@pytest.mark.parametrize("names", [
    ["Alice Kim", "Bob Lee"], ["Bob Lee", "Alice Kim"],
    ["Alice Kim", "Bob Lee", "Carol Park"], ["Alice Kim", "Alice Kim"],
])
def test_all_name_descriptions_remain_ambiguous(subject, names):
    descriptions = ''.join(f'<dd>{name}</dd>' for name in names)
    document = parse(f'<dl><dt>Name</dt>{descriptions}<dt>Email</dt><dd>alice@example.com</dd></dl>')
    before = asdict(document), subject.model_dump()
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()
    assert result == verify_identity(subject, document)
    assert before == (asdict(document), subject.model_dump())


@pytest.mark.parametrize("heading,local", [
    ("Contact Details", "contact"), ("Contact Information", "contact"),
    ("Research Activities", "research"), ("Admissions Office", "admissions"),
    ("Bob Lee", "bob"),
])
def test_heading_email_words_never_establish_other_person(subject, heading, local):
    result = verify_identity(subject, parse(card(heading, f'<p>Email: {local}@example.com</p>')))
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()


def test_name_free_contact_block_is_uncertain(subject):
    result = verify_identity(subject, parse('<div class=profile-card><p>Email: contact@example.com</p></div>'))
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()


def test_single_definition_name_retains_exact_confirmed_scope(subject):
    document = parse('<dl><dt>Name</dt><dd>Alice Kim</dd><dt>Email</dt><dd>alice@example.com</dd></dl>')
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.CONFIRMED
    assert result.target_block_ids == (block_id(document, tag='dl'),)
    assert_refs(document, result)


def test_nested_uninterpreted_name_description_never_confirms(subject):
    document = parse('<dl><dt>Name</dt><dd>Alice Kim</dd><dd><p>Bob Lee</p></dd>'
                     '<dt>Email</dt><dd>alice@example.com</dd></dl>')
    result = verify_identity(subject, document)
    assert result.identity_status == IdentityStatus.UNCERTAIN
    assert result.target_block_ids == ()
