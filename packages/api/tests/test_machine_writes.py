"""Cloud-owned file writes bind complete native state to a one-use task ticket."""

import asyncio

import pytest
from solus_api.agent.tools.machine_writes import build_machine_write_tool
from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.agent.tools.tool import ToolException
from solus_companion.machine.server import MachineServer


class Native:
    def __init__(self, root):
        self.server = MachineServer(root)
        self.descriptor = ToolDescriptor(
            name="machine.write_file",
            description="Native write",
            params={},
            returns={},
            requires_confirmation=True,
        )
        self.calls = []

    async def invoke(self, args):
        self.calls.append(args)
        result = await self.server.call_tool("write_file", args)
        if result.isError:
            raise ToolException("Native write refused")
        return result.structuredContent


async def test_wrapper_schema_and_verified_write(tmp_path):
    raw = Native(tmp_path)
    tool = build_machine_write_tool(raw)
    properties = tool.descriptor.params["properties"]
    assert set(properties) == {"path", "content", "create_dirs"}
    assert tool.requires_complete_preview is True
    args = {"path": "main.py", "content": "print('hello')\n"}
    rows = await tool.preview(args)
    assert rows
    assert not (tmp_path / "main.py").exists()
    result = await tool.invoke(args)
    assert result["verified"] is True
    assert "expected_fingerprint" in raw.calls[-1]
    with pytest.raises(ToolException):
        await tool.invoke(args)


async def test_missing_ticket_and_changed_args_refused(tmp_path):
    raw = Native(tmp_path)
    tool = build_machine_write_tool(raw)
    args = {"path": "main.py", "content": "before"}
    with pytest.raises(ToolException):
        await tool.invoke(args)
    await tool.preview(args)
    with pytest.raises(ToolException):
        await tool.invoke({**args, "content": "different"})
    assert not (tmp_path / "main.py").exists()


async def test_intervening_native_preview_cannot_replace_cloud_approved_state(tmp_path):
    target = tmp_path / "main.py"
    target.write_text("first")
    raw = Native(tmp_path)
    tool = build_machine_write_tool(raw)
    args = {"path": "main.py", "content": "proposed"}
    await tool.preview(args)
    target.write_text("external")
    await raw.invoke({**args, "dry_run": True})
    with pytest.raises(ToolException):
        await tool.invoke(args)
    assert target.read_text() == "external"


async def test_child_task_consumes_parent_ticket(tmp_path):
    tool = build_machine_write_tool(Native(tmp_path))
    args = {"path": "main.py", "content": "print('once')"}
    await tool.preview(args)
    assert (await asyncio.create_task(tool.invoke(args)))["verified"] is True
    with pytest.raises(ToolException):
        await tool.invoke(args)


@pytest.mark.parametrize(
    "extra", [{"dry_run": False}, {"expected_fingerprint": "0" * 64}, {"auto": True}]
)
async def test_internal_fields_not_public_authority(tmp_path, extra):
    tool = build_machine_write_tool(Native(tmp_path))
    with pytest.raises(ToolException):
        await tool.preview({"path": "main.py", "content": "x", **extra})
    assert list(tmp_path.iterdir()) == []


async def test_file_changes_after_wrapper_recheck_still_refused_by_native(tmp_path):
    target = tmp_path / "main.py"
    target.write_text("first")
    raw = Native(tmp_path)
    invoke = raw.invoke

    async def mutate_at_execution(args):
        if "expected_fingerprint" in args:
            target.write_text("external")
        return await invoke(args)

    raw.invoke = mutate_at_execution
    tool = build_machine_write_tool(raw)
    args = {"path": "main.py", "content": "proposed"}
    await tool.preview(args)
    with pytest.raises(ToolException):
        await tool.invoke(args)
    assert target.read_text() == "external"
