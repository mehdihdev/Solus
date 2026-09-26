"""Phase 6 proof (a) — three machines, one code path (docs/architecture/hardware-onboarding.md).

A recorded autopilot link (UDP), a recorded CAN base and a recorded bare-board float dump each
run the SAME onboarding sequence — interrogate → propose → HardwareConfig → LiveConnection →
packets — through `_p6_onboard`, which has no per-machine branch: everything that differs is a
row in `MACHINES`. A `sys.setprofile` module tracer records which modules ran; the set of
non-plugin `livebench.*` modules entered from the shared path must be identical across the
three, and only `livebench.plugins.*` may differ.

Attribution rule (ponytail: precise, not lenient): a shared module reached only THROUGH a plugin
frame — a plugin calling a shared helper such as `recognition.passive.characterize_stream` — is
the plugin's business and is reported, not compared. A branch in the shared loop itself is
always caught, because the loop's frames are non-plugin frames.
"""

from __future__ import annotations

import asyncio
import functools
import json
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any, Final

import pytest
from livebench.hardware.channel import TransportRegistry
from livebench.hardware.connection import open_robot_connection
from livebench.hardware.detection import DetectedDevice, Proposal, interrogate_device, propose
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry
from livebench.hardware.registries import Registries
from livebench.hardware.replay import Recording, ReplayChannel, load_recording
from livebench.hardware.repo_config import RepoConfigMatch, RepoPartDecl
from livebench.hardware.topology_extractors import firmware_topology, repo_config_topology
from livebench.plugins import load_all
from livebench.recognition.firmware import FirmwareFinding, extract_firmware_findings
from solus_api.agent.interfaces import TelemetryWindow
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import (
    ConfigLayer,
    FieldProvenance,
    HardwareConfig,
    LifecycleState,
    PartConfig,
    TelemetryChannel,
    TransportBinding,
    merge_layers,
    part_ref,
)
from solus_api.hardware.topology_evidence import TopologyExtraction
from solus_api.hardware.topology_observations import onboard_topology, schematic_topology

FIXTURES: Final = Path(__file__).with_name("fixtures")
BUDGET_S: Final = 0.3
WINDOW_S: Final = 0.2
MIN_PACKETS: Final = 3
COLLECT_TIMEOUT_S: Final = 5.0
PLUGIN_PREFIX: Final = "livebench.plugins."
#: Shared modules the sequence must visibly pass through — proves the tracer saw the path.
SHARED_SPINE: Final = frozenset(
    {
        "livebench.hardware.detection",
        "livebench.hardware.interrogator",
        "livebench.hardware.channel",
        "livebench.hardware.replay",
        "livebench.hardware.driver",
        "livebench.hardware.connection",
        "livebench.telemetry.stream_live",
    }
)

PartNames = Mapping[str, tuple[str, str | None]]  # bus address → (channel name, unit)


@dataclass(frozen=True)
class _P6Machine:
    fixture: str
    candidate_params: tuple[Mapping[str, Any], ...]
    part_names: PartNames
    driver_ids: frozenset[str]  # what the framing may honestly pick
    min_rows: int
    signals: Mapping[str, str]  # signal name → unit that must appear in the packets


MACHINES: Final[dict[str, _P6Machine]] = {
    "drone": _P6Machine(
        fixture="mavlink_px4_quadrotor.json",
        candidate_params=({},),
        part_names={"1:1": ("attitude.roll", None)},
        driver_ids=frozenset({"mavlink"}),
        min_rows=5,
        signals={"attitude.roll": "rad"},
    ),
    "base": _P6Machine(
        fixture="can_odrive_base.json",
        candidate_params=({},),
        part_names={"0x10": ("left_wheel.velocity", None), "0x11": ("right_wheel.velocity", None)},
        driver_ids=frozenset({"odrive-can"}),
        min_rows=2,
        signals={"left_wheel.velocity": "rev/s"},
    ),
    "rover": _P6Machine(
        fixture="serial_arduino_rover.json",
        candidate_params=({"baud": 115200},),
        part_names={
            "0": ("base.velocity", "m/s"),
            "1": ("base.angular_velocity", "rad/s"),
            "2": ("heading.angle", "rad"),
            "3": ("battery.voltage", "V"),
            "4": ("gyro.rate", "rad/s"),
            "5": ("gripper.position", "%"),
        },
        driver_ids=frozenset({"raw-lines", "lb06"}),
        min_rows=6,
        signals={"base.velocity": "m/s", "battery.voltage": "V"},
    ),
}


