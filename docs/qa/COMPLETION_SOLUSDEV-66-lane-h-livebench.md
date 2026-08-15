# LANE H completion report — Streaming Telemetry & Live Bench (SOLUSDEV-66)

**Branch:** `SOLUSDEV-66-lane-telemetry` (renamed from `-live-bench-telemetry` to match CODEOWNERS).
**Pattern 2 throughout** — telemetry is a streaming `LiveConnection`, never an MCP tool; the
conformance suite enforces it mechanically and runs in CI with every live source.

## Tickets

| Ticket                    | Key | Outcome                                                                                                                                                          |
| ------------------------- | --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LB-06 packet              | 126 | Merged LANE A's ratified msgpack/JSON implementation into the lane; verified (107 py + 56 ts). Propose closing when SOLUSDEV-63 lands.                           |
| CON-03 Foxglove/MCAP      | 105 | Built + review-hardened. FoxgloveLiveConnection (WS), MCAP in/out, viz-out doc. Live bridge smoke pending `foxglove_bridge` install.                             |
| LB-01 sim                 | 121 | MuJoCo **verified on real physics**; Gazebo + Isaac (MCAP path) fixture-verified. **Open until Isaac live smoke runs** (Isaac not installed — human installing). |
| LB-02 robot + observers   | 122 | Built; verified on real pty serial + real WS server. Physical-robot gate reported unverified (no robot).                                                         |
| RBT-01 passive id         | 228 | Built; **live CH343 enumeration verified** (honest "MCU unknown"); DXL/CAN protocol-exact vs fixtures (no such hardware).                                        |
| RBT-02 firmware idioms    | 229 | Extraction built + verified. **Emission half deferred** — CTR-05 can't express firmware idioms; LANE 0 amendment proposed (below). Boundary tested.              |
| LB-05 widget + transport  | 125 | Built; bench API routes (isolation-tested) + self-registering widget. First production wiring of LNK-06 + MCP-02.                                                |
| RBT-03 proposal + confirm | 230 | Built; four-tier fixtures, no auto-accept, tier-3 naming, cheap reject/edit.                                                                                     |
| LB-03 deployment          | 123 | Built (scripted runners); flash tri-state honesty, scp arg safety. Real flash gate not run (no sanctioned hardware).                                             |
| RBT-04 active id          | 231 | Built incl. the cannot-tell case. Physical + live-gate runs await hardware / SOLUSDEV-60.                                                                        |
| RBT-05 persist            | 232 | Built + **verified through the real FP-02 ingest path**. No parallel identity mechanism; reconnect + diff re-proposal.                                           |
| LB-04 fault induction     | 124 | Drill harness built + verified incl. **real serial teardown**; full-robot session documented.                                                                    |

## What governs / what was amended

- Governing contracts consulted and bound to exactly: MCP-02 LiveConnection + conformance,
  W0-07 windowed shapes (frozen, reused), LB-06 codec, CTR-08 hardware modalities + identity
  linchpin, FP-02 ingest seam, CTR-01 widget, CTR-03 gate types, CTR-05 boundary.
- **Tier-1 amendment (ADR-032, in the diff):** `docs/api/API-implementation.md` §13 — the bench
  telemetry routes. `docs/architecture/telemetry-viz-out.md` — the Solus→Foxglove path.
- **New workspace member:** `livebench/` (`solus-livebench`, src layout) so hardware/sim deps
  (mujoco, pyserial, tree-sitter, mcap) never enter the API service. Root `pyproject.toml`
  members + `mcap`/`mujoco` mypy overrides adjusted.
- **main.py** gained the bench-router registration + telemetry-plumbing/event-ring state (3
  regions) — outside the lane's four paths, called out here.

## Lane-brief corrections (Phase 0 audit)

1. **CTR-08 field warning was inverted.** Real names: `EntityOut.source_key`,
   `ModalityMatch.source_ref: SourceRef`, `EntityOut.modality_hints`; `SourceRef`/`external_ref`/
   `source_key` all exist; `EntityOut.source_id` does not. RBT-05 uses the correct names.
2. **Isaac Sim is NOT installed** on this DGX Spark (the brief said it runs here). Human is
   installing; LB-01 Isaac connector built over the MCAP path meanwhile.
3. **LB-06 was already built** on LANE A's branch — merged, not rebuilt.
4. CTR-05's consumer is **TU-06**, not TU-05.

## Human-owed items

- **Installs**: `ros-jazzy-foxglove-bridge` (CON-03 live smoke), `ros-jazzy-ros-gz` (Gazebo),
  Isaac Sim container (LB-01 — ticket stays open until its live smoke runs).
- **SOLUSDEV-60** merge unblocks RBT-04's end-to-end gated dispatch (the gate can only refuse on
  this branch).
