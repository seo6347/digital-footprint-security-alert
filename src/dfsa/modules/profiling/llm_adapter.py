"""Internal structured completion boundary for Profiling."""

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Generic, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

GATEWAY = "https://factchat-cloud.mindlogic.ai/v1/gateway/chat/completions/"
DEFAULT_TOKENS = 4096
MAX_TOKENS = 16384
MAX_REQUEST_BYTES = 32 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
CALL_SECONDS = 20
SESSION_SECONDS = 90
SESSION_CALLS = 10

Model = TypeVar("Model", bound=BaseModel)
Result = TypeVar("Result")


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None


@dataclass(frozen=True)
class Completion(Generic[Model]):
    requested_model: str
    elapsed_ms: float
    value: Model | None = None
    error: str | None = None
    actual_model: str | None = None
    usage: Usage = Usage()


class LLMClient(Protocol):
    async def complete(
        self, instruction: str, data: Mapping, schema: type[Model], *, model: str | None = None,
    ) -> Completion[Model]: ...


_HTTP_ERRORS = {
    400: "invalid_request", 422: "invalid_request",
    401: "authentication", 402: "insufficient_credits", 403: "permission",
    404: "model_unavailable", 408: "timeout", 429: "rate_limit",
}
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


def _closed_objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object" and (
            node.get("additionalProperties") is not False
            or set(node.get("required", ())) != set(node.get("properties", {}))
        ):
            return False
        return all(_closed_objects(value) for value in node.values())
    if isinstance(node, list):
        return all(_closed_objects(value) for value in node)
    return True


def _usage(payload: dict) -> Usage:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return Usage()
    details = usage.get("completion_tokens_details")
    if not isinstance(details, dict):
        details = {}

    def count(fields, key):
        value = fields.get(key)
        return value if type(value) is int and value >= 0 else None

    return Usage(
        count(usage, "prompt_tokens"), count(usage, "completion_tokens"),
        count(usage, "total_tokens"), count(details, "reasoning_tokens"),
    )


class MindlogicSession:
    """One sequential request-scoped session. Open it in the calling event loop."""

    def __init__(
        self, *, api_key: str, model: str, max_completion_tokens: int = DEFAULT_TOKENS,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key.strip() or not _MODEL_ID.fullmatch(model.strip()) or api_key.strip() in model:
            raise ValueError("LLM API key and model are required")
        if type(max_completion_tokens) is not int or not 1 <= max_completion_tokens <= MAX_TOKENS:
            raise ValueError("Invalid LLM completion token limit")
        self._key = api_key.strip()
        self._model = model.strip()
        self._tokens = max_completion_tokens
        self._transport = transport
        self._client = None

    @classmethod
    def from_env(cls, *, model: str | None = None, max_completion_tokens: int | None = None):
        if max_completion_tokens is None:
            try:
                max_completion_tokens = int(os.getenv("DFSA_LLM_MAX_COMPLETION_TOKENS", str(DEFAULT_TOKENS)))
            except ValueError:
                raise ValueError("Invalid LLM completion token limit") from None
        return cls(
            api_key=os.getenv("DFSA_LLM_API_KEY", ""), model=model or os.getenv("DFSA_LLM_MODEL", ""),
            max_completion_tokens=max_completion_tokens,
        )

    async def __aenter__(self):
        if self._client is not None:
            raise RuntimeError("LLM session is already open")
        self._client = httpx.AsyncClient(
            transport=self._transport, trust_env=False, follow_redirects=False, timeout=CALL_SECONDS,
        )
        self._deadline = monotonic() + SESSION_SECONDS
        self._calls = 0
        return self

    async def __aexit__(self, *exc):
        client, self._client = self._client, None
        await client.aclose()

    def run_sync(self, operation: Callable[[LLMClient], Awaitable[Result]]) -> Result:
        """Run one complete session from synchronous code."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Use the async LLM interface inside an event loop")

        async def run():
            async with self:
                return await operation(self)

        return asyncio.run(run())

    async def complete(
        self, instruction: str, data: Mapping, schema: type[Model], *, model: str | None = None,
    ) -> Completion[Model]:
        if self._client is None:
            raise RuntimeError("Open the LLM session before calling it")
        start = monotonic()
        requested = self._model if model is None else model.strip()
        if not _MODEL_ID.fullmatch(requested) or self._key in requested:
            raise ValueError("Invalid LLM model")

        def result(error=None, **fields):
            return Completion(requested, (monotonic() - start) * 1000, error=error, **fields)

        if self._calls >= SESSION_CALLS:
            return result("call_limit")
        json_schema = schema.model_json_schema()
        if json_schema.get("type") != "object" or not _closed_objects(json_schema):
            return result("invalid_schema")
        body = json.dumps({
            "model": requested,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(dict(data), ensure_ascii=False, allow_nan=False)},
            ],
            "max_completion_tokens": self._tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "strict": True, "schema": json_schema},
            },
        }, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            return result("request_too_large")
        remaining = min(start + CALL_SECONDS, self._deadline) - monotonic()
        if remaining <= 0:
            return result("timeout")
        self._calls += 1
        try:
            async with asyncio.timeout(remaining):
                async with self._client.stream(
                    "POST", GATEWAY, content=body,
                    headers={
                        "Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
                        "Accept": "application/json", "Accept-Encoding": "identity",
                    },
                ) as response:
                    status = response.status_code
                    if status != 200:
                        if response.is_redirect:
                            return result("redirect_rejected")
                        return result(_HTTP_ERRORS.get(status, "server_error" if 500 <= status < 600 else "http_error"))
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        return result("invalid_response")
                    raw = bytearray()
                    # Raw bytes also work with pre-buffered MockTransport responses.
                    if response.is_stream_consumed:
                        raw.extend(response.content)
                    else:
                        async for chunk in response.aiter_raw():
                            if len(chunk) > MAX_RESPONSE_BYTES - len(raw):
                                return result("response_too_large")
                            raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        return result("response_too_large")
        except (TimeoutError, httpx.TimeoutException):
            return result("timeout")
        except httpx.RequestError:
            return result("network_error")

        if monotonic() >= min(start + CALL_SECONDS, self._deadline):
            return result("timeout")
        try:
            payload = json.loads(raw)
        except (UnicodeError, ValueError, RecursionError):
            return result("invalid_response")
        if not isinstance(payload, dict):
            return result("invalid_response")
        actual = payload.get("model")
        safe_model = isinstance(actual, str) and _MODEL_ID.fullmatch(actual) and self._key not in actual
        metadata = {"actual_model": actual if safe_model else None, "usage": _usage(payload)}
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            return result("invalid_response", **metadata)
        choice = choices[0]
        message = choice.get("message")
        if choice.get("finish_reason") == "length":
            return result("truncated", **metadata)
        if choice.get("finish_reason") == "content_filter" or (isinstance(message, dict) and message.get("refusal")):
            return result("refused", **metadata)
        if choice.get("finish_reason") != "stop" or not isinstance(message, dict) or message.get("tool_calls"):
            return result("invalid_response", **metadata)
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            return result("empty_response", **metadata)
        try:
            value = schema.model_validate_json(content, strict=True)
        except ValidationError as exc:
            error = "invalid_json" if exc.errors(include_input=False)[0]["type"] == "json_invalid" else "schema_error"
            return result(error, **metadata)
        if monotonic() >= min(start + CALL_SECONDS, self._deadline):
            return result("timeout", **metadata)
        return result(value=value, **metadata)
