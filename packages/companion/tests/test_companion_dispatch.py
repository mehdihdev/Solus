"""Dispatch: tool_call → exactly one tool_result, with a fake supervisor."""

import asyncio
import json
from typing import Any

from mcp.types import CallToolResult, ImageContent, TextContent
from solus_companion.artifacts import (
    REASON_PATH_ESCAPES,
    REASON_UPLOAD_UNAVAILABLE,
    ArtifactStore,
    ArtifactUploadError,
)
from solus_companion.dispatch import NON_TEXT_NOTE, Dispatcher, map_result
from solus_companion.frames import ToolCallIn
from solus_companion.supervisor import UnknownToolError


class FakeSupervisor:
    def __init__(
        self,
        result: CallToolResult | None = None,
        exc: Exception | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.result = result
        self.exc = exc
        self.gate = gate
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call_tool(self, server: str, tool: str, args: dict[str, Any]) -> CallToolResult:
        self.calls.append((server, tool, args))
        if self.gate is not None:
            await self.gate.wait()
        if self.exc is not None:
            raise self.exc
        assert self.result is not None
        return self.result


class Sink:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def __call__(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def _call(call_id: str = "c1", tool: str = "mock.echo") -> ToolCallIn:
    return ToolCallIn(tool=tool, args={"text": "hi"}, call_id=call_id)


async def test_structured_content_passes_through() -> None:
    fake = FakeSupervisor(
        result=CallToolResult(content=[], structuredContent={"result": "hi"}, isError=False)
    )
    sink = Sink()
    dispatcher = Dispatcher(fake, sink)
    dispatcher.handle_tool_call(_call())
    await dispatcher.wait_idle()
    assert sink.sent == [
        {
            "type": "tool_result",
            "data": {"call_id": "c1", "ok": True, "value": {"result": "hi"}},
        }
    ]
    # split on the FIRST dot only
    assert fake.calls == [("mock", "echo", {"text": "hi"})]


async def test_composed_name_splits_on_first_dot() -> None:
    fake = FakeSupervisor(
        result=CallToolResult(content=[], structuredContent={"ok": 1}, isError=False)
    )
    dispatcher = Dispatcher(fake, Sink())
    dispatcher.handle_tool_call(_call(tool="mock.echo.v2"))
    await dispatcher.wait_idle()
    assert fake.calls == [("mock", "echo.v2", {"text": "hi"})]


async def test_unknown_tool_maps_to_not_found() -> None:
    fake = FakeSupervisor(exc=UnknownToolError("unknown tool mock.nope"))
    sink = Sink()
    dispatcher = Dispatcher(fake, sink)
    dispatcher.handle_tool_call(_call(tool="mock.nope"))
    await dispatcher.wait_idle()
    error = sink.sent[0]["data"]["error"]
    assert error["code"] == "not_found"
    assert error["retryable"] is False


async def test_undotted_name_is_not_found_without_calling() -> None:
    fake = FakeSupervisor()
    sink = Sink()
    dispatcher = Dispatcher(fake, sink)
    dispatcher.handle_tool_call(_call(tool="nodot"))
    await dispatcher.wait_idle()
    assert sink.sent[0]["data"]["error"]["code"] == "not_found"
    assert fake.calls == []


async def test_is_error_result_maps_to_tool_error() -> None:
    fake = FakeSupervisor(
        result=CallToolResult(
            content=[TextContent(type="text", text="boom went the server")], isError=True
        )
    )
    sink = Sink()
    dispatcher = Dispatcher(fake, sink)
    dispatcher.handle_tool_call(_call())
    await dispatcher.wait_idle()
    error = sink.sent[0]["data"]["error"]
    assert error["code"] == "tool_error"
    assert error["message"] == "boom went the server"
    assert error["retryable"] is False


async def test_transport_exception_maps_to_retryable_tool_error() -> None:
    fake = FakeSupervisor(exc=RuntimeError("pipe broke"))
    sink = Sink()
    dispatcher = Dispatcher(fake, sink)
    dispatcher.handle_tool_call(_call())
    await dispatcher.wait_idle()
    error = sink.sent[0]["data"]["error"]
    assert error["code"] == "tool_error"
    assert error["retryable"] is True


async def test_non_text_content_is_never_inlined() -> None:
    fake = FakeSupervisor(
        result=CallToolResult(
            content=[
                TextContent(type="text", text="caption"),
                ImageContent(type="image", data="QklOQVJZU0VOVElORUw=", mimeType="image/png"),
            ],
            isError=False,
        )
    )
    sink = Sink()
    dispatcher = Dispatcher(fake, sink)
    dispatcher.handle_tool_call(_call(tool="mock.pic"))
    await dispatcher.wait_idle()
    value = sink.sent[0]["data"]["value"]
    assert value["content"][0]["text"] == "caption"
    # SOLUS-CAD-00c: the block now carries a HANDLE instead of a dropped note —
    # but the bytes themselves still never ride the frame.
    block = value["content"][1]
    assert block["type"] == "image"
    assert block["inlined"] is False
    assert block["artifact_id"]
    assert block["media_type"] == "image/png"
    assert block["size_bytes"] == len(b"BINARYSENTINEL")
    assert "QklOQVJZU0VOVElORUw=" not in json.dumps(sink.sent)
    assert "BINARYSENTINEL" not in json.dumps(sink.sent)


async def test_duplicate_live_call_id_is_dropped() -> None:
    gate = asyncio.Event()
    fake = FakeSupervisor(
        result=CallToolResult(content=[], structuredContent={"n": 1}, isError=False), gate=gate
    )
    sink = Sink()
    dispatcher = Dispatcher(fake, sink)
    dispatcher.handle_tool_call(_call(call_id="dup"))
    await asyncio.sleep(0.01)
    dispatcher.handle_tool_call(_call(call_id="dup"))  # protocol violation: dropped
    gate.set()
    await dispatcher.wait_idle()
    assert len(sink.sent) == 1
    assert len(fake.calls) == 1


class FakeUploader:
    """Programmable stand-in for artifacts.ArtifactUploader (structural)."""

    def __init__(
        self,
        ref: dict[str, Any] | None = None,
        exc: ArtifactUploadError | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.ref = (
            ref if ref is not None else {"artifact_id": "a1", "uri": "/u", "storage": "local"}
        )
        self.exc = exc
        self.gate = gate
        self.calls: list[dict[str, str]] = []

    async def upload(
        self, *, server: str, artifact_path: str, source_tool: str, call_id: str
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "server": server,
                "artifact_path": artifact_path,
                "source_tool": source_tool,
                "call_id": call_id,
            }
        )
        if self.gate is not None:
            await self.gate.wait()
        if self.exc is not None:
            raise self.exc
        return self.ref


def _export_value(**overrides: Any) -> dict[str, Any]:
    """The locked kicad export_netlist shape (exactly one of content/artifact_path)."""
    value: dict[str, Any] = {
        "format": "kicadxml",
        "filename": "netlist.kicadxml",
        "bytes": 2_000_000,
        "content": None,
        "artifact_path": "out/netlist.kicadxml",
        "degraded": False,
        "reason": None,
    }
    value.update(overrides)
    return value


async def test_artifact_path_is_rewritten_to_artifact_ref() -> None:
    fake = FakeSupervisor(
        result=CallToolResult(content=[], structuredContent=_export_value(), isError=False)
    )
    uploader = FakeUploader()
    sink = Sink()
    dispatcher = Dispatcher(fake, sink, uploader=uploader)
    dispatcher.handle_tool_call(_call(call_id="c-art", tool="kicad.export_netlist"))
    await dispatcher.wait_idle()
    [frame] = sink.sent
    assert frame["data"]["ok"] is True
    value = frame["data"]["value"]
    assert "artifact_path" not in value  # stripped
    assert value["artifact_ref"] == uploader.ref  # inserted
    # the rest of the locked shape is preserved verbatim
    assert value["format"] == "kicadxml"
    assert value["filename"] == "netlist.kicadxml"
    assert value["bytes"] == 2_000_000
    assert value["content"] is None
    assert value["degraded"] is False
    # the uploader received the dispatched identifiers, not client-asserted ones
    assert uploader.calls == [
        {
            "server": "kicad",
            "artifact_path": "out/netlist.kicadxml",
            "source_tool": "kicad.export_netlist",
            "call_id": "c-art",
        }
    ]


async def test_upload_failure_is_retryable_error_with_stable_reason() -> None:
    fake = FakeSupervisor(
        result=CallToolResult(content=[], structuredContent=_export_value(), isError=False)
    )
    uploader = FakeUploader(exc=ArtifactUploadError(REASON_PATH_ESCAPES))
    sink = Sink()
    dispatcher = Dispatcher(fake, sink, uploader=uploader)
    dispatcher.handle_tool_call(_call(tool="kicad.export_netlist"))
    await dispatcher.wait_idle()
    [frame] = sink.sent
    assert frame["data"]["ok"] is False
    assert "value" not in frame["data"]  # no partial fields
    error = frame["data"]["error"]
    assert error["code"] == "tool_error"
    assert error["message"] == REASON_PATH_ESCAPES
    assert error["retryable"] is True


async def test_artifact_path_without_uploader_fails_closed() -> None:
    fake = FakeSupervisor(
        result=CallToolResult(content=[], structuredContent=_export_value(), isError=False)
    )
    sink = Sink()
    dispatcher = Dispatcher(fake, sink)  # no uploader wired
    dispatcher.handle_tool_call(_call(tool="kicad.export_netlist"))
    await dispatcher.wait_idle()
    [frame] = sink.sent
    error = frame["data"]["error"]
    assert error["message"] == REASON_UPLOAD_UNAVAILABLE
    assert error["retryable"] is True
    # the local path is NEVER forwarded upstream
    assert "out/netlist.kicadxml" not in json.dumps(sink.sent)


async def test_content_branch_passes_through_untouched() -> None:
    value = _export_value(content="<netlist/>", artifact_path=None, bytes=10)
    fake = FakeSupervisor(result=CallToolResult(content=[], structuredContent=value, isError=False))
    uploader = FakeUploader()
    sink = Sink()
    dispatcher = Dispatcher(fake, sink, uploader=uploader)
    dispatcher.handle_tool_call(_call(tool="kicad.export_netlist"))
    await dispatcher.wait_idle()
    assert sink.sent[0]["data"]["value"] == value  # verbatim, null artifact_path kept
    assert uploader.calls == []


async def test_degraded_result_passes_through_untouched() -> None:
    value = _export_value(content=None, artifact_path=None, degraded=True, reason="no kicad-cli")
    fake = FakeSupervisor(result=CallToolResult(content=[], structuredContent=value, isError=False))
    uploader = FakeUploader()
    sink = Sink()
    dispatcher = Dispatcher(fake, sink, uploader=uploader)
    dispatcher.handle_tool_call(_call(tool="kicad.export_netlist"))
    await dispatcher.wait_idle()
    assert sink.sent[0]["data"]["value"] == value
    assert uploader.calls == []


async def test_artifact_upload_in_flight_never_sends_after_disconnect() -> None:
    """Contract §5: a reconnect is a new session — nothing is buffered across it."""
    gate = asyncio.Event()  # never set before cancel: the upload hangs
    fake = FakeSupervisor(
        result=CallToolResult(content=[], structuredContent=_export_value(), isError=False)
    )
    uploader = FakeUploader(gate=gate)
    sink = Sink()
    dispatcher = Dispatcher(fake, sink, uploader=uploader)
    dispatcher.handle_tool_call(_call(call_id="c-up", tool="kicad.export_netlist"))
    await asyncio.sleep(0.01)
    assert len(uploader.calls) == 1  # upload started
    dispatcher.cancel_all()
    gate.set()  # upload "completes" only after the disconnect
    await dispatcher.wait_idle()
    await asyncio.sleep(0.01)
    assert sink.sent == []


async def test_cancel_all_sends_nothing_afterward() -> None:
    gate = asyncio.Event()  # never set: the call hangs until cancelled
    fake = FakeSupervisor(
        result=CallToolResult(content=[], structuredContent={"n": 1}, isError=False), gate=gate
    )
    sink = Sink()
    dispatcher = Dispatcher(fake, sink)
    dispatcher.handle_tool_call(_call(call_id="c-hung"))
    await asyncio.sleep(0.01)
    dispatcher.cancel_all()
    await dispatcher.wait_idle()
    await asyncio.sleep(0.01)
    assert sink.sent == []
    # and new calls after the disconnect are dropped too
    dispatcher.handle_tool_call(_call(call_id="c-late"))
    await dispatcher.wait_idle()
    assert sink.sent == []


async def test_a_block_too_large_to_stage_degrades_to_a_note_not_a_failure() -> None:
    """The fallback CAD-00c left behind: staging has a per-artifact budget, and a
    block over it must not fail the tool call — the caller still gets its text
    content plus a note saying the bytes were omitted.

    Uncovered until the SOLUSDEV-100 merge, which is when it was noticed: the
    only reference to `NON_TEXT_NOTE` in the suite was an import.
    """
    fake = FakeSupervisor(
        CallToolResult(
            content=[
                TextContent(type="text", text="caption"),
                ImageContent(type="image", data="QklOQVJZU0VOVElORUw=", mimeType="image/png"),
            ]
        )
    )
    sink = Sink()
    # One byte of headroom short of the payload, so staging refuses it.
    dispatcher = Dispatcher(fake, sink, ArtifactStore(max_artifact_bytes=1))

    dispatcher.handle_tool_call(_call(tool="mock.pic"))
    await dispatcher.wait_idle()

    value = sink.sent[0]["data"]["value"]
    assert sink.sent[0]["type"] == "tool_result"
    assert value["content"][0]["text"] == "caption"
    block = value["content"][1]
    assert block["type"] == "image"
    assert block["inlined"] is False
    assert "artifact_id" not in block  # nothing was staged
    assert "exceeds" in block["note"]  # says WHY, rather than a generic omission
    # The bytes still never ride the frame, degraded or not.
    assert "BINARYSENTINEL" not in json.dumps(sink.sent)


async def test_without_a_store_a_non_text_block_degrades_to_the_generic_note() -> None:
    """`map_result`'s pre-CAD-00c behaviour, still reachable: callers that stage
    nothing get a note instead of a handle, and never the bytes."""
    result = CallToolResult(
        content=[ImageContent(type="image", data="QklOQVJZU0VOVElORUw=", mimeType="image/png")]
    )

    frame = json.loads(map_result("call-1", result))

    assert frame["data"]["value"]["content"][0] == {
        "type": "image",
        "inlined": False,
        "note": NON_TEXT_NOTE,
    }
    assert "BINARYSENTINEL" not in json.dumps(frame)
