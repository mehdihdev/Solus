"""SOLUSDEV-72: the local source catalog — honest availability probes, serial-keyed
device identity (by-id paths), and lazy provider factories."""

import asyncio
import builtins
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from livebench.hardware.channel import Frame
from livebench.hardware.replay import QUIET_READ_SECONDS, ReplayChannel
from livebench.local import (
    AmbiguousDeviceError,
    DeviceNotFoundError,
    available_simulators,
    list_devices,
    open_mujoco,
    open_replay,
    resolve_serial_device,
)
from livebench.recognition.passive import identify_port
from livebench.telemetry.stream_live import PacketStreamLiveConnection
from solus_api.agent.interfaces import TelemetryWindow
from solus_api.graph.codec import encode_json
from solus_api.graph.packet import TelemetryPacket
from solus_api.hardware.config import (
    BusMapEntry,
    FieldProvenance,
    HardwareConfig,
    PartConfig,
    ProtocolBinding,
    ProvenanceRecord,
    TelemetryChannel,
    TransportBinding,
    TransportKind,
)

CH343 = identify_port(device="/dev/ttyACM0", vid=0x1A86, pid=0x55D3, serial="5B42135040")
CH343_TWIN = identify_port(device="/dev/ttyACM1", vid=0x1A86, pid=0x55D3, serial="5B42135040")
TEENSY = identify_port(device="/dev/ttyACM2", vid=0x16C0, pid=0x0483, serial="TN99")
NO_SERIAL = identify_port(device="/dev/ttyUSB0", vid=0x1A86, pid=0x7523, serial=None)


# ── availability ────────────────────────────────────────────────────────────────


def test_available_simulators_reports_honestly() -> None:
    sims = {
        s.kind: s
        for s in available_simulators(
            find_spec=lambda name: object() if name == "mujoco" else None,
            which=lambda name: None,
            isaac_root=Path("/nonexistent"),
        )
    }
    assert sims["mujoco"].available and sims["mujoco"].reason is None
    assert not sims["gazebo"].available and "not" in (sims["gazebo"].reason or "")
    assert not sims["isaac"].available
    assert "not installed" in (sims["isaac"].reason or "")


def test_gazebo_available_when_gz_on_path(tmp_path: Path) -> None:
    sims = {
        s.kind: s
        for s in available_simulators(
            find_spec=lambda name: None,
            which=lambda name: "/usr/bin/gz" if name == "gz" else None,
            isaac_root=tmp_path,  # exists
        )
    }
    assert not sims["mujoco"].available
    assert sims["gazebo"].available
    # Isaac present is still NOT a startable session provider — honest, not fake.
    assert not sims["isaac"].available
    assert "direct script" in (sims["isaac"].reason or "") or "MCAP" in (sims["isaac"].reason or "")


def test_listing_never_imports_heavy_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    imported: list[str] = []
    real_import = builtins.__import__

    def spying_import(name: str, *args: Any, **kwargs: Any) -> Any:
        imported.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", spying_import)
    available_simulators()
    list_devices(identities=[CH343])
    assert "mujoco" not in imported
    assert not any(name.startswith("livebench.sim") for name in imported)


# ── devices ─────────────────────────────────────────────────────────────────────


def _by_id_dir(tmp_path: Path, links: dict[str, str]) -> Path:
    root = tmp_path / "by-id"
    root.mkdir()
    for name, target in links.items():
        (root / name).symlink_to(target)
    return root


def test_list_devices_maps_by_id_and_flags_nothing_for_unique_serials(tmp_path: Path) -> None:
    by_id = _by_id_dir(tmp_path, {"usb-1a86_USB_Single_Serial_5B42135040-if00": "/dev/ttyACM0"})
    devices = list_devices(identities=[CH343, TEENSY], by_id_dir=by_id)
    by_path = {d.identity.device: d for d in devices}
    assert by_path["/dev/ttyACM0"].by_id_path == str(
        by_id / "usb-1a86_USB_Single_Serial_5B42135040-if00"
    )
    assert by_path["/dev/ttyACM2"].by_id_path is None
    assert not by_path["/dev/ttyACM0"].ambiguous
    assert not by_path["/dev/ttyACM2"].ambiguous


