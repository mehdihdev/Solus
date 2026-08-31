# Cowork QA — SOLUSDEV-167: integration cache + live graph propagation

For a tester with the running application and this file, and nothing else.

**What changed, in one line:** Solus now asks a connected tool "did anything
change?" before paying to re-read it, coalesces simultaneous syncs into one, and
pushes a change to every open session instead of making each one poll.

**Why it matters:** Onshape's API quota is **annual** — 2,500 calls per user per
year on Free/Standard. One person previously spent ~2,000 of them in a stretch of
testing. A realistic session now costs 22 calls where it used to cost 120.

---

## 0. Setup

| Requirement | How to check |
| --- | --- |
| API running | `make dev-api`, then `GET /api/v1/readyz` returns 200 |
| Desktop app running | `make dev-desktop` |
| Postgres running | `docker compose -f docker-compose.dev.yml up -d db` |
| **Redis running** | `docker compose -f docker-compose.dev.yml up -d redis` — **see note** |
| An Onshape account with at least one document containing an assembly | you can open it at cad.onshape.com |
| A second Solus user on the same team | invite from the Members screen |

> **Redis note.** Without Redis the cache and coalescing are **per-process**. The
> app works, but two API workers will not share a fetch, and the "two users, one
> fetch" behaviour in §3 is only observable within one process. If Redis is not
> running the API logs a warning at startup saying exactly this. Please run it.

A second terminal for `docker logs` or the API's stdout is useful throughout —
several checks below are about what the system *does not* do, which is visible in
logs rather than the UI.

---

## 1. The headline number (5 minutes, no accounts needed)

- [ ] Run `make onshape-budget`
- [ ] It prints a before/after table
- [ ] `after` is materially lower than `before` (expect roughly 120 → 22)
- [ ] The output includes the note explaining the before column understates the saving

**Fail if:** the command errors, or `after >= before`.

---

## 2. A repeat sync of an unchanged document is nearly free

1. [ ] Connect an Onshape source (Sources → Connect → Onshape → authorize)
2. [ ] Pick one document, save the selection
3. [ ] Wait for the first sync to finish (the source shows entities)
4. [ ] Note the Onshape API usage in your Onshape developer console
5. [ ] Click **Sync now**. Wait for it to finish.
6. [ ] Check Onshape usage again

**Expected:** the second sync adds **at most 1–2 calls**, not a full re-export.
In the API log you should see `sync skipped (unchanged)`.

**Fail if:** the log shows a translation request / STEP download for a document
nobody edited.

---

## 3. Two engineers on one project cost one fetch

1. [ ] User A and User B are both members of the same team and project
2. [ ] Both have the project open
3. [ ] Click **Sync now** as A and, within a second or two, as B

**Expected:** one export happens, not two. The second click completes quickly and
its log line is `sync skipped (unchanged)` — B's sync sees the cursor A just
wrote.

**Fail if:** both syncs perform a full export (two translation requests in the
log for the same document).

---

## 4. A change in Onshape reaches a second open session

1. [ ] User A and User B both have the project open in Solus
2. [ ] In a browser, open the tracked Onshape document and change something
       (move a part, rename a feature) — **save it**
3. [ ] Trigger a sync in Solus (Sync now, as A)

**Expected:** B's view updates **without B refreshing or clicking anything**.

**Note:** without a publicly reachable URL, Onshape cannot call our webhook, so
automatic detection comes from the hourly sweep. For this test trigger the sync
manually — what is being verified is that the change reaches **B**.

**Fail if:** B has to refresh to see A's change.

---

## 5. Deleting something upstream also propagates

1. [ ] With both sessions open, delete a part in the Onshape document and save
2. [ ] Sync as A

**Expected:** the entity disappears for **both** users. This is worth its own
check: a deletion used to be invisible to anything watching for changes.

---

## 6. Nothing changed = nobody is disturbed

1. [ ] Both sessions open, nothing edited in Onshape
2. [ ] Click **Sync now** several times

**Expected:** B's view does **not** flash, reload, or show a spinner. A no-op
sync must wake nobody.

**Fail if:** B's widgets visibly reload on a sync that changed nothing.

---

## 7. Cross-tenant isolation (the highest-severity check)

1. [ ] Create a second team with a different project, containing a different user C
2. [ ] C opens their project; A and B open theirs
3. [ ] Sync as A

**Expected:** C sees **nothing**. No update, no flash, no new entities.

- [ ] Also: as C, try to open `GET /api/v1/projects/<A's project id>/events`
      (curl with C's token). Expect **403 or 404**, never a stream.

**Fail if:** C receives anything at all. Report immediately — this is the
highest-severity invariant in the system.

---

## 8. The webhook endpoint refuses everything it should

Substitute a real source id. These are all expected to be **rejected**:

- [ ] `curl -XPOST $API/api/v1/webhooks/onshape/<source-id>/wrong-token` → **404**
- [ ] `curl -XPOST $API/api/v1/webhooks/onshape/<random-uuid>/any-token` → **404**,
      and the body must be **identical** to the previous one (no existence oracle)
- [ ] `curl -XPOST $API/api/v1/webhooks/github/<onshape-source-id>/<its-token>` → **404**
      (a token is bound to its provider)
- [ ] A 100 KB body → **413**

**Fail if:** any of these succeeds, or if the two 404 bodies differ.

---

## 9. Local tools (KiCad) — expect a documented limitation

- [ ] Connect a KiCad source via the companion
- [ ] Edit and **save** a `.kicad_sch` in the project folder

**Expected today:** nothing automatic happens, and that is **known**. The change
sensor is built but the desktop app does not yet tell the companion which folder
to watch (`SOLUS_COMPANION_WORKSPACE` has no producer). Manual **Sync now** works.

- [ ] Confirm manual sync of a KiCad source still works end to end

**Report as a bug only if** manual sync is broken. The missing automatic
detection is expected and tracked.

---

## 10. Altium — expect "saved changes only"

- [ ] Altium change detection sees **saved** files only

Unsaved in-Altium edits are invisible by design: Solus deliberately does not
force Altium to flush its documents, so an unsaved edit has no disk footprint.
This is a stated limitation, not a defect.

---

## 11. Degradation near the quota — **not yet built**

Acceptance item 5 ("approaching quota degrades to cache-only with a visible
state") is **not implemented in this MR** — it needs an architecture decision
(ADR-019 amendment) that is awaiting sign-off.

What IS in place: an Onshape `402` (allowance exhausted) is now recognised as its
own terminal condition and no longer triggers *more* requests.

- [ ] Confirm there is no UI claiming to show a quota position. If you see one,
      that is a bug — it would be fictional.

---

## 12. Regression sweep

- [ ] Connect a GitHub source; sync; entities appear
- [ ] Sync it again — expect it to be cheap/skipped
- [ ] Connect a GitLab source; sync; entities appear
- [ ] Disconnect a source; its entities behave as before
- [ ] SOL chat still answers, and Onshape agent tools still work
- [ ] Live Bench still streams telemetry

---

## What to include in a bug report

1. Which numbered check
2. What you expected vs what happened
3. The API log lines around the moment (especially any `sync skipped`,
   `no signal`, `rate limit`, or `webhook rejected`)
4. Your Onshape developer-console usage before and after, if quota-related
