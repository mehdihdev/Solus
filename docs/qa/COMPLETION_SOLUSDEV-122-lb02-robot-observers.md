# Completion report — SOLUS-LB-02 Real robot connection + edge observers (SOLUSDEV-122)

**Branch:** `SOLUSDEV-66-lane-telemetry` · **Status:** built and verified on real serial (pty) and
real WebSocket links; the physical-robot gate is honestly unverified (no robot on the bench).

## What was built

**Edge observers** (`livebench/anomaly/observers.py`) — pure Python, bounded state, close to the
data (pre-windowing):

- `ThresholdObserver` — median-smoothed (spike-robust) bounds; fires on ENTERING a breach,
  re-arms on recovery — one event per excursion, never per sample.
- `CusumObserver` — two-sided CUSUM in σ units; learns a baseline, fires `change_point` with
  direction, then **re-learns from the new regime** so the next shift is judged against it.
  Zero-variance baselines floored, never a crash.
- `GapWatchdog` — (device, signal) silence detection with injectable clock (`tick(now)`); one
  event per gap, re-arms on resumption. This is LB-04's sensor-disconnect detector.
- `ObserverEvent` carries kind, device_id, signal, timestamp, value, and detector detail —
  attribution is the point (an anomaly without it is noise to the error path).

**Transports** (`livebench/telemetry/`):

- `serial_source.py` — newline-delimited LB-06 JSON over pyserial (blocking reads in a worker
  thread); over-long lines discarded to the next newline, junk lines cost themselves only.
  **Verified over a real pty pair through real pyserial** — LB-06 lines keep the firmware's own
  `device_id` (`trusted_identity=True`: one wire, one claimant — documented in `normalize.py`,
  bridged transports keep the spoofing guard).
- `ws_source.py` — a robot's own WebSocket pushing LB-06 msgpack (throughput) / JSON (debug)
  frames; ws/wss only, no in-URL credentials, frames capped, undecodable frames dropped.
- `reconnect.py` — `ReconnectingSource`: exponential backoff (0.5s→30s cap), reset on a live
  packet, every dead incarnation closed; injectable sleeper, schedule proven deterministically.
- `observing_source.py` — observers ride the stream; packets pass through untouched; a broken
  event sink is logged, never fatal. Event sink is the seam ERR-01 / LB-05 markers consume.
- `robot.py` — `SerialRobotConnection` (provider `serial`) and `WsRobotConnection`
  (provider `robot-ws`): transport → reconnect → observers → windowing, composed in that order
  (observers see the healed stream). Fail-fast open; stable `/dev/serial/by-id` paths advised.

## Acceptance vs. delivered

- Connect + stream reliably, reconnect/backoff on link loss: ✅ built; reconnection schedule and
  cleanup proven with deterministic fakes; live WS end-to-end test (real server, real frames,
  windows + observer event delivered) green.
- Threshold + change-point observers on configured signals: ✅ with event-shape note below.
- Observer events into telemetry/error path with signal + context: ✅ `ObserverEvent` via the
  `on_event` sink. **Note:** ERR-01 (the error store) is another lane's unbuilt path — the sink
  is the agreed seam, and wiring into the error pipeline happens when ERR-01 exists.
- **"Verified on a physical robot streaming live": NOT RUN** — no wifi robot exists on this
  bench (audited). What physically exists (CH343 serial bridge) gets its real-port exercise in
  RBT-01's stream characterization and LB-04's unplug test. Not claimed here.

## Verification

122 tests total in `livebench/tests/`, all green (this ticket: observers 15, reconnect 4,
serial 2 — real pty, ws 2 — real server, observing 2, robot composition 3). `mypy -p livebench`
strict clean (21 files) — one `warn_unreachable` false-positive on cross-task flag flips
defeated with a predicate method. `ruff` clean. TDD: RED commits precede GREEN throughout.

## Delegated judgments

1. Serial framing is newline-delimited LB-06 JSON (self-synchronizing, debuggable); msgpack
   stays the WS/MCAP throughput form. A length-prefixed serial framing can be added later
   without contract change (it's transport, not packet).
2. `seq`-based drop detection (deferred here by the LB-06 contract §8) remains open — the
   `GapWatchdog` covers silence; per-`seq` gap counting belongs with the LB-04 tuning data.
3. No numpy: detectors are incremental accumulators over bounded windows; at 512-sample scale
   the dependency buys nothing.
