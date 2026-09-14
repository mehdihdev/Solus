"""Builtin W0-04 tools over the real subsystems (SOLUS-SYS-03).

`run_checkers`, `query_graph`, `retrieve_errors`, `get_telemetry` registered as
tools wrapping the real `SolSystems` feeds (and CHK-01's real rules). Invoked
here through `build_dispatch` — the same gated, observed execution layer the
reasoning loop uses. Pinned invariants: project scope is bound by Solus code
and absent from every params schema; a failing subsystem becomes
`ToolResult(ok=False)` (never an exception to the model); empty results are
honest empties.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from solus_api.agent.feeds import DbSolSystems
from solus_api.agent.runtime import build_dispatch, build_sol_registry
from solus_api.agent.tools.shapes import ToolCall
from solus_api.checkers import attributes as av
from solus_api.checkers.core import OpAmpMismatchChecker
from solus_api.graph.buffer import InMemoryTelemetryBuffer
from solus_api.graph.resolver import DbEntityResolver
from solus_api.graph.telemetry import TelemetryPlumbing
from solus_api.models import (
    Domain,
    ErrorSolution,
    GraphEdge,
    GraphEntity,
    Membership,
    Project,
    Role,
    Team,
    User,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

BUILTIN_NAMES = {"run_checkers", "query_graph", "retrieve_errors", "get_telemetry"}
_NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def buffer() -> InMemoryTelemetryBuffer:
    return InMemoryTelemetryBuffer()


@pytest.fixture
def systems(
    maker: async_sessionmaker[AsyncSession], buffer: InMemoryTelemetryBuffer
) -> DbSolSystems:
    return DbSolSystems(maker, TelemetryPlumbing(buffer, DbEntityResolver(maker)))


async def _seed_builtin_project(db: AsyncSession, tag: str) -> Project:
    user = User(supabase_user_id=f"sub-{tag}-{uuid.uuid4().hex[:8]}", email=f"{tag}@ex.com")
    team = Team(name=tag)
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name=tag, created_by=user.id)
    db.add(project)
    await db.flush()
    return project


def _row(project_id: uuid.UUID, name: str, attrs: dict[str, Any] | None = None) -> GraphEntity:
    return GraphEntity(
        project_id=project_id,
        kind="component",
        domain=Domain.ELECTRICAL,
        name=name,
        external_ref=f"ref-{name}",
        attrs=attrs or {},
    )


def _drives(project_id: uuid.UUID, src: GraphEntity, dst: GraphEntity) -> GraphEdge:
    return GraphEdge(
        project_id=project_id,
        src_id=src.id,
        dst_id=dst.id,
        relation_type=av.DRIVES,
        domain_pair="electrical<->electrical",
        confidence=1.0,
        attrs={},
    )


def _registry_and_dispatch(
    maker: async_sessionmaker[AsyncSession], project_id: uuid.UUID, systems: DbSolSystems
) -> Any:
    registry = build_sol_registry(maker, project_id, systems=systems)
    return registry, build_dispatch(registry, None)


async def test_builtin_tools_are_registered_with_scope_bound_by_solus_code(
    maker: async_sessionmaker[AsyncSession], systems: DbSolSystems
) -> None:
    registry, _ = _registry_and_dispatch(maker, uuid.uuid4(), systems)
    descriptors = {d.name: d for d in registry.list()}
    assert BUILTIN_NAMES <= set(descriptors)
    for name in BUILTIN_NAMES:
        params = descriptors[name].params
        # §7: ingested content can never alter team scope — project_id is bound in
        # the closure at registration and must not exist as a model-supplied arg.
        assert "project_id" not in params.get("properties", {})
        assert params.get("additionalProperties") is False
        assert descriptors[name].requires_confirmation is False  # all four are reads


async def test_query_graph_returns_the_project_neighborhood(
    db: AsyncSession, maker: async_sessionmaker[AsyncSession], systems: DbSolSystems
) -> None:
    project = await _seed_builtin_project(db, "qg")
    root, peer = _row(project.id, "mcu"), _row(project.id, "imu")
    db.add_all([root, peer])
    await db.flush()
    db.add(_drives(project.id, root, peer))
    await db.commit()

    _, dispatch = _registry_and_dispatch(maker, project.id, systems)
    result = await dispatch(
        ToolCall(tool="query_graph", args={"entity_ids": [str(root.id)], "degree": 1})
    )
    assert result.ok, result.error
    assert result.value is not None
    names = {e["name"] for e in result.value["entities"]}
    assert names == {"mcu", "imu"}
    assert result.value["truncated"] is False


async def test_get_telemetry_summarizes_the_window_and_is_honestly_empty(
    db: AsyncSession,
    maker: async_sessionmaker[AsyncSession],
    systems: DbSolSystems,
    buffer: InMemoryTelemetryBuffer,
) -> None:
    project = await _seed_builtin_project(db, "tel")
    device = _row(project.id, "arm-controller")
    db.add(device)
    await db.commit()

    _, dispatch = _registry_and_dispatch(maker, project.id, systems)
    empty = await dispatch(ToolCall(tool="get_telemetry", args={"duration_seconds": 60}))
    assert empty.ok and empty.value is not None
    assert empty.value["windows"] == []  # no data → honest empty, never invented

    await buffer.append(project.id, device.id, "joint_torque_nm", _NOW, 2.4)
    filled = await dispatch(
        ToolCall(
            tool="get_telemetry",
            args={"duration_seconds": 60, "signals": ["joint_torque_nm"]},
        )
    )
    assert filled.ok and filled.value is not None
    assert filled.value["windows"], "seeded sample must appear in a window summary"
    assert "joint_torque_nm" in filled.value["windows"][-1]["signals"]


async def test_retrieve_errors_hits_the_real_store_scoped_to_the_project(
    db: AsyncSession, maker: async_sessionmaker[AsyncSession], systems: DbSolSystems
) -> None:
    mine = await _seed_builtin_project(db, "err-mine")
    other = await _seed_builtin_project(db, "err-other")
    db.add(
        ErrorSolution(
            project_id=mine.id,
            error_text="brownout at motor start",
            solution_text="add bulk cap",
            domain=Domain.ELECTRICAL,
            attrs={},
        )
    )
    db.add(
        ErrorSolution(
            project_id=other.id,
            error_text="other-tenant brownout",
            solution_text="not yours",
            domain=Domain.ELECTRICAL,
            attrs={},
        )
    )
    await db.commit()

    _, dispatch = _registry_and_dispatch(maker, mine.id, systems)
    result = await dispatch(ToolCall(tool="retrieve_errors", args={"query": "brownout", "k": 5}))
    assert result.ok and result.value is not None
    chunks = [h["chunk"] for h in result.value["hits"]]
    assert chunks == ["brownout at motor start"]  # scoped in-query; no cross-tenant hit


async def test_run_checkers_fires_chk01_real_rules_on_seeded_bug(
    db: AsyncSession, maker: async_sessionmaker[AsyncSession], systems: DbSolSystems
) -> None:
    """The wrong-op-amp seeded bug from the CHK-01 eval, as DB rows: a jellybean
    LM358-class op-amp driving a stage that needs 10x its bandwidth and current.
    The tool must surface the real rule's warning — structured, not raised."""
    project = await _seed_builtin_project(db, "chk")
    op_amp = _row(
        project.id,
        "U1 (slow-op-amp)",
        {
            av.PART_CLASS: av.OP_AMP,
            av.GBW_HZ: 1_000_000,
            av.OUTPUT_CURRENT_MAX_A: 0.04,
            av.SUPPLY_V_MIN: 3.0,
            av.SUPPLY_V_MAX: 32.0,
        },
    )
    stage = _row(
        project.id,
        "motor_current_driver",
        {
            av.PART_CLASS: av.LOAD,
            av.REQUIRED_GBW_HZ: 10_000_000,
            av.REQUIRED_OUTPUT_CURRENT_A: 0.25,
            av.REQUIRED_SUPPLY_V: 24.0,
        },
    )
    db.add_all([op_amp, stage])
    await db.flush()
    db.add(_drives(project.id, op_amp, stage))
    await db.commit()

    _, dispatch = _registry_and_dispatch(maker, project.id, systems)
    result = await dispatch(ToolCall(tool="run_checkers", args={"entity_ids": [str(op_amp.id)]}))
    assert result.ok, result.error
    assert result.value is not None
    warnings = result.value["warnings"]
    assert any(w["checker_id"] == OpAmpMismatchChecker.checker_id for w in warnings)
    clean = await dispatch(ToolCall(tool="run_checkers", args={"entity_ids": [str(uuid.uuid4())]}))
    assert clean.ok and clean.value is not None
    assert clean.value["warnings"] == []  # unknown anchor → empty graph → no warnings


