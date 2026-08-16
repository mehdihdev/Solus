# Completion report — SOLUSDEV-72: Local connections surface

Branch `SOLUSDEV-72-fix-local-connections`, built 2026-08-16. One new surface plus one catalog
fix, exactly as the spec's root-cause read: Pattern-2 local streams got a server-side lifecycle
and a UI; bridge-hosted tools got a generic tile mode. Telemetry stayed Pattern 2 throughout —
no MCP anywhere near a stream.

## Governing docs

DECISIONS.md ADR-014/030 (boundary clause)/031 §2 (conformance-enforced)/025/032;
`docs/contracts/live-connection.md`; `docs/api/API.md` §2.10 (planned sessions routes —
implemented subset; tier-1 amendments in §2.5/§2.10 and `API-implementation.md` §15b);
architecture + wireflow rungs were EMPTY for this feature — `docs/architecture/local-connections.md`
and `docs/wireflows/local-connections.md` written as tier-1 deliverables in this MR.

## What was built

**livebench**: `PacketStreamLiveConnection.tap` (per-packet tee at the pump choke point; a
failing tap never kills the pump; conformance holds); `ReconnectingSource` factory off-loop;
`livebench/local.py` (probe-only availability — never imports mujoco to answer a listing;
serial identity keyed by USB serial resolved to `/dev/serial/by-id`; ambiguity refuses with
candidates; lazy factories, MuJoCo realtime-forced with bounded duration, MJCF file-reference
denylist with sanitized compile errors); `sim/isaac_direct.py` (ROS-free live-Isaac script,
stdlib-only under Isaac's python, token via env, loopback-pinned plaintext).

**API**: `SessionManager` (in-memory project-keyed; synchronous cap reserve and synchronous
end-bookkeeping — concurrent stops tear down exactly once; dead-pump sweep frees cap slots;
lifespan teardown); routes `GET /bench/sources`, `POST/GET /bench/sessions[/{id}][/stop]`,
`GET /bench/device-recent` (batched, 1–16 ids per request); unresolved-device ring in
`TelemetryPlumbing` (16 devices × 16 signals × 256 samples per project, drop-new; cleared when
a device resolves); `CachingEntityResolver` (positive-TTL only); `GET /api/v1/integrations/local-tools`;
`Settings.bench_data_root` confines MCAP reads. Events: `bench.session_started/stopped`.

**Desktop**: Local Connections section in the Sources screen (simulators/devices/bridge tools,
honest states, disabled-with-reason controls); device rows with serial-keyed labels persisted
locally and the explicit-pick flow for ambiguous devices; `local-bridge` ConnectMode with tiles
derived entirely from the backend registry (next tool = backend entry, zero frontend edits);
BenchScreen device-keyed view (batched 2.5 s poll, ≤8 panels + honest overflow line) and an
actionable empty state.

## Verification

- TDD throughout. Suites: backend 2273 + livebench 211 (+ new tests) all passing, run in 3
  slices (H10's 600 s timeout vs the ~10 min suite); desktop 156 files / 1280 tests; ruff
  clean; `mypy` clean over 202 backend files (fresh cache); desktop typecheck clean; alembic
  single head `07c4da2feccf` (no migration — session state is deliberately ephemeral).
- **Phase 4**: 4 persona reviewers + 2 adversarial skeptics per finding (36 agents). 11
  findings confirmed (incl. a repro-confirmed stop() race, a ~1 GB ring-growth bound, an MJCF
  arbitrary-read oracle, and a self-inflicted 429 from per-device polling) — ALL FIXED and
  re-tested; 5 findings refuted by the skeptics.
- **Run, not just tested**: live API + real renderer over CDP. `GET /sources` returned the
  honest machine truth (MuJoCo available; Gazebo "not installed" and unstartable in the UI;
  Isaac detected with direct-script/MCAP guidance; the real CH343 with serial `5B42135040`,
  "MCU unknown", 0.3). A UI-started MuJoCo session streamed real physics (~50 Hz realtime,
  `qvel` oscillating) into Live Bench's device-keyed panel WITH NO FOCUSED ENTITY; stop
  idempotent; cross-tenant 404 on every new route with a fresh outsider JWT; 401 unauth.
- **ROS 2 bridge probe (user-mandated)**: headless Isaac with `isaacsim.ros2.bridge-5.1.2`
  enabled on a stepping world published ZERO topics without per-scene OmniGraph authoring —
  verdict: not cheap. The direct script is the live-Isaac path; no `ros2-topic` source built.

## Not verified here (human-assisted, flagged in COWORK_QA)

- The two-identical-arms replug test: only ONE arm was physically connected this session.
  Binding logic is fully unit-tested (serial-keyed resolution, ambiguity refusal, explicit-pick,
  port-swap survival) — the physical pass needs both arms plugged in (§6 of the QA file).
- Isaac direct script against a real articulated scene (§8), and a real `.mcap` replay (none
  exists on this machine yet).
- A real serial LB-06 stream from the arm (the CH343 fronts an MCU that isn't emitting yet).

## Deviations & delegated-judgment decisions

- **Topology caveat (flagged, by design)**: session pumps run in the API process — correct for
  today's dev topology (API on the user's machine), not for cloud. The seam (runtime-optional
  `livebench.local` + the routes) is cut so a companion-hosted runner swaps in without route
  changes; recorded in `docs/architecture/local-connections.md`.
- Fusion was NOT the `modeFor()` bug class — it was never a connector. The generic fix derives
  `local-bridge` tiles from the ADR-031 MCP catalog via `GET /integrations/local-tools`.
- `device-recent` became batched (repeated `device_id`) during Phase 4 to keep N device panels
  at one request per cycle under the shared rate budget.
- Broad `except Exception → 503 source_unavailable` on session start is deliberate (§7: device
  input must never crash the route); the cause is logged. A reviewer flagged it; skeptics
  refuted the concern.
- Rate-limit `path_limits` is exact-path only, so no dedicated bench bucket was added; the
  batched poll keeps bench polling well inside the default budget.
- H12 process note: the desktop subagent's stop-gate collided twice with the orchestrator's
  concurrently-uncommitted backend files (its own diff was clean). Commit boundaries in this
  branch's history reflect that interleaving — two early desktop-file sweeps landed inside
  backend-labelled commits; the tree state is correct and fully tested.

## Human-owed

- Plug in both LeRobot arms and run COWORK_QA §6 (the safety property's physical pass).
- Optionally set `SOLUS_BENCH_DATA_ROOT` to enable MCAP replay, and record an Isaac `.mcap`.
- Review the integrated branch, push, open the MR (no push/MR performed, per ADR-021).
