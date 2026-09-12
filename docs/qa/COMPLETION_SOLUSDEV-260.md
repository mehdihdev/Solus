# SOLUSDEV-260 — combined verification and handoff

Status: local integration and automated verification complete. Live prerequisites
remain unverified as listed below; this is not a claim that every physical demo gate passed.
No push, MR, main update, environment-file edit or other-worktree change was performed.

## Scope and governing documents

The fixed merge order was 251, then 252 (`a43578c`), then 250 (`3661e6d`, local merge commit `deaa93e`).
Phase records `PHASE0_SOLUSDEV-260.md` through `PHASE5_SOLUSDEV-260.md` contain the
per-phase defects, tests and decisions. Hardware architecture/API/schema/wireflows,
workspace navigation/wireflows, `.solus` architecture/API, SOL API and the locked
private local-state contract governed the changes. Five overlapping design documents
were reconciled against per-entity v2 CONFIG, private relinking, CODE environment
ownership and asynchronous session opening. Tier-1 API/architecture prose was updated.
No protected contract or ADR was changed without approval.

User decisions: one root console handler; explicit local relinking of opaque legacy
references rather than guessing unavailable digests; tentative ACM1 leader/ACM0
follower mapping. The bridge hello limit remains the previously approved 256 KiB.
Ponytail is unavailable; independent simplification and security reviews were used.

## Environment and preserved data

- Checkout `/home/beeboss/SOLUSDEV-260`; feature branch
  `SOLUSDEV-260-robot-onboarding-workspace-merge`.
- Live PostgreSQL database `solus`, 127.0.0.1:5432, container `solusdev-260-db`,
  volume `solus_pgdata`; Redis 6379; API 8000; renderer 5173.
- Tests use isolated `solus_test_436a6e18_*` databases, not the populated live database.
- Single Alembic head/current: `a26000000003`. Phase 2 validated the snapshot before
  backfill and applied both new revisions; historical migration is fixture evidence
  because the authorized empty-start database had no legacy CONFIG rows.
- Project My first robot: `01a08ddc-de30-7970-a0f6-d0568e8ba61f`.
  GitHub `PotosnakW/ForgeTS_internal` and Onshape
  `Wrist_Roll_Follower_SO101 v10:1` are real connected sources.
- User-authorized local workspace: `/home/beeboss/Desktop/ForgeTS`.
  Existing `.venv` found; no `sim` environment was invented or created.
- Graph before live hardware: 168 entities/166 relations. Real follower confirmation
  added its robot, categories, actuator/config nodes: 189 entities/200 relations.
  Counts survived graceful API restart. No fabricated demo nodes or pruning.
- Graph-derived document `Follower wrist — graph evidence` remains filed, 994 bytes,
  in the retained local artifact root `/tmp/solus-artifacts-5vtdd9rv`.
  It has one CAD node and no known wiring, not a claimed servo wiring schematic.

## Phase 6 gate matrix

