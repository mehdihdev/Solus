"""The file-only machine builtin preserves confinement and bridge behavior."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from mcp.types import CallToolResult, TextContent
from solus_companion.dispatch import Dispatcher
from solus_companion.frames import ToolCallIn
from solus_companion.machine import actions
from solus_companion.machine.actions import (
    READ_CAP_BYTES,
    WRITE_CAP_BYTES,
    MachineActionError,
    confine,
)
from solus_companion.machine.server import TOOL_NAMES, MachineServer
from solus_companion.supervisor import Supervisor, UnknownToolError

REPO_ROOT = Path(__file__).resolve().parents[3]
ALLOWLIST = REPO_ROOT / "integrations" / "mcp" / "machine" / "allowlist.yaml"


def test_confine_accepts_inside_and_refuses_dotdot(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert confine(tmp_path, "src") == (tmp_path / "src").resolve()
    assert confine(tmp_path, "src/../src") == (tmp_path / "src").resolve()
    with pytest.raises(MachineActionError, match="outside the workspace"):
        confine(tmp_path, "../etc/passwd")
    with pytest.raises(MachineActionError, match="outside the workspace"):
        confine(tmp_path, "/etc/passwd")


def test_confine_refuses_symlink_escape(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "link").symlink_to(outside)
    with pytest.raises(MachineActionError, match="outside the workspace"):
        confine(ws, "link/x.txt")


def test_read_file_text_binary_and_cap(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("héllo", encoding="utf-8")
    out = actions.read_file(tmp_path, "a.txt")
    assert out == {"path": "a.txt", "content": "héllo", "encoding": "utf-8", "size_bytes": 6}
    (tmp_path / "b.bin").write_bytes(b"\x00\x01")
    assert actions.read_file(tmp_path, "b.bin")["encoding"] == "base64"
    (tmp_path / "big").write_bytes(b"x" * (READ_CAP_BYTES + 1))
    with pytest.raises(MachineActionError, match="1 MiB"):
        actions.read_file(tmp_path, "big")
    with pytest.raises(MachineActionError, match="outside the workspace"):
        actions.read_file(tmp_path, "../x")


def test_write_file_atomic_create_dirs_and_cap(tmp_path: Path) -> None:
    plan = actions.plan_write_file(tmp_path, "sub/dir/f.txt", "hi", create_dirs=True)
    out = actions.write_file(
        tmp_path, "sub/dir/f.txt", "hi", create_dirs=True, expected_fingerprint=plan["fingerprint"]
    )
    assert out["path"] == "sub/dir/f.txt"
    assert out["bytes_written"] == 2
    assert out["verified"] is True
    assert (tmp_path / "sub/dir/f.txt").read_text() == "hi"
    assert [p.name for p in (tmp_path / "sub/dir").iterdir()] == ["f.txt"]  # no temp left
    with pytest.raises(MachineActionError, match="does not exist"):
        actions.plan_write_file(tmp_path, "nope/f.txt", "hi", create_dirs=False)
    with pytest.raises(MachineActionError, match="200 KB"):
        actions.plan_write_file(tmp_path, "f.txt", "x" * (WRITE_CAP_BYTES + 1), create_dirs=False)


def _allowlist_names() -> set[str]:
    """The Solus-owned allowlist IS the tool namespace: the cloud registers what
    is listed there and nothing else, so an inventory that drifts from it either
    advertises a tool that will be silently skipped or hides one the cloud
    expects. Read the yaml itself, not a copy."""
    if not ALLOWLIST.is_file():
        pytest.skip("integrations/mcp/machine/allowlist.yaml not yet written by the API lane")
    loaded = yaml.safe_load(ALLOWLIST.read_text())
    assert loaded["server"] == "machine"
    return {tool["name"] for tool in loaded["tools"]}


def test_inventory_matches_allowlist_and_schema_shape(tmp_path: Path) -> None:
    inv = MachineServer(tmp_path).inventory()
    assert inv is not None and inv["server"] == "machine"
    names = {t["name"] for t in inv["tools"]}
    assert names == TOOL_NAMES == {"read_file", "write_file", "read_code_file"}
    for tool in inv["tools"]:
        assert set(tool) == {"name", "description", "input_schema", "output_schema"}
        assert tool["input_schema"]["type"] == "object"
        assert tool["input_schema"].get("additionalProperties") is False
        assert "$ref" not in json.dumps(tool["input_schema"])
        assert tool["output_schema"]["type"] == "object"
    assert names == _allowlist_names()


def test_no_workspace_advertises_nothing_and_fails_closed() -> None:
    server = MachineServer(None)
    assert server.inventory() is None
    assert server.status_entry()["detail"] == "no project workspace linked"


async def test_supervisor_routes_builtin_and_dispatcher(tmp_path: Path) -> None:
    server = MachineServer(tmp_path)
    sup = Supervisor((), builtins=(server,))
    assert [entry["server"] for entry in sup.inventory()] == ["machine"]
    assert sup.status_snapshot() == [server.status_entry()]
    assert sup.status_snapshot()[0]["state"] == "ready"
    with pytest.raises(UnknownToolError):
        await sup.call_tool("machine", "nope", {})
    sent: list[dict[str, Any]] = []

    async def send(raw: str) -> None:
        sent.append(json.loads(raw))

    dispatcher = Dispatcher(sup, send)
    call = ToolCallIn(tool="machine.read_file", args={"path": "../x"}, call_id="c1")
    dispatcher.handle_tool_call(call)
    await dispatcher.wait_idle()
    assert sent[0]["data"]["ok"] is False
    assert sent[0]["data"]["error"]["code"] == "tool_error"
    assert "outside the workspace" in sent[0]["data"]["error"]["message"]
    # ...and a SUCCESS maps through `map_result` exactly like a fork's would:
    # structuredContent becomes the result value verbatim.
    (tmp_path / "a.txt").write_text("hi")
    dispatcher.handle_tool_call(
        ToolCallIn(tool="machine.read_file", args={"path": "a.txt"}, call_id="c2")
    )
    await dispatcher.wait_idle()
    assert sent[1]["data"]["ok"] is True
    assert sent[1]["data"]["value"] == {
        "path": "a.txt",
        "content": "hi",
        "encoding": "utf-8",
        "size_bytes": 2,
    }


def test_supervisor_no_workspace_builtin_not_in_inventory() -> None:
    sup = Supervisor((), builtins=(MachineServer(None),))
    assert sup.inventory() == []
    assert sup.status_snapshot()[0]["name"] == "machine"


def _error_text(result: CallToolResult) -> str:
    return " ".join(b.text for b in result.content if isinstance(b, TextContent))


def test_machine_has_no_parallel_environment_executor(tmp_path: Path) -> None:
    inventory = MachineServer(tmp_path).inventory()
    assert inventory is not None
    assert {tool["name"] for tool in inventory["tools"]} == {
        "read_file",
        "write_file",
        "read_code_file",
    }
