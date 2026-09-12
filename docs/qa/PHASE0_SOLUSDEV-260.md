# SOLUSDEV-260 — Phase 0 diagnostic report

Date: 2026-09-10 (local). Worktree: `/home/beeboss/SOLUSDEV-260`.
Branch: `SOLUSDEV-260-robot-onboarding-workspace-merge`.

## Scope and current gate

The user explicitly replaced the original real-data requirement with starting from
an empty local database and signing in to Solus. No original arms, Onshape graph,
calibration files, or integration accounts were copied from another worktree.
Historical-data migration, real-data retention, and cleanup gates cannot be claimed
from this new database. Phase 0 captures known failures; it does not fix them or
approve Phase 1. Merge order remains 251 → 252 → 250; only 251 is merged here.

## Environment and isolation

- Database: `solus`, PostgreSQL 16.14, `127.0.0.1:5432`, container
  `solusdev-260-db`, volume `solus_pgdata`. The user supplied `solugs_pgdata`;
  interpreted as the listed `solus_pgdata` and disclosed in chat. It was detached
  from all containers and contained no application tables before this session.
- Redis: session-owned `solusdev-260-redis`, `127.0.0.1:6379`.
- API: `127.0.0.1:8000`, launched from this checkout with
  `SOLUS_AUTO_CREATE_TABLES=false` after Alembic migration.
- Built renderer: `127.0.0.1:5173`, served from this checkout's
  `apps/desktop/out/renderer`. Browser testing covers the renderer, not Electron
  native IPC, hotkeys, device permissions, or a real companion.
- Ports were checked before binding. No foreign process was stopped. Other
  volumes were listed by name only and were not mounted, opened, or changed.
- The restored root `.env` is read directly by current API settings and Vite's
  `envDir`. The request's `pnpm env:sync` workflow is stale: that command does not
  exist, and generated package env files are not required by current code.
  No `.env*` file was edited.
- Full API suite: explicit `SOLUS_TEST_DATABASE_URL` with base database
  `solus_test_436a6e18`, four worker suffixes `_gw0` through `_gw3`.
  New regression tests use `solus_test_436a6e18_regression`; the targeted bridge
  retest uses `solus_test_436a6e18_bridge`. No pytest invocation
  targets the dev database.
- Python dependencies installed from the unchanged lock with Python 3.12.3 into
  this checkout's `.venv`; desktop dependencies installed from the unchanged
  pnpm lock. Host Node is v22.22.3.

Snapshot before the first migration:
`/tmp/solus260-snapshots/phase0-before-migration.dump`, custom pg_dump format,
restricted file permissions, archive directory successfully read by pg_restore.
This snapshot represents the authorized empty starting database. It is not a
backup of the user's historical graph. Take a new snapshot before Phase 2.

`alembic current` before migration: empty. After `upgrade head`:
**`a25100000001 (head)`**. `alembic heads` has exactly one head; no merge revision
was needed. SQL catalog inspection confirms `uq_solus_config_subject_live` and
`ck_solus_config_subject` are both absent after migration.

## Existing edits and merge

Initial HEAD `bb58aaf`; local `origin/main` `1fa9371` (no fetch performed).
`git log origin/main..HEAD` contained 22 merge commits and two non-merge commits:
`1504b3c` (Codex harness/skills/agents and root AGENTS.md), and `6093de5` (README).
Both two-dot and three-dot content diffs against origin/main were empty, and the
initial worktree was clean. No current 260-specific content was overwritten.

Merged named 251 branch at `4a80d2f`: this includes `0d13548` plus the two
review-only commits `b733f83` and `4a80d2f`. Automatic merge had no conflicts.
252 remains `a43578c`, 250 remains `3661e6d`; neither is merged.
`.Codex/` is now ignored, confirmed using `git check-ignore`.
253–256 must branch from 260, or from main after 260 is merged, per the user.

## Reproduction: owner configuration loss

A transaction against the running **dev database `solus`** created a synthetic
robot and part, saved firmware plus transport/protocol/bus/disambiguation fields,
then invoked the hardware service's lifecycle promotion. Before promotion,
`resolve_runtime_config` included the owner UUID in its own `parts` map.

| Field            | Before promote                         | After promote |
| ---------------- | -------------------------------------- | ------------- |
| identity         | USB serial binding `PHASE0-FIXTURE`    | null          |
| protocol         | `raw-serial`, empty params             | null          |
| bus_map          | one binding to the sensor at address 1 | empty list    |
| disambiguated_by | user                                   | null          |

