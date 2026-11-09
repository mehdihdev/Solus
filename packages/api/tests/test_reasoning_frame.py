"""SOLUSDEV-321 P7 — the `<reasoning>` block SOL writes before it proposes a change.

The block is model output, so it is parsed out of the text and never shown as text. The parser is
driven here over every way of cutting a reply into chunks (no DB); then one Build turn runs through
the REAL gateway with a scripted model — only the network is faked — whose block is split across
chunks ahead of a tool call.
"""

from __future__ import annotations

import json
import string
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from typing import Any

from solus_api.agent.citations import PROPOSAL_ONLY_REPLY
from solus_api.agent.confirmations import ParkedCall, _parked_message
from solus_api.agent.modes import ActionMode
from solus_api.agent.reasoning_frame import REASONING_BLOCK_CAP, ReasoningParser, strip_reasoning
from solus_api.agent.runtime import LlmRunner, build_dispatch
from solus_api.agent.stream import AgentEvent, AgentEventType
from solus_api.agent.tools import (
    InProcessTool,
    ToolCall,
    ToolDescriptor,
    ToolError,
    ToolErrorCode,
    ToolRegistry,
    ToolResult,
)
from solus_api.orchestration.providers import ToolConversation, ToolUse, Usage
from sqlalchemy.ext.asyncio import AsyncEngine
from test_sol_reasoner import _ctx

_BLOCK: dict[str, Any] = {
    "considered": ["raise the lid 2 mm", "move the USB-C port"],
    "ruled_out": [{"what": "a thinner wall", "why": "under the 1.2 mm print minimum"}],
    "proposing": "Set WIDTH to 120 mm so the port clears the casing.",
}
_REPLY = f"Checking the casing.\n<reasoning>{json.dumps(_BLOCK)}</reasoning>\nSetting the width."
_PROSE = "Checking the casing.\n\nSetting the width."


def _parsed_events(chunks: Sequence[str]) -> list[AgentEvent]:
    """Every frame the parser makes from `chunks`, the end of the text included."""
    parser = ReasoningParser()
    events = [event for chunk in chunks for event in parser.feed(chunk)]
    return [*events, *parser.flush()]


def _token_text(events: Sequence[AgentEvent]) -> str:
    return "".join(e.data["text"] for e in events if e.type is AgentEventType.TOKEN)


def _reasoning_frames(events: Sequence[AgentEvent]) -> list[dict[str, Any]]:
    return [e.data for e in events if e.type is AgentEventType.REASONING]


def test_shape_enforced_and_malformed_dropped() -> None:
    """A block with the exact shape becomes one frame; any other body — not JSON, another shape,
    a key too many or too few, a value of the wrong type, past a bound, past the block cap, or a
    second block — is dropped, and none of it streams. The prose around it always does."""
    events = _parsed_events([_REPLY])
    assert _reasoning_frames(events) == [_BLOCK]
    assert _token_text(events) == _PROSE

    malformed = (
        "{not json",
        "[]",
        '"just a sentence"',
        json.dumps({**_BLOCK, "confidence": 0.9}),
        json.dumps({k: v for k, v in _BLOCK.items() if k != "proposing"}),
        json.dumps({**_BLOCK, "considered": "one string"}),
        json.dumps({**_BLOCK, "considered": [7]}),
        json.dumps({**_BLOCK, "ruled_out": [{"what": "a thinner wall"}]}),
        json.dumps({**_BLOCK, "ruled_out": ["a thinner wall"]}),
        json.dumps({**_BLOCK, "considered": ["x"] * 13}),
        json.dumps({**_BLOCK, "ruled_out": [{"what": "x", "why": "y"}] * 13}),
        json.dumps({**_BLOCK, "considered": ["x" * 201]}),
        json.dumps({**_BLOCK, "proposing": "x" * 401}),
        "[" * 3000 + "]" * 1000,
    )
    for body in malformed:
        events = _parsed_events([f"Before. <reasoning>{body}</reasoning>After."])
        assert _reasoning_frames(events) == [], body[:60]
        assert _token_text(events) == "Before. After.", body[:60]

    # At the bounds is well formed: twelve entries of 200 characters, 400 for the proposal.
    full = {
        "considered": ["c" * 200] * 12,
        "ruled_out": [{"what": "w" * 200, "why": "y" * 200}],
        "proposing": "p" * 400,
    }
    assert _reasoning_frames(_parsed_events([f"<reasoning>{json.dumps(full)}</reasoning>"])) == [
        full
    ]

    # Past the block cap it is dropped, though its JSON is well formed.
    padded = json.dumps(_BLOCK) + " " * REASONING_BLOCK_CAP
    events = _parsed_events([f"Before. <reasoning>{padded}</reasoning>After."])
    assert _reasoning_frames(events) == [] and _token_text(events) == "Before. After."

    # One block a reply: a second is taken out of the text and dropped, whatever it holds.
    other = json.dumps({**_BLOCK, "proposing": "something else"})
    events = _parsed_events([f"{_REPLY}<reasoning>{other}</reasoning>!"])
    assert _reasoning_frames(events) == [_BLOCK] and _token_text(events) == f"{_PROSE}!"


