"""OpenAI adapter on the Responses API (SOLUSDEV-252 S1-W1): request shape, tool
calling, reasoning replay, cached-token usage, error taxonomy. Fake SDK client,
zero network — mirrors `_FakeAnthropicRecorder` in test_providers.py."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import AsyncIterator, Sequence
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem,
)
from solus_api.agent.prompt import provider_tool_names, resolve_tool_name, tool_specs
from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.orchestration.providers import (
    DEFAULT_TIMEOUT_SECONDS,
    OPENAI_API_KEY_NAME,
    GeminiAdapter,
    ImageBlock,
    OpenAIAdapter,
    ProviderError,
    ProviderTransientError,
    ToolCallingUnsupportedError,
    ToolConversation,
    ToolOutcome,
    ToolSpec,
    ToolUse,
    Turn,
    Usage,
    openai_content,
    openai_input,
)

# --- fake SDK -----------------------------------------------------------------


class _OpenAIRecorder:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.client_kwargs: dict[str, Any] = {}
        self.create_kwargs: dict[str, Any] = {}


def _fake_openai_cls(
    recorder: _OpenAIRecorder, script: Sequence[object], raise_on_create: Exception | None = None
) -> type:
    async def replay() -> AsyncIterator[object]:
        for event in script:
            yield event

    class FakeResponses:
        async def create(self, **kwargs: Any) -> AsyncIterator[object]:
            recorder.create_kwargs = dict(kwargs)
            if raise_on_create is not None:
                raise raise_on_create
            return replay()

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            recorder.client_kwargs = dict(kwargs)
            self.responses = FakeResponses()

        async def __aenter__(self) -> FakeAsyncOpenAI:
            recorder.events.append("client_enter")
            return self

        async def __aexit__(self, *exc: object) -> bool:
            recorder.events.append("client_exit")
            return False

    return FakeAsyncOpenAI


def _delta(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="response.output_text.delta", delta=text)


def _done(item: object) -> SimpleNamespace:
    return SimpleNamespace(type="response.output_item.done", item=item)


def _completed(tokens_in: int, tokens_out: int, cached: int | None = None) -> SimpleNamespace:
    details = None if cached is None else SimpleNamespace(cached_tokens=cached)
    usage = SimpleNamespace(
        input_tokens=tokens_in, output_tokens=tokens_out, input_tokens_details=details
    )
    return SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage))


def _call(call_id: str, name: str, arguments: str) -> ResponseFunctionToolCall:
    return ResponseFunctionToolCall(
        id=f"fc_{call_id}", call_id=call_id, name=name, arguments=arguments, type="function_call"
    )


def _reasoning() -> ResponseReasoningItem:
    return ResponseReasoningItem(
        id="rs_1", summary=[], type="reasoning", encrypted_content="opaque"
    )


def _message(text: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id="msg_1",
        role="assistant",
        status="completed",
        type="message",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )


async def _adapter() -> OpenAIAdapter:
    store = InMemorySecretStore()
    await store.put(OPENAI_API_KEY_NAME, "test-key")
    return OpenAIAdapter(store)


async def _drive(
    monkeypatch: pytest.MonkeyPatch,
    script: Sequence[object],
    *,
    conversation: ToolConversation | None = None,
    reasoning_effort: str | None = None,
    images: Sequence[ImageBlock] | None = None,
    raise_on_create: Exception | None = None,
) -> tuple[_OpenAIRecorder, list[str | ToolUse | Usage]]:
    recorder = _OpenAIRecorder()
    monkeypatch.setattr("openai.AsyncOpenAI", _fake_openai_cls(recorder, script, raise_on_create))
    adapter = await _adapter()
    events = [
        e
        async for e in adapter.stream(
            "some-model",
            "the query",
            max_tokens=64,
            images=images,
            conversation=conversation,
            reasoning_effort=reasoning_effort,
        )
    ]
    return recorder, events


_WEATHER_TOOL = ToolSpec(
    name="get_weather",
    description="weather",
    input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
)


# --- request shape --------------------------------------------------------------


async def test_text_only_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder, events = await _drive(monkeypatch, [_delta("a"), _completed(3, 4)])
    kw = recorder.create_kwargs
    assert kw["model"] == "some-model"
    assert kw["max_output_tokens"] == 64
    assert kw["stream"] is True
    assert kw["store"] is False  # §7: proprietary designs never retained server-side
    assert kw["input"] == [{"role": "user", "content": "the query"}]
    for absent in ("temperature", "instructions", "tools", "reasoning", "include"):
        assert absent not in kw
    assert events == ["a", Usage(tokens_in=3, tokens_out=4)]
    assert recorder.client_kwargs["max_retries"] == 0
    assert recorder.client_kwargs["timeout"] == DEFAULT_TIMEOUT_SECONDS
    assert recorder.events == ["client_enter", "client_exit"]


async def test_reasoning_kwargs_only_when_effort_set(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder, _ = await _drive(monkeypatch, [_completed(1, 1)], reasoning_effort="low")
    assert recorder.create_kwargs["reasoning"] == {"effort": "low"}
    assert recorder.create_kwargs["include"] == ["reasoning.encrypted_content"]
    assert "temperature" not in recorder.create_kwargs


async def test_conversation_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    replayed = ({"type": "reasoning", "id": "rs_0", "encrypted_content": "x", "summary": []},)
    conversation = ToolConversation(
        system="be terse",
        tools=(_WEATHER_TOOL,),
        messages=(
            Turn(role="user", text="hi"),
            Turn(
                role="assistant",
                text="calling",
                tool_uses=(ToolUse(id="c1", name="t", args={"a": 1}),),
            ),
            Turn(
                role="user",
                tool_results=(
                    ToolOutcome(id="c1", content="ok"),
                    ToolOutcome(id="c2", content="boom", is_error=True),
                ),
            ),
            Turn(role="assistant", text="ignored", provider_items=replayed),
        ),
    )
    recorder, _ = await _drive(monkeypatch, [_completed(1, 1)], conversation=conversation)
    kw = recorder.create_kwargs
    assert kw["instructions"] == "be terse"
    assert kw["tools"] == [
        {
            "type": "function",
            "name": "get_weather",
            "description": "weather",
            "parameters": _WEATHER_TOOL.input_schema,
            "strict": False,
        }
    ]
    assert kw["input"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "output_text", "text": "calling"}]},
        {"type": "function_call", "call_id": "c1", "name": "t", "arguments": json.dumps({"a": 1})},
        {"type": "function_call_output", "call_id": "c1", "output": "ok"},
        {"type": "function_call_output", "call_id": "c2", "output": "ERROR: boom"},
        replayed[0],  # verbatim; nothing synthesised for that turn
    ]
    assert kw["store"] is False


async def test_images_use_responses_input_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    image = ImageBlock(media_type="image/png", data=b"\x89PNGbytes")
    recorder, _ = await _drive(monkeypatch, [_completed(1, 1)], images=[image])
    content = recorder.create_kwargs["input"][0]["content"]
    assert content[0]["type"] == "input_image"
    url = content[0]["image_url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == image.data
    assert content[1] == {"type": "input_text", "text": "the query"}


def test_openai_content_shapes() -> None:
    assert openai_content("q", None) == "q"
    assert openai_content("q", []) == "q"
    blocks = openai_content("q", [ImageBlock(media_type="image/jpeg", data=b"j")])
    assert isinstance(blocks, list)
    assert [b["type"] for b in blocks] == ["input_image", "input_text"]


# --- streaming + tool calls -------------------------------------------------------


async def test_function_call_becomes_tool_use_with_provider_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = ToolConversation(
        system="s", tools=(_WEATHER_TOOL,), messages=(Turn(role="user", text="hi"),)
    )
    script = [
        _done(_reasoning()),
        _delta("Let me "),
        _delta("check."),
        _done(_message("Let me check.")),
        _done(_call("c1", "get_weather", json.dumps({"city": "Paris"}))),
        _completed(10, 5, cached=4),
    ]
    _, events = await _drive(monkeypatch, script, conversation=conversation)
    assert events[:2] == ["Let me ", "check."]
    assert events[2] == ToolUse(id="c1", name="get_weather", args={"city": "Paris"})
    usage = events[3]
    assert isinstance(usage, Usage)
    assert (usage.tokens_in, usage.tokens_out, usage.tokens_cached_in) == (10, 5, 4)
    assert [i["type"] for i in usage.provider_items] == ["reasoning", "message", "function_call"]
    assert usage.provider_items[0]["encrypted_content"] == "opaque"
    assert usage.provider_items[2]["call_id"] == "c1"
    assert len(events) == 4  # exactly one Usage, last


async def test_malformed_function_calls_are_dropped_not_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Weird:
        type = "function_call"
        call_id = 7  # not a string
        name = "get_weather"
        arguments = "{}"

        def model_dump(self, **_: Any) -> dict[str, Any]:
            return {"type": "function_call"}

    script = [
        _done(_call("c1", "get_weather", "[1, 2]")),  # not an object
        _done(_call("c2", "get_weather", "not json")),
        _done(Weird()),
        _done(_call("c3", "get_weather", '{"city": "Oslo"}')),
        _completed(1, 1),
    ]
    with caplog.at_level(logging.WARNING, logger="solus.orchestration.providers"):
        _, events = await _drive(monkeypatch, script)
    uses = [e for e in events if isinstance(e, ToolUse)]
    assert uses == [ToolUse(id="c3", name="get_weather", args={"city": "Oslo"})]
    assert sum("function_call" in r.getMessage() for r in caplog.records) == 3
    assert "Oslo" not in caplog.text


async def test_usage_without_cached_details_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _, events = await _drive(monkeypatch, [_completed(2, 3)])
    assert events == [Usage(tokens_in=2, tokens_out=3, tokens_cached_in=0)]


# --- error taxonomy ---------------------------------------------------------------


async def test_failed_raises_provider_error_without_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = SimpleNamespace(code="server_error", message="the query leaked")
    response = SimpleNamespace(error=error)
    script = [_delta("partial"), SimpleNamespace(type="response.failed", response=response)]
    recorder = _OpenAIRecorder()
    monkeypatch.setattr("openai.AsyncOpenAI", _fake_openai_cls(recorder, script))
    adapter = await _adapter()
    with pytest.raises(ProviderError) as excinfo:
        async for _ in adapter.stream("some-model", "the query", max_tokens=8):
            pass
    assert isinstance(excinfo.value, ProviderTransientError)
    text = str(excinfo.value)
    assert "response.failed" in text and "some-model" in text
    assert "the query" not in text and "leaked" not in text


async def test_incomplete_is_billed_and_terminates_normally(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """max_output_tokens exhaustion is a REAL, PAID call with partial text: it must
    yield its Usage so the gateway's cost hook fires (security review C1), never
    raise past it."""
    usage = SimpleNamespace(
        input_tokens=40, output_tokens=64, input_tokens_details=SimpleNamespace(cached_tokens=8)
    )
    response = SimpleNamespace(
        usage=usage, incomplete_details=SimpleNamespace(reason="max_output_tokens")
    )
    script = [
        _delta("partial"),
        _done(_message("partial")),
        SimpleNamespace(type="response.incomplete", response=response),
    ]
    with caplog.at_level(logging.WARNING, logger="solus.orchestration.providers"):
        _, events = await _drive(monkeypatch, script)
    assert events[0] == "partial"
    final = events[-1]
    assert isinstance(final, Usage)
    assert (final.tokens_in, final.tokens_out, final.tokens_cached_in) == (40, 64, 8)
    assert [i["type"] for i in final.provider_items] == ["message"]
    assert "max_output_tokens" in caplog.text and "partial" not in caplog.text


async def test_stream_without_terminal_event_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dropped connection must never be reported as a successful zero-usage call."""
    with pytest.raises(ProviderError, match="without completion"):
        await _drive(monkeypatch, [_delta("partial")])


