# Onshape quota and routing audit — SOLUSDEV-261

## Latest acceptance status — 2026-09-14

**Current open correction:** the later `Pitch servo rigid mount` fastened mate
rotated occurrence `MohrVl3240lE6NFIf`; SOL incorrectly described its pose as
preserved. Independent matrix comparison found a maximum entry difference of
1.0. Full-frame rigid-mate admission and historical correction are integrated and
reviewed. The first live correction request returned `unavailable` during preview
and executed nothing. Its underlying cause is `quota_degraded`: the local meter
reached 1,260/1,800, exactly the configured 70% threshold. No provider 402 latch
or exhaustion is observed. The user explicitly chose to keep 70% and pause live
CAD testing. No threshold adjustment or counter reset was made. The original pose
is still unrestored; this is an acceptance failure, not a completed rigid-mount
check. Resume with correction and independent pose verification before new mates.

FeatureScript persisted geometry and the larger Full Hand import have passed
their live checks. SOL independently selected and created the trigger revolute
mate in Leader; native readback reports healthy connectors and mate, and all
23 occurrence transforms match the pre-mate state exactly. Wrist-pitch mating,
nested inspection and nested connectors also passed the checks below. Remaining
base, link and wrist-roll connections are still open. These current results
supersede the earlier open checkpoints retained as the audit trail.

Turn-level reconciliation deferral is committed in `94eaa519`, with independent
code/security review passed. Its focused tests cover hold admission, concurrent
owners, expiry, worker races and cleanup; live turn-end recovery passed below.
No full-mechanism motion acceptance is claimed.

Live manual recovery then succeeded in sync
`01a09d7b-5ecd-77dd-a509-dda674e3ad7d` at 2026-09-14 01:16:47 UTC:
51 entities updated, none created, zero errors, 646 entities retained. Home showed
connected and FeatureScript ready. This proves recovery from the earlier export
race; automatic turn-end reconciliation was still pending at that checkpoint
and passed in the subsequent write test recorded below.

The new nested inspection passed a real SOL read-only continuation. SOL identified
likely base, arm-pitch, wrist-pitch and wrist-roll revolute interfaces and rejected
small off-axis mounting holes as pivot candidates. It reported uncertainty about
some component names and made no writes. Several selected references have axial
separation; a pose-preserving offset must be verified before mating those pairs.
The integrated geometry/reconciliation run passed 176 tests across ten files.
Node lint also exited zero: zero errors and 152 existing warnings.

The subsequent SOL build created `Wrist pitch revolute joint`
(`M2FzoUq3uVnFQHpIS`) with native offset expression
`-0.0018999999999999677 m`. Independent readback found both revolute mates healthy
and every one of the 23 occurrence transforms exactly unchanged. Automatic
turn-end reconciliation completed at 01:43:06 UTC in sync
`01a09d93-9c80-7a06-82e4-af2c532c4093`, updating 51 entities with zero errors.
The reused enqueue path stores trigger `manual`, but the ARQ trace shows it was
dispatched by turn cleanup without a user sync click. Connector verification
initially falsely rejected legitimate same-document revision advancement; SOL
reconciled existing features without replay, and `8ae3aaf2` corrects that check.

Later root and nested wrist-roll connectors round-tripped successfully. Their
same-direction axes exposed the former opposite-axis-only revolute limitation;
measured flip selection is implemented but its false-flag case awaits live proof.
Desktop tests passed 3,726/3,726, Node type-checking passed, and script tests passed
25/25. The broad API suite completed with 6,727 passed, six skipped and one
failure: the local KiCad write test used the obsolete direct-write protocol and
received `stale_plan`. That test was corrected to observe the fingerprint, verify
two non-mutating previews, execute with the same binding and read back the result;
its isolated rerun passed with independent review. Production gates are unchanged.
The broad run began before the final rigid correction changes; their focused
verification is separate. Counts above overlap; this is not a claim that the final
tree received another full-suite run.

## Current checkpoint (T1/T2 and verified grant continuation)

