"""The one edge writer (SOLUSDEV-320 T2): upsert, evidence merge, lifecycle, candidates."""

from __future__ import annotations

import importlib
import uuid
from typing import Any

import pytest
from solus_api.checkers import attributes as av
from solus_api.checkers.core import PowerCompatibilityChecker
from solus_api.core.errors import APIError
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.graph.edges import (
    candidates,
    confirm_edge,
    decline_edge,
    is_candidate,
    projected_copy,
    retire_edge,
    supersede_edge,
    write_edge,
)
from solus_api.graph.neighborhood import Neighborhood, to_graph_context
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, Team, utcnow
from solus_contracts.relations import EdgeEvidence, EvidenceKind
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# The scene fixture + bind helper live in an untyped test module; load them dynamically so
# mypy does not follow that module into this typed one (H10 runs mypy on changed files).
_scene_tests = importlib.import_module("test_scene_cad_refresh")
scene = _scene_tests.scene  # pytest discovers the fixture through this module attribute
bind = _scene_tests.bind

USER = uuid.uuid4()


async def _project(db: AsyncSession) -> uuid.UUID:
    team = Team(name="edges")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="edges")
    db.add(project)
    await db.flush()
    return project.id


async def _entity(
    db: AsyncSession, project_id: uuid.UUID, domain: Domain, name: str = "e", **attrs: Any
) -> GraphEntity:
    row = GraphEntity(
        project_id=project_id,
        kind="component",
        domain=domain,
        origin="manual",
        name=name,
        attrs=attrs,
    )
    db.add(row)
    await db.flush()
    return row


def _ev(ref: str, kind: EvidenceKind = EvidenceKind.NETLIST) -> EdgeEvidence:
    return EdgeEvidence(kind=kind, ref=ref)


async def _write(
    db: AsyncSession, project_id: uuid.UUID, src: GraphEntity, dst: GraphEntity, **kw: Any
) -> GraphEdge:
    base: dict[str, Any] = {
        "relation_type": "powers",
        "origin": "inferred",
        "confidence": 0.5,
        "evidence": [_ev("n1")],
        "created_by": USER,
    }
    base.update(kw)
    return await write_edge(db, project_id=project_id, src_id=src.id, dst_id=dst.id, **base)


async def test_upsert_returns_same_row_and_merges_evidence(db: AsyncSession) -> None:
    pid = await _project(db)
    a, b = await _entity(db, pid, Domain.ELECTRICAL), await _entity(db, pid, Domain.ELECTRICAL)
    first = await _write(db, pid, a, b, evidence=[_ev("n1")])
    second = await _write(db, pid, a, b, evidence=[_ev("n1"), _ev("n2")])
    assert second.id == first.id
    assert [e["ref"] for e in second.attrs["evidence"]] == ["n1", "n2"]
    assert second.attrs["created_by"] == str(USER)
    assert second.attrs["matrix_cell"] == "electrical->electrical"


async def test_confidence_max_unless_manual_and_manual_never_downgraded(db: AsyncSession) -> None:
    pid = await _project(db)
    a, b = await _entity(db, pid, Domain.ELECTRICAL), await _entity(db, pid, Domain.ELECTRICAL)
    edge = await _write(db, pid, a, b, confidence=0.7)
    edge = await _write(db, pid, a, b, confidence=0.4)
    assert edge.confidence == pytest.approx(0.7)
    edge = await _write(db, pid, a, b, origin="manual", confidence=0.3)
    assert edge.confidence == pytest.approx(0.3) and edge.origin == "manual"
    edge = await _write(db, pid, a, b, origin="inferred", confidence=0.9)
    assert edge.origin == "manual" and edge.confidence == pytest.approx(0.9)


async def test_domain_pair_is_derived_alphabetically(db: AsyncSession) -> None:
    pid = await _project(db)
    robot = await _entity(db, pid, Domain.PROJECT)
    brain = await _entity(db, pid, Domain.ELECTRICAL)
    edge = await _write(db, pid, robot, brain, relation_type="contains", origin="manual")
    assert edge.domain_pair == "electrical<->project"
    assert "matrix_cell" not in edge.attrs


async def test_unknown_relation_type_is_422_and_legacy_is_allowed(db: AsyncSession) -> None:
    pid = await _project(db)
    a, b = await _entity(db, pid, Domain.CODE), await _entity(db, pid, Domain.CODE)
    with pytest.raises(APIError) as exc:
        await _write(db, pid, a, b, relation_type="teleports")
    assert exc.value.status_code == 422 and exc.value.code == "validation_error"
    with pytest.raises(APIError) as origin_exc:
        await _write(db, pid, a, b, origin="derived")
    assert origin_exc.value.status_code == 422
    legacy = await _write(db, pid, a, b, relation_type="clone_of", origin="system")
    assert legacy.relation_type == "clone_of"


