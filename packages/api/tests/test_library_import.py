"""SOLUSDEV-326 P2: library imports as services (`hardware/library_import.py`) that the library
routes and SOL's `import_definition` tool both call. A platform becomes a new robot, in the graph
with no onboarder unless a Solus caller says otherwise; a part joins only a robot its member can
see, and takes that robot's visibility (docs/api/hardware.md §1a, §5)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from solus_api.core.errors import APIError
from solus_api.graph.read_scope import GraphReadScope, bind_scope, visible_to
from solus_api.hardware import library_import
from solus_api.hardware.library import load_library
from solus_api.hardware.operations import ReviewedHardwareOperations
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import read_entity_config
from solus_api.models import GraphEntity
from solus_api.services.physical_robots import PhysicalRobotService
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_in_graph import _team

STAMPED_KEYS = ("in_graph", "onboarded_by")


async def test_a_platform_imported_out_of_the_graph_is_its_onboarders_alone(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    bob = uuid.UUID(team.bob["id"])
    library = load_library()
    platform = library.platforms["so101-follower"]

    hidden = await library_import.import_platform(
        db,
        None,
        library,
        platform,
        project_id=team.project_id,
        user_id=team.alice_id,
        name=None,
        in_graph=False,
        onboarded_by=team.alice_id,
    )
    shared = await library_import.import_platform(
        db,
        None,
        library,
        platform,
        project_id=team.project_id,
        user_id=team.alice_id,
        name="Left arm",
    )
    await db.commit()

    assert (hidden.robot.name, shared.robot.name) == (platform.name, "Left arm")
    assert len(hidden.part_ids) == len(platform.parts) and hidden.suggestions == []
    ids = [hidden.robot.id, *hidden.part_ids]
    stamped = {"in_graph": False, "onboarded_by": str(team.alice_id)}
    for row in await db.scalars(select(GraphEntity).where(GraphEntity.id.in_(ids))):
        assert {key: row.attrs.get(key) for key in STAMPED_KEYS} == stamped
    assert not set(STAMPED_KEYS) & set(shared.robot.attrs)

    def seen(viewer: uuid.UUID) -> Select[tuple[int]]:
        return select(func.count()).where(GraphEntity.id.in_(ids), visible_to(viewer))

    assert await db.scalar(seen(bob)) == 0
    assert await db.scalar(seen(team.alice_id)) == len(ids)
    _, config = await read_entity_config(db, team.project_id, hidden.robot.id)
    assert config is not None and hidden.entry.configured_entity_id == hidden.robot.id


async def test_a_library_part_joins_only_a_robot_its_member_can_see(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    team = await _team(client, alice_headers, bob_headers)
    bob = uuid.UUID(team.bob["id"])
    robot = await PhysicalRobotService(db).create(
        team.project_id, "Private arm", in_graph=False, onboarded_by=team.alice_id
    )
    await db.commit()
    robot_id = robot.id
    part = load_library().parts["bmp390"]

    with (
        bind_scope(GraphReadScope(team.project_id, viewer_id=bob)),
        pytest.raises(APIError) as refused,
    ):
        await library_import.import_part_into_robot(
            db, part, project_id=team.project_id, user_id=bob, robot_id=robot_id, name=None
        )
    assert (refused.value.status_code, refused.value.code) == (404, "not_found")
    await db.rollback()
    written = select(func.count()).where(GraphEntity.attrs["definition_id"].astext == part.id)
    assert await db.scalar(written) == 0

    with bind_scope(GraphReadScope(team.project_id, viewer_id=team.alice_id)):
        entity, entry = await library_import.import_part_into_robot(
            db,
            part,
            project_id=team.project_id,
            user_id=team.alice_id,
            robot_id=robot_id,
            name="Cabin pressure",
        )
    await db.commit()

    assert entity.name == "Cabin pressure" and entity.attrs["definition_id"] == part.id
    assert entity.attrs["robot_id"] == str(robot_id)
    assert {key: entity.attrs.get(key) for key in STAMPED_KEYS} == {
        "in_graph": False,
        "onboarded_by": str(team.alice_id),
    }
    assert entry.configured_entity_id == robot_id
    slot = (await resolve_runtime_config(db, team.project_id, robot_id)).parts[str(entity.id)]
    assert slot.lifecycle.value == "planned"
    assert {row.name for row in slot.telemetry} == {"bmp390.pressure", "bmp390.temperature"}


async def test_a_standalone_import_key_minted_with_a_category_still_replays(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """The replay digest still carries the definition's own category, which P1 keyed it on when
    a body named none, so a key minted before the field went replays instead of a 409."""
    team = await _team(client, alice_headers, bob_headers)
    part = load_library().parts["bmp390"]
    key = uuid.uuid4()
    ledger = ReviewedHardwareOperations(db, team.project_id, team.alice_id)
    _, digest = await ledger.replay(
        key,
        "library.part.import",
        {"definition_id": part.id, "name": "Cabin pressure", "category": part.category},
    )
    saved = ledger.record(key, "library.part.import", digest, {"entity": {"id": "saved"}})
    await db.commit()

    response, replayed = await library_import.import_standalone_part(
        db, team.project_id, team.alice_id, key, part, name="Cabin pressure"
    )

    assert replayed and response == saved
