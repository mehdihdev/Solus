# Completion report — CTR-08: fingerprint contract amendment (SOLUSDEV-136)

**Commits:** `a074870` (dedicated tier-2: contract.py enum, human-approved in-chat
2026-08-07 per ADR-028/ADR-032) + `ec0ab18` (matcher routing, fixtures, tests, doc
addendum, tier-1 per ADR-032).

## What was built

1. **`Modality` extended additively** with `bus_enumeration`, `firmware_symbol`,
   `telemetry_channel` (`fingerprint/contract.py`, 5 lines, nothing else in the file or
   commit). Existing five members unchanged, order preserved.
2. **Silent-drop hazard closed at the root** (`fingerprint/matcher.py`): the CAD-only
   routing branch became a `_V1_SCORED` fall-through — ANY modality the v1 pipeline
   doesn't score now lands in `unmatched`, visible, never dropped. Covers the three new
   members and every future one structurally.
3. **Contract doc amended** (`docs/contracts/fingerprint-output.md`): dated §6 addendum
   (evidence semantics + confidence bands + explicit invariants-NOT-modified list +
   versioned-by-dated-amendments statement) and new **§6a canonical names** (the ADR-027
   three-name identity chain + the names that do NOT exist).
4. **Fixtures** (`packages/api/tests/fixtures/hardware_modalities.json` + new test module):
   bus-enumerated servo (XM430-W350, MATCHED @0.92 — human-adjudicated),
   firmware-inferred servo (XL330-M288, LOW_CONFIDENCE @0.55), and the load-bearing
   ambiguous telemetry case that provably links nothing.

## Governing docs consulted

DECISIONS.md (ADR-012, ADR-027, ADR-028, ADR-032), docs/contracts/fingerprint-output.md,
the MCP-04/SOLUSDEV-100 amendment precedent in docs/contracts/metadata-extraction.md,
CLAUDE.md §7/§9. Frozen surface: W0-06 (`contract.py`, `fingerprint/__init__.py`,
`mock_canonical_parts.json`) and all W0-05 connector files.

## Ticket corrections (deviations from the ticket text, per its own "verify against code" instruction)

- **The ticket's canonical-names list was inverted.** It ordered §6a to declare
  `source_key`, `external_ref`, and `SourceRef` non-existent — all three EXIST and are
  ADR-027's deliberate three-name identity chain (`EntityOut.source_key` ==
  `graph_entity.external_ref` == `SourceRef.external_ref`). The name that does NOT exist
  is the ticket's claimed "real name" `EntityOut.source_id` (only an ORM FK column,
  provenance plumbing). §6a documents reality; human confirmed this direction in-chat
  2026-08-07.
- **No schema version exists to bump** (no field in doc or code). Following the repo's
  only amendment precedent (MCP-04, commit `34e305e`), the contract is versioned by dated
  addenda; the addendum says so explicitly. No `schema_version` field was added (would
  change serialized shape for zero consumers).
- **"W0-08 amendment precedent (SOLUSDEV-158)" doesn't exist in git history.** The actual
  precedent used is MCP-04's amendment of `metadata-extraction.md`.
- **Ticket paths were stale** (`docs/contracts/fingerprint-output.md` was right; the code
  paths are `packages/api/src/solus_api/fingerprint/`, not `backend/...`).

## Delegated-judgment decisions

- **Confidence bands are doc-normative only** — no `matching.yaml` weights / `config.py`
  ceiling validators were added, because no scorer for these modalities exists and
  `Weights` is `extra="forbid"` (entries would be dead config). The addendum obligates the
  future scorer ticket to add the load-validated ceilings, mirroring the `photo` idiom.
- Fixture lives in `tests/fixtures/` (not `src/`) — it is contract proof with no
  production consumer; keeps the W0-06 mock byte-identical.
- New-test fixture connectors `dynamixel`/`ros2`/`runtime`/`github` are free strings per
  the contract (no connector registry exists; consistent with ADR-027's free-string
  stance).

## Human adjudications recorded (AskUserQuestion, 2026-08-07)

- The exact 5-line enum diff — approved (ADR-028/ADR-032 tier-2).
- Bus-enumerated fixture state — MATCHED @0.92 (device self-report is exact_mpn-class
  evidence; part identity ≠ motor→joint link, which still routes through LNK-01
  MATCHED-only stamping + ADR-012 human confirmation).
- §6a documents the real name chain (above).
- Note for review: the addendum's "`bus_enumeration` may exceed `thresholds.matched`" is
  the FIRST new modality allowed above matched (datasheet/photo/LLM were all capped
  below). Ratified via the fixture-state answer; flag if you want it provisional instead.

## Verification

- `git diff a074870^` on `contract.py` = exactly the 5 approved lines; empty diff on
  `fingerprint/__init__.py`, `mock_canonical_parts.json`, `test_fingerprint_contract.py`,
  and all `connectors/` (W0-05) files.
- TDD: both RED states validated before their fixes (enum ValidationError ×5 tests; 3/4
  parametrized matcher cases failing), then GREEN.
- 147 passed: `test_fingerprint_contract.py` (9, untouched) +
  `test_fingerprint_hardware_modalities.py` (5 new) + `test_matcher.py` (45, incl. the new
  4-way parametrized fall-through test) + `test_fingerprint_eval.py` (zero-false-merge
  hard gate) + `test_ingest.py`.
- `ruff` clean, `mypy --strict` clean on all touched files. Full backend suite runs at the
  SYS-02 gate (same branch, same session).

## Flagged, not fixed (pre-existing)

- `connectors/eda.py:141-142` emits hint keys `schematic_symbol_name`/`datasheet_ref`,
  but `matcher.py` `_HINT_KEYS` reads `schematic_symbol`/`datasheet` — KiCad/Altium symbol
  and datasheet hints silently never reach the matcher today. Separate ticket recommended.
