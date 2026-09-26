"""Generate and compile non-actuating presence firmware; never upload it."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType

from livebench.deploy.flash import FlashError
from livebench.plugins.arduino.arduino_flash import run_cli
from livebench.plugins.arduino.wiring import source_for_wiring, validate_wiring

# Provider-owned profiles, not renderer-supplied FQBNs or compiler arguments.
_PROFILES = MappingProxyType(
    {"uno_avr": ("arduino:avr:uno", 6, 32256), "nano_avr": ("arduino:avr:nano", 8, 30720)}
)
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_DEVICE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:./-]{0,127}\Z")


@dataclass(frozen=True)
class PreparedPresence:
    profile_id: str
    kind: str
    source: bytes
    binary: bytes
    source_sha256: str
    binary_sha256: str


def generate_source(
    *,
    profile_id: str,
    device_id: str,
    channel: str,
    kind: str,
    wiring: Sequence[Mapping[str, str]] = (),
) -> str:
    """Only status query '?' is accepted; probe values carry no topology claims."""
    if profile_id not in _PROFILES or kind not in {"heartbeat", "probe", "topology"}:
        raise ValueError("unsupported presence profile or kind")
    if not _IDENTIFIER.fullmatch(channel) or not _DEVICE.fullmatch(device_id):
        raise ValueError("invalid telemetry identifier")
    reviewed = validate_wiring(profile_id, channel, kind, wiring)
    probe = kind == "probe"
    includes = "#include <Wire.h>\n" if probe else ""
    setup = "  Wire.begin();\n  Wire.setWireTimeout(25000, true);\n" if probe else ""
    observations = ""
    if kind == "topology":
        setup, observations = source_for_wiring(reviewed)
        if reviewed:
            includes = "#include <avr/pgmspace.h>\n"
    if probe:
        observations = f"""
  // Each analog sample is a raw observation, never evidence of a connected part.
  for (uint8_t pin = 0; pin < {_PROFILES[profile_id][1]}; ++pin) {{
    char name[24];
    snprintf(name, sizeof(name), "probe.analog.%u", pin);
    telemetry.add(name, analogRead(A0 + pin), "count");
    telemetry.send();
  }}
  unsigned int responding = 0;
  for (uint8_t address = 8; address < 120; ++address) {{
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {{
      ++responding;
      telemetry.add("probe.i2c.address", address, "count");
      telemetry.send();
    }}
  }}
  // Zero means no responding I2C devices, not proof that pins are unwired.
  telemetry.add("probe.i2c.responding", responding, "count");
  telemetry.send();
"""
    return f'''#include <SolusTelemetry.h>
#include <stdio.h>
{includes}
SolusTelemetry telemetry(Serial, "{device_id}");
unsigned long lastSample = 0;
void setup() {{
  Serial.begin(115200);
  telemetry.begin();
{setup}}}
void loop() {{
  bool status = false;
  // Bound input processing so a busy serial sender cannot starve heartbeat.
  for (uint8_t n = 0; n < 16 && Serial.available(); ++n) {{
    if (Serial.read() == '?') status = true;
  }}
  unsigned long now = millis();
  if (!status && (unsigned long)(now - lastSample) < 1000) return;
  lastSample = now;
  telemetry.add("{channel}", 1, "count");
  telemetry.send();
{observations}}}
'''


class PresenceCompiler:
    """Trusted host configuration pins compiler and bundled library location."""

    def __init__(self, *, binary: str, library: Path) -> None:
        if not Path(binary).is_absolute() or not library.is_absolute() or not library.is_dir():
            raise ValueError("absolute compiler and bundled library directory required")
        self._binary = binary
        self._library = library

    async def prepare(
        self,
        *,
        profile_id: str,
        device_id: str,
        channel: str,
        kind: str,
        wiring: Sequence[Mapping[str, str]] = (),
    ) -> PreparedPresence:
        source = generate_source(
            profile_id=profile_id, device_id=device_id, channel=channel, kind=kind, wiring=wiring
        ).encode()
        fqbn, _, binary_limit = _PROFILES[profile_id]
        with TemporaryDirectory(prefix="solus-presence-") as directory:
            root = Path(directory)
            sketch = root / "presence"
            sketch.mkdir(mode=0o700)
            (sketch / "presence.ino").write_bytes(source)
            output = root / "compiled"
            output.mkdir(mode=0o700)
            await run_cli(
                [
                    self._binary,
                    "compile",
                    "--fqbn",
                    fqbn,
                    "--library",
                    str(self._library),
                    "--output-dir",
                    str(output),
                    str(sketch),
                ]
            )
            artifact = output / "presence.ino.hex"
            if artifact.is_symlink() or not artifact.is_file():
                raise FlashError("compiler did not produce the expected firmware")
            # Intel HEX is larger than binary; reserve a bounded textual encoding overhead.
            if not 0 < artifact.stat().st_size <= binary_limit * 3:
                raise FlashError("compiled firmware exceeds profile artifact size limit")
            firmware = artifact.read_bytes()
        return PreparedPresence(
            profile_id,
            kind,
            source,
            firmware,
            hashlib.sha256(source).hexdigest(),
            hashlib.sha256(firmware).hexdigest(),
        )
