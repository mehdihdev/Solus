"""SOLUSDEV-249: the hello inventory has its own cap (found in the live run — three
vendored servers' schemas overflow the 16 KiB control cap, and the companion was
closed as `update required` on every machine with a linked workspace)."""

from __future__ import annotations

import json

from solus_api.bridge.frames import FrameViolation, InboundFrame, parse_frame

CONTROL = 16 * 1024
RESULT = 1024 * 1024
HELLO = 256 * 1024


def _hello(schema_bytes: int) -> str:
    tool = {
        "name": "scan_folder",
        "description": "x" * schema_bytes,
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
    }
    return json.dumps(
        {
            "type": "hello",
            "data": {
                "protocol_version": 1,
                "companion_version": "0.1.0",
                "companion_instance_id": "a" * 32,
                "servers": [{"server": "local", "tools": [tool]}],
            },
        }
    )


def test_a_realistic_hello_passes_under_its_own_cap() -> None:
    raw = _hello(20_000)  # ≈ Altium + KiCad + local
    assert len(raw) > CONTROL
    frame = parse_frame(raw, control_cap=CONTROL, tool_result_cap=RESULT, hello_cap=HELLO)
    assert isinstance(frame, InboundFrame)
    assert frame.type == "hello"


def test_without_a_hello_cap_the_control_cap_still_applies() -> None:
    frame = parse_frame(_hello(20_000), control_cap=CONTROL, tool_result_cap=RESULT)
    assert isinstance(frame, FrameViolation)
    assert frame.kind == "oversize"


def test_a_huge_hello_is_still_refused() -> None:
    frame = parse_frame(
        _hello(300_000), control_cap=CONTROL, tool_result_cap=RESULT, hello_cap=HELLO
    )
    assert isinstance(frame, FrameViolation)


def test_other_control_frames_keep_the_small_cap() -> None:
    raw = json.dumps({"type": "status", "data": {"servers": [], "pad": "x" * 20_000}})
    frame = parse_frame(raw, control_cap=CONTROL, tool_result_cap=RESULT, hello_cap=HELLO)
    assert isinstance(frame, FrameViolation)
    assert frame.kind == "oversize"


def test_hello_identity_fields_are_bounded() -> None:
    """Security review M2: instance id and version are companion free text that
    reach a DB row and an API response — bounded at 64 chars, id charset-limited."""
    import json as _json

    def _with(**over: str) -> str:
        data = _json.loads(_hello(10))
        data["data"].update(over)
        return _json.dumps(data)

    assert isinstance(
        parse_frame(_with(), control_cap=CONTROL, tool_result_cap=RESULT, hello_cap=HELLO),
        InboundFrame,
    )
    for bad in (
        {"companion_instance_id": "x" * 65},
        {"companion_instance_id": "not hex/or safe"},
        {"companion_instance_id": ""},
        {"companion_version": "v" * 65},
    ):
        frame = parse_frame(
            _with(**bad), control_cap=CONTROL, tool_result_cap=RESULT, hello_cap=HELLO
        )
        assert isinstance(frame, FrameViolation), bad