T1 revision acquisition (`79e4e25d`) and T2 feature-spec caching (`bc70d621`)
passed independent code/security reviews. A successful refresh with the registered
OAuth application verified the grant binding. One development connection and its
source are bound to that verified application; old records remain untouched.
A normal metered REST document GET returned one item, incremented its applicable
meter by one, and reported quota status `ok`. This is current REST evidence, not
a reset of old counters or proof that all document operations succeed.

Fresh Home verification after restart shows Onshape healthy and FeatureScript
ready, initially with at least 1/1800 estimated REST usage. Home later reported
at least 492/1800 after larger-document acquisition; neither number is a provider
remaining balance. Persistent FeatureScript body/feature inspection and Leader
mating remain open. Historical 401/402 captures below describe earlier grants and
accounting scopes; they are not the current grant's observed REST status.

Current focused verification: T1 **159 passed**; T2 **320 passed**; grant/quota
suites **45 + 74 passed**, with independent reviews passed. T1 connector coverage
was 92%; T2 immutable read cache coverage was 93%. The older 967-test and full
6340-test runs later in this audit are historical, not a fresh full-suite result.

### Latest product reads and merged verification

The actual SOL tools `list_documents`, `list_elements`, and
`get_assembly_definition` succeeded. Scoped redacted evidence is stored locally in
`/tmp/solus261-onshape-live-evidence.json`. Leader's document is
`48cfe61c1144861fcbfa6bdb`, workspace `d1a5721b91c10b28bcb71214`, root assembly element
`5a91135dde16c0094005d7ff`. Readback contains 16 top-level instances, 23 occurrences,
no assembly features, and all observed fixed flags false. These are structural
reads. Subsequent immutable body inspection found six candidate coaxial joint
pairs; these are geometric candidates, not verified mates. No mates have been
added at this checkpoint.

SOL initially failed to summarize after five tool rounds. The repaired runtime
reserves its final existing model call for tool-free synthesis, and bounded,
redacted historical tool evidence is now reconstructed without approval metadata
or authority. That change passed 122 focused tests and independent review.
Live follow-up correctly identified Leader from historical evidence without new
tools; the older large assembly payload was omitted by the history bound, and SOL
explicitly reported that omission. This does not prove retention of unlimited
geometry payloads. Earlier merged verification passed **591 tests across 19 files**, plus Ruff
and mypy for **14 source files**. This remains an affected-suite result, not a new
full-repository test run.

### Larger-document and assembly continuation

Full Hand plus Leader completed normal UI import in sync
`01a09cfc-500b-78dc-b55d-7e5b627a93e7` at 2026-09-13 23:03:50 UTC, creating
641 entities. More than 50 distinct Full Hand tabs were translated, exceeding
the old 25-tab cutoff. All 42 recorded warnings concerned optional part metadata;
there were no recorded geometry failures. The invalid Part Studio metadata GET
on assembly tabs is fixed in `3194184f`, with 107 connector tests and independent
Python/code/security review passed. Assembly STEP structure remains intact.

Two earlier imports were interrupted when Electron's GPU process terminated
the combined dev stack. Narrow development-only recovery marked those verified
orphaned jobs failed without changing graph data, credentials, quotas or Redis
claims. The successful acceptance ran API, worker and renderer independently.
Automatic orphaned-sync recovery remains a separate product limitation.

Revolute mates (`d93da19a`) passed 124 focused tests and independent review;
assembly include flags and bounded opaque topology IDs (`8745c344`) passed 60.
The immutable spec cache also accepts valid conditional parameter variants in
unrelated vendor features while preserving strict selected-write validation
(`197b338e`, 320 affected tests). Complete-circle connector implementation and
live trigger-joint placement verification remain in progress.

One Full Hand STEP payload exceeds the existing 8 MiB cache-entry bound and is
not retained. Selection expansion can therefore re-export that tab even at an
unchanged revision. Other immutable payloads remain reusable. This is a known
bounded-cache limitation, not evidence that every unchanged tab was re-exported.

### Actual SOL autonomy test (user-corrected acceptance)

