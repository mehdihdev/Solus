# Completion — SOLUSDEV-197 (SOLUS-IMP-01): Impact traversal engine

Branch: `SOLUSDEV-63-solus-graph` · LANE A · 2026-08-08

## What was built

`packages/api/src/solus_api/impact/` (CODEOWNERS `@lane-graph`):

- `engine.py::compute_impact(session, project_id, *, focus_id, change, provider, depth, max_entities, computed_at)`
  → CTR-04 `ImpactResult`. **No new traversal was written**: the engine drives
  `graph/neighborhood.py::load_neighborhood` (SOLUSDEV-191, "the ONE traversal in Solus"),
  per the Phase 0 re-scope. Bounded by the traversal's own caps (depth ≤ 2, ≤ 500 entities,
  ≤ 10k edge scan, ≤ 8 edges/entity); `truncated` propagates to the result.
- Canonical identity, both forms: real `same_as` edges (LNK-01/02) traverse like any edge;
  FK-only canonical siblings (FP-02-stamped, unlinked) seed the BFS at distance 1 behind a
  synthetic `same_as` hop — same physical part, one identity hop, whether or not the linker
  materialized the edge. FP-02 bookkeeping rows (`origin="fingerprint"`) are traversal roots
  but never surface as nodes.
- Parent-tracked multi-source BFS over the induced subgraph yields per-node paths starting at
  the focus; contract invariants hold by construction (`distance == len(path)`, node severity
  = worst consequence, `consequences` non-empty or the node is omitted). Nodes sort
  worst-first, then nearest, then label (deterministic).
- Consequences via a pluggable async `ConsequenceProvider` — the engine carries no rule
  knowledge (ADR-013: rules live in the checker library). IMP-02 supplies the checker-backed
  provider with gateway narration.

## Governing docs

CTR-04 `contracts/impact.py` + `docs/contracts/impact.md` (frozen; validated round-trip in
tests) · ADR-001/013/027 · CLAUDE.md §7 (tenant isolation via the traversal's project
scoping) · Jira SOLUSDEV-197 + Phase 0 re-scope comment. **docs/api amendment**:
`API-implementation.md` §14 plans `POST /projects/{id}/impact` (tier-1, ADR-032) — the engine
is live, the route lands with LANE B's live wiring.

## Tests (written first, red → green)

`packages/api/tests/test_engine.py` — 11 tests: empty result honesty, distance-1 path shape,
two-hop relation chain, FK-sibling `same_as` hop, canonical-row exclusion, `same_as`-edge
cross-domain walk, unreached/cross-project consequence dropping, truncation propagation,
worst-first sorting + per-node worst severity, missing-focus refusal, and the hero-shaped
three-domain scenario (driver@1 critical / firmware@2 / harness@1) with full contract
round-trip validation.

## Decisions under delegated judgment

- Provider seam is a plain async callable, not a class hierarchy.
- Focus row itself never becomes a node (consequences at the focus are the change, not its
  impact); revisit if the widget wants self-impact rows.
- FK siblings enter at distance 1 (not 0) so every path can honestly start at the focus.

## Flags

- The acceptance criterion "correct downstream consequences across ≥2 domains on a sample
  project" is met at engine level with injected consequences (hero-shaped test); the fully
  real path (seeded attrs → CHK rules → consequences) lands with IMP-02's provider, by design
  of the IMP-01/IMP-02 split.
- No HTTP route yet — planned in `docs/api/API-implementation.md` §14; nothing in `docs/api`
  authorized one for this ticket.