| Gate                            | Result and evidence                                                                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Arm demo and fixture Arduino | **Partial live / fixtures.** Follower serial 5B42134331 answered as six STS3215 servos; UI confirmation produced a connected robot and accepted mapped telemetry. Channel 1 position 2126, load 0, temperature 30 with charts. No motion commanded. Arduino sketch/serial inference covered by the 523-pass Live Bench suite. Complete new SOL wiring turn/hotkey remains unverified because provider retries failed. |
| 2. Both arms / port swap        | **Unverified prerequisite.** Leader serial 5B42135040 visible but servos do not answer. Power/cabling question pending; user mapping is tentative. Physical port swap/unplug/reconnect not performed.                                                                                                                                                                                                                 |
| 3. Import + reconciliation      | **Fixtures.** Covered by hardware proposal/import/ownership regressions. Did not create an extra library robot in the user's populated graph.                                                                                                                                                                                                                                                                         |
| 4. Delete and reclaim           | **Live DB rollback + fixtures.** Phase 3 live transactional exercise proved release/reclaim with no retained synthetic rows. Phase 5 UI Delete/Keep verified. Destructive deletion of the real follower was not repeated.                                                                                                                                                                                             |
| 5. SOL field edit               | **Fixtures.** Approved single-field v2 writes preserve firmware and all other configuration/provenance; refused/stale/tenant cases tested. Live SOL execution blocked by provider failure.                                                                                                                                                                                                                            |
| 6. I3 environment install       | **Fixtures / live unverified.** One I3 environment implementation and one destructive dispatch path. Companion uses the authorized ForgeTS workspace; `sim` absent and install not completed.                                                                                                                                                                                                                         |
| 7. Brave/page citations         | **Unverified provider prerequisite.** No successful cited live turn after rate/overload failure; no invented datasheet/library item.                                                                                                                                                                                                                                                                                  |
| 8. Companion and detection      | **Live.** Real desktop companion hello accepted, local forks reported with honest unavailable/licensing states, both actual USB devices appeared. Physical unplug timing not measured.                                                                                                                                                                                                                                |
| 9. Accounts and four documents  | **Partial live.** Both integration accounts connected; account grouping and document reveal verified. One CAD document and one repo supplied, so four-document gate is unverified.                                                                                                                                                                                                                                    |
| 10. Migration/relink/real graph | **Live migration + fixtures.** Snapshot-backed migration applied; no unhandled legacy rows in fresh dev DB. Historical nested/private cases use PostgreSQL fixtures. Native private calibration relink unverified because no calibration file was supplied. Graph retains only real connected/user-created nodes.                                                                                                     |
| 11. Suites and ratchets         | **Verified on fixtures.** Final combined Python suite, desktop suite, lint/types/build and vendor/destructive/three-machine ratchets pass; skips and live limits are below.                                                                                                                                                                                                                                           |
| 12. Report and handoff          | This report plus the self-contained `COWORK_QA_SOLUSDEV-250.md` and `COWORK_QA_SOLUSDEV-251.md`; unverified paths are explicit.                                                                                                                                                                                                                                                                                       |

## Model result

At the user's request, Think harder selected `gpt-6-astra`; the live ledger recorded
`general_hard` and 18 credits on 2026-09-11 at 03:57:05 UTC. The provider exhausted
rate-limit/overload retries. Separately, the configured project returned 403 for
`text-embedding-3-small`. Embeddings and reasoning are different capabilities;
Astra was not substituted into the embedding endpoint. No additional paid retries
were made after that outcome, and no environment/model catalog was edited.

## Verification

- Desktop full suite: 3,595 tests across 345 files passed. Later private-file
  complexity refactor: 35 tests passed before and after; sidebar timing regression:
  17 passed after its reproduced failure. Type checks and final build passed. Late Guide copy now accurately distinguishes
  automatic probing from project creation on confirmation; five existing UI/copy
  tests passed, fresh review passed, and the rebuilt desktop displays the correction.
- Full Live Bench: 523 passed. Final lifecycle selection: 45 passed, 89% aggregate
  statement/branch coverage (connections 87%, runtime owner 88%, sessions 93%).
- Root Ruff passed; strict mypy passed 408 source/test files; root ESLint zero errors,
  145 existing warnings. Generated OpenAPI and renderer schema are current.
- Final combined non-live Python run: **7,169 passed, two skipped, one expected
  failure**, zero errors/failures in 1,045.21 seconds. Log and JUnit:
  `/tmp/solus260-phase6-python-verified.log` and
  `/tmp/solus260-phase6-python-verified.xml`. This includes API, companion,
  integrations, reasoning, Live Bench and CI tests. Both migration files passed
  all 38 cases; vendor/destructive/three-machine selections have no failures.
- Skips: OCCT is installed so its unavailable-parser path cannot run; the temporary
  directory is inside a git checkout so the unrooted-tree fixture is inapplicable.
  The existing KiCad byte-identical roundtrip is an expected failure because the
  upstream library normalizes formatting. Provider-live tests were explicitly
  excluded and are not claimed passed.
