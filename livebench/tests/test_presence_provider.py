"""Presence upload refuses changed identities and contested serial ownership."""

import fcntl
from unittest.mock import AsyncMock

import pytest
from livebench.plugins.arduino.presence_provider import LocalPresenceProvider, PresenceRefusalError
from livebench.recognition.passive import identify_port


def provider(tmp_path, monkeypatch):
    binary = tmp_path / "arduino-cli"
    binary.write_text("fixture")
    binary.chmod(0o700)
    port = tmp_path / "ttyUSB0"
    port.write_bytes(b"")
    identity = identify_port(device=str(port), vid=0x1A86, pid=0x7523, serial=None, location="3-1")
    p = LocalPresenceProvider(
        binary=str(binary), library=tmp_path, enumerate_ports=lambda: [identity]
    )
    run = AsyncMock()
    monkeypatch.setattr("livebench.plugins.arduino.presence_provider.run_cli", run)
    return p, identity, run


async def test_upload_uses_snapshot_and_exclusive_lease(tmp_path, monkeypatch):
    p, _, run = provider(tmp_path, monkeypatch)
    target = p.snapshot("port-3-1", "uno_avr")
    with open(target["path"], "rb") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(PresenceRefusalError, match="in use"):
            await p.upload(target, "uno_avr", b":00000001FF\n")
    run.assert_not_awaited()
    await p.upload(target, "uno_avr", b":00000001FF\n")
    args = run.await_args.args[0]
    assert "--verify" in args
    assert args[1] == "upload" and args[args.index("-p") + 1] == target["path"]


async def test_changed_identity_refuses_before_upload(tmp_path, monkeypatch):
    p, _, run = provider(tmp_path, monkeypatch)
    target = p.snapshot("port-3-1", "uno_avr")
    target["pid"] = 123
    with pytest.raises(PresenceRefusalError):
        await p.upload(target, "uno_avr", b"hex")
    run.assert_not_awaited()


def test_unknown_driver_usb_and_ambiguous_targets_refuse(tmp_path, monkeypatch):
    p, identity, _ = provider(tmp_path, monkeypatch)
    p.enumerate_ports = lambda: [identity, identity]
    with pytest.raises(PresenceRefusalError):
        p.snapshot("port-3-1", "uno_avr")
    p.enumerate_ports = lambda: [
        identify_port(device="/dev/ttyACM0", vid=0x483, pid=0x5740, serial="arm")
    ]
    with pytest.raises(PresenceRefusalError):
        p.snapshot("arm", "uno_avr")


async def test_preparation_is_only_compilation_and_revalidates(tmp_path, monkeypatch):
    from types import SimpleNamespace

    p, _, run = provider(tmp_path, monkeypatch)
    compile_only = AsyncMock(
        return_value=SimpleNamespace(
            source=b"source", binary=b"hex", source_sha256="s", binary_sha256="b"
        )
    )
    monkeypatch.setattr(
        "livebench.plugins.arduino.presence_provider.PresenceCompiler.prepare", compile_only
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
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    p, identity, run = provider(tmp_path, monkeypatch)
    rows = [{"channel": "light.raw", "pin": "A0", "kind": "analog_input"}]

    def enumerate_mutates_caller_input():
        rows[0]["pin"] = "D0"
        return [identity]

    p.enumerate_ports = enumerate_mutates_caller_input
    compile_only = AsyncMock(
        return_value=SimpleNamespace(
            source=b"source", binary=b"hex", source_sha256="s", binary_sha256="b"
        )
    )
    monkeypatch.setattr(
        "livebench.plugins.arduino.presence_provider.PresenceCompiler.prepare", compile_only
    )
    result = await p.prepare("port-3-1", "uno_avr", "topology", "uno.alive", rows)
    assert result["binary"] == b"hex"
    assert compile_only.await_args.kwargs["wiring"][0]["pin"] == "A0"
    run.assert_not_awaited()
    with pytest.raises(ValueError):
        await p.prepare("port-3-1", "uno_avr", "topology", "uno.alive", rows)
    assert compile_only.await_count == 1


async def test_topology_provider_revalidates_target_after_compilation(tmp_path, monkeypatch):
    from types import SimpleNamespace

    p, _, run = provider(tmp_path, monkeypatch)

    async def prepare_then_disconnect(self, **kwargs):
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


def test_topology_provider_keeps_motor_driver_exclusion():
    assert LocalPresenceProvider.accepts_protocol("arduino.telemetry")
    assert LocalPresenceProvider.accepts_protocol("solus.telemetry")
    assert not LocalPresenceProvider.accepts_protocol("feetech-sts")
