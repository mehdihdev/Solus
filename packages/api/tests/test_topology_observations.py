"""Supplied runtime observations and source-scoped EDA snapshots remain unaccepted evidence."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from solus_api.hardware.topology_evidence import MAX_ROWS
from solus_api.hardware.topology_observations import onboard_topology, schematic_topology

PROJECT = uuid.UUID("00000000-0000-4000-8000-000000000001")
SOURCE = uuid.UUID("00000000-0000-4000-8000-000000000002")
CONTEXT = {"source_namespace": "project:runtime-source", "source_ref": "recording:1"}


def _entity(kind: str, name: str) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "project_id": PROJECT,
        "source_id": SOURCE,
        "type": kind,
        "source_key": name,
        "name": name,
        "domain": "electrical",
        "properties": {},
    }


def _edge(component: dict[str, Any], net: dict[str, Any], pins: list[str]) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "project_id": PROJECT,
        "source_id": SOURCE,
        "type": "connected_to",
        "from_entity_id": component["id"],
        "to_entity_id": net["id"],
        "properties": {"net": net["name"], "pins": pins},
    }


def _schematic(entities: list[dict[str, Any]], edges: list[dict[str, Any]]) -> Any:
    return schematic_topology(entities, edges, project_id=PROJECT, source_id=SOURCE)


def test_recorded_ros_usb_tty_mavlink_and_can_have_source_backed_unknowns() -> None:
    snapshot = json.loads(
        (Path(__file__).parent / "fixtures/topology_observations/onboard.json").read_text()
    )
    result = onboard_topology(snapshot, **CONTEXT)
    assert result.status == "success" and result.source_kind == "onboard"
    assert len(result.rows) == 6
    assert {row.protocol for row in result.rows} >= {"ros2", "usb", "mavlink", "can"}
    can = next(row for row in result.rows if row.protocol == "can")
    assert can.address == "0x06" and can.device is None and can.part_candidate is None
    bridge = next(row for row in result.rows if row.device == "CH340 USB serial bridge")
    assert bridge.part_candidate is None
    assert all(
        row.source_namespace == CONTEXT["source_namespace"] and row.provenance
        for row in result.rows
    )
    assert any("/dev/ttyUSB0" in (p.detail or "") for row in result.rows for p in row.provenance)
    assert all(row.confidence is None for row in result.rows)


def test_shared_power_net_retains_every_pin_without_component_clique() -> None:
    net = _entity("net", "GND")
    components = [_entity("component", f"U{i}") for i in range(20)]
    edges = [_edge(component, net, ["1", "2", "EP/0"]) for component in components]
    result = _schematic([net, *components], edges)
    assert result.status == "success" and len(result.rows) == 60
    assert {row.bus for row in result.rows} == {str(net["id"])}
    assert {p.pin_ref for row in result.rows for p in row.provenance} == {"1", "2", "EP/0"}
    assert all(row.protocol is None and row.address is None for row in result.rows)
    assert {p.entity_ref for row in result.rows for p in row.provenance} == {
        str(component["id"]) for component in components
    }
    assert all(str(SOURCE) in row.source_namespace for row in result.rows)


@pytest.mark.parametrize("target", ["entity", "edge"])
@pytest.mark.parametrize("scope", ["project_id", "source_id"])
def test_foreign_scope_anywhere_invalidates_entire_snapshot(target: str, scope: str) -> None:
    component, net = _entity("component", "U1"), _entity("net", "SDA")
    edge = _edge(component, net, ["A0"])
    (component if target == "entity" else edge)[scope] = uuid.uuid4()
    result = _schematic([component, net], [edge])
    assert result.status == "invalid" and result.rows == ()


@pytest.mark.parametrize(
    "problem",
    ["dangling", "wrong_direction", "empty_pins", "bad_pin", "mismatched_net", "duplicate_id"],
)
def test_malformed_schematic_is_invalid_without_partial_rows(problem: str) -> None:
    component, net = _entity("component", "U1"), _entity("net", "SDA")
    edge = _edge(component, net, ["1"])
    entities = [component, net]
    if problem == "dangling":
        edge["to_entity_id"] = uuid.uuid4()
    elif problem == "wrong_direction":
        edge["from_entity_id"], edge["to_entity_id"] = net["id"], component["id"]
    elif problem == "empty_pins":
        edge["properties"]["pins"] = []
    elif problem == "bad_pin":
        edge["properties"]["pins"] = [None]
    elif problem == "mismatched_net":
        edge["properties"]["net"] = "unrelated-net"
    else:
        entities.append({**component, "name": "contradiction"})
    result = _schematic(entities, [edge])
    assert result.status == "invalid" and result.rows == ()


def test_source_namespace_separates_identical_recorded_addresses() -> None:
    snapshot = {"vendor": [{"bus": "can0", "protocol": "can", "address": "6"}]}
    a = onboard_topology(snapshot, **CONTEXT)
    b = onboard_topology(snapshot, source_namespace="other-source", source_ref="recording:1")
    assert a.rows[0].address == b.rows[0].address and a.rows[0] != b.rows[0]


def test_unknown_and_empty_inputs_have_distinct_statuses() -> None:
    assert onboard_topology(None, **CONTEXT).status == "unavailable"
    assert onboard_topology({}, **CONTEXT).status == "success"
    assert (
        schematic_topology(None, None, project_id=PROJECT, source_id=SOURCE).status == "unavailable"
    )
    assert _schematic([], []).status == "success"
    assert onboard_topology({}, source_namespace="", source_ref="source").status == "invalid"


def test_input_and_output_budgets_apply_before_duplicate_reduction() -> None:
    assert (
        onboard_topology({"ros2_nodes": ["/same"] * (MAX_ROWS + 1)}, **CONTEXT).status == "invalid"
    )
    component, net = _entity("component", "U1"), _entity("net", "GND")
    assert (
        _schematic([component, net], [_edge(component, net, ["1"])] * (MAX_ROWS + 1)).status
        == "invalid"
    )
    assert (
        _schematic(
            [component, net], [_edge(component, net, [str(i) for i in range(MAX_ROWS + 1)])]
        ).status
        == "invalid"
    )
    assert onboard_topology({"ros2_topics": ["x" * 10000]}, **CONTEXT).status == "invalid"


def test_adapters_do_not_read_paths_or_run_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("unexpected acquisition")

    monkeypatch.setattr(Path, "read_text", refuse)
    monkeypatch.setattr(Path, "read_bytes", refuse)
    monkeypatch.setattr("subprocess.run", refuse)
    assert (
        onboard_topology({"tty": [{"path": "/arbitrary/no-authority"}]}, **CONTEXT).status
        == "success"
    )
    assert _schematic([], []).status == "success"


@pytest.mark.parametrize(
    "snapshot",
    [
        [],
        {"unknown": []},
        {"usb": [{"vid": "bad"}]},
        {"vendor": [{"protocol": float("nan")}]},
        {"ros2_nodes": iter(())},
    ],
)
def test_malformed_runtime_snapshots_are_invalid(snapshot: Any) -> None:
    assert onboard_topology(snapshot, **CONTEXT).status == "invalid"


def test_normalization_is_deterministic_without_guessing_same_topic_membership() -> None:
    snapshot = {"ros2_nodes": ["/node-b", "/node-a", "/node-a"], "ros2_topics": ["/topic"]}
    reordered = {"ros2_topics": ["/topic"], "ros2_nodes": ["/node-a", "/node-b"]}
    result = onboard_topology(snapshot, **CONTEXT)
    assert result == onboard_topology(reordered, **CONTEXT)
    assert len(result.rows) == 3
    assert all(row.device is None and row.part_candidate is None for row in result.rows)


def test_depth_object_and_total_text_budgets_refuse_before_output() -> None:
    deep: object = "leaf"
    for _ in range(12):
        deep = [deep]
    for snapshot in (
        {"ros2_nodes": deep},
        {"ros2_nodes": ["x" * 2000] * MAX_ROWS},
        {str(i): None for i in range(8192)},
        {"ros2_nodes": [None] * 8193},
    ):
        assert onboard_topology(snapshot, **CONTEXT).status == "invalid"


def test_schematic_scope_requires_uuid_authority_not_a_path_label() -> None:
    assert schematic_topology([], [], project_id="/some/repo", source_id=SOURCE).status == "invalid"


def test_names_and_tty_paths_do_not_invent_buses_or_usb_transport() -> None:
    result = onboard_topology({"ros2_nodes": ["/node"], "tty": [{"path": "/dev/tty0"}]}, **CONTEXT)
    assert all(row.bus is None for row in result.rows)
    tty = next(
        row for row in result.rows if any("/dev/tty0" in (p.detail or "") for p in row.provenance)
    )
    assert tty.protocol is None and tty.device is None
