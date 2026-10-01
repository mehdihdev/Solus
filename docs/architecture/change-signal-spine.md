# Architecture — The change-signal spine (SOLUSDEV-167)

How a change made in ANY connected tool reaches every open Solus session, and why refreshing is
the only thing allowed to spend a provider's API quota. Companion docs:
`docs/contracts/connector-interface.md` (the connector contract), `docs/contracts/bridge-protocol.md`
(the `change` frame), `docs/api/API.md` §2.5/§3 (routes), `DECISIONS.md` ADR-030 (event-driven
connectors), ADR-019 (budgets).

## Why this exists

Onshape's API quota is **annual, per user** — 2,500 calls/year on Free/Standard/EDU, only 2xx/3xx
counted, exhaustion answers HTTP 402. That is **6.8 calls/day**. No timer-driven poll is affordable
at any interval, and no cache hit-ratio rescues a design that polls. One tester consumed ~2,000 of
those calls, and nothing in the system counted a single one.

The inversion: **the graph is the source of truth; the API is how it gets refreshed.** Feature code
reads the graph (Postgres, zero provider calls). Freshness arrives out of band, and only when a
cheap change signal says something actually moved.

## The one path

```
PRODUCERS (all untrusted)                    GATE                      CONSUMER CHAIN (one)
 1 cloud webhook   POST /webhooks/{p}/{tok} ─┐
   (per-source URL IS the credential)        │
 2 cheap-signal sweep  worker.run_change_    ┼──► execute_source_sync ──► run_sync
   detection (ARQ cron, hourly safety net)   │      worker.py             runtime.py
 3 bridge `change` frame  routers/bridge.py ─┘                              │
   (companion, unsolicited, coalesced)                                      │
                                              detect_changes(ctx) ◄─────────┤  the quota gate
                                                unchanged → _commit_skipped │
                                                                            ▼
                                                      apply_sync_result  (idempotent upsert
                                                      by (source_id, external_ref), version bump,
                                                      per-source advisory lock)
                                                                            ▼
                                                      _commit_success → commit → hub.publish()
                                                                            ▼
                                                      SSE  GET /projects/{id}/events
                                                           → every open session
```

**No producer payload ever carries scope.** `execute_source_sync` re-derives `project_id`, `team_id`
and the acting user from the `Source` row itself. That single property is what makes it safe to
accept an unauthenticated webhook body and an untrusted companion frame: the worst a forged producer
achieves is one debounced probe against a source it named, and it can name only a source whose
per-source token it already holds.

Producers differ in exactly one way — whether they carry **evidence** (a verified provider webhook,
which may proceed) or a **hint** (a bridge frame, a cron tick — which schedules the probe). That is
the only branch the spine needs.

## The gate is the quota fix

`run_sync` today goes straight to the sync and never consults `detect_changes`; the only production
caller of `detect_changes` is the scheduled sweep, inside an ARQ cron that has never fired in dev.
So every triggered sync pays full cost — for Onshape, a translation job per assembly plus a poll
loop — even when nothing changed.

The gate goes inside `run_sync`, **after credentials resolve**, and routes an unchanged verdict
through `_commit_skipped`. It cannot be a bare `return`: `_begin_sync` has already committed
`status = SYNCING`, so returning early would 409 every manual sync forever and drop the source out
of the sweep (which selects only `CONNECTED`). One guard, in the one function all three dispatch
paths funnel through.

## Per modality

| Modality | Change signal | Real-time via | Honest latency |
| --- | --- | --- | --- |
| **Cloud API — Onshape** | document microversion | per-source webhook (notifications are **free**, uncounted) | seconds |
| **Cloud API — GitHub** | commit SHA + **ETag** | `If-None-Match`: a 304 costs **zero** rate limit — better than a webhook | hourly sweep, free |
| **Cloud API — GitLab** | commit SHA | hourly sweep (ETag caching is a server-side allowlist a client cannot extend) | hourly |
| **Local bridge — KiCad** | `st_mtime_ns` over the workspace | companion `change` frame, unsolicited + coalesced | ~30 s |
| **Local bridge — Altium** | `proj_get_stats` (saved changes only) | same frame, polled | ~30 s, **saved edits only** |

