"""Provider tool-calling surface — SOLUS-RUN-01 phase 1.

Until now the gateway was text-only: `ProviderAdapter.stream()` took one string
and returned text, every adapter hard-coded a single user message with no system
prompt, and the repo contained no `tool_use` anywhere. SOL's tools were therefore
registered, gated, and unreachable by any turn.

**Tool calling follows the `ImageBlock` precedent exactly**: one optional
parameter on the existing `stream()`, provider-neutral shapes defined here, and
pure per-provider mappers beside `anthropic_content`. A separate
`complete_with_tools()` would duplicate the frequency cap, the spend gate, the
retry loop and the cost hook — and a duplicated gate is where a gate silently
goes missing.

Two properties matter more than the mechanics:

1. **`conversation=None` is byte-identical to today.** `fingerprint/escalation.py`
   and `visual.py` must not change behaviour at all.
2. **A provider that cannot do tool calling fails LOUDLY.** SOL routes
   `SOL_OPEN_QUESTION -> HARD -> general_hard -> claude-opus-4-8`, so only
   Anthropic implements this. Silently dropping the tools array would produce a
   model that *talks about* acting instead of acting — indistinguishable from it
   choosing not to.

No SDK is imported here; the mappers are pure, exactly as `anthropic_content`
and `gemini_contents` are tested today.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

import pytest
from solus_api.orchestration.providers import (
    ProviderError,
    ProviderTransientError,
    ToolCallingUnsupportedError,
    ToolConversation,
    ToolOutcome,
    ToolSpec,
    ToolUse,
    Turn,
    Usage,
    anthropic_messages,
    anthropic_tool_uses,
    anthropic_tools,
)

_TOOL = ToolSpec(
    name="onshape.get_variables",
    description="Variables in a Variable Studio.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)


class _FakeSecrets:
    async def get(self, name: str) -> str:
        return "key"


# ------------------------------------------------------------------ shapes


def test_a_tool_spec_carries_the_descriptors_schema_verbatim() -> None:
    """`ToolDescriptor.params` is already JSON Schema — nothing re-derives it,
    which is why a tool's `params` is now literally model-facing wire content."""
    assert _TOOL.input_schema["additionalProperties"] is False


def test_a_proposed_call_carries_no_way_to_execute_itself() -> None:
    """The model PROPOSES; Solus code decides and dispatches."""
    use = ToolUse(id="tu_1", name="onshape.set_variable", args={"name": "width"})

    assert use.args == {"name": "width"}
    assert not hasattr(use, "invoke")


def test_an_outcome_marks_failure_so_the_model_can_branch_on_it() -> None:
    assert ToolOutcome(id="tu_1", content="{}", is_error=True).is_error is True
    assert ToolOutcome(id="tu_1", content="{}").is_error is False


# ------------------------------------------- unsupported providers fail loud


def test_the_refusal_is_in_the_provider_error_taxonomy() -> None:
    """The gateway classifies provider failures; an unsupported provider must
    land in that taxonomy rather than escaping as an unclassified crash."""
    assert issubclass(ToolCallingUnsupportedError, ProviderError)


def test_the_refusal_is_not_retryable() -> None:
    """MO-03 backoff retries `ProviderTransientError` only. Retrying a provider
    that structurally cannot do tool calling would burn the whole budget on a
    failure that can never succeed."""
    assert not issubclass(ToolCallingUnsupportedError, ProviderTransientError)


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_a_provider_without_tool_calling_refuses(provider: str) -> None:
    from solus_api.orchestration.providers import GeminiAdapter, OpenAIAdapter

    adapter = (
        OpenAIAdapter(_FakeSecrets())  # type: ignore[arg-type]
        if provider == "openai"
        else GeminiAdapter(_FakeSecrets())  # type: ignore[arg-type]
    )
    conversation = ToolConversation(
        system="s", messages=(Turn(role="user", text="hi"),), tools=(_TOOL,)
    )

    with pytest.raises(ToolCallingUnsupportedError):
        async for _ in adapter.stream("some-model", "hi", max_tokens=64, conversation=conversation):
            pass


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_a_conversation_without_tools_is_still_refused(provider: str) -> None:
    """A multi-turn conversation is just as unsupported as a tool array — these
    adapters send exactly one user message. Accepting the turns and dropping all
    but the last would silently lose the conversation."""
    from solus_api.orchestration.providers import GeminiAdapter, OpenAIAdapter

    adapter = (
        OpenAIAdapter(_FakeSecrets())  # type: ignore[arg-type]
        if provider == "openai"
        else GeminiAdapter(_FakeSecrets())  # type: ignore[arg-type]
    )

    with pytest.raises(ToolCallingUnsupportedError):
        async for _ in adapter.stream(
            "some-model",
            "hi",
            max_tokens=64,
            conversation=ToolConversation(system="s", messages=(), tools=()),
        ):
            pass


