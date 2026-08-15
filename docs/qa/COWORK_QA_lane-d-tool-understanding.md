# Cowork QA — LANE D: Tool Understanding & Guide Overlay (SOLUSDEV-215)

Grows per shipped ticket. Currently covers: **TU-04 (SOLUSDEV-207)** KB schema/storage/API and
**TU-06 (SOLUSDEV-209)** tenancy guard + review CLI. Written for a tester with the running
application and this file only.

## Required setup

1. Local Postgres with pgvector running (`make db-up`; docker `pgvector/pgvector:pg16` is fine).
2. API running from `packages/api`: `uv run uvicorn solus_api.main:create_app --factory --port 8000`
   with `SOLUS_DATABASE_URL` pointing at a migrated dev database (`uv run alembic upgrade head`).
3. Two dev JWTs (see `docs/api/API-implementation.md` §1 for minting): one with
   `email_verified: true` ("Alice"), one with `email_verified: false` ("Uma").
4. No connected sources, sample projects, or desktop app needed — this surface is API + CLI only.

## Flow 1 — submit tool knowledge over HTTP (operator tier)

1. POST `/api/v1/toolkb/entries` as Alice with body:
   ```json
   {
     "entry": {
       "tool": "kicad",
       "version_range": ">=8.0 <9.0",
       "surface": "menu",
       "control_id": "kicad.eeschema.place_wire",
       "label": "Add Wire",
       "effect": "create_feature",
       "description": "Draws a connecting wire between two schematic pins.",
       "invocation": { "menu_path": ["Place", "Wire"], "shortcut": "W" },
       "locator": null,
       "provenance": "operator_authored"
     }
   }
   ```
   - [ ] `201` with `data.status = "candidate"`, `data.confidence = 0.7`, a UUID `data.id`.
2. GET `/api/v1/toolkb/entries?tool=kicad` as Alice.
   - [ ] `200`, `data: []` — candidates are NEVER served.
3. Repeat step 1 with the exact same body.
   - [ ] `201` with the SAME `data.id` (idempotent), still one row.
4. Repeat step 1 as Uma (unverified).
   - [ ] `403`, `error.code = "email_not_verified"`.
5. POST without an Authorization header. — [ ] `401`.

## Flow 2 — the tenancy guard rejects customer content (the lane's core property)

For each case: POST as Alice, expect `422`, and **search the raw response body for the
customer-looking string — it must be absent every time.**

1. `entry.invocation.menu_path = ["File", "Open Recent", "~/designs/arm_v3.f3d"]`
   - [ ] `error.code = "contract_validation"`; `arm_v3` nowhere in the response.
2. `entry.label = "／home／mehdi／chassis．f3d"` (fullwidth characters — homoglyph evasion).
   - [ ] rejected (`contract_validation`).
3. `entry.control_id = "d/9a1c2ef4b7d8aa00cc11ee22"` (Onshape document-scoped id).
   - [ ] rejected.
4. Extra field: add `"notes": "the bracket flexes at 40N"` inside `entry`.
   - [ ] rejected; `bracket` not in response.
5. Body `{ "entry": "~/designs/arm_v3.f3d" }` (entry not an object).
   - [ ] `422 contract_validation`; the path string NOT echoed anywhere in the response.
6. Old-shape body `{ "entry": {…valid…}, "acquired_via": "api_geometry", "endpoint_scope": "global" }`.
   - [ ] `422 contract_validation` — a client cannot pick a trust tier; `api_geometry` not echoed.
7. Valid entry but `provenance = "observed_ui"`.
   - [ ] `422`, `error.code = "provenance_mismatch"` (HTTP is pinned to operator_authored).

## Flow 3 — operator review publishes (CLI)

From `packages/api`, with `SOLUS_DATABASE_URL` set to the same dev DB:

1. `uv run python -m solus_api.toolkb.review list`
   - [ ] The Flow-1 candidate appears: id, `kicad`, control id, `candidate`, `via=operator`, `conf=0.70`.
2. `uv run python -m solus_api.toolkb.review show <id>`
   - [ ] Full entry rendered: label, description, menu path, provenance, confidence block.
3. `uv run python -m solus_api.toolkb.review approve <id>`
   - [ ] Prints `approved: …` with status `published`.
4. GET `/api/v1/toolkb/entries?tool=kicad&version=8.0.6` as Alice.
   - [ ] `200`; the entry NOW appears with all contract fields + `confidence` + non-null
         `last_verified_at`.
5. GET with `version=9.1`. — [ ] `data: []` (outside the version window).
6. GET with `version=latest`. — [ ] `422`, `error.code = "invalid_version"`.
7. `… review reject <id>` on a fresh candidate, then GET.
   - [ ] Rejected entry never appears; `list` no longer shows it.
8. `… review approve <same-id-again>` — [ ] fails cleanly ("already published" / not live).

