"""The LB-06 golden-fixture corpus — one definition, two runtimes (SOLUSDEV-126).

The packet format has a Python encoder and a TypeScript decoder, and nothing mechanically stops
them drifting: `openapi-typescript` (the repo's only Py→TS pipeline) can only export models that
are reachable from a FastAPI route, and this packet is deliberately on no route.

So the corpus below is the shared source of truth. It is generated FROM the Pydantic model and
checked in, then:

  * `test_codec_fixtures.py` regenerates and byte-compares  → changing the model without
    regenerating fails the PYTHON suite.
  * `lib/telemetry/packet.test.ts` decodes the same bytes   → regenerating without updating the
    decoder fails the TYPESCRIPT suite.

`limits.json` does the same job for the bounds and the schema version, so a constant can't drift
between the runtimes either.

Regenerate with:

    cd packages/api && uv run python tests/telemetry_corpus.py
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import msgpack
from solus_api.graph.codec import encode, encode_json, to_wire
from solus_api.graph.packet import (
    MAX_DEVICE_ID_LEN,
    MAX_SIGNAL_NAME_LEN,
    MAX_SIGNALS_PER_PACKET,
    MAX_UNIT_LEN,
    SCHEMA_VERSION,
    TelemetryPacket,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "telemetry"

# Fixed instants — a fixture corpus must be byte-identical on every machine and every run.
_T0 = datetime(2026, 7, 5, 12, 0, 0, 123456, tzinfo=UTC)
_T1 = datetime(2026, 7, 5, 12, 0, 0, 654321, tzinfo=UTC)

#: Every case the two runtimes must agree on.
CORPUS: dict[str, TelemetryPacket] = {
    # The floor: required fields only, no seq, no units.
    "minimal": TelemetryPacket(device_id="imu0", timestamp=_T0, values={"x": 1.0}),
    # The everyday case: a sequenced, unit-labelled multi-signal reading.
    "full": TelemetryPacket(
        device_id="/robot/imu0",
        timestamp=_T0,
        seq=42,
        values={"accel_x": 0.125, "temp_c": 31.5, "rpm": 1200.0},
        units={"accel_x": "m/s^2", "temp_c": "degC", "rpm": "rev/min"},
    ),
    # A realistic robot bus: many signals at full float precision (the size case that matters).
    "wide": TelemetryPacket(
        device_id="/robot/joints",
        timestamp=_T1,
        seq=1_000_000,
        values={f"tau_{i}": i * 1.5 + 0.123456789012345 for i in range(12)},
        units={f"tau_{i}": "N*m" for i in range(12)},
    ),
    # Edges a decoder gets wrong: negative, zero, tiny, huge, and the identity-key maximum.
    "extremes": TelemetryPacket(
        device_id="d" * MAX_DEVICE_ID_LEN,
        timestamp=datetime(1970, 1, 1, tzinfo=UTC),
        seq=0,
        values={"neg": -273.15, "zero": 0.0, "tiny": 1e-300, "huge": 1e300},
    ),
}

#: A packet from a FUTURE producer: higher schema_version plus fields this build has never heard
#: of. Both runtimes must decode it and ignore the surplus — the whole point of the format.
FUTURE_EXTRAS: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION + 1,
    "quality": "degraded",
    "calibration": {"offset": 0.01, "gain": 1.02},
}

#: Payloads BOTH runtimes must REJECT.
#:
#: The happy-path corpus proves the two decoders agree about valid packets. It cannot catch the
#: drift that actually bit us — cases Python rejects and TypeScript quietly accepted (units named
#: `toString` sailing past an `in` check; `ts_us: 1e300` passing `Number.isInteger` and becoming
#: an `Invalid Date`). These are msgpack-only because msgpack can carry things JSON cannot,
#: notably NaN and Infinity.
HOSTILE: dict[str, dict[str, Any]] = {
    "nan_value": {"device_id": "d", "ts_us": 1, "values": {"x": float("nan")}},
    "inf_value": {"device_id": "d", "ts_us": 1, "values": {"x": float("inf")}},
    "missing_ts": {"device_id": "d", "values": {"x": 1.0}},
    "string_ts": {"device_id": "d", "ts_us": "yesterday", "values": {"x": 1.0}},
    "bool_ts": {"device_id": "d", "ts_us": True, "values": {"x": 1.0}},
    "float_ts": {"device_id": "d", "ts_us": 1e300, "values": {"x": 1.0}},
    "unsafe_ts": {"device_id": "d", "ts_us": 2**53 + 1, "values": {"x": 1.0}},
    "empty_values": {"device_id": "d", "ts_us": 1, "values": {}},
    "not_a_map": {"device_id": "d", "ts_us": 1, "values": "everything is fine"},
    "empty_device_id": {"device_id": "", "ts_us": 1, "values": {"x": 1.0}},
    "long_device_id": {
        "device_id": "d" * (MAX_DEVICE_ID_LEN + 1),
        "ts_us": 1,
        "values": {"x": 1.0},
    },
    "too_many_signals": {
        "device_id": "d",
        "ts_us": 1,
        "values": {f"s{i}": 1.0 for i in range(MAX_SIGNALS_PER_PACKET + 1)},
    },
    "long_signal_name": {"device_id": "d", "ts_us": 1, "values": {"s" * 129: 1.0}},
    "negative_seq": {"device_id": "d", "ts_us": 1, "seq": -1, "values": {"x": 1.0}},
    "huge_seq": {"device_id": "d", "ts_us": 1, "seq": 2**63, "values": {"x": 1.0}},
    "float_seq": {"device_id": "d", "ts_us": 1, "seq": 1e300, "values": {"x": 1.0}},
    "unit_for_absent_signal": {
        "device_id": "d",
        "ts_us": 1,
        "values": {"x": 1.0},
        "units": {"nonexistent": "m/s"},
    },
    # The prototype-chain case: `'toString' in {}` is true in JS, so this bypassed the TS check
    # entirely and produced an object whose `toString` was a string, crashing any consumer that
    # coerced it. Python always rejected it.
    "unit_named_tostring": {
        "device_id": "d",
        "ts_us": 1,
        "values": {"x": 1.0},
        "units": {"toString": "m/s"},
    },
    "long_unit": {
        "device_id": "d",
        "ts_us": 1,
        "values": {"x": 1.0},
        "units": {"x": "u" * (MAX_UNIT_LEN + 1)},
    },
    "zero_schema_version": {
        "device_id": "d",
        "ts_us": 1,
        "schema_version": 0,
        "values": {"x": 1.0},
    },
}

#: Bounds shared by both runtimes; the TS suite asserts its constants against this file.
LIMITS: dict[str, int] = {
    "SCHEMA_VERSION": SCHEMA_VERSION,
    "MAX_DEVICE_ID_LEN": MAX_DEVICE_ID_LEN,
    "MAX_SIGNALS_PER_PACKET": MAX_SIGNALS_PER_PACKET,
    "MAX_SIGNAL_NAME_LEN": MAX_SIGNAL_NAME_LEN,
    "MAX_UNIT_LEN": MAX_UNIT_LEN,
}


def build_files() -> dict[str, bytes]:
    """Every fixture file as {relative name: bytes}. Pure — the writer and the drift test both
    call this, so they cannot disagree about what the corpus should contain."""
    files: dict[str, bytes] = {}
    for name, packet in CORPUS.items():
        files[f"{name}.msgpack"] = encode(packet)
        files[f"{name}.json"] = (encode_json(packet) + "\n").encode()

    future_wire = to_wire(CORPUS["full"]) | FUTURE_EXTRAS
    files["future.msgpack"] = msgpack.packb(future_wire, use_bin_type=True)
    files["future.json"] = (
        json.dumps(future_wire, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()

    for name, hostile in HOSTILE.items():
        files[f"hostile.{name}.msgpack"] = msgpack.packb(hostile, use_bin_type=True)
    # An index so the TypeScript suite can iterate the same set without hardcoding the names.
    files["hostile_index.json"] = (json.dumps(sorted(HOSTILE), indent=2) + "\n").encode()

    files["limits.json"] = (json.dumps(LIMITS, indent=2, sort_keys=True) + "\n").encode()
    return files


def write_files(directory: Path = FIXTURE_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, blob in build_files().items():
        (directory / name).write_bytes(blob)


if __name__ == "__main__":
    write_files()
    print(f"wrote {len(build_files())} fixture files to {FIXTURE_DIR}")