def test_identical_serials_are_flagged_ambiguous(tmp_path: Path) -> None:
    devices = list_devices(identities=[CH343, CH343_TWIN], by_id_dir=tmp_path / "missing")
    assert all(d.ambiguous for d in devices)


def test_absent_serial_is_flagged_ambiguous() -> None:
    devices = list_devices(identities=[NO_SERIAL, TEENSY])
    flags = {d.identity.device: d.ambiguous for d in devices}
    assert flags["/dev/ttyUSB0"] is True
    assert flags["/dev/ttyACM2"] is False


# ── serial resolution (the safety property) ─────────────────────────────────────


def test_resolve_unique_serial_prefers_the_by_id_path(tmp_path: Path) -> None:
    by_id = _by_id_dir(tmp_path, {"usb-1a86_USB_Single_Serial_5B42135040-if00": "/dev/ttyACM0"})
    path = resolve_serial_device("5B42135040", identities=[CH343, TEENSY], by_id_dir=by_id)
    assert path == str(by_id / "usb-1a86_USB_Single_Serial_5B42135040-if00")


def test_resolve_without_by_id_falls_back_to_the_device_path(tmp_path: Path) -> None:
    path = resolve_serial_device(
        "5B42135040", identities=[CH343, TEENSY], by_id_dir=tmp_path / "missing"
    )
    assert path == "/dev/ttyACM0"


def test_resolve_unknown_serial_raises() -> None:
    with pytest.raises(DeviceNotFoundError):
        resolve_serial_device("NOPE", identities=[CH343])


def test_resolve_duplicate_serials_refuses_with_candidates() -> None:
    with pytest.raises(AmbiguousDeviceError) as excinfo:
        resolve_serial_device("5B42135040", identities=[CH343, CH343_TWIN])
    candidates = {d.identity.device for d in excinfo.value.candidates}
    assert candidates == {"/dev/ttyACM0", "/dev/ttyACM1"}


def test_resolve_confirmed_path_must_match_a_live_port() -> None:
    # A serial-less device is only reachable through an explicit, still-enumerated pick.
    path = resolve_serial_device(None, identities=[NO_SERIAL], confirmed_device_path="/dev/ttyUSB0")
    assert path == "/dev/ttyUSB0"
    with pytest.raises(DeviceNotFoundError):
        resolve_serial_device(None, identities=[NO_SERIAL], confirmed_device_path="/dev/ttyGONE")
    with pytest.raises(DeviceNotFoundError):
        resolve_serial_device(None, identities=[NO_SERIAL])  # no pick → refuse, never guess


def test_resolve_replug_survives_port_swap() -> None:
    # The same physical arm re-enumerates at a different tty; serial still finds it.
    swapped = replace(CH343, device="/dev/ttyACM7")
    assert resolve_serial_device("5B42135040", identities=[TEENSY, swapped]) == "/dev/ttyACM7"


# ── factories ───────────────────────────────────────────────────────────────────


async def test_open_mujoco_builds_a_project_bound_realtime_connection() -> None:
    pytest.importorskip("mujoco")
    project = uuid4()
    conn = await open_mujoco(project_id=project, duration_seconds=0.2, sample_hz=50.0)
    try:
        assert conn.provider == "mujoco"
        assert conn.project_id == project
    finally:
        await conn.aclose()


# ── Phase-4 review fixes: MJCF must never reach the filesystem ──────────────────


async def test_open_mujoco_rejects_file_referencing_mjcf() -> None:
    pytest.importorskip("mujoco")
    hostile = [
        '<mujoco><include file="/etc/passwd"/></mujoco>',
        '<mujoco><asset><mesh file="/etc/shadow"/></asset></mujoco>',
        '<mujoco><asset><texture FILE = "x.png"/></asset></mujoco>',
        '<mujoco><compiler meshdir="/"/></mujoco>',
    ]
    for xml in hostile:
        with pytest.raises(ValueError) as excinfo:
            await open_mujoco(project_id=uuid4(), duration_seconds=1.0, xml=xml)
        assert "/etc" not in str(excinfo.value)  # never echo a probed path


async def test_open_mujoco_compile_errors_are_sanitized() -> None:
    pytest.importorskip("mujoco")
    with pytest.raises(ValueError) as excinfo:
        await open_mujoco(
            project_id=uuid4(), duration_seconds=1.0, xml="<mujoco><badelement/></mujoco>"
        )
    # Fixed message: the compiler's own text (which can leak host details for
    # probing inputs) is logged, never returned.
    assert str(excinfo.value) == "invalid MuJoCo model XML (compile failed)"


