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