@dataclass(frozen=True)
class _P6RunResult:
    identity: TransportBinding
    proposal: Proposal
    config: HardwareConfig
    packets: list[TelemetryPacket]
    shared_path: frozenset[str]  # non-plugin livebench modules entered from non-plugin frames
    via_plugins: frozenset[str]  # non-plugin livebench modules entered only through a plugin
    plugins: frozenset[str]  # livebench.plugins.* modules that ran


class _P6ModuleTrace:
    """Records, per 'call' event, the callee's module and whether a plugin frame is above it."""

    def __init__(self) -> None:
        self.calls: set[tuple[str, bool]] = set()

    def __enter__(self) -> _P6ModuleTrace:
        self._previous = sys.getprofile()
        sys.setprofile(self._hook)
        return self

    def __exit__(self, *_exc: object) -> None:
        sys.setprofile(self._previous)

    def _hook(self, frame: FrameType, event: str, _arg: object) -> None:
        if event != "call":
            return
        name = frame.f_globals.get("__name__")
        if not isinstance(name, str) or not name.startswith("livebench."):
            return
        self.calls.add((name, _p6_under_plugin(frame.f_back)))


def _p6_under_plugin(frame: FrameType | None) -> bool:
    while frame is not None:
        if str(frame.f_globals.get("__name__", "")).startswith(PLUGIN_PREFIX):
            return True
        frame = frame.f_back
    return False


def _p6_registries(recording: Recording) -> Registries:
    """Process-level setup, outside the traced sequence: every plugin, with the recording
    standing in for the live transport of its own kind (registered first, so a plugin that
    wires that shared transport itself sees it present and leaves it alone)."""

    def open_recording(binding: TransportBinding, params: Mapping[str, Any]) -> ReplayChannel:
        channel = ReplayChannel(recording.identity.kind, binding, recording.frames)
        channel.params = dict(params)  # type: ignore[attr-defined]  # live channels expose this
        return channel

    registries = Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())
    registries.transports.register(recording.identity.kind, open_recording)
    load_all(registries)
    return registries


def _p6_config(robot_id: uuid.UUID, proposal: Proposal, part_names: PartNames) -> HardwareConfig:
    """The confirm step, generically: every proposal row becomes a part; the config — never the
    driver — names its telemetry channel."""
    assert proposal.identity is not None and proposal.driver_id is not None
    part_ids = {row.address: str(uuid.uuid4()) for row in proposal.rows}
    channels = {
        row.address: part_names.get(
            row.address, (row.proposed_function or f"addr_{row.address}", None)
        )
        for row in proposal.rows
    }
    document = {
        "identity": proposal.identity.model_dump(mode="json"),
        "protocol": {"driver_id": proposal.driver_id, "params": proposal.params},
        "bus_map": [
            {
                "protocol": proposal.driver_id,
                "address": row.address,
                "part_entity_id": part_ids[row.address],
                "model": row.model,
            }
            for row in proposal.rows
        ],
        "parts": {
            part_ids[row.address]: PartConfig(
                telemetry=[TelemetryChannel(name=name, unit=unit)], lifecycle=LifecycleState.LIVE
            ).model_dump(mode="json")
            for row in proposal.rows
            for name, unit in (channels[row.address],)
        },
    }
    return merge_layers(robot_id, [ConfigLayer(by=FieldProvenance.DETECTED, document=document)])


async def _p6_collect(connection: Any, count: int) -> list[TelemetryPacket]:
    packets: list[TelemetryPacket] = []
    enough = asyncio.Event()

    async def tap(packet: TelemetryPacket) -> None:
        packets.append(packet)
        if len(packets) >= count:
            enough.set()

    connection.tap = tap
    handle = await connection.subscribe(TelemetryWindow(duration_seconds=WINDOW_S))
    try:
        await asyncio.wait_for(enough.wait(), timeout=COLLECT_TIMEOUT_S)
    finally:
        await connection.unsubscribe(handle)
        await connection.aclose()
    return list(packets)


