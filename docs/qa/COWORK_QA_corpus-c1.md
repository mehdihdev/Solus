# Cowork QA — CORPUS C1: licensing policy classification drill (SOLUSDEV-241)

This ticket ships documents, not software. The "user" is a corpus reviewer, and the "flow" is
classifying a candidate source using nothing but `docs/corpus/LICENSING.md`. This file is the
test plan for that.

## Required setup

- A checkout of the branch. Open **only** `docs/corpus/LICENSING.md`. Do not open `SCOPE.md`,
  `docs/schemas/corpus-chunk.md`, the completion report, or the ticket text until Part C.
- No running services are needed. No accounts are needed.
- The tester should not have read the implementation session. If you have, hand Part B to
  someone who has not.

## Part A — Structural checks (pass/fail)

- [ ] A1. The three outcomes (SHIP, SUMMARISE, EXCLUDE) are each defined in §1 with what may
      ship, in terms a non-lawyer can apply.
- [ ] A2. §2 gives an ordered procedure whose first question is customer derivation and whose
      last step defaults to EXCLUDE.
- [ ] A3. Every source class in the §3 table has a matching §4 subsection with the same outcome.
- [ ] A4. The vendor terms register (§7) is empty and the text says nothing ships verbatim from
      a vendor until it has a row.
- [ ] A5. §8 contains at least 25 worked classifications, each naming the step or subsection that
      decided it.

## Part B — Blind classification drill

For each candidate below, write down the outcome (SHIP / SUMMARISE / EXCLUDE) and the §2 step or
§4 subsection that decided it **before** looking at §8 or the answer key. Then compare. A row
passes if your outcome matches; a mismatch in the cited step but not the outcome is a note, not a
failure.

| #   | Candidate                                                                                     | Your outcome | Your reason | Pass |
| --- | --------------------------------------------------------------------------------------------- | ------------ | ----------- | ---- |
| B1  | A NASA report whose title page says "Work of the US Government, public use permitted"         |              |             | [ ]  |
| B2  | A NASA-hosted report with "© 2019 Contractor Corp" on the title page                         |              |             | [ ]  |
| B3  | An Analog Devices application note downloaded from analog.com                                 |              |             | [ ]  |
| B4  | A LibreTexts page whose footer shows CC BY-NC-SA 4.0                                          |              |             | [ ]  |
| B5  | A LibreTexts page whose footer shows CC BY 4.0                                                |              |             | [ ]  |
| B6  | The Art of Electronics, chapter on op-amp limitations                                         |              |             | [ ]  |
| B7  | An ASME Y14.5 clause on position tolerance, from a PDF the reviewer's employer licensed       |              |             | [ ]  |
| B8  | The same clause, quoted in a forum post                                                       |              |             | [ ]  |
| B9  | A USB-IF specification, free download after accepting terms                                   |              |             | [ ]  |
| B10 | An STM32 datasheet, one thermal-resistance value, cited to the parameter table                |              |             | [ ]  |
| B11 | The whole electrical-characteristics table from that datasheet                                |              |             | [ ]  |
| B12 | MuJoCo documentation, if the docs directory carries an Apache-2.0 LICENSE (verify)            |              |             | [ ]  |
| B13 | A KiCad documentation page under GPLv3                                                        |              |             | [ ]  |
| B14 | A Reddit thread on servo selection with excellent, correct advice                             |              |             | [ ]  |
| B15 | A CC BY 4.0 arXiv paper on sensor fusion                                                      |              |             | [ ]  |
| B16 | An arXiv paper under arXiv's non-exclusive licence                                            |              |             | [ ]  |
| B17 | A Springer journal article behind a paywall                                                   |              |             | [ ]  |
| B18 | A customer's wiring diagram with every label removed, "just to show the pattern"              |              |             | [ ]  |
| B19 | A paragraph an LLM wrote, sources listed, every claim traced by a reviewer, no verbatim match |              |             | [ ]  |
| B20 | A paragraph an LLM wrote, one claim the reviewer could not source                             |              |             | [ ]  |
| B21 | A GitHub README with no LICENSE file, written by a well-known robotics lab                    |              |             | [ ]  |
| B22 | A Solus engineer's original write-up of PID anti-windup, no sources open while writing        |              |             | [ ]  |
| B23 | A figure from a CC BY textbook whose caption reads "Figure © Elsevier, used with permission" |              |             | [ ]  |
| B24 | Wikipedia's article on the ISO fit system                                                     |              |             | [ ]  |

