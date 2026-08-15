# Completion report — SOLUS-LB-04 Live detection testing (SOLUSDEV-124)

**Branch:** `SOLUSDEV-66-lane-telemetry` · **Status:** the drill harness is built and verified;
one fault class ran against REAL serial teardown (pyserial on a pty, master closed mid-stream —
the kernel form of an unplug). **The full physical-robot induction (hand-unplugging a sensor on
a running robot, reflashing a clashing rate) is NOT RUN** — no robot on this bench. The
repeatable protocol for that session is documented in `livebench/faults.py`'s docstring.

## What was built — `livebench/faults.py` + `lb_faults_test.py`

- `run_fault_drill(packets, fault_at, expected_device/signal, …)` — replays a stream with a
  known fault instant through the LB-02 observers + gap watchdog (event-time, deterministic,
  CI-replayable) and reports: `detected`, `latency_seconds`, `attribution_ok` (right device AND
  signal), `false_positives` (pre-fault events, counted for tuning), and `missed` — **a miss is
  returned as data, never hidden or fabricated** (pinned by a deliberate-miss test: a 30s
  watchdog against a 1s observation window reports `missed=True`, latency `None`).
- `sensor_disconnect_stream` — healthy stream goes silent at the fault; a heartbeat device
  keeps event-time advancing (as other sensors do on a real robot). Caught by the gap watchdog
  in ≤1.0s with correct attribution.
- `frequency_mismatch_stream` + the `__interval__` pseudo-signal — a sampling-rate clash IS a
  change-point in inter-arrival times; CUSUM on the derived interval catches 100→20 Hz in
  ≤1.5s with correct attribution.
- **Real-hardware case**: `test_real_serial_teardown_is_detected_end_to_end` streams through
  real pyserial and closes the link mid-stream — packets arrive, the teardown lands, the gap
  watchdog fires with `serial:<port>` attribution.

## Verification

181 livebench tests green (this ticket: 5). mypy strict + ruff clean. TDD RED→GREEN.

## For the physical session (humans)

Run the same drill against the robot port; induce by hand: (1) unplug one sensor —
gap watchdog, expect ≤2× its timeout; (2) reconfigure one sensor to a clashing rate —
interval CUSUM. Record `DrillReport.false_positives`/`missed` into the tuning notes; those
numbers are the deliverable, not embarrassments.
