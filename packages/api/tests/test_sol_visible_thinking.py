"""SOLUSDEV-326: SOL's thinking, visible.

Providers stream their thought summaries as `Thinking` items (Anthropic adaptive thinking with
`display: "summarized"`, OpenAI Responses reasoning summaries), only when the gateway caller asks
AND the catalog entry allows it. The gateway's text iteration never sees them; `events()` does.
The runtime turns them into masked, bounded `thinking` frames, and the route stores them on the
assistant turn. Fake SDKs, zero network.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from types import SimpleNamespace
from typing import Any

import pytest
from solus_api.agent import runtime
from solus_api.agent.stream import (
    THINKING_CHUNK_CAP,
    THINKING_TURN_CAP,
    AgentEvent,
    AgentEventType,
)
from solus_api.agent.thinking import ThinkingRelay
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.orchestration import gateway
from solus_api.orchestration.config import (
    CostConfig,
    ModelCatalogEntry,
    OrchestrationConfig,
)
from solus_api.orchestration.providers import (
    ANTHROPIC_API_KEY_NAME,
    OPENAI_API_KEY_NAME,
    AnthropicAdapter,
    ImageBlock,
    OpenAIAdapter,
    Thinking,
    ToolConversation,
    ToolUse,
    Turn,
    Usage,
    anthropic_messages,
)
from solus_api.routers.sol import _TurnTranscript

_SECRET = "sk-ant-api03-" + "A" * 40

# --- Anthropic ----------------------------------------------------------------


class _SdkBlock(SimpleNamespace):
    def model_dump(self, **_: Any) -> dict[str, Any]:
        return dict(vars(self))


class _AnthropicFinal:
    def __init__(self, content: list[object]) -> None:
        self.content = content
        self.usage = SimpleNamespace(input_tokens=5, output_tokens=8)
        self.stop_reason = "end_turn"
        self.stop_details = None


class _AnthropicStream:
    def __init__(self, events: Sequence[object], content: list[object]) -> None:
        self._events = events
        self._content = content

    async def __aenter__(self) -> _AnthropicStream:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def _replay(self) -> AsyncIterator[object]:
        for event in self._events:
            yield event

    def __aiter__(self) -> AsyncIterator[object]:
        return self._replay()

    @property
    def text_stream(self) -> AsyncIterator[str]:
        async def chunks() -> AsyncIterator[str]:
            yield "plain"

        return chunks()

    async def get_final_message(self) -> _AnthropicFinal:
        return _AnthropicFinal(self._content)


def _thinking_anthropic_cls(
    record: dict[str, Any], events: Sequence[object], content: list[object]
) -> type:
    class Messages:
        def stream(self, **kwargs: Any) -> _AnthropicStream:
            record.update(kwargs)
            return _AnthropicStream(events, content)

    class Client:
        def __init__(self, **_: Any) -> None:
            self.messages = Messages()

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return Client


def _anthropic_delta(kind: str, **fields: str) -> SimpleNamespace:
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type=kind, **fields))


_THINKING_BLOCK = _SdkBlock(type="thinking", thinking="Check the bus.", signature="sig-1")
_TEXT_BLOCK = _SdkBlock(type="text", text="Done.")


async def _drive_anthropic(
    monkeypatch: pytest.MonkeyPatch, *, show_thinking: bool
) -> tuple[dict[str, Any], list[str | Thinking | ToolUse | Usage]]:
    record: dict[str, Any] = {}
    events = [
        SimpleNamespace(type="message_start"),
        _anthropic_delta("thinking_delta", thinking="Check "),
        _anthropic_delta("thinking_delta", thinking="the bus."),
        _anthropic_delta("signature_delta", signature="sig-1"),
        _anthropic_delta("text_delta", text="Done."),
    ]
    monkeypatch.setattr(
        "anthropic.AsyncAnthropic",
        _thinking_anthropic_cls(record, events, [_THINKING_BLOCK, _TEXT_BLOCK]),
    )
    store = InMemorySecretStore()
    await store.put(ANTHROPIC_API_KEY_NAME, "test-key")
    conversation = ToolConversation(system="sys", messages=(Turn(role="user", text="hi"),))
    kwargs: dict[str, Any] = {"show_thinking": True} if show_thinking else {}
    items = [
        item
        async for item in AnthropicAdapter(store).stream(
            "claude-sonnet-5", "hi", max_tokens=64, conversation=conversation, **kwargs
        )
    ]
    return record, items


async def test_anthropic_streams_summarized_thinking_then_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, items = await _drive_anthropic(monkeypatch, show_thinking=True)

    assert record["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert items[:3] == [Thinking("Check "), Thinking("the bus."), "Done."]
    usage = items[-1]
    assert isinstance(usage, Usage)
    # The whole assistant content rides to the next round: thinking blocks come back unchanged.
    assert usage.provider_items == (
        {"type": "thinking", "thinking": "Check the bus.", "signature": "sig-1"},
        {"type": "text", "text": "Done."},
    )


async def test_anthropic_without_show_thinking_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, items = await _drive_anthropic(monkeypatch, show_thinking=False)

    assert "thinking" not in record
    assert items[0] == "plain"
    assert not any(isinstance(item, Thinking) for item in items)
    assert isinstance(items[-1], Usage) and items[-1].provider_items == ()


def test_anthropic_messages_replay_provider_items_verbatim() -> None:
    items = (
        {"type": "thinking", "thinking": "Check the bus.", "signature": "sig-1"},
        {"type": "tool_use", "id": "t1", "name": "get_entity", "input": {"id": "U3"}},
    )
    turns = (
        Turn(role="user", text="hi"),
        Turn(
            role="assistant",
            tool_uses=(ToolUse(id="t1", name="get_entity", args={"id": "U3"}),),
            provider_items=items,
            cache_breakpoint=True,
        ),
    )

    messages = anthropic_messages(turns)

    assert messages[1]["content"] == [
        items[0],
        {**items[1], "cache_control": {"type": "ephemeral"}},
    ]


def test_anthropic_messages_ignore_foreign_provider_items() -> None:
    # An OpenAI replay item is not an Anthropic block: the turn is re-synthesised as before.
    turn = Turn(
        role="assistant",
        tool_uses=(ToolUse(id="t1", name="x", args={}),),
        provider_items=({"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque"},),
    )

    assert anthropic_messages((turn,))[0]["content"] == [
        {"type": "tool_use", "id": "t1", "name": "x", "input": {}}
    ]


# --- OpenAI -------------------------------------------------------------------


def _thinking_openai_cls(record: dict[str, Any], script: Sequence[object]) -> type:
    async def replay() -> AsyncIterator[object]:
        for event in script:
            yield event

    class Responses:
        async def create(self, **kwargs: Any) -> AsyncIterator[object]:
            record.update(kwargs)
            return replay()

    class Client:
        def __init__(self, **_: Any) -> None:
            self.responses = Responses()

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return Client


def _openai_done_event() -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=3, output_tokens=4, input_tokens_details=None)
    return SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage))


async def _drive_openai(
    monkeypatch: pytest.MonkeyPatch, *, show_thinking: bool, effort: str | None = "medium"
) -> tuple[dict[str, Any], list[str | Thinking | ToolUse | Usage]]:
    record: dict[str, Any] = {}
    script = [
        SimpleNamespace(type="response.reasoning_summary_part.added", summary_index=0),
        SimpleNamespace(type="response.reasoning_summary_text.delta", delta="Look at "),
        SimpleNamespace(type="response.reasoning_summary_text.delta", delta="pins."),
        SimpleNamespace(type="response.reasoning_summary_part.added", summary_index=1),
        SimpleNamespace(type="response.reasoning_summary_text.delta", delta="Then answer."),
        SimpleNamespace(type="response.output_text.delta", delta="Answer"),
        _openai_done_event(),
    ]
    monkeypatch.setattr("openai.AsyncOpenAI", _thinking_openai_cls(record, script))
    store = InMemorySecretStore()
    await store.put(OPENAI_API_KEY_NAME, "test-key")
    kwargs: dict[str, Any] = {"show_thinking": True} if show_thinking else {}
    items = [
        item
        async for item in OpenAIAdapter(store).stream(
            "gpt-5.6-sol", "hi", max_tokens=64, reasoning_effort=effort, **kwargs
        )
    ]
    return record, items


async def test_openai_requests_and_streams_reasoning_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, items = await _drive_openai(monkeypatch, show_thinking=True)

    assert record["reasoning"] == {"effort": "medium", "summary": "auto"}
    # A second summary part starts a new paragraph; the first does not.
    assert items[:5] == [
        Thinking("Look at "),
        Thinking("pins."),
        Thinking("\n\n"),
        Thinking("Then answer."),
        "Answer",
    ]


async def test_openai_without_show_thinking_drops_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, items = await _drive_openai(monkeypatch, show_thinking=False)

    assert record["reasoning"] == {"effort": "medium"}
    assert items[0] == "Answer"


async def test_openai_without_effort_asks_for_no_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    record, _ = await _drive_openai(monkeypatch, show_thinking=True, effort=None)

    assert "reasoning" not in record


# --- gateway ------------------------------------------------------------------


class _ThinkingAdapter:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Sequence[ImageBlock] | None = None,
        conversation: ToolConversation | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str | Thinking | ToolUse | Usage]:
        self.kwargs = kwargs
        yield Thinking("hmm ")
        yield "Hel"
        yield Thinking("ok")
        yield "lo"
        yield Usage(tokens_in=1, tokens_out=2)


def _thinking_config(*, show_thinking: bool) -> OrchestrationConfig:
    return OrchestrationConfig(
        version=1,
        catalog=[
            ModelCatalogEntry(
                provider="fake",
                name="m",
                price_in=1.0,
                price_out=2.0,
                context_window=100_000,
                roles=["only_role"],
                show_thinking=show_thinking,
            )
        ],
        matrix={},
        default_role="only_role",
        cost=CostConfig(credits_per_dollar=100.0),
    )


def _thinking_stream(
    adapter: _ThinkingAdapter, *, entry: bool, ask: bool
) -> gateway.CompletionStream:
    return gateway.stream(
        "q",
        secret_store=InMemorySecretStore(),
        config=_thinking_config(show_thinking=entry),
        adapters={"fake": adapter},
        purpose="answer",
        show_thinking=ask,
    )


async def test_text_iteration_never_sees_thinking() -> None:
    stream = _thinking_stream(_ThinkingAdapter(), entry=True, ask=True)

    assert [chunk async for chunk in stream] == ["Hel", "lo"]
    assert stream.completion is not None and stream.completion.text == "Hello"


async def test_events_yield_thinking_and_text_in_order() -> None:
    stream = _thinking_stream(_ThinkingAdapter(), entry=True, ask=True)

    assert [e async for e in stream.events()] == [
        Thinking("hmm "),
        "Hel",
        Thinking("ok"),
        "lo",
    ]
    assert stream.completion is not None and stream.completion.text == "Hello"


@pytest.mark.parametrize(
    ("entry", "ask", "passed"),
    [(True, True, True), (True, False, False), (False, True, False)],
)
async def test_show_thinking_needs_both_caller_and_catalog(
    entry: bool, ask: bool, passed: bool
) -> None:
    adapter = _ThinkingAdapter()
    stream = _thinking_stream(adapter, entry=entry, ask=ask)
    _ = [chunk async for chunk in stream]

    assert ("show_thinking" in adapter.kwargs) is passed


def test_catalog_shows_thinking_except_on_trivial_claude() -> None:
    config = gateway._default_orchestration_config()
    shown = {entry.name: entry.show_thinking for entry in config.catalog}

    assert shown["claude-haiku-4-5"] is False
    assert shown["claude-sonnet-5"] is True
    assert shown["claude-fable-5-1"] is True
    assert shown["gpt-6-astra"] is True
    assert shown["gpt-5.6-sol"] is True


# --- the frame and the relay --------------------------------------------------


def test_thinking_frame_masks_and_caps() -> None:
    event = AgentEvent.thinking(f"key {_SECRET} " + "x" * (THINKING_CHUNK_CAP * 2))

    assert event.type is AgentEventType.THINKING
    assert _SECRET not in event.data["text"]
    assert len(event.data["text"]) <= THINKING_CHUNK_CAP


def _joined_text(events: Sequence[AgentEvent]) -> str:
    return "".join(e.data["text"] for e in events)


# --- the runtime round --------------------------------------------------------


class _EventsOnlyStream:
    def __init__(self, items: Sequence[str | Thinking]) -> None:
        self._items = items

    def __aiter__(self) -> AsyncIterator[str]:
        raise AssertionError("the round must read events(), not text only")

    async def events(self) -> AsyncIterator[str | Thinking]:
        for item in self._items:
            yield item


async def test_round_events_stream_thinking_before_tokens() -> None:
    ctx = SimpleNamespace(turn_id=uuid.uuid4(), user_id=uuid.uuid4(), project_id=uuid.uuid4())
    relay = ThinkingRelay()
    stream = _EventsOnlyStream([Thinking("I should check the I2C bus. "), "The ", "answer."])

    events = [e async for e in runtime._round_events(stream, None, ctx, relay)]  # type: ignore[arg-type]

    kinds = [e.type for e in events]
    assert kinds[0] is AgentEventType.THINKING
    assert AgentEventType.TOKEN in kinds
    assert kinds.index(AgentEventType.THINKING) < kinds.index(AgentEventType.TOKEN)
    thought = _joined_text([e for e in events if e.type is AgentEventType.THINKING])
    assert thought.startswith("I should")


async def test_round_events_flush_held_thinking_when_text_starts() -> None:
    ctx = SimpleNamespace(turn_id=None, user_id=None, project_id=None)
    relay = ThinkingRelay()
    stream = _EventsOnlyStream([Thinking("no sentence end"), "Answer"])

    events = [e async for e in runtime._round_events(stream, None, ctx, relay)]  # type: ignore[arg-type]

    assert [e.type for e in events] == [AgentEventType.THINKING, AgentEventType.TOKEN]
    assert events[0].data["text"] == "no sentence end"


# --- persistence --------------------------------------------------------------


def _tool_call_frame(call_id: str) -> AgentEvent:
    return AgentEvent(
        type=AgentEventType.TOOL_CALL, data={"call_id": call_id, "tool": "t", "args": {}}
    )


def test_transcript_keeps_thinking_segments_split_by_tool_calls() -> None:
    transcript = _TurnTranscript()
    for event in [
        AgentEvent.thinking("First "),
        AgentEvent.thinking("thought."),
        _tool_call_frame("c1"),
        AgentEvent.thinking("Second thought."),
        AgentEvent.token("Answer"),
    ]:
        transcript.record(event, max_tool_calls=10)

    attrs = transcript.thinking_attrs()

    assert attrs is not None
    assert attrs["segments"] == ["First thought.", "Second thought."]
    # Each segment's place among the steps, so a reload interleaves like the live turn.
    assert attrs["after"] == [0, 1]
    assert isinstance(attrs["ms"], int) and attrs["ms"] >= 0


def test_transcript_duration_leaves_out_the_time_between_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([0.0, 2.0, 50.0, 51.5])
    monkeypatch.setattr("solus_api.routers.sol.time.monotonic", lambda: next(clock))
    transcript = _TurnTranscript()
    for event in [
        AgentEvent.thinking("One "),  # t=0
        AgentEvent.thinking("two."),  # t=2   → 2s
        _tool_call_frame("c1"),  # a 48-second tool run is not thinking
        AgentEvent.thinking("Three "),  # t=50
        AgentEvent.thinking("four."),  # t=51.5 → 1.5s
    ]:
        transcript.record(event, max_tool_calls=10)

    attrs = transcript.thinking_attrs()

    assert attrs is not None and attrs["ms"] == 3_500


def test_persisted_thinking_is_masked_whole() -> None:
    transcript = _TurnTranscript()
    for event in [AgentEvent.thinking("The db password: "), AgentEvent.thinking("hunter2 here.")]:
        transcript.record(event, max_tool_calls=10)

    attrs = transcript.thinking_attrs()

    assert attrs is not None
    assert "hunter2" not in attrs["segments"][0]


def test_transcript_caps_thinking_at_the_turn_cap() -> None:
    transcript = _TurnTranscript()
    for _ in range(40):
        transcript.record(AgentEvent.thinking("x" * 1_000), max_tool_calls=10)

    attrs = transcript.thinking_attrs()

    assert attrs is not None
    assert sum(len(s) for s in attrs["segments"]) <= THINKING_TURN_CAP


def test_transcript_without_thinking_stores_nothing() -> None:
    transcript = _TurnTranscript()
    transcript.record(AgentEvent.token("Answer"), max_tool_calls=10)

    assert transcript.thinking_attrs() is None
