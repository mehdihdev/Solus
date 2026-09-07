# Cowork QA — CORPUS C3: the first corpus (SOLUSDEV-241)

Setup as in `COWORK_QA_corpus-c2.md` (API, dev database migrated, `make corpus-ingest`, a
verified user with a project, a model key for SOL flows). Base URL `$API`, bearer JWT on every
request.

## Flow 1 — the 0.2.0 release is applied and fully licensed

1. `GET $API/api/v1/corpus/manifest` → `corpus_version` `0.2.0`, `chunk_count` `121`.
2. `cd packages/api && uv run python -m solus_api.corpus licenses` → a table with four source
   classes (`solus_authored`, `vendor_documentation`, `us_government_work`, `datasheet`), four
   licences, publishers Texas Instruments, Microchip Technology, NASA, Espressif Systems, Infineon
   Technologies, Shenzhen Feetech RC Model Co., Ltd., and the last line `Findings: none`; exit 0.
3. Edit any sourced chunk to set `source_license = "unknown"`, run `licenses` again → the chunk
   is named in Findings and the command exits 1. Revert.

- [ ] 1 · [ ] 2 · [ ] 3

## Flow 2 — "what trace width for 3 A on 1 oz copper" cites an app note

1. `GET $API/api/v1/corpus/search?q=what trace width for 3 A on 1 oz copper&limit=5` → the list
   includes `corpus:electrical/trace_width_current/ti-slua366-etch-current-for-1oz-copper`.
2. `GET $API/api/v1/corpus/chunks/corpus:electrical/trace_width_current/ti-slua366-etch-current-for-1oz-copper`
   → `source.class` `vendor_documentation`, `source.publisher` `Texas Instruments`, `source.url`
   on `ti.com`, `source.license` `vendor-terms`, non-empty `source.attribution` naming SLUA366;
   `body` states 0.050 in ≈ 3.2 A at a 10 °C rise on 1 oz outer copper and does NOT contain a
   multi-row table.
3. SOL (Guide mode): ask the question. Expected: the answer names TI SLUA366, gives about 1.2 mm
   / just under 0.050 in with the 10 °C-rise condition, and its `citations` include the SLUA366
   chunk id; the `context_used` corpus sections include it.
4. SOL (Expert mode): same question → terse answer, same citation id.

- [ ] 1 · [ ] 2 · [ ] 3 · [ ] 4

## Flow 3 — "clearance for a 48 V bus" answers with a source

1. Search `q=clearance for a 48 V bus` → top hits include
   `…/clearance_creepage/ti-slup419-creepage-clearance-and-a-48v-bus`; each sourced hit's chunk
   view has a non-null `source.url`.
2. SOL: ask "What clearance do I need for a 48 V bus on the motor board?" Expected: the answer
   distinguishes creepage from clearance, places 48 V below the 60 V ES1/SELV boundary, describes
   the IEC 60664 inputs (overvoltage category, pollution degree, material group, working voltage),
   cites the SLUP419 and/or SLUAAR5 chunks, and says the millimetre value comes from the standard's
   table rather than inventing one.

- [ ] 1 · [ ] 2

## Flow 4 — public-domain and datasheet provenance renders

1. Chunk view of `corpus:mechanical/fasteners/nasa-rp-1228-torque-coefficient-and-why-torque-is-a-poor-proxy`
   → `source.class` `us_government_work`, `source.license` `public-domain-us-gov`, URL on
   `ntrs.nasa.gov`, attribution ending "(work of the US Government, public use permitted)".
2. Chunk view of `corpus:robotics/actuator_selection/feetech-sts3215-specification-7v4-edition`
   → `source.class` `datasheet`, publisher Feetech, URL on `feetechrc.com`, locator naming edition
   A/0 and the section numbers.
3. SOL: "Is K = 0.2 a safe assumption for my steel bolts?" → cites the RP-1228 chunk, says 0.15 is
   more realistic for steel on steel, and that torque tables must match the friction condition.
4. SOL: "What is the stall current of the STS3215 on the SO-101?" → 2.5 A at 7.4 V (2 A at 6 V),
   rated 650 mA, cites the Feetech chunk.

- [ ] 1 · [ ] 2 · [ ] 3 · [ ] 4

## Flow 5 — the eval and the bar

1. `make corpus-eval` → per-domain hit@5 and support tables, overall hit@5 ≥ 0.90, support ≥
   0.85, purity 1.000, `n=126`; the only listed miss is `mechanical-gdt-01`.
2. Open `packages/api/tests/corpus/test_corpus_eval.py` and confirm the thresholds are still
   0.90 / 1.00 / 0.85 (they were not lowered).

- [ ] 1 · [ ] 2

## Edge cases

- A question with no engineering words ("how was your weekend") returns corpus sections from no
  single domain and SOL invents no citation.
- `search?q=MPU-6050 I2C address` → returns the Solus-authored bus-addressing chunk, NOT a
  datasheet chunk (the MPU-6050 datasheet is deliberately absent; see completion report).
- Delete one sourced content file, bump `corpus.toml` to 0.2.1, regenerate the manifest, ingest →
  `withdrawn 1`, and the chunk view shows `status withdrawn` with an empty body but its `source`
  block intact (auditability of takedowns).

- [ ] edge cases