# ---------------------------------------------------- anthropic tool mapping


def test_tools_map_to_the_wire_shape_with_the_schema_passed_through() -> None:
    (wire,) = anthropic_tools((_TOOL,))

    assert wire["name"] == "onshape.get_variables"
    assert wire["input_schema"] == _TOOL.input_schema


def test_no_tools_maps_to_an_empty_list_not_a_missing_key() -> None:
    assert anthropic_tools(()) == []


def test_an_assistant_turn_carries_text_and_tool_uses() -> None:
    turn = Turn(
        role="assistant",
        text="Let me look.",
        tool_uses=(ToolUse(id="tu_1", name="t", args={"a": 1}),),
    )

    (wire,) = anthropic_messages((turn,))

    assert wire["role"] == "assistant"
    blocks = cast("list[dict[str, object]]", wire["content"])
    assert blocks[0] == {"type": "text", "text": "Let me look."}
    assert blocks[1] == {"type": "tool_use", "id": "tu_1", "name": "t", "input": {"a": 1}}


def test_an_assistant_turn_with_no_text_emits_no_empty_text_block() -> None:
    """An empty text block is rejected by the API; a model that goes straight to
    a tool call is the common case, not an edge case."""
    turn = Turn(role="assistant", text="", tool_uses=(ToolUse(id="tu_1", name="t", args={}),))

    (wire,) = anthropic_messages((turn,))

    blocks = cast("list[dict[str, object]]", wire["content"])
    assert all(block["type"] != "text" for block in blocks)


def test_tool_results_go_back_as_one_user_turn() -> None:
    """All results of a round travel in ONE user turn. Splitting parallel results
    across several messages teaches the model to stop making parallel calls."""
    turn = Turn(
        role="user",
        tool_results=(
            ToolOutcome(id="tu_1", content='{"ok":true}'),
            ToolOutcome(id="tu_2", content='{"ok":false}', is_error=True),
        ),
    )

    (wire,) = anthropic_messages((turn,))

    assert wire["role"] == "user"
    blocks = cast("list[dict[str, object]]", wire["content"])
    assert len(blocks) == 2
    assert blocks[0] == {
        "type": "tool_result",
        "tool_use_id": "tu_1",
        "content": '{"ok":true}',
        "is_error": False,
    }
    assert blocks[1]["is_error"] is True


def test_a_plain_user_turn_is_plain_text() -> None:
    (wire,) = anthropic_messages((Turn(role="user", text="what is this?"),))

    assert wire == {"role": "user", "content": "what is this?"}


# -------------------------------------------------- parsing the model's reply


class _Block:
    def __init__(self, **kw: object) -> None:
        for key, value in kw.items():
            setattr(self, key, value)


def test_a_text_only_reply_proposes_nothing() -> None:
    assert anthropic_tool_uses([_Block(type="text", text="hello")]) == ()


def test_tool_use_blocks_become_proposed_calls() -> None:
    blocks = [
        _Block(type="text", text="Let me look."),
        _Block(
            type="tool_use", id="tu_1", name="onshape.get_variables", input={"document_id": "d1"}
        ),
    ]

    uses = anthropic_tool_uses(blocks)

    assert [u.name for u in uses] == ["onshape.get_variables"]
    assert uses[0].args == {"document_id": "d1"}
    assert uses[0].id == "tu_1"


