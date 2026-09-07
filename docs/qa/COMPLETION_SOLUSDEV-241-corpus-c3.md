# Completion report — CORPUS C3: the first corpus (SOLUSDEV-241)

**Branch:** `SOLUSDEV-244-home-h3-root-preferences` (shared) · **Corpus release:** 0.1.0 → **0.2.0**
· **Run for real:** yes (below).

## What was built

- **Sourced content, 19 chunks, every one fetched from its rights-holder host in this session,
  read in full, and summarised or fact-extracted in Solus's words** (LICENSING.md §4.5, §4.2,
  §4.6). No verbatim text from any SUMMARISE class; no reproduced table.
  - Vendor application notes (`vendor_documentation` / `vendor-terms` / summary or facts), 10:
    TI SLUA366 (×2: the etch-current facts and the sizing procedure), SLUP419 (creepage,
    clearance, the 48 V energy-source class), SLUAAR5 (IEC 60664 method), SNVA054 / AN-1229
    (buck layout), SLYT499 (AGND/DGND, star ground), SLVAF66 (×2: bulk caps and the 48 V ceramic
    rule; coast vs brake and Kelvin sensing); Microchip AN2587 (EMC layout checklist) and DC
    Motor Control Tips (current sensing).
  - Public-domain NASA (`us_government_work` / `public-domain-us-gov`), 6: RP-1228 Fastener
    Design Manual (torque coefficient, locking methods and lockwashers, threaded inserts),
    NASA-STD-5020A w/Change 1 (preload uncertainty by installation method, locking rules, thread
    engagement), NASA Passive Thermal Control Engineering Guidebook 5.1 (limits and margins;
    contact conductance and interface materials). Each record's public-use line was verified on
    NTRS / nasa.gov.
  - Datasheets (`datasheet` / `datasheet-terms` / facts_extracted with locators), 3: Espressif
    ESP32 v5.3, Infineon BTS7960 Rev. 1.1, Feetech STS3215 specification A/0 (7.4 V edition).
- **Principles (item 1):** the 102 Solus-authored chunks from C2 remain the principles layer; C3
  adds no unsourced prose. Human review posture unchanged per the gate: reviewer `mhussain`,
  signed at the MR.
- **Licence accounting:** `corpus/licenses.py` + `python -m solus_api.corpus licenses` (report by
  class × licence × publisher × derivation, with findings; non-zero exit on any finding) and
  `tests/corpus/test_corpus_licenses.py` (every active chunk licensed; every sourced chunk has an
  `https` rights-holder URL, a locator, and an attribution; the C3 classes are present).
- **Acceptance tests** `tests/corpus/test_corpus_c3_acceptance.py`: the trace-width question
  returns the SLUA366 chunk with its attribution and the 3.2 A / 0.050 in facts; the 48 V question
  returns attributed TI chunks stating the 60 V boundary; served sourced chunks always carry
  attribution.
- **Eval extended** by 37 questions (`tests/fixtures/corpus_eval/sourced.json`, 126 total).
  Gaps were closed by content and routing, never by thresholds: two chunk wordings sharpened,
  router lexicon extended (locknut/threadlocker/rotates, conductance/contact/TIM, STS3215/SO-101).
- Host allowlist: Feetech's two rights-holder domains added.

## Results

| Metric (keyless full-text path, as CI runs) | Before C3    | After C3      | Gate   |
| ------------------------------------------- | ------------ | ------------- | ------ |
| hit@5                                       | 1.000 (n=89) | 1.000 (n=126) | ≥ 0.90 |
| answer support                              | 0.989        | 0.992         | ≥ 0.85 |
| domain purity                               | 1.000        | 1.000         | 1.00   |
| licence findings                            | 0            | 0             | 0      |

Remaining miss: `mechanical-gdt-01` (a C2 question whose second gold chunk is not in the top 5;
support fails on "bonus"). Pre-existing, left for the GD&T content pass.

`tests/corpus` + `test_context.py`: all passing; ruff and mypy clean; `manifest --check` current.

## Run for real

Local API with the dev database ingested to 0.2.0 (`inserted 19, unchanged 102, withdrawn 0`):

- `GET /corpus/manifest` → 0.2.0, 121 chunks. Search for the trace-width question returns the
  SLUA366 chunk in the top 3; the chunk view shows `source.class vendor_documentation`, the
  ti.com URL, licence `vendor-terms`, and the attribution string.
