"""Phase 5 false-merge, provenance, determinism and real Phase 4 regressions."""

from copy import deepcopy
from dataclasses import asdict, replace
from html import unescape
from itertools import permutations
import re

import pytest
from pydantic import ValidationError

from dfsa.contracts.common import ExposureType, IdentityStatus, Subject
from dfsa.contracts.profiling import Exposure, ExposureSource
from dfsa.modules.profiling._types import (
    EvidenceReference, ExposureCandidate, ValidatedExposureCandidate,
)
from dfsa.modules.profiling.deduplication import deduplicate_exposures
from dfsa.modules.profiling.extraction import extract_exposures
from dfsa.modules.profiling.identity import verify_identity


def candidate(value="alice@example.com", *, kind=ExposureType.CONTACT,
              source="src_001", quote=None, relation=None):
    """Synthetic boundary fixture; real Phase 4 validation is tested below."""
    text = value if quote is None else quote
    return ValidatedExposureCandidate(
        source_id=source, target_block_id=1, type=kind, value=value,
        evidence=EvidenceReference(2, (0,), 10, 10 + len(text), text),
        relation=relation,
        attribution=(EvidenceReference(3, (1,), 100, 109, "Alice Kim"),),
    )


def public_pairs(exposure):
    return [(source.source_id, source.evidence) for source in exposure.sources]


@pytest.mark.parametrize("size", [0, 1, 2, 10])
def test_empty_single_and_repeated_candidates(size):
    result = deduplicate_exposures([candidate()] * size)
    if not size:
        assert result == []
        return
    assert len(result) == 1
    assert result[0].model_dump() == {
        "exposure_id": "exp_001", "type": ExposureType.CONTACT,
        "value": "alice@example.com", "relation": None,
        "sources": [{"source_id": "src_001", "evidence": "alice@example.com"}],
    }


def test_multi_source_and_same_source_different_quotes_remain_exact():
    inputs = [
        candidate(source="src_b", quote="Contact: alice@example.com"),
        candidate(source="src_a", quote="  Email: alice@example.com\n"),
        candidate(source="src_a", quote="alice@example.com"),
        candidate(source="src_c", quote="alice@example.com"),
        candidate(source="src_a", quote="alice@example.com"),
    ]
    result = deduplicate_exposures(inputs)
    assert len(result) == 1
    assert public_pairs(result[0]) == [
        ("src_a", "  Email: alice@example.com\n"),
        ("src_a", "alice@example.com"),
        ("src_b", "Contact: alice@example.com"),
        ("src_c", "alice@example.com"),
    ]
    assert {s.evidence for s in result[0].sources} <= {c.evidence.quote for c in inputs}


def test_only_exact_public_source_pairs_are_removed_not_original_refs():
    first = candidate()
    second = replace(first, target_block_id=8,
                     evidence=replace(first.evidence, block_id=9, text_indices=(6,), start=200, end=217))
    inputs = [first, second]
    before = deepcopy(inputs)
    assert len(deduplicate_exposures(inputs)[0].sources) == 1
    assert inputs == before and first.evidence != second.evidence
    assert all(c.attribution for c in inputs)


@pytest.mark.parametrize("kind", list(ExposureType))
def test_identical_values_merge_within_each_taxonomy_type(kind):
    inputs = [candidate("shared", kind=kind, source=f"src_{i}") for i in range(3)]
    result = deduplicate_exposures(inputs)
    assert len(result) == 1 and result[0].type == kind
    assert len(result[0].sources) == 3


def test_same_value_never_merges_different_types():
    result = deduplicate_exposures([candidate("shared", kind=k) for k in ExposureType])
    assert len(result) == 8
    assert {e.type for e in result} == set(ExposureType)
    assert len({e.exposure_id for e in result}) == 8


@pytest.mark.parametrize("kind", list(ExposureType))
def test_relation_is_part_of_every_key(kind):
    result = deduplicate_exposures([
        candidate("Bob Lee", kind=kind, relation=relation)
        for relation in (None, "advisor", "collaborator", "Advisor")
    ])
    assert len(result) == 4
    assert {e.relation for e in result} == {None, "advisor", "collaborator", "Advisor"}


