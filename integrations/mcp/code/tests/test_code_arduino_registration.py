"""Arduino transport preserves strict inputs, workspace binding and cancellation."""

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError
from solus_api.bridge.allowlist import requires_complete_preview, supports_dry_run

from code_paths import ALLOWLIST_YAML, overlay_module  # isort: skip

server = overlay_module("server")


async def test_arduino_schemas_are_closed_and_workspace_is_not_caller_selected() -> None:
    tools = {tool.name: tool for tool in await server.build_server().list_tools()}
    expected = {
        "arduino_probe": set(),
        "arduino_prepare": {"dry_run"},
        "arduino_compile": {"sketch", "fqbn", "dry_run"},
    }
    for name, properties in expected.items():
        schema = tools[name].inputSchema
        assert set(schema.get("properties", {})) == properties
        assert schema["additionalProperties"] is False
    assert set(tools["arduino_compile"].inputSchema["required"]) == {"sketch", "fqbn"}
    assert tools["arduino_compile"].inputSchema["properties"]["fqbn"]["const"] == "arduino:avr:uno"
    assert tools["arduino_prepare"].inputSchema["properties"]["dry_run"]["default"] is False


@pytest.mark.parametrize("args", [{"dry_run": "true"}, {"dry_run": True, "root": "/tmp"}])
async def test_arduino_transport_rejects_coercion_and_extra_fields(
    args: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    reached: list[dict[str, Any]] = []
    monkeypatch.setattr(
        server.arduino_toolchain, "arduino_prepare", lambda **kw: reached.append(kw)
    )
    with pytest.raises(ToolError):
        await server.build_server().call_tool("arduino_prepare", args)
    assert not reached


async def test_compile_binds_only_the_linked_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, dict[str, Any]]] = []
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))

    def compile_sketch(root: Path, **kw: Any) -> dict[str, Any]:
        calls.append((root, kw))
        return {"ok": True}

    monkeypatch.setattr(server.arduino_compile, "arduino_compile", compile_sketch)
    args = {"sketch": "Blink", "fqbn": "arduino:avr:uno", "dry_run": True}
    _, result = await server.build_server().call_tool("arduino_compile", args)
    assert result == {"ok": True}
    assert calls == [(tmp_path, args)]
    monkeypatch.delenv("SOLUS_MCP_WORKSPACE")
    with pytest.raises(ToolError, match="workspace_unavailable"):
        await server.build_server().call_tool("arduino_compile", args)
    assert len(calls) == 1


async def test_prepare_does_not_block_mcp_and_cancellation_reaches_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    stopped = threading.Event()

    def prepare(**_kw: Any) -> dict[str, Any]:
        event = server.arduino_process.CANCEL_EVENT.get()
        assert event is not None
        started.set()
        try:
            assert event.wait(3), "cancelled transport must stop its worker"
            return {"ok": False}
        finally:
            stopped.set()

    monkeypatch.setattr(server.arduino_toolchain, "arduino_prepare", prepare)
    task = asyncio.create_task(server.tool_arduino_prepare())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(stopped.wait, 1)
    finally:
        task.cancel()


def test_arduino_execution_requires_complete_approval_and_error_filing() -> None:
    tools = {item["name"]: item for item in yaml.safe_load(ALLOWLIST_YAML.read_text())["tools"]}
    for name, deadline in (("arduino_prepare", 630), ("arduino_compile", 150)):
        assert tools[name]["requires_confirmation"] is True
        assert tools[name]["files_errors"] is True
        assert tools[name]["timeout_seconds"] == deadline
        assert requires_complete_preview(f"code.{name}")
        assert supports_dry_run(f"code.{name}")
    assert tools["arduino_probe"]["requires_confirmation"] is False
    assert tools["arduino_probe"]["timeout_seconds"] == 15


async def test_artifact_summary_survives_actual_model_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import json

    from solus_api.agent.prompt import contain_result
    from solus_api.agent.tools.shapes import ToolCall, ToolResult

    digest = hashlib.sha256(b"verified build fixture").hexdigest()
    manifest = {
        "schema_version": 1,
        "build_id": "ec6a0d74-253a-4a77-ac4d-c950c24dca27",
        "fqbn": "arduino:avr:uno",
        "source_sha256": digest,
        "cli_sha256": digest,
        "toolchain_sha256": digest,
        "manifest_sha256": digest,
        "artifacts": [{"path": "Blink.ino.hex", "size_bytes": 42, "kind": "hex", "sha256": digest}],
    }
    original = json.dumps(manifest, sort_keys=True)
    result = server.arduino_compile.with_artifact_summary(
        {
            "ok": True,
            "started": True,
            "exit_code": 0,
            "stdout_tail": "x" * 16000,
            "stderr_tail": "",
        },
        manifest,
    )
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(server.arduino_compile, "arduino_compile", lambda **kwargs: result)
    args = {"sketch": "Blink", "fqbn": "arduino:avr:uno"}
    _, delivered = await server.build_server().call_tool("arduino_compile", args)
    outcome = contain_result(
        ToolCall(tool="code.arduino_compile", args=args, call_id="compile"),
        ToolResult.success("compile", delivered),
    )
    # The log tail is allowed to truncate; the leading summary must be a whole
    # JSON value before it, including every public artifact integrity identity.
    prefix = '{"ok":true,"value":{"artifact_summary":'
    assert outcome.content.startswith(prefix)
    summary, _ = json.JSONDecoder().raw_decode(outcome.content[len(prefix) :])
    assert summary == result["artifact_summary"]
    displayed = ":".join(digest[index : index + 16] for index in range(0, 64, 16))
    assert summary["source_fingerprint"] == displayed
    assert summary["toolchain_fingerprint"] == displayed
    assert summary["manifest_fingerprint"] == displayed
    assert summary["artifacts"][0]["fingerprint"] == displayed
    assert json.dumps(manifest, sort_keys=True) == original
    assert delivered["artifact_manifest"] == manifest


async def test_unrenderable_artifact_summary_is_refused_at_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    digest = hashlib.sha256(b"verified oversized summary fixture").hexdigest()
    manifest = {
        "build_id": "ec6a0d74-253a-4a77-ac4d-c950c24dca27",
        "fqbn": "arduino:avr:uno",
        "source_sha256": digest,
        "toolchain_sha256": digest,
        "manifest_sha256": digest,
        "artifacts": [
            {"path": "<" * 200 + f"{index}.hex", "size_bytes": 42, "kind": "hex", "sha256": digest}
            for index in range(3)
        ],
    }
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(
        server.arduino_compile,
        "arduino_compile",
        lambda **kwargs: server.arduino_compile.with_artifact_summary(
            {"ok": True, "started": True, "exit_code": 0}, manifest
        ),
    )
    with pytest.raises(ToolError, match="resource_limit"):
        await server.build_server().call_tool(
            "arduino_compile", {"sketch": "Blink", "fqbn": "arduino:avr:uno"}
        )
