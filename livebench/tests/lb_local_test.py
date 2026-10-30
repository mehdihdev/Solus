"""SOLUSDEV-72: the local source catalog — honest availability probes, serial-keyed
device identity (by-id paths), and lazy provider factories."""

import builtins
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from livebench.local import (
    AmbiguousDeviceError,
    DeviceNotFoundError,
    available_simulators,
    list_devices,
    open_mujoco,
    resolve_serial_device,
)
from livebench.recognition.passive import identify_port

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


# ── teleoperation bridge (SOLUSDEV-319): the API's door to livebench.teleop ──────


class _Conn:
    def __init__(self, actuator: Any) -> None:
        self.actuator = actuator


def _arms(follower_pan: int = 2000) -> tuple[_Conn, _Conn]:
    from lb_teleop_test import FakeActuator, _joint

    leader = FakeActuator([_joint(1, "l-pan"), _joint(6, "l-grip", "%")], {1: 2000, 6: 500})
    follower = FakeActuator(
        [_joint(1, "f-pan"), _joint(6, "f-grip", "%")], {1: follower_pan, 6: 500}
    )
    return _Conn(leader), _Conn(follower)


def test_teleop_preview_wire_carries_pairs_blockers_and_tolerance() -> None:
    from livebench.local import teleop_preview

    leader, follower = _arms(follower_pan=2100)
    wire = teleop_preview(leader, follower)
    assert wire["ready"] is True and wire["blockers"] == []
    assert wire["tolerance"] == {"deg": 15.0, "%": 20.0}
    assert wire["pairs"][0] == {
        "address": 1,
        "leader_signal": "l-pan.position",
        "follower_signal": "f-pan.position",
        "unit": "deg",
        "leader_value": 200.0,
        "follower_value": 210.0,
        "delta": -10.0,
        "within_tolerance": True,
    }


def test_teleop_preview_blockers_name_their_joint() -> None:
    from lb_teleop_test import FakeActuator, _joint
    from livebench.local import teleop_preview

    leader = _Conn(FakeActuator([_joint(1, "l"), _joint(2, "l2")], {1: 0, 2: 0}))
    follower = _Conn(FakeActuator([_joint(1, "f")], {1: 0}))
    wire = teleop_preview(leader, follower)
    assert wire["blockers"][0]["code"] == "unpaired_joint"
    assert wire["blockers"][0]["address"] == 2


async def test_a_bus_error_while_starting_is_a_runtime_failure_naming_the_hold() -> None:
    from livebench.local import teleop_start

    leader, follower = _arms()

    def unplugged() -> dict[int, int]:
        raise OSError("device disconnected")

    follower.actuator.hold = unplugged
    with pytest.raises(RuntimeError, match="may be holding"):
        await teleop_start(leader, follower, on_stopped=lambda reason: None)


def test_teleop_preview_refuses_a_connection_without_an_actuator() -> None:
    from livebench.local import teleop_preview
    from solus_api.livebench.teleop import NotActuatedError

    leader, _ = _arms()
    with pytest.raises(NotActuatedError):
        teleop_preview(leader, _Conn(None))


def test_teleop_preview_reports_a_link_gap_as_a_blocker() -> None:
    from livebench.local import teleop_preview

    leader, follower = _arms()
    follower.actuator.read_fails = 1
    wire = teleop_preview(leader, follower)
    assert wire["ready"] is False and wire["blockers"][0]["code"] == "link_unavailable"


async def test_teleop_start_returns_a_handle_with_wire_pairs_and_stops() -> None:
    from livebench.local import teleop_start

    leader, follower = _arms()
    reasons: list[str] = []
    handle = await teleop_start(leader, follower, on_stopped=reasons.append)
    assert handle.running and handle.rate_hz == 30.0
    assert [p["address"] for p in handle.pairs] == [1, 6]
    await handle.stop("user")
    assert not handle.running and reasons == ["user"]
    assert follower.actuator.released is False


async def test_teleop_start_maps_a_failed_gate_to_the_api_error_with_the_fresh_preview() -> None:
    from livebench.local import teleop_start
    from solus_api.livebench.teleop import TeleopNotReadyError

    leader, follower = _arms(follower_pan=4000)  # 200 deg apart
    with pytest.raises(TeleopNotReadyError) as refused:
        await teleop_start(leader, follower, on_stopped=lambda reason: None)
    assert refused.value.preview["pairs"][0]["within_tolerance"] is False
    assert follower.actuator.held is False


def test_robot_release_turns_torque_off_through_the_actuator() -> None:
    from livebench.local import robot_release
    from solus_api.livebench.teleop import NotActuatedError

    _, follower = _arms()
    robot_release(follower)
    assert follower.actuator.released is True
    with pytest.raises(NotActuatedError):
        robot_release(_Conn(None))
