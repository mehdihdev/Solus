# §2.17 Tool-knowledge store (`/api/v1/toolkb`) — SOLUS-TU-04 / SOLUS-TU-06

> **Tier-1 amendment** (ADR-032): docs/api had no toolkb plan; this file was added with the
> implementation in SOLUSDEV-207/209 and is called out in the completion report. Contract:
> `docs/contracts/tool-knowledge.md` (CTR-05). The store is **cross-tenant by design** — every
> tenant reads the same published tool knowledge; the tenancy boundary is what a row _cannot
> contain_ (no customer identifier, no free-form container, validated prose), not who may read it.

Writes go through the TU-06 ingestion guard (`solus_api.toolkb.guard.ingest`) — the ONLY code
path that constructs a store row (tripwire-tested). Status is computed by the guard, never
client-requestable. The `docs` acquisition path (the only one that publishes without human
review) is server-side only and not expressible over HTTP.

## POST /api/v1/toolkb/entries

Auth: authenticated + verified email (`RequireVerified`).

Body — exactly one field; anything else is a sanitized 422:

```json
{ "entry": { …CTR-05 ToolKnowledge shape, provenance MUST be "operator_authored"… } }
```

**HTTP submissions are pinned to the operator tier** (Phase-4 review, CRITICAL finding):
`acquired_via` / `endpoint_scope` are properties of Solus-side ingestion code, never body
fields — a client claiming "api_geometry, global scope" would skip the vendor-control
allowlist and forge the 0.9 confidence stamp the human reviewer trusts. The `docs`,
`api_geometry`, and `visual` tiers are reachable only from server-side jobs that call
`guard.ingest` with a context they can vouch for (docs ingestion now; bridge-authenticated
probe submissions are a future design item for TU-01 result upload).

The whole body is taken as untyped JSON and shape-checked in the route with fixed error
strings: the framework-level 422 handler echoes offending input (`exc.errors()` includes
it), and nothing from a rejected toolkb body — values or keys — may ever echo.

`201`:

```json
{ "data": { "id": "<uuid>", "status": "candidate", "confidence": 0.7 } }
```

All HTTP submissions land as `candidate` (staged, never served) until an operator approves
via the review CLI (`python -m solus_api.toolkb.review`). Initial confidence by acquisition:
api_geometry 0.9, docs 0.8, operator 0.7 (= the HTTP ceiling), visual 0.5 (provisional
values; TU-08 recalibrates from confirm/reject). A server-side docs ingest that finds a
lower-trust candidate already holding its identity **overtakes it in place** (content
replaced with the docs version, status published) rather than being silently blocked.

`422` — guard rejection, `error.code` = the guard's reason, message carries field names and
rule text only (never the rejected content):

- `contract_validation` — the CTR-05 net caught it (customer-shaped prose, extra field,
  bad control-id slug, out-of-range locator…)
- `provenance_mismatch` — acquired_via ↔ provenance map broken
- `per_document_source` — api_geometry from a per-document endpoint (or unstated scope) for
  a control vendor docs don't know — the Onshape `featurespecs` trap
- `unknown_control` — visual detection may only recognize documented controls
- `doc_domain_not_allowed` — server-side docs path with a non-vendor URL (unreachable via HTTP)

Events: `tool_knowledge.submitted` (tool, control_id, status, acquired_via) or
`tool_knowledge.rejected` (tool re-parsed against the enum or "unknown", reason — never
entry content), consent-gated as usual.

## GET /api/v1/toolkb/entries

Auth: authenticated. Deliberately team-unscoped (see header note).

Query: `tool` (required, ToolFamily) · `version` (optional, e.g. `8.0.6` — selects entries
whose version window contains it) · `surface` · `effect` · `control_id` · `limit` (1..100,
default 50) · `cursor` (§1.4).

`200` — **published, live rows only** (candidates and soft-deleted rows are invisible),
newest first, cursor-paginated:

```json
{
  "data": [
    {
      "id": "<uuid>",
      …CTR-05 ToolKnowledge fields…,
      "confidence": 0.8,
      "last_verified_at": "2026-08-08T21:00:00Z" | null
    }
  ],
  "meta": { "limit": 50, "has_next": false, "next_cursor": null }
}
```

`422 invalid_version` on an unparseable `version`.

## GET /api/v1/toolkb/guides · GET /api/v1/toolkb/guides/{guide_id} (SOLUS-TU-09)

Auth: authenticated (cross-tenant by design, like the rest of the store).

A guide is an authored task walkthrough — ordered control references + per-mode narration —
resolved against the **live** KB at read time, so it compounds as the KB thickens.

`GET /guides?tool=<ToolFamily>&version=<x.y.z>` — list summaries covering that tool+version:

```json
{ "data": [ { "id", "tool", "title", "summary", "step_count" } ] }
```

`GET /guides/{guide_id}?version=<x.y.z>` — one walkthrough, each step resolved:

