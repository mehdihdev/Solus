"""SOLUSDEV-320 T7 — `GET /projects/{id}/search` (docs/api/search.md)."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.models import (
    Domain,
    GraphEntity,
    Project,
    SolusEntry,
    SolusEntryKind,
    SolusSection,
    Source,
    SourceRevision,
    SourceStatus,
    SourceType,
    SourceViewSelection,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

CAN_BASE = Path(__file__).parent / "fixtures" / "hardware" / "can_base.json"


async def _search_project(client: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    await me(client, headers)
    team = await create_team(client, headers)
    return uuid.UUID((await create_project(client, headers, team["id"]))["id"])


def _ids(data: dict[str, Any]) -> set[str]:
    return {h["id"] for h in data["entities"]} | {h["id"] for h in data["solus"]}


def _seeded_ids(rows: dict[str, GraphEntity]) -> set[str]:
    return {str(e.id) for e in rows.values()}


def _ent(project_id: uuid.UUID, kind: str, domain: Domain, name: str, **kw: Any) -> GraphEntity:
    values: dict[str, Any] = {"origin": "manual", "attrs": {}}
    values.update(kw)
    return GraphEntity(project_id=project_id, kind=kind, domain=domain, name=name, **values)


async def _seed_search_rows(db: AsyncSession, project_id: uuid.UUID) -> dict[str, GraphEntity]:
    rows = {
        "servo": _ent(
            project_id,
            "part",
            Domain.ELECTRICAL,
            "sts-3215",
            external_ref="sch:M1",
            origin="connector",
            modality_hints={"part_number": "STS3215"},
        ),
        "mount": _ent(project_id, "part", Domain.MECHANICAL, "Motor Mount", external_ref="cad:7"),
        "code": _ent(
            project_id,
            "code_file",
            Domain.CODE,
            "main.py",
            external_ref="firmware/src/main.py",
            origin="connector",
            attrs={"path": "firmware/src/main.py"},
        ),
        "module": _ent(
            project_id,
            "code_module",
            Domain.CODE,
            "main",
            external_ref="firmware/src/main",
            origin="connector",
            attrs={"path": "firmware/src/main"},
        ),
        "robot": _ent(project_id, "physical_robot", Domain.RUNTIME, "base"),
        "widget": _ent(
            project_id, "solus:widget", Domain.WORKSPACE, "Motor Mount widget", origin="system"
        ),
    }
    db.add_all(rows.values())
    await db.flush()
    db.add(
        SolusEntry(
            project_id=project_id,
            section=SolusSection.ENVIRONMENT,
            subsection="hardware",
            kind=SolusEntryKind.CONFIG,
            text="Hardware config — base",
            payload=json.loads(CAN_BASE.read_text()),
            entity_id=rows["robot"].id,
            configured_entity_id=rows["robot"].id,
            config_version=1,
        )
    )
    db.add(
        SolusEntry(
            project_id=project_id,
            section=SolusSection.GOALS,
            kind=SolusEntryKind.TEXT,
            text="Mount the motor before Friday",
            entity_id=rows["robot"].id,
        )
    )
    await db.commit()
    return rows


async def _search(
    client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID, **params: Any
) -> tuple[int, dict[str, Any]]:
    resp = await client.get(f"/api/v1/projects/{project_id}/search", params=params, headers=headers)
    body = resp.json()
    return resp.status_code, body.get("data", body)


async def test_part_number_finds_the_hyphenated_name_by_trigram(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _search_project(client, alice_headers)
    rows = await _seed_search_rows(db, project_id)
    status, data = await _search(client, alice_headers, project_id, q="STS3215")
    assert status == 200, data
    hit = data["entities"][0]
    assert hit["id"] == str(rows["servo"].id)
    assert hit == {
        "id": str(rows["servo"].id),
        "kind": "part",
        "domain": "electrical",
        "name": "sts-3215",
        "snippet": "sts-3215",
        "score": hit["score"],
        "why": "name_match",
    }
    assert 0 < hit["score"] <= 1
    assert data["truncated"] is False

    status, data = await _search(client, alice_headers, project_id, q="sch:M1")
    assert data["entities"][0]["why"] == "ref_match"
    assert data["entities"][0]["snippet"] == "sch:M1" and data["entities"][0]["score"] == 1.0


async def test_usb_serial_finds_the_hardware_config_entry(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _search_project(client, alice_headers)
    rows = await _seed_search_rows(db, project_id)
    status, data = await _search(
        client, alice_headers, project_id, q="ODRV-3F2A-CAN0", scope="solus"
    )
    assert status == 200, data
    assert data["entities"] == []
    [hit] = data["solus"]
    assert hit["entity_id"] == str(rows["robot"].id)
    assert (hit["section"], hit["subsection"], hit["kind"]) == ("environment", "hardware", "config")
    assert hit["name"] == "Hardware config — base" and hit["why"] == "text_match"
    assert "ODRV-3F2A-CAN0" in hit["snippet"] and len(hit["snippet"]) <= 160

    status, data = await _search(client, alice_headers, project_id, q="motor", scope="all")
    assert [h["section"] for h in data["solus"]] == ["goals"]
    assert data["solus"][0]["why"] == "text_match"  # one word of a longer note
    assert "motor" in data["solus"][0]["snippet"]


async def test_code_snippets_are_their_paths(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _search_project(client, alice_headers)
    await _seed_search_rows(db, project_id)
    status, data = await _search(client, alice_headers, project_id, q="main", scope="entities")
    assert status == 200, data
    by_kind = {h["kind"]: h for h in data["entities"]}
    assert by_kind["code_file"]["snippet"] == "firmware/src/main.py"
    assert by_kind["code_module"]["snippet"] == "firmware/src/main"
    assert by_kind["code_module"]["why"] == "name_match"


async def test_filters_narrow_each_group(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _search_project(client, alice_headers)
    await _seed_search_rows(db, project_id)
    _, data = await _search(client, alice_headers, project_id, q="main", kinds="code_module")
    assert [h["kind"] for h in data["entities"]] == ["code_module"]
    _, data = await _search(client, alice_headers, project_id, q="motor", domains="mechanical")
    assert [h["name"] for h in data["entities"]] == ["Motor Mount"]
    _, data = await _search(client, alice_headers, project_id, q="motor", domains="code,runtime")
    assert data["entities"] == []
    _, data = await _search(client, alice_headers, project_id, q="motor", sections="environment")
    assert data["solus"] == []
    _, data = await _search(
        client,
        alice_headers,
        project_id,
        q="ODrive",
        sections="environment",
        subsections="hardware",
    )
    assert [h["subsection"] for h in data["solus"]] == ["hardware"]
    _, data = await _search(client, alice_headers, project_id, q="ODrive", subsections="nope")
    assert data["solus"] == []


async def test_a_renamed_entity_is_found_by_its_new_name_only(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _search_project(client, alice_headers)
    rows = await _seed_search_rows(db, project_id)
    rows["mount"].name = "Camera Bracket"
    await db.commit()
    _, data = await _search(client, alice_headers, project_id, q="bracket")
    assert [h["id"] for h in data["entities"]] == [str(rows["mount"].id)]
    _, data = await _search(client, alice_headers, project_id, q="Motor Mount", scope="entities")
    assert str(rows["mount"].id) not in {h["id"] for h in data["entities"]}


async def test_workspace_domain_is_never_searchable(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _search_project(client, alice_headers)
    rows = await _seed_search_rows(db, project_id)
    _, data = await _search(client, alice_headers, project_id, q="Motor Mount widget")
    ids = {h["id"] for h in data["entities"]}
    assert str(rows["widget"].id) not in ids and str(rows["mount"].id) in ids
    _, data = await _search(client, alice_headers, project_id, q="widget", domains="workspace")
    assert data["entities"] == []


async def test_results_never_cross_teams_or_projects(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """The predicate under test is the project scope inside each SQL statement: identical rows
    (same part name, same USB serial) in another team's project and in the same user's other
    project must never surface, for every scope."""
    alice_project = await _search_project(client, alice_headers)
    bob_project = await _search_project(client, bob_headers)
    alice_team = (await create_team(client, alice_headers, "Second"))["id"]
    alice_other = uuid.UUID((await create_project(client, alice_headers, alice_team))["id"])
    seeded = {
        pid: await _seed_search_rows(db, pid) for pid in (alice_project, bob_project, alice_other)
    }
    entry_ids = {
        pid: {
            str(i)
            for i in (await db.execute(select(SolusEntry.id).where(SolusEntry.project_id == pid)))
            .scalars()
            .all()
        }
        for pid in seeded
    }
    for headers, pid in ((alice_headers, alice_project), (bob_headers, bob_project)):
        own = _seeded_ids(seeded[pid]) | entry_ids[pid]
        for q, scope in (("STS3215", "all"), ("ODRV-3F2A-CAN0", "solus"), ("motor", "entities")):
            status, data = await _search(client, headers, pid, q=q, scope=scope, limit=50)
            assert status == 200, data
            found = _ids(data)
            assert found and found <= own, (pid, q, scope, found - own)
    _, data = await _search(client, alice_headers, alice_project, q="STS3215", limit=50)
    assert len(data["entities"]) == 1
    _, data = await _search(client, alice_headers, alice_project, q="ODRV-3F2A-CAN0", limit=50)
    assert len(data["solus"]) == 1


async def test_search_runs_under_the_graph_read_scope(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """With a snapshot revision active for Alice, the base source's entity is hidden and the
    snapshot's twin is what the index returns (search.md §2)."""
    project_id = await _search_project(client, alice_headers)
    alice_id = uuid.UUID((await me(client, alice_headers))["id"])
    project = await db.get(Project, project_id)
    assert project is not None
    base = Source(
        project_id=project_id,
        team_id=project.team_id,
        type=SourceType.GITHUB,
        name="repo",
        status=SourceStatus.CONNECTED,
        config={"repo": "acme/robot"},
    )
    db.add(base)
    await db.flush()
    snapshot = Source(
        project_id=project_id,
        team_id=project.team_id,
        type=SourceType.GITHUB,
        name="hidden",
        status=SourceStatus.CONNECTED,
        revision_base_source_id=base.id,
    )
    db.add(snapshot)
    await db.flush()
    revision = SourceRevision(
        project_id=project_id,
        base_source_id=base.id,
        materialized_source_id=snapshot.id,
        commit_id="a" * 40,
        branch="feature",
    )
    db.add(revision)
    await db.flush()
    on_base = _ent(
        project_id,
        "code_file",
        Domain.CODE,
        "motor_driver.py",
        source_id=base.id,
        origin="connector",
        attrs={"path": "src/motor_driver.py"},
    )
    on_snapshot = _ent(
        project_id,
        "code_file",
        Domain.CODE,
        "motor_driver.py",
        source_id=snapshot.id,
        origin="connector",
        attrs={"path": "src/motor_driver.py"},
    )
    db.add_all([on_base, on_snapshot])
    await db.commit()
    _, data = await _search(client, alice_headers, project_id, q="motor_driver", scope="entities")
    assert [h["id"] for h in data["entities"]] == [str(on_base.id)]
    db.add(
        SourceViewSelection(
            project_id=project_id,
            user_id=alice_id,
            base_source_id=base.id,
            active_revision_id=revision.id,
            active_branch="feature",
            status="ready",
            request_generation=uuid.uuid4(),
        )
    )
    await db.commit()
    _, data = await _search(client, alice_headers, project_id, q="motor_driver", scope="entities")
    assert [h["id"] for h in data["entities"]] == [str(on_snapshot.id)]