async def _p6_onboard(
    recording: Recording, candidate_params: Sequence[Mapping[str, Any]], part_names: PartNames
) -> _P6RunResult:
    """THE sequence. One body for every machine; the machine is data."""
    registries = _p6_registries(recording)
    robot_id, project_id = uuid.uuid4(), uuid.uuid4()
    identity = recording.identity
    with _P6ModuleTrace() as trace:
        interrogations = interrogate_device(
            identity,
            registries=registries,
            candidate_params=candidate_params,
            budget_s=BUDGET_S,
        )
        device = DetectedDevice(
            transport=identity.kind,
            device_ref=identity.device_ref,
            identity=identity,
            level="transport",
            board=None,
            board_class=None,
            mcu_known=False,
            confidence=0.0,
            evidence=[],
            ambiguous=False,
            last_seen_path=identity.last_seen_path,
        )
        proposal = propose(device, interrogations, repo_matches=[])
        config = _p6_config(robot_id, proposal, part_names)
        connection = open_robot_connection(
            config,
            project_id=project_id,
            transports=registries.transports,
            drivers=registries.drivers,
            reconnect=False,
        )
        packets = await _p6_collect(connection, MIN_PACKETS)
    shared = {name for name, _ in trace.calls if not name.startswith(PLUGIN_PREFIX)}
    direct = {name for name, via in trace.calls if not via and name in shared}
    return _P6RunResult(
        identity=identity,
        proposal=proposal,
        config=config,
        packets=packets,
        shared_path=frozenset(direct),
        via_plugins=frozenset(shared - direct),
        plugins=frozenset(name for name, _ in trace.calls if name.startswith(PLUGIN_PREFIX)),
    )


@functools.cache
def _p6_run(name: str) -> _P6RunResult:
    machine = MACHINES[name]
    recording = load_recording(FIXTURES / machine.fixture)
    return asyncio.run(_p6_onboard(recording, machine.candidate_params, machine.part_names))


@pytest.mark.parametrize("name", sorted(MACHINES))
def test_each_machine_onboards_through_the_one_generic_sequence(name: str) -> None:
    machine, run = MACHINES[name], _p6_run(name)
    assert run.proposal.level == "protocol"
    assert run.proposal.driver_id in machine.driver_ids, run.proposal.summary
    assert len(run.proposal.rows) >= machine.min_rows, [r.address for r in run.proposal.rows]
    # confirm wrote the proposal into config, provenance `detected`, and the driver read it
    assert run.config.protocol is not None
    assert run.config.protocol.driver_id == run.proposal.driver_id
    assert run.config.provenance_of("protocol.driver_id").by is FieldProvenance.DETECTED
    assert len(run.config.parts) == len(run.proposal.rows)
    assert len(run.packets) >= MIN_PACKETS
    # every signal goes out under its part's graph key `<device ref>/<address>` — the same
    # string confirm wrote to the part's external_ref, so the resolver keys telemetry to parts
    keys = {
        part_ref(run.identity.device_ref, entry.address)
        for entry in run.config.bus_map
        if entry.part_entity_id is not None
    }
    assert {p.device_id for p in run.packets} <= keys, sorted({p.device_id for p in run.packets})
    seen = {name: p.units.get(name) for p in run.packets for name in p.values}
    for signal, unit in machine.signals.items():
        assert signal in seen, f"{name}: {signal!r} not among {sorted(seen)}"
        assert seen[signal] == unit, f"{name}: {signal} unit {seen[signal]!r} != {unit!r}"
    address_of = {channel: address for address, (channel, _) in machine.part_names.items()}
    for packet in run.packets:
        for channel in packet.values:
            if channel in address_of:
                assert packet.device_id == part_ref(run.identity.device_ref, address_of[channel])


def test_the_shared_code_path_is_identical_across_the_three_machines() -> None:
    runs = {name: _p6_run(name) for name in sorted(MACHINES)}
    shared = {name: run.shared_path for name, run in runs.items()}
    plugins = {name: sorted(run.plugins) for name, run in runs.items()}
    reference = next(iter(shared.values()))
    assert SHARED_SPINE <= reference, sorted(SHARED_SPINE - reference)
    divergent = {
        name: {"extra": sorted(mods - reference), "missing": sorted(reference - mods)}
        for name, mods in shared.items()
        if mods != reference
    }
    assert not divergent, (
        f"the shared path branched per machine: {divergent}\n"
        f"plugin modules per machine: {plugins}\n"
        f"shared helpers reached only through plugins: "
        f"{ {n: sorted(r.via_plugins) for n, r in runs.items()} }"
    )
    # the proof has teeth: what DID differ is exactly the plugin layer
    assert len({frozenset(p) for p in plugins.values()}) == len(plugins), plugins
    assert all(run.plugins for run in runs.values()), plugins


