"""Local-only presence compiler/upload adapter with immutable USB snapshots."""

from __future__ import annotations

import asyncio
import fcntl
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from solus_api.hardware.presence import PresenceRefusalError

from livebench.plugins.arduino.arduino_flash import run_cli
from livebench.plugins.arduino.presence import PresenceCompiler
from livebench.plugins.arduino.wiring import validate_wiring
from livebench.recognition.passive import PortIdentity, binding_key, enumerate_usb_serial

_PROFILES = {
    "uno_avr": ("Arduino Uno (AVR)", "arduino:avr:uno"),
    "nano_avr": ("Arduino Nano (AVR)", "arduino:avr:nano"),
}
# Bridges are compatible candidates, never proof of a particular MCU. Explicit
# profile selection plus the central manual confirmation remains mandatory.
_USB = {
    "uno_avr": {(0x2341, 0x0043), (0x2A03, 0x0043), (0x1A86, 0x7523)},
    "nano_avr": {(0x0403, 0x6001), (0x1A86, 0x7523)},
}


class LocalPresenceProvider:
    @staticmethod
    def accepts_protocol(driver_id: str) -> bool:
        return driver_id in {"arduino.telemetry", "solus.telemetry"}

    def __init__(
        self,
        *,
        binary: str,
        library: Path,
        enumerate_ports: Callable[[], list[PortIdentity]] = enumerate_usb_serial,
    ):
        self.binary, self.library = binary, library
        if not Path(binary).is_absolute() or not library.is_absolute():
            raise ValueError("pinned absolute compiler/library required")
        self.enumerate_ports = enumerate_ports

    def profiles(self) -> list[dict[str, Any]]:
        available = os.access(self.binary, os.X_OK) and self.library.is_dir()
        return [
            {
                "id": key,
                "label": label,
                "available": available,
                "reason": None
                if available
                else "Arduino compiler or telemetry library unavailable",
            }
            for key, (label, _) in _PROFILES.items()
        ]

    def snapshot(self, binding: str, profile_id: str) -> dict[str, Any]:
        matches = [p for p in self.enumerate_ports() if binding_key(p) == binding]
        if profile_id not in _PROFILES or len(matches) != 1:
            raise PresenceRefusalError("Select one currently connected compatible board")
        port = matches[0]
        if (port.vid, port.pid) not in _USB[profile_id]:
            raise PresenceRefusalError(
                "This USB device is not eligible for the selected firmware profile"
            )
        return {
            "binding": binding,
            "path": port.device,
            "vid": port.vid,
            "pid": port.pid,
            "serial": port.serial,
            "location": port.location,
            "manual_confirmation_required": True,
        }

    def validate(self, target: dict[str, Any], profile_id: str) -> None:
        if self.snapshot(target["binding"], profile_id) != target:
            raise PresenceRefusalError("Device identity changed; prepare and review again")

    async def prepare(
        self,
        binding: str,
        profile_id: str,
        kind: str,
        channel: str,
        wiring: Sequence[Mapping[str, str]] = (),
    ) -> dict[str, Any]:
        reviewed = validate_wiring(profile_id, channel, kind, wiring)
        target = await asyncio.to_thread(self.snapshot, binding, profile_id)
        if not next(p["available"] for p in self.profiles() if p["id"] == profile_id):
            raise PresenceRefusalError("Arduino compiler or telemetry library unavailable")
        prepared = await PresenceCompiler(binary=self.binary, library=self.library).prepare(
            profile_id=profile_id,
            device_id=f"usb:{binding}",
            channel=channel,
            kind=kind,
            wiring=reviewed,
        )
        await asyncio.to_thread(self.validate, target, profile_id)
        return {
            "target": target,
            "source": prepared.source,
            "binary": prepared.binary,
            "source_sha256": prepared.source_sha256,
            "binary_sha256": prepared.binary_sha256,
        }

    async def upload(self, target: dict[str, Any], profile_id: str, firmware: bytes) -> None:
        if not 0 < len(firmware) <= 100000:
            raise PresenceRefusalError("Invalid firmware size")
        await asyncio.to_thread(self.validate, target, profile_id)
        # Opening without termios or DTR changes obtains only the same advisory
        # lock pyserial exclusive=True uses. It does not reset or query the board.
        fd = os.open(target["path"], os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise PresenceRefusalError(
                    "Device is in use; stop its session before approving"
                ) from exc
            await asyncio.to_thread(self.validate, target, profile_id)
            with TemporaryDirectory(prefix="solus-approved-presence-") as directory:
                artifact = Path(directory) / "presence.hex"
                artifact.write_bytes(firmware)
                await run_cli(
                    [
                        self.binary,
                        "upload",
                        "--verify",
                        "--fqbn",
                        _PROFILES[profile_id][1],
                        "-p",
                        target["path"],
                        "--input-file",
                        str(artifact),
                    ]
                )
        finally:
            os.close(fd)