# ── port-position binding (SOLUSDEV-250 Phase 2: serial-less devices) ───────────

NO_SERIAL_AT_PORT = identify_port(
    device="/dev/ttyUSB3", vid=0x1A86, pid=0x7523, serial=None, location="3-1.2"
)


def test_a_serial_less_device_with_a_location_is_not_ambiguous() -> None:
    devices = list_devices(identities=[NO_SERIAL_AT_PORT, NO_SERIAL])
    flags = {d.identity.device: d.ambiguous for d in devices}
    assert flags["/dev/ttyUSB3"] is False and flags["/dev/ttyUSB0"] is True


def test_two_serial_less_devices_on_one_location_are_ambiguous() -> None:
    twin = replace(NO_SERIAL_AT_PORT, device="/dev/ttyUSB4")
    assert all(d.ambiguous for d in list_devices(identities=[NO_SERIAL_AT_PORT, twin]))


def test_resolve_by_port_binding_returns_the_device_path() -> None:
    assert resolve_serial_device("port-3-1.2", identities=[NO_SERIAL_AT_PORT, TEENSY]) == (
        "/dev/ttyUSB3"
    )


def test_resolve_by_port_binding_fails_closed_when_moved_or_duplicated() -> None:
    with pytest.raises(DeviceNotFoundError):
        resolve_serial_device("port-3-1.2", identities=[NO_SERIAL, TEENSY])
    twin = replace(NO_SERIAL_AT_PORT, device="/dev/ttyUSB4")
    with pytest.raises(AmbiguousDeviceError):
        resolve_serial_device("port-3-1.2", identities=[NO_SERIAL_AT_PORT, twin])


def test_a_port_binding_refuses_a_substitute_device_with_another_vid_pid() -> None:
    substitute = replace(NO_SERIAL_AT_PORT, vid=0x2341, pid=0x0043)
    with pytest.raises(DeviceNotFoundError):
        resolve_serial_device("port-3-1.2", identities=[substitute, TEENSY], vid=0x1A86, pid=0x7523)
    assert (
        resolve_serial_device(
            "port-3-1.2", identities=[NO_SERIAL_AT_PORT, TEENSY], vid=0x1A86, pid=0x7523
        )
        == "/dev/ttyUSB3"
    )
    # no vid/pid from the caller: today's behaviour, the port alone decides
    assert resolve_serial_device("port-3-1.2", identities=[substitute, TEENSY]) == "/dev/ttyUSB3"


# ── replay (SOLUSDEV-321 P2-T4): a recorded capture opened as a configured robot ────────────────

REPLAY_BINDING = "REPLAY-0001"
REPLAY_REF = f"usb:{REPLAY_BINDING}"
REPLAY_EPOCH = datetime(2026, 10, 25, tzinfo=UTC)
#: How long a test watches a pump poll a replay that has ended.
POLL_WINDOW_SECONDS = 0.5
ARM, PART_ONE, PART_TWO = uuid4(), uuid4(), uuid4()


def _robot_document(binding: str = REPLAY_BINDING) -> dict[str, Any]:
    """A two-part robot's HardwareConfig: address 1 streams `a.position`, address 2 `b.position`."""
    return HardwareConfig(
        robot_entity_id=ARM,
        identity=TransportBinding(kind=TransportKind.USB_SERIAL, binding=binding),
        protocol=ProtocolBinding(driver_id="lb06"),
        bus_map=[
            BusMapEntry(protocol="lb06", address="1", part_entity_id=PART_ONE),
            BusMapEntry(protocol="lb06", address="2", part_entity_id=PART_TWO),
        ],
        parts={
            str(PART_ONE): PartConfig(telemetry=[TelemetryChannel(name="a.position", unit="deg")]),
            str(PART_TWO): PartConfig(telemetry=[TelemetryChannel(name="b.position", unit="deg")]),
        },
        provenance={
            key: ProvenanceRecord(by=FieldProvenance.USER)
            for key in ("identity", "protocol", "bus_map", "parts")
        },
    ).model_dump(mode="json")