@pytest.mark.parametrize("kind", [k for k in ExposureType
                                 if k not in {ExposureType.CONTACT, ExposureType.ACCOUNT}])
def test_text_whitespace_only_keys_keep_first_display_and_exact_quotes(kind):
    inputs = [candidate(" Alice\n  Kim ", kind=kind), candidate("Alice Kim", kind=kind)]
    forward = deduplicate_exposures(inputs)
    backward = deduplicate_exposures(reversed(inputs))
    assert len(forward) == len(backward) == 1
    assert forward[0].value == inputs[0].value
    assert backward[0].value == inputs[1].value
    assert forward[0].exposure_id == backward[0].exposure_id
    assert forward[0].sources == backward[0].sources


def test_relation_whitespace_keeps_first_representation():
    result = deduplicate_exposures([
        candidate("Bob Lee", kind=ExposureType.RELATIONSHIP, relation="  co  advisor "),
        candidate("Bob Lee", kind=ExposureType.RELATIONSHIP, relation="co advisor"),
    ])
    assert len(result) == 1 and result[0].relation == "  co  advisor "


@pytest.mark.parametrize("kind", [ExposureType.CONTACT, ExposureType.ACCOUNT])
def test_identifiers_only_trim_edges_for_comparison(kind):
    result = deduplicate_exposures([
        candidate(" alice@example.com ", kind=kind), candidate("alice@example.com", kind=kind),
    ])
    assert len(result) == 1 and result[0].value == " alice@example.com "
    assert len(deduplicate_exposures([
        candidate("a  b", kind=kind), candidate("a b", kind=kind),
    ])) == 2


@pytest.mark.parametrize("kind,left,right", [
    (ExposureType.CONTACT, "alice@example.com", "bob@example.com"),
    (ExposureType.CONTACT, "alice@example.com", "alice+tag@example.com"),
    (ExposureType.CONTACT, "alice@gmail.com", "a.lice@gmail.com"),
    (ExposureType.CONTACT, "Alice@example.com", "alice@example.com"),
    (ExposureType.CONTACT, "alice@example.com", "alice@EXAMPLE.COM"),
    (ExposureType.CONTACT, "02-1234-5678", "02-1234-5679"),
    (ExposureType.CONTACT, "+82 10-1234-5678", "010-1234-5678"),
    (ExposureType.IDENTITY, "Alice Kim", "A. Kim"),
    (ExposureType.IDENTITY, "Alice Kim", "alice kim"),
    (ExposureType.IDENTITY, "Alice Kim", "Kim Alice"),
    (ExposureType.IDENTITY, "홍길동", "Hong Gildong"),
    (ExposureType.AFFILIATION, "Example University", "Example Univ."),
    (ExposureType.AFFILIATION, "AI Lab", "AI Laboratory"),
    (ExposureType.AFFILIATION, "AI Lab", "AI Labs"),
    (ExposureType.ACTIVITY, "DFSA", "DFSA v2"),
    (ExposureType.ACTIVITY, "DFSA", "dfsa"),
    (ExposureType.INTEREST, "Artificial Intelligence", "Machine Learning"),
    (ExposureType.INTEREST, "AI", "Artificial Intelligence"),
    (ExposureType.ACCOUNT, "alice", "alice-2"),
    (ExposureType.ACCOUNT, "alice", "@alice"),
    (ExposureType.ACCOUNT, "alice", "https://github.com/alice"),
    (ExposureType.ACCOUNT, "https://github.com/alice", "https://github.com/bob"),
    (ExposureType.ACCOUNT, "Alice", "alice"),
    (ExposureType.TEMPORAL, "2022–2024", "2022–2025"),
    (ExposureType.TEMPORAL, "2024", "2024-01"),
    (ExposureType.TEMPORAL, "2022–present", "2022–현재"),
    (ExposureType.TEMPORAL, "2022–2024", "2022-2024"),
])
def test_similar_but_unproven_equivalences_stay_separate(kind, left, right):
    result = deduplicate_exposures([candidate(left, kind=kind), candidate(right, kind=kind)])
    assert len(result) == 2
    assert {e.value for e in result} == {left, right}
    assert len({e.exposure_id for e in result}) == 2