async def test_query_graph_cannot_reach_another_projects_entities(
    db: AsyncSession, maker: async_sessionmaker[AsyncSession], systems: DbSolSystems
) -> None:
    """§7 at the TOOL surface: `entity_ids` is exactly the model-controllable input
    an injected README would aim at another team's UUIDs."""
    a = await _seed_builtin_project(db, "iso-a")
    b = await _seed_builtin_project(db, "iso-b")
    a_root, a_peer = _row(a.id, "a-secret"), _row(a.id, "a-peer")
    db.add_all([a_root, a_peer])
    await db.flush()
    db.add(_drives(a.id, a_root, a_peer))
    await db.commit()

    _, dispatch = _registry_and_dispatch(maker, b.id, systems)
    result = await dispatch(
        ToolCall(tool="query_graph", args={"entity_ids": [str(a_root.id)], "degree": 2})
    )
    assert result.ok and result.value is not None
    assert result.value["entities"] == [] and result.value["edges"] == []


async def test_run_checkers_cannot_reach_another_projects_graph(
    db: AsyncSession, maker: async_sessionmaker[AsyncSession], systems: DbSolSystems
) -> None:
    a = await _seed_builtin_project(db, "chk-a")
    b = await _seed_builtin_project(db, "chk-b")
    op_amp = _row(
        a.id,
        "a-slow-op-amp",
        {
            av.PART_CLASS: av.OP_AMP,
            av.GBW_HZ: 1_000_000,
            av.OUTPUT_CURRENT_MAX_A: 0.04,
            av.SUPPLY_V_MIN: 3.0,
            av.SUPPLY_V_MAX: 32.0,
        },
    )
    stage = _row(
        a.id,
        "a-driver",
        {
            av.PART_CLASS: av.LOAD,
            av.REQUIRED_GBW_HZ: 10_000_000,
            av.REQUIRED_OUTPUT_CURRENT_A: 0.25,
            av.REQUIRED_SUPPLY_V: 24.0,
        },
    )
    db.add_all([op_amp, stage])
    await db.flush()
    db.add(_drives(a.id, op_amp, stage))
    await db.commit()

    _, dispatch = _registry_and_dispatch(maker, b.id, systems)
    result = await dispatch(ToolCall(tool="run_checkers", args={"entity_ids": [str(op_amp.id)]}))
    assert result.ok and result.value is not None
    assert result.value["warnings"] == []  # A's bug is invisible from B