def test_the_frame_masks_model_text_and_cuts_after_masking() -> None:
    """Model text crosses to the desktop: each string is masked token by token, then cut to its
    bound — masking can grow a value (`token=ab` becomes `token=[REDACTED]`)."""
    entropic = string.ascii_letters + string.digits  # 62 distinct characters, one token
    block = {
        **_BLOCK,
        "considered": [f"token=abc123 then {entropic}"],
        "proposing": "x" * 385 + " token=ab",
    }
    (frame,) = _reasoning_frames(_parsed_events([f"<reasoning>{json.dumps(block)}</reasoning>"]))
    assert frame["considered"] == ["token=[REDACTED] then [REDACTED]"]
    assert len(frame["proposing"]) == 400
    assert frame["proposing"].startswith("x" * 385 + " token=[RED")


def test_block_never_streams_as_tokens() -> None:
    """However the reply is cut into chunks — at every offset, and one character at a time — the
    block arrives as one frame and no part of it as text; the tags match in any ASCII case."""
    cuts = [[_REPLY[:i], _REPLY[i:]] for i in range(len(_REPLY) + 1)]
    for chunks in [*cuts, list(_REPLY)]:
        events = _parsed_events(chunks)
        assert _reasoning_frames(events) == [_BLOCK]
        assert _token_text(events) == _PROSE
        for event in events:
            if event.type is AgentEventType.TOKEN:
                text = event.data["text"]
                assert "<" not in text and "considered" not in text and "}" not in text

    shouting = _REPLY.replace("<reasoning>", "<REASONING>").replace("</reasoning>", "</Reasoning>")
    assert _reasoning_frames(_parsed_events([shouting])) == [_BLOCK]
    # A `<` that starts no tag is held only until the text shows it, then streams as written.
    assert _token_text(_parsed_events(["x <", "re", "d> y <reas"])) == "x <red> y <reas"
    # The closing message is cut the same way the tokens were.
    assert strip_reasoning(_REPLY) == _PROSE


def test_unterminated_block_dropped() -> None:
    """A block still open when the text ends is dropped, never streamed — and however long it runs,
    the parser holds no more than the block cap and a closing tag's length of it."""
    parser = ReasoningParser()
    events = parser.feed('Done. <reasoning>{"considered": [')
    for _ in range(2_000):
        events += parser.feed('"one more thought", ')
        assert len(parser._body or "") < REASONING_BLOCK_CAP + len("</reasoning>")
    events += parser.flush()
    assert _token_text(events) == "Done. " and _reasoning_frames(events) == []
    assert strip_reasoning('Done. <reasoning>{"considered": ["half') == "Done. "


def test_prose_quoting_the_tag_streams_back_as_written() -> None:
    """P7 fix 1 (M3): a `<reasoning>` that never closes, whose body never ran past the cap, holds
    no `{` and does not open (after whitespace) with `[`, was prose quoting the tag — Guide
    explaining the format, say — so at the end of the text it streams back exactly as written
    instead of truncating the round, a citation in it included. Any other open body is JSON however
    it starts — bare, behind a code fence, or an array (P7 fix 2, N1) — and is dropped, and so is
    one past the cap."""
    text = "Wrap your notes in a <Reasoning> tag [solus:documentation:d1], then carry on."
    for chunks in ([text], list(text), [text[:30], text[30:]]):
        events = _parsed_events(chunks)
        assert _token_text(events) == text and _reasoning_frames(events) == []
    assert strip_reasoning(text) == text
    for body in (
        '\n  {"considered": ["half',
        '```json\n{"considered": ["half',
        '[{"what": "a thinner wall"',
        '\n["raise the lid", "move the port"]',
    ):
        assert strip_reasoning(f"Done. <reasoning>{body}") == "Done. ", body
    assert strip_reasoning("Note <reasoning> " + "word " * REASONING_BLOCK_CAP) == "Note "


