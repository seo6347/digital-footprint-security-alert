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
    assert report["score"]["correct"] == report["score"]["required"]
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
    assert result["correct"] < result["required"] and "unsupported_evidence" in result["critical"]


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
    assert summary["models"][0]["actual_credits"] == "15.0"
    assert summary["models"][0]["usage"]["total_tokens"] == {"sum": 36, "reported_calls": 6}
    assert summary["models"][2]["actual_credits"] is None
    assert summary["models"][3]["completed_cases"] == 0
    assert pilot.summarize(reports[1:])["recommended_among_complete_settled_models"] == pilot.MODELS[1]
    with pytest.raises(ValueError, match="one result per model"):
        pilot.summarize([reports[0], reports[0]])


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
