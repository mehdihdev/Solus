# SOLUSDEV-260 Phase 4 — SOL integration

Status: integration implemented and reviewed; live limitations are listed below.
Phase 3 committed as `b004c99` after 4852 API tests passed (7 skipped), plus later
focused coverage additions. Incoming commit is `a43578c`; 250 is not merged yet.

## Integration decisions

Twelve conflicted files were reconciled, including generated clients and added
CONFIG rendering tests. MAIN retains private-source state alongside SOL window,
tray and hotkey state. The merged runtime retains I3 resolver registration and
license-scoped preview readers; confirmation retains tool-knowledge feedback and
uses one generic error recorder. Both Python dependencies remain. The user-approved
hello bound is 256 KiB, distinct from control frames, with oversize close 4413.

The solus API plan keeps graph context on text/artifact entries, permits CODE
records through generic POST, and keeps hardware configuration writes on v2 routes.
CODE records use existing solus_note graph identities; hardware_config is reserved
for HARDWARE. Their create/upsert/delete lifecycle cannot alter hardware configs.
A CODE deletion confirmation names the record and leaves the local environment.
Nullable host facts reflect missing I3 observations rather than an invented host.

SOL hardware field writes now use independent v2 documents. Existing argument/path
forms are mapped to the owned subject, with a bounded one-use preview snapshot
checked under the project lock before expected-version writing. Diagrams use the
runtime aggregate; config/build/render failures produce portable tool errors.

## Evidence so far

- Section/UI failures reproduced before fixing: two CODE rendering regressions,
  first v2 payload validation and CODE graph-kind failures, CODE deletion-menu gap.
- Root focused UI suite: 31 passed. Graph/section/retired-config suite: 24 passed.
- Live database rollback exercise proved CODE create/upsert/delete leaves hardware
  runtime exactly unchanged; baseline counts remain teams/projects/entities/edges/
  entries **1/1/6/5/0**. No hardware was opened and no synthetic graph data persisted.
- Full merged desktop suite: **3386 passed, 322 files**, on host (loopback/process
  tests available). Workspace TypeScript checks and desktop production build passed.
- Hardware SOL/diagram suite: **35 passed**, plus the later descriptor regression.
  Independent code/Python/security review
  approved direct v2 preservation, tenant/ownership checks, bounded preview cache,
  final-preview race protection, and sanitized diagram failure.
- Provider seeder executed against verified local encrypted storage in `solus:5432`.
  All four configured refs seeded and `--check` passed. No credential values printed.
  This is storage evidence, not a paid live provider-turn claim.
- Read-only retained-fix audit found Responses replay/usage, cloud-owned fork rules,
  hello sizing, research, datasheet extraction and seeder/startup checks intact.
  Actual registry.invoke sites remain runtime and confirmation handling only.
  Incoming prose does not enumerate eleven defects consistently; retain and test
  concrete behaviors rather than inventing an eleven-test count.
- Environment integration slice: **124 passed**; final adapter preservation tests:
  **13 passed**; runtime annotation follow-up: **21 passed**. Final companion/I3:
  **469 passed**. Named probe alone: **196 passed**. Failed package inspection returns
  unavailable facts, a successful empty inventory remains valid, and unavailable
  re-probes leave saved CODE records unchanged. Named linking and recording probe
  the exact target. Fresh code/Python/security re-review approved both fixes.
- Repository Ruff passed. Clean strict mypy passed **319 source files** after the
  merged, hash-pinned PDF dependency was installed; stale import-cache results were
  discarded through a non-incremental check, without relaxing type checks.
- The updated desktop and API booted on this task's existing ports/profile. All
  five installable forks were materialized from pinned dependencies. Companion
  correctly leaves Brave to the cloud. The user selected
  `/home/beeboss/Desktop/ForgeTS` as the local workspace; desktop was relaunched
  with that process-level setting, without editing any `.env`.
- User connected GitHub and Onshape and selected real sources. Read-only audit:
  **167 entities / 164 edges**, including 135 code files, 21 code modules, three CAD
  parts, one repository, one CAD document and six `.solus` nodes. This supersedes
  the earlier empty baseline; none of the new real data was pruned.
