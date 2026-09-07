# Completion Report — SOLUSDEV-248: Robot onboarding (R5 → R3 → R1 → R2 → R4)

**Ticket:** SOLUSDEV-248 · **Branch:** `SOLUSDEV-248-R15` (22 feature commits plus merge commit `c059170` syncing `origin/main` — SOLUSDEV-242 Home and SOLUSDEV-246 workspace layer — into the branch; `b15fc84` is the live-run fix; alembic head after the merge is `7e290e665c1f`, a merge revision over `8f1c2a7d4e90` and main's `f7a8b9c0d1e2`) · **Date:** 2026-09-06 · **Status:** integrated,
suites green, run for real against two arms, awaiting the human steps in §7.

Spec: the ticket brief (the repo's `docs/design/SPEC.md` is a copy of `.gitlab-ci.yml`; the
Phase 1 gate recorded "brief is the spec"). Governing docs authored on this branch as tier-1:
`docs/api/hardware.md`, `docs/architecture/hardware-onboarding.md`,
`docs/wireflows/hardware-onboarding.md`, `docs/contracts/telemetry-packet.md` §2a,
`docs/api/solus.md` and `docs/api/API.md` amendments. Tier-2: ADR-034 amendment (approved
in-chat verbatim, commit `901c47e`).

---

## 1. Per phase — what was verified on hardware, on fixtures, or not at all

| Phase                                                        | Built                                                                                                                                                                                                                                                                                                                      | On hardware (two six-servo serial arms, live API on :8000)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | On fixtures / CI                                                                                                                                                                                                                  | Not verified                                                                                                                                                                                                    |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1 · R5** config schema, lifecycle, link engine             | `solus_api/hardware/{config,store,links}.py`, `SolusEntryKind.CONFIG` + JSONB `payload`, `hardware_suggestions` table (migration `8f1c2a7d4e90`; head after the main sync is the merge revision `7e290e665c1f`), routes config/parts/lifecycle/suggestions                                                                 | Config documents written by real confirm and accept flows carry per-leaf provenance (`detected` identity/protocol/bus map, `repo` names+calibration with the calibration file as source, `library` names/units, `user` disambiguation); suggestion rows created, accepted, siblings superseded                                                                                                                                                                                                                                                                                                      | `test_hardware_config`, `test_store`, `test_links` (two candidates → two rows, floor, ceilings), `test_hardware_router` (auth, cross-tenant 404, viewer 403, events)                                                              | `PUT …/config` and lifecycle promotion were exercised only through tests, not by hand on the live API                                                                                                           |
| **2 · R3** transports, drivers, reconnect, telemetry library | `livebench/hardware/*` seams (Channel, ProtocolDriver, Interrogator, registries, replay), transports usb_serial/usb_can/udp/bluetooth, plugins feetech/dynamixel/odrive/mavlink/lb06/jsonlines/raw/arduino, `open_robot_connection`, bench `provider: "robot"`, `libs/solus-telemetry` (Python, MicroPython, Arduino, MIT) | Both arms open by USB serial identity; six servos each at 1 Mbaud; sessions from the robot config stream ~30 Hz per servo; **every packet resolves** to its part (`ingested` 984 / 540 in 3 s, `unresolved` 0) after the fix in §2; six joints in `deg`, gripper in `%` in the resolved series                                                                                                                                                                                                                                                                                                      | Replay channel drives the CAN/UDP/line fixtures through transport → driver with no vendor import; reconnect factory re-resolves by identity (`lb_connection_test`); bluetooth honest not-installed; telemetry-library parity test | **Silent reconnect on unplug/replug and USB port swap** (human steps §7); **Nano flash** of the telemetry library (human step); CAN and UDP against real hardware (none present)                                |
| **3 · R1** Add › Hardware                                    | Five cards, Authored flow end to end, honest Sourced tile, `lib/api/hardware.ts` typed client                                                                                                                                                                                                                              | Authored parts created through the real API (part + config entry + provenance `user`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Desktop vitest: 266 files / 2756 tests green incl. `HardwareAddPanel`, `AuthoredPartModal`, `vendorHygiene`                                                                                                                       | **The desktop UI was not driven in a real browser or Electron by the agent**; the API twins of each card were                                                                                                   |
| **4 · R2** detection loop                                    | `hardware/detection.py`, `repo_config.py` + lerobot AST parser plugin, calibration signature, `detect.py` routes (propose/confirm), port-path repair notice, From-a-file attach, Detected + From-a-file desktop flows                                                                                                      | `GET /detected` lists both arms by serial at the honest bridge level (0.30); propose → driver `feetech-sts`, six rows at 0.92, names + calibration from the lerobot clone (provenance `repo`), three matching repo configs → one disambiguation question with the wire's burned calibration **favouring** `bee_leader_arm` (never answering); confirm → robot + six parts keyed `usb:<serial>/<address>`, session started; second arm offered only the unbound configs; re-confirm of a bound device → 409 naming the owning robot; `port_repair` is a notice only (lerobot binds ports on the CLI) | `lb_detection`, `lb_repo_config`, `lb_lerobot_parser`, `test_hardware_detect` (22 cases incl. accept-with-runner, 409, layers), `test_hardware_attach`                                                                            | **Detected / From-a-file desktop modals not driven by hand**; From-a-file needs a connected source with parts (none on this machine — tests only)                                                               |
| **5 · R4** library                                           | 18 parts, 6 platforms (`definitions/{parts,platforms,vendor}`), in-memory catalog + lexical search, import → robot + parts + config with provenance `library`, reconciliation through the link engine, desktop Library modal (search → preview → import)                                                                   | Import `so101-follower` → propose the real arm → **one** suggestion (bus-map rule, 0.80 high) → accept → identity bound, six library parts keyed and **live**, session ingesting, no second robot                                                                                                                                                                                                                                                                                                                                                                                                   | `test_library`, `test_library_router`, `test_hardware_detect` reconcile case; desktop `LibraryModal.test.tsx`                                                                                                                     | Desktop Library modal not driven by hand (9 vitest cases: seed listing, search, no-match copy, part import with category default, platform import with gear table and the pending-suggestion line, error paths) |
| **6 · proofs**                                               | (a) `lb_three_machines_test.py`: PX4-over-UDP, ODrive-over-CAN, Arduino line rover through one shared module set; (b) vendor-hygiene ratchets (livebench, API, desktop) in CI                                                                                                                                              | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Both pass; (a) now also asserts every packet carries a part key; (b) caught two leaks during the work (a `links.py` docstring, a persist comment)                                                                                 | —                                                                                                                                                                                                               |

## 2. What the real run found that the suites did not

The brief's warning ("three times this repo shipped green suites over a broken product") held a
fourth time. With 3893 API tests, 708 livebench/companion tests and 2745 desktop tests green, the
first live session showed **`ingested: 0, unresolved: 193`**: drivers emit one sweep packet keyed
by the device (`usb:<serial>`), every part's `external_ref` is `<device>/<address>`, and the
resolver matches `device_id` alone. The provider test asserted the session opened, never that
anything resolved. Fixed at the shared seam (`livebench/hardware/connection.py`,
`PartRoutingSource`): the robot connection splits each sweep by signal — exact declared channel
name, else an unambiguous `<part>` prefix, else `addr_<address>` — so each part's readings carry
the part's own key. Config-driven, vendor-free; the three-machine proof is its fixture twin.
Documented in `hardware.md` §6 and `telemetry-packet.md` §2a. Commit `b15fc84`.

Second finding: the dev database was one migration behind, so `POST …/projects` returned 500
until `alembic upgrade head` (recorded in the QA setup).

## 3. Quality gates (final tree)

| Gate                                                                                                               | Result                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ruff check .` (repo)                                                                                              | All checks passed                                                                                                                                                                          |
| `mypy --strict` (`packages/api/src`, `packages/companion/src`, `livebench/src`, `libs/solus-telemetry/python/src`) | Success, 315 files                                                                                                                                                                         |
| `pytest packages/api/tests -n 8`                                                                                   | 3893 passed, 4 skipped (5:23); the rerun with full output passed identically (3893 passed, 4 skipped, 5:41); the earlier xdist "different tests were collected" worker error did not recur |
| `pytest livebench packages/companion`                                                                              | 708 passed                                                                                                                                                                                 |
| fast suites (`livebench packages/companion integrations reasoning libs infrastructure/ci/tests`)                   | 1339 passed, 1 xfailed after the `links.py` docstring fix                                                                                                                                  |
| `pnpm typecheck` + desktop vitest                                                                                  | 266 files / 2756 passed (final tree, Library modal included)                                                                                                                               |
| `alembic heads`                                                                                                    | single head `7e290e665c1f` (merge revision; both branches upgrade through it)                                                                                                              |
| Vendor ratchets                                                                                                    | green in all three trees                                                                                                                                                                   |

## 4. Decisions made under delegated judgment

- **Identity key** `transport:binding` (`usb:5B42134331`), parts `<device>/<address>`; driver
  id lives only in the config (Phase 1 gate answer 6). Confirm accepts a transport-prefix
  allowlist, never a vendor.
- **Packets keyed per part** (§2) rather than per robot: the entity that answers on the bus is
  the part; the robot root keeps `external_ref` NULL.
- **Accepting a library suggestion marks the parts that answered on the wire `live`**
  (provenance `detected`) — consistent with confirm; a library part that did not answer stays
  `planned`.
- **Gripper unit is `%`** (lerobot v0.4.4 `RANGE_0_100`; no `LINEAR` mode exists); `linear→mm`
  kept for the legacy format.
- **Port-path repair is a notice, never a write**: lerobot binds ports on the command line, so
  the proposal reports configured vs actual and the corrected command; a write-through action
  behind the confirmation gate is a later SOL ticket.
- **Detected / authored parts keep `origin: manual`** (editing rights, sweeps stay off);
  provenance lives in the config.
- **MAVLink parser hand-rolled** for HEARTBEAT / ATTITUDE / SERVO_OUTPUT_RAW (pymavlink is LGPL,
  outside the ADR-031 boundary). **R4 definitions are YAML loaded in memory** (no global table,
  ADR-033 untouched). "MHS drivers" = vendor-shipped definition files; `definitions/vendor/` is
  the typed ingest seam, seeded empty.
- **Busy port reads as silence**: while a session (or a teleop) holds the port, propose returns
  no protocol rather than an error; the QA file says so.

## 5. Deviations from the plan

- The hardware routes return `dict[str, Any]`, so the desktop R2/R4 wire shapes are hand-typed
  in `lib/api/hardware.ts` (the generated `schema.ts` carries no shape for them).
- A `bench_local_enabled` settings gate was planned and not built; runner absence is reported
  per response (`bind_error` / `session_error`) instead.
- `SOLUS_HARDWARE_ENUMERATE_INTERVAL_S` was anticipated and not needed: enumeration is
  on-demand per `GET /detected`; no continuous enumerator process exists.
- Desktop R1/R2/R4 flows were verified through vitest and the API twins, not by driving the UI.

## 6. Open concerns (report, not hidden)

- **Both arms carry the leader's burned homing offsets** (1964, 508, 976, 1193, −1934, −589 =
  `bee_leader_arm.json`): lerobot writes calibration into the motors on connect and the user's
  teleop runs swapped `ttyACM0`/`ttyACM1`. The wire signature therefore favours `bee_leader_arm`
  for **both** arms; the proposal still asks. The follower needs recalibrating (human).
- A stray `None.json` in the lerobot calibration cache appears as the option
  `lerobot:SOLeader:None` (a run without `--teleop.id`); delete it or it will keep being offered.
- One `pytest -n 8` rerun of the API suite ended with a worker error "Different tests were
  collected between gw0 and gw6" (xdist collection mismatch) after an otherwise identical run
  passed 3893; the rerun passed identically (§8). If it recurs, look for a parametrize id that depends on set ordering; nothing in this ticket's tests parametrizes on unordered input.
- `DECISIONS.md` has two ADR-035 headings (pre-existing); the H10 stop gate's 900 s cap is below
  the full suite's runtime (pre-existing, human-only).
- Pre-existing eslint `react-refresh/only-export-components` error in `AuthoredPartModal.tsx`
  (exports a constant beside the component); left as found.
- H12 manifests must be globs (bare prefixes never match) — the manifests were rewritten; the
  hook's matching is worth a human look.
- The lerobot real-clone parser test skips when `~/lerobot` is absent (environment-dependent by
  design); the fixture copies under `livebench/tests/fixtures/lerobot_calibration/` cover CI.
- `GET …/bench/device-recent` reports `resolved_entity_id` with empty `signals` for a resolved
  device — by design (resolved series live under the entity), but the UI copy should not imply
  data loss.

## 7. Human steps (exact)

1. **Swap the arms' USB ports** — stop both sessions, swap the two cables, then restart each
   robot's session (`POST /api/v1/projects/<P>/bench/sessions
{"mode":"real","config":{"provider":"robot","robot_entity_id":"<ROBOT_ID>"}}`). Expected:
   each robot streams from its own arm; `GET …/hardware/robots/<ROBOT_ID>/config` shows the
   same `identity.binding` and an updated `last_seen_path`.
2. **Unplug / replug** an arm for ~5 s during a session. Expected: session stays `active`,
   `ingested` pauses and resumes, no proposal needed. (`lb_connection_test` covers the identity
   re-resolution; the physical gap was not exercised.)
3. **Flash a Nano** with `libs/solus-telemetry/arduino/examples/NanoSixChannels` (Arduino Nano,
   115200 baud; arduino-cli:
   `arduino-cli compile --fqbn arduino:avr:nano libs/solus-telemetry/arduino/examples/NanoSixChannels && arduino-cli upload -p /dev/ttyUSB0 --fqbn arduino:avr:nano libs/solus-telemetry/arduino/examples/NanoSixChannels`).
   Then Detected → Propose → six rows by address (driver `raw-lines`/`lb06`) → Confirm → ~35 Hz.
4. **Recalibrate the follower arm** in lerobot (its motors hold the leader's offsets), then
   Propose again: the favoured option should become `my_awesome_follower_arm` for that arm.
5. Delete `~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/None.json`.
6. Renumber the duplicate ADR-035; raise the H10 hook cap or scope its suite.
7. Review, push, open the MR, run `docs/qa/COWORK_QA_SOLUSDEV-248.md`.

**Environment values to set:** none new. Dev machines must run `alembic upgrade head` once.

## 8. Final gate results appended at handoff

- Desktop after the Library modal: `pnpm typecheck` clean; vitest 266 files / 2756 tests passed; eslint clean on the nine touched files.
- API suite rerun (`pytest packages/api/tests -n 8`): 3893 passed, 4 skipped.
- Working tree clean at handoff; `.claude/state/ownership/` emptied.
- **Main sync (2026-09-06, commit `c059170`)**: `origin/main` (SOLUSDEV-242 Home, SOLUSDEV-246 workspace layer, 185 files) merged in. Four conflicts resolved — `pyproject.toml` (union: main's pytest-timeout ceiling + this branch's `libs` testpath), `docs/api/API.md` §2.1 (main's table; our §2.3/§2.10 rows kept), `openapi.json` + `schema.ts` (regenerated, idempotent), `uv.lock` (regenerated). Alembic merge revision `7e290e665c1f`. Gates on the merged tree: ruff clean, mypy 327 files, API 4036 passed from a scratch database, fast suites 1344, desktop 2815 tests + typecheck. Live run repeated on the merged tree with both arms: ingested 990 / 540, unresolved 0, 409 on re-confirm. Dev database upgraded through the mergepoint. Post-merge review (three reviewers + adversarial verify) confirmed one gap: `.gitlab-ci.yml` `.python-rules` `changes:` had no `libs/**/*`, so a merge request confined to the telemetry library would have run no Python lint/type-check/tests; fixed (tier-1 CI edit, ADR-032) with a `libs` row in `infrastructure/ci/tests/test_pipeline_config.py`. Refuted as pre-existing on main, not merge damage: main's ADR-027 amendment blocks are spliced into the middle of an older bullet list in `DECISIONS.md` (human to tidy), and the graph canvas renders main's `domain=workspace` system nodes without a domain filter.
