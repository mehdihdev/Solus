"""KiCad acceptance criterion 9a (SOLUSDEV-312 audit): tenant isolation for every
endpoint that touches KiCad data (CLAUDE.md §7 — the highest-severity invariant).

Team A owns a project with a synced KiCad source, its graph entities and edges, a
sync record, a job and a netlist artifact. Team B (a different team) then drives
EVERY route that can read or mutate that data, twice:

* against A's project id (a stranger to the project), and
* against B's OWN project with A's object ids (cross-project id guessing).

Each attempt must be refused as not-found/forbidden — never an existence oracle, no
KiCad content in the body — and A's data must be byte-for-byte unchanged afterwards.
The per-route table below is the audit's evidence that no KiCad route lacks a
cross-team test.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from conftest import bearer
from fastapi import FastAPI
from fixtures.kicad_audit import (
    Maker,
    connect_kicad,
    entities_by_ref,
    new_project,
    sync,
)
from fixtures.kicad_sample import KICAD_PCB, KICAD_SEXPR
from httpx import AsyncClient
from solus_api.agent.interfaces import GraphScope
from solus_api.fingerprint.ingest import scan_project
from solus_api.graph.neighborhood import load_neighborhood
from solus_api.models import Domain, GraphEdge, GraphEntity, Job, Source
from solus_api.services.artifacts import create_artifact
from solus_api.widgets.bom.service import load_inputs
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

# Phrases that only exist inside team A's KiCad design.
A_MARKERS = ("LM358DR", "RC0603FR-0710KL", "SIGNAL", "Dual op-amp")


@dataclass(frozen=True)
class World:
    """Team A's KiCad world plus team B's empty project."""

    a_headers: dict[str, str]
    b_headers: dict[str, str]
    a_project: uuid.UUID
    b_project: uuid.UUID
    source_id: str
    sync_id: str
    job_id: str
    component_id: str
    net_id: str
    artifact_id: str


@pytest.fixture
def maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def world(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    maker: Maker,
    app: FastAPI,
) -> World:
    a_project = await new_project(client, alice_headers)
    source = await connect_kicad(
        client, alice_headers, a_project, export=KICAD_SEXPR, board=KICAD_PCB
    )
    trigger = await client.post(
        f"/api/v1/projects/{a_project}/sources/{source['id']}/sync", headers=alice_headers
    )
    assert trigger.status_code == 202
    job_id = trigger.headers["Location"].rsplit("/", 1)[1]
    record = await sync(client, alice_headers, a_project, source["id"])
    assert record["status"] == "succeeded"

    entities = await entities_by_ref(maker, a_project)
    async with maker() as session:
        user_id = await session.scalar(select(Source.created_by).where(Source.id == source["id"]))
        assert user_id is not None
        artifact = await create_artifact(
            session,
            app.state.artifact_store,
            project_id=a_project,
            created_by=user_id,
            data=KICAD_SEXPR.encode(),
            media_type="text/plain",
            source_tool="kicad.export_netlist",
            tool_call_id="isolation-1",
        )
        await session.commit()
        artifact_id = str(artifact.id)

    b_project = await new_project(client, bob_headers)
    return World(
        a_headers=alice_headers,
        b_headers=bob_headers,
        a_project=a_project,
        b_project=b_project,
        source_id=str(source["id"]),
        sync_id=str(record["id"]),
        job_id=job_id,
        component_id=str(entities["U1"].id),
        net_id=str(entities["net:VCC"].id),
        artifact_id=artifact_id,
    )


async def _a_state(maker: Maker, project_id: uuid.UUID) -> dict[str, Any]:
    """A fingerprint of everything team B must not be able to change."""
    async with maker() as session:
        entities = (
            await session.execute(
                select(
                    GraphEntity.id, GraphEntity.name, GraphEntity.version, GraphEntity.deleted_at
                )
                .where(GraphEntity.project_id == project_id)
                .order_by(GraphEntity.id)
            )
        ).all()
        edges = await session.scalar(
            select(func.count()).select_from(GraphEdge).where(GraphEdge.project_id == project_id)
        )
        source = (
            await session.execute(
                select(Source.name, Source.config, Source.status).where(
                    Source.project_id == project_id
                )
            )
        ).all()
        jobs = (
            await session.execute(select(Job.id, Job.status).where(Job.project_id == project_id))
        ).all()
    return {
        "entities": [tuple(row) for row in entities],
        "edges": edges,
        "source": [tuple(row) for row in source],
        "jobs": [tuple(row) for row in jobs],
    }


# Every route that touches KiCad data. `{p}` = project id, others filled from World.
# (method, path template, json body or None, needs member role)
ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    # sources
    ("GET", "/projects/{p}/sources", None),
    ("GET", "/projects/{p}/sources/{source}", None),
    ("PATCH", "/projects/{p}/sources/{source}", {"name": "pwned", "config": {"export": "x"}}),
    ("DELETE", "/projects/{p}/sources/{source}", None),
    ("POST", "/projects/{p}/sources/{source}/sync", None),
    ("GET", "/projects/{p}/sources/{source}/syncs", None),
    ("GET", "/projects/{p}/sources/{source}/syncs/{sync}", None),
    ("GET", "/projects/{p}/sources/{source}/selectable", None),
    ("POST", "/projects/{p}/sources/{source}/documents", {"id": "evil"}),
    ("DELETE", "/projects/{p}/sources/{source}/documents/evil", None),
    # graph entities / relations
    ("GET", "/projects/{p}/entities", None),
    ("GET", "/projects/{p}/entities/{entity}", None),
    ("GET", "/projects/{p}/entities/{entity}/relations", None),
    ("PATCH", "/projects/{p}/entities/{entity}", {"name": "pwned"}),
    ("DELETE", "/projects/{p}/entities/{entity}", None),
    ("GET", "/projects/{p}/graph?root={entity}&depth=2", None),
    ("GET", "/projects/{p}/relations", None),
    # jobs the sync produced
    ("GET", "/jobs/{job}", None),
    ("POST", "/jobs/{job}/cancel", None),
    ("GET", "/projects/{p}/jobs", None),
    # artifacts holding the exported netlist
    ("GET", "/projects/{p}/artifacts/{artifact}", None),
    ("GET", "/projects/{p}/artifacts/{artifact}/content", None),
]


def _url(template: str, project: uuid.UUID, w: World) -> str:
    path = template.format(
        p=project,
        source=w.source_id,
        sync=w.sync_id,
        entity=w.component_id,
        job=w.job_id,
        artifact=w.artifact_id,
    )
    return f"/api/v1{path}"


def _b(w: World) -> dict[str, str]:
    """Team B's headers plus an If-Match so entity mutations reach the scope check
    instead of failing header validation first."""
    return {**w.b_headers, "If-Match": "1"}


def _assert_leaks_nothing(resp: Any) -> None:
    body = resp.text
    for marker in A_MARKERS:
        assert marker not in body, f"{resp.request.method} {resp.request.url} leaked {marker!r}"


@pytest.mark.parametrize(("method", "template", "body"), ROUTES, ids=lambda v: str(v)[:60])
async def test_team_b_is_refused_on_team_as_project(
    method: str, template: str, body: dict[str, Any] | None, world: World, client: AsyncClient
) -> None:
    resp = await client.request(
        method, _url(template, world.a_project, world), json=body, headers=_b(world)
    )
    assert resp.status_code in {403, 404}, f"{method} {template}: {resp.status_code} {resp.text}"
    _assert_leaks_nothing(resp)


# Routes whose path carries an object id: team B's OWN project with A's ids.
OBJECT_ROUTES = [
    r for r in ROUTES if "{source}" in r[1] or "{entity}" in r[1] or "{artifact}" in r[1]
]


@pytest.mark.parametrize(("method", "template", "body"), OBJECT_ROUTES, ids=lambda v: str(v)[:60])
async def test_team_bs_own_project_cannot_reach_team_as_objects_by_id(
    method: str, template: str, body: dict[str, Any] | None, world: World, client: AsyncClient
) -> None:
    resp = await client.request(
        method, _url(template, world.b_project, world), json=body, headers=_b(world)
    )
    assert resp.status_code in {403, 404}, f"{method} {template}: {resp.status_code} {resp.text}"
    _assert_leaks_nothing(resp)


async def test_job_ids_are_not_readable_across_teams_even_with_own_membership(
    world: World, client: AsyncClient
) -> None:
    # `/jobs/{id}` has no project in its path: membership of the JOB's team is the gate.
    for method, suffix in (("GET", ""), ("POST", "/cancel")):
        resp = await client.request(
            method, f"/api/v1/jobs/{world.job_id}{suffix}", headers=world.b_headers
        )
        assert resp.status_code == 404


async def test_team_bs_list_routes_in_its_own_project_show_none_of_team_as_kicad_data(
    world: World, client: AsyncClient
) -> None:
    for path in ("sources", "entities", "relations", "jobs"):
        resp = await client.get(
            f"/api/v1/projects/{world.b_project}/{path}", headers=world.b_headers
        )
        assert resp.status_code == 200, resp.text
        # B's project only holds its own default workspace layer, never team A's KiCad data.
        rows = resp.json()["data"]
        assert not [r for r in rows if r.get("type") in {"component", "net", "kicad"}]
        _assert_leaks_nothing(resp)
    graph = await client.get(
        f"/api/v1/projects/{world.b_project}/graph",
        params={"root": world.component_id, "depth": 2},
        headers=world.b_headers,
    )
    assert graph.status_code in {200, 404}
    _assert_leaks_nothing(graph)


async def test_team_as_kicad_world_is_unchanged_after_every_attempt(
    world: World, client: AsyncClient, maker: Maker
) -> None:
    before = await _a_state(maker, world.a_project)
    for project in (world.a_project, world.b_project):
        for method, template, body in ROUTES:
            await client.request(
                method, _url(template, project, world), json=body, headers=_b(world)
            )
    assert await _a_state(maker, world.a_project) == before
    # ...and team A can still read all of it.
    listed = await client.get(
        f"/api/v1/projects/{world.a_project}/sources", headers=world.a_headers
    )
    assert [s["id"] for s in listed.json()["data"]] == [world.source_id]
    assert (
        await client.get(
            f"/api/v1/projects/{world.a_project}/artifacts/{world.artifact_id}/content",
            headers=world.a_headers,
        )
    ).status_code == 200


async def test_unauthenticated_callers_get_401_on_every_kicad_route(
    world: World, client: AsyncClient
) -> None:
    for method, template, body in ROUTES:
        resp = await client.request(method, _url(template, world.a_project, world), json=body)
        assert resp.status_code == 401, f"{method} {template}"


async def test_a_forged_token_for_an_unknown_user_sees_nothing(
    world: World, client: AsyncClient
) -> None:
    stranger = bearer("00000000-0000-0000-0000-00000000dead", "dead@example.com")
    resp = await client.get(f"/api/v1/projects/{world.a_project}/entities", headers=stranger)
    assert resp.status_code in {401, 403, 404}
    _assert_leaks_nothing(resp)


# --------------------------------------- the reasoning layer reads team-scoped data


async def test_graph_traversal_in_team_bs_project_cannot_reach_team_as_entities(
    world: World, maker: Maker
) -> None:
    async with maker() as session:
        hood = await load_neighborhood(
            session,
            world.b_project,
            roots=[uuid.UUID(world.component_id), uuid.UUID(world.net_id)],
            depth=2,
        )
    assert hood.entities == [] and hood.edges == []


async def test_sol_graph_context_for_team_bs_project_is_empty_even_with_as_anchors(
    world: World, maker: Maker
) -> None:
    from solus_api.agent.feeds import DbSolSystems
    from solus_api.graph.buffer import InMemoryTelemetryBuffer
    from solus_api.graph.resolver import DbEntityResolver
    from solus_api.graph.telemetry import TelemetryPlumbing

    systems = DbSolSystems(
        maker, TelemetryPlumbing(InMemoryTelemetryBuffer(), DbEntityResolver(maker))
    )
    scope = GraphScope(anchor_entity_ids=[uuid.UUID(world.component_id)], degree=2)
    foreign = await systems.get_graph_context(world.b_project, scope)
    assert foreign.entities == [] and foreign.edges == []
    own = await systems.get_graph_context(world.a_project, scope)
    assert {e.name for e in own.entities} >= {"U1"}  # the same call IS populated for team A


async def test_fingerprint_scan_and_bom_inputs_never_cross_the_project_boundary(
    world: World, maker: Maker
) -> None:
    async with maker() as session:
        summary = await scan_project(session, world.b_project)
        await session.commit()
        inputs = await load_inputs(session, world.b_project)
        canonicals = await session.scalar(
            select(func.count())
            .select_from(GraphEntity)
            .where(
                GraphEntity.project_id == world.b_project,
                GraphEntity.kind.in_(["component", "net"]),
            )
        )
    assert summary.observations == 0 and summary.canonical_created == 0
    assert inputs.observations == [] and inputs.canonicals == [] and inputs.items == []
    assert canonicals == 0
    async with maker() as session:
        mine = await load_inputs(session, world.a_project)
    assert mine.observations  # team A's own BOM inputs are populated


async def test_entities_in_as_project_stay_electrical_and_owned_by_as_source(
    world: World, maker: Maker
) -> None:
    async with maker() as session:
        rows = (
            await session.scalars(
                select(GraphEntity).where(
                    GraphEntity.project_id == world.a_project, GraphEntity.kind == "component"
                )
            )
        ).all()
    assert rows and all(
        r.domain is Domain.ELECTRICAL and str(r.source_id) == world.source_id for r in rows
    )