async def test_missing_or_foreign_endpoint_is_404(db: AsyncSession) -> None:
    pid, other = await _project(db), await _project(db)
    a = await _entity(db, pid, Domain.CODE)
    foreign = await _entity(db, other, Domain.CODE)
    with pytest.raises(APIError) as exc:
        await _write(db, pid, a, foreign)
    assert exc.value.status_code == 404


async def test_edge_id_resurrects_and_managed_by_conflicts(db: AsyncSession) -> None:
    pid = await _project(db)
    a, b = await _entity(db, pid, Domain.ELECTRICAL), await _entity(db, pid, Domain.ELECTRICAL)
    edge_id = uuid.uuid5(pid, "topology:a:b")
    edge = await _write(
        db, pid, a, b, origin="manual", edge_id=edge_id, managed_by="m1", attrs={"managed_by": "m1"}
    )
    assert edge.id == edge_id
    retire_edge(edge)
    await db.flush()
    again = await _write(
        db, pid, a, b, origin="manual", edge_id=edge_id, managed_by="m1", attrs={"managed_by": "m1"}
    )
    assert again is edge and again.deleted_at is None
    with pytest.raises(APIError) as exc:
        await _write(db, pid, a, b, origin="manual", edge_id=edge_id, managed_by="other")
    assert exc.value.status_code == 409 and exc.value.code == "topology_conflict"


async def test_confirm_decline_supersede(db: AsyncSession) -> None:
    pid = await _project(db)
    a, b = await _entity(db, pid, Domain.ELECTRICAL), await _entity(db, pid, Domain.ELECTRICAL)
    edge = await _write(db, pid, a, b)
    assert is_candidate(edge)
    confirmed = await confirm_edge(db, pid, edge.id, USER)
    assert confirmed.origin == "manual" and confirmed.confidence == 1.0
    assert ("user_confirmed", str(USER)) in {
        (e["kind"], e["ref"]) for e in confirmed.attrs["evidence"]
    }
    assert confirmed.attrs["confirmed_by"] == str(USER) and confirmed.attrs["confirmed_at"]
    assert not is_candidate(confirmed)

    other = await _write(db, pid, b, a)
    declined = await decline_edge(db, pid, other.id, USER, "wrong")
    assert declined.deleted_at is not None
    assert declined.attrs["declined_by"] == str(USER)
    assert declined.attrs["declined_reason"] == "wrong" and declined.attrs["declined_at"]
    with pytest.raises(APIError) as exc:
        await confirm_edge(db, pid, other.id, USER)
    assert exc.value.status_code == 404

    replacement = await _write(db, pid, a, b, relation_type="drives")
    await supersede_edge(db, pid, confirmed.id, replacement.id)
    assert confirmed.deleted_at is not None
    assert confirmed.attrs["superseded_by"] == str(replacement.id)


async def test_declined_candidate_is_not_reproposed_with_same_evidence(db: AsyncSession) -> None:
    pid = await _project(db)
    a, b = await _entity(db, pid, Domain.ELECTRICAL), await _entity(db, pid, Domain.ELECTRICAL)
    edge = await _write(db, pid, a, b, evidence=[_ev("n1")])
    await decline_edge(db, pid, edge.id, USER, None)
    same = await _write(db, pid, a, b, evidence=[_ev("n1")])
    assert same is edge and same.deleted_at is not None
    fresh = await _write(db, pid, a, b, evidence=[_ev("n1"), _ev("n2")])
    assert fresh.id != edge.id and fresh.deleted_at is None


async def test_candidates_filters_by_threshold_type_and_subject(db: AsyncSession) -> None:
    pid = await _project(db)
    a = await _entity(db, pid, Domain.ELECTRICAL, "a")
    b = await _entity(db, pid, Domain.ELECTRICAL, "b")
    c = await _entity(db, pid, Domain.ELECTRICAL, "c")
    low = await _write(db, pid, a, b, confidence=0.5)
    await _write(db, pid, a, c, confidence=0.95)  # not a candidate
    await _write(db, pid, b, c, relation_type="drives", confidence=0.2)
    manual = await _write(db, pid, c, a, origin="manual", confidence=0.1)
    retired = await _write(db, pid, c, b, confidence=0.1)
    retire_edge(retired)
    await db.flush()
    found = await candidates(db, pid)
    assert {e.id for e in found} == {low.id} | {e.id for e in found if e.relation_type == "drives"}
    assert manual.id not in {e.id for e in found}
    assert [e.id for e in await candidates(db, pid, relation_type="powers")] == [low.id]
    assert [e.id for e in await candidates(db, pid, subject=b.id, relation_type="powers")] == [
        low.id
    ]
    assert await candidates(db, pid, subject=c.id, relation_type="powers") == []


