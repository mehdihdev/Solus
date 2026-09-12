"""`make_diagram` (SOLUSDEV-252 S5): a pure graph → Diagram → SVG pipeline plus the
ungated tool that writes the SVG as a TTL artifact. A pin is `known` ONLY when the
graph or the robot config names it — the diagram never invents one."""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from solus_api.agent.diagram.build import WIRING_RELATIONS, build_wiring_diagram
from solus_api.agent.diagram.model import UNKNOWN_PIN, Diagram
from solus_api.agent.diagram.svg import MAX_SVG_BYTES, render_svg
from solus_api.agent.tools import ToolCall, ToolRegistry
from solus_api.agent.tools.make_diagram import MAKE_DIAGRAM_DESCRIPTOR, register_diagram_tools
from solus_api.graph.neighborhood import Neighborhood
from solus_api.hardware.config import (
    BusMapEntry,
    FieldProvenance,
    HardwareConfig,
    ProvenanceRecord,
)
from solus_api.hardware.store import ROBOT_KIND, ensure_config, put_config
from solus_api.models import (
    Artifact,
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    Team,
    TeamKind,
    User,
)
from solus_api.services.solus_graph import ORIGIN
from solus_api.storage import LocalArtifactStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

HOSTILE = '<script>alert("x")</script> & "quoted"'


def _diagram_entity(project_id: uuid.UUID, name: str, kind: str, **attrs: object) -> GraphEntity:
    return GraphEntity(
        id=uuid.uuid4(),
        project_id=project_id,
        kind=kind,
        domain=Domain.ELECTRICAL,
        name=name,
        attrs=dict(attrs),
    )


def _diagram_edge(a: GraphEntity, b: GraphEntity, relation: str, **attrs: object) -> GraphEdge:
    return GraphEdge(
        id=uuid.uuid4(),
        project_id=a.project_id,
        src_id=a.id,
        dst_id=b.id,
        relation_type=relation,
        domain_pair="electrical<->electrical",
        attrs=dict(attrs),
    )


def _synthetic() -> tuple[Neighborhood, HardwareConfig, list[GraphEntity]]:
    """Controller board + motor driver on one net (board pin known, driver pin not),
    plus a servo on a config bus line."""
    pid = uuid.uuid4()
    board = _diagram_entity(pid, "Controller board", "board")
    driver = _diagram_entity(pid, HOSTILE, "component")
    net = _diagram_entity(pid, "PWM_A", "net")
    robot = _diagram_entity(pid, "Arm", ROBOT_KIND)
    servo = _diagram_entity(pid, "Wrist servo", "part", robot_id=str(robot.id))
    # A container: no wiring edge, so it must not render.
    category = _diagram_entity(pid, "Actuators", "robot_category")
    edges = [
        _diagram_edge(board, net, "connected_to", net="PWM_A", pins=["D9"]),
        _diagram_edge(driver, net, "connected_to", net="PWM_A"),
        _diagram_edge(robot, category, "contains"),
        _diagram_edge(category, servo, "contains"),
    ]
    config = HardwareConfig(
        robot_entity_id=robot.id,
        bus_map=[BusMapEntry(protocol="serial-bus", address="1", part_entity_id=servo.id)],
        provenance={"bus_map": ProvenanceRecord(by=FieldProvenance.USER)},
    )
    hood = Neighborhood(
        entities=[board, driver, net, robot, servo, category], edges=edges, truncated=False
    )
    return hood, config, [board, driver, net, robot, servo]


def _wires_between(diagram: Diagram, a: str, b: str) -> list[tuple[str, str, str, str, bool]]:
    return [
        (w.from_node, w.from_pin, w.to_node, w.to_pin, w.known)
        for w in diagram.wires
        if {w.from_node, w.to_node} == {a, b}
    ]


# ------------------------------------------------------------------ build


def test_wiring_set_is_the_documented_one() -> None:
    assert {"connected_to", "drives", "reads_from", "powers", "bus"} <= set(WIRING_RELATIONS)
    assert "contains" not in WIRING_RELATIONS


def test_known_pin_comes_from_the_edge_and_unknown_pin_is_a_stub() -> None:
    hood, config, (board, driver, net, robot, servo) = _synthetic()
    diagram = build_wiring_diagram(hood, config, focus_ids=[board.id])

    [(_, from_pin, _, _, known)] = _wires_between(diagram, str(board.id), str(net.id))
    assert (from_pin, known) == ("D9", True)
    [(_, from_pin, _, _, known)] = _wires_between(diagram, str(driver.id), str(net.id))
    assert (from_pin, known) == (UNKNOWN_PIN, False)

    by_id = {n.id: n for n in diagram.nodes}
    assert [p.name for p in by_id[str(board.id)].pins if p.known] == ["D9"]
    assert [p.known for p in by_id[str(driver.id)].pins] == [False]
    assert any("Never invent a pin" in note for note in diagram.notes)
    assert str(hood.entities[5].id) not in by_id  # the container is not drawn


