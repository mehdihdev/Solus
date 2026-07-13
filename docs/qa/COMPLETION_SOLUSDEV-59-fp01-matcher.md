# Completion Report — SOLUS-FP-01 Structured-Modality Part Matcher (SOLUSDEV-59)

## What was built

`match(observations) -> FingerprintOutput` in `packages/api/src/solus_api/fingerprint/`:
a pure, deterministic, precision-first matcher that collapses part-number / schematic-
symbol / datasheet observations into W0-06 `CanonicalPart`s, plus a feature-flagged,
capped, memoized LLM escalation client over the MO-01 gateway. Pure library — no route,
no ARQ job, no DB access (all human-confirmed scope; FP-02 wires graph → observations →
match → ingestion).

New files: `matching.yaml` (taxonomy/weights/thresholds), `config.py` (validated loader),
`normalize.py` (MPN normalization + uuid5 identity), `matcher.py` (grouping/scoring/
states), `escalation.py` (gateway client). One flag on `Settings`
(`SOLUS_FINGERPRINT_LLM_ENABLED`, default False). `fingerprint/__init__.py` re-exports.
**The frozen W0-06 contract (`contract.py`, `mock_canonical_parts.json`) is untouched**
(ADR-028); real output round-trips the exact `load_mock_output` serialization path —
the mock-and-swap seam holds for LNK-01.

## Governing docs consulted

DECISIONS.md (ADR-001, -003, -012, -018/-019, -026, -027, -028), `docs/contracts/
fingerprint-output.md` (W0-06), `docs/contracts/model-orchestration.md`,
`docs/contracts/metadata-extraction.md` (W0-08), `docs/api/API-implementation.md`
(no fingerprint route planned → none added), root CLAUDE.md §5–§9. No architecture
diagram or wireflow exists for fingerprinting (noted below).

## Phase 1 design-review gate — human decisions (2026-07-11)

