"""The SOL streaming event protocol (SOLUS-SYS-01).

One uniform envelope, `AgentEvent`, is what the `AgentRunner` yields and what the
service serializes onto the SSE wire — so the transport never learns the runner's
internals and a WebSocket transport could carry the SAME events unchanged.

Security (CLAUDE.md §7): a `tool_result` carries the W0-04 `ToolResult` envelope
(never a traceback), and `error` carries a generic, author-safe message — model- and
ingested-content strings ride as DATA in `data`, never as control instructions.
"""

import enum
import json
from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict

from solus_api.agent.tools import ToolCall, ToolResult
from solus_api.agent.tools.untrusted import redact_text, redact_value

#: The bounds of a `research_sources` frame, defined ONCE: agent/research.py takes its title and
#: query limits from here, and the desktop validator (researchSources.ts) drops the whole payload
#: for a title or query past them. A frame cuts to them AFTER it masks, because masking can grow a
#: value (`token=[RED` becomes `token=[REDACTED]`). 400 is the search tool's own query ceiling.
RESEARCH_TITLE_CAP: Final = 160
RESEARCH_QUESTION_CAP: Final = 400
#: The bounds of a `reasoning` frame (SOLUSDEV-321 P7), defined ONCE: agent/reasoning_frame.py
#: refuses a block past them and the desktop validator (solStream.ts) drops a frame past them. The
#: frame cuts to them after it masks, like the research frame.
REASONING_ITEMS_CAP: Final = 12
REASONING_TEXT_CAP: Final = 200
REASONING_PROPOSING_CAP: Final = 400


def _masked(text: str, cap: int) -> str:
    """Model or ingested prose masked token by token, then cut to `cap` (masking can grow it)."""
    return redact_text(text)[:cap]


class AgentEventType(enum.StrEnum):
    """The kinds of event a SOL turn streams. `token` is an incremental text delta;
    `message` is the finished assistant text; `done` is the terminal marker carrying
    the persisted ids."""

    TOKEN = "token"  # noqa: S105 — an event-type label, not a credential
    #: SOLUSDEV-233: what context the model was handed this turn — kinds,
    #: citations and token weights only, never section text.
    CONTEXT_USED = "context_used"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    #: SOLUS-ONS-A5: a destructive action is parked awaiting the user.
    TOOL_CONFIRMATION = "tool_confirmation"
    #: SOLUSDEV-252 S5: a tool produced a viewable artifact (a diagram, a read
    #: document). A REFERENCE — id, uri, media type — never bytes.
    ARTIFACT = "artifact"
    #: SOLUSDEV-321 P1-T2: the turn was answered by Solus code from the project's facts
    #: (the first tier), with no model call; it precedes that answer's `message`.
    ANSWER_SOURCE = "answer_source"
    #: SOLUSDEV-321 P1-T3: the turn reached a server-owned ceiling (tool calls, model calls,
    #: web calls, a round's input tokens, rounds); it precedes the closing round, which has no
    #: tools, so the turn still ends in a `message`.
    BUDGET_REACHED = "budget_reached"
    #: SOLUSDEV-321 P1-T5: the web sources a turn's research found. The desktop never receives a
    #: tool's value, so its source pills ride this frame, right after the `research` tool result.
    RESEARCH_SOURCES = "research_sources"
    #: SOLUSDEV-321 P7: what SOL weighed before it proposes a change — the `<reasoning>` block it
    #: wrote, parsed out of its text (agent/reasoning_frame.py); it precedes the round's calls.
    REASONING = "reasoning"
    MESSAGE = "message"
    ERROR = "error"
    DONE = "done"


#: Who answered a turn that names it: `graph` is the first tier (agent/deterministic.py).
AnswerSource = Literal["graph"]


#: Tools whose successful result may carry an artifact reference. Fixed by Solus
#: code: a result shaped like an artifact from any other tool emits nothing.
#: `render_view` carries one only when the person asked to see the render (SOLUSDEV-321 P5).
ARTIFACT_TOOLS: frozenset[str] = frozenset({"make_diagram", "render_view"})
_ARTIFACT_KEYS = ("artifact_id", "uri", "media_type")