- The initial combined run had two worker deaths. PostgreSQL logs showed forced
  checkpoints lasting 631.4 seconds, beyond the unchanged 300-second timeout.
  Reviewed fixtures now reuse a separate migration DB per checkout/run/worker and
  reset its schema each case; URL queries are refused before connecting. No
  product migration or assertion was weakened. The final uninterrupted green run
  above verifies the repair.
- Fresh code and security reviews cleared lifecycle, scope and cancellation fixes.
  Final private source refactor and sidebar change also passed fresh security/TS review.
- The requested H10 worktree-DB hook change remains unimplemented: repository rules
  explicitly prohibit agent edits to hook files. The hook was not bypassed. Human
  follow-up is required for that protected harness change.

Supporting local logs/screenshots are under `/tmp/solus260-phase*`; they are
session artifacts rather than claims of CI execution. Private credentials are not
included in this report.

Phase 5 was recorded locally as `deaa93e`. The six requested baseline test-file
formatting changes have identical Python ASTs before/after and pass Ruff; they
are recorded separately in `1fff63d4`. Phase 5 ownership manifests were removed
after integration and review; the Phase 6 fixture ownership manifest was removed
after its final passing run. No outstanding sub-branches remain from this work.

## Startup and provider follow-up — 2026-09-11

SOLUSDEV-251 (`0d13548`), SOLUSDEV-252 (`a43578c`) and SOLUSDEV-250
(`3661e6d`) are ancestors of this local feature branch. This is local integration
evidence, not a claim of a remote main merge.

The reported `pnpm dev:all` failure was reproduced: Compose selected an empty
worktree volume, the API failed because `graph_entity` was absent, Redis was not
started, and Electron continued against the failed API. The original `solus_pgdata`
volume remained intact. A private custom-format backup was made under ignored
`tmp/backups/`; an ignored `docker-compose.local.yml` now explicitly selects that
original volume. Both volumes and the original stopped container are preserved.
The restored database has revision `a26000000003` and 189 graph entities.

The launcher now consistently applies the optional local override, starts configured
local Redis, checks schema and dependency readiness without migrating, pins the
selected Node >=22 executable for MCP forks, tolerates TIME_WAIT on restart, and
waits for API readiness before starting Electron. Continued health checks tolerate
normal reloads and stop the owned stack after sustained API failure. Startup does
not install MCP dependencies. The Docker readiness probe reads from `/dev/null`
to avoid suspension or input consumption in terminal launches. Both detached and
terminal `pnpm dev:all` launches reached API, Electron and MCP discovery; the
terminal-specific fix also passed fresh code review. README documents native
application prerequisites.

All 11 configured reasoning models returned successfully using their production
adapters and the configured provider keys. The restored encrypted keys match those
tested. A separate Astra response returned HTTP 200 with limit headers of 5,000
requests/minute and 2,000,000 tokens/minute. `text-embedding-3-small` returned HTTP
403, code `model_not_found`; this remains an access prerequisite, not a retryable
rate limit. Astra is not substituted into the embedding endpoint.

The shared model retry path now distinguishes permanent quota/auth/access failures
from temporary failures, honors provider timing, adds jitter, and shares cooldowns
within each API/worker process. Delays beyond the interactive wait bound fail
without an early retry. Existing routing, user admission caps, credit gates and
no-replay-after-output behavior remain intact. This is not an account-wide,
cross-process RPM/TPM scheduler. GitHub stops after a throttled conditional probe;
Onshape no longer truncates a long Retry-After into an early retry. The vendored
Brave upstream is unchanged; no new Brave rate scheduler is claimed.

Live `pnpm dev:all` reached API startup complete and started Electron and companion
tool discovery against the restored database. KiCad answered tool discovery.
Fusion's native MCP endpoint was absent. AutoCAD/SolidWorks launchers are absent;
Altium requires a linked workspace. The desktop retained a stale project selection,
and the earlier supplied password returned HTTP 400 on sign-in. A new authenticated
SOL turn and project-scoped MCP acceptance therefore still require the user to
sign in and select the restored project. These are not marked passed by the direct
provider probes.

