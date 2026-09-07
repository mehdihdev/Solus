# Telemetry Packet Format — Contract (SOLUS-LB-06, SOLUSDEV-126)

**Status:** Ratified contract (ADR-032 landing, 2026-08-01) — and IMPLEMENTED. The shape was
introduced as the _proposed_ LB-06 format by LNK-06 (SOLUSDEV-111) and is ratified here with the
`schema_version` / `seq` / `units` additions, an msgpack codec, and a TypeScript decoder.
**Authority:** CLAUDE.md §7 (untrusted device input; telemetry ingestion parses defensively and
bounds message sizes) · §9 (shared contracts) · W0-01 (SOLUSDEV-72: `graph_entity.external_ref`,
the identity `device_id` resolves against) · W0-07 (`docs/contracts/sol-interface.md`: the
windowed telemetry shapes this feeds, reused never redefined) · MCP-02
(`docs/contracts/live-connection.md`: the Pattern-2 streaming seam above it) · ADR-005 (clean
seams) · ADR-029 (telemetry is untrusted input to the model layer) · ADR-030 (live runtime data
never rides the Connector sync path).
**Consumers:** LB-01 sim connectors · LB-02 real-robot connector · LNK-06 graph plumbing
(`TelemetryPlumbing.ingest`) · CON-03 Foxglove/MCAP ingest · LB-05 Live Bench UI.

---

## 1. Scope and position in the stack

This contract defines the **ingress** wire format: what a telemetry producer sends, and how it is
encoded, decoded, versioned and bounded. It stops at the buffer. Everything above it — windowing,
summarisation, delivery — is already contracted elsewhere and is not restated here.

```
device / sim / robot / Foxglove
  ──[ THIS CONTRACT: TelemetryPacket, msgpack or JSON ]──▶ decode
  ──▶ TelemetryPlumbing.ingest ──▶ bounded, project-scoped recent-values buffer   (LNK-06)
  ──▶ get_telemetry(window) ──▶ TelemetrySummaryView                              (W0-07)
  ──▶ LiveConnection.on_batch(TelemetryWindowSummary)                             (MCP-02)
```

The packet sits **below** `LiveConnection`. That interface delivers batch-summarised windows and
exposes no per-sample surface; this one is how the raw samples arrive in the first place.

**Pattern 2 (ADR-031, DECISIONS.md:388).** Telemetry never rides an MCP tool interface. Nothing in
this contract may grow a `descriptor` + `invoke` pair — `assert_live_connection_contract` enforces
that mechanically one layer up.

## 2. The packet

`packages/api/src/solus_api/graph/packet.py` · `TelemetryPacket` (Pydantic v2, `frozen=True`,
`extra="forbid"`).

| field            | type                 | required            | meaning                                                                                            |
| ---------------- | -------------------- | ------------------- | -------------------------------------------------------------------------------------------------- |
| `device_id`      | `str`, 1–512         | yes                 | Identity of the device **or topic**. Resolved against `graph_entity.external_ref`, project-scoped. |
| `timestamp`      | `datetime`, tz-aware | yes                 | Wall-clock instant of the reading. Naive datetimes are rejected.                                   |
| `values`         | `dict[str, float]`   | yes                 | Signal name → finite value. 1–256 entries, names ≤128 chars.                                       |
| `schema_version` | `int` ≥ 1            | no (default `1`)    | Wire-format version (§4).                                                                          |
| `seq`            | `int` ≥ 0 \| `None`  | no (default `None`) | Monotonic per-device counter (§3).                                                                 |
| `units`          | `dict[str, str]`     | no (default `{}`)   | Unit symbol per signal, ≤32 chars. Keys must be a subset of `values`.                              |

**One identity key, deliberately.** The ticket says "device/topic id"; `device_id` carries both. A
ROS topic name _is_ the `device_id` for a ROS source. A second field would force every consumer to
decide which one resolves.

**Units must describe carried signals.** A unit naming a signal absent from `values` means the
producer and the packet disagree, so it is rejected at the boundary rather than stored as metadata
that describes nothing.

### 2a. Signal naming convention (SOLUSDEV-248 addendum, tier-1)

