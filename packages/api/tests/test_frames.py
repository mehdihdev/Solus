"""Unit tests for the bridge wire frames (BRG-02-impl, contract §4/§6).

No DB, no socket — mirrors test_stream.py: encode/parse/redact only.
"""

import json
from typing import Any

from solus_api.agent.tools.shapes import ToolCall, ToolResult
from solus_api.bridge.frames import (
    CLOSE_OVERSIZE,
    PROTOCOL_VERSION,
    ErrorData,
    FrameViolation,
    HelloData,
    InboundFrame,
    ServerState,
    StatusData,
    UnknownFrame,
    error_frame,
    hello_ack_frame,
    parse_frame,
    pong_frame,
    redact_value,
    tool_call_frame,
)

CONTROL_CAP = 16_384
RESULT_CAP = 1_048_576


def _parse(obj: dict[str, Any]) -> InboundFrame | FrameViolation | UnknownFrame:
    return parse_frame(json.dumps(obj), control_cap=CONTROL_CAP, tool_result_cap=RESULT_CAP)


def _hello_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "companion_version": "0.1.0",
        "companion_instance_id": "instance-a",
        "servers": [
            {
                "server": "mock",
                "tools": [{"name": "echo", "description": "d", "input_schema": {"type": "object"}}],
            }
        ],
    }
    data.update(overrides)
    return data


def test_hello_parses_strictly() -> None:
    frame = _parse({"type": "hello", "data": _hello_data()})
    assert isinstance(frame, InboundFrame)
    assert isinstance(frame.payload, HelloData)
    assert frame.payload.servers[0].tools[0].name == "echo"


def test_hello_rejects_client_asserted_confirmation_and_scope() -> None:
    # extra="forbid": a companion asserting requires_confirmation or scope ids
    # produces a violation, never a parsed hello (contract §9 case 2 groundwork).
    tools = [
        {
            "name": "echo",
            "input_schema": {"type": "object"},
            "requires_confirmation": False,
        }
    ]
    bad_tool = _parse(
        {"type": "hello", "data": _hello_data(servers=[{"server": "mock", "tools": tools}])}
    )
    assert isinstance(bad_tool, FrameViolation)
    bad_scope = _parse({"type": "hello", "data": _hello_data(team_id="not-yours")})
    assert isinstance(bad_scope, FrameViolation)


def test_tool_result_rides_w004_shape_with_invariant() -> None:
    ok = ToolResult.success("c1", {"result": "hi"})
    frame = _parse({"type": "tool_result", "data": ok.model_dump(mode="json")})
    assert isinstance(frame, InboundFrame)
    assert isinstance(frame.payload, ToolResult)
    # ok=True with an error attached violates the W0-04 invariant → dropped.
    broken = _parse(
        {
            "type": "tool_result",
            "data": {
                "call_id": "c1",
                "ok": True,
                "value": {"x": 1},
                "error": {"code": "tool_error", "message": "no"},
            },
        }
    )
    assert isinstance(broken, FrameViolation)
    assert broken.kind == "invalid"


def test_ping_error_and_status_frames() -> None:
    ping = _parse({"type": "ping", "data": {}})
    assert isinstance(ping, InboundFrame) and ping.payload is None
    loaded_ping = _parse({"type": "ping", "data": {"x": 1}})
    assert isinstance(loaded_ping, FrameViolation)
    err = _parse({"type": "error", "data": {"code": "boo", "message": "m", "details": []}})
    assert isinstance(err, InboundFrame) and isinstance(err.payload, ErrorData)
    # status validates strictly since BRG-03 (snapshot-not-delta schema)
    snapshot = {
        "servers": [
            {"name": "mock", "state": "ready", "detail": None, "updated_at": "2026-07-23T00:00:00Z"}
        ]
    }
    status = _parse({"type": "status", "data": snapshot})
    assert isinstance(status, InboundFrame) and isinstance(status.payload, StatusData)
    assert status.payload.servers[0].state is ServerState.READY
    bad_state = _parse(
        {
            "type": "status",
            "data": {"servers": [{"name": "m", "state": "exploded", "updated_at": "2026-01-01"}]},
        }
    )
    assert isinstance(bad_state, FrameViolation)
    oversize_detail = _parse(
        {
            "type": "status",
            "data": {
                "servers": [
                    {"name": "m", "state": "error", "detail": "x" * 600, "updated_at": "2026-01-01"}
                ]
            },
        }
    )
    assert isinstance(oversize_detail, FrameViolation)
    assert isinstance(_parse({"type": "status", "data": {"anything": "goes"}}), FrameViolation)


