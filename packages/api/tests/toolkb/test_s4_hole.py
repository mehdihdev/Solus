"""S4 authored hole instructions remain honest without version knowledge."""

import pytest
from solus_api.contracts.tool_knowledge import ToolFamily
from solus_api.toolkb.guides import list_guides, resolve_guide
from sqlalchemy.ext.asyncio import AsyncSession


async def test_hole_guide_uses_existing_control_and_unknown_knowledge(db: AsyncSession) -> None:
    guide = next(
        g
        for g in list_guides(tool=ToolFamily.ONSHAPE, version="1.0")
        if g.id == "onshape.partstudio.hole_6mm"
    )
    assert all(s.control_id == "onshape.partstudio.feature_list" for s in guide.steps)
    resolved = await resolve_guide(db, guide.id, version="1.0")
    assert resolved is not None and len(resolved.steps) >= 3
    assert all(not s.available and s.locator is None for s in resolved.steps)
    assert "6 mm" in " ".join(s.note_guide for s in resolved.steps)


@pytest.mark.parametrize("approve", [False, True])
async def test_fixture_hole_guide_never_writes_build_parks_real_preview_then_approval_writes(
    db: AsyncSession,
    approve: bool,
) -> None:
    """Synthetic vendor response, real operation/dispatcher/confirmation ledger; no live write."""
    import copy
    import uuid
    from typing import Any, cast

    import httpx
    import respx
    from fixtures.onshape_sample import (
        ADD_FEATURE_RESPONSE,
        FEATURE_SPECS_WITH_DEFAULTS,
        WORKSPACE_INFO,
    )
    from solus_api.agent.confirmations import decide_confirmation, request_confirmation
    from solus_api.agent.modes import ActionMode, build_mode_dispatch
    from solus_api.agent.runtime import build_dispatch
    from solus_api.agent.tools.registry import ToolRegistry
    from solus_api.agent.tools.shapes import ToolCall, ToolDescriptor
    from solus_api.agent.tools.tool import InProcessTool
    from solus_api.connectors.contracts import Credentials
    from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
    from solus_api.connectors.onshape_ops import operation_by_name
    from solus_api.models import Project, Team, ToolConfirmation, User

    user = User(supabase_user_id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@example.test")
    team = Team(name="Fixture")
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name="Hole fixture")
    db.add(project)
    await db.flush()
    operation = operation_by_name("onshape.add_feature")
    assert operation is not None and operation.preview is not None
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    # Reuse the documented recorded envelope; this fixture's parameter meaning is
    # deliberately synthetic and is not evidence of a current vendor hole schema.
    specs = cast(dict[str, Any], copy.deepcopy(FEATURE_SPECS_WITH_DEFAULTS))
    spec = specs["featureSpecs"][0]["message"]
    spec["featureType"] = "hole"
    spec["featureTypeName"] = "Hole"
    diameter = spec["parameterIdToSpec"].pop("depth")
    diameter["parameterId"] = "diameter"
    diameter["defaultValue"]["parameterId"] = "diameter"
    spec["parameterIdToSpec"]["diameter"] = diameter
    response = cast(dict[str, Any], copy.deepcopy(ADD_FEATURE_RESPONSE))
    response["feature"].update(name="6 mm hole fixture", featureType="hole")
    args = {
        "document_id": "d1",
        "element_id": "e1",
        "feature_type": "hole",
        "name": "6 mm hole fixture",
        "parameters": {"diameter": "6 mm"},
    }

    async def invoke(values: dict[str, Any]) -> dict[str, Any]:
        async with connector.http(Credentials(token="fixture")) as client:
            return await operation.run(connector, client, values)

    async def preview(values: dict[str, Any]) -> list[dict[str, Any]]:
        assert operation.preview is not None
        async with connector.http(Credentials(token="fixture")) as client:
            return await operation.preview(connector, client, values)

    registry = ToolRegistry()
    registry.register(
        InProcessTool(
            ToolDescriptor(
                name=operation.name,
                description=operation.description,
                params=operation.params,
                returns={"type": "object"},
                requires_confirmation=operation.requires_confirmation,
            ),
            invoke,
            preview,
        )
    )

    from solus_api.agent.confirmations import ParkedCall

    async def park(call: ToolCall) -> ParkedCall | None:
        return await request_confirmation(
            db, registry, call, project_id=project.id, team_id=team.id, user_id=user.id
        )

    with respx.mock as router:
        base = f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/d1/w/w1/e/e1/features"
        router.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d1").respond(200, json=WORKSPACE_INFO)
        router.get(f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/d1/m/mvabc/e/e1/featurespecs").respond(
            200, json=specs
        )
        posted = router.post(base).respond(200, json=response)

        def tree(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "features": [copy.deepcopy(response["feature"])] if posted.called else [],
                    "featureStates": {"F9": {"featureStatus": "OK"}},
                    "serializationVersion": "1.2.7",
                    "sourceMicroversion": "mvabc",
                    "libraryVersion": 2522,
                },
            )

        router.get(base).mock(side_effect=tree)
        call = ToolCall(tool=operation.name, args=args)
        gated = build_dispatch(registry, park)
        guide = build_mode_dispatch(ActionMode.GUIDE, registry.list(), gated)
        assert not (await guide(call)).ok
        assert not posted.called
        from sqlalchemy import select

        assert (
            await db.scalar(
                select(ToolConfirmation).where(ToolConfirmation.project_id == project.id)
            )
            is None
        )
        build = build_mode_dispatch(ActionMode.DO, registry.list(), gated)
        assert not (await build(call)).ok
        assert not posted.called
        row = await db.scalar(
            select(ToolConfirmation).where(ToolConfirmation.project_id == project.id)
        )
        assert row is not None
        assert row.preview == [
            {"label": "6 mm hole fixture", "before": None, "after": "new hole (diameter=6 mm)"}
        ]
        result = await decide_confirmation(
            db, registry, row.id, approve=approve, project_id=project.id, user_id=user.id
        )
        assert result.ok is approve
        assert posted.call_count == int(approve)