class _ScriptedProposal:
    """Round 1: prose, then the block cut across four chunks, then a read call. Round 2: a block
    that is not JSON, then the closing prose."""

    def __init__(self) -> None:
        self.seen: list[ToolConversation] = []

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        conversation: ToolConversation | None = None,
        **_: Any,
    ) -> AsyncIterator[str | ToolUse | Usage]:
        if conversation is not None:
            self.seen.append(conversation)
        if len(self.seen) == 1:
            block = json.dumps(_BLOCK)
            yield "Checking the casing.\n<reas"
            yield f"oning>{block[:40]}"
            yield f"{block[40:]}</reaso"
            yield "ning>"
            yield ToolUse(id="tu_1", name="onshape__get_variables", args={"d": "x"})
            yield Usage(tokens_in=5, tokens_out=2)
            return
        yield "<reasoning>{not json</reasoning>The width is set."
        yield Usage(tokens_in=5, tokens_out=2)


async def test_a_turn_streams_the_block_as_one_frame_ahead_of_its_call(engine: AsyncEngine) -> None:
    """The REAL runner: the round's block is one `reasoning` frame before the call it precedes, no
    `token` or `message` carries any of it, and the next round's malformed block is dropped while
    its prose still closes the turn."""
    ctx = await _ctx(engine, "make the casing clear the port", action_mode=ActionMode.DO)
    model = _ScriptedProposal()
    adapters = {name: model for name in ("anthropic", "openai", "google")}
    events = [event async for event in LlmRunner(adapters=adapters).run(ctx)]

    kinds = [event.type for event in events]
    assert kinds.count(AgentEventType.REASONING) == 1
    assert kinds.index(AgentEventType.REASONING) < kinds.index(AgentEventType.TOOL_CALL)
    assert _reasoning_frames(events) == [_BLOCK]
    shown = [
        str(event.data.get("text") or event.data.get("content") or "")
        for event in events
        if event.type in (AgentEventType.TOKEN, AgentEventType.MESSAGE)
    ]
    assert not any("reasoning" in text or "considered" in text for text in shown)
    assert _token_text(events) == "Checking the casing.\nThe width is set."
    assert events[-1].type is AgentEventType.MESSAGE
    assert events[-1].data["content"] == "The width is set."


_WRITE = ToolDescriptor(
    name="onshape.set_variable",
    description="Sets a variable in a Variable Studio.",
    params={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    returns={"type": "object"},
    requires_confirmation=True,
)


class _ScriptedPark:
    """Round 1: a block, then a write that needs the person's approval. Round 2: a block and
    nothing else — no prose to close the turn with."""

    def __init__(self) -> None:
        self.rounds = 0

    async def stream(self, model_name: str, query: str, **_: Any) -> AsyncIterator[Any]:
        self.rounds += 1
        yield f"<reasoning>{json.dumps(_BLOCK)}</reasoning>"
        if self.rounds == 1:
            yield ToolUse(id="tu_w", name="onshape_set_variable", args={"name": "WIDTH"})
        yield Usage(tokens_in=5, tokens_out=2)


async def test_a_block_only_reply_points_at_the_card_its_turn_parked(engine: AsyncEngine) -> None:
    """P7 fix 1 (M4), the REAL runner: round 1 proposes a write the gate parks for the person;
    round 2 writes only a block. The closing message is the one fixed Solus line, never model
    text — and with no confirmation flow wired the gate's flat refusal parks nothing, so the same
    reply closes empty."""

    async def write(args: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("a parked write never runs")

    async def park(call: ToolCall) -> ParkedCall:
        words = _parked_message(call, "Set WIDTH.")
        refusal = ToolError(code=ToolErrorCode.UNAUTHORIZED, message=words)
        result = ToolResult.failure(call.call_id, refusal)
        return ParkedCall(uuid.uuid4(), call.tool, dict(call.args), "Set WIDTH.", [], result)

    registry = ToolRegistry()
    registry.register(InProcessTool(_WRITE, write))
    base = await _ctx(engine, "widen the casing", action_mode=ActionMode.DO)
    closing = []
    for gate in (park, None):
        ctx = replace(base, tools=(_WRITE,), dispatch=build_dispatch(registry, gate))
        model = _ScriptedPark()
        adapters = {name: model for name in ("anthropic", "openai", "google")}
        events = [event async for event in LlmRunner(adapters=adapters).run(ctx)]
        assert model.rounds == 2
        assert events[-1].type is AgentEventType.MESSAGE
        closing.append(events[-1].data["content"])
    assert closing == [PROPOSAL_ONLY_REPLY, ""]