**Altium cannot be truly real-time and the codebase explains why.** The fork never reads a design
file — the netlist export sources entirely from live IPC — and Solus deliberately pins
`force_recompile: False` so upstream never flushes dirty documents. An unsaved Altium edit has no
disk footprint, so mtime is not merely lossy, it is engineered stale. The UI says so; it does not
claim live.

**Browser-based tool work needs no browser code.** A user editing Onshape in Chrome fires
`onshape.model.lifecycle.changed`, which reaches producer 1 server-side. The browser is a rendering
surface, not a change source.

## Why the local push transport is nearly free

The companion already speaks first, unprompted, on three inbound frame types. `_status_loop` is an
event-driven, coalesced, unsolicited companion→cloud send, and `credential_submit` proves the full
unsolicited-push → cloud DB write → ack round trip. So the transport a local change event needs is
already built, tested, and in production; only the **sensor** is missing.

The `change` frame is added under the bridge contract's §4 extension rule — **new frame types do not
bump `protocol_version`**; an old peer logs and ignores. That rule has been exercised twice already.

Two constraints the frame handler must respect:

- **Cheap enqueue only.** `_handle_parsed` is awaited inline in the recv loop, so synchronous work
  there stalls pongs and every in-flight `tool_result`.
- **Pass the companion's user.** A bridge-originated sync must forward `acting_user_id` from the
  `BridgeSession` (server-derived at bind, never from the frame). Without it the sync falls back to
  `source.created_by`, the acquirer's exact-triple session lookup misses, it declines, and the read
  silently falls through to the stale committed export — producing a "changed" notification that
  contains no change.

## Caching: what is cached, and what must never be

Caching is **opt-in per request**; admission and metering are **unconditional**. If caching were the
gate for both, metering would become opt-in too — and every expensive call (the translation poll,
the STEP download, the picker) is deliberately uncached, so the ledger would count the cheap reads
and miss the ones that burn the quota.

Cache keys carry `(provider, account_external_id, item, version)` — the ACCOUNT, and (since I1,
below) never a project or a source. The identity choice was argued here first:

- `team_id` is **wrong**: a team can hold two projects with two Onshape sources connected by two
  different accounts.
- `source_id` alone is **also wrong**: an account switch reuses the same `Source` row by design, so
  the row can carry a different provider identity over time.

The version segment is the document's microversion, so a change makes every derived key unreachable
— partial invalidation at document granularity with **zero invalidation code**.

**Never cache inside a confirmable operation.** The action-gate re-runs a tool's preview at approve
time and refuses on divergence; that guarantee is worth exactly nothing if both previews come from
one cache entry. Worse, Onshape's variable write **replaces** the whole studio table, so a cached
read of that table would revert every variable a teammate changed since the entry was stored.

**Never cache a 401.** The credential-refresh path keys off it, and a cached auth failure would
strand a reconnect that has already succeeded.

## Fail-safe, without the amplifier

Every probe fails safe — an unreachable provider counts as "changed" so an outage schedules a sync
rather than silently skipping one. That is right for a network blip and **wrong** for a rate-limit
error: it turns being throttled into more traffic, which is the loop that empties an annual budget.

So "we could not ask" is classified apart from "it changed". Quota and rate-limit codes are re-raised
rather than swallowed, the sweep logs and skips them instead of enqueuing a full sync, and an
observed 402 latches: further spend is refused until the latch expires, cache-only, visibly.

## The read side, built (SOLUSDEV-241 / I1 — the connection model)

The caching rules above were a specification; I1 builds them as `connectors/integration_cache.py`,
and moves the OAuth grant to where the keys already said it belonged: **the account**.