def test_bus_map_entries_become_bus_lines_to_the_named_parts() -> None:
    hood, config, (board, driver, net, robot, servo) = _synthetic()
    diagram = build_wiring_diagram(hood, config, focus_ids=[robot.id])
    bus = next(n for n in diagram.nodes if n.kind == "bus")
    assert bus.label == "serial-bus bus"
    [(_, from_pin, _, _, known)] = _wires_between(diagram, str(servo.id), bus.id)
    assert from_pin == UNKNOWN_PIN and known is False  # the address is not a pin
    labels = [w.label for w in diagram.wires if bus.id in (w.from_node, w.to_node)]
    assert any("addr 1" in label for label in labels)
    assert _wires_between(diagram, str(robot.id), bus.id)  # controller ↔ bus line


def test_firmware_pin_idioms_on_the_part_config_are_known_pins() -> None:
    hood, config, (board, driver, net, robot, servo) = _synthetic()
    document = config.model_dump(mode="json")
    document["parts"] = {str(servo.id): {"firmware": {"signal_pin": "D5", "baud": 1000000}}}
    document["provenance"]["parts"] = {"by": "repo", "source": None}
    diagram = build_wiring_diagram(hood, HardwareConfig.model_validate(document), [robot.id])
    servo_node = next(n for n in diagram.nodes if n.id == str(servo.id))
    assert [(p.name, p.known, p.net) for p in servo_node.pins if p.known] == [
        ("D5", True, "signal_pin")
    ]


def test_no_config_means_no_bus_and_focus_always_renders() -> None:
    hood, _, (board, *_rest) = _synthetic()
    lonely = _diagram_entity(board.project_id, "Unwired sensor", "component")
    hood = Neighborhood(entities=[*hood.entities, lonely], edges=hood.edges, truncated=False)
    diagram = build_wiring_diagram(hood, None, focus_ids=[lonely.id])
    assert all(n.kind != "bus" for n in diagram.nodes)
    assert str(lonely.id) in {n.id for n in diagram.nodes}


def test_build_is_deterministic() -> None:
    hood, config, (board, *_rest) = _synthetic()
    a = build_wiring_diagram(hood, config, focus_ids=[board.id])
    b = build_wiring_diagram(hood, config, focus_ids=[board.id])
    assert a == b


# -------------------------------------------------------------------- svg


def test_svg_is_wellformed_labelled_escaped_and_bounded() -> None:
    hood, config, (board, driver, net, robot, servo) = _synthetic()
    svg = render_svg(build_wiring_diagram(hood, config, focus_ids=[board.id]), title=HOSTILE)

    assert len(svg.encode()) <= MAX_SVG_BYTES
    root = ET.fromstring(svg)  # parses → well-formed XML
    assert root.tag.endswith("svg") and root.get("viewBox")
    assert "<script" not in svg and "foreignObject" not in svg
    assert "&lt;script&gt;" in svg  # hostile name is escaped text, not markup
    texts = [t.text or "" for t in root.iter() if t.tag.endswith("text")]
    assert "Controller board" in texts and "D9" in texts and "PWM_A" in texts
    assert HOSTILE in texts  # title AND the hostile node label survive as text
    assert any("Never invent a pin" in t for t in texts)
    assert 'class="wire unknown"' in svg and "stroke-dasharray" in svg
    assert any("Legend" in t for t in texts)


def test_svg_stays_under_the_cap_on_a_large_graph() -> None:
    pid = uuid.uuid4()
    hub = _diagram_entity(pid, "Hub", "board")
    parts = [_diagram_entity(pid, f"Part {i:03d}", "component") for i in range(400)]
    edges = [_diagram_edge(hub, p, "connected_to", pins=[f"P{i}"]) for i, p in enumerate(parts)]
    hood = Neighborhood(entities=[hub, *parts], edges=edges, truncated=True)
    diagram = build_wiring_diagram(hood, None, focus_ids=[hub.id])
    svg = render_svg(diagram, title="big")
    assert len(svg.encode()) <= MAX_SVG_BYTES
    assert any("truncated" in note for note in diagram.notes)


# ------------------------------------------------------------------- tool


def test_descriptor_is_ungated_and_bounded() -> None:
    assert MAKE_DIAGRAM_DESCRIPTOR.name == "make_diagram"
    assert MAKE_DIAGRAM_DESCRIPTOR.requires_confirmation is False
    props = MAKE_DIAGRAM_DESCRIPTOR.params["properties"]
    assert props["focus_entity_ids"]["maxItems"] == 8
    assert props["kind"]["enum"] == ["wiring", "plug_in"]
    assert props["title"]["maxLength"] == 120
    assert MAKE_DIAGRAM_DESCRIPTOR.params["additionalProperties"] is False


