# Completion — SOLUSDEV-107 (SOLUS-LNK-02): Swap to real fingerprint output

Branch: `SOLUSDEV-63-solus-graph` · LANE A · 2026-08-08

## What was built

The mock-and-swap payoff: `link_from_fingerprint(session, *, project_id, config)` in
`linking/linker.py` — takes the per-project advisory lock, gathers the same modality-hint
observations `scan_project` gathers, runs the pure matcher, and feeds the SAME `link()` the
mock path uses. **Linker core unchanged by the swap** (the acceptance criterion); the LNK-01
mock e2e still passes untouched.

Coverage broadened per ticket:
- Multi-instance parts: two board positions of one MPN link via the real matcher.
- Conflict handling: competing canonical parts on one entity pair resolve by confidence;
  an exact tie is flagged (`LinkResult.ties`), the pair left un-edged, and a previously
  asserted edge for a now-tied pair is retracted — ties are never guessed.
- FP precision posture verified end-to-end: a datasheet-only entity is `unmatched` by the
  real matcher ("a datasheet alone is a family") and produces no edge; `scan_project` →
  `link_from_fingerprint` agree (FK stamps and edges consistent; canonical rows never edge
  endpoints).
- Honest scoping: nets/sub-assembly link types have **no data source yet** (no connector
  emits such hints); not faked. Cross-entity LOW_CONFIDENCE cannot arise from v1 hints
  (photo is the future source); the low-confidence edge path is exercised via the contract
  and the mock.

## Phase 4 review (code + security, adversarially verified) — 6 confirmed findings, all fixed

1. **HIGH — gather outside the lock**: `link_from_fingerprint` now locks BEFORE gathering
   (reentrant xact lock), so a stale-snapshot run can no longer retract a fresher run's
   correct edges. Mirrors `scan_project`'s lock-before-gather.
2. **HIGH — unbounded O(n²) fan-out**: pairing capped at `MAX_LINKED_OBSERVATIONS_PER_PART`
   (64) per part; excess dropped deterministically, surfaced via `LinkResult.capped_parts`
   (crafted connector hints can no longer mint 100k edges).
3. **MEDIUM — N+1 resolution**: replaced with batch resolution — one id query + one
   `(connector, external_ref)` tuple query per run, memoized per ref; no per-observation
   round-trips inside the lock.
4. **MEDIUM — write path used read-path fallback**: default is now WRITE-SAFE — a dead
   `graph_entity_id` refuses rather than falling back to the pair (FP-02's write-path
   rule: a re-synced row can be a different physical component). Only `link_from_mock`
   opts into the fallback (fixture ids).
5. **LOW — idempotency untested across commit**: added a commit-crossing re-link test
   (JSONB/Float DB round-trip equality holds).
6. **LOW — LinkResult docstring wrong**: corrected (unresolved/ties/capped restate input).

Refuted by verification (no change): duplicate-live-edge invisibility; `link_from_mock`
path-parameter file read (not route-exposed; pinned as internal).

## Tests

`packages/api/tests/test_linker.py` — 25 tests total (15 LNK-01 + 10 LNK-02: conflict by
confidence, tie flagging/clearing/retraction, real-matcher multi-instance, datasheet
refusal, full scan→link pipeline, write-safe stale-id refusal, mock-path fallback,
across-commit idempotency, fan-out cap). Lint + mypy clean.

## Flags

- LANE 0 follow-ups (unchanged from LNK-01): partial unique index for source-less edges;
  extraction of one shared public gather (the gather loop is duplicated from
  `scan_project` because `fingerprint/` is `@shared`).
- No perf probe at 10k-entity scale yet; batch resolution makes the run O(queries)=3, but
  a committed probe like SYS-02's would evidence it — candidate for LNK-08.