**OAuth binds at ACCOUNT scope.** `account_connections` is one row per provider grant per user
(Home, H2). A project attaches through `sources.connection_id` (Workspace, W2) and MIRRORS the
connection's secret ref (`connection/{id}/{provider}`), so every credential read path — `run_sync`,
the sweep, the picker, the SOL tools, hosted add-ons — is unchanged. What changes is ownership:
a connection-owned ref is never deleted by a source disconnect or a project teardown; revoking the
connection deletes the whole family and disconnects every bound source. A document may therefore
belong to several projects on one grant, and their fetches share one cache.

**Three entry kinds, one key discipline.** Keys carry `(provider, account_external_id, …)` — never
a project or a source, for the reasons the section above records — and a hit is only ever served to
a caller that resolved that account's credentials (`services/connections.account_ref_for`).

| Entry | Key | Moves when |
| --- | --- | --- |
| **listing** — the picker's documents/repositories | `…:listing` | an explicit `refresh=true` (at most one walk per cooldown window per ACCOUNT, however many members share the grant; each refresh is a logged data event), or a webhook doorbell for any source on the account. **Never a timer** — the TTL is storage hygiene. |
| **signal** — a document's microversion + the workspace fetched to read it | `…:signal:{document}` | every probe that actually asked. Readers say how old a recorded one may be: a human's sync trusts it for the sweep interval (the sweep is what moves it); the sweep trusts one a few minutes old (two projects on one document → one probe per sweep); a **webhook never trusts it** — a doorbell means "it changed". |
| **payload** — the element list, a STEP export, part metadata | `…:{kind}:{document}:{microversion}[:{element}]` | never invalidated: a change makes the key unreachable. Payloads above 8 MiB are used but not stored. |

So "sync on first select, then ONLY when the change signal moves" holds literally: a manual sync
reads the recorded signal (zero calls); the hourly sweep and the doorbell are the only things that
move it; and a second project — or a teammate — at the same microversion costs zero calls end to end
because every read it makes is keyed by a version someone already paid for. Measured in
`tests/test_onshape_call_budget.py` (the I1 block), never claimed.

Windows are settings (`SOLUS_INTEGRATION_SIGNAL_TTL_SECONDS`, `…_SIGNAL_SWEEP_REUSE_SECONDS`,
`…_LISTING_TTL_SECONDS`, `…_LISTING_REFRESH_COOLDOWN_SECONDS`, `…_PAYLOAD_TTL_SECONDS`,
`…_CACHE_MAX_PAYLOAD_BYTES`). Revoking a connection or deleting the account drops every entry
for that account (a per-account key index): derived copies of a customer's CAD do not outlive the
grant. An unidentified account (no provider account id) caches nothing. The honest bound:
without a registered webhook a teammate's "Sync now" can be up to one sweep interval stale by
design; the UI shows "Synced … ago", not "live".

## Freshness is not a new table

Everything the spine needs already has a home: the per-document change tokens and the resolved
workspace ids live in `Source.cursor`; the webhook token digest and the provider account id live on
`Source`; the cache, the probe due-gate and the annual ledger live in Redis; and the event vocabulary
is an unconstrained string column. **No migration** — for the spine. I1 adds one
(`account_connections`, `sources.connection_id`, nullable `oauth_states.source_id`) because the
account is a new scoping anchor, not new freshness state.

The workspace id in particular belongs in the cursor rather than the cache: it is fetched *in order
to build* the microversion URL, so there is no version to key it on, and a TTL'd entry would be
exactly the unversioned-staleness hole the version-keyed design exists to avoid. In the cursor it is
durable, cross-process, and free — and it halves the probe's cost permanently.

## What the spine does NOT do

- It does not make the graph a second read surface for raw vendor payloads (ADR-001).
- It does not move heavy work into the request path — that ADR-005 violation predates this work and
  is tracked separately.
- It does not meter provider quota in credits. Provider quota is a separate budget in a unit Solus
  neither buys nor can convert (ADR-019, amended).

## SOLUSDEV-242 Phase 3 correction — change evidence is mandatory