async def _seed_wiring(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, list[GraphEntity]]:
    user = User(supabase_user_id=uuid.uuid4().hex, email="d@x.io")
    team = Team(name="T", kind=TeamKind.COLLABORATIVE)
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name="Rover", created_by=user.id)
    db.add(project)
    await db.flush()
    pid = project.id
    board = _diagram_entity(pid, "Controller board", "board")
    driver = _diagram_entity(pid, HOSTILE, "component")
    net = _diagram_entity(pid, "PWM_A", "net")
    robot = GraphEntity(
        id=uuid.uuid4(),
        project_id=pid,
        kind=ROBOT_KIND,
        domain=Domain.PROJECT,
        name="Arm",
        origin=ORIGIN,
        attrs={},
    )
    servo = _diagram_entity(pid, "Wrist servo", "part", robot_id=str(robot.id))
    db.add_all([board, driver, net, robot, servo])
    await db.flush()
    db.add_all(
        [
            _diagram_edge(board, net, "connected_to", net="PWM_A", pins=["D9"]),
            _diagram_edge(driver, net, "connected_to", net="PWM_A"),
            _diagram_edge(robot, servo, "contains"),
        ]
    )
    await db.flush()
    await ensure_config(db, pid, robot, created_by=user.id)
    config = HardwareConfig(
        robot_entity_id=robot.id,
        bus_map=[BusMapEntry(protocol="serial-bus", address="1", part_entity_id=servo.id)],
        provenance={"bus_map": ProvenanceRecord(by=FieldProvenance.USER)},
    )
    await put_config(db, pid, robot, config, created_by=user.id)
    await db.commit()
    return pid, user.id, [board, driver, net, robot, servo]


def _registry(engine: AsyncEngine, tmp_path: Path, project_id: uuid.UUID, user_id: uuid.UUID):  # type: ignore[no-untyped-def]
    registry = ToolRegistry()
    register_diagram_tools(
        registry,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        store=LocalArtifactStore(str(tmp_path)),
        project_id=project_id,
        user_id=user_id,
    )
    return registry


async def test_tool_writes_an_svg_artifact_and_reports_unknown_pins(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path
) -> None:
    project_id, user_id, (board, driver, net, robot, servo) = await _seed_wiring(db)
    registry = _registry(engine, tmp_path, project_id, user_id)
    assert [d.name for d in registry.list()] == ["make_diagram"]

    result = await registry.invoke(
        ToolCall(
            call_id="c1",
            tool="make_diagram",
            args={"focus_entity_ids": [str(robot.id), str(board.id)], "title": "Arm wiring"},
        )
    )
    assert result.ok, result.error
    value = result.value or {}
    assert value["media_type"] == "image/svg+xml" and value["title"] == "Arm wiring"
    assert value["uri"].endswith(f"/artifacts/{value['artifact_id']}/content")
    assert any(HOSTILE in u for u in value["unknown_pins"])  # the driver's pin is unknown
    assert "D9" not in " ".join(value["unknown_pins"])
    assert "unknown" in value["summary"]

    row = await db.get(Artifact, uuid.UUID(value["artifact_id"]))
    assert row is not None and row.project_id == project_id and row.retained is False
    assert row.source_tool == "make_diagram" and row.created_by == user_id
    svg = (await LocalArtifactStore(str(tmp_path)).get(str(row.id))).decode()
    assert svg.lstrip().startswith("<svg") and "serial-bus bus" in svg and "D9" in svg
    assert "&lt;script&gt;" in svg and "<script" not in svg


async def test_tool_refuses_bad_ids_and_foreign_entities_without_raising(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path
) -> None:
    project_id, user_id, _ = await _seed_wiring(db)
    _other_project, _, (foreign_board, *_rest) = await _seed_wiring(db)
    registry = _registry(engine, tmp_path, project_id, user_id)
    bad = await registry.invoke(
        ToolCall(call_id="c2", tool="make_diagram", args={"focus_entity_ids": ["nope"]})
    )
    assert bad.ok is False and bad.error is not None and bad.error.code.value == "invalid_args"

    foreign = await registry.invoke(
        ToolCall(
            call_id="c3", tool="make_diagram", args={"focus_entity_ids": [str(foreign_board.id)]}
        )
    )
    assert foreign.ok is False and foreign.error is not None
    assert foreign.error.code.value == "not_found"
    assert (await db.scalar(select(Artifact).where(Artifact.project_id == project_id))) is None