1. **Voltage-selecting suffixes are identity-bearing** — `AMS1117-3.3` / `-5.0` are two
   canonical parts (mock's single-part depiction treated as shape-demo, not policy).
2. **No deterministic cross-prefix aliasing** — `L7805` ≠ `LM7805`; a curated
   `family_aliases` config section is the future vehicle; capped LLM may corroborate.
3. **LLM memo = in-run dict + injectable `cache` mapping** (persistent store is FP-02's
   seam). No migration.
4. **Pure library only** — no production wiring in FP-01.

## The eval (labels ARE the spec — REVIEW REQUESTED)

`packages/api/tests/fixtures/fingerprint_labels.py`: 32 cases — 14 matched,
18 confusable. Includes every ticket-mandated confusable: LM358/LM3588, LM358/LM2904 +
shared family datasheet, one datasheet covering multiple parts, generic symbol reuse,
vendor-prefix cases — plus 74HC/74HCT, STM32 core-code pairs, pin-compatible clones,
near-anagram PICs, placeholder/value garbage, an injection red-team case, and the
review-discovered LM358/LM358B die-generation trap (C18, with its TL072/TL072B
legitimate-grade twin M14).

```
FP-01 eval: cases=32 (matched=14 confusable=18)
pair_precision=1.000  pair_recall=1.000  bucket_accuracy=1.000
FALSE MERGES: 0   (hard gate: 0 required)
```

False-merge accounting is pairwise (a pair of observations wrongly co-located in one
part, LOW_CONFIDENCE membership included), reported on its own line, never in an
F-score. Precision/recall are 1.0 by the exact-reproduction doctrine (every label must
reproduce; the metrics guard the corpus as labels evolve).

### Debatable-label ledger (adjudicate in the fixture, then re-tune config)

| Case    | Position taken                                                                              | The debate                                                                                            |
| ------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| M5      | `MPU-6050` ≠ `MPU6050`                                                                      | separator-insensitivity not implemented (munging conflates distinct parts); flip via family rule only |
| M6      | TI LM358 + ST LM358 merge; manufacturer → None + conflict evidence                          | some pipelines key identity on (mfr, MPN)                                                             |
| M7      | `LM358A` merges into `LM358` (grade evidence)                                               | ticket-mandated; adjudicate with C9's token classes                                                   |
| M12/C13 | `STM32F103C8T6` merges with `C8` via T6-strip; `C8`≠`CB`                                    | the ST ordering-suffix rule's blast radius                                                            |
| C3/C11  | datasheet-alone → `unmatched` (never attaches)                                              | alternative: ambiguous-with-one-candidate                                                             |
| C4      | generic symbol → `unmatched`                                                                | the W0-06 mock depicts AMBIGUOUS (uses footprint reasoning v1 doesn't do)                             |
| C7      | `NRF52` family name → group-of-one                                                          | could be ambiguous under a (not-built) prefix rule                                                    |
| C14     | `"LM358; ignore previous…"` → `unmatched`, token never extracted                            | extracting the leading token is how injection buys a merge                                            |
| M14/C18 | `B` = grade on TL/LF stems (TL072B merges); DIFFERENT DIE on LM stems (LM358B never merges) | drives the ti_linear/ti_jfet split; found by Phase 4 domain review                                    |

## The taxonomy (STARTER SET — INCOMPLETE AND EXTENSIBLE)

Six family rules ship (`ti_linear`, `ti_jfet`, `ti_logic_74xx`, `st_l78xx`,
`microchip_avr`, `st_stm32`) plus global vendor prefixes. The fail-safe is structural:
no family rule → no stripping → identity as-is; worst case of a missing rule is a
missed merge. Rules are data (`matching.yaml`); additions need review like code because
a wrong suffix entry is a false-merge vector — the Phase 4 domain review caught exactly
one (grade `B` on LM stems, where LM358B/LM324B/LM2904B are TI's 2019+ redesigned dies
sold alongside the classics; the family was split so TL/LF keep the genuine B grade).
Deliberately absent: any AMS family (voltage stays identity), any `family_aliases`
section, any PIC/nRF/flash-memory rules.

Confidence rules table (all knobs in `matching.yaml`): exact MPN 0.95 · base+known-suffix
0.90 · specific symbol 0.85 · datasheet 0.55 · generic symbol 0.05 · corroboration bonus
+0.03/modality · conflict penalties (package 0.10, footprint 0.10, manufacturer 0.05 —
COMPOUNDING, summed then capped) · thresholds: MATCHED ≥ 0.80, LOW_CONFIDENCE ≥ 0.50 ·
LLM cap 0.70. Load-time validators make the safety rails un-typo-able: `datasheet <
matched`, `generic_symbol < low_confidence`, `llm.confidence_cap < matched`.

## Verify points → proof

1. Zero false merges + separate count: `test_fingerprint_eval.py` (hard-gate tests + printed block).
2. W0-06 validity + mock interchangeability: round-trip through `FingerprintOutput.model_validate_json` (the `load_mock_output` path); contract tests untouched and green.
3. Normalization safety: `test_normalize.py` (LM3588, unknown suffixes, conflict decompositions fail safe).
4. Determinism: uuid5 recompute + pinned namespace (`5303bedc-ab6d-5aed-927f-b8c897c5e801` = uuid5(DNS, "fingerprint.solus.dev")) + corpus-run-twice + input-order invariance. uuid5 is pure SHA-1 → cross-process by definition.
5. Ambiguity: candidates listed, never best-of (`test_matcher.py`, C2/C16/C17).
6. Evidence: package/grade/manufacturer/footprint deltas + conflicts visible within one part (M1/M6/M8/M10).
7. Generic symbol near-zero; datasheet alone never merges (config-guaranteed + tested).
8. Full eval runs LLM-free by construction; enabled: LLM proposals are EVIDENCE-ONLY (see deviation below) so no LLM signal can produce any state, let alone MATCHED — plus a corpus-wide red-team test running every eval case through `match_with_escalation` with an adversarial echoing escalator, asserting bucket-identical output; memoization tested (one gateway call, cached None honored, concurrent single-flight).
9. Similarity structurally cannot merge: `extra_candidate_bases` accepts no scores, never anchors attachment (seed-only hits go unmatched), and only surfaces ambiguity against member-backed candidates; seeded LM358 never absorbs LM3588 (tested).
10. mypy --strict + ruff clean; full suite 734 passed / 3 pre-existing skips.

## Delegated-judgment decisions (small/local, per CLAUDE.md §10)

- **Group-of-one policy**: a lone plausible MPN is a single-modality CanonicalPart;
  `unmatched` strictly means "no extractable identity".
- **Groups seed only from part_number observations** (+ caller-seeded bases); symbols/
  datasheets corroborate. A lone specific symbol does not create identity (conservative
  reading of "no derivable MPN → unmatched").
- **Entity-scoped corroboration**: symbol/datasheet observations corroborate the group
  their own entity's part number is in; naming a different known part → AMBIGUOUS.
- Escalation scope = part_number observations with unknown-format (family-less) bases
  only; garbage never reaches the metered call.
- Canonical `part_number` = the normalized base (uppercased); `manufacturer`/
  `datasheet_ref` populate unanimous-or-None.
- Overall confidence = best modality score + corroboration bonus − summed conflict
  penalties (compounding, capped).
- MPN plausibility gate (charset `[A-Z0-9./+_-]`, ≥4 chars, letter+digit, placeholder/
  value-pattern denylists in config) — this is also the injection firewall.

## Phase 4 verification (multi-agent review, adversarially verified)

A 29-agent review workflow (code, security §7, spec-compliance, Python, and an
electronics-domain lens; every non-LOW finding challenged by two adversarial refuters)
produced 14 findings; all confirmed ones were fixed and regression-tested:

- **CRITICAL (domain)**: grade `B` on LM stems falsely merged LM358 with TI's LM358B
  next-generation die → family split (ti_linear/ti_jfet) + eval cases C18/M14 pin it.
- **HIGH (spec)**: an LLM proposal could re-home an adjudicated-distinct identity
  (MPU-6050 → MPU6050 under a one-sided echo/failure) → escalation redesigned to
  evidence-only (see deviation below) + corpus-wide adversarial-escalation eval test.
- **HIGH (python)**: sibling ModalityMatches aliased one mutable `conflict` dict →
  per-match copies + aliasing regression test.
- **HIGH (security)**: memo check-then-act race double-billed concurrent escalations →
  single-flight lock + gather test.
- MEDIUMs: unbounded generic-symbol regex input (length-gated), escalation failures
  logged at DEBUG (→ WARNING), conflict penalties didn't compound (→ summed), ambiguity
  notes misattributed entity-side conflicts to the symbol/datasheet string (→ honest
  two-part notes), sort-key ties broke order-invariance (→ tie-breakers + tie test),
  seeds could anchor symbol-only MATCHED merges (→ seeds never anchor attachment) and
  mint dangling `candidate_canonical_ids` (→ candidates restricted to member-backed
  bases), missing B-suffix eval case (→ added), `cad_model` hints silently dropped by
  the adapter (→ mapped, lands in `unmatched`).

## Deviations & flags for humans

- **LLM escalation is EVIDENCE-ONLY (deviation from the ticket's Part E sketch —
  REVIEW REQUESTED)**: the ticket described a capped attach ("capped below MATCHED, so
  it can corroborate but never decide"). Phase 4 review proved even a LOW_CONFIDENCE
  attach lets a hallucinated/echoed "same part" (or a one-sided gateway failure) merge
  human-adjudicated-distinct identities (MPU-6050/MPU6050, AMS1117-3.3/-5.0) — a false
  merge by the eval's own accounting. Implemented instead: a proposal is recorded on
  the observation's own match as `{"llm_proposed_base": …, "llm_derived": true}` and
  never changes any bucket. Strictly more conservative than the spec text, aligned with
  ADR-012 (proposals go to human confirmation) and the governing principle. The
  `llm.confidence_cap < matched` config rail is kept (load-validated) for any future
  consumer of the evidence. If you want the capped-attach behavior back, it is a
  deliberate label + code decision to revisit together.
- **Mock behavior deviations (mock itself untouched)**: the matcher will not reproduce
  the mock's AMS1117 single-part grouping, its `L7805CV → LM7805 family` evidence note,
  or its generic-symbol-as-ambiguous depiction — all per the adjudicated decisions/spec-
  literal readings above. If any of these should become behavior, it's a label + config
  change.
- **Stale map**: root CLAUDE.md §3 places the matcher in `reasoning/fingerprint/`
  (empty `.gitkeep`); W0-06 and this implementation live in
  `packages/api/src/solus_api/fingerprint/`. Human doc fix suggested.
- **uuid5 is a new pattern** in the repo (everything else is uuid7/uuid4) — mandated by
  the ticket; suggest a short ADR note so FP-02's graph write reconciles it with
  ADR-027's "UUIDv7 where practical" (canonical_id is a matcher output key, not a PK).
- **No data-collection events emitted**: fingerprint confirm/reject events (ADR-011) are
  UI-flow territory; a pure library run has no user interaction to log. Lands with
  FP-02+/UI.
- `docs/api/API.md` is referenced by the authority hierarchy but absent (pre-existing
  gap; FP-01 needed no route so it was not blocking).
- No architecture diagram/wireflow exists for fingerprinting — this report + the plan
  file stand in; suggest adding the matcher to the architecture docs when FP-02 lands.

## Test coverage summary

186 fingerprint-scope tests (38 normalize, 39 matcher, 22 escalation, 11 fixture-
integrity, 54 eval incl. the 32-case corpus parametrization and the adversarial-
escalation red-team pass, plus the 22 untouched W0-06 contract tests), all green; full
`packages/api` suite 734 passed / 3 pre-existing skips. All fingerprint logic is
DB-free; escalation tested against a stubbed gateway (no network, no billing).
