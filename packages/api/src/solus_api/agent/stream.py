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


class AgentEventType(enum.StrEnum):
    """The kinds of event a SOL turn streams. `token` is an incremental text delta;
    `message` is the finished assistant text; `done` is the terminal marker carrying
    the persisted ids."""

    TOKEN = "token"  # noqa: S105 — an event-type label, not a credential
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
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
    def tool_call(cls, call: ToolCall) -> Self:
        return cls(
            type=AgentEventType.TOOL_CALL,
            data={"call_id": call.call_id, "tool": call.tool, "args": call.args},
        )

    @classmethod
    def tool_result(cls, result: ToolResult) -> Self:
        return cls(type=AgentEventType.TOOL_RESULT, data=result.model_dump(mode="json"))

    @classmethod
    def message(cls, content: str, role: str = "assistant") -> Self:
        return cls(type=AgentEventType.MESSAGE, data={"role": role, "content": content})

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