Developer geometry investigation above is not evidence that SOL can reason about
an assembly. At the user's clarification, a fresh SOL Build conversation
`01a09d13-2c8d-7c09-b3b4-e59d432ed67f` received only:
“In the Leader document, can you add mates on the specific joints of this arm?”
The request started at 2026-09-13 23:21:14 UTC. SOL called list_documents,
list_elements and get_assembly_definition, then asked which joints to mate.
No developer joint IDs, axes or candidate pairs were supplied.

At 23:22:03 UTC the sole clarification was: “Inspect the arm and work out which
joints need mates yourself, preserving its current assembled position.” SOL made
seven read-tool calls (document/element discovery, four assembly reads and a part
list), then reported that its tool window ended before identifying matching
joint geometry. It created no mates or pending approvals. The saved redacted
trace is `/tmp/solus261-sol-autonomous-mates.json`.

This is a failed end-to-end autonomy test. The existing limit of five model
rounds reserves the fifth for synthesis, and the transport separately allows only
eight tool calls. The existing Onshape tool path has no image operation supplying
a screenshot to SOL. Bounded Build headroom and compact numerical assembly
inspection are being implemented; successful low-level mating tests do not
substitute for repeating this natural-language acceptance.

### Current acquisition and spec costs

- Elements and metadata use validated immutable `/m/{revision}` routes. Cold
  workspace STEP translations are bracketed by two uncached revision reads;
  drift aborts the snapshot, publishes no mismatched export, and is not retried
  automatically. Immutable empty-geometry proof remains required.
- `revision-v2-*` payload keys exclude older associations. `cad-geometry-v2` forces
  one successful repair ingestion for existing nonempty tracked sources. Verified
  warm payloads are reusable without translation or bracketing calls.
- All six spec sites are wired: get specs, add preview, add execution, sketch,
  cut and mate observations. Each selects `/m/` specs from a fresh feature tree;
  account/document/element/revision/collection/default-configuration form the key.
  Incomplete/error/malformed/nonfinite responses are not cached.
- Standalone get-specs/add-preview gain one fresh tree read. Add execution reorders
  its existing tree read and retains postwrite verification. Sketch/cut/mate reuse
  their existing fresh trees. A cold spec key costs one GET; a warm identical key
  costs zero spec GETs, while mutable target reads still occur.
- For a changed document with E nonempty cold exportable tabs, known workspace,
  no retries and no discovery, acquisition is `2 + sum(P + 5)` requests, minimum
  `2 + 6E` when each translation completes in one poll. The extra two per tab are
  the revision bracket. This is code-derived cost, not a live benchmark.
- REST quota and health use verified application-plus-account identity. Legacy
  unbound grants keep their old scope; settings changes alone never transfer a
  grant or clear usage. Rotation within an application retains its ledger.

## Provider evidence