def test_permutations_preserve_ids_output_and_source_order_for_same_spelling():
    inputs = [candidate("z@example.com", source="src_b"),
              candidate("a@example.com", source="src_c"),
              candidate("z@example.com", source="src_a", quote="Email: z@example.com"),
              candidate("Alice Kim", kind=ExposureType.IDENTITY)]
    expected = deduplicate_exposures(inputs)
    assert [(e.exposure_id, e.value) for e in expected] == [
        ("exp_001", "a@example.com"), ("exp_002", "z@example.com"), ("exp_003", "Alice Kim")]
    for order in permutations(inputs):
        assert deduplicate_exposures(order) == expected


def test_sequential_ids_are_unique_beyond_three_digits_without_personal_data():
    inputs = [candidate(f"private-person-{i:04}@example.com") for i in range(1001)]
    result = deduplicate_exposures(reversed(inputs))
    ids = [e.exposure_id for e in result]
    assert len(set(ids)) == 1001
    assert ids == [f"exp_{i:03d}" for i in range(1, 1002)]
    assert all(re.fullmatch(r"exp_[0-9]+", value) for value in ids)
    assert all("private" not in value and "@" not in value for value in ids)


def test_whitespace_variants_keep_ids_among_other_groups_when_reordered():
    inputs = [candidate(" Alice   Kim ", kind=ExposureType.IDENTITY),
              candidate("Alice Kim", kind=ExposureType.IDENTITY),
              candidate("Zoe Lee", kind=ExposureType.IDENTITY),
              candidate("alice@example.com")]
    expected = deduplicate_exposures(inputs)
    for order in permutations(inputs):
        actual = deduplicate_exposures(order)
        assert [(e.exposure_id, e.type, " ".join(e.value.split()), e.sources) for e in actual] == [
            (e.exposure_id, e.type, " ".join(e.value.split()), e.sources) for e in expected]
        first_name = next(c.value for c in order if "Alice" in c.value)
        assert next(e.value for e in actual if e.exposure_id == "exp_002") == first_name


def test_ids_are_request_local_and_can_shift_when_key_set_changes():
    alone = deduplicate_exposures([candidate("z@example.com")])
    expanded = deduplicate_exposures([candidate("a@example.com"), candidate("z@example.com")])
    assert alone[0].exposure_id == "exp_001"
    assert expanded[1].exposure_id == "exp_002"


def test_inputs_unchanged_and_outputs_not_shared_across_calls():
    inputs = [candidate(source="src_a"), candidate(source="src_b")]
    before = deepcopy(inputs)
    first = deduplicate_exposures(inputs)
    assert deduplicate_exposures(inputs) == first
    first[0].sources[0].evidence = "caller mutation"
    first[0].sources.append(ExposureSource(source_id="foreign", evidence="foreign"))
    second = deduplicate_exposures(inputs)
    assert inputs == before
    assert public_pairs(second[0]) == [("src_a", "alice@example.com"), ("src_b", "alice@example.com")]
    assert deduplicate_exposures([]) == []
    other = deduplicate_exposures([candidate(source="src_a", quote="Other request's quote")])
    assert public_pairs(other[0]) == [("src_a", "Other request's quote")]
    assert other[0].exposure_id == second[0].exposure_id == "exp_001"


def test_public_models_round_trip_without_extra_fields():
    for exposure in deduplicate_exposures([candidate(), candidate("Bob Lee", kind=ExposureType.RELATIONSHIP,
                                                               relation="advisor")]):
        assert Exposure.model_validate_json(exposure.model_dump_json()) == exposure
        assert set(exposure.model_dump()) == {"exposure_id", "type", "value", "relation", "sources"}
        assert exposure.sources
        for source in exposure.sources:
            assert ExposureSource.model_validate(source.model_dump()) == source
            assert set(source.model_dump()) == {"source_id", "evidence"}
        with pytest.raises(ValidationError):
            Exposure.model_validate({**exposure.model_dump(), "sources": []})


@pytest.mark.parametrize("bad", [None, {}, "candidate", ExposureCandidate(
    "src_001", 1, ExposureType.CONTACT, "alice@example.com",
    EvidenceReference(2, (0,), 10, 27, "alice@example.com")),
])
def test_unvalidated_objects_are_never_promoted(bad):
    with pytest.raises(ValueError, match="ValidatedExposureCandidate"):
        deduplicate_exposures([candidate(), bad])


