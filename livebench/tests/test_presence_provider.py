"""Presence upload refuses changed identities and contested serial ownership."""

import fcntl
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import serial
from livebench.hardware.serial_owner import Claimant, SerialOwner
from livebench.plugins.arduino.presence_provider import LocalPresenceProvider
from livebench.recognition.passive import PortIdentity, identify_port
from solus_api.hardware.presence import PresenceRefusalError
from solus_api.livebench.sessions import DeviceBusyError

REF = "usb:port-3-1"
HEX = b":00000001FF\n"
PROJECT = uuid.UUID("3d2b7f5e-6a1c-4c8e-9b0a-1f2e3d4c5b6a")
USER = uuid.UUID("7c1d9e2f-0a3b-4c5d-8e6f-112233445566")
MINE = Claimant("session", str(PROJECT), str(USER))  # the flashing member's own session


def provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: SerialOwner | None = None
) -> tuple[LocalPresenceProvider, PortIdentity, AsyncMock]:
    binary = tmp_path / "arduino-cli"
    binary.write_text("fixture")
    binary.chmod(0o700)
    port = tmp_path / "ttyUSB0"
    port.write_bytes(b"")
    identity = identify_port(device=str(port), vid=0x1A86, pid=0x7523, serial=None, location="3-1")
    p = LocalPresenceProvider(
        binary=str(binary),
        library=tmp_path,
        enumerate_ports=lambda: [identity],
        owner=owner or SerialOwner(),
    )
    run = AsyncMock()
    monkeypatch.setattr("livebench.plugins.arduino.presence_provider.run_cli", run)
    return p, identity, run


def _compiled(source: bytes = b"source") -> AsyncMock:
    return AsyncMock(
        return_value=SimpleNamespace(
            source=source, binary=b"hex", source_sha256="s", binary_sha256="b"
        )
    )


async def test_upload_uses_snapshot_and_exclusive_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p, _, run = provider(tmp_path, monkeypatch)
    target = p.snapshot("port-3-1", "uno_avr")
    with open(target["path"], "rb") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(DeviceBusyError) as busy:  # another program holds the port
            await p.upload(target, "uno_avr", HEX)
    assert (busy.value.device_ref, busy.value.holder) == (REF, None)
    run.assert_not_awaited()
    await p.upload(target, "uno_avr", HEX)
    assert run.await_args is not None
    args = run.await_args.args[0]
    assert "--verify" in args
    assert args[1] == "upload" and args[args.index("-p") + 1] == target["path"]