def test_unknown_type_is_ignored_but_outbound_types_are_violations() -> None:
    assert isinstance(_parse({"type": "future_thing", "data": {}}), UnknownFrame)
    wrong_direction = _parse({"type": "tool_call", "data": {}})
    assert isinstance(wrong_direction, FrameViolation)


def test_malformed_envelopes_are_violations_never_raises() -> None:
    assert isinstance(
        parse_frame("not json{", control_cap=CONTROL_CAP, tool_result_cap=RESULT_CAP),
        FrameViolation,
    )
    assert isinstance(_parse({"type": 3, "data": {}}), FrameViolation)
    assert isinstance(
        parse_frame(json.dumps([1, 2]), control_cap=CONTROL_CAP, tool_result_cap=RESULT_CAP),
        FrameViolation,
    )
    extra_key = _parse({"type": "ping", "data": {}, "meta": 1})
    assert isinstance(extra_key, FrameViolation)
    assert isinstance(_parse({"type": "ping", "data": [1]}), FrameViolation)


def test_size_caps_pre_parse_and_per_type() -> None:
    huge = json.dumps({"type": "tool_result", "data": {"blob": "x" * (RESULT_CAP + 1)}})
    frame = parse_frame(huge, control_cap=CONTROL_CAP, tool_result_cap=RESULT_CAP)
    assert isinstance(frame, FrameViolation) and frame.kind == "oversize"
    big_control = json.dumps({"type": "status", "data": {"blob": "x" * (CONTROL_CAP + 1)}})
    frame = parse_frame(big_control, control_cap=CONTROL_CAP, tool_result_cap=RESULT_CAP)
    assert isinstance(frame, FrameViolation) and frame.kind == "oversize"
    assert CLOSE_OVERSIZE == 4413


def test_outbound_builders_round_trip() -> None:
    ack = json.loads(hello_ack_frame())
    assert ack == {"type": "hello_ack", "data": {"protocol_version": PROTOCOL_VERSION}}
    assert json.loads(pong_frame()) == {"type": "pong", "data": {}}
    err = json.loads(error_frame("unsupported_protocol_version", "m", [{"supported": 1}]))
    assert err["data"]["details"] == [{"supported": 1}]
    call = ToolCall(tool="mock.echo", args={"text": "hi"})
    wire = json.loads(tool_call_frame(call))
    assert wire["type"] == "tool_call"
    assert wire["data"] == {"tool": "mock.echo", "args": {"text": "hi"}, "call_id": call.call_id}


def test_redact_value_keys_and_entropy() -> None:
    value = {
        "api_key": "shortvalue",
        "nested": {"Authorization": "Bearer abc", "fine": "hello world"},
        "list": [{"private-key": "x"}],
        "entropic": "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0",  # 40 chars, many distinct
        "call_id": "0123456789abcdef0123456789abcdef",  # 32-hex id shape — kept
    }
    red = redact_value(value)
    assert red["api_key"] == "[REDACTED]"
    assert red["nested"]["Authorization"] == "[REDACTED]"
    assert red["list"][0]["private-key"] == "[REDACTED]"
    assert red["entropic"] == "[REDACTED]"
    assert red["call_id"] == value["call_id"]
    assert red["nested"]["fine"] == "hello world"
    assert value["api_key"] == "shortvalue"  # input not mutated


def test_recursion_bomb_is_a_violation_not_a_crash() -> None:
    # SEC-L1: deep nesting must come back as a dropped violation.
    bomb = ("[" * 50_000) + ("]" * 50_000)
    frame = parse_frame(
        f'{{"type": "status", "data": {{"x": {bomb}}}}}',
        control_cap=CONTROL_CAP,
        tool_result_cap=RESULT_CAP,
    )
    assert isinstance(frame, FrameViolation)


def test_redact_text_masks_assignments_and_entropic_tokens() -> None:
    # SEC-M3: the error channel gets scalar redaction.
    from solus_api.bridge.frames import redact_text

    masked = redact_text("aws_secret_key= AKIA123 api-key: hunter2secret plain words")
    assert "hunter2secret" not in masked
    text = "token=abc123 then " + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"
    masked = redact_text(text)
    assert "abc123" not in masked
    assert "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0" not in masked
    assert redact_text("no secrets here at all") == "no secrets here at all"
