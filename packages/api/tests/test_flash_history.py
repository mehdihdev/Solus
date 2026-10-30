"""SOLUSDEV-320 P5-T7: `agent/tools/flash_history.record_tool_history` — a clean
`code.arduino_upload` run is one `firmware.flashed` history row; nothing else is. The two
hook sites (the runner's post-dispatch hook, `confirmations.decide_confirmation`) are driven
for real below: a flash that only the helper knows about is not an audit trail."""

from __future__ import annotations

import uuid
from contextlib import nullcontext
from typing import Any

from conftest import create_project, create_team, me
from fixtures.fake_systems import FakeSolSystems
from httpx import AsyncClient
from solus_api.agent.confirmations import decide_confirmation, request_confirmation
from solus_api.agent.runtime import AgentRunContext, LlmRunner, build_dispatch
from solus_api.agent.tools import InProcessTool, ToolDescriptor, ToolRegistry
from solus_api.agent.tools.flash_history import record_tool_history
from solus_api.agent.tools.shapes import ToolCall, ToolError, ToolErrorCode, ToolResult
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import Activity, Domain, GraphEntity, Project, Team
from solus_api.orchestration.providers import ToolUse, Usage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_sol_reasoner import _funded_user

FLASH_OK = {"exit_code": 0, "port": "/dev/ttyACM0"}


def _flash_call(**args: Any) -> ToolCall:
    return ToolCall(tool="code.arduino_upload", args=args, call_id="c1")


