"""The reference `get_entity` tool, end to end against Postgres (SOLUS-W0-04).

Proves the whole contract on a real graph read: registration, arg validation, a
team-scoped DB read, a model-consumable dict, and — the security-critical part — that
a missing OR out-of-scope id both come back as ok=False/NOT_FOUND with no traceback.
"""

import json
import uuid
from typing import Any

from solus_api.agent.tools import ToolCall, ToolErrorCode, ToolRegistry, build_get_entity_tool
from solus_api.agent.tools.shapes import ToolResult
from solus_api.models import (
    Domain,
    GraphEntity,
    Membership,
    Project,
    Role,
    Team,
    User,
    utcnow,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def _val(result: ToolResult) -> dict[str, Any]:
    assert result.value is not None  # narrows the type; asserts the success path
    return result.value


async def _make_project_with_entity(db: AsyncSession, name: str) -> tuple[Project, GraphEntity]:
    """Seed the tenancy chain (User→Team→Membership→Project) plus one entity."""
    user = User(supabase_user_id=f"sub-{name}-{uuid.uuid4().hex[:8]}", email=f"{name}@ex.com")
    team = Team(name=name)
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name=name, created_by=user.id)
    db.add(project)
    await db.flush()
    entity = GraphEntity(
        project_id=project.id,
        kind="component",
        domain=Domain.MECHANICAL,
        name=f"{name}-part",
        attrs={},
    )
    db.add(entity)
    await db.flush()
    return project, entity


def _tool_for(engine: AsyncEngine, project_id: uuid.UUID) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        build_get_entity_tool(async_sessionmaker(engine, expire_on_commit=False), project_id)
    )
    return registry


async def test_get_entity_returns_a_curated_json_native_value(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    user = User(supabase_user_id="sub-ge", email="ge@example.com")
    team = Team(name="GE")
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name="Rover", created_by=user.id)
    db.add(project)
    await db.flush()
    canonical = GraphEntity(
        project_id=project.id,
        kind="canonical_part",
        domain=Domain.ELECTRICAL,
        name="OV9281",
    )
    db.add(canonical)
    await db.flush()
    entity = GraphEntity(
        project_id=project.id,
        kind="component",
        domain=Domain.MECHANICAL,
        name="CAM_v2",
        canonical_part_id=canonical.id,
        attrs={"pins": 8},
        source_connector="onshape",
        external_ref="X1",
        embedding=[0.1] * 1536,
    )
    db.add(entity)
    await db.commit()

    registry = _tool_for(engine, project.id)
    result = await registry.invoke(ToolCall(tool="get_entity", args={"entity_id": str(entity.id)}))

    assert result.ok is True
    value = _val(result)
    assert value["name"] == "CAM_v2"
    assert value["kind"] == "component"  # free-string kind
    assert value["domain"] == "mechanical"
    assert value["canonical_part_id"] == str(canonical.id)
    assert value["attrs"] == {"pins": 8}
    assert value["source_connector"] == "onshape"
    assert "embedding" not in value  # bulk vector stays OFF the reasoning path
    json.dumps(result.model_dump(mode="json"))  # model-consumable — must not raise


async def test_registry_lists_the_get_entity_tool(db: AsyncSession, engine: AsyncEngine) -> None:
    registry = _tool_for(engine, uuid.uuid4())
    names = [d.name for d in registry.list()]
    assert names == ["get_entity"]