def _capture(directory: Path, *, binding: str = REPLAY_BINDING, lines: int = 3) -> Path:
    """A capture of `lines` LB-06 lines, one every 50 ms, carrying both parts' positions."""
    frames = []
    for index in range(lines):
        packet = TelemetryPacket(
            device_id=f"usb:{binding}",
            timestamp=REPLAY_EPOCH + timedelta(milliseconds=50 * index),
            seq=index,
            values={"a.position": float(index), "b.position": 10.0 + index},
            units={"a.position": "deg", "b.position": "deg"},
        )
        frames.append({"t": index * 0.05, "hex": (encode_json(packet) + "\n").encode().hex()})
    path = directory / "capture.json"
    path.write_text(json.dumps({"transport": "usb_serial", "binding": binding, "frames": frames}))
    return path


def _replay_config(path: Path, *, realtime: bool = False) -> dict[str, Any]:
    return {"document": _robot_document(), "recording": str(path), "realtime": realtime}


async def _packets(connection: PacketStreamLiveConnection, count: int) -> list[TelemetryPacket]:
    """The first `count` packets the connection pumps, then it is closed."""
    packets: list[TelemetryPacket] = []
    enough = asyncio.Event()

    async def tap(packet: TelemetryPacket) -> None:
        packets.append(packet)
        if len(packets) >= count:
            enough.set()

    connection.tap = tap
    handle = await connection.subscribe(TelemetryWindow(duration_seconds=1.0))
    try:
        await asyncio.wait_for(enough.wait(), timeout=10)
    finally:
        await connection.unsubscribe(handle)
        await connection.aclose()
    return packets


async def test_open_replay_streams_the_capture_as_the_robots_parts(tmp_path: Path) -> None:
    connection = await open_replay(_replay_config(_capture(tmp_path)), project_id=uuid4())

    packets = await _packets(connection, 6)

    assert [packet.device_id for packet in packets] == [f"{REPLAY_REF}/1", f"{REPLAY_REF}/2"] * 3
    assert [dict(packet.values) for packet in packets[:2]] == [
        {"a.position": 0.0},
        {"b.position": 10.0},
    ]
    assert dict(packets[0].units) == {"a.position": "deg"}
    assert [packet.timestamp for packet in packets[::2]] == [  # the line's own event time
        REPLAY_EPOCH + timedelta(milliseconds=50 * index) for index in range(3)
    ]


async def test_open_replay_refuses_a_capture_of_another_device(tmp_path: Path) -> None:
    other = _capture(tmp_path, binding="OTHER-0002")

    with pytest.raises(ValueError, match="another device") as refused:
        await open_replay(_replay_config(other), project_id=uuid4())

    assert "OTHER-0002" not in str(refused.value) and REPLAY_BINDING not in str(refused.value)


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[1, 2]",
        '{"transport": "usb_serial"}',
        '{"transport": "nowhere", "binding": "X", "frames": []}',
        '{"transport": "usb_serial", "binding": "X", "frames": [{"t": 0, "hex": "zz"}]}',
        '{"transport": "usb_serial", "binding": "X", "frames": ["secret-frame-text"]}',
        "[" * 100_000,  # M75: nesting past the decoder's recursion limit is unreadable too
    ],
)
async def test_open_replay_names_an_unreadable_capture_without_echoing_it(
    tmp_path: Path, text: str, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "capture.json"
    path.write_text(text)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ValueError, match="could not be read") as refused:
        await open_replay(_replay_config(path), project_id=uuid4())

    assert "secret-frame-text" not in str(refused.value) and "nowhere" not in str(refused.value)
    logged = caplog.text  # the refusal logs the exception's type, never its message or the path
    assert "secret-frame-text" not in logged and str(tmp_path) not in logged