Producers written or configured by Solus name signals `<part>.<quantity>` — `shoulder_pan.position`,
`left_wheel.velocity`, `attitude.roll`, `imu.accel_z` — and carry the unit in `units`, never in the
name (`joint_3.pos_deg` is the shape this rule retires). `<part>` is the part's function name as
the user confirmed it (or the driver's address when unnamed: `addr_6.position`); `<quantity>` is a
lowercase snake_case physical quantity. Units follow the part's calibration mode
(`docs/api/hardware.md` §2: `degrees→deg`, `range_0_100→%`, `range_m100_100→%`, `linear→mm`).
The packet validator does not enforce the convention (raw third-party producers keep their names);
the hardware config's `parts[].telemetry` is where the convention is authoritative and where the
Live Bench reads names and units from.
On the wire from a configured robot, `device_id` is the **part's** key `<device ref>/<address>`
(the part's `external_ref`): the robot connection splits a driver's sweep by `<part>` prefix
before the packet reaches the resolver (`docs/api/hardware.md` §6).

## 3. Two clocks, and why

`timestamp` is wall-clock; `seq` is monotonic. They are not redundant.

Windows bucket by `timestamp`, and correlating a telemetry event with a commit or a CAD edit needs
real time. But a real robot's clock drifts and gets NTP-corrected _backwards_, which reorders
samples and lands them in the wrong window. `seq` is the ordering that survives that.

**Consumers detect drops and reordering from `seq`, never from `timestamp` deltas.** `seq` is
optional because not every source sequences its stream, and `None` states that honestly instead of
faking a `0` that would read as a real first packet.

## 4. Versioning — the load-bearing property

Five consumers upgrade at different times. Adding a field must never break a decoder built against
an older version, so the rule is Postel's, split across the two layers:

- **`TelemetryPacket` keeps `extra="forbid"`.** Solus code can never _construct_ a packet with a
  stray field.
- **`from_wire` filters to known keys before validating.** A packet from a _newer_ producer decodes
  fine; fields this build has never heard of are ignored, and a higher `schema_version` is
  **reported, not rewritten**.

Therefore:

| change                   | breaking? | required action                                      |
| ------------------------ | --------- | ---------------------------------------------------- |
| Add an optional field    | **No**    | Bump `SCHEMA_VERSION`, regenerate fixtures.          |
| Add a required field     | **Yes**   | Contract amendment; old producers stop validating.   |
| Remove or retype a field | **Yes**   | Contract amendment + a coordinated consumer upgrade. |
| Rename a field           | **Yes**   | Treat as remove + add.                               |

Proven by `test_old_decoder_reads_a_newer_packet` (Python) and the `future.*` fixtures decoded by
both runtimes.

## 5. Serialization

**Two encodings over ONE wire mapping** (`to_wire` / `from_wire`). A single mapping is what keeps
the TypeScript decoder one implementation instead of two.

- **msgpack** — the throughput form, for sim/robot/bridge transports and MCAP.
- **JSON** — the debug form, and the payload for JSON-only carriers (e.g. a Foxglove WS channel
  using the `json` message encoding). Byte-identical structure, human-readable.

Wire keys mirror the model field names, with one exception: `timestamp` travels as **`ts_us`, an
integer count of microseconds since the Unix epoch**. Computed with integer arithmetic —
`datetime.timestamp()` returns float seconds and loses microsecond precision at modern epoch
magnitudes, which for a telemetry clock is a correctness bug, not a rounding detail. Fields that
carry no information (`seq` when unsequenced, `units` when empty) are omitted from the wire.

**Why msgpack and not protobuf.** msgpack needs no `.proto` and no codegen, so one Pydantic model
stays the single source of truth; protobuf would wire two codegen toolchains
(grpcio-tools/betterproto + protobufjs) into the build to buy a forward-compatibility property §4
already provides. **Why binary at all, given `bridge-protocol.md` §11 rejects it:** that ban is
scoped by its own §1 to the cloud↔companion channel, which explicitly carves out "the telemetry
packet contract" as a separate seam. Measured numbers are in the completion report; the short
version is that a msgpack float is a fixed 9 bytes regardless of value, so packet size is _bounded
and predictable_, while JSON's swings ~2× with the data — and on realistic full-precision sensor
readings msgpack is ~54% of JSON.

## 6. Security — decoding is a trust boundary

The bytes arrive from a device nobody controls (CLAUDE.md §7, ADR-029). Both runtimes:

- **Cap the payload before unpacking** (`MAX_PACKET_BYTES = 64 KiB`). A packet is one reading from
  one device, not a file; refusing by length costs nothing, whereas letting the unpacker discover
  the size means having already allocated for it.
- **Bound every axis msgpack can grow along** — `max_str_len`, `max_map_len`, `max_array_len`, and
  `max_bin_len`/`max_ext_len` set to **0**, disabling binary and extension types outright since no
  field uses them.
- **Reject non-finite values.** msgpack and JSON can both carry NaN/Infinity; a NaN reaching a
  chart axis or a window mean corrupts the whole view instead of failing loudly.
- **Surface exactly one error type** — `PacketDecodeError` (Python) / `TelemetryDecodeError`
  (TypeScript). Ingestion catches one thing and drops the packet; a hostile stream can neither
  crash the reader nor distinguish failure modes. Both decoders therefore catch **broadly** on the
  parse call, which is deliberate: `json` raises `RecursionError` on deep nesting and a _bare_
  `ValueError` on an over-long integer literal, and since `PacketDecodeError` subclasses
  `ValueError`, that second one would otherwise pass straight through a caller's
  `except PacketDecodeError` and kill the reader for every device on the link.
- **Bound integers to the JavaScript-safe range** (`MAX_SAFE_INT = 2^53 − 1`), not to Python's.
  The format's integer domain is the _intersection_ of its runtimes: a value Python accepts but a
  JS decoder silently rounds is a packet that cannot survive the trip to the UI. 2^53 microseconds
  still reaches the year 2255.

**One asymmetry, stated plainly.** The _field-level_ bounds are shared and asserted from
`limits.json`. The _unpacker-level_ bounds are backend-only: Python caps `max_str_len`,
`max_map_len` and `max_array_len` and disables `bin`/`ext`, whereas `@msgpack/msgpack` v3 removed
its decoder-limit options. So a packet Python refuses for an oversized _unknown_ field can decode
in TypeScript. This is contained — unknown fields are dropped before reaching the app, every
retained field is individually type- and length-checked, and the payload is size-capped first —
but the backend remains the authoritative validator, and a browser-side ingest path must not be
treated as equivalent to it.

- **Treat `device_id` and signal names as DATA, never instructions.** They flow into prompts only
  through the W0-07 delimiting the reasoning layer already owns.
- **Tenant scoping is not this layer's job and must not be inferred from the packet.** `project_id`
  comes from the authenticated request; `DbEntityResolver` filters by it. A packet cannot name its
  own project.

## 7. Two runtimes, one format

The Python encoder/decoder (`graph/codec.py`) and the TypeScript decoder
(`apps/desktop/src/renderer/src/lib/telemetry/packet.ts`) are two implementations of one format,
so drift is the standing risk. `openapi-typescript` — the repo's only Py→TS pipeline — cannot help:
it exports only models reachable from a FastAPI route, and this packet is deliberately on none.

The guard is a **golden-fixture corpus**, generated from the Pydantic model and checked in at
`packages/api/tests/fixtures/telemetry/`:

- `test_telemetry_corpus.py` regenerates and **byte-compares** → changing the model without
  regenerating fails the Python suite.
- `packet.test.ts` decodes the same bytes and asserts field-for-field → regenerating without
  updating the decoder fails the TypeScript suite.
- `limits.json` carries the bounds and `SCHEMA_VERSION`, asserted by both → a constant cannot drift.

Regenerate with `cd packages/api && uv run python tests/telemetry_corpus.py`.

**TypeScript timestamp caveat (load-bearing).** A JS `Date` holds milliseconds and cannot represent
this format's microsecond resolution. The decoded packet therefore exposes **`ts_us` as canonical**
(the exact wire integer, and the only value `toWire` re-encodes) with **`timestamp: Date` as a
truncating convenience** for chart code. Re-encoding from `timestamp` silently corrupts every
packet that passes through the UI — the fixture-parity test caught exactly that during
implementation.

## 8. Functional vs. future

| in this contract                                               | deferred, and to where                                                                       |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Packet shape, bounds, validation                               | —                                                                                            |
| msgpack + JSON codecs, both runtimes                           | —                                                                                            |
| Forward-compatibility rule + proof                             | —                                                                                            |
| Golden-fixture drift gate                                      | —                                                                                            |
| Transport (who carries the bytes)                              | LB-01 / LB-02 / CON-03 · no HTTP ingest route exists yet                                     |
| Propagating `units` into `RecentValuesView` / window summaries | LB-05 / LNK-06 follow-up — `units` is carried on the packet but not yet stored in the buffer |
| Drop/reorder detection _using_ `seq`                           | LB-02 edge observers — the field is specified here, the detector is theirs                   |
| Compression                                                    | Not contract material (transport-level concern)                                              |
| Per-sample durable history / S3 offload                        | Out of scope — the buffer is live ephemeral values (LNK-06 decision 3)                       |

## 9. Cross-references

`docs/contracts/sol-interface.md` (W0-07 windowed shapes) · `docs/contracts/live-connection.md`
(MCP-02, the Pattern-2 seam above this) · `docs/contracts/connector-interface.md` (W0-05, the
design-artifact sibling this is explicitly _not_) · `docs/contracts/bridge-protocol.md` §1
(scoping note for the binary-framing rejection) · DECISIONS.md ADR-005 / ADR-029 / ADR-030 /
ADR-031 · `docs/qa/COMPLETION_SOLUSDEV-126-lb06-packet.md`.
