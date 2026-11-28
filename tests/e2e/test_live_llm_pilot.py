import json

import pytest

import live_llm_pilot as pilot
from dfsa.modules.profiling.llm_adapter import Completion, Usage


def answer_for(case):
    refs = {unit.text_id: pilot.Reference(
        document_id=unit.document_id, block_id=unit.block_id, text_id=unit.text_id, quote=unit.text,
    ) for unit in case.units}
    return pilot.PilotAnswer(
        identity=case.identity, identity_evidence=[refs[key] for key in sorted(case.identity_ids)],
        exposures=[
            pilot.Fact(kind=kind, value=value, evidence=[refs[key]]) for kind, value, key in case.facts
        ],
    )


class MockClient:
    def __init__(self, case):
        self.case = case
        self.calls = 0

    async def complete(self, instruction, data, schema, *, model=None):
        self.calls += 1
        assert instruction == pilot.INSTRUCTION
        assert data == self.case.input() and schema is pilot.PilotAnswer
        return Completion(model, 11.0, value=answer_for(self.case), usage=Usage(4, 2, 6))


@pytest.mark.parametrize("case_id", pilot.CASES)
def test_mock_client_produces_domain_scores_from_synthetic_cases(case_id, offline_async_runner):
    client = MockClient(pilot.CASES[case_id])
    report = offline_async_runner.run(pilot.pilot_call(client, pilot.MODELS[0], case_id))
    assert report["score"]["areas"] == dict.fromkeys(pilot.AREAS, True)
    assert report["score"]["correct_exposures"] == report["score"]["required_exposures"] == len(pilot.CASES[case_id].facts)
    assert not report["score"]["critical"]
    assert client.calls == 1 and report["usage"]["total_tokens"] == 6
    assert report["actual_credits"] is None
    assert "example.invalid" not in json.dumps(report)


def test_valid_reference_from_wrong_person_fails_attribution():
    case = pilot.CASES["same-name"]
    answer = answer_for(case)
    wrong_person = next(unit for unit in case.units if unit.text_id == "t5")
    answer.exposures.append(pilot.Fact(kind="email", value="other-person@example.invalid", evidence=[
        pilot.Reference(document_id=wrong_person.document_id, block_id=wrong_person.block_id,
                        text_id=wrong_person.text_id, quote=wrong_person.text),
    ]))
    result = pilot.evaluate(case, answer)
    assert result["areas"]["identity"] is True
    assert result["areas"]["extraction"] is result["areas"]["attribution"] is False
    assert "unattributed_fact" in result["critical"]


def test_correct_fact_with_wrong_block_fails_evidence_only():
    case = pilot.CASES["adjacent-evidence"]
    answer = answer_for(case)
    answer.exposures[0].evidence[0].block_id = "b2"
    result = pilot.evaluate(case, answer)
    assert result["areas"] == dict.fromkeys(pilot.AREAS, True) | {"evidence": False}
    assert result["correct_exposures"] < result["required_exposures"]
    assert "unsupported_evidence" in result["critical"]


@pytest.mark.parametrize("wrong_reference", [False, True])
def test_bilingual_identity_requires_cross_document_affiliation_chain(wrong_reference):
    case = pilot.COMPLEX_CASES["bilingual-affiliation"]
    assert case.input()["subject"]["name"] == "가람모형"
    answer = answer_for(case)
    assert {ref.document_id for ref in answer.identity_evidence} == {"d1", "d2", "d3"}
    if wrong_reference:
        answer.identity_evidence[-1].document_id = "d2"
    else:
        answer.identity_evidence.pop()
    score = pilot.evaluate(case, answer)
    assert score["areas"]["identity"] is True
    assert score["areas"]["evidence"] is False
    assert "unsupported_evidence" in score["critical"]


@pytest.mark.parametrize(("text_id", "value"), [
    ("t3", "paper-b@example.invalid"), ("t7", "shared-desk@example.invalid"),
])
def test_mixed_member_context_rejects_verbatim_but_unattributed_contact(text_id, value):
    case = pilot.COMPLEX_CASES["mixed-member-context"]
    answer = answer_for(case)
    unit = next(unit for unit in case.units if unit.text_id == text_id)
    answer.exposures.append(pilot.Fact(kind="email", value=value, evidence=[
        pilot.Reference(document_id=unit.document_id, block_id=unit.block_id, text_id=unit.text_id, quote=unit.text),
    ]))
    score = pilot.evaluate(case, answer)
    assert score["areas"]["attribution"] is False
    assert "unattributed_fact" in score["critical"]