async def test_missing_entity_is_not_found_without_a_traceback(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project, _ = await _make_project_with_entity(db, "solo")
    await db.commit()
    registry = _tool_for(engine, project.id)
    result = await registry.invoke(
        ToolCall(tool="get_entity", args={"entity_id": str(uuid.uuid4())})
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.NOT_FOUND
    assert result.error.retryable is False


async def test_out_of_scope_entity_is_not_found_no_cross_tenant_leak(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_a, _ = await _make_project_with_entity(db, "team-a")
    _, entity_b = await _make_project_with_entity(db, "team-b")
    await db.commit()

    # Tool is scoped to project A; asking for B's entity must look like it does not exist.
    registry = _tool_for(engine, project_a.id)
    result = await registry.invoke(
        ToolCall(tool="get_entity", args={"entity_id": str(entity_b.id)})
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.NOT_FOUND


async def test_soft_deleted_entity_is_not_found(db: AsyncSession, engine: AsyncEngine) -> None:
    project, entity = await _make_project_with_entity(db, "sd")
    entity.deleted_at = utcnow()
    await db.commit()
    registry = _tool_for(engine, project.id)
    result = await registry.invoke(ToolCall(tool="get_entity", args={"entity_id": str(entity.id)}))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.NOT_FOUND


async def test_bad_args_are_invalid_args(db: AsyncSession, engine: AsyncEngine) -> None:
    registry = _tool_for(engine, uuid.uuid4())
    missing = await registry.invoke(ToolCall(tool="get_entity", args={}))
    assert missing.error is not None and missing.error.code is ToolErrorCode.INVALID_ARGS
    non_uuid = await registry.invoke(ToolCall(tool="get_entity", args={"entity_id": "not-a-uuid"}))
    assert non_uuid.error is not None and non_uuid.error.code is ToolErrorCode.INVALID_ARGS


async def test_model_cannot_smuggle_a_scope_override_via_extra_args(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    # Tenant isolation depends on scope being construction-bound, never a model arg.
    # get_entity's params are additionalProperties:false, so an injected project_id is
    # rejected as INVALID_ARGS before the handler runs — never a cross-tenant read.
    project_a, _ = await _make_project_with_entity(db, "smuggle-a")
    _, entity_b = await _make_project_with_entity(db, "smuggle-b")
    await db.commit()
    registry = _tool_for(engine, project_a.id)
    result = await registry.invoke(
        ToolCall(
            tool="get_entity",
            args={"entity_id": str(entity_b.id), "project_id": str(entity_b.project_id)},
        )
    )
    assert result.ok is False
    assert result.error is not None and result.error.code is ToolErrorCode.INVALID_ARGS


async def test_connector_written_entity_is_resolvable_by_get_entity(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """Decision A seam (SOLUSDEV-72): a connector sync writes `graph_entity`, and the
    SOL `get_entity` tool resolves that exact row. Before unification the connector
    wrote the separate `entities` table while the tool read `graph_entity`, so
    get_entity on a really-synced project ALWAYS returned not_found."""
    from solus_api.connectors.contracts import EntityOut, SyncResult
    from solus_api.connectors.runtime import apply_sync_result
    from solus_api.models import Source, SourceStatus, SourceType
    from sqlalchemy import select

    user = User(supabase_user_id="sub-seam", email="seam@example.com")
    team = Team(name="Seam")
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name="Rover", created_by=user.id)
    db.add(project)
    await db.flush()
    source = Source(
        project_id=project.id,
        team_id=team.id,
        type=SourceType.GITHUB,
        name="octo/r",
        status=SourceStatus.CONNECTED,
    )
    db.add(source)
    await db.flush()

    # The real connector write path (EntityOut.domain uses the reconciled Domain enum).
    result = SyncResult(
        entities=[
            EntityOut(source_key="src/a.py", type="code_file", domain=Domain.CODE, name="a.py")
        ]
    )
    await apply_sync_result(db, source, result)
    await db.commit()

    written = await db.scalar(select(GraphEntity).where(GraphEntity.source_id == source.id))
    assert written is not None  # the connector landed a graph_entity row

    registry = _tool_for(engine, project.id)
    resolved = await registry.invoke(
        ToolCall(tool="get_entity", args={"entity_id": str(written.id)})
    )
    assert resolved.ok is True  # seam fixed: the not_found bug is gone
    value = _val(resolved)
    assert value["kind"] == "code_file"
    assert value["domain"] == "code"  # connector "software" reconciled to "code"
    assert value["external_ref"] == "src/a.py"  # linchpin == EntityOut.source_key
    assert value["source_connector"] == "github"
