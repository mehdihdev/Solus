"""CAD associations require graph identity evidence and an explicit decision."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from solus_api.core.errors import APIError
from solus_api.hardware.cad_suggestions import accept_cad_suggestion, propose_cad_suggestions
from solus_api.hardware.links import decide_suggestion
from solus_api.models import GraphEdge, GraphEntity, User, utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def setup_graph(
    client: Any, headers: dict[str, str], db: AsyncSession
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, GraphEdge]:
    from test_hardware_attach import _attach_robot, _connector_parts
    from test_hardware_detect import _detect_project

    project_id, team_id = await _detect_project(client, headers)
    robot_id = await _attach_robot(client, headers, project_id)
    cad, known = await _connector_parts(
        db, project_id, team_id, ["CAD gripper", "Known end effector"]
    )
    response = await client.post(
        f"/api/v1/projects/{project_id}/hardware/robots/{robot_id}/parts/attach",
        headers=headers,
        json={"entity_ids": [str(known)], "category": "end_effectors"},
    )
    assert response.status_code == 200
    edge = GraphEdge(
        project_id=uuid.UUID(project_id),
        src_id=cad,
        dst_id=known,
        relation_type="same_as",
        domain_pair="mechanical<->mechanical",
        origin="linking",
        confidence=0.92,
        attrs={
            "matched": True,
            "canonical_id": str(uuid.uuid4()),
            "part_number": "QA-GRIPPER",
            "modalities": ["cad_model", "part_number"],
        },
    )
    db.add(edge)
    await db.commit()
    return uuid.UUID(project_id), uuid.UUID(robot_id), cad, edge


async def test_propose_then_accept_attaches_same_cad_entity_once(
    client: Any, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, robot, cad, _ = await setup_graph(client, alice_headers, db)
    user = await db.scalar(select(User.id).limit(1))
    assert user is not None
    [suggestion] = await propose_cad_suggestions(db, project, cad, await actor(db))
    assert suggestion.candidate_robot_id == robot
    assert suggestion.evidence[0]["modality"] == "cad_model"
    assert not (await db.get(GraphEntity, cad)).attrs.get("robot_id")
    await decide_suggestion(db, project, suggestion.id, True, user)
    result = await accept_cad_suggestion(db, project, suggestion, user)
    assert result["bound"] is True and result["robot_id"] == robot
    repeated = await accept_cad_suggestion(db, project, suggestion, user)
    assert repeated["bound"] is True
    assert result["attached_count"] == 1 and repeated["attached_count"] == 0
    assert await propose_cad_suggestions(db, project, cad, await actor(db)) == []


@pytest.mark.parametrize(
    "damage", ["low", "unmatched", "untrusted", "deleted", "no_edge", "foreign"]
)
async def test_cad_has_no_name_only_or_untrusted_suggestion(
    client: Any, alice_headers: dict[str, str], db: AsyncSession, damage: str
) -> None:
    project, _, cad, edge = await setup_graph(client, alice_headers, db)
    if damage == "low":
        edge.confidence = 0.5
    if damage == "unmatched":
        edge.attrs = {**edge.attrs, "matched": False}
    if damage == "untrusted":
        edge.origin = "connector"
    if damage == "deleted":
        edge.deleted_at = utcnow()
    if damage == "no_edge":
        edge.relation_type = "mates_with"
    if damage == "foreign":
        with pytest.raises(APIError) as exc:
            await propose_cad_suggestions(db, uuid.uuid4(), cad, await actor(db))
        assert exc.value.status_code == 404
        return
    await db.flush()
    assert await propose_cad_suggestions(db, project, cad, await actor(db)) == []


async def test_stale_evidence_refuses_accept_and_decline_survives_rescan(
    client: Any, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project, _, cad, edge = await setup_graph(client, alice_headers, db)
    user = await db.scalar(select(User.id).limit(1))
    assert user is not None
    [suggestion] = await propose_cad_suggestions(db, project, cad, await actor(db))
    edge.attrs = {**edge.attrs, "canonical_id": str(uuid.uuid4())}
    await db.flush()
    with pytest.raises(APIError) as exc:
        await accept_cad_suggestion(db, project, suggestion, user)
    assert exc.value.status_code == 409
    await decide_suggestion(db, project, suggestion.id, False, user)
    # New canonical evidence permits a new review; unchanged evidence remains declined.
    [fresh] = await propose_cad_suggestions(db, project, cad, await actor(db))
    await decide_suggestion(db, project, fresh.id, False, user)
    assert await propose_cad_suggestions(db, project, cad, await actor(db)) == []


async def test_ambiguous_robot_owners_never_propose(
    client: Any, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from test_hardware_attach import _attach_robot

    project, _, cad, edge = await setup_graph(client, alice_headers, db)
    other = await _attach_robot(client, alice_headers, str(project))
    category = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == project,
            GraphEntity.kind == "robot_category",
            GraphEntity.attrs["robot_id"].astext == other,
            GraphEntity.attrs["category"].astext == "end_effectors",
        )
    )
    assert category is not None
    # Corrupt/ambiguous dual ownership is refused, not selected by query order.
    db.add(
        GraphEdge(
            project_id=project,
            src_id=category.id,
            dst_id=edge.dst_id,
            relation_type="contains",
            domain_pair="project<->mechanical",
            origin="manual",
        )
    )
    await db.flush()
    assert await propose_cad_suggestions(db, project, cad, await actor(db)) == []


async def test_stale_pending_proposal_is_superseded_on_explicit_refresh(
    client: Any, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from solus_api.models import SuggestionStatus

    project, _, cad, edge = await setup_graph(client, alice_headers, db)
    [old] = await propose_cad_suggestions(db, project, cad, await actor(db))
    old_id = old.id
    edge.attrs = {**edge.attrs, "canonical_id": str(uuid.uuid4())}
    await db.flush()
    [fresh] = await propose_cad_suggestions(db, project, cad, await actor(db))
    assert fresh.id != old_id
    assert old.status is SuggestionStatus.SUPERSEDED


async def test_cad_http_proposal_decision_and_stale_review(
    client: Any, alice_headers: dict[str, str], bob_headers: dict[str, str], db: AsyncSession
) -> None:
    from conftest import me
    from solus_api.models import HardwareSuggestion, SuggestionStatus

    project, robot, cad, edge = await setup_graph(client, alice_headers, db)
    base = f"/api/v1/projects/{project}/hardware"
    proposed = await client.post(f"{base}/parts/{cad}/suggestions", headers=alice_headers)
    assert proposed.status_code == 200, proposed.text
    [row] = proposed.json()["data"]
    assert row["candidate_robot_id"] == str(robot)
    await me(client, bob_headers)
    foreign = await client.post(f"{base}/suggestions/{row['id']}/accept", headers=bob_headers)
    assert foreign.status_code == 404
    edge.attrs = {**edge.attrs, "canonical_id": str(uuid.uuid4())}
    await db.commit()
    stale = await client.post(f"{base}/suggestions/{row['id']}/accept", headers=alice_headers)
    assert stale.status_code == 409, stale.text
    stored = await db.get(HardwareSuggestion, uuid.UUID(row["id"]), populate_existing=True)
    assert stored is not None and stored.status is SuggestionStatus.PENDING
    refreshed = await client.post(f"{base}/parts/{cad}/suggestions", headers=alice_headers)
    assert refreshed.status_code == 200, refreshed.text
    [fresh] = refreshed.json()["data"]
    assert fresh["id"] != row["id"]
    accepted = await client.post(f"{base}/suggestions/{fresh['id']}/accept", headers=alice_headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["bound"] is True
    assert accepted.json()["data"]["robot_id"] == str(robot)
    unassigned = await client.get(f"{base}/unassigned", headers=alice_headers)
    assert all(item["id"] != str(cad) for item in unassigned.json()["data"])


async def actor(db: AsyncSession) -> uuid.UUID:
    user = await db.scalar(select(User.id).limit(1))
    assert user is not None
    return user


async def test_same_user_unverified_token_cannot_accept_cad(
    client: Any, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from conftest import ALICE, bearer

    project, _, cad, _ = await setup_graph(client, alice_headers, db)
    [suggestion] = await propose_cad_suggestions(db, project, cad, await actor(db))
    await db.commit()
    unverified = bearer(ALICE["sub"], ALICE["email"], email_verified=False)
    response = await client.post(
        f"/api/v1/projects/{project}/hardware/suggestions/{suggestion.id}/accept",
        headers=unverified,
    )
    assert response.status_code == 403


async def test_hidden_revision_cad_is_not_available_in_default_graph_scope(
    client: Any, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from solus_api.models import Source, SourceType

    project, _, cad, _ = await setup_graph(client, alice_headers, db)
    part = await db.get(GraphEntity, cad)
    assert part is not None and part.source_id is not None
    base = await db.get(Source, part.source_id)
    assert base is not None
    hidden = Source(
        project_id=project,
        team_id=base.team_id,
        type=SourceType.ONSHAPE,
        name="Hidden revision",
        config={},
        status="connected",
        revision_base_source_id=base.id,
    )
    db.add(hidden)
    await db.flush()
    part.source_id = hidden.id
    await db.flush()
    with pytest.raises(APIError) as exc:
        await propose_cad_suggestions(db, project, cad, await actor(db))
    assert exc.value.status_code == 404


@pytest.mark.parametrize("hidden_subject", [True, False])
async def test_listing_filters_hidden_cad_references_without_mutating_history(
    client: Any,
    alice_headers: dict[str, str],
    db: AsyncSession,
    hidden_subject: bool,
) -> None:
    from solus_api.hardware.cad_suggestions import filter_visible_cad_suggestions
    from solus_api.models import Source, SourceType, SuggestionStatus

    project, _, cad, edge = await setup_graph(client, alice_headers, db)
    user = await actor(db)
    [suggestion] = await propose_cad_suggestions(db, project, cad, user)
    assert await filter_visible_cad_suggestions(db, project, user, [suggestion]) == [suggestion]
    part = await db.get(GraphEntity, cad if hidden_subject else edge.dst_id)
    assert part is not None and part.source_id is not None
    base = await db.get(Source, part.source_id)
    assert base is not None
    hidden = Source(
        project_id=project,
        team_id=base.team_id,
        type=SourceType.ONSHAPE,
        name="Hidden revision",
        config={},
        status="connected",
        revision_base_source_id=base.id,
    )
    db.add(hidden)
    await db.flush()
    part.source_id = hidden.id
    await db.flush()
    assert await filter_visible_cad_suggestions(db, project, user, [suggestion]) == []
    assert suggestion.status is SuggestionStatus.PENDING
    await db.commit()
    response = await client.get(
        f"/api/v1/projects/{project}/hardware/suggestions", headers=alice_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"] == []
    # Legacy device decisions do not depend on CAD revision evidence.
    suggestion.subject_kind = "device"
    assert await filter_visible_cad_suggestions(db, project, user, [suggestion]) == [suggestion]


async def test_listing_hides_malformed_cad_evidence(
    client: Any, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    from solus_api.hardware.cad_suggestions import filter_visible_cad_suggestions

    project, _, cad, _ = await setup_graph(client, alice_headers, db)
    user = await actor(db)
    [suggestion] = await propose_cad_suggestions(db, project, cad, user)
    suggestion.evidence = [
        {
            **suggestion.evidence[0],
            "evidence": {**suggestion.evidence[0]["evidence"], "counterpart_id": "not-a-graph-id"},
        }
    ]
    assert await filter_visible_cad_suggestions(db, project, user, [suggestion]) == []
