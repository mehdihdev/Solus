"""Scene tools are centrally registered and open a fresh session for every operation."""

from unittest.mock import MagicMock
from uuid import uuid4

from solus_api.agent.runtime import build_sol_registry
from test_scene_cad_refresh import scene as scene


def test_scene_registration_requires_actor_and_sync_dispatch():
    maker = MagicMock()
    bare = build_sol_registry(maker, uuid4())
    assert not any(row.name.startswith("bench.") for row in bare.list())
    registry = build_sol_registry(maker, uuid4(), user_id=uuid4(), scene_enqueue=MagicMock())
    assert {row.name for row in registry.list() if row.name.startswith("bench.")} == {
        "bench.list_cad_sources",
        "bench.import_cad_scene",
        "bench.cad_import_status",
    }
    maker.assert_not_called()


async def test_fresh_sessions_for_preview_invoke_and_status(client, alice_headers, db, scene):
    from contextlib import asynccontextmanager

    from conftest import me
    from solus_api.agent.tools.bench_scene import build_bench_scene_tools
    from sqlalchemy.ext.asyncio import async_sessionmaker

    _, _, leaf, model, _ = scene
    leaf.attrs = {
        **leaf.attrs,
        "parent_transform": {
            "length_unit": "mm",
            "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        },
    }
    await db.commit()
    user = await me(client, alice_headers)
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    sessions = []
    closed = []

    @asynccontextmanager
    async def tracked():
        async with maker() as session:
            sessions.append(session)
            yield session
        closed.append(session)

    async def enqueue(session, pending):
        assert session is sessions[-1]
        assert session is not db
        await session.commit()
        return uuid4()

    from uuid import UUID

    tools = {
        tool.descriptor.name: tool
        for tool in build_bench_scene_tools(tracked, leaf.project_id, UUID(user["id"]), enqueue)
    }
    assert sessions == []
    args = {
        "robot_id": model["robot_id"],
        "source_entity_id": str(leaf.id),
        "expected_revision": "r1",
    }
    await tools["bench.import_cad_scene"].preview(args)
    result = await tools["bench.import_cad_scene"].invoke(args)
    status = await tools["bench.cad_import_status"].invoke({"import_id": result["import_id"]})
    assert status["status"] == "pending"
    assert len(sessions) == len(closed) == 3
    assert len({id(session) for session in sessions}) == 3


async def test_route_registry_contains_scene_tools(client, alice_headers, scene):
    base, _, _, _, _ = scene
    path = base.replace("/bench/scene", "/sol/tools")
    response = await client.get(path, headers=alice_headers)
    assert response.status_code == 200
    # Verify the authoritative HTTP dependency, not only the pure factory.
    assert "bench.import_cad_scene" in response.text


async def test_http_approval_rebuilds_scene_registry_and_uses_scoped_queue(
    client, alice_headers, db, scene
):
    from uuid import UUID

    from conftest import me
    from solus_api.agent.confirmations import request_confirmation
    from solus_api.agent.tools.shapes import ToolCall
    from sqlalchemy.ext.asyncio import async_sessionmaker

    base, source, leaf, model, enqueue = scene
    leaf.attrs = {
        **leaf.attrs,
        "parent_transform": {
            "length_unit": "mm",
            "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        },
    }
    await db.commit()
    user = await me(client, alice_headers)
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    registry = build_sol_registry(
        maker, leaf.project_id, user_id=UUID(user["id"]), scene_enqueue=MagicMock()
    )
    call = ToolCall(
        tool="bench.import_cad_scene",
        args={
            "robot_id": model["robot_id"],
            "source_entity_id": str(leaf.id),
            "expected_revision": "r1",
        },
    )
    parked = await request_confirmation(
        db,
        registry,
        call,
        project_id=leaf.project_id,
        team_id=source.team_id,
        user_id=UUID(user["id"]),
    )
    await db.commit()
    assert parked and parked.confirmation_id
    enqueue.assert_not_awaited()
    response = await client.post(
        base.replace("/bench/scene", "/sol/confirmations/") + str(parked.confirmation_id),
        headers=alice_headers,
        json={"decision": "approve"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["ok"] is True, response.text
    assert response.json()["data"]["value"]["status"] == "pending"
    enqueue.assert_awaited_once()
    args = enqueue.await_args.args
    assert args[1].project.id == leaf.project_id
    assert args[1].user.id == UUID(user["id"])
    assert args[2].id == source.id
    assert args[5].sync_inline is False
