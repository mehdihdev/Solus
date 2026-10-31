"""SOLUSDEV-321 P4-T4 (R92, R113) — the bounded CAD twin a CAD import writes beside its model.

`materialize` keeps `model.joints` empty: the graph holds no mate frame. A revolute or slider
`mates_with` between two leaves of the import becomes a candidate joint under
`model.candidate_joints`, its axis and origin unknown. The robot's bus map is the actuated set, a
candidate's limits come from the definition of the part that actuates it, a sensor site sits where
a `mounts` edge places it, and masses stay unknown. The kinematics provider then names the mate
frame as what it lacks. Building the twin writes nothing: it rides the scene model `materialize`
already persists.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.graph import kinds
from solus_api.hardware.config import (
    BusMapEntry,
    EntityHardwareConfig,
    FieldProvenance,
    ProvenanceRecord,
)
from solus_api.hardware.library import Library, PartDefinition, PartLimitsSpec
from solus_api.hardware.store import put_entity_config
from solus_api.livebench.scene.cad_import import STATIC_REASON, rigid_matrix, twin_of
from solus_api.livebench.scene.service import SceneService
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    Source,
    SourceStatus,
    SourceType,
    Team,
)
from solus_api.orchestration.config import SimulationConfig
from solus_api.simulation.providers.deterministic_robot import DeterministicRobot
from solus_api.simulation.sim_capability import SimQuestion
from solus_api.simulation.sim_ladder import LadderContext, propose_for
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

IDENTITY: Final = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
#: 100 mm along x: where the forearm sits in the assembly.
OUT_100_MM: Final = [1, 0, 0, 100, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
SERVO: Final = PartDefinition(
    id="fake-servo",
    name="Fake servo",
    category="actuators",
    limits=PartLimitsSpec(position_min=-150, position_max=150),
)
LIBRARY: Final = Library(parts={"fake-servo": SERVO}, platforms={})
#: The one revision every CAD row below was observed at.
REVISION: Final = {"document_id": "doc", "element_id": "element", "observed_microversion": "r1"}


def _transform(matrix: list[int]) -> dict[str, Any]:
    return {"length_unit": "mm", "matrix": matrix}


def _mate(src: GraphEntity, dst: GraphEntity, mate_type: str, feature: str) -> GraphEdge:
    return GraphEdge(
        project_id=src.project_id,
        source_id=src.source_id,
        src_id=src.id,
        dst_id=dst.id,
        relation_type="mates_with",
        domain_pair="mechanical<->mechanical",
        origin="connector",
        attrs={"mate_type": mate_type, "feature_id": feature},
    )


def _cad_part(source: Source, name: str, ref: str, **attrs: Any) -> GraphEntity:
    return GraphEntity(
        project_id=source.project_id,
        source_id=source.id,
        kind="part",
        domain=Domain.MECHANICAL,
        origin="connector",
        name=name,
        external_ref=ref,
        attrs={**REVISION, **attrs},
    )


async def _cad_project(
    client: AsyncClient, headers: dict[str, str], db: AsyncSession
) -> tuple[uuid.UUID, Source, GraphEntity]:
    """The person, a connected CAD source tracking `doc`, and a physical robot."""
    user = await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    source = Source(
        project_id=uuid.UUID(project["id"]),
        team_id=uuid.UUID(team["id"]),
        name="CAD",
        type=SourceType.ONSHAPE,
        status=SourceStatus.CONNECTED,
        secret_ref="test-reference",
        config={"documents": ["doc"]},
    )
    robot = GraphEntity(
        project_id=uuid.UUID(project["id"]),
        kind=kinds.PHYSICAL_ROBOT,
        domain=Domain.RUNTIME,
        origin="manual",
        name="Robot",
    )
    db.add_all([source, robot])
    await db.commit()
    return uuid.UUID(user["id"]), source, robot


async def test_revolute_mates_become_candidate_joints_with_missing_axis(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from solus_api.connectors import step_tessellation
    from solus_api.livebench.scene.cad_import import materialize, propose

    user_id, source, robot = await _cad_project(client, alice_headers, db)
    root = _cad_part(
        source,
        "Arm",
        "doc:element:root",
        is_assembly=True,
        parent_transform=_transform(IDENTITY),
    )
    db.add(root)
    await db.flush()
    parts = {}
    for name, place in (("base", IDENTITY), ("upper", IDENTITY), ("fore", OUT_100_MM)):
        part = _cad_part(
            source,
            name,
            f"doc:element:root/{name}",
            is_assembly=False,
            parent_transform=_transform(place),
        )
        db.add(part)
        await db.flush()
        db.add(
            GraphEdge(
                project_id=source.project_id,
                source_id=source.id,
                src_id=part.id,
                dst_id=root.id,
                relation_type="part_of",
                domain_pair="mechanical<->mechanical",
                origin="connector",
            )
        )
        parts[name] = part
    db.add_all(
        [
            _mate(parts["base"], parts["upper"], "REVOLUTE", "Fm1"),
            _mate(parts["upper"], parts["fore"], "SLIDER", "Fs1"),
            _mate(parts["base"], parts["fore"], "FASTENED", "Ff1"),
        ]
    )
    await db.commit()
    service = SceneService(db, source.project_id, user_id)
    row = await propose(service, robot.id, root.id, "r1")
    await db.commit()
    mesh = {"vertices": [0.001, 0, 0] * 3}
    monkeypatch.setattr(
        step_tessellation,
        "tessellate_isolated",
        AsyncMock(return_value={f"root/{name}": mesh for name in parts}),
    )

    await materialize(service, row, {("doc", "element"): ("r1", "EXACT")}, app.state.artifact_store)
    await db.commit()

    saved = await db.get(GraphEntity, uuid.UUID(row.attrs["model_id"]))
    assert saved is not None
    twin = saved.attrs["model"]
    assert twin["joints"] == []
    assert twin["warnings"][0] == STATIC_REASON
    assert any("mate frame" in line for line in twin["warnings"][1:])
    unknown = {
        "axis": "unknown",
        "origin": "unknown",
        "actuated": False,
        "actuator": None,
        "limits": None,
    }
    assert twin["candidate_joints"] == [
        {
            "name": "Fm1",
            "type": "revolute",
            "parent": str(parts["base"].id),
            "child": str(parts["upper"].id),
            "mate_feature_id": "Fm1",
            **unknown,
        },
        {
            "name": "Fs1",
            "type": "prismatic",
            "parent": str(parts["upper"].id),
            "child": str(parts["fore"].id),
            "mate_feature_id": "Fs1",
            **unknown,
        },
    ]
    assert twin["masses"] == {}
    assert [need["name"] for need in twin["missing"]] == ["mate_frame", "mass"]
    question = SimQuestion(subject_id=saved.id, quantity="reach_m", facts=saved.attrs)
    provider = DeterministicRobot()
    assert [need.name for need in provider.can_answer(question).missing] == ["mate_frame"]
    ladder = LadderContext(
        config=SimulationConfig(),
        providers=(provider,),
        available=frozenset({provider.name}),
        asked=frozenset({(saved.id, "mate_frame")}),
    )
    proposal = propose_for(question, trigger="user", context=ladder)
    assert proposal is not None and proposal.decision == "missing_input"
    assert [need.name for need in proposal.missing] == ["mate_frame"]


async def _arm(db: AsyncSession) -> tuple[SceneService, GraphEntity, dict[str, GraphEntity]]:
    """A committed project with a robot and three parts, none of them mated yet."""
    team = Team(name="twin")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="twin")
    db.add(project)
    await db.flush()
    robot = GraphEntity(
        project_id=project.id,
        kind=kinds.PHYSICAL_ROBOT,
        domain=Domain.PROJECT,
        origin="manual",
        name="robot",
    )
    parts = {
        name: GraphEntity(
            project_id=project.id,
            kind=kinds.PART,
            domain=Domain.MECHANICAL,
            origin="manual",
            name=name,
            attrs={"definition_id": "fake-servo"} if name == "fore" else {},
        )
        for name in ("base", "upper", "fore")
    }
    db.add_all([robot, *parts.values()])
    await db.commit()
    return SceneService(db, project.id, uuid.uuid4()), robot, parts


def _placed(parts: dict[str, GraphEntity]) -> list[tuple[GraphEntity, list[float]]]:
    return [
        (part, rigid_matrix(_transform(OUT_100_MM if name == "fore" else IDENTITY)))
        for name, part in parts.items()
    ]


async def _rows(db: AsyncSession) -> tuple[int, int]:
    entities = await db.scalar(select(func.count()).select_from(GraphEntity))
    edges = await db.scalar(select(func.count()).select_from(GraphEdge))
    return entities or 0, edges or 0


async def test_the_bus_map_is_the_actuated_set_and_limits_come_from_definitions(
    db: AsyncSession,
) -> None:
    service, robot, parts = await _arm(db)
    await put_entity_config(
        db,
        service.project_id,
        robot,
        EntityHardwareConfig(
            entity_id=robot.id,
            bus_map=[BusMapEntry(protocol="fixture", address="3", part_entity_id=parts["fore"].id)],
            provenance={"bus_map": ProvenanceRecord(by=FieldProvenance.USER)},
        ),
        expected_version=0,
        created_by=None,
    )
    db.add_all(
        [
            _mate(parts["base"], parts["upper"], "revolute", "Fm1"),
            _mate(parts["upper"], parts["fore"], "REVOLUTE", "Fm2"),
        ]
    )
    await db.commit()
    before = await _rows(db)

    twin = await twin_of(service, _placed(parts), robot.id, library=LIBRARY)

    assert await _rows(db) == before  # the twin reads; `materialize` persists it
    elbow = {"part_entity_id": str(parts["fore"].id), "protocol": "fixture", "address": "3"}
    assert twin["actuated"] == [elbow]
    shoulder, wrist = twin["candidate_joints"]
    assert (shoulder["name"], shoulder["actuated"], shoulder["actuator"]) == ("Fm1", False, None)
    assert shoulder["limits"] is None
    assert (wrist["name"], wrist["actuated"], wrist["actuator"]) == ("Fm2", True, elbow)
    # A definition states no unit, so its limits never become a joint's radians or metres.
    assert wrist["limits"] == {"lower": -150, "upper": 150, "unit": None, "source": "definition"}
    assert "lower" not in wrist and "upper" not in wrist


async def test_a_sensor_site_sits_where_mounts_places_it_and_masses_stay_unknown(
    db: AsyncSession,
) -> None:
    service, robot, parts = await _arm(db)
    camera, imu, gps = (
        GraphEntity(
            project_id=service.project_id,
            kind=kinds.PART,
            domain=Domain.ELECTRICAL,
            origin="manual",
            name=name,
        )
        for name in ("camera", "imu", "gps")
    )
    db.add_all([camera, imu, gps])
    await db.flush()
    # (device, origin, confidence, attrs): a person's edge, an accepted inference, and a candidate
    # inference, which is a proposal and so never a site.
    placement: tuple[tuple[GraphEntity, str, float, dict[str, Any]], ...] = (
        (camera, "manual", 1.0, {"position_m": [0.01, 0.0, 0.002]}),
        (imu, "inferred", 0.9, {}),
        (gps, "inferred", 0.7, {"position_m": [0.0, 0.0, 0.0]}),
    )
    for device, origin, confidence, attrs in placement:
        db.add(
            GraphEdge(
                project_id=service.project_id,
                src_id=parts["fore"].id,
                dst_id=device.id,
                relation_type="mounts",
                domain_pair="electrical<->mechanical",
                origin=origin,
                confidence=confidence,
                attrs=attrs,
            )
        )
    await db.commit()

    twin = await twin_of(service, _placed(parts), robot.id, library=LIBRARY)

    placed, unplaced = sorted(twin["sensor_sites"], key=lambda site: site["xyz"] == "unknown")
    assert placed["device_entity_id"] == str(camera.id)
    assert placed["link"] == str(parts["fore"].id)
    # 10 mm out along the forearm, which itself sits 100 mm out.
    assert placed["xyz"] == pytest.approx([0.11, 0.0, 0.002])
    assert unplaced == {
        "device_entity_id": str(imu.id),
        "link": str(parts["fore"].id),
        "xyz": "unknown",
    }
    assert twin["candidate_joints"] == [] and twin["actuated"] == []
    assert twin["masses"] == {}
    assert [need["name"] for need in twin["missing"]] == ["mass"]
    assert any("mass" in line for line in twin["warnings"])


async def test_only_the_bounded_number_of_moving_mates_are_listed(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_api.livebench.scene import cad_import

    service, robot, parts = await _arm(db)
    db.add_all(
        [
            _mate(parts["base"], parts["upper"], "REVOLUTE", "Fm1"),
            _mate(parts["upper"], parts["fore"], "SLIDER", "Fs1"),
        ]
    )
    await db.commit()
    monkeypatch.setattr(cad_import, "MAX_CANDIDATES", 1)

    twin = await twin_of(service, _placed(parts), robot.id, library=LIBRARY)

    assert [joint["name"] for joint in twin["candidate_joints"]] == ["Fm1"]
    assert any("first 1" in line for line in twin["warnings"])
