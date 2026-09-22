"""Approved authoring observations cannot be replaced or reused at execution."""

import asyncio
import copy
import uuid
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from solus_api.agent import confirmations
from solus_api.agent.tools import onshape_tools
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.onshape_cut import CUT_OPERATIONS
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import ConfirmationStatus
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

ARGS: dict[str, Any] = {
    "document_id": "document",
    "workspace_id": "workspace",
    "element_id": "studio",
    "sketch_feature_id": "sketch",
    "part_id": "part",
    "name": "Cut",
    "depth_mm": 2.0,
    "opposite_direction": False,
}
ROWS = [{"label": "Microversion", "before": None, "after": "version1"}]


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Any:
    state = SimpleNamespace(rows=copy.deepcopy(ROWS), failure=False, writes=0)
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    monkeypatch.setattr(connector, "get_json", AsyncMock(return_value={"name": "Fixture"}))
    monkeypatch.setattr(
        onshape_tools,
        "_prepare",
        AsyncMock(
            return_value=(
                connector,
                Credentials(token="fixture"),
                SimpleNamespace(config={"documents": ["document"]}),
            )
        ),
    )

    async def refresh(*args: Any, **kwargs: Any) -> Any:
        return await args[6](Credentials(token="fixture"))

    monkeypatch.setattr(onshape_tools, "_run_with_refresh", refresh)

    async def preview(*args: Any) -> Any:
        if state.failure:
            raise ConnectorError("api_error", "Unavailable")
        return copy.deepcopy(state.rows)

    async def run(*args: Any) -> Any:
        from solus_api.connectors.onshape_confirmation import require_matching_preview

        require_matching_preview(state.rows)
        state.writes += 1
        return {"applied": True}

    def build(name: str = "onshape.extrude_cut") -> Any:
        operation = replace(CUT_OPERATIONS[0], name=name, preview=preview, run=run)
        return cast(
            InProcessTool,
            onshape_tools._build_tool(
                operation,
                async_sessionmaker(),
                uuid.uuid4(),
                InMemorySecretStore(),
                ConnectorRegistry(),
            ),
        )

    state.build = build
    state.tool = build()
    state.registry = ToolRegistry()
    state.registry.register(state.tool)
    return state


@pytest.mark.parametrize("name", ["onshape.extrude_cut", "onshape.create_circle_sketch"])
def test_new_authoring_requires_complete_preview(harness: Any, name: str) -> None:
    assert getattr(harness.build(name), "requires_complete_preview", False) is True


async def test_failed_preview_does_not_park_an_argument_only_card(harness: Any) -> None:
    harness.failure = True
    db = AsyncMock(spec=AsyncSession)
    parked = await confirmations.request_confirmation(
        db,
        harness.registry,
        ToolCall(tool="onshape.extrude_cut", args=ARGS),
        project_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )
    assert parked is not None and parked.confirmation_id is None and not parked.result.ok
    db.add.assert_not_called()
    assert harness.writes == 0


async def test_missing_approval_preview_refuses_legacy_argument_card(harness: Any) -> None:
    harness.failure = True
    row = SimpleNamespace(
        status=ConfirmationStatus.PENDING,
        expires_at=confirmations.utcnow() + confirmations.CONFIRMATION_TTL,
        tool="onshape.extrude_cut",
        args=ARGS,
        preview=confirmations._argument_rows(ARGS),
        id=uuid.uuid4(),
    )
    db = AsyncMock(spec=AsyncSession)
    db.scalar.return_value = row
    result = await confirmations.decide_confirmation(
        db,
        harness.registry,
        row.id,
        approve=True,
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )
    assert not result.ok and row.status is ConfirmationStatus.STALE
    assert harness.writes == 0


async def test_execution_without_preview_refuses_before_operation(harness: Any) -> None:
    with pytest.raises(ToolException):
        await harness.tool.invoke(ARGS)
    assert harness.writes == 0


@pytest.mark.parametrize("field", ["Microversion", "Specification", "Workspace"])
async def test_execution_refuses_changed_observation_before_write(harness: Any, field: str) -> None:
    harness.rows = [{"label": field, "before": None, "after": "approved"}]
    await harness.tool.preview(ARGS)
    harness.rows[0]["after"] = "changed"
    result = await harness.registry.invoke(ToolCall(tool="onshape.extrude_cut", args=ARGS))
    assert not result.ok and result.error is not None and not result.error.retryable
    assert harness.writes == 0


async def test_registry_child_task_consumes_ticket_once(harness: Any) -> None:
    await harness.tool.preview(ARGS)
    call = ToolCall(tool="onshape.extrude_cut", args=ARGS)
    first = await harness.registry.invoke(call)
    second = await harness.registry.invoke(call)
    assert first.ok and not second.ok and harness.writes == 1


async def test_changed_arguments_cannot_use_preview_ticket(harness: Any) -> None:
    await harness.tool.preview(ARGS)
    result = await harness.registry.invoke(
        ToolCall(
            tool="onshape.extrude_cut",
            args={**ARGS, "depth_mm": 3.0},
        )
    )
    assert not result.ok and harness.writes == 0


async def test_failed_repreview_invalidates_old_ticket(harness: Any) -> None:
    await harness.tool.preview(ARGS)
    harness.failure = True
    with pytest.raises(ToolException):
        await harness.tool.preview(ARGS)
    harness.failure = False
    result = await harness.registry.invoke(ToolCall(tool="onshape.extrude_cut", args=ARGS))
    assert not result.ok and harness.writes == 0


async def test_other_bound_project_cannot_reuse_ticket(harness: Any) -> None:
    await harness.tool.preview(ARGS)
    with pytest.raises(ToolException):
        await harness.build().invoke(ARGS)
    assert harness.writes == 0


async def test_async_requests_do_not_share_observations(harness: Any) -> None:
    ready = asyncio.Event()
    finished = asyncio.Event()

    async def first() -> None:
        await harness.tool.preview(ARGS)
        ready.set()
        await finished.wait()
        result = await harness.registry.invoke(ToolCall(tool="onshape.extrude_cut", args=ARGS))
        assert result.ok

    async def second() -> None:
        await ready.wait()
        try:
            with pytest.raises(ToolException):
                await harness.tool.invoke(ARGS)
        finally:
            finished.set()

    await asyncio.gather(first(), second())
    assert harness.writes == 1


@pytest.mark.parametrize("extra", ["_documents", "_expected_preview", "_confirmation"])
async def test_public_arguments_cannot_inject_authority(harness: Any, extra: str) -> None:
    result = await harness.registry.invoke(
        ToolCall(
            tool="onshape.extrude_cut",
            args={**ARGS, extra: ROWS},
        )
    )
    assert not result.ok and harness.writes == 0


async def test_operation_helper_refuses_outside_execution_context() -> None:
    from solus_api.connectors.onshape_confirmation import require_matching_preview

    with pytest.raises(ConnectorError):
        require_matching_preview(ROWS)
