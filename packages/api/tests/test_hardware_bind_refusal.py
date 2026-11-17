"""SOLUSDEV-326 review: a refused bind writes nothing.

One config per device project-wide: `bind_device` refuses a device another robot or a lone
part already binds before it writes anything, and an accepted device suggestion whose bind is
refused at any step rolls the whole bind back — the decision is kept, and the robot's config
and bindings are exactly as they were (docs/api/hardware.md §5).
"""

from typing import Any

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.core.errors import APIError
from solus_api.hardware.config import EntityHardwareConfig
from solus_api.hardware.detect import ConfirmIn, bind_device, confirm_proposal
from solus_api.hardware.links import LinkSuggestion, LinkTier, persist_suggestions
from solus_api.hardware.store import put_entity_config, read_entity_config
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, SolusEntry, User, utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_identity_list import (
    USER,
    _binds,
    _brain,
    _bus_proposal,
    _project_by_id,
    _project_row,
    _robot,
    _url,
)

PROPOSAL = _bus_proposal("BBB", "right-driver")


class _Runner:
    """The local runner as accepting a device suggestion uses it: it re-proposes the wire."""

    def propose_device(self, device_ref: str, **_: Any) -> dict[str, Any] | None:
        return PROPOSAL.model_dump(mode="json") if device_ref == PROPOSAL.device_ref else None


async def _holder(db: AsyncSession, project: Project, kind: str) -> GraphEntity:
    """A robot (kind physical_robot) or a lone part whose live config binds usb:BBB."""
    holder = GraphEntity(
        project_id=project.id, kind=kind, domain=Domain.PROJECT, origin="manual", name="Holder"
    )
    db.add(holder)
    await db.flush()
    await put_entity_config(
        db,
        project.id,
        holder,
        EntityHardwareConfig.model_validate(
            {
                "entity_id": str(holder.id),
                "identity": [_brain("BBB", "right-driver")],
                "provenance": {"identity": USER},
            }
        ),
        expected_version=0,
        created_by=None,
    )
    return holder


@pytest.mark.parametrize("holder", ["backfilled robot", "lone part"])
async def test_bind_device_refuses_a_device_another_config_binds_before_writing(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, holder: str
) -> None:
    """A backfilled robot binds its device in its stored config only (revision a26000000002
    derives no binding edge); a lone part's binding is an edge. Either holder refuses the
    robot before its first write: not even an empty config is created."""
    await me(client, alice_headers)
    user = await db.scalar(select(User.id).limit(1))
    assert user is not None
    project = await _project_row(db)
    robot, _ = await _robot(db, project)
    await _holder(db, project, "physical_robot" if holder == "backfilled robot" else "part")
    if holder == "backfilled robot":
        edges = await db.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project.id, GraphEdge.relation_type == "binds"
            )
        )
        for edge in edges:
            edge.deleted_at = utcnow()

    with pytest.raises(APIError) as refused:
        await bind_device(db, project.id, robot, PROPOSAL, created_by=user)

    assert (refused.value.status_code, refused.value.code) == (409, "binding_conflict")
    written = select(SolusEntry.id).where(SolusEntry.configured_entity_id == robot.id)
    assert await db.scalar(written) is None
    assert "usb:BBB" in refused.value.message


async def _offered(
    client: AsyncClient,
    headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    *,
    binding: str | None,
) -> tuple[Project, GraphEntity, GraphEntity, str]:
    """Robot R with one brain (bound to usb:<binding>, or still waiting for its device) and a
    joint at address 1, a pending suggestion offering usb:BBB to R, and a runner that
    re-proposes usb:BBB. Returns the project, R, the joint and the accept URL."""
    await me(client, headers)
    team = await create_team(client, headers)
    created = await create_project(client, headers, team["id"])
    project = await _project_by_id(db, str(created["id"]))
    robot, (joint,) = await _robot(db, project, "joint")
    brain = _brain(binding or "unused", "right-driver")
    if binding is None:
        brain["binding"] = None  # the brain still waits for its device
    await put_entity_config(
        db,
        project.id,
        robot,
        EntityHardwareConfig.model_validate(
            {
                "entity_id": str(robot.id),
                "identity": [brain],
                "bus_map": [
                    {"protocol": "right-driver", "address": "1", "part_entity_id": str(joint.id)}
                ],
                "provenance": {"identity": USER, "bus_map": USER},
            }
        ),
        expected_version=0,
        created_by=None,
    )
    [row] = await persist_suggestions(
        db,
        project.id,
        [
            LinkSuggestion(
                subject_ref="usb:BBB",
                subject_kind="device",
                candidate_robot_id=robot.id,
                confidence=0.8,
                tier=LinkTier.HIGH,
                evidence=[],
                reason="fixture",
            )
        ],
    )
    await db.commit()
    app.state.bench_local = _Runner()
    return project, robot, joint, _url(str(project.id), f"suggestions/{row.id}/accept")


async def _brains_and_version(
    db: AsyncSession, project: Project, robot: GraphEntity
) -> tuple[list[str | None], int]:
    entry, config = await read_entity_config(db, project.id, robot.id)
    assert entry is not None and config is not None
    return [brain.device_ref for brain in config.identity], entry.config_version


