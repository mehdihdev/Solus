"""Bridge wire frames — the `{type, data}` protocol (contract §4).

One JSON text message per frame, riding the SYS-01 `AgentEvent` shape. The
cloud is the STRICT end: known inbound types validate with `extra="forbid"`;
`tool_result` data is parsed with the real W0-04 `ToolResult` so its
ok/value/error invariant is enforced at ingress; unknown types are ignored
(the §4 extension mechanism); wrong-direction known types are violations.
`status` is a reserved type with an opaque payload until BRG-03.
"""

import enum
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_api.agent.tools.shapes import ToolCall, ToolResult

# Redaction moved to the shared untrusted-input module (SOLUS-RUN-01) so the
# agent's tool-result path gets the same gate. Explicit `as` re-export: this
# module's own callers import these from here and are unchanged.
from solus_api.agent.tools.untrusted import REDACTED as REDACTED
from solus_api.agent.tools.untrusted import redact_text as redact_text
from solus_api.agent.tools.untrusted import redact_value as redact_value

logger = logging.getLogger("solus.bridge.frames")

PROTOCOL_VERSION = 1

# App close codes — complete set (contract §4).
CLOSE_UNSUPPORTED_VERSION = 4400
CLOSE_UNAUTHENTICATED = 4401
CLOSE_REVOKED = 4403
CLOSE_NOT_FOUND = 4404  # non-member/unknown project: no existence leak
CLOSE_SUPERSEDED = 4409
CLOSE_OVERSIZE = 4413
CLOSE_RATE_EXCEEDED = 4429


class ToolOutputData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    call_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1, le=256)
    stream: Literal["stdout", "stderr"]
    text: str = Field(max_length=2048)
    truncated: bool = False


class HelloTool(BaseModel):
    """One tool a companion advertises. UNTRUSTED — deliberately has no
    `requires_confirmation` field: that flag comes only from the Solus-owned
    allowlist, and a companion asserting it fails `extra="forbid"`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str = ""
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None


class HelloServer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    server: str
    tools: tuple[HelloTool, ...] = ()


class HelloData(BaseModel):
    """The first frame on a new socket (contract §2/§4). The hello-inventory
    schema fills the contract's §10 MCP-03 hole — recorded in the paste file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: int
    # Bounded (security review M2): both are companion-supplied free text that
    # reaches a DB row (supersede events) and an API response (bridge status).
    companion_version: str = Field(min_length=1, max_length=64)
    companion_instance_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    servers: tuple[HelloServer, ...] = ()


class ServerState(enum.StrEnum):
    """Per-server lifecycle a companion reports (BRG-03). Busy is PER-SERVER —
    these servers wrap serialized desktop apps; the process is the concurrency
    unit, and per-tool busy would be fabricated data."""

    NOT_LAUNCHED = "not_launched"
    LAUNCHING = "launching"
    READY = "ready"
    BUSY = "busy"
    ERROR = "error"


class ServerStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    state: ServerState
    # §6 hygiene: short, no tracebacks/env dumps/foreign paths — capped here.
    detail: str | None = Field(default=None, max_length=512)
    updated_at: datetime


class StatusData(BaseModel):
    """A FULL snapshot, never a delta — idempotent, no ordering hazards; the
    cloud cache is simply the last frame verbatim (dies with the session)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    servers: tuple[ServerStatus, ...] = ()


class ErrorData(BaseModel):
    """Protocol-level failure object — the API.md §1.4 error shape. Tool
    failures never use this frame; they are `ToolResult.error` data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    details: tuple[dict[str, Any], ...] = ()