@pytest.mark.parametrize("change", [
    {"source_id": ""}, {"source_id": " \n "}, {"source_id": None}, {"source_id": 123},
    {"value": ""}, {"value": " \t "}, {"value": None}, {"value": 12},
    {"type": "contact"}, {"type": None},
    {"target_block_id": -1}, {"target_block_id": True}, {"target_block_id": "1"},
    {"relation": " "}, {"relation": 12},
    {"evidence": None}, {"attribution": ()}, {"attribution": None}, {"attribution": [None]},
    {"attribution": (None,)},
])
def test_malformed_boundary_fields_raise_instead_of_returning_partial_results(change):
    with pytest.raises(ValueError):
        deduplicate_exposures([candidate(), replace(candidate(), **change)])


@pytest.mark.parametrize("change", [
    {"quote": ""}, {"quote": " "}, {"quote": None}, {"quote": 5},
    {"block_id": -1}, {"block_id": True}, {"block_id": "2"},
    {"start": -1}, {"start": True}, {"start": "1"}, {"end": 10}, {"end": None},
    {"text_indices": ()}, {"text_indices": []}, {"text_indices": (-1,)},
    {"text_indices": (True,)}, {"text_indices": ("0",)},
    {"text_indices": (1, 0)}, {"text_indices": (0, 0)},
])
def test_malformed_value_evidence_is_not_public_evidence(change):
    original = candidate()
    with pytest.raises(ValueError):
        deduplicate_exposures([replace(original, evidence=replace(original.evidence, **change))])


def test_iterator_implementation_error_propagates():
    def broken():
        yield candidate()
        raise RuntimeError("upstream bug")
    with pytest.raises(RuntimeError, match="upstream bug"):
        deduplicate_exposures(broken())


def test_real_phase4_all_types_multiple_sources_and_distinct_quotes(
        phase4_parse, phase4_card, phase4_subject):
    fields = ('<p>Phone: 02-1234-5678</p><p>Lab: AI &amp; Security Lab</p>'
              '<p>Advisor: Bob Lee</p><p>Collaborator: Bob Lee</p>'
              '<p>Activity: Presented DFSA</p>'
              '<p>Research Interests: Artificial\n  Intelligence</p>'
              '<p>Research Interests: Artificial Intelligence</p>'
              '<p>GitHub: <a href="https://github.com/alice">alice</a></p>'
              '<p>Project period: 2022–2024</p>')
    documents = [replace(phase4_parse(phase4_card(fields)), source_id="src_b"),
                 replace(phase4_parse(phase4_card(fields)), source_id="src_a")]
    decisions = [verify_identity(phase4_subject, doc) for doc in documents]
    assert all(d.identity_status == IdentityStatus.CONFIRMED for d in decisions)
    extractions = [extract_exposures(doc, decision) for doc, decision in zip(documents, decisions)]
    inputs = [c for result in extractions for c in result.candidates]
    before = deepcopy((documents, decisions, extractions))
    output = deduplicate_exposures(inputs)
    assert len(output) == 10  # Eight types, plus a phone and a second relationship.
    assert {e.type for e in output} == set(ExposureType)
    for exposure in output:
        matching = [c for c in inputs if (c.type, c.value, c.relation) ==
                    (exposure.type, exposure.value, exposure.relation)]
        assert set(public_pairs(exposure)) == {(c.source_id, c.evidence.quote) for c in matching}
        assert {s.source_id for s in exposure.sources} == {"src_a", "src_b"}
        assert Exposure.model_validate_json(exposure.model_dump_json()) == exposure
    interests = next(e for e in output if e.type == ExposureType.INTEREST)
    assert len(interests.sources) == 4
    lab = next(e for e in output if e.type == ExposureType.AFFILIATION)
    assert lab.value == "AI & Security Lab"
    assert all("&amp;" not in s.evidence and "&" in s.evidence for s in lab.sources)
    for doc, extraction in zip(documents, extractions):
        for c in extraction.candidates:
            for ref in (c.evidence, *c.attribution):
                assert unescape(doc.html_text[ref.start:ref.end]) == ref.quote
    assert before == (documents, decisions, extractions)
    assert deduplicate_exposures(reversed(inputs)) == output