async def test_confirm_decline_are_project_scoped(db: AsyncSession) -> None:
    pid, other = await _project(db), await _project(db)
    x, y = await _entity(db, other, Domain.ELECTRICAL), await _entity(db, other, Domain.ELECTRICAL)
    theirs = await _write(db, other, x, y)
    with pytest.raises(APIError) as confirm_exc:
        await confirm_edge(db, pid, theirs.id, USER)
    assert confirm_exc.value.status_code == 404
    with pytest.raises(APIError) as decline_exc:
        await decline_edge(db, pid, theirs.id, USER, "mine now")
    assert decline_exc.value.status_code == 404
    assert theirs.origin == "inferred" and theirs.deleted_at is None
    assert "declined_by" not in theirs.attrs and "confirmed_by" not in theirs.attrs

    a, b = await _entity(db, pid, Domain.ELECTRICAL), await _entity(db, pid, Domain.ELECTRICAL)
    mine = await _write(db, pid, a, b)
    with pytest.raises(APIError) as old_exc:
        await supersede_edge(db, pid, theirs.id, mine.id)
    assert old_exc.value.status_code == 404
    with pytest.raises(APIError) as new_exc:
        await supersede_edge(db, pid, mine.id, theirs.id)
    assert new_exc.value.status_code == 404
    assert mine.deleted_at is None and theirs.deleted_at is None


async def test_decline_manual_edge_is_404(db: AsyncSession) -> None:
    pid = await _project(db)
    a, b = await _entity(db, pid, Domain.ELECTRICAL), await _entity(db, pid, Domain.ELECTRICAL)
    manual = await _write(db, pid, a, b, origin="manual", confidence=1.0)
    for call in (confirm_edge, decline_edge):
        with pytest.raises(APIError) as exc:
            await call(db, pid, manual.id, USER, *(["no"] if call is decline_edge else []))
        assert exc.value.status_code == 404
    assert manual.deleted_at is None and "declined_by" not in manual.attrs


async def test_candidates_are_project_scoped(db: AsyncSession) -> None:
    pid, other = await _project(db), await _project(db)
    a, b = await _entity(db, pid, Domain.ELECTRICAL), await _entity(db, pid, Domain.ELECTRICAL)
    x, y = await _entity(db, other, Domain.ELECTRICAL), await _entity(db, other, Domain.ELECTRICAL)
    low = await _write(db, pid, a, b, confidence=0.5)
    await _write(db, other, x, y, confidence=0.5)
    assert [e.id for e in await candidates(db, pid)] == [low.id]
    assert await candidates(db, pid, subject=x.id) == []


async def test_edge_id_owned_by_another_project_is_409(db: AsyncSession) -> None:
    pid, other = await _project(db), await _project(db)
    a, b = await _entity(db, pid, Domain.ELECTRICAL), await _entity(db, pid, Domain.ELECTRICAL)
    x, y = await _entity(db, other, Domain.ELECTRICAL), await _entity(db, other, Domain.ELECTRICAL)
    edge_id = uuid.uuid5(other, "topology:x:y")
    managed = {
        "origin": "manual",
        "edge_id": edge_id,
        "managed_by": "m1",
        "attrs": {"managed_by": "m1"},
    }
    theirs = await _write(db, other, x, y, **managed)
    with pytest.raises(APIError) as exc:
        await _write(db, pid, a, b, **managed)
    assert exc.value.status_code == 409 and exc.value.code == "topology_conflict"
    assert (theirs.project_id, theirs.src_id, theirs.dst_id) == (other, x.id, y.id)
    assert theirs.deleted_at is None


