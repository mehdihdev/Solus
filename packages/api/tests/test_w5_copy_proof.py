"""W5 saved binding removal and rediscovery; fixtures never open actual hardware.

The standalone run_copy_proof helper accepts only the explicitly named rehearsal copy.
It never connects to the live database and uses the recorded six-servo identity evidence.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from solus_api.hardware.config import HardwareConfig
from solus_api.hardware.detect import ProposalOut, bind_device, reconcile_device
from solus_api.hardware.links import decide_suggestion
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import put_config, robot_root
from solus_api.models import GraphEntity, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def recorded_proposal() -> ProposalOut:
    """Read-only capture docs/qa/SOLUSDEV-262-both-arms-live.json: STS3215 IDs1..6."""
    ref = "usb:5B42134331"
    return ProposalOut.model_validate(
        {
            "disambiguation": None,
            "device_ref": ref,
            "identity": {"kind": "usb_serial", "binding": "5B42134331", "vid": 6790, "pid": 21971},
            "level": "protocol",
            "summary": "Six STS3215 servos",
            "driver_id": "feetech-sts",
            "params": {"baud": 1000000, "protocol_version": 0},
            "rows": [
                {
                    "id": f"{ref}/{i}",
                    "subject": f"STS3215 at {i}",
                    "address": str(i),
                    "model": "STS3215",
                    "proposed_function": None,
                    "confidence": 0.92,
                    "evidence": [],
                    "provenance": "bus",
                }
                for i in range(1, 7)
            ],
            "confidence": 0.92,
            "evidence": [
                {
                    "modality": "bus_enumeration",
                    "source_ref": {"source_connector": "feetech-sts", "external_ref": ref},
                    "confidence": 0.92,
                    "state": "matched",
                    "evidence": {"value": "STS3215"},
                }
            ],
        }
    )


async def removed_binding_proof(
    session: AsyncSession, project: uuid.UUID, robot_id: uuid.UUID
) -> dict[str, Any]:
    robot = await robot_root(session, project, robot_id)
    user = await session.scalar(select(User.id).limit(1))
    assert user is not None
    config = await resolve_runtime_config(session, project, robot.id)
    assert config.identity is None or config.identity.binding == "5B42134331"
    before_parts = set(config.parts)
    before_calibration = {key: part.calibration for key, part in config.parts.items()}
    before_count = await session.scalar(
        select(func.count())
        .select_from(GraphEntity)
        .where(
            GraphEntity.project_id == project,
            GraphEntity.kind == "physical_robot",
            GraphEntity.deleted_at.is_(None),
        )
    )
    document = config.model_dump(mode="json")
    document["identity"] = None
    document["provenance"] = {
        key: value
        for key, value in document["provenance"].items()
        if key != "identity" and not key.startswith("identity.")
    }
    await put_config(
        session, project, robot, HardwareConfig.model_validate(document), created_by=user
    )
    await session.commit()
    suggestions = await reconcile_device(session, project, recorded_proposal())
    candidates = [row for row in suggestions if row.candidate_robot_id == robot_id]
    if not candidates:
        await session.rollback()
        return {
            "status": "failed",
            "reason": "No suggestion for the retained robot after binding removal",
            "accepted_parts": len(before_parts),
            "wire_addresses": 6,
        }
    await decide_suggestion(session, project, candidates[0].id, True, user)
    await bind_device(session, project, robot, recorded_proposal(), created_by=user)
    await session.commit()
    rebound = await resolve_runtime_config(session, project, robot_id)
    after_count = await session.scalar(
        select(func.count())
        .select_from(GraphEntity)
        .where(
            GraphEntity.project_id == project,
            GraphEntity.kind == "physical_robot",
            GraphEntity.deleted_at.is_(None),
        )
    )
    assert set(rebound.parts) == before_parts
    assert {key: part.calibration for key, part in rebound.parts.items()} == before_calibration
    assert after_count == before_count
    assert rebound.identity is not None and rebound.identity.binding == "5B42134331"
    return {
        "status": "passed",
        "accepted_parts": len(before_parts),
        "wire_addresses": 6,
        "same_robot": True,
        "same_part_ids": True,
        "same_calibration": True,
        "robot_count_before": before_count,
        "robot_count_after": after_count,
        "hardware_io": False,
    }


async def run_copy_proof(database_url: str, robot_id: str, project_id: str) -> dict[str, Any]:
    from sqlalchemy.engine import make_url

    if make_url(database_url).database != "solus_262_w5_copy_20260914":
        raise ValueError("Proof must run only against the explicitly created W5 copy")
    engine = create_async_engine(database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await removed_binding_proof(session, uuid.UUID(project_id), uuid.UUID(robot_id))
    finally:
        await engine.dispose()


@pytest.mark.parametrize("accepted_count", [1, 6])
async def test_removed_binding_suggests_same_partial_or_complete_robot(
    client: Any,
    alice_headers: dict[str, str],
    db: AsyncSession,
    accepted_count: int,
) -> None:
    from solus_api.hardware.detect import ConfirmIn, confirm_proposal
    from test_hardware_detect import _detect_project

    project_id, _ = await _detect_project(client, alice_headers)
    project = uuid.UUID(project_id)
    user = await db.scalar(select(User.id).limit(1))
    assert user is not None
    result = await confirm_proposal(
        db,
        project_id=project,
        proposal=recorded_proposal(),
        body=ConfirmIn.model_validate(
            {
                "target": {"kind": "new", "name": "Follower"},
                "accepted": [
                    {"row_id": f"usb:5B42134331/{i}"} for i in range(7 - accepted_count, 7)
                ],
                "start_session": False,
            }
        ),
        created_by=user,
    )
    robot_id = result.robot.id
    await db.commit()
    proof = await removed_binding_proof(db, project, robot_id)
    assert proof["status"] == "passed", proof
    repeated = await removed_binding_proof(db, project, robot_id)
    assert repeated["status"] == "passed", repeated


@pytest.mark.parametrize(
    "damage", ["wrong_device", "wrong_address", "foreign_owner", "missing_wire_row"]
)
async def test_retained_binding_refuses_inconsistent_or_absent_graph_evidence(
    client: Any,
    alice_headers: dict[str, str],
    db: AsyncSession,
    damage: str,
) -> None:
    from solus_api.hardware.detect import ConfirmIn, confirm_proposal
    from test_hardware_detect import _detect_project

    project_id, _ = await _detect_project(client, alice_headers)
    project = uuid.UUID(project_id)
    user = await db.scalar(select(User.id).limit(1))
    assert user is not None
    result = await confirm_proposal(
        db,
        project_id=project,
        proposal=recorded_proposal(),
        body=ConfirmIn.model_validate(
            {
                "target": {"kind": "new", "name": "Follower"},
                "accepted": [{"row_id": "usb:5B42134331/6"}],
                "start_session": False,
            }
        ),
        created_by=user,
    )
    part = await db.get(GraphEntity, result.part_ids[0])
    assert part is not None
    if damage == "wrong_device":
        part.attrs = {**part.attrs, "device_ref": "usb:OTHER"}
    if damage == "wrong_address":
        part.attrs = {**part.attrs, "address": "2"}
    if damage == "foreign_owner":
        part.attrs = {**part.attrs, "robot_id": str(uuid.uuid4())}
    await put_config(
        db,
        project,
        result.robot,
        result.config.model_copy(update={"identity": None}),
        created_by=user,
    )
    proposal = recorded_proposal()
    if damage == "missing_wire_row":
        proposal = proposal.model_copy(update={"rows": proposal.rows[:-1]})
    assert await reconcile_device(db, project, proposal) == []


async def test_cad_decline_memory_and_explicit_attachment(
    client: Any,
    alice_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    from solus_api.fingerprint.contract import ModalityMatch
    from solus_api.hardware.links import LinkSuggestion, LinkTier, persist_suggestions
    from test_hardware_attach import _attach_robot, _connector_parts
    from test_hardware_detect import _detect_project

    project_id, team_id = await _detect_project(client, alice_headers)
    robot_id = await _attach_robot(client, alice_headers, project_id)
    [part_id] = await _connector_parts(db, project_id, team_id, ["Fixture gripper"])
    evidence = ModalityMatch.model_validate(
        {
            "modality": "part_number",
            "confidence": 0.95,
            "state": "matched",
            "source_ref": {"graph_entity_id": str(part_id), "source_connector": "onshape"},
            "evidence": {"matched_on": "explicit_fixture_part_number", "value": "QA-GRIPPER-1"},
        }
    )
    suggestion = LinkSuggestion(
        subject_ref=str(part_id),
        subject_kind="part",
        candidate_robot_id=uuid.UUID(robot_id),
        confidence=0.8,
        tier=LinkTier.HIGH,
        evidence=[evidence],
        reason="Fixture-provided CAD association; not automatic CAD inference",
    )
    [saved] = await persist_suggestions(db, uuid.UUID(project_id), [suggestion])
    await db.commit()
    base = f"/api/v1/projects/{project_id}/hardware"
    rejected = await client.post(f"{base}/suggestions/{saved.id}/reject", headers=alice_headers)
    assert rejected.status_code == 200
    assert await persist_suggestions(db, uuid.UUID(project_id), [suggestion]) == []
    await db.commit()
    attached = await client.post(
        f"{base}/robots/{robot_id}/parts/attach",
        headers=alice_headers,
        json={"entity_ids": [str(part_id)], "category": "end_effectors"},
    )
    assert attached.status_code == 200, attached.text
    repeated = await client.post(
        f"{base}/robots/{robot_id}/parts/attach",
        headers=alice_headers,
        json={"entity_ids": [str(part_id)], "category": "end_effectors"},
    )
    assert repeated.status_code == 200, repeated.text
    count = await db.scalar(
        select(func.count()).select_from(GraphEntity).where(GraphEntity.id == part_id)
    )
    assert count == 1