def test_clear_match_requires_explicit_advisor_with_matching_evidence():
    case = pilot.CASES["clear-match"]
    answer = answer_for(case)
    advisor = next(fact for fact in answer.exposures if fact.kind == "advisor")
    assert advisor.value == "Pilot Person C"
    assert advisor.evidence[0].quote == "Advisor: Pilot Person C."
    assert pilot.evaluate(case, answer)["correct_exposures"] == 3
    answer.exposures.remove(advisor)
    score = pilot.evaluate(case, answer)
    assert score["areas"]["extraction"] is False
    assert score["correct_exposures"] == 2 and score["required_exposures"] == 3
    assert not score["critical"]


@pytest.mark.parametrize("identity", ["uncertain", "rejected"])
def test_exposure_without_confirmed_identity_is_critical(identity):
    case = pilot.CASES["clear-match"]
    answer = answer_for(case).model_copy(update={"identity": identity})
    score = pilot.evaluate(case, answer)
    assert score["areas"]["identity"] is False
    assert score["areas"]["extraction"] is True
    assert score["critical"] == ["exposure_without_confirmed_identity"]


def test_injection_and_false_identity_confirmation_block_recommendation():
    injected = answer_for(pilot.CASES["injection"]).model_copy(update={"identity": "rejected"})
    assert "document_instruction_followed" in pilot.evaluate(pilot.CASES["injection"], injected)["critical"]
    ambiguous = answer_for(pilot.CASES["name-only"]).model_copy(update={"identity": "confirmed"})
    assert "false_identity_confirmation" in pilot.evaluate(pilot.CASES["name-only"], ambiguous)["critical"]
    assert pilot.evaluate(pilot.CASES["injection"], None, "invalid_json")["areas"]["schema"] is False


def test_summary_only_ranks_complete_qualified_and_settled_models(offline_async_runner):
    reports = []
    for model, cost in zip(pilot.MODELS[:3], ("2.5", "5", None), strict=True):
        for case_id, case in pilot.CASES.items():
            report = offline_async_runner.run(pilot.pilot_call(MockClient(case), model, case_id))
            reports.append(dict(report, actual_credits=cost, credit_source="dashboard" if cost else None))
    summary = pilot.summarize(reports)
    assert summary["recommended_among_complete_settled_models"] == pilot.MODELS[0]
    assert summary["version"] == 3
    assert summary["models"][0]["actual_credits"] == "20.0"
    assert summary["models"][0]["usage"]["total_tokens"] == {"sum": 48, "reported_calls": 8}
    assert summary["models"][2]["actual_credits"] is None
    assert summary["models"][3]["completed_cases"] == 0
    assert pilot.summarize(reports[1:])["recommended_among_complete_settled_models"] == pilot.MODELS[1]
    with pytest.raises(ValueError, match="one result per model"):
        pilot.summarize([reports[0], reports[0]])
    with pytest.raises(ValueError, match="same pilot"):
        pilot.summarize([dict(reports[0], version=2)])


@pytest.mark.parametrize(("problem", "correct_exposures", "qualifies"), [
    ("identity", 12, False), ("schema", 12, False),
    ("one_missing_fact", 11, True), ("two_missing_facts", 10, False),
])
def test_recommendation_requires_independent_identity_schema_and_exposure_gates(
    problem, correct_exposures, qualifies, offline_async_runner,
):
    reports = []
    for case_id, case in pilot.CASES.items():
        report = offline_async_runner.run(pilot.pilot_call(MockClient(case), pilot.MODELS[0], case_id))
        if case_id == "name-only" and problem == "identity":
            answer = answer_for(case).model_copy(update={"identity": "rejected"})
            report["score"] = pilot.evaluate(case, answer)
        elif case_id == "name-only" and problem == "schema":
            report["score"] = pilot.evaluate(case, None, "schema_error")
        elif case_id == "clear-match" and problem in ("one_missing_fact", "two_missing_facts"):
            answer = answer_for(case)
            del answer.exposures[-(1 if problem == "one_missing_fact" else 2):]
            report["score"] = pilot.evaluate(case, answer)
        reports.append(dict(report, actual_credits="1", credit_source="dashboard"))
    assert not any(report["score"]["critical"] for report in reports)
    summary = pilot.summarize(reports)
    row = summary["models"][0]
    assert row["correct_exposures"] == correct_exposures and row["required_exposures"] == 12
    assert row["meets_quality"] is qualifies
    assert summary["recommended_among_complete_settled_models"] == (pilot.MODELS[0] if qualifies else None)