class CredentialSubmitData(BaseModel):
    """MCP-05 BYO-license capture (inbound): license credential VALUES for one
    byo_paid server, keyed by credential key NAME. The values are the only
    secret material that legitimately rides this channel, so the model is
    unloggable by construction: `hide_input_in_errors` keeps values out of
    validation errors (which feed drop-reason log lines), and `__repr__`/
    `__str__` redact the mapping so no log interpolation can leak one (§6:
    credential values NEVER in cloud logs). New frame type per the §4 extension
    rule — no protocol_version bump; old clouds ignore it as unknown."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    server: str
    secrets: dict[str, str]

    def __repr__(self) -> str:
        return f"CredentialSubmitData(server={self.server!r}, secrets={REDACTED})"

    __str__ = __repr__


class ArtifactChunkData(BaseModel):
    """One slice of a staged artifact (SOLUS-CAD-00c, inbound).

    Bulk export bytes never ride a tool result (`metadata-extraction.md` §2.1);
    the companion stages them and the cloud pulls them in chunks. `data` is
    base64 so bytes survive a JSON text frame. `error` set means the fetch
    cannot be served — that one fetch fails, the socket survives. New frame
    type per the §4 extension rule; no protocol_version bump."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fetch_id: str
    data: str = ""
    final: bool = False
    error: str | None = None


# Inbound (companion → cloud) frame types and the outbound-only set — a known
# outbound type arriving inbound is a protocol violation, not an unknown.
INBOUND_TYPES = frozenset(
    {
        "hello",
        "ping",
        "status",
        "error",
        "tool_result",
        "tool_output",
        "credential_submit",
        "artifact_chunk",
        # SOLUSDEV-167: an unsolicited "something under my workspace moved".
        # Added under the §4 extension rule — a new frame type does NOT bump
        # protocol_version; an old peer logs and ignores it.
        "change",
    }
)
OUTBOUND_TYPES = frozenset({"hello_ack", "pong", "tool_call", "credential_ack", "artifact_fetch"})


@dataclass(frozen=True)
class InboundFrame:
    type: str
    # hello → HelloData · tool_result → ToolResult · error → ErrorData ·
    # status → StatusData (BRG-03) · credential_submit → CredentialSubmitData
    # (MCP-05) · ping → None
    payload: (
        HelloData
        | ToolResult
        | ErrorData
        | StatusData
        | CredentialSubmitData
        | ArtifactChunkData
        | ToolOutputData
        | None
    )


@dataclass(frozen=True)
class FrameViolation:
    """Drop (+ abuse count); `oversize` additionally means close 4413."""

    kind: Literal["oversize", "invalid"]
    reason: str


@dataclass(frozen=True)
class UnknownFrame:
    """Log + ignore — the extension mechanism (§4)."""

    type: str


def _parse_envelope(raw: str | bytes) -> tuple[str, dict[str, Any]] | FrameViolation:
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return FrameViolation(kind="invalid", reason="not valid JSON")
    except RecursionError:
        # SEC-L1: a ≤1 MiB deeply-nested frame must be a dropped violation,
        # never an escaped exception (§7: never crash on malformed input).
        return FrameViolation(kind="invalid", reason="JSON nesting too deep")
    if not isinstance(envelope, dict):
        return FrameViolation(kind="invalid", reason="frame is not an object")
    frame_type = envelope.get("type")
    data = envelope.get("data", {})
    if not isinstance(frame_type, str) or set(envelope) - {"type", "data"}:
        return FrameViolation(kind="invalid", reason="malformed envelope")
    if not isinstance(data, dict):
        return FrameViolation(kind="invalid", reason="data is not an object")
    return frame_type, data


#: Inbound types that carry a validated payload model. A table rather than an
#: if-ladder so adding a frame type cannot quietly grow the dispatcher.
_PAYLOAD_MODELS: dict[str, Any] = {
    "hello": HelloData,
    "tool_result": ToolResult,
    "tool_output": ToolOutputData,
    "error": ErrorData,
    "status": StatusData,
    "credential_submit": CredentialSubmitData,
    "artifact_chunk": ArtifactChunkData,
}

#: Inbound types whose `data` must be EMPTY — the type is the whole message.
_EMPTY_PAYLOAD_TYPES = ("ping", "change")


