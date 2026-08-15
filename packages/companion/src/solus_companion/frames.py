"""Companion wire frames — the `{type, data}` bridge protocol, client side.

Mirrors the cloud's `solus_api.bridge.frames` EXACTLY without importing it
(the companion is bundled standalone). Outbound frames are built here;
inbound frames parse defensively and never raise. The cloud is the strict
end — outbound `tool_result` data must satisfy the W0-04 ok/value/error
invariant (ok=true carries value and no error; ok=false the inverse), and
hello tools carry exactly {name, description, input_schema, output_schema}
(never `requires_confirmation` — the cloud rejects that hello).
"""

import base64
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger("solus.companion.frames")

PROTOCOL_VERSION = 1
ERROR_MESSAGE_CAP = 500

ErrorCode = Literal["invalid_args", "not_found", "tool_error", "timeout", "unauthorized"]


class ToolCallIn(BaseModel):
    """An inbound `tool_call` frame's data — `tool` is `server.tool`, split on
    the FIRST dot by the dispatcher."""

    model_config = ConfigDict(frozen=True)

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    call_id: str


@dataclass(frozen=True)
class Ack:
    protocol_version: int


@dataclass(frozen=True)
class Pong:
    pass


@dataclass(frozen=True)
class ErrorIn:
    code: str
    message: str


@dataclass(frozen=True)
class Unknown:
    type: str


@dataclass(frozen=True)
class Invalid:
    reason: str


class ArtifactFetchIn(BaseModel):
    """An inbound `artifact_fetch` frame (SOLUS-CAD-00c): the cloud asking for
    the bytes behind a handle a previous tool result advertised."""

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    fetch_id: str


Inbound = ToolCallIn | ArtifactFetchIn | Ack | Pong | ErrorIn | Unknown | Invalid


def _parse_data(raw: str | bytes) -> tuple[str, dict[str, Any]] | Invalid:
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return Invalid(reason="not valid JSON")
    if not isinstance(envelope, dict):
        return Invalid(reason="frame is not an object")
    frame_type = envelope.get("type")
    data = envelope.get("data", {})
    if not isinstance(frame_type, str):
        return Invalid(reason="missing frame type")
    if not isinstance(data, dict):
        return Invalid(reason="data is not an object")
    return frame_type, data


def parse_inbound(raw: str | bytes) -> Inbound:
    """Parse one inbound message defensively — never raises."""
    parsed = _parse_data(raw)
    if isinstance(parsed, Invalid):
        return parsed
    frame_type, data = parsed
    if frame_type == "tool_call":
        try:
            return ToolCallIn.model_validate(data)
        except ValidationError:
            return Invalid(reason="tool_call failed validation")
    if frame_type == "artifact_fetch":
        try:
            return ArtifactFetchIn.model_validate(data)
        except ValidationError:
            return Invalid(reason="artifact_fetch failed validation")
    if frame_type == "hello_ack":
        version = data.get("protocol_version")
        if isinstance(version, int):
            return Ack(protocol_version=version)
        return Invalid(reason="hello_ack missing protocol_version")
    if frame_type == "pong":
        return Pong()
    if frame_type == "error":
        return ErrorIn(
            code=str(data.get("code", ""))[:100],
            message=str(data.get("message", ""))[:ERROR_MESSAGE_CAP],
        )
    return Unknown(type=frame_type)


def _encode(frame_type: str, data: dict[str, Any]) -> str:
    return json.dumps({"type": frame_type, "data": data}, separators=(",", ":"))


def hello_frame(
    *,
    companion_version: str,
    instance_id: str,
    servers: Sequence[dict[str, Any]],
) -> str:
    """The first frame on a new socket. `servers` is the supervisor inventory,
    advertised VERBATIM — the cloud allowlist is the gate, not the companion."""
    return _encode(
        "hello",
        {
            "protocol_version": PROTOCOL_VERSION,
            "companion_version": companion_version,
            "companion_instance_id": instance_id,
            "servers": list(servers),
        },
    )


def ping_frame() -> str:
    return _encode("ping", {})


def status_frame(servers: Sequence[dict[str, Any]]) -> str:
    """BRG-03: a FULL per-server status snapshot, never a delta."""
    return _encode("status", {"servers": list(servers)})


def tool_result_ok(call_id: str, value: dict[str, Any]) -> str:
    return _encode("tool_result", {"call_id": call_id, "ok": True, "value": value})


def tool_result_error(call_id: str, code: ErrorCode, message: str, *, retryable: bool) -> str:
    return _encode(
        "tool_result",
        {
            "call_id": call_id,
            "ok": False,
            "error": {
                "code": code,
                "message": message[:ERROR_MESSAGE_CAP],
                "retryable": retryable,
            },
        },
    )


def artifact_chunk_frame(
    *, fetch_id: str, data: bytes, final: bool, error: str | None = None
) -> str:
    """One slice of a staged artifact (SOLUS-CAD-00c).

    `data` is base64 so the bytes survive a JSON text frame. `error` set means
    the fetch cannot be served (unknown/evicted handle) — the cloud fails that
    one fetch and the socket survives.
    """
    return _encode(
        "artifact_chunk",
        {
            "fetch_id": fetch_id,
            "data": base64.b64encode(data).decode("ascii"),
            "final": final,
            "error": error,
        },
    )
