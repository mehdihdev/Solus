# Completion report — SOLUSDEV-209 (SOLUS-TU-06): HARD tenancy ingestion guard + rejection tests

**Lane:** D (SOLUSDEV-215) · **Branch:** `SOLUSDEV-215-lane-toolkb` · **Date:** 2026-08-08
**⛔ Gate honored:** nothing writes to the shared store except through this guard; the HTTP
surface shipped with the guard in front of it, never before it.

## What was built

- `toolkb/guard.py` — `ingest()` is **the only write path** into `tool_knowledge`; a tripwire
  test greps the source tree and fails if `ToolKnowledgeEntry(` is constructed anywhere else
  (same spirit as `tool-knowledge.illegal.ts`). Rules in order: CTR-05 re-validation (the NET,
  never the filter); closed acquired_via↔provenance map; per-path source allowlist; idempotent
  dedup; **status computed, never a parameter**. `approve()`/`reject()` are the review level.
- `toolkb/catalog.py` + `toolkb/catalog/*.json` — the "allowlist at the source" the contract doc
  demands: a control is known vendor surface iff a curated seed file or a previously PUBLISHED
  `vendor_docs` row names it. `VENDOR_DOC_DOMAINS` (host or host/path-prefix, https-only,
  exact-host, segment-boundary prefix match) decides what counts as vendor documentation.
- Per-path rules: **docs** (server-side only) requires a vendor-doc URL — checked then discarded
  (no column for it, by design) — and is the only auto-publishing path; **api_geometry** from a
  per-document endpoint (or unstated scope) must name a known vendor control — the **Onshape
  `featurespecs` trap**, rejected by name (`PER_DOCUMENT_SOURCE`); **visual** may only recognize
  known controls, never introduce one, never auto-promotes; **operator** may introduce controls,
  always staged.
- **Rejections carry no entry content** — not in exceptions (sanitized pydantic details,
  `from None` so the input-embedding cause never reaches a traceback), not in HTTP responses,
  not in logs, not in events (tool re-parsed against the enum or "unknown").
- `toolkb/review.py` — operator CLI (`python -m solus_api.toolkb.review list|show|approve|
reject`); approve stamps `last_verified_at`; reviewer identity logged, deliberately never
  stored (open question §7.1: durable audit trail).

## Phase-4 verification (mandatory reviews) — run and FIXED, not noted

Fresh-context review workflow: security-reviewer + code-reviewer + python-reviewer over the
staged diff, every finding adversarially verified by an independent agent. **9 confirmed
findings, all fixed with regression tests:**

1. **CRITICAL — client-forgeable trust tier.** `acquired_via`/`endpoint_scope` were HTTP body
   fields; `endpoint_scope="global"` skipped the vendor-control allowlist and stamped forged
   0.9 confidence — the exact signal the human reviewer trusts. **Fix:** HTTP submissions are
   pinned server-side to the operator tier; the fields no longer exist in the API; higher tiers
   are reachable only from server-side ingestion code. (Consequence recorded in
   docs/api/toolkb.md: TU-01 probe-result upload needs a verifiable channel — future design
   item, likely bridge-authenticated.)
2. HIGH — non-object bodies died in the framework validator, whose 422 echoes input. Fix: body
   taken as untyped JSON, shape-checked in-route with fixed strings (keys are attacker-chosen
   too — never echoed).
3. HIGH — `raise … from exc` re-attached the pydantic error whose `str()` embeds the input.
   Fix: `from None`; traceback-render test pins it.
4. HIGH — version ranges passing the CTR-05 regex but not the key grammar ("==2.0", "<<2.0",
   ">=3.0 <2.0", ">9999 components") became unhandled 500s. Fix: sanitized
   `contract_validation` rejection.
5. HIGH — check-then-insert race → unhandled IntegrityError 500. Fix: savepoint + converge on
   the winner idempotently (matches the existing stripe_events pattern).
6. HIGH — npm caret `^0.x` windows were ~10× too wide. Fix: leftmost-non-zero bump + tests.
7. MEDIUM — a low-trust candidate squatting an identity silently blocked the authoritative docs
   publish forever. Fix: a docs ingest **overtakes** a lower-trust row in place — content
   replaced with the docs version (publishing the squatter's prose under docs trust would be
   worse), logged.
8. MEDIUM — a stored row failing CTR-05 re-validation at read time would leak its content into
   server logs via the catch-all handler. Fix: per-row omit + id/tool-only log line.
9. MEDIUM — vendor-doc path prefix used bare `startswith` (`/helpdesk-upload` passed `/help`).
   Fix: segment-boundary match.

## Tests

`tests/toolkb/test_guard.py` — the full rejection suite: the featurespecs canonical case
(prose passes the net; guard still rejects — with a sanity assertion proving the net alone
would have admitted it), menu-path customer content (`~/designs/arm_v3.f3d`), NFKC homoglyph,
document-scoped control id, extra field, provenance mismatch, customer doc-URL, docs-without-URL,
visual unknown control, unstated probe scope; accept paths per tier; idempotency; race
convergence; docs-overtake; traceback-leak pin; embedding best-effort; tripwire.
`test_catalog.py`, `test_review.py`, `router_test.py` (trust-tier forging, never-echo incl.
non-object bodies and wrapper keys, candidate-never-served, GET re-validation omission).
Full suite **1640 passed / 0 failed**, mypy clean.

## Open items (human)

Phase 0 §7.1 (operator identity/audit-trail/two-person rule), §7.5 (catalog + doc-domain
curation sign-off — current seeds are minimal agent-curated lists for kicad/fusion), and the
TU-01 probe-upload channel design named in finding 1.