class AgentEvent(BaseModel):
    """A single streamed event. `data` is always JSON-serializable so it maps
    straight onto the SSE `data:` line (or a WS frame)."""

    model_config = ConfigDict(frozen=True)

    type: AgentEventType
    data: dict[str, Any]

    @classmethod
    def token(cls, text: str) -> Self:
        return cls(type=AgentEventType.TOKEN, data={"text": text})

    @classmethod
    def context_used(
        cls,
        *,
        sections: list[dict[str, Any]],
        truncated: bool,
        dropped: int,
        layers: list[dict[str, Any]],
        anchors: list[dict[str, str]],
        anchors_dropped: list[dict[str, str]],
    ) -> Self:
        """The turn's context manifest (SOLUSDEV-233): one frame at turn start
        naming each assembled section by kind/citation/tokens. Section TEXT is
        deliberately absent — prompt internals never cross the wire; the
        citation is the same verified provenance surface `message` carries.
        SOLUSDEV-321 P0-T4: `layers` names every context layer in prompt order
        ({layer, tokens, sections, empty_reason}), `anchors` where SOL looked and
        why ({id, reason}), `anchors_dropped` what never reached the scope
        ({id, reason, cause})."""
        return cls(
            type=AgentEventType.CONTEXT_USED,
            data={
                "sections": sections,
                "truncated": truncated,
                "dropped": dropped,
                "layers": layers,
                "anchors": anchors,
                "anchors_dropped": anchors_dropped,
            },
        )

    @classmethod
    def tool_call(cls, call: ToolCall) -> Self:
        # redact_value (SOLX-04 SEC-H3): model-proposed args stream to the
        # browser BEFORE validation/dispatch — a secret-shaped value the model
        # echoes must not cross the wire in the clear. Persistence already
        # redacts (_persist_turn); the live frame gets the same gate.
        return cls(
            type=AgentEventType.TOOL_CALL,
            data={"call_id": call.call_id, "tool": call.tool, "args": redact_value(call.args)},
        )

    @classmethod
    def tool_confirmation(
        cls,
        *,
        confirmation_id: str,
        tool: str,
        args: dict[str, Any],
        summary: str,
        preview: list[dict[str, Any]] | None = None,
    ) -> Self:
        """A destructive action awaiting approval (SOLUS-ONS-A5).

        Carries the CONCRETE action — tool, arguments and a readable summary —
        because a user cannot meaningfully approve an opaque id. The client
        decides via `POST .../sol/confirmations/{confirmation_id}` and sends back
        a decision only; the arguments that execute are the stored ones.
        """
        return cls(
            type=AgentEventType.TOOL_CONFIRMATION,
            data={
                "confirmation_id": confirmation_id,
                "tool": tool,
                "args": args,
                "summary": summary,
                # The diff being approved, generic across tool kinds.
                "preview": preview or [],
            },
        )

    @classmethod
    def tool_result(cls, result: ToolResult, *, command: dict[str, Any] | None = None) -> Self:
        """`command` (SOLUSDEV-317 §10.1) is an auto-run `code.exec`'s desktop
        row — `{tool, auto, program, status, stdout_tail, stderr_tail}` — merged
        at the top level beside the unchanged `{call_id, ok, value, error}`."""
        # redact_value (SYS-04 SEC M5): tool values carry connector-ingested
        # content — a synced attrs key literally named `api_key` must not stream
        # to the client in the clear. Same gate the persisted turn already gets.
        data = result.model_dump(mode="json")
        return cls(type=AgentEventType.TOOL_RESULT, data=redact_value({**(command or {}), **data}))

    @classmethod
    def artifact(cls, ref: dict[str, Any]) -> Self:
        """A viewable artifact the turn produced (SOLUSDEV-252 S5). The renderer
        fetches the bytes through the artifacts route with the viewer's own auth;
        the event carries only `{artifact_id, uri, media_type, title, source_tool,
        summary}` — never inline bytes."""
        return cls(type=AgentEventType.ARTIFACT, data=dict(ref))

    @classmethod
    def artifact_from_result(cls, tool: str, result: ToolResult) -> Self | None:
        """The `artifact` event a tool result implies, or None. Keyed on BOTH the
        allowlist and the result shape, so a look-alike value from another tool
        (or model-influenced text) can never make the UI fetch something."""
        value = result.value if result.ok and tool in ARTIFACT_TOOLS else None
        # `value` is a tool's own return shape, so it is checked, not trusted:
        # the whole point of this method is that a look-alike cannot make the UI
        # fetch something. A non-mapping is simply not an artifact.
        if not isinstance(value, Mapping):
            return None
        if not all(isinstance(value.get(k), str) for k in _ARTIFACT_KEYS):
            return None
        return cls.artifact(
            {
                **{k: value[k] for k in _ARTIFACT_KEYS},
                "title": str(value.get("title") or ""),
                "source_tool": tool,
                "summary": str(value.get("summary") or ""),
            }
        )

    @classmethod
    def answer_source(
        cls,
        source: AnswerSource,
        *,
        sources: tuple[str, ...] = (),
        citations: tuple[str, ...] = (),
    ) -> Self:
        """The answer's envelope (SOLUSDEV-321 P1-T2): who answered (`graph`, the first tier),
        the fact sources it read (`config`, `telemetry`, …) and the citations it was built from
        — Solus-authored ids over fixed kinds, never model text. The route stores it on the
        assistant turn (`attrs.answer_source`, `attrs.sources`, `attrs.citations`)."""
        return cls(
            type=AgentEventType.ANSWER_SOURCE,
            data={"source": source, "sources": list(sources), "citations": list(citations)},
        )

    @classmethod
    def budget_reached(cls, limit: str, used: int, cap: int) -> Self:
        """A ceiling the turn reached (SOLUSDEV-321 P1-T3): which (`limit`: `tool_calls`,
        `model_calls`, `web_searches`, `web_fetches`, `input_tokens` or `model_rounds`), what the
        turn used and the cap it was held to. Counts only — Solus-authored, never model text. At
        most one a turn; the closing round and the `message` follow."""
        return cls(
            type=AgentEventType.BUDGET_REACHED, data={"limit": limit, "used": used, "cap": cap}
        )

    @classmethod
    def research_sources(
        cls,
        *,
        call_id: str,
        question: str,
        cached: bool,
        searches: int,
        pages: int,
        sources: Sequence[Mapping[str, Any]],
    ) -> Self:
        """The sources a turn's web research found (SOLUSDEV-321 P1-T5): the call it answers, the
        (redacted) query, whether the cache answered, what THIS turn spent (`searches` and `pages`
        are 0 for a cached answer) and each source as `{url, title, fetched}`. The desktop renders
        them as inert pills; the route stores the whole payload on the assistant turn. Page text is
        written by other people, so the payload is redacted like any tool value — and the prose
        fields (the query and each title) token by token first, since `redact_value` judges a
        string whole and a credential inside a sentence would pass it. Both are then cut to
        `RESEARCH_QUESTION_CAP` / `RESEARCH_TITLE_CAP` — after masking, which can grow a value; the
        other bounds (a URL, twenty sources) are the digest's own, proved where it is read."""
        return cls(
            type=AgentEventType.RESEARCH_SOURCES,
            data=redact_value(
                {
                    "call_id": call_id,
                    "question": redact_text(question)[:RESEARCH_QUESTION_CAP],
                    "cached": cached,
                    "searches": searches,
                    "pages": pages,
                    "sources": [
                        {
                            **source,
                            "title": redact_text(str(source.get("title", "")))[:RESEARCH_TITLE_CAP],
                        }
                        for source in sources
                    ],
                }
            ),
        )

    @classmethod
    def reasoning(
        cls,
        considered: Sequence[str],
        ruled_out: Sequence[Mapping[str, str]],
        proposing: str,
    ) -> Self:
        """What SOL weighed before it proposes a change (SOLUSDEV-321 P7): what it considered,
        what it ruled out and why (`{what, why}`), and what it proposes. Model text that
        agent/reasoning_frame.py parsed out of the reply and held to its shape, so each string is
        masked token by token and cut to its bound after masking. The desktop draws it as plain
        text above the proposal's card; nothing on the server reads it back — it picks no tool,
        mode, scope or permission."""
        return cls(
            type=AgentEventType.REASONING,
            data={
                "considered": [
                    _masked(item, REASONING_TEXT_CAP) for item in considered[:REASONING_ITEMS_CAP]
                ],
                "ruled_out": [
                    {
                        "what": _masked(row["what"], REASONING_TEXT_CAP),
                        "why": _masked(row["why"], REASONING_TEXT_CAP),
                    }
                    for row in ruled_out[:REASONING_ITEMS_CAP]
                ],
                "proposing": _masked(proposing, REASONING_PROPOSING_CAP),
            },
        )

    @classmethod
    def message(
        cls, content: str, role: str = "assistant", citations: tuple[str, ...] = ()
    ) -> Self:
        """`citations` is the AUTHORITATIVE provenance surface (SOL-02): verified
        by Solus code, carried as structured data so model prose can never
        impersonate it. Renderers show it in a region model text cannot reach,
        never linkified, display-capped."""
        return cls(
            type=AgentEventType.MESSAGE,
            data={"role": role, "content": content, "citations": list(citations)},
        )

    @classmethod
    def error(cls, code: str, message: str) -> Self:
        return cls(type=AgentEventType.ERROR, data={"code": code, "message": message})

    @classmethod
    def done(cls, **fields: Any) -> Self:
        return cls(type=AgentEventType.DONE, data=dict(fields))


