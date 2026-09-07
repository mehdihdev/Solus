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
from livebench.plugins import load_all
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
