"""Exact I3 plans must not disappear behind preview truncation."""

from typing import Any

import pytest
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.previews import preview_builder


async def test_late_argv_changes_alter_the_preview() -> None:
    plan: dict[str, Any] = {"ok": True, "argv": ["python", "a" * 490, "first"], "cwd": "."}

    async def read(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        assert tool == "code.plan"
        return plan

    preview = preview_builder("code.run", read)
    assert preview is not None
    before = await preview({})
    plan["argv"][-1] = "second"
    assert await preview({}) != before
    assert any("second" in str(row["after"]) for row in await preview({}))


@pytest.mark.parametrize(
    "plan",
    [None, {"ok": False, "reason": "unsupported"}, {"ok": True, "argv": ["x" * 26000], "cwd": "."}],
)
async def test_unavailable_refused_or_unrenderable_plan_fails_closed(plan: Any) -> None:
    async def read(tool: str, args: dict[str, Any]) -> Any:
        return plan

    preview = preview_builder("code.run", read)
    assert preview is not None
    with pytest.raises(ToolException):
        await preview({})