Answer key (do not read until the table is filled):

B1 SHIP §4.2 · B2 SUMMARISE §4.2 · B3 SUMMARISE §4.5 · B4 SUMMARISE §4.4 · B5 SHIP §4.3 ·
B6 EXCLUDE §4.10 · B7 SUMMARISE §4.7 · B8 EXCLUDE §4.7/§4.9 · B9 SUMMARISE §4.7 ·
B10 SUMMARISE (facts_extracted) §4.6 · B11 EXCLUDE as a table, §1 and §4.14 ·
B12 SHIP §4.8 only after the licence is verified on the file · B13 SUMMARISE §4.8 ·
B14 EXCLUDE §4.9 · B15 SHIP §4.11 · B16 SUMMARISE §4.11 · B17 EXCLUDE §4.11 ·
B18 EXCLUDE §2 step 1 · B19 SHIP §4.1 with `llm_assisted` · B20 SHIP after the claim is removed,
§4.12 · B21 EXCLUDE §2 step 2 · B22 SHIP §4.1, must still list what it was checked against ·
B23 the text SHIPs, the figure is EXCLUDE, §4.14 · B24 EXCLUDE §4.9.

- [ ] B-overall. At least 22 of 24 outcomes match. If fewer, record which rows and why the policy
      text led you elsewhere; that is a defect in the policy, not in the tester.

## Part C — Consistency across the three documents

Now open `docs/corpus/SCOPE.md` and `docs/schemas/corpus-chunk.md`.

- [ ] C1. Every `topic` value in `SCOPE.md` §4 tables is a lowercase identifier usable as an enum
      member, and `corpus-chunk.md` §4 says `Topic` is exactly that set.
- [ ] C2. Every applicability key in `SCOPE.md` §6 is referenced by `corpus-chunk.md` §2
      (`applicability`) and §4 (`ApplicabilityKey`).
- [ ] C3. Every `source_class` value in `corpus-chunk.md` §4 corresponds to a SHIP or SUMMARISE
      class in `LICENSING.md` §3, and no EXCLUDE class (community, textbooks, customer, model) has
      a `source_class` value.
- [ ] C4. Every non-SPDX vocabulary value (`public-domain-us-gov`, `vendor-terms`,
      `datasheet-terms`, `standard-summary`, `solus-proprietary`, `arxiv-nonexclusive`, `unknown`)
      appears in both `LICENSING.md` §5 and `corpus-chunk.md` §4. SPDX identifiers are examples
      in the policy and a closed list in the schema; every example in the policy is in the list.
- [ ] C5. Rule 1's table in `corpus-chunk.md` §5 reproduces the §3 outcome of `LICENSING.md` for
      each class: verbatim is only allowed where the policy says SHIP.
- [ ] C6. The §7 example in `corpus-chunk.md` is `draft`, and the text explains which rule would
      refuse to activate it.
- [ ] C7. Every `§` cross-reference between the three files points at a heading that exists.

## Part D — Edge cases for the policy itself

- [ ] D1. Find a real candidate source not covered by any §8 row. Classify it. If §2 does not
      resolve it in five steps, record it as a policy gap.
- [ ] D2. Try to construct a chunk that ships an IPC table under `facts_extracted`. Confirm both
      `LICENSING.md` §4.7 and `corpus-chunk.md` §5 rule 3 refuse it.
- [ ] D3. Try to record a community source as provenance. Confirm there is no `source_class` for
      it and that `further_reading` is the only place it can appear.
- [ ] D4. Try to name a customer anywhere on a chunk. Confirm `corpus-chunk.md` §3 lists every
      field that would have allowed it as non-existent.

## Sign-off

- [ ] Parts A–D complete. Defects recorded below with the section that caused them.

| Defect | Section | Note |
| ------ | ------- | ---- |
|        |         |      |
