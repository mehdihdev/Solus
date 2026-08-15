# Completion — SOLUSDEV-198 (SOLUS-IMP-02): Consequence model + "why" explanations

Branch: `SOLUSDEV-63-solus-graph` · LANE A · 2026-08-08

## What was built

`packages/api/src/solus_api/impact/consequences.py` — the checker-backed
`ConsequenceProvider` for `compute_impact`, closing the IMP-01/02 split:

- **Warning → Consequence mapping**: stable ids
  (`checker_id:discriminator:entity-digest`), headline = rule message (truncated to the
  contract's 200), evidence rows flattened from `Warning.evidence` (per-load rows for the
  power rule; all caps enforced), `locator` emitted **only** when `sch:<name>` satisfies
  the contract's `LOCATOR_RE` — adversarial/spaced names yield None, never a violation.
  `action=None` (v1 rules compute no proposable fix — honest null, per contract comment).
- **Every implicated entity gets the row** (the over-drawn supply AND its starving load),
  so findings surface wherever the traversal reaches. Rules stay pure (ADR-003); the
  I/O-bearing narration lives in this assembly layer.
- **Uncertain/unknown consequences are MARKED, not dropped**: a warning from a rule the
  adapter has no knowledge of maps generically (message + marked template rationale).
- **LLM narration (Phase 0 Decision 3)**: `build_narrate_fn` adapts the orchestration
  gateway's `complete()` to the narration seam — mirroring `build_embed_fn` exactly. ONE
  batched, metered call per analysis (`cost-aware-llm-pipeline` consulted: routing,
  budget gates, retries, and the credit ledger are the gateway's per ADR-017/018/019;
  identity `user_id`+`session` is the expected shape). Output tokens capped (1200);
  evidence in the prompt capped at 600 chars/finding.
- **§7 posture**: finding text is framed as delimited DATA (`<findings>` block, `<`
  escaped so content cannot close it) beneath an explicit data-not-instructions
  instruction; narration output is untrusted model output — JSON-parsed defensively,
  filtered to known consequence ids, type-checked, stripped, capped at 4000 before
  becoming `Consequence.rationale`. Any failure (keyless, over-budget, provider error,
  garbage output) degrades to the deterministic template suffixed with `TEMPLATE_MARKER`
  — impact never fails and never returns empty because narration was unavailable.

## Tests (written first, red → green)

`packages/api/tests/test_consequences.py` — 13 tests: multi-entity attachment, stable
ids, cross-domain sensor conflict (code+electrical), clean-graph empty, locator gating,
unknown-rule marking, one-batched-call narration replacing templates, None/empty/oversized
narration fallback + bounding, red-team prompt construction (hostile connector string only
ever inside the data block) and defensive parsing, and the fully-real acceptance:
`compute_impact` + `checker_provider` on a seeded sample project returns real consequences
across electrical AND code with paths and contract round-trip validation — the "motor
current change → ≥2 domains" criterion with zero injected data.

## Decisions under delegated judgment

- Template fallback = rule message + suggested area + marker (the rules' messages already
  carry names and numbers); richer per-rule prose is exactly what narration is for.
- One consequence object shared across its implicated entities (one finding, N locations).
- Narration seam is a plain async callable; the gateway wiring composes at the (future)
  route/job layer, like `EmbedFn`.

## Phase 4 review (correctness + §7 model-orchestration, adversarially verified) — 11 confirmed, all fixed

Engine (IMP-01 scope, fixed here):
1. **MEDIUM** focus row truncated out of a capped roots load → `KeyError` in path
   assembly (live-reproduced by the verifier) → the engine now pins the focus row it
   already holds; regression test added.
2. **MEDIUM** `_canonical_siblings` had no ORDER BY → nondeterministic tie paths →
   ordered by `(created_at, id)` per the traversal's convention.
3. **LOW** no test walked a multi-hop path THROUGH a synthetic sibling seed → added.

Consequences (IMP-02 scope):
4. **MEDIUM** `_consequence_id` collided for same-checker/same-entity warnings without a
   `conflict` key, and right-truncation could amputate the digest → digest now covers the
   full warning content; head sanitized (`[A-Za-z0-9_.-]`, ≤115) so the 12-char digest
   always survives.
5. **MEDIUM** raw `conflict` values could break the `<finding id="...">` attribute →
   same sanitization closes it (verified: quotes/spaces/`<` impossible in ids).
6. **MEDIUM** identity-less `build_narrate_fn` defaults silently skipped budget
   gates/ledger → identity now REQUIRED; `allow_unmetered=True` is the explicit opt-out
   (mirrors `build_embed_fn`).
7. **MEDIUM** narration prompt unbounded in warning count → capped at 32 worst-first
   findings per analysis; the tail keeps marked template rationale; cap logged.
8. **LOW** `re.match` accepted a trailing newline the TS locator twin rejects →
   `re.fullmatch`.
9. **LOW** empty `Warning.message` → contract ValidationError → headline falls back to
   `"<checker_id> finding"`.
10. **LOW** duplicate ids in `entity_ids` attached the same row twice → deduped.
11. **LOW** `TEMPLATE_MARKER` spoofable by model output → narration containing the
    marker is refused (falls back to the genuine template).

Refuted by verification (no change): finding-id interpolation as an instruction/data
separation break (the confirmed attribute-safety variant covered the real risk).

Regression tests for every fix live in `test_consequences.py` / `test_engine.py`
(35 impact-module tests total, all green).

## Flags

- The narration red-team test covers prompt construction and parsing; a live-gateway
  injection test (adversarial repo → prompt → model) belongs to the agent test suite's
  red-team fixtures once the impact route lands (route planned in
  `docs/api/API-implementation.md` §14).
