# Completion report — SOLUS-CON-03 Foxglove / MCAP telemetry ingest (SOLUSDEV-105)

**Branch:** `SOLUSDEV-66-lane-telemetry` · **Status:** built and verified against fixtures + a
mock bridge; live `foxglove_bridge` smoke pending the human's ROS package install.

## What was built

`livebench/src/livebench/telemetry/` (new `solus-livebench` workspace member):

| Module               | Job                                                                                                                                                                                                                                                                                                                                                     |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `normalize.py`       | JSON message payloads → LB-06 `TelemetryPacket`. Native LB-06 wire payloads (marked by `ts_us`) decode losslessly via the ratified codec; anything else flattens numeric leaves (dot paths, depth ≤ 8, bool excluded, non-finite dropped, deterministic 256-signal truncation). Size-capped before parsing; every failure returns `None`, never raises. |
| `mcap_ingest.py`     | MCAP stream → packets, json channels only, log-time order, topic filter pushed into the reader. Per-message failures skipped; a corrupt file fails loudly at open.                                                                                                                                                                                      |
| `mcap_export.py`     | Packets → Foxglove-consumable MCAP (viz-out), one json channel per `device_id`, LB-06 wire payloads. Round-trip tested.                                                                                                                                                                                                                                 |
| `foxglove_client.py` | Subscribe-only `foxglove.websocket.v1` client on the already-installed `websockets` — parses `advertise`, subscribes to json channels (incremental advertise batches handled), surfaces binary MESSAGE_DATA frames. Frame-size capped; unknown ops/frames ignored.                                                                                      |
| `foxglove_live.py`   | `FoxgloveLiveConnection(LiveConnection)`, `provider="foxglove"`: per-subscription event-time windowing → `TelemetryWindowSummary` delivery. Passes `assert_live_connection_contract`. `for_url("ws://robot:8765")` is the production constructor.                                                                                                       |
| `windowing.py`       | Event-time `WindowAggregator`: anchored windows, LNK-06-shaped stats (`mean/min/max/last/count`), closed-window watermark (late stragglers dropped, open-window reorders re-anchor), deterministic summary text. No wall clock.                                                                                                                         |

## Acceptance vs. delivered

- **Subscribe to a foxglove_bridge WS + read MCAP; telemetry lands in the W0-07 windowed shape
  via LiveConnection** — ✅ built; WS side verified against an in-test mock bridge speaking the
  real protocol (subprotocol negotiation, advertise/subscribe, binary frames); MCAP side verified
  against generated fixtures. Conformance suite green.
- **Viz-out path documented** — ✅ `docs/architecture/telemetry-viz-out.md` + tested exporter.
- **Sample robot / MCAP test** — MCAP: ✅ fixtures. **Live robot bridge: NOT RUN** —
  `foxglove_bridge` is not installed (human installing `ros-jazzy-foxglove-bridge`); the live
  smoke happens then. No live gate is claimed.
- **Pattern 2** — no MCP import anywhere in `livebench/`; the conformance suite's not-a-Tool
  check runs in CI with the tests.

## Verification

74 CON-03 tests in `livebench/tests/` (normalize 23, windowing 15, MCAP 11, WS client 10,
live connection 14, conformance 1), all green. `mypy -p livebench` strict: clean.
`ruff check livebench/`: clean. TDD followed: RED commit → implementation → GREEN, then a
review-driven hardening RED→GREEN cycle.

## Review cycle (Phase 4 run per-ticket; findings FIXED, not noted)

A fresh-context code review and a §7 security review both ran against the initial GREEN diff and
correctly **falsified** this report's first draft ("one hostile message can drop itself, never the
stream" was untrue). All findings were fixed with regression tests before this commit:

- **C1/CRITICAL (both reviews)**: `{"": 1.5}` or a 400-digit int killed the pump/MCAP generator.
  → leaf-level guards + a guarded packet construction; hostile-payload corpus test.
- **C2**: MCAP decompression-bomb exposure (measured 32,722:1). → seekable-stream requirement,
  input size cap, `record_size_limit`; the residual chunk-amplification ceiling is a documented
  mcap-library limitation — untrusted files must be ingested in a memory-capped worker.
- **C3**: unbounded window state under novel signal names / frozen timestamps. →
  `MAX_SIGNALS_PER_WINDOW` (1024), `MAX_SAMPLES_PER_WINDOW` forced flush, duration bounds.
- **C4**: advertise flood grew client state ~20 MB/s. → `MAX_CHANNELS` (4096), topic/id bounds,
  counter-based subscription ids.
- **H (identity)**: an LB-06 payload on topic A could assert itself as entity B (graph identity
  spoofing). → `device_id` must equal the transport topic or the message drops.
- **H (teardown)**: unsubscribe/aclose silently discarded the pending partial window. → flushed
  to the callback before removal.
- **H (windowing)**: backward re-anchor could emit a window excluding its own samples. →
  watermark + max-ts guard; a straggler that can't coexist is dropped.
- **H (supervision)**: a dead pump reported `CONNECTED` forever. → status drops to
  `DISCONNECTED` on pump exit, `subscribe` restarts a done pump, exception class logged
  (never the URI).
- **M**: `RecursionError` on deep-nested control frames; frame-cap rationale (512 KiB, tied to
  a full advertise); `for_url` scheme allow-list + in-URL credential rejection; `frozenset`
  signal filter; export channel cap; log truncation for untrusted topics.
- **H3 (tenant)**: `project_id: UUID | None` slot added to the connection. The route that serves
  it (LB-05) MUST bind a real project and ship the §7 isolation tests — flagged there.

Tier-2 proposal for the human (NOT edited): `TelemetryWindow.duration_seconds` accepts
`float("inf")` (`gt=0` only) — propose adding `le=86_400` in `agent/interfaces.py` (W0-07,
frozen). The aggregator clamps locally in the meantime.

## Delegated judgments

1. **No vendor SDK / no new WS dependency** — the subscribe-only client is ~90 lines over the
   `websockets` already shipped with the API stack; the Foxglove SDK would add a dependency for
   one direction we don't use.
2. **json channels only** — decoding protobuf/cdr/flatbuffer channels means shipping their schema
   toolchains, the exact weight the LB-06 contract rejected. ROS 2 users reach us via
   `foxglove_bridge`'s json encoding or rosbag2's MCAP.
3. **Trust boundary at normalize** — topic/payload bounds mirror the LB-06 codec's; one hostile
   message can drop itself, never the stream.
4. **`livebench` is a new uv workspace member** (src layout, `py.typed`) so mcap/websockets — and
   the coming mujoco/pyserial — never become API-service dependencies. Root `pyproject.toml`
   members list updated (the file's own "add as created" instruction); mypy got an `mcap.*`
   follow-imports skip (its layout double-maps module names and aborts strict runs).

## Deviations / notes for review

- Ticket path `backend/app/livebench/` translated per `docs/WORKTREES.md` §4.
- Test files use the `lb_<module>_test.py` suffix convention — satisfies the H9 TDD matcher while
  avoiding basename collisions with `packages/api/tests/` in root-level pytest collection.
- The LNK-06 buffer path (`TelemetryPlumbing.ingest`) is deliberately NOT wired here: transport →
  ingest → UI wiring is LB-05's route work. This ticket delivers the sources.
