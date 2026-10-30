"""graph/inference/power_nets + the sync orchestrator (SOLUSDEV-320 Phase 3).

The fixture graph is `tests/fixtures/solus_sample.net` landed through the EDA connector IR
and `apply_sync_result`, exactly as a KiCad sync lands it.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from solus_api.connectors.contracts import (
    AccountInfo,
    AuthKind,
    Capability,
    Connector,
    Credentials,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.eda import build_graph
from solus_api.connectors.kicad_netlist import parse_kicad_netlist
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.runtime import apply_sync_result, run_sync
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.graph import kinds
from solus_api.graph.edges import write_edge
from solus_api.graph.inference import InferenceReport, infer_after_sync, power_nets, run_guarded
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

NETLIST = (Path(__file__).parent / "fixtures" / "solus_sample.net").read_text()
USER = uuid.uuid4()

#: Every unordered component pair sharing at least one net in the fixture, with the nets.
EXPECTED_WIRES: dict[frozenset[str], list[str]] = {
    frozenset({"C1", "C2"}): ["+3V3", "GND"],
    frozenset({"C1", "R1"}): ["+3V3"],
    frozenset({"C1", "R2"}): ["+3V3"],
    frozenset({"C1", "R3"}): ["+3V3"],
    frozenset({"C1", "U1"}): ["+3V3", "GND"],
    frozenset({"C1", "U2"}): ["+3V3", "GND"],
    frozenset({"C1", "C3"}): ["GND"],
    frozenset({"C1", "C4"}): ["GND"],
    frozenset({"C2", "R1"}): ["+3V3"],
    frozenset({"C2", "R2"}): ["+3V3"],
    frozenset({"C2", "R3"}): ["+3V3"],
    frozenset({"C2", "U1"}): ["+3V3", "GND"],
    frozenset({"C2", "U2"}): ["+3V3", "GND"],
    frozenset({"C2", "C3"}): ["GND"],
    frozenset({"C2", "C4"}): ["GND"],
    frozenset({"R1", "R2"}): ["+3V3"],
    frozenset({"R1", "R3"}): ["+3V3"],
    frozenset({"R1", "U1"}): ["+3V3", "/SDA"],
    frozenset({"R1", "U2"}): ["+3V3", "/SDA"],
    frozenset({"R2", "R3"}): ["+3V3"],
    frozenset({"R2", "U1"}): ["+3V3", "/SCL"],
    frozenset({"R2", "U2"}): ["+3V3", "/SCL"],
    frozenset({"R3", "U1"}): ["+3V3", "/NRST"],
    frozenset({"R3", "U2"}): ["+3V3"],
    frozenset({"U1", "U2"}): ["+3V3", "/IMU_INT", "/SCL", "/SDA", "GND"],
    frozenset({"C3", "C4"}): ["GND"],
    frozenset({"C3", "U1"}): ["GND"],
    frozenset({"C3", "U2"}): ["/CPOUT", "GND"],
    frozenset({"C4", "U1"}): ["GND"],
    frozenset({"C4", "U2"}): ["/REGOUT", "GND"],
}


async def seed_project(db: AsyncSession) -> uuid.UUID:
    team = Team(name="inference")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="inference")
    db.add(project)
    await db.flush()
    return project.id


async def seed_source(db: AsyncSession, project_id: uuid.UUID, kind: SourceType) -> Source:
    project = await db.get(Project, project_id)
    assert project is not None
    source = Source(
        project_id=project_id,
        team_id=project.team_id,
        type=kind,
        name=f"{kind.value} fixture",
        status=SourceStatus.CONNECTED,
        config={},
    )
    db.add(source)
    await db.flush()
    return source


async def land_netlist(db: AsyncSession, source: Source, text: str = NETLIST) -> None:
    entities, relations, errors = build_graph(parse_kicad_netlist(text))
    assert errors == []
    await apply_sync_result(db, source, SyncResult(entities=entities, relations=relations))


async def seed_component(
    db: AsyncSession, project_id: uuid.UUID, name: str, kind: str = kinds.COMPONENT, **attrs: Any
) -> GraphEntity:
    row = GraphEntity(
        project_id=project_id,
        kind=kind,
        domain=Domain.ELECTRICAL,
        origin="manual",
        name=name,
        attrs=attrs,
    )
    db.add(row)
    await db.flush()
    return row


async def link_components(
    db: AsyncSession, project_id: uuid.UUID, net: GraphEntity, *members: tuple[GraphEntity, str]
) -> None:
    for component, pin in members:
        await write_edge(
            db,
            project_id=project_id,
            src_id=component.id,
            dst_id=net.id,
            relation_type="connected_to",
            origin="manual",
            confidence=1.0,
            evidence=[],
            created_by=USER,
            attrs={"net": net.name, "pins": [pin]},
        )


async def edge_rows(db: AsyncSession, project_id: uuid.UUID, relation_type: str) -> list[GraphEdge]:
    return list(
        await db.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == project_id,
                GraphEdge.relation_type == relation_type,
                GraphEdge.deleted_at.is_(None),
            )
        )
    )


async def names_of(db: AsyncSession, edges: list[GraphEdge]) -> dict[uuid.UUID, str]:
    ids = {e.src_id for e in edges} | {e.dst_id for e in edges}
    if not ids:
        return {}
    rows = await db.scalars(select(GraphEntity).where(GraphEntity.id.in_(ids)))
    return {row.id: row.name for row in rows}


async def snapshot_edges(db: AsyncSession, project_id: uuid.UUID) -> list[tuple[Any, ...]]:
    db.expire_all()
    rows = await db.scalars(
        select(GraphEdge)
        .where(GraphEdge.project_id == project_id, GraphEdge.origin == "inferred")
        .order_by(GraphEdge.id)
    )
    return [(r.id, r.updated_at, r.confidence, r.attrs, r.deleted_at) for r in rows]


async def test_wires_cover_every_shared_net_exactly(db: AsyncSession) -> None:
    pid = await seed_project(db)
    source = await seed_source(db, pid, SourceType.KICAD)
    await land_netlist(db, source)

    report = await power_nets.infer(db, pid)

    wires = await edge_rows(db, pid, "wires")
    names = await names_of(db, wires)
    actual = {frozenset({names[e.src_id], names[e.dst_id]}): e.attrs["nets"] for e in wires}
    assert actual == EXPECTED_WIRES
    assert report == InferenceReport("power_nets", created=30, updated=0, skipped=0, candidates=0)
    for edge in wires:
        assert edge.origin == "inferred" and edge.confidence == 1.0
        assert edge.src_id < edge.dst_id  # canonical order: the same row on every rerun
        assert edge.attrs["matrix_cell"] == "electrical->electrical"
        assert [(ev["kind"], ev["ref"]) for ev in edge.attrs["evidence"]] == [
            ("netlist", net) for net in edge.attrs["nets"]
        ]
    u1_u2 = next(e for e in wires if {names[e.src_id], names[e.dst_id]} == {"U1", "U2"})
    by_name = {names[uuid.UUID(k)]: v for k, v in u1_u2.attrs["pins"].items()}
    assert by_name == {
        "U1": ["1", "15", "16", "17", "18", "5", "6"],
        "U2": ["1", "11", "12", "13", "18", "23", "24", "8", "9"],
    }
    # No component in the sample is a supply, so no `powers` edge — exactly none.
    assert await edge_rows(db, pid, "powers") == []


async def test_powers_supply_to_sink_on_power_nets_only(db: AsyncSession) -> None:
    pid = await seed_project(db)
    ldo = await seed_component(
        db, pid, "U3", value="AMS1117-3.3", libsource="Regulator_Linear:AMS1117"
    )
    battery = await seed_component(db, pid, "BT1", definition_id="lipo-4s")
    mcu = await seed_component(db, pid, "U4", value="ESP32")
    rail = await seed_component(db, pid, "+5V", kind=kinds.NET)
    vcc = await seed_component(db, pid, "VCC", kind=kinds.NET)
    gnd = await seed_component(db, pid, "GND", kind=kinds.NET)
    await link_components(db, pid, rail, (ldo, "2"), (battery, "1"), (mcu, "3"))
    await link_components(db, pid, vcc, (ldo, "3"), (mcu, "4"))
    await link_components(db, pid, gnd, (ldo, "1"), (battery, "2"), (mcu, "1"))

    report = await power_nets.infer(db, pid)

    powers = await edge_rows(db, pid, "powers")
    names = await names_of(db, powers)
    assert {(names[e.src_id], names[e.dst_id]): e.attrs["nets"] for e in powers} == {
        ("U3", "U4"): ["+5V", "VCC"],
        ("BT1", "U4"): ["+5V"],
    }
    assert all(e.confidence == 0.9 for e in powers)
    assert {ev["ref"] for e in powers for ev in e.attrs["evidence"]} == {"+5V", "VCC"}
    assert report.created == 2 + 3  # two powers + three wires (U3-BT1, U3-U4, BT1-U4)


async def test_rerun_is_a_no_op_and_manual_edges_survive(db: AsyncSession) -> None:
    pid = await seed_project(db)
    source = await seed_source(db, pid, SourceType.KICAD)
    await land_netlist(db, source)
    await power_nets.infer(db, pid)
    before = await snapshot_edges(db, pid)

    report = await power_nets.infer(db, pid)

    assert before == await snapshot_edges(db, pid)
    assert report == InferenceReport("power_nets", created=0, updated=0, skipped=30, candidates=0)

    names = {
        e.name: e
        for e in await db.scalars(select(GraphEntity).where(GraphEntity.project_id == pid))
    }
    manual = await write_edge(
        db,
        project_id=pid,
        src_id=names["C3"].id,
        dst_id=names["R1"].id,
        relation_type="wires",
        origin="manual",
        confidence=1.0,
        evidence=[],
        created_by=USER,
    )
    # The inputs change (C3 leaves /CPOUT); the manual edge is untouched by the rerun.
    cpout = next(
        e
        for e in await edge_rows(db, pid, "connected_to")
        if e.src_id == names["C3"].id and e.attrs["net"] == "/CPOUT"
    )
    cpout.deleted_at = cpout.created_at
    await db.flush()
    await power_nets.infer(db, pid)
    await db.refresh(manual)
    assert manual.deleted_at is None and manual.origin == "manual"


class NetlistConnector(Connector):
    provider = "kicad"
    auth_kind = AuthKind.NONE
    capabilities = frozenset({Capability.NETLIST, Capability.STRUCTURE})

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        return AccountInfo(external_id="k", login="kicad")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        entities, relations, _ = build_graph(parse_kicad_netlist(NETLIST))
        return SyncResult(entities=entities, relations=relations)

    async def detect_changes(self, ctx: SyncContext) -> bool:
        return True


def register_kicad() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register("kicad", NetlistConnector)
    return registry


async def test_infer_after_sync_dispatches_by_capability(db: AsyncSession) -> None:
    pid = await seed_project(db)
    source = await seed_source(db, pid, SourceType.KICAD)
    await land_netlist(db, source)

    reports = await infer_after_sync(db, pid, source_id=source.id, registry=register_kicad())

    assert [r.module for r in reports] == ["power_nets"]
    assert len(await edge_rows(db, pid, "wires")) == 30
    # A provider with no NETLIST/STRUCTURE/GEOMETRY capability runs nothing.
    bare = ConnectorRegistry()
    bare.register(
        "kicad", lambda: type("Bare", (NetlistConnector,), {"capabilities": frozenset()})()
    )
    assert await infer_after_sync(db, pid, source_id=source.id, registry=bare) == []


async def test_a_failing_module_is_logged_and_the_session_stays_usable(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = await seed_project(db)

    async def boom() -> InferenceReport:
        db.add(GraphEntity(project_id=pid, kind="x", domain=Domain.CODE, name="rolled back"))
        await db.flush()
        raise RuntimeError("inference exploded")

    assert await run_guarded(db, pid, "boom", boom) is None
    db.add(GraphEntity(project_id=pid, kind="y", domain=Domain.CODE, name="after"))
    await db.flush()
    names = set(await db.scalars(select(GraphEntity.name).where(GraphEntity.project_id == pid)))
    assert names == {"after"}


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_run_sync_infers_edges_in_the_commit(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        pid = await seed_project(db)
        source = await seed_source(db, pid, SourceType.KICAD)
        await db.commit()
        source_id = source.id

    sync_id = await run_sync(
        source_id=source_id,
        sessionmaker=maker,
        connector=NetlistConnector(),
        secret_store=InMemorySecretStore(),
        registry=register_kicad(),
    )

    assert sync_id is not None
    async with maker() as db:
        assert len(await edge_rows(db, pid, "wires")) == 30


async def test_a_wide_net_gets_powers_but_no_pairwise_wires(db: AsyncSession) -> None:
    pid = await seed_project(db)
    rail = await seed_component(db, pid, "+5V", kind=kinds.NET)
    ldo = await seed_component(db, pid, "U1", value="LDO regulator")
    sinks = [
        await seed_component(db, pid, f"R{i}") for i in range(power_nets.MAX_WIRED_NET_MEMBERS)
    ]
    await link_components(db, pid, rail, (ldo, "2"), *((sink, "1") for sink in sinks))

    report = await power_nets.infer(db, pid)

    assert await edge_rows(db, pid, "wires") == []
    assert len(await edge_rows(db, pid, "powers")) == len(sinks)
    assert report.created == len(sinks)


async def test_a_rail_with_too_many_supply_sink_pairs_is_skipped(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(power_nets, "MAX_POWERED_NET_PAIRS", 4)
    pid = await seed_project(db)
    rail = await seed_component(db, pid, "+5V", kind=kinds.NET)
    supplies = [await seed_component(db, pid, f"U{i}", value="LDO regulator") for i in range(2)]
    sinks = [await seed_component(db, pid, f"R{i}") for i in range(3)]
    await link_components(db, pid, rail, *((c, "1") for c in [*supplies, *sinks]))

    report = await power_nets.infer(db, pid)

    assert await edge_rows(db, pid, "powers") == []  # 2 × 3 = 6 pairs > 4: skipped, logged
    assert len(await edge_rows(db, pid, "wires")) == 10  # the net still wires its 5 members
    assert report.created == 10
