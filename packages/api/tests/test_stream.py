"""SOL streaming event protocol (SOLUS-SYS-01).

Unit — no DB. Proves the `AgentEvent` envelope and its SSE encoding: the four
constructors carry the right payloads, a `tool_result` rides as the W0-04
`ToolResult` DATA (never a traceback), and `format_sse` emits a well-formed,
deterministic SSE frame the transport can write verbatim.
"""

import json

from solus_api.agent.stream import AgentEvent, AgentEventType, format_sse
from solus_api.agent.tools import ToolCall, ToolError, ToolErrorCode, ToolResult


def test_token_event_carries_text() -> None:
    event = AgentEvent.token("hello")
    assert event.type is AgentEventType.TOKEN
    assert event.data == {"text": "hello"}


def test_tool_call_event_carries_call_id_tool_and_args() -> None:
    call = ToolCall(tool="get_entity", args={"entity_id": "x"}, call_id="c1")
    event = AgentEvent.tool_call(call)
    assert event.type is AgentEventType.TOOL_CALL
    assert event.data == {"call_id": "c1", "tool": "get_entity", "args": {"entity_id": "x"}}


def test_tool_result_event_is_the_w004_envelope() -> None:
    result = ToolResult.success("c1", {"name": "LM358"})
    event = AgentEvent.tool_result(result)
    assert event.type is AgentEventType.TOOL_RESULT
    assert event.data["ok"] is True
    assert event.data["call_id"] == "c1"
    assert event.data["value"] == {"name": "LM358"}


def test_tool_result_failure_carries_structured_error_not_a_traceback() -> None:
    result = ToolResult.failure("c1", ToolError(code=ToolErrorCode.NOT_FOUND, message="nope"))
    event = AgentEvent.tool_result(result)
    assert event.data["ok"] is False
    assert event.data["error"]["code"] == "not_found"
    assert event.data["value"] is None


def test_message_and_error_events() -> None:
    msg = AgentEvent.message("done reasoning")
    assert msg.data == {"role": "assistant", "content": "done reasoning", "citations": []}
    cited = AgentEvent.message("grounded", citations=("[datasheet:x.pdf]",))
    assert cited.data["citations"] == ["[datasheet:x.pdf]"]
    err = AgentEvent.error("internal", "the turn failed")
    assert err.type is AgentEventType.ERROR
    assert err.data == {"code": "internal", "message": "the turn failed"}


def test_format_sse_is_a_wellformed_frame() -> None:
    frame = format_sse(AgentEvent.token("hi"))
    assert frame.startswith("event: token\n")
    assert frame.endswith("\n\n")
    body = frame.split("data: ", 1)[1].rstrip("\n")
    assert json.loads(body) == {"text": "hi"}


def test_format_sse_is_deterministic() -> None:
    event = AgentEvent.done(conversation_id="a", turn_id="b")
    assert format_sse(event) == format_sse(event)
    # keys are sorted → stable wire regardless of insertion order
    assert '"conversation_id":"a"' in format_sse(event)