async def test_arduino_upload_success_records_firmware_flashed(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project_id = (await create_project(client, alice_headers, team["id"]))["id"]
    alice = (await me(client, alice_headers))["id"]
    pid, user_id = uuid.UUID(project_id), uuid.UUID(alice)
    sketch = GraphEntity(project_id=pid, kind="arduino_sketch", domain=Domain.CODE, name="fw")
    db.add(sketch)
    await db.commit()
    ok = ToolResult.success("c1", {"exit_code": 0, "port": "/dev/ttyACM0"})
    maker = lambda: nullcontext(db)  # noqa: E731 — the confirmation path's own shape

    await record_tool_history(
        maker,
        project_id=pid,
        user_id=user_id,
        call=_flash_call(entity_id=str(sketch.id)),
        result=ok,
        executed=True,
    )
    # Not a flash that ran: parked, failed at the transport, failed after starting, other tool.
    await record_tool_history(
        maker, project_id=pid, user_id=user_id, call=_flash_call(), result=ok, executed=False
    )
    await record_tool_history(
        maker,
        project_id=pid,
        user_id=user_id,
        call=_flash_call(),
        result=ToolResult.failure("c1", ToolError(code=ToolErrorCode.TOOL_ERROR, message="x")),
        executed=True,
    )
    await record_tool_history(
        maker,
        project_id=pid,
        user_id=user_id,
        call=_flash_call(),
        result=ToolResult.success("c1", {"exit_code": 1}),
        executed=True,
    )
    await record_tool_history(
        maker,
        project_id=pid,
        user_id=user_id,
        call=ToolCall(tool="code.run", args={}, call_id="c2"),
        result=ok,
        executed=True,
    )
    # A foreign entity id in the model-proposed args is never stored.
    await record_tool_history(
        maker,
        project_id=pid,
        user_id=user_id,
        call=_flash_call(entity_id=str(uuid.uuid4())),
        result=ok,
        executed=True,
    )

    rows = list(
        await db.scalars(
            select(Activity)
            .where(Activity.project_id == pid, Activity.type == "firmware.flashed")
            .order_by(Activity.created_at)
        )
    )
    assert [r.entity_ids for r in rows] == [[str(sketch.id)], []]
    assert all(r.actor_id == user_id and r.domain == "code" for r in rows)
    assert rows[0].payload == {"tool": "code.arduino_upload", "port": "/dev/ttyACM0"}


async def _flash_rows(db: AsyncSession, project_id: uuid.UUID) -> list[Activity]:
    db.expire_all()
    return list(
        await db.scalars(
            select(Activity)
            .where(Activity.project_id == project_id, Activity.type == "firmware.flashed")
            .order_by(Activity.created_at)
        )
    )


def _flash_tool(*, gated: bool) -> InProcessTool:
    async def upload(args: dict[str, Any]) -> dict[str, Any]:
        return dict(FLASH_OK)

    return InProcessTool(
        ToolDescriptor(
            name="code.arduino_upload",
            description="Flash a sketch.",
            params={"type": "object"},
            returns={"type": "object"},
            requires_confirmation=gated,
            consent_summary="Flash the board" if gated else None,
            files_errors=True,
        ),
        upload,
    )


async def _flash_registry(*, gated: bool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(_flash_tool(gated=gated))
    return registry


async def _scope(
    client: AsyncClient, headers: dict[str, str], db: AsyncSession
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    await me(client, headers)
    team = await create_team(client, headers)
    project_id = uuid.UUID((await create_project(client, headers, team["id"]))["id"])
    user_id = uuid.UUID((await me(client, headers))["id"])
    sketch = GraphEntity(
        project_id=project_id, kind="arduino_sketch", domain=Domain.CODE, name="fw"
    )
    db.add(sketch)
    await db.commit()
    return project_id, uuid.UUID(team["id"]), user_id, sketch.id


async def test_a_confirmed_flash_writes_one_history_row(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, engine: AsyncEngine
) -> None:
    """`decide_confirmation` is where a gated flash RUNS (the turn only parked it)."""
    project_id, team_id, user_id, sketch_id = await _scope(client, alice_headers, db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    registry = await _flash_registry(gated=True)

    async def _park(args: dict[str, Any]) -> uuid.UUID:
        async with maker() as session:
            parked = await request_confirmation(
                session,
                registry,
                ToolCall(tool="code.arduino_upload", args=args),
                project_id=project_id,
                team_id=team_id,
                user_id=user_id,
            )
            await session.commit()
        assert parked is not None and parked.confirmation_id is not None
        return parked.confirmation_id

    async def _decide(confirmation_id: uuid.UUID, *, approve: bool) -> ToolResult:
        async with maker() as session:
            result = await decide_confirmation(
                session,
                registry,
                confirmation_id,
                approve=approve,
                project_id=project_id,
                user_id=user_id,
            )
            await session.commit()
        return result

    # Parked: nothing ran, nothing filed.
    own = await _park({"entity_id": str(sketch_id)})
    assert await _flash_rows(db, project_id) == []
    assert (await _decide(own, approve=True)).ok is True
    # Rejected: never runs, never a row.
    assert (await _decide(await _park({}), approve=False)).ok is False
    # Another project's entity in the model-proposed args: the flash is recorded, the
    # foreign id is not.
    other_project = uuid.UUID((await create_project(client, alice_headers, str(team_id)))["id"])
    foreign = GraphEntity(
        project_id=other_project, kind="arduino_sketch", domain=Domain.CODE, name="theirs"
    )
    db.add(foreign)
    await db.commit()
    foreign_id = foreign.id
    assert (await _decide(await _park({"entity_id": str(foreign_id)}), approve=True)).ok

    rows = await _flash_rows(db, project_id)
    assert [r.entity_ids for r in rows] == [[str(sketch_id)], []]
    assert all(r.actor_id == user_id and r.domain == "code" for r in rows)
    assert rows[0].payload == {"tool": "code.arduino_upload", "port": "/dev/ttyACM0"}
    assert await _flash_rows(db, other_project) == []


class _FlashModel:
    """Round 1: one ungated flash call. Round 2: prose."""

    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id
        self.rounds = 0

    async def stream(self, model_name: str, query: str, **_: Any) -> Any:
        self.rounds += 1
        if self.rounds == 1:
            yield ToolUse(id="tu_1", name="code_arduino_upload", args={"entity_id": self.entity_id})
            yield Usage(tokens_in=5, tokens_out=2)
            return
        yield "Flashed."
        yield Usage(tokens_in=5, tokens_out=2)


async def test_the_runners_post_dispatch_hook_records_an_ungated_flash(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_id = await _funded_user(maker)
    async with maker() as session:
        team = Team(name="T")
        session.add(team)
        await session.flush()
        project = Project(team_id=team.id, name="P", created_by=user_id)
        session.add(project)
        await session.flush()
        sketch = GraphEntity(
            project_id=project.id, kind="arduino_sketch", domain=Domain.CODE, name="fw"
        )
        session.add(sketch)
        await session.commit()
        project_id, sketch_id = project.id, sketch.id
    registry = await _flash_registry(gated=False)
    ctx = AgentRunContext(
        prompt="flash it",
        tools=tuple(registry.list()),
        dispatch=build_dispatch(registry, None),
        systems=FakeSolSystems(),
        project_id=project_id,
        user_id=user_id,
        sessionmaker=maker,
        secret_store=InMemorySecretStore(),
    )
    model = _FlashModel(str(sketch_id))
    adapters = {name: model for name in ("anthropic", "openai", "google")}
    events = [event async for event in LlmRunner(adapters=adapters).run(ctx)]
    assert any(e.type.value == "tool_result" for e in events)

    rows = await _flash_rows(db, project_id)
    assert [r.entity_ids for r in rows] == [[str(sketch_id)]]
    assert rows[0].actor_id == user_id and rows[0].payload["port"] == "/dev/ttyACM0"