async def test_non_member_404_and_validation_422(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_id = await _search_project(client, alice_headers)
    await _seed_search_rows(db, project_id)
    await me(client, bob_headers)
    status, body = await _search(client, bob_headers, project_id, q="sts")
    assert status == 404 and body["error"]["code"] == "not_found"
    for params in (
        {"q": ""},
        {"q": "x" * 256},
        {"q": "sts", "limit": 0},
        {"q": "sts", "limit": 51},
        {"q": "sts", "scope": "everything"},
        {"q": "sts", "sections": "hardware"},
        {"q": "sts", "domains": "plasma"},
        {},
    ):
        status, body = await _search(client, alice_headers, project_id, **params)
        assert status == 422, (params, body)
        assert body["error"]["code"] == "validation_error"


async def test_search_over_three_thousand_rows_is_fast(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id = await _search_project(client, alice_headers)
    rows = await _seed_search_rows(db, project_id)
    db.add_all(
        _ent(
            project_id,
            "component",
            Domain.ELECTRICAL,
            f"R{i}",
            external_ref=f"sch:R{i}",
            origin="connector",
            attrs={"manufacturer": "Yageo", "mpn": f"RC0603FR-07{i}KL"},
        )
        for i in range(3000)
    )
    await db.commit()
    await _search(client, alice_headers, project_id, q="warm")  # connection + plan warm-up
    started = time.perf_counter()
    status, data = await _search(client, alice_headers, project_id, q="STS3215", limit=50)
    elapsed = time.perf_counter() - started
    print(f"search over 3006 entities: {elapsed * 1000:.1f} ms")
    assert status == 200 and data["entities"][0]["id"] == str(rows["servo"].id)
    assert elapsed < 0.5
    status, data = await _search(client, alice_headers, project_id, q="Yageo", limit=10)
    assert len(data["entities"]) == 10 and data["truncated"] is True