The previously described `run_sync` gate is now required on every established cloud cursor.
An ambiguous/failed probe does not mean changed and cannot fall through to an export. Refresh
expired credentials around the cheap probe, preserving refreshed credentials for any ensuing
sync. Retryable probe failures retain a source's eligibility for the next change sweep; permanent
auth failures remain visible. First ingestion and changes to the selected document set are
legitimate changes. Evicted payload cache entries alone never trigger ingestion.

Account payload/listing and per-source synchronization flights must fail closed if the claim
cannot be acquired. A waiter cannot proceed unclaimed or release another caller's lease.
Concurrent duplicate hints are coalesced; once a new version is persisted, later hints skip it.
The independent worker remains the change producer; no timer or request from canvas zoom,
selection, dropdown opening, or layout saving probes providers.

I1's cache-only read and exact account/selection binding semantics are specified in the Phase 3
amendment to `docs/api/API.md`. The historical text above about automatic account rebinding is
superseded: Add must never switch an existing source to a different grant silently. Provider
webhook registration is not assumed from OAuth connection; live verification must identify the
actual configured worker/change-delivery path and count successful ingestions explicitly.

### Phase 3 lease and queue bounds

Payload and source flights renew only while their owner token still matches. Failed, timed-out,
or lost renewal cancels protected work; bounded release cannot hang cleanup or delete a successor's
lease. Acquired sync work has a one-hour deadline. An accepted job waiting on another source flight
stays queued; ARQ defers that specific job by 30 seconds, with a two-hour wall-clock queue bound.
Cancellation/expiry marks only the matching project's unfinished job, preserves completed work,
and does not reset a newer synchronization. Other worker jobs retain their existing timeouts.
A failed change probe never advances the last successful sync timestamp.

### SOLUSDEV-261 — approved native Onshape writes

A successful approval of a registered native Onshape write is another change
producer. The confirmation route uses the stored arguments and current project/
team scope, resolves the live tracked source and grant, removes only the target
document's cached signal, and enqueues the existing sync job with the deciding
user. Both existing source and account fallback cache identities are invalidated;
immutable payload caches remain intact. Invalidation failures are surfaced rather
than silently trusting the old microversion.

Approval never waits for CAD export, including when development `sync_inline` is
enabled. The existing queue/worker, change probe, ingestion and `graph.changed`
publication remain authoritative. Rejections, stale/failed executions, reads and
unknown hosted operations do not produce this hint. Scheduling failure preserves
the successful CAD outcome and instructs the user to retry source sync, never the
already-applied mutation. Scheduling uses a separate database session so its
failure cannot poison confirmation history.

## Onshape transport/reconciliation amendment — SOLUSDEV-261

The approved ADR-019/035 amendment supersedes blanket polling and blanket bans on
caching inside confirmable operations. Mutable target state and microversion
checks remain fresh; reuse is limited to immutable donor revisions and
specifications bound to a freshly verified revision and account scope.

Onshape webhook lifecycle and dirty generations live in internal Source.config
metadata (`_onshape_webhook`), not the replacement connector cursor. Updates lock
the Source row and merge only this internal key. Registration records document
subscriptions, status and observed delivery health. Dirty generation increases
for accepted external hints and verified local writes; a worker captures a
generation and acknowledges only that generation after successful full-snapshot
reconciliation. Later generations survive and schedule a trailing run. Provider
payloads never supply project/team/acting-user authority. Bounded event identity
storage deduplicates deliveries; saturation retains dirty state rather than
silently dropping freshness. Existing ARQ work executes reconciliation; a bounded
local sweep recovers unacknowledged generations after enqueue failure/restart.

Healthy registered subscriptions replace routine vendor polling. Missing, failed,
or unverified subscriptions retain explicit bounded recovery behavior; localhost
callbacks are unavailable, never reported healthy. Vendor registration must use
pinned Onshape transport with owner credentials and a validated public HTTPS
callback. Source removal/revocation invalidates local webhook authority immediately;
remote cleanup is best effort with recorded failure. No webhook carries graph
facts. Graph state becomes current only after authoritative reconciliation.

