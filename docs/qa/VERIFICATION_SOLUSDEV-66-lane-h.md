# LANE H — Branch verification (SOLUSDEV-66, 2026-08-10)

## Post-merge re-check (main → lane, merge `1bd6189`)

A human later merged `origin/main` into the lane (SOLUSDEV-102 altium, SOLUSDEV-114, further
SOLUSDEV-136 CTR-08 touch, billing/desktop, +3 Alembic migrations). Re-verified on the **merged**
HEAD — the merge did NOT mess with LANE H:

- **Statics**: `git diff 8ccc92d..HEAD` over every LANE H path (`livebench/`, `solus_api/livebench/`,
  `widgets/livebench/`, `features/bench/`, `main.py`) and over the contracts (`fingerprint/contract.py`,
  `graph/`, `packages/contracts/`) is **empty** — lane code and its CTR-08 dependency are byte-identical.
  Single Alembic head `a91b3c7e2d48` (the 3 merged migrations are billing-only). `livebench` workspace
  member + deps intact; `pyproject.toml` merged as a clean union; no stray conflict markers.
- **Suites on merged HEAD** (isolated `solus_test_verify`): livebench **191**, full API **1709 passed /
  3 skipped** (up from 1656 — main's billing/altium tests; the run proves the new migration head applies
  cleanly on a fresh DB, and `test_bench_router.py`/`test_persist.py` pass against merged contracts),
  desktop widgets **27**, `mypy -p livebench` + `ruff` + `typecheck:web` clean.

Verdict: **merge clean** — no LANE H regression.

---

Original verification pass on `SOLUSDEV-66-lane-telemetry` @ `58e958e` after the human wired real
credentials via `.env`. All DB work ran against the **isolated** `solus_test_verify` (never the
dev `solus_cadmcp`); the test harness's session-autouse `_schema` fixture overrides
`SOLUS_DATABASE_URL`, so the `.env`'s dev-DB URL cannot leak into tests.

## What ran

| Phase           | What                                                                                              | Result                             |
| --------------- | ------------------------------------------------------------------------------------------------- | ---------------------------------- |
| A — suites      | `livebench` pytest                                                                                | **191 passed**                     |
| A — suites      | full API pytest (isolated test DB)                                                                | **1656 passed, 3 skipped**         |
| A — suites      | desktop widget + recognition vitest                                                               | **27 passed**                      |
| A — static      | `mypy -p livebench` + changed API mypy; `ruff`; `typecheck:web`; eslint                           | **clean**                          |
| B — live API    | real uvicorn (`--factory`) booted against `solus_test_verify`, real HS256 JWT auth, seeded entity | **14/14 checks**                   |
| C — live bridge | CON-03 `FoxgloveClient` vs the real `ros-jazzy foxglove_bridge` binary                            | **handshake finding — see CON-03** |

### Phase B — live bench routes (real server, real auth, real Postgres)

Booting `solus-api` with the `.env` succeeded — `main.py`'s lifespan wired `TelemetryPlumbing`

- `BenchEventRing` and the bench router without error. Against the running server: ingest
  (`{accepted:2,unresolved:0,rejected:0}`) → recent (`rpm [100,200]`) → summary (1 W0-07 window,
  `rpm` present) → events round-trip; unresolved device dropped (not 500); **cross-tenant isolation
  holds with real JWTs** (bob → 404 on alice's recent/events/ingest; same `device_id` in bob's
  project → `accepted:0`, no bleed); unauthenticated → 401; and the hardening caps fire (413
  oversized body, 422 oversized `detail`, distinct-signal flood → `rejected:4`, batch>500 → 422).

### Phase C — live Foxglove bridge (finding, not a failure)

The bench now has `foxglove_bridge` **3.4.1** — the newer **Foxglove-SDK** bridge, which speaks
subprotocol **`foxglove.sdk.v1`**. CON-03 targets the ticket's **MIT** protocol
**`foxglove.websocket.v1`** (the classic `ros-foxglove-bridge` ≤0.x). So the client cannot
handshake with _this_ binary — and it fails **cleanly** (`InvalidStatus` HTTP 400, no hang/crash;
in production `FoxgloveLiveConnection._run` surfaces that as a disconnected pump per the review
hardening). CON-03's v1 protocol path IS verified live against a **real WebSocket server** — the
suite's mock-bridge test uses real sockets, real handshake, real advertise/message frames, and
ingests real packets end-to-end. **Follow-up for humans (flagged, not silently fixed):** to smoke
CON-03 against the installed bridge, either add `foxglove.sdk.v1` support (a distinct framing — a
product/scope decision) or install a classic `foxglove.websocket.v1` bridge. Hacking the client to
accept `sdk.v1` would misparse frames, so it was not done.