async def test_diagram_resolves_v2_owner_and_independent_part_firmware(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path
) -> None:
    from solus_api.hardware.config import EntityHardwareConfig
    from solus_api.hardware.store import put_entity_config

    project, user, (_, _, _, robot, servo) = await _seed_wiring(db)
    await put_entity_config(
        db,
        project,
        servo,
        EntityHardwareConfig.model_validate(
            {
                "entity_id": str(servo.id),
                "component": {"firmware": {"signal_pin": "D5"}},
                "provenance": {"component": {"by": "user"}},
            }
        ),
        expected_version=0,
        created_by=user,
    )
    await db.commit()
    result = await _registry(engine, tmp_path, project, user).invoke(
        ToolCall(call_id="v2", tool="make_diagram", args={"focus_entity_ids": [str(robot.id)]})
    )
    assert result.ok, result.error
    assert result.value is not None
    svg = (await LocalArtifactStore(str(tmp_path)).get(result.value["artifact_id"])).decode()
    assert "serial-bus bus" in svg and "D5" in svg


async def test_diagram_builder_failure_is_portable_and_creates_no_artifact(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_api.agent.tools import make_diagram
    from solus_api.agent.tools.tool import ToolException

    project, user, (board, *_) = await _seed_wiring(db)

    def broken(*args: object, **kwargs: object) -> None:
        raise ValueError("fixture-private-builder-input")

    monkeypatch.setattr(make_diagram, "build_wiring_diagram", broken)
    tool = _registry(engine, tmp_path, project, user).tools()[0]
    with pytest.raises(ToolException) as failure:
        await tool.invoke({"focus_entity_ids": [str(board.id)]})
    assert "fixture-private" not in str(failure.value)
    assert await db.scalar(select(Artifact).where(Artifact.project_id == project)) is None


@pytest.mark.parametrize(
    "root_state",
    ["invalid_id", "missing", "foreign", "deleted", "connector", "wrong_kind", "no_config"],
)
async def test_unusable_robot_reference_keeps_diagram_graph_only_and_config_read_pure(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path, root_state: str
) -> None:
    from datetime import UTC, datetime

    from solus_api.agent.tools.make_diagram import _robot_config
    from solus_api.models import SolusEntry, Source, SourceType

    project, user, (board, _, _, robot, servo) = await _seed_wiring(db)
    if root_state == "foreign":
        _, _, (_, _, _, foreign_robot, _) = await _seed_wiring(db)
        servo.attrs = {"robot_id": str(foreign_robot.id)}
    elif root_state in {"invalid_id", "missing"}:
        servo.attrs = {"robot_id": "invalid" if root_state == "invalid_id" else str(uuid.uuid4())}
    elif root_state == "deleted":
        robot.deleted_at = datetime.now(UTC)
    elif root_state == "wrong_kind":
        robot.kind = "code_repo"
    elif root_state == "connector":
        owner = await db.get(Project, project)
        assert owner is not None
        source = Source(
            project_id=project, team_id=owner.team_id, type=SourceType.GITHUB, name="fixture"
        )
        db.add(source)
        await db.flush()
        robot.source_id = source.id
        robot.origin = "connector"
    else:
        empty_robot = GraphEntity(
            project_id=project,
            kind=ROBOT_KIND,
            domain=Domain.PROJECT,
            name="No config",
            origin=ORIGIN,
            attrs={},
        )
        db.add(empty_robot)
        await db.flush()
        servo.attrs = {"robot_id": str(empty_robot.id)}

    # Only the visible physical wiring is in this neighborhood; the robot is
    # referenced by the part's metadata, not admitted as a graph focus node.
    for edge in await db.scalars(
        select(GraphEdge).where(
            GraphEdge.project_id == project,
            GraphEdge.src_id == robot.id,
            GraphEdge.dst_id == servo.id,
        )
    ):
        edge.deleted_at = datetime.now(UTC)
    db.add(_diagram_edge(board, servo, "connected_to", pins=["D7"]))
    await db.commit()

    async def config_snapshot() -> list[tuple[object, ...]]:
        return [
            tuple(row)
            for row in await db.execute(
                select(
                    SolusEntry.id,
                    SolusEntry.project_id,
                    SolusEntry.entity_id,
                    SolusEntry.config_version,
                    SolusEntry.payload,
                    SolusEntry.deleted_at,
                ).order_by(SolusEntry.id)
            )
        ]

    before = await config_snapshot()
    assert await _robot_config(db, project, [servo]) is None
    result = await _registry(engine, tmp_path, project, user).invoke(
        ToolCall(call_id="guard", tool="make_diagram", args={"focus_entity_ids": [str(board.id)]})
    )
    assert result.ok, result.error
    assert result.value is not None
    svg = (await LocalArtifactStore(str(tmp_path)).get(result.value["artifact_id"])).decode()
    assert "D7" in svg
    assert "serial-bus bus" not in svg
    assert await config_snapshot() == before
