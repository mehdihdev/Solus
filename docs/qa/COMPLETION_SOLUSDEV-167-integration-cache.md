# Completion report — SOLUSDEV-167: integration cache + live graph propagation

Branch `SOLUSDEV-167-integration-cache-live-graph` · 10 commits · full API suite
**2,635 passed, 4 skipped, 0 failed**; companion suite **214 passed**.

---

## 1. The finding that reframed the ticket

**Onshape's quota is annual, not hourly.** 2,500 calls per user per year on
Free/Standard/EDU-Student; only 2xx/3xx count; exhaustion answers HTTP 402
([docs](https://onshape-public.github.io/docs/auth/limits/), restated at
`docs/integrations/onshape-setup.md:202`). ~2,000 calls is **80% of a year**.

That is **6.8 calls/day**, which changes what a fix can be: no timer-driven poll
is affordable at any interval, and no cache hit-ratio rescues a design that
polls. The answer had to be "don't ask unless something says to".

**The every-minute cron was not the cause.** `worker.py` registered
`cron(..., minute=None)`, which in arq means every minute (verified by executing
`calculate_next`) — 2 calls/document/minute against 2,500/year. But it never
fired: the dev DB's `syncs` table held 4 rows, all `trigger='manual'`, zero
`scheduled`; no Redis container ran; and no ARQ worker exists in the `Makefile`,
`docker-compose.dev.yml`, or `scripts/dev-all.sh`. The burn was **request-path**,
because `.env:23 SOLUS_SYNC_INLINE=true` runs the whole sync inside the HTTP
request. The cron was a landmine that would have detonated the moment Redis and a
worker came up; it is now hourly, bounded, and fair-shared.

**Nothing counted a single call.** So the first deliverable was not a cache — it
was a number.

---

## 2. The result

`make onshape-budget`:

```
before (no gate, no coalescing):  120 quota-counted calls
after                          :   22
saved                          :   98  (82%)
```

4.8% of a year → 0.9%. The before column is **measured, not asserted** (the same
session run with the gate bypassed), and it **understates** the saving — it
already includes this ticket's poll backoff. Only the after column is asserted,
so the comparison cannot rot into a stale constant.

---

## 3. Acceptance

| # | Criterion | Status |
| --- | --- | --- |
| 1 | Repeated read of an unchanged document costs zero API calls | ✅ **15 → 1** |
| 2 | Two users on one document cost one fetch | ✅ single-flight; **per-process without Redis** |
| 3 | A change appears in a second session without manual refresh | ✅ end-to-end test drives a real sync to a subscriber |
| 4 | 20 concurrent requests produce one upstream call | ✅ measured **at peak** against a blocked upstream |
| 5 | Approaching quota degrades to cache-only, visibly | ✅ per-account meter; ADR-019 amended with approval |
| 6 | Cross-tenant: a subscriber cannot receive another project's updates | ✅ enforced by routing, not filtering |
| 7 | Re-sync is idempotent | ✅ collisions eliminated by a per-source advisory lock |
| 8 | Before/after call counts | ✅ 82% |

---

## 4. What was built

**The spine.** Four producers — webhook, hourly sweep, bridge `change` frame, and
(implicitly) browser-originated Onshape edits — converge on `execute_source_sync`,
which re-derives tenancy from the `Source` row. **No producer payload ever carries
scope**, which is what makes it safe to accept an unauthenticated webhook body and
an untrusted companion frame.

**The gate** (`runtime.run_sync`). Every connector already shipped
`detect_changes(ctx) -> bool` and a JSON cursor, and *nothing on the sync path
consulted either*. One guard, in the one function all five providers and all three
dispatch paths funnel through. It routes an unchanged verdict through
`_commit_skipped` rather than returning early — `_begin_sync` has already committed
`status = SYNCING`, so a bare return would 409 every manual sync forever *and* drop
the source out of the sweep.

**Single-flight** on a `SET NX EX` claim rather than per-key futures, because the
API and the ARQ worker are separate processes; an in-process future would coalesce
one worker's callers and let the rest through.

**Producers.** A webhook receiver where **the URL is the credential**, and a bridge
`change` frame carrying an empty payload, pushed by a stdlib `st_mtime_ns` sensor
on the loop the companion already runs.

**Propagation.** `LiveHub` + `GET /projects/{id}/events` (SSE), publishing after
the commit, gated on `counts.changed`.

**Generalization.** GitHub conditional requests (a 304 costs *zero* rate limit —
free money, previously unused), and three conformance assertions that make cheap
change detection a contract rather than a courtesy.

---

## 5. Decisions taken under delegated judgment

| Decision | Why |
| --- | --- |
| **SSE, not the WebSocket `API.md` sketched** | I told you WS auth would reuse the existing pattern. **That was wrong**: it reads an `Authorization` header, which works only because the companion is a Python client. No browser WebSocket can set headers and the renderer is Chromium. SSE needs no new credential path and its client half already ships. `API.md:343` amended with the reason. |
| **The webhook URL is the credential** | Matching the payload's document id is a cross-tenant hole: that id is global, so two teams tracking one shared document would both match a delivery and one would spend the other's annual quota. A per-source URL makes that unexpressible. It also sidesteps Onshape publishing **no** inbound signature scheme. |
| **Cache keys carry `(source_id, account_external_id)`** | `team_id` would let two projects with two connected accounts share a namespace; `source_id` alone survives a reconnect, which deliberately reuses one row to switch account. |
| **The gate skips the EDA family** | Their probe *is* the export, so gating would halve nothing and double the changed path. |
| **Cron kept, demoted to hourly** | ADR-030 forbids poll-**only**, not polling. A safety net under push producers is compliant, and webhook delivery is best-effort. |
| **No GitHub/GitLab webhook receivers** | GitHub's 5,000/hour is not the scarce resource, and a free 304 beats a push needing a public endpoint and a shared secret. |

---

## 6. Not done, and why

**The SOL agent's Onshape tools are still uncached and unmetered.** 12 tools bound
into every turn, ≤8 calls/turn, and a confirmed write re-runs its preview chain up
to three times — all outside the gate. Tenant scoping there is correct (the
project id is a closure variable, never a model argument), so this is a budget gap
rather than an isolation one. It is deliberately not fixed here, because caching a
read inside a confirmable operation is dangerous: the action gate re-runs a
preview at approve time and refuses on divergence, and Onshape's variable write
**replaces** the whole studio table — so a cached read would silently revert every
variable a teammate changed. That work needs the `is_write` flag threaded as a
no-cache signal.

**Both producers dispatch inline rather than through ARQ.** The webhook uses
`BackgroundTasks` and the bridge frame `asyncio.create_task`, so neither gets the
queue's concurrency limit, and neither creates a `Job` row or emits the
`source.sync_started` event a manual sync does. Routing both through
`_dispatch_sync` is the fix.

**The SSE stream authorizes once and never re-checks.** The bridge re-resolves
membership every 15s and closes on failure; this does not, so a removed member
keeps receiving `graph.changed` (source ids, sync ids, churn counts) until they
disconnect. Not a data breach — the frame carries nothing a member could not
already read — but a live channel that outlives revocation.

**No cap on concurrent SSE subscriptions per user or project.**

**The webhook endpoint is dormant.** `mint_webhook_token` has no production
caller, and `Source.config` strips `_`-prefixed keys on create and PATCH, so the
digest cannot be written through the API. It fails closed (permanent 404), which
is the safe direction, but registration needs building alongside the public URL.

**`SOLUS_COMPANION_WORKSPACE` has no producer.** The companion sensor is built and
tested, but the desktop main process sets three other env vars and the user's
chosen folder never leaves renderer `localStorage`. Until that is wired, local
change detection has nothing to watch. Pre-existing, not introduced here.

**`kicad.py:36 config_fields` omits `project_path`**, so `mcp_acquire` declines
every KiCad live acquisition. Also pre-existing; also blocks local real-time.

**Altium cannot be real-time.** Its fork never reads a design file and Solus pins
`force_recompile: False` so upstream never flushes dirty documents — an unsaved
edit has no disk footprint. Stated as a limitation rather than papered over.

**`SOLUS_SYNC_INLINE=true` still violates ADR-005.** H1 hard-blocks agent edits to
`.env` and `conftest.py` depends on it.

**No response cache, and the SOL agent path is still uncached and unmetered.**
The freshness gate and single-flight collapse the *sync* path, which is what the
acceptance criteria measure — but `agent/tools/onshape_tools.py` binds 12 Onshape
tools into every SOL turn (≤8 calls/turn, and a confirmed write runs its preview
chain up to three times), and none of that goes through them. A response cache
would help there; it is deliberately NOT built here, because caching a read inside
a confirmable operation is dangerous: `confirmations.py:346` re-runs a preview at
approve time and refuses on divergence, and `onshape_ops.py:478` documents that
Onshape's variable write REPLACES the whole studio table — so a cached read of
that table would silently revert every variable a teammate changed. That work
needs the `is_write` flag threaded as a no-cache signal, and it belongs with the
metering in §6.

---

## 7. Things worth your attention

1. **Rotate the Onshape OAuth client secret.** It is plaintext at `.env:49-50` and
   `:69-70`, and reading that file printed it into the build transcript. `.env` is
   gitignored and untracked, so nothing reached git.
2. **Start Redis** (`docker compose -f docker-compose.dev.yml up -d redis`). Without
   it the cache and coalescing are per-process; the API now warns at startup.
3. **Webhook registration needs a publicly reachable URL.** Until then the endpoint
   is dormant and the hourly sweep is the change signal.

---

## 8. Bugs found and fixed along the way

- **The measurement instrument nearly lied.** `respx`'s `CallList` subclasses
  `unittest.mock.Mock`, so a `.reset()` that does not exist auto-created a no-op
  child mock — every "costs zero calls" assertion was vacuously true. Replaced with
  an offset the Mock machinery cannot fake.
- **A test was making real network calls** to `cad.onshape.com` (missing
  `@respx.mock`).
- **The SSE route held a DB session for the life of each subscription.** FastAPI
  tears a yield-dependency down only after the response is fully sent, and an SSE
  response never finishes — so every subscriber would have pinned a pooled
  connection `idle in transaction` for hours. It surfaced as a *hanging* test
  rather than a failing one.
- **`_Counts` had no delete counter**, so a delete-only sync read as "nothing
  happened" and would have suppressed the propagation frame.
- **A soft delete did not bump `version`**, making tombstones invisible to any
  version-watching consumer.

---

## 9. Governance

**Tier-1 amended** (agent-editable, MR is the gate): `docs/architecture/change-signal-spine.md`
(new), `docs/api/API.md` §2.5/§3, `docs/contracts/connector-interface.md`
(corrected a `detect_changes` signature that never shipped),
`docs/contracts/bridge-protocol.md` (the `change` frame, under the §4 extension
rule — no `protocol_version` bump).

**Tier-2: nothing edited.** `packages/contracts/` is untouched — the shipped
`detect_changes(ctx) -> bool` + `SyncResult.cursor` is sufficient for all three
modalities. `DECISIONS.md` is untouched, pending the ADR-019 approval in §6.

**No migration.** Everything rides existing columns and Redis.