async def test_accepting_a_device_another_robot_binds_keeps_the_decision_and_writes_nothing(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
) -> None:
    """The review's probe: R has usb:AAA, robot S has usb:BBB, and a suggestion offers usb:BBB
    to R. The accept refuses the bind; R keeps its brains, its version and its bindings."""
    project, robot, _, url = await _offered(client, alice_headers, db, app, binding="AAA")
    await _holder(db, project, "physical_robot")
    await db.commit()
    before = await _brains_and_version(db, project, robot)
    assert before == (["usb:AAA"], 1)
    bindings = await _binds(db, project)
    assert bindings == {"usb:AAA", "usb:AAA/1", "usb:BBB"}
    await me(client, bob_headers)
    for headers, status in (({}, 401), (bob_headers, 404)):
        assert (await client.post(url, headers=headers)).status_code == status

    accepted = await client.post(url, headers=alice_headers)

    assert accepted.status_code == 200, accepted.text
    data = accepted.json()["data"]
    assert (data["status"], data["bound"], data["session_id"]) == ("accepted", False, None)
    assert await _brains_and_version(db, project, robot) == before
    assert await _binds(db, project) == bindings
    assert "usb:BBB" in data["bind_error"]


async def test_a_bind_refused_after_it_wrote_is_rolled_back_and_the_decision_kept(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, app: FastAPI
) -> None:
    """R's brain waits for its device, so the bind writes R's config and bindings before it
    finds usb:BBB/1 already keyed to another part: those writes are undone, not committed."""
    project, robot, joint, url = await _offered(client, alice_headers, db, app, binding=None)
    db.add(
        GraphEntity(
            project_id=project.id,
            kind="part",
            domain=Domain.PROJECT,
            origin="manual",
            name="Old board",
            external_ref="usb:BBB/1",
        )
    )
    await db.commit()
    before = await _brains_and_version(db, project, robot)
    assert before == ([None], 1)

    accepted = await client.post(url, headers=alice_headers)

    assert accepted.status_code == 200, accepted.text
    data = accepted.json()["data"]
    assert (data["status"], data["bound"]) == ("accepted", False)
    assert await _brains_and_version(db, project, robot) == before
    assert await _binds(db, project) == set()
    await db.refresh(joint)
    assert joint.external_ref is None
    assert "already part of" in data["bind_error"]


async def test_every_config_writer_refuses_a_device_another_robot_holds(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """One config per device project-wide on every writer, not only bind_device: confirming a
    usb:BBB row onto robot R (which has usb:AAA) while robot S holds usb:BBB in its stored config
    only (backfilled, no binding edge) is 409 binding_conflict; S stays the only holder and R's
    brains and version are unchanged."""
    await me(client, alice_headers)
    user = await db.scalar(select(User.id).limit(1))
    assert user is not None
    project = await _project_row(db)
    robot, _ = await _robot(db, project)
    await put_entity_config(
        db,
        project.id,
        robot,
        EntityHardwareConfig.model_validate(
            {
                "entity_id": str(robot.id),
                "identity": [_brain("AAA", "left-driver")],
                "provenance": {"identity": USER},
            }
        ),
        expected_version=0,
        created_by=None,
    )
    holder = await _holder(db, project, "physical_robot")
    for edge in await db.scalars(
        select(GraphEdge).where(
            GraphEdge.project_id == project.id,
            GraphEdge.relation_type == "binds",
            GraphEdge.attrs["device_ref"].astext.like("usb:BBB%"),
        )
    ):
        edge.deleted_at = utcnow()  # the holder as backfilled: stored brain, no binding edge
    await db.commit()
    project_id, robot_id, holder_id = project.id, robot.id, holder.id
    before = await _brains_and_version(db, project, robot)

    body = ConfirmIn.model_validate(
        {
            "target": {"kind": "existing", "robot_id": str(robot_id)},
            "accepted": [{"row_id": "usb:BBB/1", "function_name": "Wrist"}],
            "start_session": False,
        }
    )
    with pytest.raises(APIError) as refused:
        await confirm_proposal(
            db,
            project_id=project_id,
            proposal=_bus_proposal("BBB", "right-driver"),
            body=body,
            created_by=user,
        )
    assert refused.value.code == "binding_conflict"
    await db.rollback()
    project = await _project_by_id(db, str(project_id))
    again = await db.get(GraphEntity, robot_id)
    assert again is not None
    assert await _brains_and_version(db, project, again) == before
    _, held = await read_entity_config(db, project_id, holder_id)
    assert held is not None and [brain.device_ref for brain in held.identity] == ["usb:BBB"]


async def test_a_binding_edge_for_another_device_never_frees_a_held_one(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """The stored-brains check is judged per device: a holder whose config binds another device
    by edge, but this one by its stored brains alone (backfilled), still holds it."""
    await me(client, alice_headers)
    project = await _project_row(db)
    robot, _ = await _robot(db, project)
    holder = GraphEntity(
        project_id=project.id,
        kind="physical_robot",
        domain=Domain.PROJECT,
        origin="manual",
        name="H",
    )
    db.add(holder)
    await db.flush()
    await put_entity_config(
        db,
        project.id,
        holder,
        EntityHardwareConfig.model_validate(
            {
                "entity_id": str(holder.id),
                "identity": [_brain("BBB", "right-driver"), _brain("CCC", "left-driver")],
                "provenance": {"identity": USER},
            }
        ),
        expected_version=0,
        created_by=None,
    )
    for edge in await db.scalars(
        select(GraphEdge).where(
            GraphEdge.project_id == project.id,
            GraphEdge.relation_type == "binds",
            GraphEdge.attrs["device_ref"].astext.like("usb:BBB%"),
        )
    ):
        edge.deleted_at = utcnow()  # BBB as backfilled; CCC keeps its live edge
    await db.commit()
    config = EntityHardwareConfig.model_validate(
        {
            "entity_id": str(robot.id),
            "identity": [_brain("BBB", "right-driver")],
            "provenance": {"identity": USER},
        }
    )
    with pytest.raises(APIError) as refused:
        await put_entity_config(db, project.id, robot, config, expected_version=0, created_by=None)
    assert refused.value.code == "binding_conflict"