# E4 is an EXTRACTION-only synthetic twin of the recordings above. It proves the common
# candidate boundary, not application to a graph, robot motion, calibration or live hardware.
def _extraction_twins() -> tuple[dict[str, Any], list[FirmwareFinding]]:
    root = FIXTURES / "topology_three_machines"
    raw = json.loads((root / "twins.json").read_text())
    assert raw["fixture_kind"].startswith("synthetic")
    assert set(raw["recording_references"]) == {machine.fixture for machine in MACHINES.values()}
    return raw, extract_firmware_findings(root)


def _candidate_consumer(batch: TopologyExtraction) -> TopologyExtraction:
    """The same immutable consumer for every source kind; validates only, never applies."""
    restored = TopologyExtraction.model_validate_json(batch.model_dump_json())
    assert restored == batch
    assert isinstance(restored.rows, tuple)
    return restored


def test_extraction_twins_share_one_candidate_consumer_without_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, findings = _extraction_twins()
    config = dict(raw["config"])
    config["parts"] = [RepoPartDecl(**part) for part in config["parts"]]
    match = RepoConfigMatch(**config)
    before = json.dumps(raw, sort_keys=True)

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("pure extraction attempted acquisition or a write")

    monkeypatch.setattr(Path, "read_text", refuse)
    monkeypatch.setattr(Path, "read_bytes", refuse)
    monkeypatch.setattr(Path, "write_text", refuse)
    monkeypatch.setattr(Path, "write_bytes", refuse)
    monkeypatch.setattr("builtins.open", refuse)
    monkeypatch.setattr("subprocess.run", refuse)
    monkeypatch.setattr("socket.socket", refuse)
    outputs = {
        name: onboard_topology(
            snapshot, source_namespace=f"fixture:{name}", source_ref="recording:twin"
        )
        for name, snapshot in raw["onboard"].items()
    }
    outputs["host_config"] = repo_config_topology(
        [match], source_namespace="fixture:serial", source_ref="fixture-config.json"
    )
    outputs["firmware"] = firmware_topology(
        findings, source_namespace="fixture:firmware", source_ref="intent.ino"
    )
    outputs["schematic"] = schematic_topology(
        raw["entities"],
        raw["relations"],
        project_id=uuid.UUID(raw["project_id"]),
        source_id=uuid.UUID(raw["source_id"]),
    )
    consumed = {name: _candidate_consumer(batch) for name, batch in outputs.items()}
    assert all(batch.status == "success" and batch.rows for batch in consumed.values())
    assert {batch.source_kind for batch in consumed.values()} == {
        "firmware",
        "host_config",
        "onboard",
        "schematic",
    }
    assert json.dumps(raw, sort_keys=True) == before
    shared_address = [
        row for batch in consumed.values() for row in batch.rows if row.address == "1"
    ]
    assert len(shared_address) == 2
    assert len({row.source_namespace for row in shared_address}) == 2
    schematic_pins = {p.pin_ref for row in consumed["schematic"].rows for p in row.provenance}
    assert schematic_pins == {"1", "2", "EP"}
    assert len(consumed["schematic"].rows) == 3  # component→net pins, not a clique
    firmware = consumed["firmware"]
    symbolic = next(row for row in firmware.rows if row.part_candidate == "left")
    assert symbolic.address is None
    assert any(p.pin_ref == "LEFT_PIN" for p in symbolic.provenance)
    dependencies = [
        row
        for row in firmware.rows
        if any("library_include" in (p.detail or "") for p in row.provenance)
    ]
    assert dependencies and all(
        row.device is None and row.part_candidate is None for row in dependencies
    )
    assert all(row.device is None for row in consumed["host_config"].rows)


def test_common_candidate_consumer_keeps_missing_and_invalid_sources_distinct() -> None:
    source = {"source_namespace": "fixture:source", "source_ref": "fixture:ref"}
    missing = [
        onboard_topology(None, **source),
        firmware_topology(None, **source),
        repo_config_topology(None, **source),
        schematic_topology(None, None, project_id=uuid.uuid4(), source_id=uuid.uuid4()),
    ]
    assert all(
        _candidate_consumer(batch).status == "unavailable" and not batch.rows for batch in missing
    )
    raw, _ = _extraction_twins()
    foreign = schematic_topology(
        raw["entities"],
        raw["relations"],
        project_id=uuid.uuid4(),
        source_id=uuid.UUID(raw["source_id"]),
    )
    assert _candidate_consumer(foreign).status == "invalid" and not foreign.rows


