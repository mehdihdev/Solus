"""Presence preparation is bounded compilation, never an upload."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from livebench.deploy.flash import FlashError
from livebench.plugins.arduino import presence
from livebench.plugins.arduino.arduino_flash import run_cli


def test_source_is_bounded_read_only_and_profile_specific() -> None:
    heartbeat = presence.generate_source(
        profile_id="uno_avr", device_id="usb:test", channel="uno.alive", kind="heartbeat"
    )
    assert '"uno.alive"' in heartbeat and "SolusTelemetry" in heartbeat
    assert "analogRead" not in heartbeat and "digitalWrite" not in heartbeat
    probe = presence.generate_source(
        profile_id="uno_avr", device_id="usb:test", channel="board.alive", kind="probe"
    )
    assert "analogRead" in probe and "endTransmission" in probe
    assert "raw observation" in probe and "attached" not in probe
    assert "pin < 6" in probe
    assert "pin < 8" in presence.generate_source(
        profile_id="nano_avr", device_id="usb:test", channel="board.alive", kind="probe"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"profile_id": "evil:fqbn"},
        {"device_id": 'x";evil()'},
        {"channel": "x\\n"},
        {"kind": "actuate"},
    ],
)
def test_rejects_untrusted_source_values(overrides: dict[str, str]) -> None:
    values = dict(
        profile_id="uno_avr", device_id="usb:test", channel="board.alive", kind="heartbeat"
    )
    values.update(overrides)
    with pytest.raises(ValueError):
        presence.generate_source(**values)


@pytest.mark.asyncio
async def test_prepare_immutable_digests_private_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    library = tmp_path / "library"
    library.mkdir()
    calls: list[list[str]] = []

    async def compile_fake(argv: list[str], **kwargs: object) -> bytes:
        calls.append(argv)
        sketch = Path(argv[-1])
        assert sketch.parent.stat().st_mode & 0o077 == 0
        output = Path(argv[argv.index("--output-dir") + 1])
        (output / "presence.ino.hex").write_bytes(b":hex fixture")
        return b"ok"

    monkeypatch.setattr(presence, "run_cli", compile_fake)
    compiler = presence.PresenceCompiler(binary="/usr/bin/arduino-cli", library=library)
    result = await compiler.prepare(
        profile_id="uno_avr", device_id="usb:test", channel="uno.alive", kind="heartbeat"
    )
    assert result.binary == b":hex fixture" and len(result.binary_sha256) == 64
    assert calls[0][1] == "compile" and "upload" not in calls[0]
    assert not Path(calls[0][-1]).exists()
    with pytest.raises(FrozenInstanceError):
        result.profile_id = "changed"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_cli_output_limit_and_timeout() -> None:
    with pytest.raises(FlashError, match="output limit"):
        await run_cli(["/usr/bin/python3", "-c", "print('x'*10000)"], output_limit=100)
    with pytest.raises(FlashError, match="timed out"):
        await run_cli(["/usr/bin/python3", "-c", "import time;time.sleep(10)"], timeout=0.05)
    with pytest.raises(FlashError, match="exited"):
        await run_cli(["/usr/bin/python3", "-c", "raise SystemExit(3)"])


@pytest.mark.asyncio
async def test_compile_failure_cleans_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = AsyncMock(side_effect=FlashError("failed"))
    monkeypatch.setattr(presence, "run_cli", runner)
    compiler = presence.PresenceCompiler(binary="/usr/bin/arduino-cli", library=tmp_path)
    with pytest.raises(FlashError):
        await compiler.prepare(
            profile_id="uno_avr", device_id="usb:test", channel="uno.alive", kind="heartbeat"
        )
    assert not Path(runner.call_args.args[0][-1]).exists()


@pytest.mark.parametrize("kind", ["heartbeat", "probe", "topology"])
@pytest.mark.parametrize("profile", ["uno_avr", "nano_avr"])
def test_generated_source_compiles_against_host_library(
    tmp_path: Path, kind: str, profile: str
) -> None:
    import subprocess

    repo = Path(__file__).resolve().parents[2]
    library = repo / "libs/solus-telemetry/arduino"
    (tmp_path / "avr").mkdir()
    (tmp_path / "avr/pgmspace.h").write_text(
        "#include <string.h>\n#define PSTR(s) (s)\n#define strcpy_P strcpy\n"
    )
    stub = (library / "extras/host/Arduino.h").read_text()
    (tmp_path / "Arduino.h").write_text(
        stub
        + """