- **LANE 0 proposal (RBT-02)**: additively extend CTR-05 so firmware library idioms are
  expressible — e.g. `ToolFamily.ARDUINO_SERVO`/`MICROPYTHON_MACHINE`, a `UiSurface.API` value,
  bind/actuate `ControlEffect`s — keeping instances out via the existing vendor-text machinery.
  Until then RBT-02 emits nothing to the shared store (boundary tested).
- **Tier-2 proposal**: `TelemetryWindow.duration_seconds` (W0-07, frozen) accepts `inf`
  (`gt=0` only) — propose `le=86_400`. The aggregator clamps locally meanwhile.
- **Hardware session**: LB-02/03/04 physical robot, RBT-01 real buses, RBT-04 actuator — the
  gates the automated suites cannot run. Protocols documented in-code and in `COWORK_QA_livebench.md`.
- **DECISIONS.md**: no ADR edits were needed; the LB-06/msgpack decision predates this lane.
- **LANE A (LNK-06 / `graph/buffer.py`, `graph/resolver.py`)**: the Phase-4 security review found the
  in-memory `InMemoryTelemetryBuffer` uses O(n²) list-membership per distinct signal and never
  evicts (unlike the Redis backend's TTL), and `DbEntityResolver.resolve` opens one session per
  packet. These are LANE A's shipped files (outside this lane's four paths), so LANE H hardened at
  its own boundary instead: the bench router caps distinct signals per batch (4096), bounds the
  request body and event `detail`, and counts overflow as `rejected` — a single request can no
  longer wedge the event loop. **LANE A follow-ups (flagged, not edited):** make the buffer's
  per-signal set a dict, add TTL/LRU eviction to the in-memory backend, and batch-resolve device
  ids in one query. Until those land, prod should wire the Redis buffer backend (it already has a
  TTL) rather than the in-memory one.
- **SOLUSDEV-60 (gate)**: LB-03 flash now takes an `approval` seam and refuses before touching the
  device (mirrors RBT-04); the real confirmation surface still comes from SOLUSDEV-60.
- Push, MR, and merge to main are yours (agents never push).

## Phase-4 review + hardening (both reviews returned BLOCK; findings fixed before handoff)

A fresh-context code review and a §7 security review ran on the post-CON-03 diff. Both flagged the
same CRITICAL; all confirmed findings in this lane's paths were fixed with regression tests:

- **CRITICAL — firmware-scanner symlink traversal** (both reviews): `rglob` followed symlinked
  files, so a hostile repo could read `/etc/passwd` via `evil.cpp -> …`. Fixed: `os.walk`
  without following links, skip symlinked files, verify each path resolves inside root, budget
  every entry. Two regression tests (file + directory symlink).
- **HIGH — flash had no confirmation gate**: added `propose_flash` + `approval`; a refusal returns
  `unchanged` before the runner runs (tested).
- **HIGH — scp remote-command injection**: `_safe_remote_path` rejected only a leading `-`; a
  legacy-protocol scp shell-expands the remote path on the robot. Fixed: an allowlist rejecting
  `; $ \` & | \* ~` and whitespace (+ timeout on the subprocess). 9-case regression test.
- **HIGH — persist forked canonical identity**: keyed on the raw part number while FP-02 keys on
  the normalized base, so every hyphenated Dynamixel made a second canonical row. Fixed: normalize
  through `normalize_mpn` and key on `.base`; over-64-char bases are skipped, not raised.
  Convergence test proves a confirmed part reconciles onto FP-02's existing row.
- **HIGH — bench-router availability**: unbounded body/`detail`/distinct-signals let one request
  spike the process. Fixed: Content-Length precheck (411/413), `detail` size validator,
  distinct-signal cap per batch. Regression tests for each.
- **MEDIUM — resource/teardown**: `check.py` now `try/finally`-closes its source; the Gazebo pump
  joins cancelled tasks and reaps subprocesses (SIGTERM→SIGKILL); the serial source **pins to the
  first device_id and drops mid-stream identity changes** (an unauthenticated link can't relabel
  telemetry onto another entity). Regression tests added.
- **Not-my-lane items flagged** (above): the LNK-06 buffer O(n²)/eviction and per-packet resolver
  session are LANE A's; the LB-06-summary untrusted-field classification note is a one-line
  `agent/interfaces.py` doc addition proposed to LANE 0.

## Verification

- **Python**: full API suite **1656 passed, 3 skipped**; `livebench` package **191 passed**.
  mypy strict clean across both (incl. a `conftest` follow-imports override so the two test dirs'
  same-named conftest modules don't collide under the H10 changed-file gate); ruff clean.
- **TypeScript**: desktop widget suites **27 passed** (722 across the app earlier);
  `typecheck:web` + eslint clean. OpenAPI + desktop TS schema regenerated after the router change.
- **TDD** throughout: every ticket a RED commit before GREEN; **three** review→hardening cycles
  (CON-03 pre-merge, the lane Phase-4 pass, and this security/code-review remediation).
- Real-hardware verified where possible: MuJoCo physics, CH343 enumeration, pty serial + real WS,
  real serial teardown. Every hardware gate NOT run is named, never faked.