def test_real_definition_list_attribution_stays_separate_and_unmodified(phase4_parse, phase4_subject):
    document = phase4_parse('<dl><dt>Name</dt><dd>Alice Kim</dd>'
                            '<dt>Email</dt><dd>alice@example.com</dd>'
                            '<dt>Advisor</dt><dd>Bob Lee</dd></dl>')
    result = extract_exposures(document, verify_identity(phase4_subject, document))
    original = next(c for c in result.candidates if c.type == ExposureType.RELATIONSHIP)
    before = asdict(original)
    exposure = next(e for e in deduplicate_exposures(result.candidates)
                    if e.type == ExposureType.RELATIONSHIP)
    assert public_pairs(exposure) == [(document.source_id, "Bob Lee")]
    assert [r.quote for r in original.attribution] == ["Alice Kim", "Advisor"]
    assert asdict(original) == before


def test_real_inline_attribution_can_include_whitespace_spans(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p> <span itemprop=telephone>02-1234-5678</span> </p>'))
    result = extract_exposures(document, verify_identity(phase4_subject, document))
    phone = next(c for c in result.candidates if c.value == "02-1234-5678")
    assert any(r.quote.isspace() for r in phone.attribution)
    exposure = deduplicate_exposures([phone])[0]
    assert public_pairs(exposure) == [(document.source_id, "02-1234-5678")]


def test_real_separate_person_requests_do_not_share_sources_even_with_same_email(phase4_parse):
    results = []
    for name, source in [("Alice Kim", "src_a"), ("Bob Lee", "src_b")]:
        doc = replace(phase4_parse(f'<div class=profile-card><h2>{name}</h2>'
                                  '<p>Email: shared@example.com</p></div>'), source_id=source)
        subject = Subject(name=name, organization="Example University", email="shared@example.com")
        extraction = extract_exposures(doc, verify_identity(subject, doc))
        results.append(deduplicate_exposures(extraction.candidates))
    for output, source in zip(results, ("src_a", "src_b")):
        email = next(e for e in output if e.type == ExposureType.CONTACT)
        assert public_pairs(email) == [(source, "Email: shared@example.com")]


def test_real_noncontiguous_value_is_excluded_before_deduplication(phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card('<p>Research Interests: Artificial <b>Intelligence</b></p>'))
    extraction = extract_exposures(document, verify_identity(phase4_subject, document))
    output = deduplicate_exposures(extraction.candidates)
    assert all(e.type != ExposureType.INTEREST for e in output)
    assert all(s.evidence != "Artificial Intelligence" for e in output for s in e.sources)


def test_real_repeated_roots_keep_positions_in_input_and_deduplicate_public_quotes(
        phase4_parse, phase4_card, phase4_subject):
    document = phase4_parse(phase4_card() + phase4_card())
    decision = verify_identity(phase4_subject, document)
    extraction = extract_exposures(document, decision)
    assert len(decision.target_block_ids) == 2
    before = asdict(extraction)
    assert len(extraction.candidates) == 4
    output = deduplicate_exposures(extraction.candidates)
    assert len(output) == 2
    assert all(len(e.sources) == 1 for e in output)
    assert asdict(extraction) == before


def test_real_multispan_name_attribution_is_never_joined_into_public_evidence(phase4_parse):
    subject = Subject(name="Anne & Kim", email="anne@example.com", organization="Example University")
    document = phase4_parse('<div class=profile-card><h2>Anne <b>&amp;</b> Kim</h2>'
                            '<p>Email: anne@example.com</p></div>')
    extraction = extract_exposures(document, verify_identity(subject, document))
    before = asdict(extraction)
    output = deduplicate_exposures(extraction.candidates)
    assert len(output) == 1 and output[0].type == ExposureType.CONTACT
    assert public_pairs(output[0]) == [(document.source_id, "Email: anne@example.com")]
    assert [ref.quote for ref in extraction.candidates[0].attribution] == ["Anne ", "&", " Kim"]
    assert asdict(extraction) == before