# L2–L5 proof twins: these geometry and fault inputs are authored SYNTHETIC data.
# They borrow only the recording's accepted identity shape. They are not downloaded
# CAD, measured faults, accepted live joint mappings, or evidence of robot motion.
@dataclass(frozen=True)
class _BenchTwin:
    xml: bytes
    format: str
    link_count: int
    moving_types: frozenset[str]
    position_unit: str
    current_unit: str
    current_scale: float


BENCH_TWINS: Final[dict[str, _BenchTwin]] = {
    "drone": _BenchTwin(
        b'<mujoco><compiler angle="radian"/><worldbody><body name="airframe">'
        b'<geom type="box" size="0.1 0.1 0.02"/></body></worldbody></mujoco>',
        "mjcf",
        1,
        frozenset(),
        "rad",
        "A",
        1,
    ),
    "base": _BenchTwin(
        b'<robot name="rolling"><link name="chassis"/><link name="left"/>'
        b'<link name="right"/><joint name="left_axis" type="continuous">'
        b'<parent link="chassis"/><child link="left"/></joint>'
        b'<joint name="right_axis" type="continuous"><parent link="chassis"/>'
        b'<child link="right"/></joint></robot>',
        "urdf",
        3,
        frozenset({"continuous"}),
        "deg",
        "mA",
        1000,
    ),
    "rover": _BenchTwin(
        b'<mujoco><compiler angle="radian"/><worldbody><body name="chassis">'
        b'<body name="mast"><joint name="extension" type="slide" range="0 0.2"/>'
        b'<body name="tool"><joint name="yaw" type="hinge" range="-1 1"/>'
        b"</body></body></body></worldbody></mujoco>",
        "mjcf",
        3,
        frozenset({"prismatic", "revolute"}),
        "m",
        "A",
        1,
    ),
}


def _bench_manifest(name: str, *, synthetic: bool) -> Any:
    """All twins enter the same scene, packet and run boundaries; no vendor branch."""
    from datetime import UTC, datetime, timedelta

    from solus_api.livebench.runs.models import PartEvidence, RevisionSnapshot, RunManifest
    from solus_api.livebench.scene.parser import parse_model

    run, twin = _p6_run(name), BENCH_TWINS[name]
    normalized = parse_model(twin.xml, twin.format)
    observed = run.packets[0]
    entry = next(
        row
        for row in run.config.bus_map
        if part_ref(run.identity.device_ref, row.address) == observed.device_id
    )
    assert entry.part_entity_id is not None
    started = (
        datetime(2026, 1, 1, tzinfo=UTC)
        if synthetic
        else min(packet.timestamp for packet in run.packets)
    )
    # Every synthetic twin has the same authored stimulus but different physical
    # units, topology and transport identity. Ratings are fixture data, not inferred.
    packets = (
        [
            TelemetryPacket(
                device_id=observed.device_id,
                timestamp=started + timedelta(milliseconds=250 * index),
                seq=index,
                values={
                    "current": (1 if index < 50 else 3) * twin.current_scale,
                    "position": 0,
                    "command": 0 if index < 50 else 1,
                },
                units={
                    "current": twin.current_unit,
                    "position": twin.position_unit,
                    "command": twin.position_unit,
                },
            )
            for index in range(55)
        ]
        if synthetic
        else list(run.packets)
    )
    part = PartEvidence(
        entity_id=entry.part_entity_id,
        name=f"Synthetic {name} axis" if synthetic else name,
        device_id=observed.device_id,
        current_signal="current" if synthetic else None,
        position_signal="position" if synthetic else None,
        command_signal="command" if synthetic else None,
        position_unit=twin.position_unit if synthetic else None,
        stall_current_a=2 if synthetic else None,
        cad_revision="synthetic-scene-v1" if synthetic else None,
    )
    return RunManifest(
        robot_id=run.config.robot_entity_id,
        started_at=started,
        packets=packets,
        parts=[part],
        snapshots=[
            RevisionSnapshot(
                entity_id=run.config.robot_entity_id,
                kind="fixture_provenance",
                name=f"{'Synthetic fault twin' if synthetic else 'Recorded telemetry'}: {name}",
                revision="synthetic" if synthetic else "recorded",
                data=json.dumps(
                    {
                        "recording": MACHINES[name].fixture,
                        "scene_origin": "synthetic",
                        "normalized_scene": normalized,
                    }
                ),
            )
        ],
    )