Acquisition continues to return a complete SyncResult. Larger documents use
bounded complete staging; failures do not apply a partial snapshot. Dependency
closure remains conservative when cross-tab effects cannot be proven. Coalescing
avoids a full export after each operation without treating intended writes as
verified downstream geometry.

### Onshape revision proof and OAuth quota identity (SOLUSDEV-261)

Acquisition reads element lists and part metadata at the planned immutable
microversion. Workspace-only asynchronous STEP translations require fresh revision
checks before submission and after completion/download, both matching the planned
revision. Drift fails the complete snapshot without publishing a cache payload or
automatically replaying an export. A new acquisition cache namespace excludes
payloads stored before revision verification; the projection version requests one
quota-gated repair sync for existing sources. Cold exports add two verification
reads; validated warm export payloads do not repeat them.

Onshape quota estimates and provider-exhaustion flags are scoped to the OAuth
application that issued the grant plus the provider account. Reconnecting or
rotating a secret for the same application does not reset either. A configured
application change cannot relabel a previously issued token. Legacy records remain
intact; application attribution must be established by successful authorization,
not client-supplied source configuration. This implements the approved ADR-019
application-identity amendment without asserting a renewed provider allowance.

### SOL turn reconciliation deferral (SOLUSDEV-261)

A Build turn may perform several independently verified native CAD writes.
Reconciliation must retain durable dirty generations while waiting for that
turn's writes to finish. Before an already-admitted native write is invoked,
record the affected source dirty, invalidate its document signal and acquire a
server-owned turn hold in existing source reconciliation metadata. This is
bookkeeping after authorization, never authority to execute a model proposal.
It also covers uncertain outcomes and cancellation without replaying a write.

Each hold has an independent server UUID and fixed expiry bounded by the turn's
300-second deadline plus 30 seconds; at most 32 live owners are admitted per
source. Row locks protect updates. Never evict another live owner or release
its hold. Turn cleanup releases only its own holds and schedules one normal
reconciliation per dirty source when no live holds remain. Failed cleanup or
enqueue is recovered through durable dirty state and hold expiry. Successful
write results report graph sync as deferred, not queued or current. Standalone
confirmation decisions retain immediate scheduling.

Webhook, sweep/recovery and already-queued job admission respect live holds;
accepted jobs stay queued under existing bounded defer semantics. Direct CAD
reads and mandatory write readbacks remain immediate. Exports started before a
hold still rely on revision bracketing and may fail; this is not transactional
isolation against concurrent editors. Generation acknowledgments never clear
later changes. No new public route, database column or tool authority is added.

## Live channels beyond the graph — SOLUSDEV-312 (ADR-037)

The fan-out half of the spine now carries more than `graph.changed`. `LiveHub`
routes on three channel kinds — `project:{id}`, `team:{id}`, `user:{id}` — over
Redis `solus:live:{kind}:{id}` (the relay still accepts legacy
`solus:graph:{project_id}` during rollout).

```
REST mutation / worker job ─► ORM flush ─► live_publisher derives hints from
  changed rows (Activity, Notification, Team, Membership, ProjectMembership,
  Invite, Project, Source, WorkspaceLayout, Job) ─► queued on the session
  ─► after_commit ─► hub.publish_to(channel) ─► Redis ─► every API process
  ─► SSE: /projects/{id}/events (project channel)
          /users/me/events      (user channel + every team channel)
```

Properties carried over unchanged from the graph path: hints never deltas,
committed-only, structural routing, drop-on-full, newline frames dropped. New:
streams re-verify access every 30 s and immediately on a revocation hint, and
`/readyz` reports `live_fanout = redis | local_only`. Connector sync status
changes reach clients as `sources.changed` / `job.updated` without any new
producer code — they are derived from the same `Source`/`Job` row writes the
worker already commits. The contract is `docs/contracts/live-events.md`.
