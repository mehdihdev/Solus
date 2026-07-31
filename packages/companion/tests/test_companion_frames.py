"""Frames: outbound builders round-trip; inbound parsing never raises.

Includes a drift guard: the frames the companion emits must validate against
the cloud's strict Pydantic models (skipped if solus_api is not importable —
the companion package itself never depends on it).
"""

import json

import pytest
from solus_companion.frames import (
    ERROR_MESSAGE_CAP,
    PROTOCOL_VERSION,
    Ack,
    ErrorIn,
    Invalid,
    Pong,
    ToolCallIn,
    Unknown,
    hello_frame,
    parse_inbound,
    ping_frame,
    status_frame,
    tool_result_error,
    tool_result_ok,
)

STATUS_ENTRY = {
    "name": "mock",
    "state": "busy",
    "detail": None,
    "updated_at": "2026-07-23T00:00:00+00:00",
}

SERVERS = [
    {
        "server": "mock",
        "tools": [
            {
                "name": "echo",
                "description": "Echo the input back.",
                "input_schema": {"type": "object"},
                "output_schema": None,
            }
        ],
    }
]


def test_hello_frame_shape() -> None:
    frame = json.loads(
        hello_frame(companion_version="0.1.0", instance_id="a" * 32, servers=SERVERS)
    )
    assert frame == {
        "type": "hello",
        "data": {
            "protocol_version": PROTOCOL_VERSION,
            "companion_version": "0.1.0",
            "companion_instance_id": "a" * 32,
            "servers": SERVERS,
        },
    }


def test_hello_never_carries_requires_confirmation() -> None:
    raw = hello_frame(companion_version="0.1.0", instance_id="a" * 32, servers=SERVERS)
    assert "requires_confirmation" not in raw


def test_ping_frame_compact() -> None:
    assert ping_frame() == '{"type":"ping","data":{}}'


def test_tool_result_ok_shape() -> None:
    frame = json.loads(tool_result_ok("c1", {"result": "hi"}))
    assert frame == {
        "type": "tool_result",
        "data": {"call_id": "c1", "ok": True, "value": {"result": "hi"}},
    }
    assert "error" not in frame["data"]


def test_tool_result_error_shape_and_cap() -> None:
    frame = json.loads(tool_result_error("c2", "tool_error", "x" * 1000, retryable=True))
    data = frame["data"]
    assert data["call_id"] == "c2"
    assert data["ok"] is False
    assert "value" not in data
    assert data["error"]["code"] == "tool_error"
    assert data["error"]["retryable"] is True
    assert len(data["error"]["message"]) == ERROR_MESSAGE_CAP


def test_status_frame_full_snapshot_shape() -> None:
    frame = json.loads(status_frame([STATUS_ENTRY]))
    assert frame == {"type": "status", "data": {"servers": [STATUS_ENTRY]}}


def test_parse_tool_call() -> None:
    frame = parse_inbound(
        '{"type":"tool_call","data":{"tool":"mock.echo","args":{"text":"hi"},"call_id":"c1"}}'
    )
    assert isinstance(frame, ToolCallIn)
    assert frame.tool == "mock.echo"
    assert frame.args == {"text": "hi"}
    assert frame.call_id == "c1"


def test_parse_tool_call_defaults_args() -> None:
    frame = parse_inbound('{"type":"tool_call","data":{"tool":"mock.echo","call_id":"c1"}}')
    assert isinstance(frame, ToolCallIn)
    assert frame.args == {}


def test_parse_hello_ack_pong_error_unknown() -> None:
    assert parse_inbound('{"type":"hello_ack","data":{"protocol_version":1}}') == Ack(
        protocol_version=1
    )
    assert parse_inbound('{"type":"pong","data":{}}') == Pong()
    error = parse_inbound('{"type":"error","data":{"code":"nope","message":"' + "y" * 900 + '"}}')
    assert isinstance(error, ErrorIn)
    assert error.code == "nope"
    assert len(error.message) == ERROR_MESSAGE_CAP
    assert parse_inbound('{"type":"status_ack","data":{}}') == Unknown(type="status_ack")


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff\xfe garbage",
        "not json",
        "[1,2,3]",
        '{"data":{}}',
        '{"type":"tool_call","data":{"args":{}}}',
        '{"type":"tool_call","data":"nope"}',
        '{"type":"hello_ack","data":{}}',
        '{"type":42,"data":{}}',
    ],
)
def test_parse_inbound_never_raises(raw: str | bytes) -> None:
    assert isinstance(parse_inbound(raw), Invalid)


def test_frames_validate_against_cloud_models() -> None:
    """Drift guard: what we emit must pass the cloud's strict ingress models."""
    solus_frames = pytest.importorskip("solus_api.bridge.frames")
    shapes = pytest.importorskip("solus_api.agent.tools.shapes")

    hello = json.loads(
        hello_frame(companion_version="0.1.0", instance_id="a" * 32, servers=SERVERS)
    )
    solus_frames.HelloData.model_validate(hello["data"])

    ok = json.loads(tool_result_ok("c1", {"result": "hi"}))
    shapes.ToolResult.model_validate(ok["data"])

    failed = json.loads(tool_result_error("c2", "not_found", "no such tool", retryable=False))
    shapes.ToolResult.model_validate(failed["data"])

    status = json.loads(status_frame([STATUS_ENTRY]))
    solus_frames.StatusData.model_validate(status["data"])