## Per-ticket acceptance map

Legend: **LIVE** = verified this pass against real services/binaries · **BUILT** = verified in-build
(unit/integration/real-pty/real-WS) · **BLOCKED** = needs a named install/hardware/merge.

| Ticket         | Acceptance                                                                                  | Status                                                                                                                                              |
| -------------- | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| **LB-06** 126  | packet schema + msgpack/JSON codec + TS decoder + versioning                                | **BUILT** (107 py + 56 ts; merged from LANE A). Propose close when SOLUSDEV-63 lands.                                                               |
| **CON-03** 105 | Foxglove WS subscribe → W0-07 windows via LiveConnection                                    | **BUILT** (v1 protocol vs real-socket mock; conformance suite). **Live vs installed bridge: BLOCKED** by the 3.4.1 `sdk.v1` protocol delta (above). |
|                | MCAP read + viz-out                                                                         | **BUILT** (fixture + round-trip).                                                                                                                   |
| **LB-01** 121  | MuJoCo start/stop/stream + graph mapping                                                    | **BUILT/real physics** (MuJoCo 3.11 in-venv; conformance-checked).                                                                                  |
|                | Gazebo · Isaac                                                                              | **BLOCKED** — `ros-gz` and Isaac Sim not installed (confirmed this pass). Isaac connector built over the MCAP path.                                 |
| **LB-02** 122  | robot connect + reconnect/backoff; threshold+CUSUM observers; events w/ context             | **BUILT/real** (real pty serial, real WS server, deterministic reconnect). Physical wifi-robot gate **BLOCKED** (no robot).                         |
| **LB-05** 125  | bench ingest/recent/summary/events; widget tiles/charts/markers/state; isolation            | **LIVE** (Phase B: real server + JWT + isolation + caps, 14/14). Widget: **BUILT** (27 vitest, honest states, remount-safe).                        |
| **RBT-01** 228 | USB VID/PID vs table (unknown→unknown); Dynamixel/CAN; stream shape; CTR-08 evidence        | **BUILT**; **CH343 live** honest-unknown case verified in-build. Dynamixel/CAN **BLOCKED** (no buses).                                              |
| **RBT-02** 229 | firmware idiom extraction w/ provenance; instance-can't-be-a-pattern                        | **BUILT** (tree-sitter cpp/micropython; symlink-traversal hardened). Emission half **BLOCKED** on the LANE-0 CTR-05 amendment.                      |
| **RBT-03** 230 | proposal table, no auto-accept, four tiers, tier-3 naming                                   | **BUILT** (13 vitest; four-tier fixtures).                                                                                                          |
| **LB-03** 123  | flash w/ progress + mid-flash UNKNOWN; fs r/w; post-deploy telemetry; **confirmation gate** | **BUILT** (scripted runners; gate + scp allowlist hardened). Real-device flash **BLOCKED** (needs sanctioned hardware).                             |
| **RBT-04** 231 | gated bounded motion → correlate; explicit NO-RESULT; cannot-tell                           | **BUILT** (synthetic incl. cannot-tell). Physical + live gate **BLOCKED** (no actuator; SOLUSDEV-60 unmerged).                                      |
| **RBT-05** 232 | persist via FP-02 seam, no parallel identity; reconnect recognition                         | **BUILT/real DB** (real FP-02 ingest; canonical-key normalization proven to converge, not fork).                                                    |
| **LB-04** 124  | induce faults; observers fire within latency w/ attribution; misses recorded                | **BUILT** incl. **real serial teardown**. Full-robot induction **BLOCKED** (no robot).                                                              |

## Verdict

Everything that can be verified without the still-missing installs/hardware **passes**, now
including the two biggest live gates this `.env` unlocked: the **bench routes end-to-end against a
real server** (LB-05) and the **CON-03 client against a real foxglove_bridge binary** (which surfaced
the `sdk.v1` protocol-version finding). No regressions. The only new action item is the CON-03
bridge-protocol delta; every other blocked gate is the same named install/hardware/merge already in
the lane completion report.
