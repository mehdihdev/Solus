# Onshape quota and assembly acceptance — SOLUSDEV-261

This is an acceptance checklist, not a record of completed live tests. Use the
separate quota audit for observed results and blockers. Do not reset provider quota
or bypass confirmation/authentication boundaries to make a check pass.

## Historical starting evidence

The baseline below predates successful FeatureScript, trigger/wrist-pitch mating
and nested-connector checks. See the live checkpoint at the end and
`ONSHAPE_QUOTA_AUDIT_SOLUSDEV-261.md` for current results. Live CAD testing is
paused at the user's request with the 70% conservation threshold unchanged.
The pitch-servo rigid mount still needs historical pose restoration.

T1 revision repair and T2 six-site immutable feature-spec caching are reviewed and
committed. Focused suites passed: T1 159; T2 320; grant/quota 45 + 74. A verified
application refresh bound one development connection/source. One normal metered
REST document GET returned one item, increased the applicable meter by one, and
reported status `ok`; old application records/counters were untouched. Earlier
401/402 logs are historical. Fresh Home verification after restart shows Onshape healthy and FeatureScript
ready, with at least 1/1800 estimated usage. Actual SOL document/element/assembly
reads succeeded; Leader has 16 top-level instances, 23 occurrences, no features
and all fixed flags false. Full Hand plus Leader later imported 641 entities,
exceeding 50 translated Full Hand tabs. Its 42 optional metadata warnings exposed
an assembly-only request bug, now fixed with 107 passing connector tests and
independent review. Revolute implementation passed 124 tests; root observation
flags/topology IDs passed 60. Actual mating and persistent FeatureScript geometry
remain open. SOL's bounded historical evidence repair passed 122 focused tests;
a live historical follow-up worked, while a truncated older assembly payload was
explicitly reported unavailable. The earlier merged affected suite passed 591 tests in 19 files, with
Ruff/mypy passing for 14 source files. Do not mark the walkthroughs below passed from these narrower checks.

## Setup

- [ ] Start `pnpm dev:all`, PostgreSQL, Redis and the normal ARQ worker; apply the
  repository migrations. Sign in to Solus and select the acceptance project.
- [ ] Connect Onshape with the existing Read/Write grant. Complete FeatureScript
  setup using only its admitted scopes. An expired or broader grant must produce a
  reconnect/refusal state, never silently authorize extra permissions.
- [ ] Use authorized disposable CAD for destructive/failure cases. Keep Leader's
  existing parts, features and placement; record its starting assembly state.
- [ ] Select Leader and Draw Piece. Prepare a document with at least 26 exportable
  tabs for the larger-import check. Have one tab contain known simple geometry.
- [ ] For webhook tests configure the existing public API base URL to a reachable
  HTTPS deployment. Localhost is not externally reachable and must report webhook
  delivery unavailable. Never paste callback tokens into reports.

## Import and graph preservation

1. Import the 26-tab document using the source sync UI.
   - [ ] All expected entities are indexed; the old 25-tab rejection is absent.
   - [ ] Record source revision and entity count, then inspect known geometry.
2. Exercise a controlled failure on the final tab using the test transport/fixture.
   - [ ] The entire sync fails and prior graph/cursor remain intact.
   - [ ] No changed-only snapshot tombstones unrelated entities.
3. Exercise the configured element, record and byte bounds using fixtures.
   - [ ] Limits fail explicitly, without unbounded staging or a partial graph.
4. Import a mixed Assembly/Part Studio selection.
   - [ ] Assembly tabs never request the Part Studio `/parts` metadata endpoint.
   - [ ] Assembly geometry and hierarchy survive; Part Studio enrichment still works.
   - [ ] A real Part Studio metadata failure remains an explicit optional warning.
5. Repeat acquisition of an unchanged selection and record transport calls.
   - [ ] Cached immutable payloads avoid repeat translations.
   - [ ] An export over the configured cache-entry size is explicitly distinguished
     from cached payloads; do not claim it is retained or free to reacquire.

## Revision and grant isolation regression walkthroughs

1. With mocked transport, plan revision A, then change the workspace before
   translation or during its download.
   - [ ] Drift refuses the complete sync; prior graph/cursor survive.
   - [ ] No mismatched export cache entry or automatic translation retry appears.
   - [ ] Element and metadata GETs use revision A `/m/` paths.
   - [ ] Empty/invalid revision IDs issue no immutable GET or cache entry.