The official [Onshape API limits](https://onshape-public.github.io/docs/auth/limits/)
exclude public App Store OAuth calls and webhook notifications from the annual
REST allowance. API-key calls and private-app OAuth successes (2xx/3xx) count;
private-app usage belongs to the app owner. Rotating keys is not evidence of a
renewed account/company allowance. Endpoint rate limits remain separate.

Onshape's [FeatureScript MCP announcement](https://www.onshape.com/en/blog/featurescript-mcp-server-enables-text-code-cad)
confirms the vendor-hosted App Store workflow for creating, testing and refining
custom features. It does not establish equivalence to every REST operation.

An earlier live capture in `HANDOFF_featurescript-mcp.md` reported that the MCP
server consumed an allocation, with 0/2500 used while the private app had spent
about 2000. That was one observation, not proof of a separate annual entitlement.
The official REST exemption must not be conflated with unlimited MCP service use.
Current service accounting needs verification before changing quota enforcement.

## Historical live acceptance before the verified-grant continuation

The user completed native FeatureScript reconnection. The refresh path explicitly
requests the pinned Read/Write scopes; broader scopes were not accepted. Fresh
inventory admitted twelve of fourteen tools. Hosted usage reported 1/2500 used,
2499 remaining before the first evaluation. This is an observed service allocation,
not evidence of an annual entitlement.

Through the real SOL conversation, a temporary FeatureScript 3070 evaluation using
`fCylinder` returned one body and volume 62.83185307179587 mm³ without notices.
The hosted evaluator supplies a map as its second argument; the successful probe
used `makeId` explicitly. An earlier `test_feature` card was cancelled unexecuted.

The user approved exactly one `onshape_fs.create_geometry` operation with
`clean:false`. The vendor reported successful feature creation in a new workspace:

- Document: `92214dab788af254f404e110`
- Workspace: `d9e98e400d3e226d34cbd191`
- Part Studio: `8ea79a56f87d98c71b93f607`
- Feature: `Fpt2fKWNGU5aXgW_0`
- Feature Studio: `25f825009167a43e58bbf780`
- Feature name: `solusAcceptanceCylinder`, radius 2 mm, height 5 mm
- [Created workspace](https://cad.onshape.com/documents/92214dab788af254f404e110/w/d9e98e400d3e226d34cbd191/e/8ea79a56f87d98c71b93f607)

Two subsequent hosted read-only calls listed the Feature Studio and read its saved
source, confirming it matches the approved code in the new workspace. These calls
verify source persistence, not independent persistent-body geometry or feature
health. The vendor returned image payloads that the current adapter omits; they
were not inspected. Temporary evaluator volume is not a persistent-branch readback.
No self-approval or uncertain-write replay occurred.

At that historical checkpoint, native source sync reported `quota_exhausted`; prior graph data was preserved.
No quota latch or counters were reset. Leader geometry and joint axes have not
been read, and no mates were added. The native mate operation is fastened-only;
it must not be used to immobilize articulated joints. Full Hand live import and
assembly acceptance remain open.

The current hosted inventory covers Feature Studio list/read/write/create,
documentation/notes, FeatureScript testing, geometry creation, feature testing,
identity and usage reads. `create_geometry` branches a workspace; it is not an
equivalent in-place native-feature edit. No generic variable-table setter,
arbitrary native-feature editor or assembly-mating tool was demonstrated.

## Baseline direct write cost (before this amendment)

Static successful-path counts: one preview plus one execution, explicit workspace,
no retries or discovery. These are code-derived, not a fresh vendor benchmark.

| Operation | Requests before graph sync |
| --- | ---: |
| Scalar feature edit | 4 |
| Feature edit with Q geometry-query parameters | 4 + 2Q |
| Variable set | 4 |
| Generic feature add | 4 |
| Assembly part insertion | 6 |
| Fastened mate | 8 |
| Face mate connector | 10 |

Missing workspace identity adds two document lookups across preview/execution.
At this baseline, direct featurespecs reads were uncached. Generic feature add
then extracted the POST response without the fresh readback used by the other
audited paths. Both limitations were subsequently repaired; see the current
checkpoint above.

Trace: `connectors/onshape_refs.py`, `onshape_ops.py`, `onshape_authoring.py`,
`onshape_mates.py`; direct `get_json` in `connectors/onshape.py:1291` always requests.
All paths are under `packages/api/src/solus_api/`.

`services/onshape_write_sync.py` invalidates the document signal and queues a full
source sync after successful writes. With warm shared cache and known workspace,
a changed document with E nonempty exportable tabs costs:

`2 + sum(P + 3)` requests, minimum `2 + 4E` (P is translation status polls).

This includes microversion, elements, translation creation/status/download, and
metadata. Export keys contain the document microversion, so editing one tab
invalidates all its tabs' export keys. A scalar edit plus sync therefore costs at
least 10 requests for one tab or 26 for five. Retries and cold discovery add cost.

## Baseline webhooks and freshness (before this amendment)

The receiver exists, but no production caller mints its source token and no vendor
registration/lifecycle is implemented. Hourly ARQ sweeps provide actual freshness.
One unchanged document at hourly cadence would spend 8760 probes/year without the
budget guard; the default scheduled threshold is 1260 of a local 1800 allowance.

The receiver discards event identity, lacks durable dirty-state/event deduplication,
and ignores deliveries during syncing. Its 24/day delivery limit drops excess
notifications. Webhook-triggered sync bypasses signal-cache reuse and may repeat
microversion reads. Single-flight serialization is not durable event coalescing.
Registration, authenticated ingestion, durable dirty state and recovery must precede
turning off the current fallback; otherwise external edits become invisible.

## Approved implementation plan

1. Reconcile public-app REST exemption versus MCP service accounting. Preserve
   rate limits, bounded retries and truthful usage; no fabricated remaining balance.
2. Discover current hosted capabilities after resolving the narrower-grant failure.
   Route each equivalent supported operation through the reviewed MCP adapter.
   Keep explicit REST exceptions for unsupported operations, including assembly or
   variable operations if discovery still lacks them. Never silently switch to REST
   after an uncertain MCP write, or replace an in-place edit with a branched model.
3. Cache version-bound feature specs and immutable donor reads, reuse geometry
   reads within a verified microversion, and coalesce postwrite reconciliation.
4. Record verified write outcomes and mark affected geometry/dependents dirty.
   Reconcile only the necessary dependency closure where demonstrable; preserve
   unchanged graph subtrees. Existing connector snapshots tombstone omitted nodes,
   so a changed-only snapshot is unsafe without explicit merge semantics.
5. Implement webhook registration/renewal/removal and a reachable callback;
   persist/coalesce authenticated events, including arrivals during sync. Process
   the final dirty revision once. Remove routine polling for healthy subscriptions;
   retain bounded, visible manual/recovery checks for unavailable subscriptions.
6. Add request-budget, duplicate-event, concurrent external-edit, stale-preview,
   partial-write, graph-freshness and account/project-isolation regressions; then
   resume FeatureScript and assembly acceptance with measured call budgets.

## Approved ADR-019 / ADR-035 amendment

> Onshape transport selection is capability- and semantics-based. Prefer the
> admitted vendor-hosted FeatureScript MCP for supported equivalent operations;
> retain explicitly classified REST operations where no equivalent is available.
> Public App Store OAuth REST usage is exempt from the documented annual REST
> allowance; any separately observed hosted-service allocation is represented
> independently without assuming an annual cap from one sample. Authentication,
> rate limits, allowlists, project/account scope and uncertain-write safeguards
> remain enforced. Verified Solus writes drive dependency-aware invalidation and
> coalesced authoritative reconciliation rather than an unconditional full export
> after each write. Healthy registered webhooks replace routine change polling;
> bounded recovery checks remain explicit when delivery is unavailable. Geometry
> stays stale until verified, and incremental reconciliation preserves unchanged
> graph data. This amendment does not authorize additional OAuth scopes.

The user approved this concrete text in-chat; it is recorded in DECISIONS.md.
Approval does not widen OAuth scopes or permit fabricated live acceptance results.


## Implemented boundaries and remaining acceptance (updated by T1/T2)

- Import staging now defaults to 256 exportable elements, with 100,000 graph records
  and 64 MiB serialized graph bounds. A late failure yields no partial snapshot.
  Fixture tests cover 26+ elements; Full Hand has not yet passed a live import.
- Account/revision-scoped immutable donor body geometry is cached and validated
  before insertion into the cache. Mate previews still reread the mutable target.
  Two previews reuse one donor read while performing two target assembly and tree
  reads. T2 now also caches immutable revision-bound specs; mutable target state remains fresh.
- Source-row-locked webhook generations, bounded deduplication and durable recovery
  coalesce notifications and successful native writes. Later arrivals remain dirty
  after an earlier reconciliation. Healthy verified subscriptions replace routine
  polling. Registration requires a reachable public HTTPS callback; localhost is
  explicitly unavailable. Production registration and external delivery remain
  unverified here.
- Reconciliation still publishes a complete authoritative snapshot. Coalescing
  reduces repeated jobs; dependency-closure export optimization is not yet complete.
  Returning only changed entities would tombstone unchanged graph data under the
  existing connector contract and is intentionally not presented as a safe shortcut.
- Generic feature creation now performs one additional authoritative tree read
  before success (baseline 4 becomes 5 requests before graph sync). Missing or
  unhealthy readback is an uncertain mutation, never an automatic write retry.
- FeatureScript temporary execution, vendor-reported persistent creation and saved
  source readback passed. Independent persistent-body inspection, native assembly
  insertion and meaningful movable joints remain open. Fresh inventory did not
  establish MCP equivalents for these native assembly operations.


## Credential configuration check

`make seed-secrets` runs `scripts/seed-provider-keys.py`; it seeds AI/search refs,
not Onshape. Its read-only check passed. Solus reads the `SOLUS_ONSHAPE_CLIENT_ID`
and `SOLUS_ONSHAPE_CLIENT_SECRET` settings. The unprefixed and prefixed pairs were
initially different; the user updated both, they now match, and the dev stack was
restarted. No secret values were printed or written into source. Updating these
settings does not itself renew hosted OAuth or reset an observed provider quota.

The old hosted 2500/year admission assumption and unused setting were removed: no
hosted code recorded requests to that ledger, and one observed usage sample did
not establish an annual entitlement. Vendor refusals remain authoritative. Exactly
REST `quota_exhausted` source errors can now use an otherwise valid independent
hosted grant; other error states, revoked accounts and invalid credentials remain
blocked. Account-backed and legacy OAuth completion use the same narrow condition.


## Historical reconnect and stale import message follow-up

The user completed native FeatureScript reconnection successfully (hosted exchange
HTTP 200 and twelve reviewed tools admitted). Native imports then encountered the
old REST quota refusal. The reported old 25-element error came from another
bug: onboarding selected the oldest entry of newest-first sync history and ignored
the accepted job identity. The implemented fix follows the exact accepted job, including the queue interval
before a Sync row exists, and uses the current job failure/cancellation. Source
entity counts avoid unnecessary history reads. Tests cover this display race;
the successful large-document import was still unverified. Current REST status is
recorded in the latest checkpoint above; Full Hand acceptance remains open.


## Historical verification and handoff before T1/T2

- Affected API suite: 967 passed, three warnings; includes Onshape acquisition,
  writes, hosted auth, webhook lifecycle/recovery, logging and repaired regressions.
- Earlier full API run: 6340 passed, five failed, one skipped. The five failures
  were stale test expectations or a test interpreter mismatch; all repaired files
  passed in the final affected suite. A second full-suite run was not performed.
- API mypy: 341 source files passed; Ruff passed.
- Onboarding frontend: 321 tests in 29 files passed; renderer type checks passed.
- Root `pnpm lint`: exit 0, zero errors and 151 existing warnings.
- Independent code, TypeScript/Python and dedicated security reviews completed;
  findings fixed. Ponytail and a standalone secret scanner were unavailable;
  dedicated review was used, without claiming those unavailable tools ran.
- `COWORK_QA_onshape-quota-acceptance.md` contains the remaining live walkthroughs.

Remaining implementation: dependency-closure export reconciliation. T2 has now
wired version-bound feature-spec caching into all six actual call sites. Complete snapshots are
still required by the connector contract; coalescing is implemented, changed-only
snapshots are not. Public webhook registration/delivery needs a reachable HTTPS
callback and has not been demonstrated on localhost.

## Historical credential rotation diagnostic (superseded by verified grant)

After the user changed the client pair again, a bounded read-only REST diagnostic
loaded the latest matching prefixed/unprefixed settings and requested one document.
Onshape returned HTTP 401. The existing single-refresh helper then failed with
`oauth_refresh_failed`; no successful REST request or current allowance was
established. The old persisted source `quota_exhausted` state is historical and
must not be presented as a fresh provider response from this diagnostic. Solus was
restarted with the latest settings. The document picker still displayed its cached
listing; cached listing success is not authentication evidence. No quota counter
or provider-exhaustion latch was reset. The user confirmed the values had come from a newly created company API key,
then registered a company OAuth application and supplied its client credentials.
Solus restarted with those values; fresh user authorization was pending at that
time. The successful subsequent grant refresh and metered read are recorded above.

The subsequent T1/T2 implementation repaired revision association for element
lists, STEP exports and metadata and wired immutable feature-spec caching.
Workspace translations are documented for w/v, so a microversion path is not
invented: cold exports require revision checks around asynchronous completion.

OAuth recovery UI now exposes the existing Re-authorize action for linked OAuth
accounts independently of quota health. Tested 41 account-card cases, renderer
TypeScript, and root-scoped ESLint (zero errors, four existing warnings); independent
code/TypeScript/security review passed. Live browser verification found the button
and account wizard; actual consent requires the native desktop app. The wireflow
was amended directly under tier-1 governance. No quota reset or revocation added.

## Live SOL follow-up: persisted FeatureScript and autonomous assembly

Persisted FeatureScript geometry PASS in actual SOL conversation
`01a09c64-8494-752a-adb3-faaf2e6a1a5a`: read-only follow-up after selecting
FeatureScript MCP Workspace returned one solid JHD, radius 0.002 m, height
0.005 m, volume 6.283185307179588e-8 m³, bounds ±0.002 m in X/Y and
0..0.005 m in Z. Feature tree and part revision both identify
`333e0d0aeafc7ac120e8c2a0`; persisted feature `Fpt2fKWNGU5aXgW_0` remains
present. The public feature-tree projection omits explicit regeneration status,
so successful solid readback is geometry evidence, not a separate exposed status
field. SOL performed eight read tools and no modifications in this follow-up.

First extended autonomous Build attempt, conversation
`01a09d35-6748-7b9d-b628-3672ccdf42c9`, received only a natural-language request
to inspect Leader and add all appropriate mates while preserving its pose. SOL
chose document/assembly discovery and the compact inspector independently, but
inspection failed: an 11.3 MiB valid donor exceeded an incorrectly shared 8 MiB
cache/acquisition ceiling. Eleven tools ran, no mates were added. SOL's suggestion
to heal/re-import the source was unsupported: developer diagnosis identified a
Solus size-limit error. This attempt is FAIL, not autonomous mating acceptance.
The fix separates bounded 32 MiB donor acquisition from 8 MiB cache storage.

Latest successful four-document selection sync
`01a09d18-8fe3-7b56-a1c1-17f5686f23d0` added two entities with zero errors;
Leader, Full Hand, Draw Piece and FeatureScript MCP Workspace are selected.
Earlier successful Full Hand import supersedes historical open entries above.

Further actual SOL continuation in conversation
`01a09d39-c8ac-75c9-9909-aec8f9674013` created both trigger pivot connectors.
First connector `Mrl41Rb8CK549vkst` verified immediately; second
`MaMhEvtX1V+iiiX/y` returned uncertainty because its valid JSON feature ID
contained `+` and `/`. Independent readback found both features `OK`, at matching
world centers and opposite signed axes. No revolute mate was yet created.
The JSON-ID fix preserves resource URL validation.

Subsequent SOL readback first failed because a raced export left a
`revision_changed` source error despite a healthy account, then correctly
identified the missing feature evidence because the 13.5 KiB assembly response
was truncated before features. These are recorded failures, not assembly passes.
Source authority now narrowly admits that sync error under unchanged live grant
checks; stale export signals are invalidated before the original refusal.
Compact feature-view readback is under live acceptance next.

Verification checkpoints: integrated Onshape 299 tests; source authority recovery
81 tests; stale-signal acquisition/call-budget tests 55; compact feature view and
operations 90. These overlap and must not be added as a unique test total.

## Verified autonomous revolute joint — 2026-09-14 00:53 UTC

In the same natural-language SOL conversation, after complete feature readback
was exposed, SOL independently chose and created `Trigger revolute joint`,
feature `MyCMtaZGUqDkhAmSS`. Native readback reports `mateType=REVOLUTE`,
`primaryAxisAlignment=true`, feature status `OK`. It reused existing healthy
connectors `Mrl41Rb8CK549vkst` and `MaMhEvtX1V+iiiX/y`. No tester-provided
joint IDs or axes were supplied in its prompts.

Independent metered readback compared all 23 occurrence transforms before and
after: identical path sets and maximum transform difference exactly 0.0. This
passes creation, health and preserved placement for this selected joint. It does
not prove remaining arm connections, full mechanism degrees of freedom, travel
limits or collision clearance. Remaining arm-joint acceptance continues.

Observed quota after three independent verification reads: 758 estimated used,
status OK. This is an observation at this checkpoint, not a current balance or
provider allocation reset. Graph synchronization still requires final recovery.