This is a reproduced defect, not a static prediction. The fixture transaction
was always rolled back; graph row count before/after was 0/0. This direct service
check does not stand in for successful login or authenticated UI verification.

New route regressions in
`packages/api/tests/test_hardware_roundtrip_regression.py` exercise real
PostgreSQL in the separate regression database. Every failing assertion follows
a successful HTTP response and a refreshed read of the durable v2 config:

| Case                                         | HTTP | Preservation result                                  |
| -------------------------------------------- | ---- | ---------------------------------------------------- |
| Firmware robot, promote lifecycle            | 200  | FAIL: all four fields erased                         |
| Firmware robot, GET then PUT config          | 200  | FAIL: all four fields erased                         |
| Firmware robot, library part import          | 201  | FAIL: all four fields erased                         |
| Existing firmware robot, detect confirm      | 201  | FAIL: prior bus binding and user disambiguation lost |
| No-firmware robot, promote lifecycle control | 200  | PASS                                                 |

The detect case is **a separate overwrite path**: confirm builds a fresh aggregate
rather than reading/re-splitting the owner aggregate. It preserves the matching
identity/protocol in this fixture but drops saved context. Do not claim the
owner-key fix alone repairs detect confirm. Fixture devices and library records
are synthetic; sessions are disabled and no hardware motion occurs.

The new tests intentionally remain RED for the later fix. Fresh code-review, Python-review, and
security-review passes found no new issues in the diagnostic test file. These
limited reviews do not certify the inherited 251 implementation for release.

## Static checks and desktop boot

- Ruff over `packages/api`: **9 findings**, the same 9 in review §3.9
  (2 E501, 4 F401, 2 I001, 1 C901; 6 auto-fixable). No fixes applied in Phase 0.
- Strict mypy over API source **and all API tests**: **26 errors in 9 files**.
  Includes the review's 9 errors, plus a v2 union use in `test_store.py` and broader
  test findings in `test_perf_rag_retrieval.py`, `test_live_onshape_write.py`,
  `test_extension_review_job.py`, `test_sync_live_acquisition.py`, and
  `test_code_environment.py`. The broader count is not claimed as 26 new defects.
- Standard desktop build: **PASS**, including pinned OpenAPI type generation,
  node/web TypeScript checks, and Electron main/preload/renderer bundles. Initial
  sandboxed generator attempt failed DNS; rerun with network access passed.
  Existing dynamic-import/chunk warning remains; no generated source diff.
- App login and workspace: **PASS after the user signed in directly**. The
  authenticated Home screen shows `pmadaram`; opening `My first robot` displays
  the expected `.solus` navigator, 6 entities, 5 relations, and 0 sources. Initial
  supplied-credential sign-in was rejected; no password change or auth bypass
  was used. Native companion remains offline.

## Full API suite

**4694 passed, 14 failed, 7 skipped**, 8 warnings, 844.33 seconds. The original
merged-tree suite ran before the five new regressions were added; those ran
separately (4 failed, 1 passed). Full results for all **287 test files** and the
14 failing case names are in [the API results](PHASE0_SOLUSDEV-260_API_RESULTS.md).

| Legacy regression file       | Passed | Failed |
| ---------------------------- | -----: | -----: |
| test_hardware_router.py      |     28 |      3 |
| test_store.py                |      5 |      2 |
| test_library_router.py       |     18 |      1 |
| test_bench_robot_provider.py |      5 |      3 |

Other initial failures: `test_hardware_detect.py` (18 passed, 4 failed) and
`test_bridge_e2e.py` (1 failed: companion mock inventory is empty). The bridge
fixture shim executes `python3` from PATH; the first suite inherited the host
Python rather than this checkout's virtualenv. Targeted retest with `.venv/bin`
prepended to PATH **passed (1 test, 5.20 seconds)** without code changes. Keep
that PATH for future suites. The other **13 baseline failures remain unresolved**.
The full suite was not repeated; its original results remain recorded. Some hardware
assertions still expect v1 representation, private paths, or accept missing part
IDs; classify contract changes versus defects before repairing them. The separate
preservation regressions and dev-database reproduction establish actual data loss.
No test was weakened to make this baseline green.

## Serial identity and reconnect (§3.5)