def persisted_answer(event: AgentEvent) -> dict[str, Any]:
    """The assistant-turn attrs a frame carries, and {} for any other frame: an `answer_source`
    frame's `answer_source`, `sources`, `citations` (SOLUSDEV-321 P1-T2), a `budget_reached`
    frame's `budget_reached` = {limit, used, cap} (P1-T3), a `research_sources` frame's whole
    payload as `research_sources` (P1-T5), so a reload shows the same source pills. The route
    merges them into the turn's attrs whichever runner streamed the frame."""
    if event.type is AgentEventType.ANSWER_SOURCE:
        return {
            "answer_source": event.data["source"],
            "sources": event.data["sources"],
            "citations": event.data["citations"],
        }
    if event.type is AgentEventType.BUDGET_REACHED:
        return {"budget_reached": dict(event.data)}
    if event.type is AgentEventType.RESEARCH_SOURCES:
        return {"research_sources": dict(event.data)}
    return {}


def format_sse(event: AgentEvent) -> str:
    """Encode one event as an SSE frame: a named event plus a compact JSON payload.
    `separators` keeps the wire tight and deterministic (stable for tests)."""
    payload = json.dumps(event.data, separators=(",", ":"), sort_keys=True)
    return f"event: {event.type.value}\ndata: {payload}\n\n"
