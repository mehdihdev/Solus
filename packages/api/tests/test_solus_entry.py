"""`add_solus_entry` — the first write builtin (SOLUSDEV-240). Ungated, scope-free
params, author=sol, and the registry's never-raises invariant on bad input."""

import uuid

from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.agent.tools import ToolCall, ToolRegistry
from solus_api.agent.tools.solus_entry import (
    ADD_SOLUS_ENTRY_DESCRIPTOR,
    build_add_solus_entry_tool,
)
from solus_api.models import SolusEntry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

SECTIONS = ("hardware", "details", "errors", "docs", "code")


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return project["id"], team["id"]


def test_add_solus_entry_descriptor_is_ungated_and_scope_free() -> None:
    assert ADD_SOLUS_ENTRY_DESCRIPTOR.requires_confirmation is False
    props = ADD_SOLUS_ENTRY_DESCRIPTOR.params["properties"]
    assert set(props) == {"section", "text"}
    assert props["section"]["enum"] == list(SECTIONS)
    assert ADD_SOLUS_ENTRY_DESCRIPTOR.params["additionalProperties"] is False


async def test_sol_files_an_entry_and_bad_input_never_raises(
    client: AsyncClient, alice_headers: dict[str, str], engine: AsyncEngine, db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    user = await me(client, alice_headers)
    registry = ToolRegistry()
    registry.register(
        build_add_solus_entry_tool(
            async_sessionmaker(engine, expire_on_commit=False),
            uuid.UUID(project_id),
            user_id=uuid.UUID(user["id"]),
        )
    )
    ok = await registry.invoke(
        ToolCall(
            call_id="c1",
            tool="add_solus_entry",
            args={"section": "errors", "text": "Servo bus browned out at 5 V"},
        )
    )
    assert ok.ok, ok.error
    assert ok.value is not None
    assert ok.value["section"] == "errors"
    row = await db.scalar(select(SolusEntry).where(SolusEntry.id == uuid.UUID(ok.value["id"])))
    assert row is not None
    assert row.author == "sol"
    assert row.created_by == uuid.UUID(user["id"])

    bad = await registry.invoke(
        ToolCall(call_id="c2", tool="add_solus_entry", args={"section": "secrets", "text": "x"})
    )
    assert bad.ok is False
    assert bad.error is not None
