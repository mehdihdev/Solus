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
from typing import Any, Self

from pydantic import BaseModel, ConfigDict

from solus_api.agent.tools import ToolCall, ToolResult
from solus_api.agent.tools.untrusted import redact_value


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
    MESSAGE = "message"
    ERROR = "error"
    DONE = "done"


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
    def context_used(cls, *, sections: list[dict[str, Any]], truncated: bool, dropped: int) -> Self:
        """The turn's context manifest (SOLUSDEV-233): one frame at turn start
        naming each assembled section by kind/citation/tokens. Section TEXT is
        deliberately absent — prompt internals never cross the wire; the
        citation is the same verified provenance surface `message` carries."""
        return cls(
            type=AgentEventType.CONTEXT_USED,
            data={"sections": sections, "truncated": truncated, "dropped": dropped},
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
    def tool_result(cls, result: ToolResult) -> Self:
        # redact_value (SYS-04 SEC M5): tool values carry connector-ingested
        # content — a synced attrs key literally named `api_key` must not stream
        # to the client in the clear. Same gate the persisted turn already gets.
        return cls(
            type=AgentEventType.TOOL_RESULT, data=redact_value(result.model_dump(mode="json"))
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


def format_sse(event: AgentEvent) -> str:
    """Encode one event as an SSE frame: a named event plus a compact JSON payload.
    `separators` keeps the wire tight and deterministic (stable for tests)."""
    payload = json.dumps(event.data, separators=(",", ":"), sort_keys=True)
    return f"event: {event.type.value}\ndata: {payload}\n\n"