```json
{ "data": {
  "id", "tool", "title", "summary",
  "steps": [ {
    "step_number", "control_id",
    "entry_id",                           // resolved KB entry UUID — the TU-08 feedback target
    "note_guide", "note_expert",          // both modes returned; panel switches with no round-trip
    "available",                          // false ⇒ KB doesn't cover this step (never faked)
    "tentative",                          // true ⇒ confidence < 0.6, render as uncertain
    "stale",                              // true ⇒ past its re-verification window (TU-07)
    "locator",                            // {x,y,w,h} normalised 0..1, or null — see below
    "label", "description", "shortcut", "menu_path", "surface", "confidence"  // null when unavailable
  } ]
} }
```

Unknown `guide_id` → `404`. `422 invalid_version` on an unparseable `version`. An unavailable or
tentative step is marked, never faked — the renderer degrades gracefully and never shows a
confident wrong pointer.

`locator` (SOLUS-TU-10 / SOLX-03) is the geometry the Guide **overlay** needs to point at a real
control: `{ "x", "y", "w", "h" }` normalised 0..1 within the tool window, matching CTR-05's
`ScreenLocator` and CTR-06's `ControlPointer.locator` — one type end to end. The key is always
present; `null` is the **common** case, not an error, because vendor documentation carries no
coordinates (TU-02 ingests `locator: null`) and only the visual path (TU-03) populates it. The
side panel ignores the field. The overlay must fall back to the panel rather than guess at a box
it does not have.

## POST /api/v1/toolkb/entries/{id}/feedback (SOLUS-TU-08 / TU-05)

Auth: authenticated + verified email. Body: `{ "verdict": "confirm" | "reject" }` (`extra="forbid"`).

Records the caller's vote and recomputes the entry's confidence deterministically. `200`:

```json
{ "data": { "id", "confidence", "confirm_count", "reject_count" } }
```

`404` unknown/deleted entry; `422` bad verdict.

**One vote per distinct voter (TU-05).** Each vote is stored in the **server-only**
`tool_knowledge_observation` table keyed on a salted one-way voter hash (no user/team/project FK,
never returned by any route); a repeat vote from the same voter updates that single row rather than
inflating the count. So `confirm_count`/`reject_count` are DISTINCT-voter counts, and a single actor
can never move an entry on their own.

**Corroboration can auto-share, or retract (TU-05).** After each vote the entry's shared-store
status is reconciled from the full tally: a **candidate** with ≥ 2 distinct confirms AND confidence
≥ 0.85 is **promoted to `published`** (now served to every tenant — this is the compounding
mechanism); a promoted non-docs entry whose confidence falls below 0.6 is **retracted** to
`candidate`. Docs-published entries are vendor-authoritative and never retracted. Promotion is
order-independent (evaluated from the whole tally, not vote arrival order). Events:
`tool_knowledge.confirmed` / `tool_knowledge.rejected` (never entry prose).

## Not in this plan (future tickets)

- User-authored guides (a guides table) — the current guides are committed seed data.
- Semantic search over the embedding column — when the Guide needs it (rag pattern ready).
- PATCH/DELETE — review is operator-CLI only for now (open question Phase 0 §7.1).

## SOLUSDEV-251 (INTEGRATIONS I4) amendment — tool knowledge in the SOL loop

No new routes. Two seams inside the API consume and feed the global table (ADR-033):

- **Notes on write tools.** `agent/tools/knowledge.py::TOOL_CONTROLS` maps each MCP write tool
  to the vendor-documented UI control it acts on (`kicad.set_symbol_property` →
  `kicad.eeschema.edit_symbol_properties`; `onshape.set_variable` →
  `onshape.partstudio.variable_table`; `onshape.add_feature`/`update_feature` →
  `onshape.partstudio.feature_list`). When the SOL route assembles the turn's descriptors, a
  PUBLISHED entry for that control is appended to the tool's description as one nonce-fenced
  `tool_knowledge` data block (`{control, note}`, ≤ 400 chars) — the model learns how the TOOL
  behaves ("writing the Variable Table replaces it") without any prose entering the prompt as
  an instruction. Candidates are never read; nothing project-scoped is read.
- **Outcome feedback.** After a confirmed write actually runs (`confirmations.decide_confirmation`,
  the sanctioned post-approval site) its outcome is one vote on that control through
  `toolkb.feedback.apply_feedback` — `confirm` when the write landed, `reject` when the tool
  refused (per tool: a KiCad write that answers `changed: false` with a reason is a rejection
  even though the result is `ok`). Per-voter idempotent, as every vote is.
- **Seed.** `scripts/seed-toolkb-mcp-controls.py` admits the three controls through the guard's
  docs path (vendor documentation URLs, published directly). The catalogs
  `toolkb/catalog/{kicad,onshape}.json` list the ids as known vendor controls. Set
  `SOLUS_TOOLKB_VOTE_SALT` so votes survive an API restart (the unset warning is real: the live
  run counted the same user twice across a restart).
- **Bridge write previews** (`bridge/previews.py`): a companion write tool gets an approval-card
  diff by READING through the same bridge first — `kicad.set_symbol_property` previews as
  `R1 · Value: <current> → <new>` from `kicad.extract_project_netlist` (the schematic's project
  file), `before: None` when the read declines. The gate re-runs the preview at approve time and
  refuses on divergence, exactly as for in-process tools.