async def test_managed_edge_id_write_replaces_evidence_and_attrs(db: AsyncSession) -> None:
    pid = await _project(db)
    a, b = await _entity(db, pid, Domain.ELECTRICAL), await _entity(db, pid, Domain.ELECTRICAL)
    edge_id = uuid.uuid5(pid, "topology:a:b")

    def sync(source: str, **extra: Any) -> dict[str, Any]:
        return {
            "origin": "manual",
            "edge_id": edge_id,
            "managed_by": "m1",
            "attrs": {"managed_by": "m1", **extra},
            "evidence": [EdgeEvidence(kind=EvidenceKind.CONFIG, ref="bus_map", detail=source)],
        }

    first = await _write(db, pid, a, b, **sync("a.ino", software="ros2"))
    second = await _write(db, pid, a, b, **sync("b.ino"))
    assert second is first
    assert [e["detail"] for e in second.attrs["evidence"]] == ["b.ino"]
    assert "software" not in second.attrs
    assert second.attrs["created_by"] == str(USER)


async def test_deleted_endpoint_is_404(db: AsyncSession) -> None:
    pid = await _project(db)
    a, b = await _entity(db, pid, Domain.ELECTRICAL), await _entity(db, pid, Domain.ELECTRICAL)
    b.deleted_at = utcnow()
    await db.flush()
    with pytest.raises(APIError) as exc:
        await _write(db, pid, a, b)
    assert exc.value.status_code == 404


def test_projected_copy_is_transient() -> None:
    edge = GraphEdge(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        src_id=uuid.uuid4(),
        dst_id=uuid.uuid4(),
        relation_type="contains",
        domain_pair="code<->code",
        origin="manual",
        attrs={"k": 1},
    )
    new_src = uuid.uuid4()
    copy = projected_copy(edge, src_id=new_src)
    assert copy is not edge and copy.src_id == new_src and copy.dst_id == edge.dst_id
    assert copy.id == edge.id and copy.attrs == {"k": 1}


async def test_bind_cad_twice_leaves_one_live_edge(
    client: Any,
    alice_headers: dict[str, str],
    scene: Any,  # noqa: F811
    db: AsyncSession,
) -> None:
    base, _, leaf, model, _ = scene
    bound = await bind(client, alice_headers, scene)
    key = next(iter(model["model"]["meshes"]))
    second = await client.put(
        f"{base}/models/{model['id']}/cad-bindings",
        headers=alice_headers,
        json={
            "expected_version": bound["version"],
            "bindings": [{"mesh_key": key, "source_entity_id": str(leaf.id)}],
        },
    )
    assert second.status_code == 202, second.text
    rows = list(
        await db.scalars(
            select(GraphEdge).where(
                GraphEdge.src_id == uuid.UUID(model["id"]),
                GraphEdge.relation_type == "cad_visual_for",
            )
        )
    )
    assert len([r for r in rows if r.deleted_at is None]) == 1
    assert rows and all(r.domain_pair == "mechanical<->simulation" for r in rows)
    project = base.split("/")[4]
    listed = await client.get(
        f"/api/v1/projects/{project}/entities/{model['id']}/relations?type=cad_visual_for",
        headers=alice_headers,
    )
    assert listed.status_code == 200, listed.text
    data = listed.json()["data"]
    assert len(data) == 1
    assert data[0]["confidence"] == 1.0 and data[0]["domain_pair"] == "mechanical<->simulation"


async def test_candidate_powers_edge_never_reaches_checkers(db: AsyncSession) -> None:
    pid = await _project(db)
    supply = await _entity(
        db,
        pid,
        Domain.ELECTRICAL,
        "buck_5v",
        **{av.PART_CLASS: av.SUPPLY, av.VOLTAGE_NOMINAL_V: 5.0, av.CURRENT_MAX_A: 2.0},
    )
    load_attrs = {av.PART_CLASS: av.LOAD, av.VOLTAGE_REQUIRED_V: 5.0, av.CURRENT_DRAW_A: 1.5}
    compute = await _entity(db, pid, Domain.ELECTRICAL, "compute", **load_attrs)
    radio = await _entity(db, pid, Domain.ELECTRICAL, "radio", **load_attrs)
    confirmed = await _write(db, pid, supply, compute, origin="manual", confidence=1.0)
    candidate = await _write(db, pid, supply, radio, confidence=0.7)
    parts = FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])

    context = to_graph_context(
        Neighborhood(
            entities=[supply, compute, radio], edges=[confirmed, candidate], truncated=False
        )
    )
    assert [(e.src_id, e.dst_id) for e in context.edges] == [(supply.id, compute.id)]
    assert PowerCompatibilityChecker().check(context, parts) == []

    await confirm_edge(db, pid, candidate.id, USER)
    context = to_graph_context(
        Neighborhood(
            entities=[supply, compute, radio], edges=[confirmed, candidate], truncated=False
        )
    )
    assert len(context.edges) == 2
    assert PowerCompatibilityChecker().check(context, parts)