- **Live SOL turn** "What trace width do I need for 3 A on 1 oz copper?" → answer opens with
  "about 1.2 mm (just under 0.050 in) … from TI's layout note SLUA366 … ~3.2 A" and cites
  `[corpus:electrical/trace_width_current/ti-slua366-etch-current-for-1oz-copper]` first.
- **Live SOL turn** "What clearance do I need for a 48 V bus on the motor board?" → cites the
  SLUP419 and SLUAAR5 chunks, distinguishes creepage from clearance, and states that the
  millimetre value comes from the standard's table, which the corpus does not carry. That is the
  policy working as designed (LICENSING.md §4.7).

## Decisions under delegated judgment

- **Item (4), R4's library:** R4 is in progress elsewhere and has no seed list yet. Datasheet chunks
  were written for the parts the R4 ticket names and that could be fetched from a rights-holder:
  ESP32, BTS7960, STS3215 (the SO-101 actuator). The MPU-6050 datasheet is blocked by TDK's site
  (HTTP 403 / navigation page) from this environment and was **not** written. When R4's dozen
  lands, each part gets a `datasheet` chunk by the same recipe (`docs/corpus/AUTHORING.md` §8).
- **Values from a SUMMARISE source:** individual facts with a locator only (e.g. "0.050 in ≈
  3.2 A at 10 °C rise"), never the table; the trace chunk says so in its own text.
- The one thermal source is a spacecraft guidebook; only the sections that transfer (margin
  ladder, contact conductance, interface materials) were used, with their project provenance.
- Corpus version bumped to 0.2.0 (new chunks, no withdrawals).

## Not done, and why

- **Analog Devices and ST notes:** every fetch route from this environment timed out (analog.com
  and st.com PDFs and HTML; the shell has no outbound network). Nothing was written from memory.
  Empty beats invented. Adding them is a content-only change when a session has access.
- **NASA tolerancing:** the NTRS "Statistical Tolerance and Clearance Analysis for Assembly"
  record carries an "Other" copyright (JPL) and no PDF → EXCLUDE. Tolerancing stays Solus-authored
  (C2) plus the thread-engagement guidance from NASA-STD-5020A.
- **MPU-6050** (above).
- The model-judged `-m live` eval was not run.

## Flags for review

1. Every sourced chunk is `llm_assisted` and carries the exact locator; the MR review is the
   LICENSING.md §6 signature and the §4.1/§4.5 spot-check. Source texts are extracted in the
   session scratchpad and can be re-fetched from the recorded URLs.
2. NASA-STD-5020A percentages (25 % / 35 %) and the RP-1228 K values are stated with their
   conditions; the guidebook's contact-conductance ranges are flown-project correlations, not
   handbook values, and the chunk says so.
3. `hosts.py` now admits `feetechrc.com` / `feetech.cn` (rights-holder for the SO-101 servo).
4. No `.env` values required. `docs/design/SPEC.md` still does not exist (noted once).

## Validation gate (H10) at handoff

- Every item the gate attributed to corpus files was fixed in `5f53e7a` (ruff/mypy clean on
  `migrations/env.py`, the corpus migration, and the contract test).
- A full API run on a private test database (`SOLUS_TEST_DATABASE_URL=…/solus_test_corpus65`)
  completed in 22 min: **3456 passed, 1 failed** — the failure was the ST5 session's new
  `sourcing.derive_torque` tool registering into the reference registry
  (`test_registry_lists_only_the_reference_tool`), which that session fixed in `27f8fb3`.
- The gate's own full-suite run keeps hitting the 300 s per-test timeout inside conftest's
  per-test `TRUNCATE`. `pg_stat_activity` showed no lock waits; the only active session was
  another session's suite waiting on `DataFileImmediateSync`. Three concurrent full suites on the
  single local Postgres (which lacks CI's `fsync=off`) make the TRUNCATE the bottleneck. This is
  contention between sessions sharing one checkout, not a code defect; flagged per CLAUDE.md §5
  for the human rather than bypassed.
- The gate's eslint errors are in the HOME H3/H4 session's `LiveHome` / `HomeTeamModals`
  (complexity), reported to that session; no corpus commit touches the desktop.
