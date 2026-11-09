"""Cloud-owned file writes bind complete native state to a one-use task ticket."""
# mypy: disable-error-code="no-untyped-def,no-untyped-call,method-assign"

import asyncio
from pathlib import Path
from typing import Any

import pytest
from mcp.types import TextContent
from solus_api.agent.tools.machine_writes import (
    CARD_ROWS,
    ROW_CHARS,
    build_machine_write_tool,
    card_rows,
)
from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.agent.tools.tool import ToolException
from solus_companion.machine.server import MachineServer


class Native:
    def __init__(self, root: Path) -> None:
        self.server = MachineServer(root)
        self.descriptor = ToolDescriptor(
            name="machine.write_file",
            description="Native write",
            params={},
            returns={},
            requires_confirmation=True,
        )
        self.calls: list[dict[str, Any]] = []

    async def invoke(self, args: dict[str, Any]) -> Any:
        self.calls.append(args)
        result = await self.server.call_tool("write_file", args)
        if result.isError:
            raise ToolException("Native write refused")
        return result.structuredContent


async def test_wrapper_schema_and_verified_write(tmp_path: Path) -> None:
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


async def test_missing_ticket_and_changed_args_refused(tmp_path: Path) -> None:
    raw = Native(tmp_path)
    tool = build_machine_write_tool(raw)
    args = {"path": "main.py", "content": "before"}
    with pytest.raises(ToolException):
        await tool.invoke(args)
    await tool.preview(args)
    with pytest.raises(ToolException):
        await tool.invoke({**args, "content": "different"})
    assert not (tmp_path / "main.py").exists()


async def test_intervening_native_preview_cannot_replace_cloud_approved_state(
    tmp_path: Path,
) -> None:
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


async def test_child_task_consumes_parent_ticket(tmp_path: Path) -> None:
    tool = build_machine_write_tool(Native(tmp_path))
    args = {"path": "main.py", "content": "print('once')"}
    await tool.preview(args)
    assert (await asyncio.create_task(tool.invoke(args)))["verified"] is True
    with pytest.raises(ToolException):
        await tool.invoke(args)


@pytest.mark.parametrize(
    "extra", [{"dry_run": False}, {"expected_fingerprint": "0" * 64}, {"auto": True}]
)
async def test_internal_fields_not_public_authority(tmp_path: Path, extra: dict[str, Any]) -> None:
    tool = build_machine_write_tool(Native(tmp_path))
    with pytest.raises(ToolException):
        await tool.preview({"path": "main.py", "content": "x", **extra})
    assert list(tmp_path.iterdir()) == []


async def test_file_changes_after_wrapper_recheck_still_refused_by_native(tmp_path: Path) -> None:
    target = tmp_path / "main.py"
    target.write_text("first")
    raw = Native(tmp_path)
    invoke = raw.invoke

    async def mutate_at_execution(args: dict[str, Any]) -> Any:
        if "expected_fingerprint" in args:
            target.write_text("external")
        return await invoke(args)

    raw.invoke = mutate_at_execution  # type: ignore[method-assign]
    tool = build_machine_write_tool(raw)
    args = {"path": "main.py", "content": "proposed"}
    await tool.preview(args)
    with pytest.raises(ToolException):
        await tool.invoke(args)
    assert target.read_text() == "external"


# --- SOLUSDEV-321 P6: the card's ceiling, and the read half of a read-modify-write ----------


class Telling(Native):
    """The native write, failing with the companion's own words, as the bridge relays them."""

    async def invoke(self, args: dict[str, Any]) -> Any:
        self.calls.append(args)
        result = await self.server.call_tool("write_file", args)
        if result.isError:
            said = result.content[0]
            raise ToolException(said.text if isinstance(said, TextContent) else "refused")
        return result.structuredContent


class Masked:
    """A write whose preview shows the file after sensitive-data filtering."""

    def __init__(self) -> None:
        self.descriptor = ToolDescriptor(
            name="machine.write_file", description="", params={}, returns={}
        )

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        fingerprint = ":".join(["0" * 16] * 4)
        return {
            "ok": True,
            "dry_run": True,
            "fingerprint": fingerprint,
            "preview": [
                {"label": "File", "before": None, "after": args["path"]},
                {"label": "File state fingerprint", "before": None, "after": fingerprint},
                {"label": "Content 1", "before": 'KEY = "[REDACTED]";\n', "after": ""},
            ],
        }


def test_a_card_holds_forty_rows_of_four_hundred_characters() -> None:
    """The bridge's `_diff_rows` bound and the companion's chunking, named once."""
    from solus_api.bridge.tool import _diff_rows

    row = {"label": "x", "before": None, "after": "y" * ROW_CHARS}
    assert (CARD_ROWS, ROW_CHARS) == (40, 400)
    assert _diff_rows([row] * CARD_ROWS) and not _diff_rows([row] * (CARD_ROWS + 1))
    assert not _diff_rows([{**row, "after": "y" * (ROW_CHARS + 1)}])
    assert (card_rows("", ""), card_rows("a" * 400, "b"), card_rows("", "c" * 401)) == (3, 3, 4)


async def test_current_text_reads_through_a_dry_run_and_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / "fw" / "main.ino"
    target.parent.mkdir()
    text = "void setup() {}\n" * 60
    target.write_text(text)
    raw = Telling(tmp_path)
    tool = build_machine_write_tool(raw)

    assert await tool.current_text("fw/main.ino") == text
    assert await tool.current_text("fw/new.ino") is None

    assert target.read_text() == text and not (tmp_path / "fw" / "new.ino").exists()
    assert raw.calls and all(c["dry_run"] is True and c["content"] == "" for c in raw.calls)


async def test_current_text_refuses_past_the_card_ceiling_naming_it(tmp_path: Path) -> None:
    (tmp_path / "big.ino").write_text("x" * (ROW_CHARS * (CARD_ROWS - 2) + 1))
    tool = build_machine_write_tool(Telling(tmp_path))
    with pytest.raises(ToolException) as refused:
        await tool.current_text("big.ino")
    assert f"{CARD_ROWS} rows of {ROW_CHARS} characters" in refused.value.message


async def test_current_text_refuses_a_file_the_filter_masked() -> None:
    """Rewriting a masked file would write the mask back over the real text."""
    tool = build_machine_write_tool(Masked())
    with pytest.raises(ToolException) as refused:
        await tool.current_text("keys.ino")
    assert "masked" in refused.value.message
