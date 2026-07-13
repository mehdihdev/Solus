# COWORK QA — FP-Fixes + FP-03 Vision Scaffold (SOLUSDEV-59)

Library-level QA (no UI; vision is flag-off scaffold). Setup: repo on
`SOLUSDEV-59-Multimodal-Fingerprint`, `uv sync`. **No API keys needed anywhere.**
DB (`make db-up`) needed only for Flow 4.

## Flow 1 — Hard gate + full suite

1. `uv run pytest packages/api/tests/test_fingerprint_eval.py -q -s`
   - [ ] All pass; the printed block shows `cases=35 (matched=14 confusable=21)` and
         `FALSE MERGES: 0`.
2. `uv run pytest packages/api/tests -q`
   - [ ] Full suite green (804+).

## Flow 2 — Separator policy + new traps (REPL from `packages/api/`)

```python
from solus_api.fingerprint import load_fingerprint_config, normalize_mpn
cfg = load_fingerprint_config()
b = lambda s: (normalize_mpn(s, cfg) or None) and normalize_mpn(s, cfg).base
```

- [ ] `b("MPU-6050") == b("MPU6050") == "MPU6050"` (one IMU, both spellings).
- [ ] `b("AMS1117-3.3") == "AMS11173.3"`, `b("AMS1117-5.0") == "AMS11175.0"`,
      `b("AMS1117") == "AMS1117"` — three distinct identities.
- [ ] `normalize_mpn("10-K", cfg) is None` (re-gate: de-hyphenated value dies).
- [ ] Nordic: `b("NRF52832-QFAA") == "NRF52832QFAA" != b("NRF52832-QFAB")`;
      `b("NRF52832") != b("NRF52840")`.
- [ ] STM32 positional: `b("STM32F103C8T6") == "STM32F103C8"`;
      `b("STM32F103RCT6") == "STM32F103RC"`; unknown tails kept whole:
      `b("STM32F103C8T9") == "STM32F103C8T9"`; `b("STM32F103CB") == "STM32F103CB"`.
- [ ] B-split still holds: `b("TL072B") == "TL072"` but `b("LM358B") == "LM358B"`.
- [ ] Collision guard (Phase 4 CRITICAL fix): de-hyphenation never mints a
      taxonomy-known identity — `b("LM358-8") == "LM358-8" != b("LM3588")`;
      `b("ATMEGA328-P") == "ATMEGA328-P" != b("ATMEGA328P")`.

## Flow 3 — Vision containment (mocked; no keys)

1. `uv run pytest packages/api/tests/test_visual.py packages/api/tests/test_matcher.py -q`
   - [ ] All pass — includes: photo corroborates at LOW_CONFIDENCE only, photo never
         mints a part, multiple readings → ONE ambiguity (never a winner), photo
         never anchors to retrieval seeds, keyless `identify_from_image` returns []
         through the REAL gateway with an empty SecretStore, and ALL ArtifactRef
         inputs (traversal / local / s3 uris) are inert — never read, never shipped.
2. `uv run pytest "packages/api/tests/test_fingerprint_eval.py::test_adversarial_photo_cannot_change_structured_buckets" -q`
   - [ ] Passes — an adversarial "LM358"-everywhere extractor cannot change any
         structured bucket on any of the 35 eval cases.
3. `grep -rn "fingerprint_vision_enabled" packages/api/src`
   - [ ] Flag exists, default False, zero library readers (caller-owned; the future
         trigger router wires it).

## Flow 4 — Vision → graph (DB): no assertion from a photo

- `uv run pytest "packages/api/tests/test_ingest.py::test_photo_evidence_never_sets_the_graph_fk" -q`
  - [ ] Passes: the photo-corroborated canonical carries the photo as
        `low_confidence` evidence in attrs; the photo's observation row has
        `canonical_part_id IS NULL` and no ownership stamp.

## Flow 5 — Gateway chokepoint intact

- [ ] `uv run pytest packages/api/tests/test_no_hardcoded_models.py packages/api/tests/test_providers.py packages/api/tests/test_gateway.py -q` — all pass
      (SDK imports only in providers.py; images-absent calls bit-identical;
      content shapes per provider tested as pure functions).
- [ ] `git diff a7e4068 -- packages/api/src/solus_api/fingerprint/contract.py packages/api/src/solus_api/fingerprint/mock_canonical_parts.json DECISIONS.md` → EMPTY
      (a7e4068 = FP-02's last commit; the whole FP-fixes+FP-03 diff never touched the
      frozen contract, the mock catalog, or DECISIONS.md).

## Human-step checklist (not QA failures)

- [ ] `temp-ADR-027-origin-fingerprint.md` pasted into DECISIONS.md by a human.
- [ ] H6 hook: already applied + verified in-session (migrations exemption at
      pre_write_recreation_guard.sh:16).
- [ ] `temp-PROPOSAL-gateway-embeddings.md` still awaits adjudication (FP-02).
- [ ] Real silkscreen photos for the manual vision demo await provider keys
      (two-liner in visual.py's docstring).