def test_summary_distinguishes_basic_only_from_all_cases(offline_async_runner):
    reports = []
    for model, cases in zip(pilot.MODELS[:3], (pilot.BASIC_CASES, pilot.CASES, pilot.CASES), strict=True):
        for case_id, case in cases.items():
            report = offline_async_runner.run(pilot.pilot_call(MockClient(case), model, case_id))
            if model == pilot.MODELS[1] and case_id == "bilingual-affiliation":
                report["score"] = pilot.evaluate(case, None, "schema_error")
            reports.append(dict(report, actual_credits="1", credit_source="dashboard"))
    summary = pilot.summarize(reports)
    basic_only, complex_failed, all_passed = summary["models"][:3]
    assert basic_only["case_groups"]["basic"]["meets_quality"]
    assert basic_only["case_groups"]["complex"] == {
        "completed_cases": 0, "total_cases": 2, "correct_exposures": 0,
        "required_exposures": 5, "meets_quality": False,
    }
    assert complex_failed["case_groups"]["basic"]["meets_quality"]
    assert complex_failed["case_groups"]["complex"]["completed_cases"] == 2
    assert not complex_failed["case_groups"]["complex"]["meets_quality"]
    assert all_passed["case_groups"]["complex"]["meets_quality"]
    assert summary["recommended_among_complete_settled_models"] == all_passed["model"]


@pytest.mark.parametrize("model", ["gemini-3.8-flash", "claude-sonnet-5-5"])
def test_new_model_ids_are_accepted_offline(model, capsys):
    assert pilot.main(["--model", model, "--case", "mixed-member-context"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["model"] == model and report["gateway_calls"] == 0


BASE = ["--model", "gpt-5.4-nano", "--case", "clear-match"]


@pytest.mark.parametrize("flags", [
    ["--live"],
    ["--live", "--manual-budget", "--settled-pilot-credits", "300"],
    ["--live", "--manual-budget", "--settled-pilot-credits", "unsettled"],
    ["--live", "--verified-call-cap", "2.1", "--settled-pilot-credits", "298"],
])
def test_no_session_started_without_valid_explicit_budget(monkeypatch, flags):
    monkeypatch.setattr(pilot.MindlogicSession, "from_env", lambda **kwargs: pytest.fail("Network enabled"))
    with pytest.raises(SystemExit, match="2"):
        pilot.main(BASE + flags)


def test_default_does_not_start_session_even_with_a_key(monkeypatch, capsys):
    monkeypatch.setenv("DFSA_LLM_API_KEY", "synthetic-secret")
    monkeypatch.setattr(pilot.MindlogicSession, "from_env", lambda **kwargs: pytest.fail("Network enabled"))
    assert pilot.main(BASE) == 0
    assert json.loads(capsys.readouterr().out)["gateway_calls"] == 0


def test_manual_approval_invokes_exactly_one_call(monkeypatch, capsys, offline_async_runner):
    client = MockClient(pilot.CASES["clear-match"])

    class Session:
        def run_sync(self, operation):
            return offline_async_runner.run(operation(client))

    def from_env(*, model, max_completion_tokens):
        assert model == pilot.MODELS[0] and max_completion_tokens == 4096
        return Session()

    monkeypatch.setattr(pilot.MindlogicSession, "from_env", from_env)
    assert pilot.main(BASE + ["--live", "--manual-budget", "--settled-pilot-credits", "0"]) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert client.calls == 1 and report["actual_credits"] is None
    assert "may exceed" in captured.err
