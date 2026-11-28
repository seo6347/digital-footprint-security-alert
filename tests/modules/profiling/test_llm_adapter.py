import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from dfsa.modules.profiling import llm_adapter as llm


pytestmark = pytest.mark.usefixtures("deny_unit_network")


@pytest.fixture(autouse=True)
def use_offline_runner(monkeypatch, offline_async_runner):
    monkeypatch.setattr(asyncio, "run", offline_async_runner.run)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool


def envelope(content='{"accepted":true}', *, finish="stop", model="served-model"):
    return {
        "model": model,
        "usage": {
            "prompt_tokens": 12, "completion_tokens": 9, "total_tokens": 21,
            "completion_tokens_details": {"reasoning_tokens": 3},
        },
        "choices": [{"finish_reason": finish, "message": {"content": content}}],
    }


def session(handler, **settings):
    return llm.MindlogicSession(
        api_key="synthetic-secret", model="default-model", transport=httpx.MockTransport(handler), **settings,
    )


def test_sync_session_reuses_transport_with_default_and_explicit_model(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=envelope())

    monkeypatch.setenv("HTTPS_PROXY", "https://proxy.example.invalid")
    client = session(handler, max_completion_tokens=200)

    async def operation(active):
        assert not active._client.trust_env
        assert not active._client.follow_redirects
        return [
            await active.complete("rules", {"text": "untrusted data"}, Answer),
            await active.complete("rules", {}, Answer, model="task-model"),
        ]

    first, second = client.run_sync(operation)
    assert client._client is None
    assert first.value == second.value == Answer(accepted=True)
    assert first.usage == second.usage == llm.Usage(12, 9, 21, 3)
    assert first.elapsed_ms >= 0 and first.actual_model == "served-model"
    assert first.requested_model == "default-model" and second.requested_model == "task-model"
    for request, model in zip(requests, ("default-model", "task-model"), strict=True):
        assert str(request.url) == llm.GATEWAY and request.method == "POST"
        assert request.headers["Authorization"] == "Bearer synthetic-secret"
        payload = json.loads(request.content)
        assert payload["model"] == model and payload["max_completion_tokens"] == 200
        assert "tools" not in payload and "stream" not in payload
        assert payload["response_format"]["json_schema"] == {
            "name": "Answer", "strict": True, "schema": Answer.model_json_schema(),
        }
        assert [message["role"] for message in payload["messages"]] == ["system", "user"]


@pytest.mark.parametrize(("response", "error"), [
    (httpx.Response(301, headers={"Location": "https://other.example.invalid/"}), "redirect_rejected"),
    (httpx.Response(400), "invalid_request"),
    (httpx.Response(401), "authentication"),
    (httpx.Response(402), "insufficient_credits"),
    (httpx.Response(403), "permission"),
    (httpx.Response(404), "model_unavailable"),
    (httpx.Response(429), "rate_limit"),
    (httpx.Response(503), "server_error"),
    (httpx.Response(200, content=b"not an envelope"), "invalid_response"),
    (httpx.Response(200, json=envelope(finish="length")), "truncated"),
    (httpx.Response(200, json=envelope(finish="content_filter")), "refused"),
    (httpx.Response(200, json=envelope(None)), "empty_response"),
    (httpx.Response(200, json=envelope("bad JSON")), "invalid_json"),
    (httpx.Response(200, json=envelope('{"accepted":"yes"}')), "schema_error"),
    (httpx.Response(200, json=envelope('{"accepted":true,"extra":1}')), "schema_error"),
])
def test_errors_are_classified_without_retry_or_body_leak(response, error):
    requests = []

    def handler(request):
        requests.append(request)
        return response

    answer = session(handler).run_sync(lambda client: client.complete("synthetic-secret", {}, Answer))
    assert answer.error == error and answer.value is None
    assert "synthetic-secret" not in repr(answer)
    assert len(requests) == 1


def test_vendor_echo_of_key_is_not_exposed_in_metadata():
    result = session(lambda request: httpx.Response(200, json=envelope(model="synthetic-secret"))).run_sync(
        lambda client: client.complete("rules", {}, Answer)
    )
    assert result.value == Answer(accepted=True) and result.actual_model is None


def test_session_budget_counts_started_failed_calls_only(monkeypatch):
    monkeypatch.setattr(llm, "SESSION_CALLS", 2)
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.ConnectError("sensitive detail")

    async def operation(client):
        too_large = await client.complete("rules", {"data": "x" * llm.MAX_REQUEST_BYTES}, Answer)
        calls = [await client.complete("rules", {}, Answer) for _ in range(3)]
        return [too_large.error, *(result.error for result in calls)]

    assert session(handler).run_sync(operation) == [
        "request_too_large", "network_error", "network_error", "call_limit",
    ]
    assert len(attempts) == 2


def test_timeout_cancels_inflight_call_and_session_deadline_blocks_new_call(monkeypatch):
    monkeypatch.setattr(llm, "SESSION_SECONDS", 0.15)
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(5)
        pytest.fail("The network call was not cancelled")

    async def operation(client):
        first = await client.complete("rules", {}, Answer)
        second = await client.complete("rules", {}, Answer)
        return first.error, second.error

    assert session(handler).run_sync(operation) == ("timeout", "timeout")
    assert len(calls) == 1


def test_response_is_rejected_before_reading_beyond_limit():
    class OversizedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * llm.MAX_RESPONSE_BYTES
            yield b"x"
            pytest.fail("Read continued past the response limit")

    result = session(lambda request: httpx.Response(200, stream=OversizedStream())).run_sync(
        lambda client: client.complete("rules", {}, Answer)
    )
    assert result.error == "response_too_large"


def test_rejects_open_pydantic_schema_before_network():
    class OpenModel(BaseModel):
        value: str

    result = session(lambda request: pytest.fail("Unexpected call")).run_sync(
        lambda client: client.complete("rules", {}, OpenModel)
    )
    assert result.error == "invalid_schema"


@pytest.mark.parametrize("value", ["0", "16385", "bad"])
def test_invalid_token_configuration(monkeypatch, value):
    monkeypatch.setenv("DFSA_LLM_API_KEY", "synthetic-secret")
    monkeypatch.setenv("DFSA_LLM_MODEL", "default-model")
    monkeypatch.setenv("DFSA_LLM_MAX_COMPLETION_TOKENS", value)
    with pytest.raises(ValueError, match="completion token limit"):
        llm.MindlogicSession.from_env()