@pytest.mark.parametrize("name", sorted(BENCH_TWINS))
def test_recorded_machines_roundtrip_scene_and_runs_without_inventing_faults(name: str) -> None:
    import io
    from datetime import timedelta

    from livebench.telemetry.mcap_export import write_packets
    from livebench.telemetry.mcap_ingest import read_packets
    from solus_api.livebench.runs.analysis import compare, findings
    from solus_api.livebench.runs.models import encode_manifest, parse_manifest

    original = _bench_manifest(name, synthetic=False)
    restored = parse_manifest(encode_manifest(original))
    assert restored == original
    scene = json.loads(restored.snapshots[0].data)["normalized_scene"]
    twin = BENCH_TWINS[name]
    assert len(scene["links"]) == twin.link_count
    assert {
        joint["type"] for joint in scene["joints"] if joint["type"] != "fixed"
    } == twin.moving_types
    assert bool(scene["warnings"]) == (not twin.moving_types)
    # The existing playback/export boundary preserves identity, units and event time.
    stream = io.BytesIO()
    assert write_packets(stream, restored.packets) == len(restored.packets)
    stream.seek(0)
    replay = list(read_packets(stream))
    expected = sorted(restored.packets, key=lambda packet: packet.timestamp)
    assert [packet.model_dump() for packet in replay] == [
        packet.model_dump() for packet in expected
    ]
    report = findings(restored)
    assert report["findings"] == []
    assert report["insufficient"][0]["entity_id"] == str(restored.parts[0].entity_id)
    shifted = restored.model_copy(deep=True)
    shifted.started_at += timedelta(hours=7)
    shifted.packets = [
        packet.model_copy(update={"timestamp": packet.timestamp + timedelta(hours=7)})
        for packet in shifted.packets
    ]
    assert compare(restored, shifted)["divergences"] == []
    assert restored.packets == original.packets  # playback operations did not mutate the source


def test_synthetic_scene_run_observers_preserve_machine_and_unit_boundaries() -> None:
    from livebench.anomaly.session import SessionObservers
    from solus_api.livebench.runs.analysis import compare, findings
    from solus_api.livebench.runs.models import encode_manifest, parse_manifest

    manifests = {
        name: parse_manifest(encode_manifest(_bench_manifest(name, synthetic=True)))
        for name in BENCH_TWINS
    }
    assert len({manifest.robot_id for manifest in manifests.values()}) == 3
    assert len({manifest.parts[0].device_id for manifest in manifests.values()}) == 3
    observer, markers = SessionObservers(), []
    # One interleaved session-local observer; reused signal names cannot mix devices.
    for index in range(55):
        for manifest in manifests.values():
            markers.extend(observer.add(manifest.packets[index]))
    for name, manifest in manifests.items():
        device = manifest.parts[0].device_id
        current_markers = [
            marker
            for marker in markers
            if marker["device_id"] == device and marker["signal"] == "current"
        ]
        assert len(current_markers) == 1
        assert current_markers[0]["detail"]["baseline_mean"] == BENCH_TWINS[name].current_scale
        assert current_markers[0]["kind"] == "change_point"  # statistical marker, not fault claim
        card = findings(manifest)["findings"][0]
        assert card["entity_id"] == str(manifest.parts[0].entity_id)
        assert card["evidence"]["measured_current_min_a"] == pytest.approx(3)
        assert card["evidence"]["position_unit"] == BENCH_TWINS[name].position_unit
        assert card["cad_revision"] == "synthetic-scene-v1"
        wrong_unit = manifest.model_copy(deep=True)
        for packet in wrong_unit.packets:
            packet.units["current"] = "%"
        assert findings(wrong_unit)["findings"] == []  # percent is never current
        assert any(
            row["signal"] == "current" for row in compare(manifest, wrong_unit)["insufficient"]
        )
        changed = manifest.packets[50]
        assert SessionObservers().add(changed) == []  # reconnect never inherits another baseline
    first, second = list(manifests.values())[:2]
    with pytest.raises(ValueError, match="same robot"):
        compare(first, second)