`lb_usb_serial_test.py`: **6 passed**. The connection/local/reconnect fixture
files: **30 passed** outside the sandbox, including
`test_factory_reopens_the_transport_by_identity_each_incarnation`. The config
has no saved device path; successive opens use the same serial identity and
different resolved paths. The initial sandboxed combined run timed out after
22 tests; the same three files passed outside the sandbox in 0.97 seconds.
This establishes the behavior on fixtures, not physical arms. Serial-port
enumeration found **zero devices** on this host. No port was opened.

## Empty-data preflight and graph cleanup

Immediately after migration and the rolled-back reproduction all counts were
zero. After the user's successful login and project creation, a fresh inventory
shows **1 project (`My first robot`), 6 graph entities, 5 relations, 0 solus entries,
and 0 account connections**. The six entities are exactly the user-created
project's manual `.solus` root and its five standard section nodes, created at
2026-09-11 00:27:37 UTC. They are legitimate user data and must be retained.

Legacy robot configs, nested parts, firmware-bearing rows, local-path sources,
deleted robots, duplicate/conflicting configs, and needs-manual config rows remain
zero. Details are in [the migration preflight](MIGRATION_SOLUSDEV-251_preflight.md).
This is not evidence that historical data elsewhere is clean or convertible.

Deletion proposal: **empty list**. No committed QA fixtures or dangling edges are
present. No deletion was performed or self-approved. The original historical-data
cleanup and migration-retention gates remain unverified under the empty-start
scope; the newly created user's `.solus` hierarchy is present and intact.

## Cross-branch collision inventory

I3's environment implementation is already present: `integrations/mcp/code/`,
`packages/api/src/solus_api/routers/code_environment.py`,
`packages/api/src/solus_api/agent/tools/environment.py`, and
`docs/architecture/code-environment.md`. 252 adds a parallel implementation in
`packages/companion/src/solus_companion/machine/{environments,actions,host,server}.py`,
wired by `__main__.py`, `config.py`, and `supervisor.py`. Consolidate into I3 in
Phase 4 as requested.

252 contains execution calls to `registry.invoke` only in the existing
`agent/runtime.py` and `agent/confirmations.py`; its registry.py match is prose.
No additional execution site was found by static search. This is not a substitute
for the combined destructive-gate tests.

250's `hardware/device_watch.py` is a **local API watcher**, not a companion
watcher. It sends full lists through `LiveHub.publish_local` as
`hardware.devices_changed`. 252 modifies companion inventory/launch ownership
in `supervisor.py` and `config.py`, and hello bounds in API `routers/bridge.py`.
Their live coexistence remains a later gate.

| Branch pair | Files modified by both relative to local origin/main                                                                                                                                      |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 251 / 252   | `.gitignore`; desktop `src/main/index.ts`, `src/preload/index.ts`; `docs/api/solus.md`                                                                                                    |
| 251 / 250   | `docs/api/hardware.md`; `docs/architecture/hardware-onboarding.md`, `workspace-navigation.md`; `docs/wireflows/hardware-onboarding.md`, `workspace.md`; API `hardware/hardware_router.py` |
| 252 / 250   | desktop graph `SolusNodeContent.tsx`, `solusActions.ts`, `useSolusNodes.test.tsx`; `WorkspaceShell.tsx`; API client `resources.ts`; `docs/api/API.md`; API `core/config.py`, `main.py`    |

These are overlap inventories, not tested conflict predictions.

## Governing material and remaining prerequisites

The attached request and subsequent user scope changes govern Phase 0. Consulted
root AGENTS.md, DECISIONS.md (including 251's already-approved ADR-034 amendment),
251's full pre-merge review and execution plan, hardware-config schema,
hardware/workspace/local-connections/change-signal architecture, hardware/workspace/
solus route plans, hardware/workspace wireflows, and desktop directory instructions.
Used verification-loop, database-migrations, and TDD guidance for diagnostic work.

- 252 bridge-protocol amendment is **approved by the original request**; mark it
  approved in the document when merging Phase 4.
- `SOLUS_NODE_BIN` remains unset. Candidate user-set value:
  `/home/beeboss/.nvm/versions/node/v22.22.3/bin/node`.
- OpenAI funding is unknown; no model call attempted in Phase 0.
- Root logging-handler decision remains pending for Phase 5.
- Real arms, USB swaps, native Electron, real companion, two integration accounts,
  existing calibration-file relink, and historical-data migration remain unverified.
- Phase 0 diagnostic evidence does not approve cleanup or implementation. Stop at
  this gate for the user before proceeding to Phase 0b/1.