## Flow 4 — pagination

1. Submit 5 distinct valid entries (vary `control_id`), approve all via the CLI.
2. GET `…?tool=kicad&limit=2`. — [ ] 2 items, `meta.has_next = true`, `meta.next_cursor` set.
3. Follow `cursor=` twice. — [ ] pages of 2/2/1, no duplicates, final `has_next = false`.
4. GET with `cursor=garbage`. — [ ] `400`, `error.code = "invalid_cursor"`.

## Cross-feature interactions

- [ ] Data events (only if the submitting user has data-collection consent): a submission
      writes `tool_knowledge.submitted`, a guard rejection writes `tool_knowledge.rejected`
      (payload has tool + reason ONLY — verify no entry prose in `data_events.payload`).
- [ ] The store is cross-tenant BY DESIGN: a second team's user sees the same published
      entries via GET. This is correct behavior, not a leak — the boundary is what rows cannot
      contain.

## Flow 5 — the Guide walkthrough (TU-09, backend API; panel not yet mountable)

The Guide **panel** has no live mount yet (a LANE 0 CODEOWNERS + widget-canvas item), so verify
the backend that feeds it. Ingest KiCad first (Flow 3 step 0 / the TU-02 path), then:

1. GET `/api/v1/toolkb/guides?tool=kicad&version=9.0.4` as Alice.
   - [ ] `200`; a guide `kicad.eeschema.first_schematic` with a title and `step_count` ≥ 6.
2. GET `/api/v1/toolkb/guides/kicad.eeschema.first_schematic?version=9.0.4` as Alice.
   - [ ] `200`; `steps` numbered 1..N; each has `note_guide` AND `note_expert`.
   - [ ] resolved steps carry a `label`, `confidence`, and an invocation (`shortcut` or `menu_path`).
3. GET the same guide with the KB **empty** (fresh DB, before ingesting).
   - [ ] `200`; every step `available: false`, `label: null`, but `note_guide` still present
         (graceful degradation — the panel shows the narration, no fake control pointer).
4. GET `/api/v1/toolkb/guides/no.such.guide?version=9.0.4`. — [ ] `404`.
5. GET a guide with `version=7.0` (a KiCad 7 the guide doesn't cover). — [ ] the list at step 1
   returns `[]` for `version=7.0`.
6. Panel behavior (once a mount exists — deferred): Guide vs Expert mode (Settings → SOL mode)
   swaps each step's narration; a step with confidence < 0.6 renders a "tentative" badge; a step
   the KB doesn't cover shows "isn't in the knowledge base yet", never a confident pointer.

## Flow 6 — feedback, corroboration & sharing (TU-08 + TU-05)

Needs the API + two verified dev users ("Alice", "Bob") and a third ("Carol") for the multi-voter
case. Create a **candidate** entry first (submit via Flow 1 as `acquired_via: api_geometry`,
`endpoint_scope: global` — it lands `candidate` at 0.9; grab its `id` from the 201). It is NOT
served by GET yet (candidates are private).

1. POST `/api/v1/toolkb/entries/{id}/feedback` `{ "verdict": "confirm" }` as Alice.
   - [ ] `200`; `confirm_count = 1`.
2. Repeat the exact same call as Alice several times.
   - [ ] `confirm_count` STAYS 1 — one distinct voter, no ballot-stuffing.
   - [ ] GET `?tool=…&version=…` still does NOT list the entry (1 voter < the 2-voter floor).
3. POST the same confirm as **Bob** (a second distinct user).
   - [ ] `200`; now 2 distinct confirms on a 0.9-base candidate → **auto-promoted to published**.
   - [ ] GET now lists the entry — it is shared to every tenant (the compounding moment).
4. On a fresh api_geometry candidate, have Alice+Bob confirm (promotes it), then have 4 other users
   reject it.
   - [ ] confidence falls and the entry is **retracted** — GET no longer lists it.
5. A `docs`-published entry (Flow 3/TU-02) that gets several rejects.
   - [ ] confidence drops (renders tentative in Guide) but it is **NOT** un-published — docs are
         vendor-authoritative.
6. POST feedback unauthenticated → `401`; with `{ "verdict": "maybe" }` → `422`; on a random UUID
   → `404`.

**Boundary check (important):** there is **no** API that returns who voted. The
`tool_knowledge_observation` table is server-only; confirm no `/toolkb` response ever contains a
`voter_hash`, a user id, or a per-vote record — only aggregate `confirm_count`/`reject_count`.

## Edge/failure paths already pinned by automated tests (spot-check only)

Concurrent duplicate submission converges (no 500); `^0.x` version ranges window correctly;
`https://cad.onshape.com/helpdesk-upload/…` does not count as vendor docs; a published row
whose prose would no longer pass the contract patterns is silently omitted from GET; a single
voter confirming an entry any number of times can never auto-promote it (distinct-voter floor).