2. Sync a source with the old projection marker, without editing its CAD.
   - [ ] One repair ingestion uses `revision-v2-*` entries and persists
     `cad-geometry-v2` only on success; a subsequent unchanged sync skips.
   - [ ] Cold translations spend two fresh revision GETs; warm verified exports
     need neither translation nor bracket reads. Positive empty proof is retained.
3. Repeat get-specs/add-preview/add/sketch/cut/mate fixture workflows.
   - [ ] All six use specs at the freshly read tree revision, never cached workspace
     specs relabeled with an earlier revision.
   - [ ] Same-key previews reuse one spec GET; changed revision/account/collection
     misses. Mutable trees/geometry remain fresh and stale approval is refused.
   - [ ] Error, partial, malformed parameter and nonfinite responses are not cached.
4. Exercise verified OAuth application and account isolation through existing routes.
   - [ ] Only successful grant verification binds application identity to the
     connection/source; changing settings alone does not rebind historical grants.
   - [ ] Same-application secret rotation retains usage; another verified
     application/account has its own scope without deleting old records.
   - [ ] Legacy unbound grants retain their prior accounting; quota health uses
     the same identity as request metering. No counter reset is part of recovery.

## Webhook delivery and recovery

1. Sync a tracked document through the normal worker on the public deployment.
   - [ ] Vendor registration uses the existing source/account authorization.
   - [ ] Registration alone does not claim verified delivery health.
2. Edit the document externally; inspect graph state after the notification.
   - [ ] The changed revision is observed even if the previous signal cache is warm.
   - [ ] The healthy subscription removes routine microversion polling.
3. Deliver a duplicate event and two events while a reconciliation is running.
   - [ ] Duplicate identity produces no extra dirty generation.
   - [ ] The later generation remains pending and is reconciled after the first run.
4. Simulate enqueue failure, then let the local recovery sweep run.
   - [ ] Dirty work survives; recovery honors existing provider rate/quota deferrals.
5. Revoke the account while old subscriptions are being removed.
   - [ ] Local callback authority is invalid immediately; no new registration starts.
   - [ ] Remote cleanup failure is recorded without making the source healthy.
6. Examine normal and error request logs using a synthetic callback token.
   - [ ] Token and query strings are redacted in access/error/traceback output.
   - [ ] Wrong token, malformed body and untracked document never authorize graph work.

## Write costs and freshness

1. Request two previews against the same immutable donor part revision.
   - [ ] Donor body geometry is fetched once; target assembly/tree are read fresh twice.
   - [ ] Switching account or donor revision does not reuse the old cache entry.
2. Execute authorized ordinary writes through SOL Build mode.
   - [ ] Successful writes queue/coalesce reconciliation; graph stays stale until verified.
   - [ ] A failed readback is not reported as success and is not automatically replayed.
   - [ ] An uncertain hosted mutation is never retried through REST as a fallback.
3. Record actual request counts, retries, transport and source syncs for each action.
   - [ ] Public App Store REST exemption is distinguished from any observed MCP
     service restriction. No guessed annual entitlement is displayed/enforced.

## FeatureScript live proof

1. Read current hosted inventory through the connected account.
   - [ ] Only reviewed tools are admitted; unsupported native operations remain explicit.
2. Ask SOL to create a named disposable Feature Studio, write a simple custom
   feature, test/execute it, and create its intended geometry using supported tools.
   - [ ] Read back the actual source and vendor execution result.
   - [ ] Inspect generated part geometry and record document/workspace/element IDs.
   - [ ] If the operation branches a workspace, report that branch explicitly.
   - [ ] Listing studios or reconnecting alone does not count as execution acceptance.

## Leader assembly live proof

### Required autonomous SOL acceptance

1. Start a fresh SOL Build chat with only “In the Leader document, can you add
   mates on the specific joints of this arm?” Do not supply developer-derived
   edge IDs, axes, joint pairs or a tool sequence.
   - [ ] Record elapsed time, tools and provider requests.
   - [ ] SOL inspects its own available CAD evidence and identifies candidate joints.
   - [ ] If it asks which joints, use only “Inspect the arm and work out which
     joints need mates yourself, preserving its current assembled position.”
2. Observe SOL's execution and independently verify its reported result.
   - [ ] Report exactly which mates exist and which joints remain unsupported.
   - [ ] Compare before/after poses and feature health; no false completion claim.
   - [ ] Do not self-approve any explicit card. Ordinary reviewed Build admission
     may execute through its existing policy.
   - [ ] A developer's separate geometric analysis or direct API write does not
     count as SOL autonomous acceptance.
   - [ ] Distinguish numerical CAD observations from screenshots actually delivered
     to the model. An image visible only to the tester is not SOL visual evidence.