class HostSerial : public Stream {
 public:
  void begin(unsigned long) {}
  int available() { return 0; }
  int read() { return -1; }
  size_t write(uint8_t) override { return 1; }
};
extern HostSerial Serial;
inline unsigned long millis() { return 1000; }
static const int A0 = 14, A5 = 19, A7 = 21, INPUT = 0;
inline void pinMode(int, int) {}
inline int digitalRead(int) { return 0; }
inline int analogRead(int) { return 0; }
"""
    )
    (tmp_path / "Wire.h").write_text("""
class HostWire {
 public:
  void begin() {}
  void setWireTimeout(unsigned long, bool) {}
  void beginTransmission(unsigned char) {}
  int endTransmission() { return 4; }
};
extern HostWire Wire;
""")
    (tmp_path / "presence.cpp").write_text(
        presence.generate_source(
            profile_id=profile,
            device_id="usb:test",
            channel="board.alive",
            kind=kind,
            wiring=[
                {
                    "channel": "sensor.raw",
                    "pin": "A7" if profile == "nano_avr" else "A5",
                    "kind": "analog_input",
                },
                {"channel": "switch.state", "pin": "D13", "kind": "digital_input"},
            ]
            if kind == "topology"
            else (),
        )
    )
    subprocess.run(
        [
            "/usr/bin/g++",
            "-std=c++11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-c",
            "-I",
            str(tmp_path),
            "-I",
            str(library / "src"),
            str(tmp_path / "presence.cpp"),
            "-o",
            str(tmp_path / "presence.o"),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )


@pytest.mark.parametrize("artifact_kind", ["absent", "empty", "large", "symlink"])
@pytest.mark.asyncio
async def test_compile_rejects_invalid_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, artifact_kind: str
) -> None:
    async def compile_fake(argv: list[str], **kwargs: object) -> bytes:
        output = Path(argv[argv.index("--output-dir") + 1]) / "presence.ino.hex"
        if artifact_kind == "empty":
            output.write_bytes(b"")
        elif artifact_kind == "large":
            output.write_bytes(b"a" * 100000)
        elif artifact_kind == "symlink":
            output.symlink_to(__file__)
        return b""

    monkeypatch.setattr(presence, "run_cli", compile_fake)
    with pytest.raises(FlashError):
        await presence.PresenceCompiler(binary="/usr/bin/arduino-cli", library=tmp_path).prepare(
            profile_id="uno_avr", device_id="usb:test", channel="board.alive", kind="heartbeat"
        )


@pytest.mark.asyncio
async def test_cli_success_and_cancellation(tmp_path: Path) -> None:
    import asyncio
    import os

    assert await run_cli(["/usr/bin/python3", "-c", "print('ok')"]) == b"ok\n"
    pidfile = tmp_path / "pid"
    task = asyncio.create_task(
        run_cli(
            [
                "/usr/bin/python3",
                "-c",
                "import os,sys,time;open(sys.argv[1],'w').write(str(os.getpid()));time.sleep(30)",
                str(pidfile),
            ]
        )
    )
    async with asyncio.timeout(5):
        while not pidfile.exists():
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)


def test_compiler_rejects_unpinned_configuration(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        presence.PresenceCompiler(binary="arduino-cli", library=tmp_path)


@pytest.mark.asyncio
async def test_upload_supervision_only_at_write_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    from livebench.deploy.flash import FlashPhase
    from livebench.plugins.arduino import arduino_flash

    run = AsyncMock(return_value=b"")
    monkeypatch.setattr(arduino_flash, "run_cli", run)
    runner = arduino_flash.ArduinoCliRunner(
        binary="/usr/bin/arduino-cli", fqbn="arduino:avr:uno", port="/dev/ttyUSB0"
    )
    for phase in FlashPhase:
        await runner.run(phase, "usb:test", Path("/tmp/firmware.hex"))
    run.assert_awaited_once_with(runner.upload_argv(Path("/tmp/firmware.hex")))
    assert "--verify" in runner.upload_argv(Path("/tmp/firmware.hex"))


@pytest.mark.asyncio
async def test_supervision_configuration_limits() -> None:
    with pytest.raises(FlashError):
        await run_cli(["relative-binary"])
    with pytest.raises(ValueError):
        await run_cli(["/usr/bin/false"], timeout=0)
