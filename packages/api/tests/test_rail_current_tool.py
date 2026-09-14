"""Read-only rail tool is bound to the caller's systems/project context."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from solus_api.agent.interfaces import EntityRead, GraphContext
from solus_api.agent.tools.rail_current import build_rail_current_tool
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall


@pytest.mark.parametrize("foreign", [False, True])
async def test_rail_tool_uses_bound_project_and_refuses_foreign_anchor(foreign):
    project, rail = UUID(int=11), UUID(int=12)
    systems = AsyncMock()
    systems.get_graph_context.return_value = GraphContext(
        entities=[]
        if foreign
        else [EntityRead(id=rail, kind="net", domain="electrical", name="+5V")],
        edges=[],
    )
    tool = build_rail_current_tool(systems, project)
    assert tool.descriptor.requires_confirmation is False
    result = await tool.invoke({"rail_entity_id": str(rail)}) if not foreign else None
    if foreign:
        from solus_api.agent.tools.tool import ToolException

        with pytest.raises(ToolException):
            await tool.invoke({"rail_entity_id": str(rail)})
    else:
        assert result["complete"] is False
    called_project, scope, budget = systems.get_graph_context.call_args.args
    assert called_project == project
    assert scope.anchor_entity_ids == [rail]
    assert scope.degree == 2
    assert budget.max_entities is not None


@pytest.mark.parametrize(
    "args",
    [
        {"rail_entity_id": "bad"},
        {"rail_entity_id": str(UUID(int=1)), "project_id": str(UUID(int=2))},
    ],
)
async def test_rail_tool_rejects_invalid_or_scope_injection_before_graph_read(args):
    systems = AsyncMock()
    registry = ToolRegistry()
    registry.register(build_rail_current_tool(systems, UUID(int=3)))
    result = await registry.invoke(ToolCall(tool="analyze_rail_current", args=args))
    assert not result.ok
    systems.get_graph_context.assert_not_awaited()


async def test_real_systems_never_resolves_another_teams_rail(engine):
    from solus_api.agent.feeds import DbSolSystems
    from solus_api.agent.tools.tool import ToolException
    from solus_api.models import Domain, GraphEntity, Project, Team, User
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = User(supabase_user_id="rail-scope-owner", email="rail-scope@example.test")
        teams = [Team(name="rail A"), Team(name="rail B")]
        db.add_all([user, *teams])
        await db.flush()
        projects = [Project(team_id=team.id, created_by=user.id, name=team.name) for team in teams]
        db.add_all(projects)
        await db.flush()
        rail = GraphEntity(
            project_id=projects[1].id,
            kind="net",
            domain=Domain.ELECTRICAL,
            name="Private rail B",
            attrs={},
        )
        db.add(rail)
        await db.commit()
    tool = build_rail_current_tool(DbSolSystems(maker, AsyncMock()), projects[0].id)
    with pytest.raises(ToolException):
        await tool.invoke({"rail_entity_id": str(rail.id)})


@pytest.mark.parametrize("hostile", ["😀", "<"])
async def test_rail_tool_never_delivers_a_truncated_json_prefix_as_complete(hostile):
    from solus_api.agent.interfaces import EdgeRead
    from solus_api.agent.tools.tool import ToolException

    rail = UUID(int=1)
    members = [
        EntityRead(
            id=UUID(int=i),
            kind="component",
            domain="electrical",
            name=hostile * 160,
            attrs={
                "current_draw_a": 0.1,
                "current_rail": str(rail),
                "current_draw_source": hostile * 400,
            },
        )
        for i in range(2, 102)
    ]
    systems = AsyncMock()
    systems.get_graph_context.return_value = GraphContext(
        entities=[EntityRead(id=rail, kind="net", domain="electrical", name="+5V"), *members],
        edges=[
            EdgeRead(
                src_id=rail,
                dst_id=member.id,
                relation_type="connected_to",
                domain_pair="electrical<->electrical",
                confidence=1,
            )
            for member in members
        ],
    )
    with pytest.raises(ToolException, match="report exceeds"):
        await build_rail_current_tool(systems, UUID(int=3)).invoke({"rail_entity_id": str(rail)})
