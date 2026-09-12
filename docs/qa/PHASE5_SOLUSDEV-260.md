# SOLUSDEV-260 Phase 5 integration record

Status: integration implemented and reviewed; combined verification is recorded below.
Live prerequisites remain explicitly unverified where noted.
Input: SOLUSDEV-250 `3661e6d`, merged after Phase 4 `0f0157e` on the ticket branch.

## Governing design

Read and reconcile `docs/api/hardware.md`, `docs/architecture/hardware-onboarding.md`,
`docs/architecture/workspace-navigation.md`, `docs/wireflows/hardware-onboarding.md`,
and `docs/wireflows/workspace.md`. Per-entity v2 CONFIG, explicit private-source
relinking, CODE environment ownership and the existing SOL action gates remain
authoritative. The asynchronous connection contract is documented in the API plan.

## Root changes and evidence

- One idempotent application console handler preserves instrumentation and emits
  confirmation timing fields. Arbitrary structured extras are excluded. Two new
  tests failed at the missing module before implementation, then passed.
- Application lifecycle uses exception-safe cleanup in watcher → coordinator →
  sessions → graph-hub order. Three tests reproduced startup, lifespan-body and
  cleanup failures before the fix.
- Onshape labels prefer provider display name, then provider email. The current
  read-only live grant supplies neither, so the UI uses “Onshape account” rather
  than an opaque identifier. Existing stored opaque labels are normalized in API
  serialization; the underlying provider identity remains intact for matching.
  No OAuth scope expansion or substitution of the Solus user's email occurred.
- The actual launcher is `scripts/dev-all.sh`; this repository has no `dev-up`.
  It resolves the root configuration without shell evaluation, checks only its
  configured application ports, and refuses occupied listeners before starting
  services. A bind probe detects listeners hidden from process inspection. Local
  Compose DB reuse requires a matching running service; configured external DBs
  skip Compose. Failed DB startup/readiness stops application launch. Cleanup
  remains restricted to child process groups started by this invocation.
- Root focused suite: **109 passed**, log `/tmp/solus260-phase5-root-green.log`.
  Later launcher regressions, including IPv6 listeners: **18 passed**, log
  `/tmp/solus260-phase5-launcher-final2.log`. These overlap and are not a
  combined unique test count. Root Ruff and strict mypy passed on 11 files.
- Full Live Bench suite for the incoming detection changes: **523 passed** in
  18.30 seconds, log `/tmp/solus260-phase5-livebench-full.log`.
- Full desktop suite after review fixes: **3,595 passed** across 345 files,
  log `/tmp/solus260-phase6-desktop-unrestricted.log`. Desktop type checks and the
  development build passed; OpenAPI and TypeScript schema were regenerated.
  Review regressions cover unplug/replug while probing or confirming, synthetic
  account anchors excluded from SOL focus, failed focus, and honest connecting
  versus connected status. Fresh code review cleared those changes.

The real configured application ports resolve to API 8000 and desktop 5173.
The local database remains `solus`; tests use isolated `solus_test_436a6e18_*`
databases. No environment file was edited.

## Final review and verification

Fresh code and dedicated security reviews passed after fixing runtime ownership,
threaded acquisition cancellation, Stop/delete races and stale account/project
callbacks. Lifecycle coverage is 89% aggregate (connections 87%, owner 88%, sessions
93%); the final lifecycle selection passed 45 tests. Backend focused suite passed
123 tests. Python review guidance was applied by the security reviewer; the
separate Python reviewer could not be spawned because of the session agent limit.

The full root ESLint pass found seven complexity violations in Phase 3 private
source code and one in NodeSidebar. Behavior-preserving extractions passed the
35 existing private source/state tests before and after, and fresh security review.
Root ESLint now has zero errors (145 existing warnings). Ruff passes; strict mypy
passes across 406 source files. The six pre-existing format-only files were
recorded separately in `1fff63d4`, with unchanged Python ASTs.

Native Electron QA exposed a stale sidebar timing mark: revealing a later entity
could reuse a completed click and report a bogus 35-second duration. A new test
failed, then passed with the mark consumed after measurement (17 sidebar tests).
The rebuilt live desktop measures the actual robot selection at 2 ms.

The first API full run was deliberately interrupted after 1,068 passes and one
skip because review found additional cancellation/session-ended cases. The initial
combined non-live run completed with 7,156 passes, two skipped, one expected failure
and two worker crashes in migration fixtures. PostgreSQL logs traced these to
DROP DATABASE forcing cluster-wide checkpoints, including 258,576 files and
631.4 seconds, exceeding pytest's 300-second per-test timeout.

Migration tests now derive a separate database per checkout, isolated run base and
worker, reset its schema before/after each case, and retain it empty. No assertions
or timeouts were weakened. Both URL derivation and reset reject query parameters
before connecting, closing a database-override issue caught during fresh review.
Transition tests passed 37 cases; targeted safety guards passed 10. Code/Python and
security/database reviews passed. The final combined run passed **7,169 tests**,
with two skips and one expected failure, no worker crashes, in 1,045.21 seconds.
See `COMPLETION_SOLUSDEV-260.md` for the final per-gate evidence and skip reasons.

The H10 stop hook's database configuration remains a protected-file limitation.
The task requests a worktree-scoped test DB override, but repository rules forbid
agent edits to hook implementations. It was neither edited nor bypassed.

## Live verification

The rebuilt actual Electron desktop was exercised with its real companion and
connected accounts. The follower (USB serial 5B42134331) was identified as six
STS3215 servos and confirmed through the UI. Accepted mapped telemetry appeared in
Live Bench: channel 1 position 2126, load 0 and temperature 30, with rolling charts.
No motor movement command was sent. A session-open response alone was not counted
as telemetry evidence.

The confirmation cache had expired during inspection: proposal 2.023 s, database
write 0.1383 s, inline session time 0.0 s. This verifies asynchronous opening but
not the sub-500-ms cached-confirm target. The populated graph grew legitimately
from 168 entities/166 relations to 189/200; graceful API shutdown and restart
preserved those counts and changed the owned robot from Connected to Disconnected.
The API completed its shutdown after the open browser SSE connections were closed.

The account sidebar shows Onshape account and its actual CAD document; Add another
opens Integrations with both real account labels. The new source label also reads
Onshape account after restart. Historical activity retains the original audit text.
The robot sidebar opens a separate SOL window. Unassigned parts lists three actual
CAD entities; two share a display name but have distinct IDs. Delete/Keep was
exercised without deleting the live robot. The private source picker is present.

The requested Astra attempt was made in Phase 4 through Think harder and confirmed
as `gpt-6-astra`; it exhausted rate-limit/overload retries. The configured project's
denial of `text-embedding-3-small` is a separate embedding permission failure.
No model catalog or environment changes were made to conflate the two capabilities.

Still unverified: leader protocol/telemetry (5B42135040 visible but no servo answers;
power/cabling question pending), physical port swap/unplug/reconnect, serial-less
physical board, four-document canvas (one CAD document and one repo supplied),
private calibration relink without a supplied file, global hotkeys/gesture from
another application, and provider-dependent environment install/page-cited Brave
turns. See the combined completion report for the per-gate distinction.
