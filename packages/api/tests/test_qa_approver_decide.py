"""Fixture-only QA approvals traverse the real authenticated HTTP decision gate."""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from conftest import create_project, create_team
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.confirmations import request_confirmation
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolDescriptor
from solus_api.agent.tools.tool import InProcessTool
from solus_api.deps import get_sol_registry
from solus_api.models import ConfirmationStatus, ToolConfirmation
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from scripts.qa_approver import QAApprover


@pytest.mark.parametrize("tool_disappears", [False, True])
async def test_real_decide_route_with_inert_flash_fixture(
    client: AsyncClient,
    app: FastAPI,
    engine: AsyncEngine,
    alice_headers: dict[str, str],
    tmp_path: Path,
    tool_disappears: bool,
) -> None:
    """Stored args execute once; a 200 tool-gone result is not success."""
    team = await create_team(client, alice_headers, "QA fixture")
    project = await create_project(client, alice_headers, team["id"], "QA fixture")
    me = await client.get("/api/v1/users/me", headers=alice_headers)
    user_id = UUID(me.json()["data"]["id"])
    records: list[dict[str, Any]] = []

    async def inert(args: dict[str, Any]) -> dict[str, Any]:
        records.append(args)
        return {"fixture_only": True}

    descriptor = ToolDescriptor(
        name="flash_device",
        description="Inert test fixture; never writes hardware",
        requires_confirmation=True,
        params={"type": "object"},
        returns={"type": "object"},
    )
    registry = ToolRegistry()
    tool = InProcessTool(descriptor, inert)
    registry.register(tool)
    args = {
        "target": "usb:fixture-bare-mcu",
        "artifact": "probe.hex",
        "sha256": "a" * 64,
        "size": 42,
    }
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        parked = await request_confirmation(
            db,
            registry,
            ToolCall(tool="flash_device", args=args, call_id="qa-fixture"),
            project_id=UUID(project["id"]),
            team_id=UUID(team["id"]),
            user_id=user_id,
        )
        await db.commit()
    assert parked is not None and parked.confirmation_id is not None
    event = {
        "confirmation_id": str(parked.confirmation_id),
        "tool": parked.tool,
        "args": parked.args,
        "summary": parked.summary,
        "preview": parked.preview,
    }

    async def attest(project_id: str, card: dict[str, Any]) -> bool:
        # Test-only attestor: the exact inert instance is trusted, not its name.
        async with maker() as db:
            row = await db.get(ToolConfirmation, UUID(card["confirmation_id"]))
            return bool(
                tool in registry.tools()
                and row is not None
                and row.project_id == UUID(project_id)
                and row.user_id == user_id
                and row.team_id == UUID(team["id"])
                and row.status is ConfirmationStatus.PENDING
                and row.tool == card["tool"]
                and row.args == card["args"]
                and row.summary == card["summary"]
                and row.preview == card["preview"]
            )

    app.dependency_overrides[get_sol_registry] = lambda: (
        ToolRegistry() if tool_disappears else registry
    )
    client.headers.update(alice_headers)
    try:
        approver = QAApprover(
            app_env="dev",
            usb_serial="fixture-bare-mcu",
            client=client,
            audit_path=tmp_path / "QA_APPROVALS_SOLUSDEV-262.md",
            verify_stored_action=attest,
        )
        assert await approver.approve(project["id"], event) is (not tool_disappears)
        assert not await approver.approve(project["id"], event)
        assert records == ([] if tool_disappears else [args])
        async with maker() as db:
            row = await db.get(ToolConfirmation, parked.confirmation_id)
            assert row is not None
            assert row.status is (
                ConfirmationStatus.PENDING if tool_disappears else ConfirmationStatus.APPROVED
            )
    finally:
        app.dependency_overrides.pop(get_sol_registry)