def test_several_tool_uses_in_one_reply_are_all_returned() -> None:
    """Parallel tool calls are the point — one round, several reads."""
    blocks = [
        _Block(type="tool_use", id="a", name="t1", input={}),
        _Block(type="tool_use", id="b", name="t2", input={}),
    ]

    assert len(anthropic_tool_uses(blocks)) == 2


def test_an_unknown_block_type_is_ignored_rather_than_crashing() -> None:
    """Provider output is untrusted and providers add block types. An unknown one
    must not break a turn that is otherwise fine."""
    blocks = [_Block(type="thinking", thinking="..."), _Block(type="tool_use", id="a", name="t")]

    assert len(anthropic_tool_uses(blocks)) == 1


def test_a_tool_use_with_non_object_input_is_dropped() -> None:
    """Args must be a mapping before they reach the registry's schema validation.
    A provider returning a scalar is malformed, not an invitation to guess."""
    assert anthropic_tool_uses([_Block(type="tool_use", id="a", name="t", input="oops")]) == ()


def test_a_tool_use_with_a_non_string_name_is_dropped() -> None:
    assert anthropic_tool_uses([_Block(type="tool_use", id="a", name=123, input={})]) == ()


def test_usage_is_unchanged_by_tool_calling() -> None:
    """The cost hook's input shape is untouched — a tool round bills like any
    other call."""
    assert Usage(tokens_in=10, tokens_out=3).tokens_in == 10


# ------------------------------------------------- through the real gateway
#
# These use the REAL gateway — its gates, retry policy, cost hook and Completion
# assembly — and fake only the network. A tool loop that bypassed the gateway
# would be an unmetered, unlimited model path, so it must be provably the same
# code path as every other call.


class _ToolAdapter:
    """Yields text, then a tool call, then usage — the adapter contract."""

    def __init__(self, *uses: ToolUse) -> None:
        self.uses = uses
        self.seen: ToolConversation | None = None

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: object = None,
        conversation: ToolConversation | None = None,
    ) -> AsyncIterator[str | ToolUse | Usage]:
        self.seen = conversation
        yield "Let me "
        yield "look."
        for use in self.uses:
            yield use
        yield Usage(tokens_in=11, tokens_out=4)


async def test_a_proposed_call_survives_the_gateway_without_leaking_into_text() -> None:
    """`CompletionStream` is typed `AsyncIterator[str]` and every existing
    consumer treats what it yields as text — a tool call must never arrive as a
    text chunk."""
    from solus_api.connectors.secrets import InMemorySecretStore
    from solus_api.orchestration.gateway import complete

    adapter = _ToolAdapter(ToolUse(id="tu_1", name="onshape.get_variables", args={"d": "1"}))

    result = await complete(
        "what variables?",
        secret_store=InMemorySecretStore(),
        adapters={"anthropic": adapter, "openai": adapter, "google": adapter},
        conversation=ToolConversation(system="You are SOL.", tools=(_TOOL,)),
    )

    assert result.text == "Let me look."
    assert [c.name for c in result.tool_calls] == ["onshape.get_variables"]
    assert result.tokens_in == 11


async def test_a_text_only_call_reports_no_tool_calls() -> None:
    """Every existing caller reads `.text` and never looks at `.tool_calls`."""
    from solus_api.connectors.secrets import InMemorySecretStore
    from solus_api.orchestration.gateway import complete

    adapter = _ToolAdapter()

    result = await complete(
        "hello", secret_store=InMemorySecretStore(), adapters={"anthropic": adapter}
    )

    assert result.tool_calls == ()
    assert adapter.seen is None


async def test_the_conversation_reaches_the_adapter_intact() -> None:
    from solus_api.connectors.secrets import InMemorySecretStore
    from solus_api.orchestration.gateway import complete

    adapter = _ToolAdapter()
    conversation = ToolConversation(
        system="You are SOL.", messages=(Turn(role="user", text="hi"),), tools=(_TOOL,)
    )

    await complete(
        "hi",
        secret_store=InMemorySecretStore(),
        adapters={"anthropic": adapter},
        conversation=conversation,
    )

    assert adapter.seen == conversation
