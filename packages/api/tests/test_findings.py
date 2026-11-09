"""SOLUSDEV-320 T3: findings are `kind=finding` graph nodes (docs/api/findings.md)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from typing import Any

import pytest
from conftest import add_member, create_project, create_team, me
from httpx import AsyncClient
from pydantic import ValidationError
from solus_api.checkers.interface import Severity, Warning
from solus_api.core.db import build_sessionmaker
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.graph.findings import (
    FindingSpec,
    acknowledge_finding,
    annotate_finding,
    canonical_finding_key,
    dismiss_finding,
    finding_from_warning,
    list_findings,
    raise_finding,
    resolve_finding,
    resolve_system_finding,
    subject_rows,
)
from solus_api.models import (
    Activity,
    Domain,
    GraphEdge,
    GraphEntity,
    SolusEntry,
    SolusSection,
    utcnow,
)
from solus_api.services.solus_payloads import ErrorMeta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from test_live_publisher import RecordingHub, commit_then_drain


async def _project_ids(client: AsyncClient, headers: dict[str, str]) -> tuple[uuid.UUID, str]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return uuid.UUID(project["id"]), str(team["id"])


async def _seed_entities(
    db: AsyncSession, project_id: uuid.UUID, n: int, kind: str = kinds.COMPONENT
) -> list[GraphEntity]:
    rows = [
        GraphEntity(project_id=project_id, kind=kind, domain=Domain.ELECTRICAL, name=f"U{i}")
        for i in range(n)
    ]
    db.add_all(rows)
    await db.flush()
    return rows


def _finding_spec(subjects: list[uuid.UUID], **over: Any) -> FindingSpec:
    base: dict[str, Any] = {
        "rule_id": "i2c_address_conflict",
        "severity": Severity.WARNING,
        "source": "checker",
        "headline": "0x68 used twice",
        "subjects": subjects,
        "evidence": {"address": "0x68"},
        "matrix_cell": None,
        "domain": Domain.ELECTRICAL,
        "bucket": None,
    }
    return FindingSpec(**{**base, **over})


async def _finding_rows(db: AsyncSession, project_id: uuid.UUID) -> list[GraphEntity]:
    return list(
        await db.scalars(
            select(GraphEntity).where(
                GraphEntity.project_id == project_id,
                GraphEntity.kind == kinds.FINDING,
                GraphEntity.deleted_at.is_(None),
            )
        )
    )


async def _out_edges(db: AsyncSession, src_id: uuid.UUID, relation: str) -> list[GraphEdge]:
    return list(
        await db.scalars(
            select(GraphEdge).where(
                GraphEdge.src_id == src_id,
                GraphEdge.relation_type == relation,
                GraphEdge.deleted_at.is_(None),
            )
        )
    )


# ------------------------------------------------------------------ service


def test_canonical_key_is_sha1_of_project_rule_sorted_subjects_bucket() -> None:
    pid = uuid.uuid4()
    a, b = uuid.UUID(int=2), uuid.UUID(int=1)
    key = canonical_finding_key(pid, _finding_spec([a, b], bucket="rail:5v"))
    expected = hashlib.sha1(f"{pid}|i2c_address_conflict|{b},{a}|rail:5v".encode()).hexdigest()
    assert key == expected and len(key) == 40
    assert key == canonical_finding_key(pid, _finding_spec([b, a], bucket="rail:5v"))
    assert key != canonical_finding_key(pid, _finding_spec([a, b]))


def test_spec_forbids_extra_and_empty_subjects() -> None:
    with pytest.raises(ValueError):
        _finding_spec([])
    with pytest.raises(ValueError):
        FindingSpec(**{**_finding_spec([uuid.uuid4()]).model_dump(), "extra": 1})


async def test_raise_twice_is_one_node_count_two_and_observed_edges(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project_ids(client, alice_headers)
    a, b = await _seed_entities(db, project_id, 2)
    first = await raise_finding(db, project_id, _finding_spec([a.id, b.id]))
    await db.commit()
    seen = first.attrs["last_seen"]
    second = await raise_finding(
        db, project_id, _finding_spec([b.id, a.id], evidence={"address": "0x69"})
    )
    await db.commit()

    rows = await _finding_rows(db, project_id)
    assert [r.id for r in rows] == [first.id] and second.id == first.id
    node = rows[0]
    assert node.origin == "system" and node.domain == Domain.ELECTRICAL
    assert node.name == "0x68 used twice"
    assert node.canonical_key == canonical_finding_key(project_id, _finding_spec([a.id, b.id]))
    assert node.attrs["count"] == 2 and node.attrs["status"] == "open"
    assert node.attrs["last_seen"] >= seen and node.attrs["first_seen"] <= seen
    assert node.attrs["subjects"] == [str(b.id), str(a.id)]  # blame order of the latest raise
    assert node.attrs["explanation"] == "" and node.attrs["detail"] == ""
    assert node.attrs["evidence"]["address"] == "0x69"
    assert node.attrs["evidence"]["items"] == [{"address": "0x68"}, {"address": "0x69"}]
    edges = await _out_edges(db, node.id, "observed")
    assert {e.dst_id for e in edges} == {a.id, b.id} and len(edges) == 2
    assert all(e.origin == "system" and e.confidence == 1.0 for e in edges)
    assert edges[0].attrs["evidence"] == [
        {"kind": "checker", "ref": "i2c_address_conflict", "detail": None}
    ]


async def test_evidence_items_keep_the_latest_twenty(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project_ids(client, alice_headers)
    (a,) = await _seed_entities(db, project_id, 1)
    for i in range(25):
        node = await raise_finding(db, project_id, _finding_spec([a.id], evidence={"items": [i]}))
    assert node.attrs["evidence"]["items"] == list(range(5, 25))
    assert node.attrs["count"] == 25


async def test_reraise_list_evidence_is_the_latest_raise(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """SOLUSDEV-321 P2-T6 (M71): a re-raise's list-valued evidence (`also`, `causes`) replaces the
    earlier raise's at the top level, as its scalars do — what the pane and the narration read is
    the latest raise; `items` keeps each raise whole."""
    project_id, _ = await _project_ids(client, alice_headers)
    (a,) = await _seed_entities(db, project_id, 1)
    first = {"address": "0x68", "also": ["x"], "causes": [{"kind": "actuator"}]}
    latest = {"address": "0x69", "also": ["y", "z"], "causes": [{"kind": "mechanical_load"}]}
    await raise_finding(db, project_id, _finding_spec([a.id], evidence=first))
    node = await raise_finding(db, project_id, _finding_spec([a.id], evidence=latest))
    evidence = node.attrs["evidence"]
    assert {key: evidence[key] for key in latest} == latest
    assert evidence["items"] == [first, latest]


async def test_raise_rejects_unknown_or_foreign_subjects(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_a, _ = await _project_ids(client, alice_headers)
    project_b, _ = await _project_ids(client, bob_headers)
    (foreign,) = await _seed_entities(db, project_b, 1)
    (mine,) = await _seed_entities(db, project_a, 1)
    for subjects in ([uuid.uuid4()], [foreign.id], [mine.id, foreign.id]):
        with pytest.raises(APIError) as err:
            await raise_finding(db, project_a, _finding_spec(subjects))
        assert err.value.status_code == 404
    assert await _finding_rows(db, project_a) == []


async def test_dismissed_stays_dismissed_until_cooldown_then_reopens(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project_ids(client, alice_headers)
    (a,) = await _seed_entities(db, project_id, 1)
    user = uuid.uuid4()
    node = await raise_finding(db, project_id, _finding_spec([a.id]))
    entries_before = len(list(await db.scalars(select(SolusEntry))))
    await dismiss_finding(db, project_id, node.id, user, cooldown_hours=2)
    assert node.attrs["status"] == "dismissed"
    assert node.attrs["dismissed_until"] > utcnow().isoformat()
    await raise_finding(db, project_id, _finding_spec([a.id]))
    assert node.attrs["status"] == "dismissed" and node.attrs["count"] == 2
    # dismiss creates nothing else
    assert len(list(await db.scalars(select(SolusEntry)))) == entries_before
    assert len(await _out_edges(db, node.id, "observed")) == 1

    node.attrs = {**node.attrs, "dismissed_until": (utcnow() - timedelta(hours=1)).isoformat()}
    await db.flush()
    await raise_finding(db, project_id, _finding_spec([a.id]))
    assert node.attrs["status"] == "open" and node.attrs["count"] == 3
    assert "dismissed_until" not in node.attrs


async def test_resolve_files_one_errors_entry_and_fixed_by_edge_then_reopens_on_raise(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project_ids(client, alice_headers)
    user_id = uuid.UUID((await me(client, alice_headers))["id"])
    a, b, fix = await _seed_entities(db, project_id, 3)
    (machine,) = await _seed_entities(db, project_id, 1, kind=kinds.MACHINE)
    node = await raise_finding(
        db, project_id, _finding_spec([a.id, b.id], evidence={"machine_id": str(machine.id)})
    )
    await raise_finding(db, project_id, _finding_spec([a.id, b.id]))
    await dismiss_finding(db, project_id, node.id, user_id)
    entry, edge = await resolve_finding(
        db, project_id, node.id, user_id, note="swapped the address", fix_ref=fix.id
    )
    await db.commit()

    assert node.attrs["status"] == "resolved" and node.attrs["resolved_by"] == str(user_id)
    assert node.attrs["note"] == "swapped the address"
    assert "dismissed_until" not in node.attrs
    rows = list(
        await db.scalars(
            select(SolusEntry).where(
                SolusEntry.project_id == project_id, SolusEntry.section == SolusSection.ERRORS
            )
        )
    )
    assert [r.id for r in rows] == [entry.id]
    assert entry.author == "user" and entry.created_by == user_id
    assert (
        entry.text == "Resolved i2c_address_conflict: 0x68 used twice\n\nFix: swapped the address"
    )
    meta = ErrorMeta.model_validate(entry.payload)
    assert meta.entity_id == a.id and meta.machine_id == machine.id
    assert meta.dedupe_key == node.canonical_key and meta.count == 2
    assert meta.status == "resolved" and meta.fix_ref == fix.id
    assert meta.first_seen.isoformat() == node.attrs["first_seen"]
    assert edge is not None and edge.dst_id == fix.id and edge.relation_type == "fixed_by"
    assert [e.id for e in await _out_edges(db, node.id, "fixed_by")] == [edge.id]

    with pytest.raises(APIError) as err:
        await resolve_finding(db, project_id, node.id, user_id, note="again", fix_ref=None)
    assert err.value.status_code == 409 and err.value.code == "conflict"
    with pytest.raises(APIError) as err:
        await dismiss_finding(db, project_id, node.id, user_id)
    assert err.value.status_code == 409 and err.value.code == "conflict"
    with pytest.raises(APIError) as err:
        await acknowledge_finding(db, project_id, node.id, user_id)
    assert err.value.status_code == 409 and err.value.code == "conflict"
    assert node.attrs["status"] == "resolved"

    await raise_finding(db, project_id, _finding_spec([a.id, b.id]))
    assert node.attrs["status"] == "open" and node.attrs["count"] == 3
    assert "resolved_by" not in node.attrs and "note" not in node.attrs


async def test_resolve_without_fix_ref_writes_no_edge_and_bad_fix_ref_is_404(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_id, _ = await _project_ids(client, alice_headers)
    project_b, _ = await _project_ids(client, bob_headers)
    user_id = uuid.UUID((await me(client, alice_headers))["id"])
    (a,) = await _seed_entities(db, project_id, 1)
    (foreign,) = await _seed_entities(db, project_b, 1)
    node = await raise_finding(
        db, project_id, _finding_spec([a.id], evidence={"machine_id": str(uuid.uuid4())})
    )
    with pytest.raises(APIError) as err:
        await resolve_finding(db, project_id, node.id, user_id, note="x", fix_ref=foreign.id)
    assert err.value.status_code == 404
    entry, edge = await resolve_finding(db, project_id, node.id, user_id, note="x", fix_ref=None)
    assert edge is None and entry.payload is not None
    meta = ErrorMeta.model_validate(entry.payload)
    assert meta.fix_ref is None and meta.machine_id is None  # not a live machine here
    assert await _out_edges(db, node.id, "fixed_by") == []

    node.attrs = {**node.attrs, "subjects": [str(a.id), str(foreign.id)]}
    await db.flush()
    assert [r.id for r in await subject_rows(db, node)] == [a.id]  # foreign id never resolves


async def test_resolve_system_finding_needs_no_person_and_files_nothing(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """SOLUSDEV-321 P3-T3 (R63): Solus resolves a finding itself when a matrix run finds the fact a
    standing info lacked. There is no person, no `.solus` errors entry and no activity:
    `resolved_by` is "system" and the reason is the note. A finding already resolved comes back
    unchanged, another project's is 404, and a later raise reopens it without the system's note."""
    project_id, _ = await _project_ids(client, alice_headers)
    other_id, _ = await _project_ids(client, bob_headers)
    (a,) = await _seed_entities(db, project_id, 1)
    info = _finding_spec([a.id], severity=Severity.INFO)
    node = await raise_finding(db, project_id, info)

    resolved = await resolve_system_finding(db, project_id, node.id, reason="the fact is stated")
    await db.commit()

    assert resolved is node and node.attrs["status"] == "resolved"
    assert (node.attrs["resolved_by"], node.attrs["note"]) == ("system", "the fact is stated")
    filed = select(SolusEntry.id).where(
        SolusEntry.project_id == project_id, SolusEntry.section == SolusSection.ERRORS
    )
    assert list(await db.scalars(filed)) == []
    resolutions = select(Activity.id).where(
        Activity.project_id == project_id, Activity.type == "finding.resolved"
    )
    assert list(await db.scalars(resolutions)) == []
    version = node.version
    again = await resolve_system_finding(db, project_id, node.id, reason="said again")
    assert again.version == version and again.attrs["note"] == "the fact is stated"
    with pytest.raises(APIError) as err:
        await resolve_system_finding(db, other_id, node.id, reason="not theirs")
    assert err.value.status_code == 404

    await raise_finding(db, project_id, info)
    assert node.attrs["status"] == "open" and node.attrs["count"] == 2
    assert "resolved_by" not in node.attrs and "note" not in node.attrs


async def test_acknowledge_sets_status_and_who(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project_ids(client, alice_headers)
    (a,) = await _seed_entities(db, project_id, 1)
    node = await raise_finding(db, project_id, _finding_spec([a.id]))
    user = uuid.uuid4()
    await acknowledge_finding(db, project_id, node.id, user)
    assert node.attrs["status"] == "acknowledged"
    assert node.attrs["acknowledged_by"] == str(user)
    with pytest.raises(APIError):
        await acknowledge_finding(db, uuid.uuid4(), node.id, user)


def test_finding_spec_rejects_oversized_evidence() -> None:
    _finding_spec([uuid.uuid4()], evidence={"blob": "x" * 15_000})
    with pytest.raises(ValidationError):
        _finding_spec([uuid.uuid4()], evidence={"blob": "x" * 17_000})


def test_finding_from_warning_maps_one_to_one() -> None:
    ids = (uuid.uuid4(), uuid.uuid4())
    warning = Warning(
        checker_id="voltage_mismatch",
        severity=Severity.CRITICAL,
        domains=("code", "electrical"),
        message="3.3 V pin driven at 5 V",
        evidence={"pin": "D4"},
        entity_ids=ids,
    )
    spec = finding_from_warning(warning)
    assert spec.rule_id == "voltage_mismatch" and spec.source == "checker"
    assert spec.severity is Severity.CRITICAL and spec.domain is Domain.CODE
    assert spec.headline == "3.3 V pin driven at 5 V"
    assert spec.subjects == list(ids) and spec.evidence == {"pin": "D4"}
    assert spec.bucket is None and spec.matrix_cell is None
    assert finding_from_warning(warning, source="sol").source == "sol"


async def test_list_filters_status_severity_subject_robot_and_pages(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project_ids(client, alice_headers)
    robot, body, part, loose = await _seed_entities(db, project_id, 4)
    for src, dst in ((robot.id, body.id), (body.id, part.id)):
        await write_edge(
            db,
            project_id=project_id,
            src_id=src,
            dst_id=dst,
            relation_type="contains",
            origin="system",
            confidence=1.0,
            evidence=[],
            created_by=None,
        )
    on_robot = await raise_finding(db, project_id, _finding_spec([robot.id], rule_id="r0"))
    on_part = await raise_finding(db, project_id, _finding_spec([part.id], rule_id="r1"))
    on_loose = await raise_finding(
        db, project_id, _finding_spec([loose.id], rule_id="r2", severity=Severity.CRITICAL)
    )
    dismissed = await raise_finding(db, project_id, _finding_spec([loose.id], rule_id="r3"))
    await dismiss_finding(db, project_id, dismissed.id, uuid.uuid4())

    rows, meta = await list_findings(db, project_id)
    assert [r.id for r in rows] == [on_loose.id, on_part.id, on_robot.id]  # newest first
    assert meta["has_next"] is False
    rows, _ = await list_findings(db, project_id, status="dismissed")
    assert [r.id for r in rows] == [dismissed.id]
    rows, _ = await list_findings(db, project_id, severity="critical")
    assert [r.id for r in rows] == [on_loose.id]
    rows, _ = await list_findings(db, project_id, severities=(Severity.CRITICAL, Severity.INFO))
    assert [r.id for r in rows] == [on_loose.id]  # any of them (SOL's routing read, P0-T7)
    rows, _ = await list_findings(db, project_id, subject=loose.id)
    assert [r.id for r in rows] == [on_loose.id]
    rows, _ = await list_findings(db, project_id, robot=robot.id)
    assert [r.id for r in rows] == [on_part.id, on_robot.id]  # the robot itself counts
    rows, _ = await list_findings(db, project_id, robot=loose.id)
    assert [r.id for r in rows] == [on_loose.id]  # a root with no children is still a subject

    page1, meta = await list_findings(db, project_id, limit=1)
    assert [r.id for r in page1] == [on_loose.id] and meta["has_next"] is True
    page2, meta = await list_findings(db, project_id, limit=1, cursor=meta["next_cursor"])
    assert [r.id for r in page2] == [on_part.id] and meta["has_next"] is True
    page3, meta = await list_findings(db, project_id, limit=1, cursor=meta["next_cursor"])
    assert [r.id for r in page3] == [on_robot.id] and meta["has_next"] is False


# -------------------------------------------------------------------- frames


async def test_live_frames_raised_then_updated_then_resolved(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, _ = await _project_ids(client, alice_headers)
    user_id = uuid.UUID((await me(client, alice_headers))["id"])
    (a,) = await _seed_entities(db, project_id, 1)
    await db.commit()
    hub = RecordingHub()
    maker = build_sessionmaker(engine, hub=hub)  # type: ignore[arg-type]

    async with maker() as s:
        node = await raise_finding(s, project_id, _finding_spec([a.id]))
        await commit_then_drain(s)
        await raise_finding(s, project_id, _finding_spec([a.id]))
        await commit_then_drain(s)
        await resolve_finding(s, project_id, node.id, user_id, note="n", fix_ref=None)
        await commit_then_drain(s)

    assert [t for _, t in hub.seen() if t.startswith("finding.")] == [
        "finding.raised",
        "finding.updated",
        "finding.resolved",
    ]
    raised = hub.find("project", "finding.raised")[0]
    assert raised["finding_id"] == str(node.id) and raised["status"] == "open"
    assert raised["project_id"] == str(project_id)
    assert hub.find("project", "finding.resolved")[0]["status"] == "resolved"


async def test_live_frames_ignore_other_entity_kinds_and_untouched_findings(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, _ = await _project_ids(client, alice_headers)
    (a,) = await _seed_entities(db, project_id, 1)
    node = await raise_finding(db, project_id, _finding_spec([a.id]))
    await db.commit()
    hub = RecordingHub()
    maker = build_sessionmaker(engine, hub=hub)  # type: ignore[arg-type]
    async with maker() as s:
        s.add(GraphEntity(project_id=project_id, kind="part", domain=Domain.MECHANICAL, name="x"))
        row = await s.get(GraphEntity, node.id)
        assert row is not None
        row.attrs = {**row.attrs, "detail": "SOL filled this in"}
        await commit_then_drain(s)
        assert [t for _, t in hub.seen() if t.startswith("finding.")] == []  # a part, a detail
        # SOLUSDEV-321 P2-T6 (Q4c): an explanation filling in IS a hint — once, not on a rewrite.
        row.attrs = {**row.attrs, "explanation": "SOL filled this in"}
        await commit_then_drain(s)
        row.attrs = {**row.attrs, "explanation": "SOL said it better"}
        await commit_then_drain(s)
    assert [t for _, t in hub.seen() if t.startswith("finding.")] == ["finding.updated"]


# -------------------------------------------------------------------- routes


async def _seeded_finding(
    client: AsyncClient, headers: dict[str, str], db: AsyncSession
) -> tuple[uuid.UUID, str, list[GraphEntity], GraphEntity]:
    project_id, team_id = await _project_ids(client, headers)
    subjects = await _seed_entities(db, project_id, 2)
    node = await raise_finding(db, project_id, _finding_spec([s.id for s in subjects]))
    await db.commit()
    return project_id, team_id, subjects, node


async def test_routes_list_and_get(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _, subjects, node = await _seeded_finding(client, alice_headers, db)
    url = f"/api/v1/projects/{project_id}/findings"
    resp = await client.get(url, headers=alice_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [f["id"] for f in body["data"]] == [str(node.id)]
    assert body["meta"] == {"limit": 100, "has_next": False, "next_cursor": None}
    item = body["data"][0]
    for key in (
        "id rule_id severity source status headline explanation detail subjects evidence "
        "count first_seen last_seen matrix_cell domain dismissed_until created_at updated_at"
    ).split():
        assert key in item, key
    assert item["subjects"] == [str(s.id) for s in subjects]
    assert item["status"] == "open" and item["domain"] == "electrical"

    assert (
        await client.get(url, params={"status": "nope"}, headers=alice_headers)
    ).status_code == 422
    resp = await client.get(url, params={"status": "resolved"}, headers=alice_headers)
    assert resp.json()["data"] == []

    resp = await client.get(f"{url}/{node.id}", headers=alice_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["subject_entities"] == [
        {"id": str(s.id), "kind": "component", "name": s.name} for s in subjects
    ]


async def test_routes_serve_causes_ranked_and_robot_id(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """SOLUSDEV-321 P2-T6: a finding serves its narration's ranked causes and the robot its
    evidence names; a row with neither (a checker's, one older than narration) or with a robot id
    that is no id serves `[]` and null."""
    project_id, _, subjects, node = await _seeded_finding(client, alice_headers, db)
    url = f"/api/v1/projects/{project_id}/findings/{node.id}"
    item = (await client.get(url, headers=alice_headers)).json()["data"]
    assert (item["causes_ranked"], item["robot_id"]) == ([], None)

    robot, ids = uuid.uuid4(), [s.id for s in subjects]
    await raise_finding(db, project_id, _finding_spec(ids, evidence={"robot_id": str(robot)}))
    await annotate_finding(
        db,
        project_id,
        node.id,
        explanation="Held past its rating.",
        detail="",
        causes_ranked=["actuator"],
        narration_tokens=3,
    )
    await db.commit()
    item = (await client.get(url, headers=alice_headers)).json()["data"]
    assert (item["causes_ranked"], item["robot_id"]) == (["actuator"], str(robot))

    await raise_finding(db, project_id, _finding_spec(ids, evidence={"robot_id": "not-an-id"}))
    await db.commit()
    assert (await client.get(url, headers=alice_headers)).json()["data"]["robot_id"] is None


async def test_routes_cross_project_and_non_member_are_404(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_a, _, _, _ = await _seeded_finding(client, alice_headers, db)
    _, _, _, node_b = await _seeded_finding(client, bob_headers, db)
    for path in (f"/findings/{node_b.id}", f"/findings/{uuid.uuid4()}"):
        resp = await client.get(f"/api/v1/projects/{project_a}{path}", headers=alice_headers)
        assert resp.status_code == 404, resp.text
    resp = await client.post(
        f"/api/v1/projects/{project_a}/findings/{node_b.id}/acknowledge", headers=alice_headers
    )
    assert resp.status_code == 404
    resp = await client.get(f"/api/v1/projects/{project_a}/findings", headers=bob_headers)
    assert resp.status_code == 404


async def test_routes_viewer_is_403_on_mutations(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_id, team_id, _, node = await _seeded_finding(client, alice_headers, db)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")
    base = f"/api/v1/projects/{project_id}/findings/{node.id}"
    assert (await client.get(base, headers=bob_headers)).status_code == 200
    for action, body in (("resolve", {"note": "n"}), ("dismiss", {}), ("acknowledge", None)):
        resp = await client.post(f"{base}/{action}", json=body, headers=bob_headers)
        assert resp.status_code == 403, (action, resp.text)
    row = await db.get(GraphEntity, node.id)
    assert row is not None and row.attrs["status"] == "open"


async def test_routes_resolve_dismiss_acknowledge(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _, subjects, node = await _seeded_finding(client, alice_headers, db)
    base = f"/api/v1/projects/{project_id}/findings/{node.id}"

    resp = await client.post(f"{base}/acknowledge", headers=alice_headers)
    assert resp.status_code == 200 and resp.json()["data"]["status"] == "acknowledged"

    resp = await client.post(f"{base}/dismiss", json={"cooldown_hours": 721}, headers=alice_headers)
    assert resp.status_code == 422
    resp = await client.post(f"{base}/dismiss", json={"cooldown_hours": 1}, headers=alice_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "dismissed"
    assert resp.json()["data"]["dismissed_until"] is not None

    resp = await client.post(f"{base}/resolve", json={"note": "x" * 4001}, headers=alice_headers)
    assert resp.status_code == 422
    resp = await client.post(
        f"{base}/resolve",
        json={"note": "fixed", "fix_ref": str(subjects[1].id)},
        headers=alice_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "resolved"
    assert uuid.UUID(data["entry_id"]) and uuid.UUID(data["fixed_by_edge_id"])
    resp = await client.post(f"{base}/resolve", json={"note": "again"}, headers=alice_headers)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "conflict"
