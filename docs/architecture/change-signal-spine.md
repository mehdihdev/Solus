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

Cache keys carry `(provider, source_id, account_external_id, scope, version)`. Both identity
segments are required:

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

## Freshness is not a new table

Everything the spine needs already has a home: the per-document change tokens and the resolved
workspace ids live in `Source.cursor`; the webhook token digest and the provider account id live on
`Source`; the cache, the probe due-gate and the annual ledger live in Redis; and the event vocabulary
is an unconstrained string column. **No migration.**

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
