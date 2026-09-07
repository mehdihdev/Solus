"""Cross-runtime parity: every emitter in libs/solus-telemetry writes a line the Solus decoder
(`solus_api.graph.codec.decode_json`) turns into the same `TelemetryPacket`, and the Python and
Arduino emitters agree byte-for-byte on the shared golden inputs.

Dev-only cross-package test: `solus-telemetry` has no dependencies, but the workspace venv has
`solus_api`, which is the consumer this library exists for. The values are chosen with exactly
four non-zero-terminated decimals because the C++ side prints fixed 4 decimals while Python
prints the shortest repr — `0.1234` agrees, `1.0` vs `1.0000` would not.
"""

import importlib.util
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from solus_api.graph import codec, packet
from solus_telemetry import (
    MAX_DEVICE_ID_LEN,
    MAX_LINE_BYTES,
    MAX_SAFE_INT,
    MAX_SIGNAL_NAME_LEN,
    MAX_SIGNALS,
    MAX_UNIT_LEN,
    SCHEMA_VERSION,
    format_line,
)

LIB_DIR = Path(__file__).resolve().parents[2]
ARDUINO_DIR = LIB_DIR / "arduino"
MICROPYTHON_MODULE = LIB_DIR / "micropython" / "solus_telemetry.py"

DEVICE = "usb:5B42134331"
TS_US = 1234567  # a micros() value: the Arduino golden is since-boot, not epoch
SEQ = 0
VALUES = {
    "base.velocity": round(0.1234, 4),
    "base.yaw_rate": round(-0.0125, 4),
    "imu.accel_z": round(9.8067, 4),
    "motor.current": round(1.2345, 4),
    "battery.voltage": round(11.9876, 4),
    "chassis.temperature": round(27.1234, 4),
}
UNITS = {
    "base.velocity": "m/s",
    "base.yaw_rate": "rad/s",
    "imu.accel_z": "m/s^2",
    "motor.current": "A",
    "battery.voltage": "V",
    "chassis.temperature": "degC",
}

#: The Arduino golden: what `SolusTelemetry` prints for the inputs above with micros() == TS_US.
#: Captured from `arduino/extras/host/host_check.cpp` (host-compiled against the Stream stub in
#: `arduino/extras/host/Arduino.h`); `test_arduino_source_prints_the_golden` regenerates it.
ARDUINO_GOLDEN = (
    '{"schema_version":1,"device_id":"usb:5B42134331","ts_us":1234567,'
    '"values":{"base.velocity":0.1234,"base.yaw_rate":-0.0125,"imu.accel_z":9.8067,'
    '"motor.current":1.2345,"battery.voltage":11.9876,"chassis.temperature":27.1234},'
    '"seq":0,"units":{"base.velocity":"m/s","base.yaw_rate":"rad/s","imu.accel_z":"m/s^2",'
    '"motor.current":"A","battery.voltage":"V","chassis.temperature":"degC"}}\n'
)


def _expected_packet() -> packet.TelemetryPacket:
    return packet.TelemetryPacket(
        device_id=DEVICE,
        timestamp=datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=TS_US),
        values=VALUES,
        seq=SEQ,
        units=UNITS,
    )


def test_python_line_decodes_to_the_same_packet() -> None:
    line = format_line(DEVICE, VALUES, ts_us=TS_US, seq=SEQ, units=UNITS)
    assert codec.decode_json(line) == _expected_packet()


def test_epoch_timestamps_survive_to_the_microsecond() -> None:
    now = datetime(2026, 9, 6, 12, 0, 0, 123456, tzinfo=UTC)
    ts_us = int((now - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds()) * 1_000_000 + 123456
    decoded = codec.decode_json(format_line(DEVICE, {"a": 1.0}, ts_us=ts_us))
    assert decoded.timestamp == now


def test_arduino_golden_decodes_to_the_same_packet() -> None:
    assert codec.decode_json(ARDUINO_GOLDEN) == _expected_packet()


def test_python_and_arduino_goldens_are_byte_identical() -> None:
    assert format_line(DEVICE, VALUES, ts_us=TS_US, seq=SEQ, units=UNITS) == ARDUINO_GOLDEN


def _load_micropython_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("solus_telemetry_micropython", MICROPYTHON_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_micropython_emitter_matches_the_golden_under_cpython() -> None:
    upy = _load_micropython_module()
    assert upy.format_line(DEVICE, VALUES, ts_us=TS_US, seq=SEQ, units=UNITS) == ARDUINO_GOLDEN
    out: list[bytes] = []
    tx = upy.Emitter(DEVICE, out.append, clock_us=lambda: TS_US)
    assert tx.send(VALUES, UNITS) == 0
    assert codec.decode_json(out[0]) == _expected_packet()


def test_micropython_self_check_passes() -> None:
    result = subprocess.run(
        ["python3", str(MICROPYTHON_MODULE)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "self-check ok" in result.stdout


@pytest.mark.skipif(shutil.which("g++") is None, reason="needs a host C++ compiler")
def test_arduino_source_prints_the_golden(tmp_path: Path) -> None:
    binary = tmp_path / "host_check"
    subprocess.run(
        [
            "g++",
            "-std=c++11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(ARDUINO_DIR / "extras" / "host"),
            "-I",
            str(ARDUINO_DIR / "src"),
            str(ARDUINO_DIR / "extras" / "host" / "host_check.cpp"),
            str(ARDUINO_DIR / "src" / "SolusTelemetry.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout
    assert result.stdout == ARDUINO_GOLDEN


def test_library_bounds_mirror_the_solus_contract() -> None:
    assert SCHEMA_VERSION == packet.SCHEMA_VERSION
    assert MAX_DEVICE_ID_LEN == packet.MAX_DEVICE_ID_LEN
    assert MAX_SIGNALS == packet.MAX_SIGNALS_PER_PACKET
    assert MAX_SIGNAL_NAME_LEN == packet.MAX_SIGNAL_NAME_LEN
    assert MAX_UNIT_LEN == packet.MAX_UNIT_LEN
    assert MAX_SAFE_INT == packet.MAX_SAFE_INT
    assert MAX_LINE_BYTES == codec.MAX_PACKET_BYTES


def test_library_sources_carry_no_vendor_names() -> None:
    """The library is vendor-neutral by design (hardware-onboarding.md: vendors live in plugins)."""
    vendor = re.compile(r"\b(feetech|dynamixel|odrive|myactuator|mavlink)\b", re.IGNORECASE)
    sources = list((LIB_DIR / "python" / "src").rglob("*.py")) + [MICROPYTHON_MODULE]
    sources += list((ARDUINO_DIR / "src").iterdir())
    assert not [p.name for p in sources if vendor.search(p.read_text())]