async def test_the_upload_holds_the_serial_owner_for_its_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SOLUSDEV-326: nothing in this process opens the port while firmware is going on."""
    owner = SerialOwner()
    p, _, run = provider(tmp_path, monkeypatch, owner)
    target = p.snapshot("port-3-1", "uno_avr")
    refused: list[DeviceBusyError] = []

    def never() -> serial.Serial:
        raise AssertionError("the port is not opened during an upload")

    async def uploading(argv: list[str]) -> None:
        teammate = Claimant("session", str(PROJECT), str(uuid.uuid4()))
        elsewhere = Claimant("session", str(uuid.uuid4()), str(USER))
        for claimant in (MINE, teammate, elsewhere, Claimant("session")):
            try:
                owner.hold(REF, claimant, never)
            except DeviceBusyError as exc:
                refused.append(exc)

    run.side_effect = uploading
    await p.upload(target, "uno_avr", HEX, project_id=PROJECT, user_id=USER)
    assert [exc.holder for exc in refused] == ["upload", None, None, None]  # its own member only
    owner.hold(REF, MINE, lambda: serial.serial_for_url("loop://")).close()


async def test_a_device_this_process_holds_refuses_the_upload_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = SerialOwner()
    p, _, run = provider(tmp_path, monkeypatch, owner)
    target = p.snapshot("port-3-1", "uno_avr")
    session = owner.hold(REF, MINE, lambda: serial.serial_for_url("loop://"))
    for project_id, user_id, holder in (
        (PROJECT, USER, "session"),
        (PROJECT, uuid.uuid4(), None),  # a teammate's flash: their session may be hidden (§1a)
        (PROJECT, None, None),
        (uuid.uuid4(), USER, None),
        (None, None, None),
    ):
        with pytest.raises(DeviceBusyError) as busy:
            await p.upload(target, "uno_avr", HEX, project_id=project_id, user_id=user_id)
        assert busy.value.holder == holder  # the session is named to its own member only
    run.assert_not_awaited()
    session.close()


async def test_changed_identity_refuses_before_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p, _, run = provider(tmp_path, monkeypatch)
    target = p.snapshot("port-3-1", "uno_avr")
    target["pid"] = 123
    with pytest.raises(PresenceRefusalError):
        await p.upload(target, "uno_avr", b"hex")
    run.assert_not_awaited()


def test_unknown_driver_usb_and_ambiguous_targets_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p, identity, _ = provider(tmp_path, monkeypatch)
    p.enumerate_ports = lambda: [identity, identity]
    with pytest.raises(PresenceRefusalError):
        p.snapshot("port-3-1", "uno_avr")
    p.enumerate_ports = lambda: [
        identify_port(device="/dev/ttyACM0", vid=0x483, pid=0x5740, serial="arm")
    ]
    with pytest.raises(PresenceRefusalError):
        p.snapshot("arm", "uno_avr")


async def test_preparation_is_only_compilation_and_revalidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p, _, run = provider(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "livebench.plugins.arduino.presence_provider.PresenceCompiler.prepare", _compiled()
    )
    result = await p.prepare("port-3-1", "uno_avr", "heartbeat", "uno.alive")
    assert result["source"] == b"source"
    assert p.profiles()[0]["available"]
    run.assert_not_awaited()
    tmp_path.joinpath("arduino-cli").unlink()
    assert not p.profiles()[0]["available"]
    with pytest.raises(PresenceRefusalError, match="unavailable"):
        await p.prepare("port-3-1", "uno_avr", "heartbeat", "uno.alive")
    with pytest.raises(PresenceRefusalError):
        await p.upload(result["target"], "uno_avr", b"")
    with pytest.raises(ValueError):
        LocalPresenceProvider(binary="relative", library=tmp_path)


async def test_topology_provider_freezes_review_before_await_and_never_uploads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p, identity, run = provider(tmp_path, monkeypatch)
    rows = [{"channel": "light.raw", "pin": "A0", "kind": "analog_input"}]

    def enumerate_mutates_caller_input() -> list[PortIdentity]:
        rows[0]["pin"] = "D0"
        return [identity]

    p.enumerate_ports = enumerate_mutates_caller_input
    compile_only = _compiled()
    compile_only.return_value.binary = b"hex"
    monkeypatch.setattr(
        "livebench.plugins.arduino.presence_provider.PresenceCompiler.prepare", compile_only
    )
    result = await p.prepare("port-3-1", "uno_avr", "topology", "uno.alive", rows)
    assert result["binary"] == b"hex"
    assert compile_only.await_args is not None
    assert compile_only.await_args.kwargs["wiring"][0]["pin"] == "A0"
    run.assert_not_awaited()
    with pytest.raises(ValueError):
        await p.prepare("port-3-1", "uno_avr", "topology", "uno.alive", rows)
    assert compile_only.await_count == 1


async def test_topology_provider_revalidates_target_after_compilation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p, _, run = provider(tmp_path, monkeypatch)

    async def prepare_then_disconnect(self: Any, **kwargs: Any) -> SimpleNamespace:
        p.enumerate_ports = lambda: []
        return SimpleNamespace(
            source=b"source", binary=b"hex", source_sha256="s", binary_sha256="b"
        )

    monkeypatch.setattr(
        "livebench.plugins.arduino.presence_provider.PresenceCompiler.prepare",
        prepare_then_disconnect,
    )
    with pytest.raises(PresenceRefusalError):
        await p.prepare("port-3-1", "uno_avr", "topology", "uno.alive", [])
    run.assert_not_awaited()


def test_topology_provider_keeps_motor_driver_exclusion() -> None:
    assert LocalPresenceProvider.accepts_protocol("arduino.telemetry")
    assert LocalPresenceProvider.accepts_protocol("solus.telemetry")
    assert not LocalPresenceProvider.accepts_protocol("feetech-sts")