async def test_get_telemetry_cannot_read_another_projects_buffer(
    db: AsyncSession,
    maker: async_sessionmaker[AsyncSession],
    systems: DbSolSystems,
    buffer: InMemoryTelemetryBuffer,
) -> None:
    a = await _seed_builtin_project(db, "tel-a")
    b = await _seed_builtin_project(db, "tel-b")
    a_device = _row(a.id, "a-device")
    db.add(a_device)
    await db.commit()
    await buffer.append(a.id, a_device.id, "motor_current_a", _NOW, 3.1)

    _, dispatch = _registry_and_dispatch(maker, b.id, systems)
    result = await dispatch(ToolCall(tool="get_telemetry", args={"duration_seconds": 60}))
    assert result.ok and result.value is not None
    assert result.value["windows"] == []


async def test_array_params_are_bounded(
    maker: async_sessionmaker[AsyncSession], systems: DbSolSystems
) -> None:
    """§7 DoS bound: every model-suppliable array/string arg is capped, so a large
    model-emitted list can never become an oversized bind-parameter fan-out."""
    registry, _ = _registry_and_dispatch(maker, uuid.uuid4(), systems)
    descriptors = {d.name: d for d in registry.list()}
    for name, field in (
        ("query_graph", "kinds"),
        ("query_graph", "domains"),
        ("get_telemetry", "signals"),
        ("query_graph", "entity_ids"),
        ("run_checkers", "entity_ids"),
    ):
        schema = descriptors[name].params["properties"][field]
        assert schema["maxItems"] == 16, (name, field)
        assert schema["items"].get("maxLength", 64) == 64 or "format" in schema["items"], (
            name,
            field,
        )


async def test_a_failing_subsystem_becomes_ok_false_never_an_exception(
    maker: async_sessionmaker[AsyncSession],
    buffer: InMemoryTelemetryBuffer,
) -> None:
    class _Exploding(DbSolSystems):
        async def get_graph_context(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("subsystem down")

        async def get_telemetry(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("subsystem down")

        async def get_error_history(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("subsystem down")

    exploding = _Exploding(maker, TelemetryPlumbing(buffer, DbEntityResolver(maker)))
    _, dispatch = _registry_and_dispatch(maker, uuid.uuid4(), exploding)
    for call in (
        ToolCall(tool="query_graph", args={"entity_ids": [str(uuid.uuid4())]}),
        ToolCall(tool="get_telemetry", args={"duration_seconds": 10}),
        ToolCall(tool="retrieve_errors", args={"query": "x", "k": 1}),
        ToolCall(tool="run_checkers", args={"entity_ids": [str(uuid.uuid4())]}),
    ):
        result = await dispatch(call)  # the never-raises invariant, per tool
        assert result.ok is False
        assert result.error is not None and result.error.message
        assert "subsystem down" not in str(result.value)  # no leak through value


async def test_rail_analysis_is_registered_read_only_and_project_bound(
    maker: async_sessionmaker[AsyncSession], systems: DbSolSystems
) -> None:
    registry, _ = _registry_and_dispatch(maker, uuid.uuid4(), systems)
    descriptor = next(d for d in registry.list() if d.name == "analyze_rail_current")
    assert descriptor.requires_confirmation is False
    assert set(descriptor.params["properties"]) == {"rail_entity_id"}
    assert descriptor.params["additionalProperties"] is False
