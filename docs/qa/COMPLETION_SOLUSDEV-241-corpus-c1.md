# Completion report — CORPUS C1: scope, licensing policy, chunk schema (SOLUSDEV-241)

**Branch:** `SOLUSDEV-241-corpus-c1-scope-and-licensing` · **Status:** documents written; no code,
no product change, nothing to run. **Docs-only ticket by in-session decision** (Phase 1 gate,
2026-09-05).

## What was delivered

- `docs/corpus/SCOPE.md` — what the corpus is and is not; the five domains with 41 topics, each
  with the questions it must answer, a P0/P1/P2 priority, and its consumers (SOL, checkers,
  autocomplete, Live Bench); depth levels tied to SOL modes; explicit exclusions; the v1
  applicability key set that the `.solus/project.toml` preferences layer will select on;
  versioning rules.
- `docs/corpus/LICENSING.md` — the policy. Three outcomes (SHIP / SUMMARISE / EXCLUDE) with
  precise definitions, a five-step classification procedure, an outcome table for fourteen
  source classes, per-class detail, attribution and licence-recording rules, review and takedown
  accountability, an (empty) vendor terms register, and 29 worked classifications that serve as
  the acceptance test.
- `docs/schemas/corpus-chunk.md` — the per-chunk schema: fields with caps, the fields that must
  never exist (mirroring the tool-knowledge contract), closed enumerations, 16 numbered
  validation rules that encode the licensing policy as cross-field checks, prompt-assembly and
  retrieval rules, a worked example, and the corpus manifest.
- `docs/qa/COWORK_QA_corpus-c1.md` — a reviewer drill, since the deliverable's "user flow" is a
  reviewer classifying sources from the policy alone.

## Governing docs consulted

ADR-033 (global tenant-free tool knowledge — the containment precedent), ADR-034 and
`docs/architecture/solus-folder.md` (the `.solus` layers; custom instructions stay deferred),
ADR-016 (SOL modes), ADR-013 (autocomplete is the checker library), ADR-032 (tier-1 edits),
`docs/contracts/tool-knowledge.md`, `docs/api/toolkb.md`, `packages/api/src/solus_api/agent/prompt.py`
(data fencing), `docs/qa/COMPLETION_SOLUSDEV-205-tu02-kicad-docs-ingestion.md` (the GPL fixture
flag that motivates the copyleft-documentation rule).

**The standing rule to read `docs/design/SPEC.md` and `docs/design/screens/` could not be
applied: neither path exists in this repository.** If they live elsewhere, point me at them and
I will reconcile.

## Decisions made at the Phase 1 gate (human answers)

1. Vendor application notes and datasheets: **SUMMARISE and cite by default**, verbatim only
   after a per-vendor terms entry in the register (empty at v1). The ticket's "ship with
   attribution" conflated free access with a redistribution licence.
2. Open textbooks: **CC BY-SA and CC BY-NC both SUMMARISE**; copyright protects expression, not
   facts. Recorded in the policy as a considered posture, with every such chunk enumerable by
   `source_license` if the posture changes.
3. **C1 is docs only.** Types, fixtures, the illegal-construction proof, and the storage ADR are
   C2.

## Decisions made under delegated judgment

- **CC BY-ND folded into the SUMMARISE class** alongside SA and NC. The gate answer named SA and
  NC; ND was not asked. The reasoning is the same (a Solus-written statement of facts is not an
  adaptation), and the policy says so. Easy to move to EXCLUDE if you disagree — one table row and
  one rule-1 cell.
- **All-rights-reserved textbooks are EXCLUDE, not SUMMARISE**, even though the same
  "facts are not copyrightable" reasoning could be stretched to them. The distinction: open
  non-commercial licences anticipate reading and reuse of ideas; a "summary" of a Shigley chapter
  is where a reviewer is most likely to produce an adaptation without noticing. The ticket named
  textbooks as the legal edge, so the policy keeps them on the far side of it.
- **Community content is EXCLUDE on accuracy**, independent of licence, with an explicit note
  that an "expert-authored, individually reviewed" class would be a policy amendment.
- **No quotation allowance.** A short-quote rule invites an argument about length; matching
  prose fails, full stop.
- **US government works added as a first-class SHIP source** (MIL-STD/MIL-HDBK, NIST, FAA), with a
  per-document check because NASA's server also hosts copyrighted contractor reports.
- **Schema location:** `docs/schemas/` (tier-1) rather than `packages/contracts/` (tier-2), because
  no type ships yet. C2 promotes it to a contract with human approval.
- **Applicability keys** were chosen to be the facts a `.solus/project.toml` would naturally
  declare. The Layer-2 TOML contract does not exist yet; whichever lands second reconciles
  (`SCOPE.md` §8).
- **Standards get no `facts_extracted` derivation.** A "fact" from a standard is usually a
  requirement, which is the standard's expression.

## Deviations and flags for human review

1. **CLAUDE.md §3 repository map** now has an undocumented `docs/corpus/` directory. CLAUDE.md is
   tier-2, so I did not edit it. Suggested one-line addition under `docs/`:
   `│   ├── corpus/                ← engineering corpus scope + licensing policy (SOLUSDEV-241)`.
2. **No licence claim about any specific external source is asserted.** Every named publisher
   (OpenStax, ROS docs, MuJoCo, KiCad, Zephyr, vendor SDK repos) is marked verify-before-pinning.
   The policy is deliberately empty where the repo's own convention (`metadata-extraction.md`)
   would be: empty beats invented.
3. **Legal review.** This is an engineering-authored policy. Two positions in it are legal
   postures, not certainties, and are labelled as such: summarising SA/NC/ND sources (§4.4), and
   treating US-government public-domain status as sufficient in non-US jurisdictions (§4.2).
   Both are queryable by `source_license` so they can be reversed in one corpus version.
4. **C2 needs a new ADR**, not an ADR-033 amendment: it would be the first global table whose
   rows are long prose, which ADR-033's "typed columns only" rule was written to prevent. The
   schema's four containment properties (§1) are the proposed basis for that ADR.
5. The TU-02 GPLv3 fixture flag (SOLUSDEV-205, flag 1) is still open and is now cited by policy
   §4.8; resolving it is outside this ticket.

## Verification

- `prettier --check` passes on all four new files (H7 formatted them on write).
- Every `§` cross-reference between the three documents was checked against the actual heading
  list; all resolve.
- The acceptance criterion ("a reviewer can classify any candidate source from the policy
  alone") is exercised by the 29 worked rows in `LICENSING.md` §8 and by the drill in
  `COWORK_QA_corpus-c1.md`. It has not been exercised by a second human yet; that is the MR
  review.
- No tests: nothing executable changed. No product run: nothing runnable changed. Stated
  plainly per the standing rule.