async def test_dropped_function_call_is_not_replayed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed call is dropped from the proposals AND from the replay items —
    replaying it with no function_call_output would 400 the next round."""
    script = [
        _done(_reasoning()),
        _done(_call("bad", "get_weather", "not json")),
        _done(_call("ok", "get_weather", '{"city": "Oslo"}')),
        _completed(1, 1),
    ]
    _, events = await _drive(monkeypatch, script)
    usage = events[-1]
    assert isinstance(usage, Usage)
    assert [i.get("call_id", i["type"]) for i in usage.provider_items] == ["reasoning", "ok"]


async def test_authentication_error_carries_no_key_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = _status_error(openai.AuthenticationError, 401)
    error.message = "Incorrect API key provided: sk-secret-value"  # what the SDK echoes
    with pytest.raises(ProviderError) as excinfo:
        await _drive(monkeypatch, [], raise_on_create=error)
    assert not isinstance(excinfo.value, ProviderTransientError)
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__
    assert "sk-secret" not in str(excinfo.value)


def _status_error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return cls("msg", response=httpx.Response(status, request=request), body={"code": "bad_thing"})


@pytest.mark.parametrize(
    "error",
    [
        _status_error(openai.RateLimitError, 429),
        _status_error(openai.InternalServerError, 500),
        openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com")),
    ],
)
async def test_transient_errors_are_classified(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    with pytest.raises(ProviderTransientError) as excinfo:
        await _drive(monkeypatch, [], raise_on_create=error)
    assert "some-model" in str(excinfo.value)
    assert "the query" not in str(excinfo.value)


async def test_a_rate_limit_inside_the_stream_body_is_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observed live: OpenAI reports a mid-stream 429 in the SSE BODY, so the SDK
    raises a bare APIError rather than RateLimitError. It must still reach the
    gateway's backoff — the message even says how long to wait."""
    error = openai.APIError(
        "Rate limit reached for a model on tokens per min (TPM). Try again in 2.742s.",
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        body={"code": "rate_limit_exceeded", "type": "tokens"},
    )
    with pytest.raises(ProviderTransientError) as excinfo:
        await _drive(monkeypatch, [], raise_on_create=error)
    assert "rate_limit_exceeded" in str(excinfo.value)
    assert "the query" not in str(excinfo.value)


