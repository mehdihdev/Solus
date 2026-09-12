# SOLUSDEV-260 Phase 3 — lifecycle, private sources and versioned editing

Work follows Phase 2 commit `8c7334e`, on the same ticket branch and local database.
Governing documents: `docs/architecture/hardware-onboarding.md`,
`docs/architecture/solus-folder.md`, `docs/architecture/workspace-navigation.md`,
`docs/api/hardware.md`, `docs/api/solus.md`, `docs/api/workspace.md`,
`docs/wireflows/hardware-onboarding.md`, `docs/wireflows/workspace.md`,
`docs/schemas/hardware-config.md` and the existing private local-state contract.
The execution split is recorded in `PLAN_PHASE3_SOLUSDEV-260.md`.

## Result

Deleting an owner releases its claims while independent retained controllers keep
valid mappings. Reads are pure and validate the live CONFIG
node, subject and relation. Legacy robot GET requires MEMBER; v2 GET permits
project viewers. Missing configuration stays absent until first PUT;
inconsistent live graph state fails closed. Runtime assembly excludes retired
configuration rather than using it as connection authority.

The renderer uses versioned per-entity configuration endpoints and presents CONFIG
nodes as configuration editors. Private source controls use the existing MAIN IPC
namespace and reject stale project/account responses, including A→B→A switches.
Explicit relinking preserves approved migrated references; actual selected bytes
establish the private digest. Historical aliases remain independently usable.

The local reader verifies bounded regular files, digest and account/project scope.
Both session entry points use it off the event loop. Private USB hints are ephemeral,
are not confirmed-port permission and cannot choose CAN channels. Driver errors
are translated into portable errors without leaking private paths to responses or
logs. Arbitrary compatibility `repo_root` values are rejected before filesystem I/O.
No new API route or protected contract was introduced. API documentation and the
source-alias schema explanation were updated directly under tier-1 governance.

## Verification evidence

- Focused backend lifecycle/config regressions: 97 passed; attach/ownership: 19
  passed; retired CONFIG regressions: 30 passed; private source/session/detect
  integration: 45 passed. These overlap; do not add them into a unique total.
- Desktop full run: 3168 passed, 10 environment failures, one skipped. All ten
  failures were loopback-listener or `/bin/ps` sandbox restrictions. Both affected
  files passed on the host (37 tests). All 3178 executed cases therefore have passing
  evidence; the one skipped case remains skipped.
- Live Bench: 476 passed. Companion: 258 passed.
- Workspace TypeScript checks and desktop production build passed. OpenAPI/schema
  generation used the already cached exact generator after npm DNS resolution
  failed; no dependency or generated shape was invented.
- Coverage audit added one confirm-after-commit source-change HTTP regression
  (passed) and six direct CONFIG GET/PUT scope-change regressions (10 focused
  desktop tests passed). These test-only additions followed full-suite collection
  and have separate focused evidence; no production code changed.
- Final repository ruff passed; strict API mypy passed for 667 source files.
- Full API suite: **4852 passed, 7 skipped**, 2462.55 seconds. No failures.
  Skips: Anthropic corpus/live keys (2), Google live key, OpenAI dedicated live
  key/model, Onshape write credentials/document/element, missing KiCad fork venv,
  and the OCCT-absent path because OCCT is installed. The separate new confirm
  regression also passed after this run collected its tests.
- Live database rollback exercise passed create/configure/promote/versioned edit,
  stale 409, deletion, retained calibration/lifecycle and device reclaim. A commit
  blocker and mandatory outer rollback preserved counts (teams/projects/entities/
  edges/entries) at **1/1/6/5/0**. Temporary synthetic source bytes verified scope,
  hint lookup and changed-digest refusal. No device was opened.
- Independent code/Python/TypeScript and security review findings were addressed:
  retired CONFIG authority, private error leakage, and CAN hint selection. The
  proposal to prohibit historical same-file aliases was rejected because it breaks
  the explicitly approved relink model; normal new picks still reuse a known ref.

Logs reside under `/tmp/solus260-phase3-*`; these ephemeral logs are supporting
local evidence rather than committed artifacts or a claim of CI execution.

## Live boundaries

The live database is `solus`, on this task's container `solusdev-260-db` and volume
`solus_pgdata`, PostgreSQL 5432; Redis 6379; API 8000; browser renderer 5173.
The live API was restarted from this checkout after integration and readiness
reported the database healthy. Only this task's verified API process was stopped.

The browser enumerated both actual adapters and showed the native-only source
picker unavailable, as intended. Host serial mapping is `/dev/ttyACM1` →
`5B42135040`, `/dev/ttyACM0` → `5B42134331`. The user tentatively identified 1 as
leader and 0 as follower. Enumeration does not verify protocol, roles or streaming;
no motion was performed. This checkout's Electron app was launched with a separate
profile to enable account connection and native picker checks. Native picker,
real calibration relink and integration sync remain human-dependent live checks.

The initial live graph contains six legitimate `.solus` nodes, five edges and no
CONFIG entries. Historical migration evidence is PostgreSQL fixtures plus the
snapshot-backed live migration from Phase 2, not invented historical live rows.
Legacy unversioned PUT remains a compatibility surface; the renderer uses v2
optimistic concurrency. File parsing/proposal expansion remains the later B2 scope.
Ponytail is unavailable; independent reviewers provided the code simplification
and security passes. No remote operation or other worktree modification occurred.

Standalone creation, first-save of an absent CONFIG and connection-owner part
session creation have API/fixture coverage but no dedicated renderer caller. The
existing CONFIG editor edits records created through hardware confirmation or
other API flows. These UI limits are explicitly called out in the QA walkthrough.

Final test-only additions passed code/Python/TypeScript review. Both coverage-audit
gaps are closed. The API suite includes the vendor-hygiene ratchet; Live Bench
includes its vendor and three-machine tests. All four requested suites have green
executed-case evidence, with skips and native/human prerequisites retained above.
