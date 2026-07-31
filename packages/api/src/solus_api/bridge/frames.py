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
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_api.agent.tools.shapes import ToolCall, ToolResult

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
    companion_version: str
    companion_instance_id: str
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


# Inbound (companion → cloud) frame types and the outbound-only set — a known
# outbound type arriving inbound is a protocol violation, not an unknown.
INBOUND_TYPES = frozenset({"hello", "ping", "status", "error", "tool_result", "credential_submit"})
OUTBOUND_TYPES = frozenset({"hello_ack", "pong", "tool_call", "credential_ack"})


@dataclass(frozen=True)
class InboundFrame:
    type: str
    # hello → HelloData · tool_result → ToolResult · error → ErrorData ·
    # status → StatusData (BRG-03) · credential_submit → CredentialSubmitData
    # (MCP-05) · ping → None
    payload: HelloData | ToolResult | ErrorData | StatusData | CredentialSubmitData | None


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


def _parse_payload(frame_type: str, data: dict[str, Any]) -> InboundFrame | FrameViolation:
    try:
        if frame_type == "hello":
            return InboundFrame(type="hello", payload=HelloData.model_validate(data))
        if frame_type == "tool_result":
            return InboundFrame(type="tool_result", payload=ToolResult.model_validate(data))
        if frame_type == "error":
            return InboundFrame(type="error", payload=ErrorData.model_validate(data))
        if frame_type == "status":
            return InboundFrame(type="status", payload=StatusData.model_validate(data))
        if frame_type == "credential_submit":
            return InboundFrame(
                type="credential_submit", payload=CredentialSubmitData.model_validate(data)
            )
    except ValidationError as exc:
        return FrameViolation(
            kind="invalid", reason=f"{frame_type} failed validation: {exc!s:.200}"
        )
    if frame_type == "ping":
        if data:
            return FrameViolation(kind="invalid", reason="ping carries no data")
        return InboundFrame(type="ping", payload=None)
    raise AssertionError(f"unhandled inbound type {frame_type!r}")  # pragma: no cover


def parse_frame(
    raw: str | bytes,
    *,
    control_cap: int,
    tool_result_cap: int,
) -> InboundFrame | FrameViolation | UnknownFrame:
    """Validate one inbound message: size caps first (pre-parse), then the
    envelope, then the per-type strict payload. Never raises."""
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
    if frame_type != "tool_result" and size > control_cap:
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

_SECRET_KEY = re.compile(
    r"token|secret|passw(or)?d|api[_-]?key|authorization|cookie|private[_-]?key|credential",
    re.IGNORECASE,
)
_ENTROPIC_CHARSET = re.compile(r"^[A-Za-z0-9+/=_.-]+$")
# ponytail: length/charset/distinct-chars heuristic — ≥40 spares uuid4().hex
# call-id-shaped values; a base64 secret under 40 chars slips through. Tighten
# with a real detector (e.g. detect-secrets) if field data shows leaks.
_ENTROPIC_MIN_LEN = 40
_ENTROPIC_MIN_DISTINCT = 16

REDACTED = "[REDACTED]"


def _looks_entropic(value: str) -> bool:
    return (
        len(value) >= _ENTROPIC_MIN_LEN
        and _ENTROPIC_CHARSET.fullmatch(value) is not None
        and len(set(value)) >= _ENTROPIC_MIN_DISTINCT
    )


def redact_value(value: Any) -> Any:
    """Recursively redact secret-shaped content from an untrusted result before
    it is persisted or enters model context. Returns a new structure."""
    if isinstance(value, dict):
        return {
            key: (
                REDACTED if isinstance(key, str) and _SECRET_KEY.search(key) else redact_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str) and _looks_entropic(value):
        return REDACTED
    return value


_SECRET_ASSIGNMENT = re.compile(
    r"((?:token|secret|passw(?:or)?d|api[_-]?key|authorization|cookie|private[_-]?key|credential)"
    r"[A-Za-z0-9_-]*\s*[=:]\s*)(\S+)",
    re.IGNORECASE,
)


def redact_text(text: str) -> str:
    """Scalar redaction for untrusted free text (SEC-M3): secret-shaped
    `key=value`/`key: value` assignments and entropic tokens are masked before
    the text can reach model context or persistence."""
    masked = _SECRET_ASSIGNMENT.sub(lambda m: m.group(1) + REDACTED, text)
    tokens = [REDACTED if _looks_entropic(token) else token for token in masked.split(" ")]
    return " ".join(tokens)