async def test_open_replay_refuses_a_path_that_moved_after_it_was_checked(tmp_path: Path) -> None:
    """The API hands over a resolved path; a symlink there now is a swap, not the checked file."""
    real = _capture(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(real)

    with pytest.raises(ValueError, match="moved"):
        await open_replay(_replay_config(link), project_id=uuid4())


async def test_open_replay_calls_a_symlink_loop_a_swap_and_logs_no_server_path(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A loop swapped in after the API's check: resolving it raises an error that names the
    server's path. That error is the same answer as any swap, and neither it nor a log shows it."""
    loop = tmp_path / "loop.json"
    loop.symlink_to(loop)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ValueError, match="moved") as refused:
        await open_replay(_replay_config(loop), project_id=uuid4())

    assert str(tmp_path) not in str(refused.value) + caplog.text


async def test_open_replay_reads_a_capture_only_up_to_the_cap_it_was_given(tmp_path: Path) -> None:
    """The route stat'ed the file once; the runner's read is bounded by the same cap, so a file
    grown after that check is refused, with the fixed message and no path."""
    path = _capture(tmp_path)
    size = path.stat().st_size

    at_cap = await open_replay({**_replay_config(path), "max_bytes": size}, project_id=uuid4())
    await at_cap.aclose()
    with pytest.raises(ValueError, match="could not be read") as refused:
        await open_replay({**_replay_config(path), "max_bytes": size - 1}, project_id=uuid4())

    assert str(tmp_path) not in str(refused.value)


async def test_open_replay_polls_an_ended_capture_like_a_quiet_link_not_a_busy_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SOLUSDEV-321 P2-T4 fix 1: a fast replay (`realtime` false) that had reached its end
    answered silence at once, and the lb06 source polling it spun on a thread hop, about 6,000
    reads a second and 0.8 of a core in the API process until the session was stopped. It now
    waits a quiet read for each read, as a live link with nothing to say does."""
    reads = 0
    real_recv = ReplayChannel.recv

    def counting(self: ReplayChannel, max_bytes: int = 4096) -> Frame | None:
        nonlocal reads
        reads += 1
        return real_recv(self, max_bytes)

    monkeypatch.setattr(ReplayChannel, "recv", counting)
    connection = await open_replay(_replay_config(_capture(tmp_path)), project_id=uuid4())
    seen: list[TelemetryPacket] = []
    consumed = asyncio.Event()

    async def tap(packet: TelemetryPacket) -> None:
        seen.append(packet)
        if len(seen) >= 6:  # three lines of two parts: the whole capture
            consumed.set()

    connection.tap = tap
    handle = await connection.subscribe(TelemetryWindow(duration_seconds=1.0))
    try:
        await asyncio.wait_for(consumed.wait(), timeout=10)
        await asyncio.sleep(0.1)  # into the idle poll
        before = reads
        await asyncio.sleep(POLL_WINDOW_SECONDS)
        polled = reads - before
    finally:
        await connection.unsubscribe(handle)
        await connection.aclose()

    quiet_reads = POLL_WINDOW_SECONDS / QUIET_READ_SECONDS
    assert polled <= quiet_reads + 3, (
        f"{polled / POLL_WINDOW_SECONDS:.0f} reads a second against a quiet link's "
        f"{1 / QUIET_READ_SECONDS:.0f}"
    )


async def test_open_replay_opens_on_a_scratch_registry_and_never_reconnects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from livebench.hardware import connection as connection_module
    from livebench.hardware.registries import default_registries

    shared = default_registries().transports
    kinds_before = shared.kinds()
    seen: dict[str, Any] = {}
    real = connection_module.open_robot_connection

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(connection_module, "open_robot_connection", spy)
    connection = await open_replay(_replay_config(_capture(tmp_path)), project_id=uuid4())
    await connection.aclose()

    assert seen["reconnect"] is False
    assert seen["transports"] is not shared
    assert seen["transports"].kinds() == [TransportKind.USB_SERIAL]
    assert shared.kinds() == kinds_before  # the process-wide transports are untouched


async def test_open_replay_paces_by_recorded_time_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from livebench.hardware import replay as replay_module

    asked: list[bool] = []
    real = replay_module.replay_opener

    def spy(recording: Any, *, realtime: bool = False) -> Any:
        asked.append(realtime)
        return real(recording, realtime=realtime)

    monkeypatch.setattr(replay_module, "replay_opener", spy)
    path = _capture(tmp_path)
    for realtime in (True, False):
        connection = await open_replay(_replay_config(path, realtime=realtime), project_id=uuid4())
        await connection.aclose()
    unasked = {"document": _robot_document(), "recording": str(path)}
    await (await open_replay(unasked, project_id=uuid4())).aclose()

    assert asked == [True, False, True]  # the default is the pane's: paced