1. Read Leader's current assembly instances, transforms, geometry and existing mates.
   - [ ] Identify each intended joint from actual faces/axes and part roles.
   - [ ] Present the proposed base and joint relationships with uncertainty made explicit.
2. For each supported joint, use its verified vendor schema and SOL's normal gate.
   - [ ] Do not replace a revolute/sliding joint with a fastened mate.
   - [ ] Stop only the ambiguous joint for clarification; preserve verified independent work.
3. Read back every resulting mate and inspect assembly motion/remaining degrees of freedom.
   - [ ] Intended movement is retained; rigid subassemblies stay rigid.
   - [ ] No duplicate instances, orphan mate connectors or unintended placements appear.
   - [ ] An HTTP 503 is reconciled by readback before any insertion/mate retry.
4. Record actual pass/fail for insertion, each joint type, readback and visible motion.
   - [ ] Never mark full assembly acceptance based solely on a successful POST.

## OAuth application replacement recovery

- [ ] With a linked Onshape account showing healthy, degraded, or exhausted quota,
  open Home → Mechanical → Onshape. Re-authorize remains available without an
  authentication-error warning being invented.
- [ ] Click Re-authorize in the native desktop app, then Connect Onshape. Select
  Read and edit and complete the vendor consent for the configured application.
  The existing account-scope handshake replaces the grant only after successful
  authorization. No revoke or document-selection change is triggered by opening it.
- [ ] Cancel sign-in: existing credentials, source selection and usage remain.
- [ ] Browser-only attempt reports that the desktop app is required. Reauthorization
  itself does not reset quota counters or imply that the provider's allowance renewed.

## Live acceptance checkpoint and recovery regressions

- [x] Full Hand imported beyond 25 exportable elements.
- [x] Persisted FeatureScript cylinder independently read through SOL: one solid,
  2 mm radius, 5 mm height, 62.83185307179588 mm³ volume.
- [x] SOL independently selected the trigger/servo pivot and created two connectors.
- [x] SOL creates and verifies the corresponding revolute mate; all 23 occurrence transforms unchanged.
- [x] SOL inspects nested/coaxial interfaces and distinguishes likely actuator axes
  from mounting holes without developer-provided joint IDs or types.
- [x] Normal manual recovery clears the old export-race error: 51 entities updated,
  zero errors, 646 entities retained (2026-09-14 01:16:47 UTC).
- [x] Native nested connectors round-trip with exact occurrence and ancestor identity.
- [x] Nonzero offsets preserve the original pose, with authoritative native readback
  (wrist pitch, approximately -1.9 mm; all 23 poses unchanged).
- [x] Multiple Build writes defer graph reconciliation until turn completion and
  automatically update the graph once without an export/write race.
- [ ] Same-direction wrist-roll axes execute with the measured primary-axis flip
  and preserve the original pose.
- [ ] Correct the failed pitch-servo rigid mount against the saved historical pose;
  verify all occurrence matrices independently before continuing CAD writes.
- [ ] SOL determines and completes remaining rigid and moving arm connections.
- [ ] Verify all occurrence poses and intended remaining freedom; connector
  creation alone does not satisfy either joint or mechanism acceptance.

1. Read a large assembly whose instances exceed the normal tool-result cap.
   - [ ] SOL can select the complete feature view and receive existing connector
     IDs, explicit current health and actual world frames without truncation.
   - [ ] Continuation preserves complete rows and rejects actual revision/pose changes.
2. Use an imported body and returned assembly feature with `+` or `/` in its ID.
   - [ ] JSON references and readback work; malformed resource URL IDs still refuse.
3. Change the document while a graph export is underway.
   - [ ] The snapshot fails closed; no partial graph is published.
   - [ ] Live tools remain available only under the valid current account/grant.
   - [ ] A subsequent normal sync reacquires its revision instead of trusting the
     known-stale signal. Auth/revocation failures must still refuse.
4. Inspect valid donor geometry between 8 and 32 MiB.
   - [ ] Inspection succeeds without cache storage; subsequent reads may refetch.
   - [ ] Unrelated floating-point face-area metadata does not invalidate circle pages.
   - [ ] Actual circle geometry, root pose, revision or filter changes do invalidate them.
