# Completion report — SOLUSDEV-211 (SOLUS-TU-08): human confirm/reject loop

**Lane:** D (SOLUSDEV-215) · **Branch:** `SOLUSDEV-215-lane-toolkb` · **Commit:** `1110c5e`

## What was built

- `packages/api/src/solus_api/toolkb/feedback.py`:
  - `recompute_confidence(acquired_via, confirms, rejects)` — **deterministic**: confidence is a
    pure function of the acquisition base + vote counts (Beta-style smoothing, prior 3, a reject
    weighing 3× a confirm). Order-independent and auditable — the same counts always yield the same
    value, so confidence never drifts. **Precision over recall**: two rejects push a docs-tier
    entry well below the Guide tentative threshold, because a wrongly-learned meaning propagates to
    every user and must stop being served confidently fast.
  - `apply_feedback(session, entry_id, verdict, user)` — increments the count, recomputes
    confidence, refreshes `last_verified_at` on a confirm (a confirmation IS a re-verification),
    emits `tool_knowledge.confirmed` / `tool_knowledge.rejected` events. Raises `LookupError` for a
    missing/deleted entry.
- Route `POST /api/v1/toolkb/entries/{id}/feedback` (`{verdict: confirm|reject}`, auth + verified;
  `422` on a bad verdict, `404` on unknown entry). Low confidence then renders tentative via
  TU-07's `effective_confidence` — the existing Guide path needs no change.
- Guide resolver now surfaces each resolved step's `entry_id` (the feedback target). Frontend
  `features/guide/`: `guideApi.sendFeedback(entryId, verdict)` + a Helpful/Wrong control per
  available step in `GuidePanel` (fire-and-forget; a failed request shows no fabricated success).

## Acceptance (met)

- A user confirms/rejects a guidance step; the correction updates the shared entry's confidence
  (deterministically) and provenance-of-freshness (`last_verified_at` + the data event).
- Low-confidence entries render tentative in Guide (never a confident wrong instruction).

## Interpretation notes (delegated judgment)

- **"Updates provenance"**: the CTR-05 `provenance` enum (vendor_docs/observed_ui/
  operator_authored) records the SOURCE, which a user vote does not change — so a confirm does not
  rewrite it. The freshness/audit half is captured by `last_verified_at` + the consent-gated data
  event instead. Per-user vote identity is **deliberately not** stored on the entry: it would be a
  customer-linkable reference the tenancy boundary forbids on the cross-tenant table; it lives in
  the event store only.

## Tests

`tests/toolkb/test_feedback.py` — pure recompute (base, confirms-raise, rejects-drop-hard,
reject-outweighs-confirm, unit-interval), endpoint (confirm raises + stamps verification, two
rejects → tentative, auth, bad verdict → 422, missing → 404). Frontend `guideApi.test.ts`
(feedback POST shape) + `GuidePanel.test.tsx` (reject fires to the entry, no control for
KB-uncovered steps). Full toolkb suite 145 passed; mypy clean; renderer typecheck clean; 15 guide
FE tests.

## Flag for human (Phase 0 §7.3)

**Anti-ballot-stuffing:** one user's rejects move shared cross-tenant confidence, so a coordinated
account could suppress good entries. The smoothing prior damps single actions and rate limiting
applies, but per-user once-per-entry enforcement needs the **server-only votes table** that is
pending the §7.3 install-identity sign-off (same table TU-05 needs). Deferred to that decision.