async def test_an_unretryable_stream_body_error_stays_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A billing failure is not transient: retrying burns the budget on something
    that cannot succeed."""
    error = openai.APIError(
        "You exceeded your current quota.",
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        body={"code": "insufficient_quota", "type": "billing"},
    )
    with pytest.raises(ProviderError) as excinfo:
        await _drive(monkeypatch, [], raise_on_create=error)
    assert not isinstance(excinfo.value, ProviderTransientError)
    assert "insufficient_quota" in str(excinfo.value)


async def test_bad_request_is_a_non_transient_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ProviderError) as excinfo:
        await _drive(monkeypatch, [], raise_on_create=_status_error(openai.BadRequestError, 400))
    assert not isinstance(excinfo.value, ProviderTransientError)
    assert "BadRequestError" in str(excinfo.value)
    assert "the query" not in str(excinfo.value)


# --- the other adapters are untouched ----------------------------------------


async def test_gemini_still_refuses_conversations() -> None:
    store = InMemorySecretStore()
    await store.put("google_api_key", "k")
    conversation = ToolConversation(system="s", messages=(Turn(role="user", text="hi"),))
    with pytest.raises(ToolCallingUnsupportedError):
        async for _ in GeminiAdapter(store).stream(
            "m", "hi", max_tokens=8, conversation=conversation
        ):
            pass


# --- provider tool-name cap (OpenAI: ^[a-zA-Z0-9_-]{1,64}$) --------------------


def _cap_descriptor(name: str) -> ToolDescriptor:
    return ToolDescriptor(
        name=name,
        description="d",
        params={"type": "object", "properties": {}},
        returns={"type": "object"},
    )


def test_long_dotted_names_fit_the_openai_cap_and_resolve_back() -> None:
    long_a = "onshape." + "a" * 62  # 70 chars
    long_b = "onshape." + "a" * 61 + "b"  # collides with long_a after truncation
    descriptors = [_cap_descriptor(long_a), _cap_descriptor(long_b), _cap_descriptor("get_entity")]
    offered = provider_tool_names(descriptors)
    assert len(set(offered.values())) == 3
    for real, safe in offered.items():
        assert 1 <= len(safe) <= 64, safe
        assert "." not in safe
        assert resolve_tool_name(safe, descriptors) == real
    assert all(len(spec.name) <= 64 for spec in tool_specs(descriptors))
    assert provider_tool_names(descriptors) == offered  # deterministic


def test_a_user_turn_with_images_becomes_input_image_then_input_text() -> None:
    """SOLUSDEV-252 S3 (sol-window.md §8.2): the screenshot rides the live user
    Turn; on the wire it is the same shape the text-only images path uses."""
    image = ImageBlock(media_type="image/png", data=b"\x89PNGbytes")
    [item] = openai_input([Turn(role="user", text="what is this?", images=(image,))])
    assert item["role"] == "user"
    content = item["content"]
    assert content[0]["type"] == "input_image"
    url = content[0]["image_url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == image.data
    assert content[1] == {"type": "input_text", "text": "what is this?"}
    assert openai_input([Turn(role="user", text="hi")]) == [{"role": "user", "content": "hi"}]


@pytest.mark.parametrize("code", ["insufficient_quota", "rate_limit_exceeded"])
async def test_http_429_quota_and_retry_after_reach_adapter(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    error = openai.RateLimitError(
        "private prompt",
        response=httpx.Response(429, request=request, headers={"retry-after": "8"}),
        body={"code": code},
    )
    with pytest.raises(ProviderError) as failure:
        await _drive(monkeypatch, [], raise_on_create=error)
    assert isinstance(failure.value, ProviderTransientError) == (code == "rate_limit_exceeded")
    if isinstance(failure.value, ProviderTransientError):
        assert failure.value.retry_after_seconds == 8.0
    assert failure.value.__suppress_context__ and failure.value.__cause__ is None
    assert "private" not in str(failure.value)