- Live SOL first returned a response; UI displayed `sol-reasoner-1` and five credits
  were debited. A subsequent turn streamed successful `solus.verify_integration`
  twice and `onshape.list_documents` once, then reported the reasoning service busy.
  Six more credits were recorded (11 total). Persisted metadata does not establish
  whether the transient provider error was a timeout, rate limit or upstream fault.
  This verifies live provider/tool use and billing, not a completed tool-turn answer.

The incoming 252 completion report is historical: its seven machine tools and
multi-environment inventory claims are superseded by the I3 integration described
here and in the updated architecture/API documents. Only workspace venv facts
actually observed by I3 are linked; unsupported host/conda/Docker facts stay absent.

## Final verification follow-ups

- Full API run on four isolated workers: **5175 passed, six skipped**, with two
  failures. An obsolete real-machine preview test called removed `run_command`;
  a worker exited during the duplicate migration-constraint case. Duration 20m53s.
  The preview test now exercises real I3 planning through the bridge and asserts
  exact argv, working directory, fingerprint and zero command execution; both tests
  in its file passed. All five migration constraint tests then passed serially
  and with four workers. Every initially failed case has passed on recheck; the
  original worker exit remains unexplained, without OOM or shared-test-DB evidence.
  Preserve this distinction from a single uninterrupted green full-suite run and
  watch the constraint case again during combined Phase 6 verification.
- Coverage audit of five integration files used existing tests (252 passed, then
  a corrected API-only selection of 56 passed). Combined statement/branch coverage:
  I3 probe 100%, server 87.5%, adapter 90.09%, SOL tools 91.85%, diagram tool 90.28%.
  This is targeted coverage, not a repository-wide percentage. Added meaningful
  negative cases then passed: 21 adapter tests and 20 diagram tests, both independently
  reviewed. They prove failed/unknown exits never overwrite CODE and invalid robot
  references cannot leak configuration or mutate rows.
- All **476 Live Bench tests** passed; live DB current and only Alembic head both
  remain `a26000000003`.
- Live companion popover reports altium/code/kicad/local/machine READY; altium
  requires a license upgrade, Fusion ERROR after three start attempts. Missing
  AutoCAD/SolidWorks launchers are reported, not invented as available. Brave stays
  cloud-owned. Native hotkeys/gesture remain unverified by the browser-only UI tool.
- A graph-derived SVG was created and filed to Documentation through the UI:
  `Follower wrist — graph evidence`, one node and no wiring relations. This is
  an honest diagram of available CAD graph evidence, not a verified servo wiring
  diagram. Artifact `01a08e94-6ea4-7709-a989-2bd76a9e4b05` is retained, 994 bytes.
  The restarted API preserves its existing storage via process setting
  `SOLUS_ARTIFACT_LOCAL_ROOT=/tmp/solus-artifacts-5vtdd9rv`.
- API logs additionally establish `text-embedding-3-small` access denied (403)
  for the configured OpenAI project. The reasoner logs rate-limit/overload retries
  exhausted. At the user's request, Think harder selected existing catalog model
  `gpt-6-astra` for a standard request (hard tier); ledger confirms `general_hard`,
  18 credits at 2026-09-11 03:57:05 UTC. Astra hit the same retry exhaustion.
  No model catalog or `.env` was changed; no further paid retries are being made.
  Creating/installing `sim` and Brave/page-cited extraction remain incomplete.

## Live limitations carried into combined verification

The provider failures prevent completing the environment install and page-cited
datasheet turns. Native hotkey/gesture checks require a person because the available
UI automation controls only the browser. Physical-arm wiring, motion, port-swap and
reconnect checks have not been performed. Both integration accounts and selected
real sources are connected, but the graph currently contains one CAD document,
not the requested four-document demonstration. No synthetic graph nodes were added
to satisfy that count. The filed diagram is derived from the user's real CAD node.

Ponytail is unavailable in this session; independent simplification, code,
Python/TypeScript and security reviews were used. No remote git action, main-branch
edit, hook bypass, `.env` edit or access to another worktree occurred. The explicitly
authorized ForgeTS folder is the local user workspace for companion tools.