def _parse_payload(frame_type: str, data: dict[str, Any]) -> InboundFrame | FrameViolation:
    model = _PAYLOAD_MODELS.get(frame_type)
    if model is not None:
        try:
            return InboundFrame(type=frame_type, payload=model.model_validate(data))
        except ValidationError as exc:
            return FrameViolation(
                kind="invalid", reason=f"{frame_type} failed validation: {exc!s:.200}"
            )
    if frame_type in _EMPTY_PAYLOAD_TYPES:
        # SOLUSDEV-167 for `change`: EMPTY BY DESIGN. Its whole meaning is its
        # type — some design artifact under this companion's workspace moved,
        # come and ask. No digest (the connector's own detect_changes is the
        # authority) and no server name (the sensor watches one workspace shared
        # by both forks, so attributing kicad vs altium would be a guess).
        # Rejecting a payload keeps that true rather than merely intended.
        if data:
            return FrameViolation(kind="invalid", reason=f"{frame_type} carries no data")
        return InboundFrame(type=frame_type, payload=None)
    raise AssertionError(f"unhandled inbound type {frame_type!r}")  # pragma: no cover


def parse_frame(
    raw: str | bytes,
    *,
    control_cap: int,
    tool_result_cap: int,
    hello_cap: int | None = None,
) -> InboundFrame | FrameViolation | UnknownFrame:
    """Validate one inbound message: size caps first (pre-parse), then the
    envelope, then the per-type strict payload. Never raises.

    `hello_cap` (SOLUSDEV-249): the hello carries every advertised tool's
    schema, so three vendored servers (Altium + KiCad + local ≈ 19 KB) already
    overflow the 16 KiB control cap — the companion was then closed with
    `4400 update required` on any machine with a linked workspace. The first
    frame gets its own bounded cap (default: the tool_call bound); every other
    control frame keeps the small one."""
    size = len(raw.encode() if isinstance(raw, str) else raw)
    if size > tool_result_cap:
        return FrameViolation(kind="oversize", reason=f"frame of {size} bytes exceeds the cap")
    envelope = _parse_envelope(raw)
    if isinstance(envelope, FrameViolation):
        return envelope
    frame_type, data = envelope
    if frame_type in OUTBOUND_TYPES:
        return FrameViolation(kind="invalid", reason=f"{frame_type!r} is not an inbound frame")
    if frame_type not in INBOUND_TYPES:
        return UnknownFrame(type=frame_type)
    cap = hello_cap if (frame_type == "hello" and hello_cap is not None) else control_cap
    if frame_type != "tool_result" and size > cap:
        return FrameViolation(
            kind="oversize", reason=f"control frame of {size} bytes exceeds the cap"
        )
    return _parse_payload(frame_type, data)


def _dump(frame_type: str, data: dict[str, Any]) -> str:
    return json.dumps({"type": frame_type, "data": data}, separators=(",", ":"))


def hello_ack_frame() -> str:
    return _dump("hello_ack", {"protocol_version": PROTOCOL_VERSION})


def pong_frame() -> str:
    return _dump("pong", {})


def error_frame(code: str, message: str, details: list[dict[str, Any]] | None = None) -> str:
    return _dump("error", {"code": code, "message": message, "details": details or []})


def tool_call_frame(call: ToolCall) -> str:
    return _dump("tool_call", call.model_dump(mode="json"))


def credential_ack_frame(server: str, *, ok: bool, stored: list[str], error: str | None) -> str:
    """MCP-05 reply to `credential_submit`: key NAMES only, never values."""
    return _dump("credential_ack", {"server": server, "ok": ok, "stored": stored, "error": error})


# --- Ingress redaction (contract §6) -----------------------------------------


def artifact_fetch_frame(*, artifact_id: str, fetch_id: str) -> str:
    """Ask the companion for the bytes behind a staged handle (SOLUS-CAD-00c)."""
    return _dump("artifact_fetch", {"artifact_id": artifact_id, "fetch_id": fetch_id})