Governing material: ADR-026/031, the model-orchestration contract, local-connections
and local-machine-actions architecture, existing readiness/bridge routes, and the
gateway-embeddings API document. No routes, protected contracts, environment files
or hooks were changed.

Final follow-up verification: **321 tests passed in 15.40 seconds**, covering the
launcher, all three provider adapters, retry concurrency, gateway/embedding gates,
tool conversations, Responses handling and both connectors. Tests used the separate
`solus_test_260_final` database; the restored project database was not a fixture.
Ruff lint/format and mypy passed all 14 changed Python source/test files; shell
syntax and documentation formatting passed. This targeted run supplements the
earlier full-suite results above; it is not a new full-suite or CI claim. Coverage
instrumentation was unavailable, so no measured percentage is asserted.

Fresh code and security reviews passed. Python review found a Google transport
timeout escaping normalization and an SDK transport-level reconnect; both were
fixed with an explicitly owned HTTPX client, safe transport-error normalization,
single-send SDK tests and cancellation cleanup tests. Python and security re-review
passed on `bb4931b8`. Final live smoke calls to Astra, Claude Sonnet and Gemini Flash
all succeeded through the updated adapters. Local evidence:
`/tmp/solus260-followup-final-tests.log`, `/tmp/solus260-provider-final-probe.jsonl`
and `/tmp/solus260-dev-all-terminal.log`. No credentials are included in this report.

## September 11 follow-up — SOL shortcut and graph mentions

The user replaced the double-Ctrl request with a conventional shortcut:
Ctrl+Shift+Space on Windows/Linux and Cmd+Shift+Space on macOS. Registration now
runs independently of native gesture support. Wayland attempts Electron's global
shortcut portal, preserving existing Chromium feature flags; unsupported or denied
registration retains the clickable Open SOL window fallback. No native-hook build
or platform support guarantee is implied.

Removed the main SOL Guide/Expert header selector and floating-window header mode
selector while retaining settings and composer controls. The floating window
rehydrates the existing workspace store on local-storage changes so it follows the
main window's selected project.

Existing entity search now matches code-file/module paths and external references
as well as names, using bound, escaped queries with existing project/tenant/deleted
filters. Mention rows expose paths. Project changes invalidate pending searches,
results and picked IDs, including leave-and-return transitions. Mentioning an
entity supplies graph metadata; raw GitHub file contents still require an authorized
source-tool retrieval.

Governing docs: docs/api/API.md, docs/architecture/sol-window.md and the SOL page
and window wireflows. These are updated in this follow-up. No new route or protected
contract change was required. QA section H in COWORK_QA_SOLUSDEV-252.md covers the
physical shortcut, portal fallback, headers, project changes and path searches.

Verification: all 3,599 desktop tests passed across 347 files; 16 API search tests
passed against the isolated solus_test_mentions_260 database. Desktop typecheck and
production build passed. Changed Python files passed Ruff and mypy. The initial
sandbox build failed to resolve npm; the full build with network access succeeded.
Fresh code and security reviews found no outstanding issues. Physical global-key
activation and a signed-in end-to-end mention conversation still require desktop
acceptance; no UI automation claim is made.

The embedding retry still returned HTTP 403 model_not_found for
text-embedding-3-small. Embedding generation remains unverified because the
provider rejected access; configuration was not changed or replaced with Astra.

Canonical desktop lint remains at 64 errors and 12 warnings, identical to baseline
c3ec85e5 (normalized rule, severity, location and message comparison). All 19
changed TS/TSX files have zero errors or warnings under that same config. The fresh
TypeScript review found no current-diff issue; repository-wide lint is not claimed
green. Evidence: /tmp/sol-ts-lint-baseline-summary.json.

The restarted pnpm dev:all reached API readiness and authenticated requests for
the restored project returned HTTP 200. Physical shortcut acceptance is pending.

Fresh Python review also passed for the search router and its tests, with no
findings. The local persona file was unavailable; the reviewer applied the supplied
Python-reviewer criteria. No coverage percentage or remote CI pass is asserted.
