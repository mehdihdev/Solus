# Corpus Chunk — Schema (CORPUS C1)

**Ticket:** SOLUSDEV-241 (CORPUS C1, implemented in CORPUS C2) · **Status:** schema document,
tier-1 (ADR-032). **Implemented by** `packages/api/src/solus_api/corpus/contract.py` (the
Pydantic type and all rules below, one named test per rule in
`packages/api/tests/corpus/test_corpus_contract.py`), stored per ADR-036 in `corpus_chunk`
(`corpus/schema.py`, migration `a9c0d1e2f3b4`). No TypeScript twin exists yet: no desktop code
constructs a chunk; the desktop reads the served view in `docs/api/corpus.md`.
**Governs:** every chunk of the engineering corpus (`docs/corpus/SCOPE.md`), classified under
`docs/corpus/LICENSING.md`.
**Precedents inherited:** ADR-033 (global content-bearing store: no tenant columns, typed columns
only, no runtime write path, lexical-first retrieval, embedding nullable and unpopulated until
`embed()` exists); `docs/contracts/tool-knowledge.md` (closed enums, a provenance vocabulary with
no customer option, nothing to point at customer-owned things, a compile-time illegal-construction
proof); `packages/api/src/solus_api/agent/prompt.py` (every non-instruction string is fenced data).

---

## 1. What is different from tool knowledge, and what is not

The tool-knowledge store bounds its prose to 400 characters and rejects dimensioned values and
paths, because its prose is a label, not the content. **A corpus chunk's body is the content.** It
is paragraphs of engineering prose that legitimately contain `0.5 mm`, `24 AWG`, `3.3 V`, and
formulae. The tool-knowledge prose patterns therefore **must not** be reused as this schema's
filter — they would reject every valid chunk.

Containment for the corpus comes from four things instead, and C2 must implement all four:

1. **No field can reference anything customer-owned** (§3). No project, team, user, entity,
   document, file, or conversation identifier exists on the type.
2. **Every categorical field is a closed enum** (§4), and `source_class` has no customer option
   and no "model" option.
3. **The only write path is the curated ingestion job** reading from a Solus-committed source
   manifest. No request handler, sync, tool call, or anything holding a `SyncContext` constructs
   a chunk. This is ADR-033 rule 3 verbatim.
4. **Cross-field validation encodes the licensing policy** (§5), so a chunk whose derivation the
   policy forbids for its source class does not validate.

What the schema cannot do, stated so nobody over-trusts it: it cannot tell whether a paragraph of
prose was copied from a textbook or describes a customer's robot in general terms. That is the
reviewer's job (`LICENSING.md` §6), which is why `reviewer` is a required field.

## 2. Fields

Ids and slugs are lowercase `[a-z0-9_-]`. Strings are NFKC-normalised on ingest. Caps are
maxima; C2 may set them lower.

| Field              | Type                                                        | Req               | Cap        | Meaning                                                                                                                                         |
| ------------------ | ----------------------------------------------------------- | ----------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`               | string, `corpus:<domain>/<topic>/<slug>`                    | yes               | 120        | Stable for the chunk's life; survives withdrawal                                                                                                |
| `domain`           | enum `Domain`                                               | yes               |            | `mechanical` `electrical` `software` `systems` `robotics`                                                                                       |
| `topic`            | enum `Topic`                                                | yes               |            | One of the `topic` values in `SCOPE.md` §4, scoped to `domain`                                                                                  |
| `title`            | string                                                      | yes               | 120        | Human title, Solus-written                                                                                                                      |
| `body`             | string, Markdown subset                                     | yes               | 6000       | The chunk. Headings, lists, inline code, tables written by Solus, LaTeX-free formulae. No images, no raw HTML, no links except to `source_url`. |
| `kind`             | enum `Kind`                                                 | yes               |            | `principle` `procedure` `rule_of_thumb` `reference_value` `pitfall` `glossary`                                                                  |
| `audience`         | enum `Audience`                                             | yes               |            | `fundamentals` `reference` (`SCOPE.md` §3)                                                                                                      |
| `applicability`    | list of `{key: enum ApplicabilityKey, value: enum per key}` | yes, may be empty | 16 entries | `SCOPE.md` §6 key set. Empty list means "applies regardless"                                                                                    |
| `derivation`       | enum `Derivation`                                           | yes               |            | `verbatim` `summary` `facts_extracted` `solus_original`                                                                                         |
| `provenance`       | object `Provenance` (§2.1)                                  | yes               |            | Where it came from and under what terms                                                                                                         |
| `further_reading`  | list of `Citation` (§2.2)                                   | yes, may be empty | 8          | Bibliographic pointers only; the only place an EXCLUDE-class work may be named                                                                  |
| `license`          | enum, single value `solus-proprietary`                      | yes               |            | The chunk's outgoing licence. Fixed at v1; an enum so a second value is a policy change, not a string edit                                      |
| `confidence`       | number `0.0..1.0`                                           | yes               |            | Reviewer's confidence the chunk is correct and generally applicable                                                                             |
| `confidence_basis` | enum `ConfidenceBasis`                                      | yes               |            | `standard_derived` `vendor_stated` `government_published` `peer_reviewed` `solus_measured` `rule_of_thumb` `consensus`                          |
| `drafting`         | enum `Drafting`                                             | yes               |            | `human` `llm_assisted`                                                                                                                          |
| `reviewer`         | string, Solus staff id                                      | yes               | 64         | Never a customer id, never a model name (§5 rule 8)                                                                                             |
| `reviewed_at`      | date (ISO 8601, UTC)                                        | yes               |            |                                                                                                                                                 |
| `status`           | enum `Status`                                               | yes               |            | `draft` `active` `superseded` `withdrawn`                                                                                                       |
| `supersedes`       | chunk id or null                                            | yes               |            | Set when this chunk replaces another                                                                                                            |
| `related`          | list of chunk ids                                           | yes, may be empty | 12         | Cross-links within the corpus only                                                                                                              |
| `corpus_version`   | semver                                                      | yes               |            | Version the chunk was introduced in                                                                                                             |
| `revised_in`       | semver                                                      | yes               |            | Version of the last change to any field; equals `corpus_version` when unchanged                                                                 |
| `content_hash`     | string, `sha256:<hex>`                                      | yes               |            | Over the canonical JSON of every field except `content_hash`, `embedding`                                                                       |
| `embedding`        | vector or null                                              | yes               |            | Null in the authored document; populated at ingest by `embed()` (SYS-02, ADR-036) and stored in the table only; never part of the hash          |

### 2.1 `Provenance`

| Field              | Type                      | Req               | Cap | Meaning                                                                |
| ------------------ | ------------------------- | ----------------- | --- | ---------------------------------------------------------------------- |
| `source_class`     | enum `SourceClass` (§4)   | yes               |     | The `LICENSING.md` §4 class                                            |
| `source_title`     | string                    | yes               | 200 |                                                                        |
| `source_publisher` | string                    | yes               | 120 | Rights-holder or publisher name                                        |
| `source_url`       | `https` URL or null       | yes               | 400 | Canonical, rights-holder-hosted; null only for `solus_authored`        |
| `source_locator`   | string                    | yes, may be empty | 200 | Revision, page, clause, table, section, or commit                      |
| `source_license`   | enum `SourceLicense` (§4) | yes               |     | SPDX id or corpus vocabulary value                                     |
| `accessed_at`      | date                      | yes               |     |                                                                        |
| `attribution`      | string                    | yes, may be empty | 600 | Rendered attribution when the licence requires one (`LICENSING.md` §5) |
| `checked_against`  | list of `Citation`        | yes, may be empty | 8   | For `solus_authored`: what the verbatim check was run against          |

### 2.2 `Citation`

| Field        | Type                | Req               | Cap                                                   |
| ------------ | ------------------- | ----------------- | ----------------------------------------------------- |
| `title`      | string              | yes               | 200                                                   |
| `author`     | string              | yes, may be empty | 120                                                   |
| `identifier` | string              | yes, may be empty | 120 (ISBN, DOI, document number, arXiv id)            |
| `url`        | `https` URL or null | yes               | 400 (rights-holder-hosted only; null for print works) |

## 3. Fields that do not exist, and never will without a human decision

Mirroring `docs/contracts/tool-knowledge.md` §1–2. C2's illegal-construction proof asserts each of
these fails to compile.

- No `project_id`, `team_id`, `user_id`, `entity_id`, `source_id` (the connector kind),
  `document_id`, `element_id`, `conversation_id`, `file_path`, or any URL field other than the
  two rights-holder URLs above.
- No `metadata`, `attrs`, `extra`, `notes`, `payload`, `tags` (free-form), or index signature.
  `applicability` is closed-key, closed-value; it is not a tag bag.
- No `image`, `figure`, `screenshot`, or binary field (`LICENSING.md` §4.14 defers images to
  C2 as a separate decision).
- No `author` on the chunk itself. Solus is the author of every chunk; the individual is the
  `reviewer`. A named drafter would be a person field that could name a customer.
- No `source_class` value for customers or for models (§4).

Adding any of these is a security change, not a schema change (CLAUDE.md §7; tool-knowledge
contract "Changing this contract").

## 4. Enumerations

All closed. Adding a value is a C-series ticket that updates this page and the fixtures together;
the TypeScript and Python halves assert vocabularies match member for member, as the tool-knowledge
suites do.

- `Domain`: `mechanical`, `electrical`, `software`, `systems`, `robotics`.
- `Topic`: exactly the `topic` column values of `SCOPE.md` §4.1–4.5, each bound to its domain.
- `Kind`: `principle`, `procedure`, `rule_of_thumb`, `reference_value`, `pitfall`, `glossary`.
- `Audience`: `fundamentals`, `reference`.
- `ApplicabilityKey` and per-key values: `SCOPE.md` §6, verbatim.
- `Derivation`: `verbatim`, `summary`, `facts_extracted`, `solus_original`.
- `SourceClass`: `solus_authored`, `us_government_work`, `open_license_permissive`,
  `open_license_restricted`, `vendor_documentation`, `datasheet`, `standards_body`,
  `open_source_project_docs`, `academic_paper`. **There is no `customer`, `community`, `model`,
  or `other` value.** Community and textbook sources are EXCLUDE and so have no way to be
  recorded as provenance; they can appear only as `further_reading`.
- `SourceLicense`: `CC0-1.0`, `CC-BY-2.5`, `CC-BY-3.0`, `CC-BY-4.0`, `MIT`, `BSD-2-Clause`,
  `BSD-3-Clause`, `Apache-2.0`, `ISC`, `CC-BY-SA-3.0`, `CC-BY-SA-4.0`, `CC-BY-NC-4.0`,
  `CC-BY-NC-SA-4.0`, `CC-BY-NC-ND-4.0`, `CC-BY-ND-4.0`, `GFDL-1.3-only`, `GPL-2.0-only`,
  `GPL-3.0-only`, `public-domain-us-gov`, `vendor-terms`, `datasheet-terms`, `standard-summary`,
  `arxiv-nonexclusive`, `solus-proprietary`, `unknown`.
- `ConfidenceBasis`: `standard_derived`, `vendor_stated`, `government_published`,
  `peer_reviewed`, `solus_measured`, `rule_of_thumb`, `consensus`.
- `Drafting`: `human`, `llm_assisted`.
- `Status`: `draft`, `active`, `superseded`, `withdrawn`.

The two licence sets the rules below refer to:

- **SHIP licences** = `CC0-1.0`, `CC-BY-2.5`, `CC-BY-3.0`, `CC-BY-4.0`, `MIT`, `BSD-2-Clause`,
  `BSD-3-Clause`, `Apache-2.0`, `ISC`, `public-domain-us-gov`, `solus-proprietary`.
- **SUMMARISE licences** = every other value except `unknown`.

## 5. Validation rules (the policy, made mechanical)

C2 implements each rule in both halves with a named test. Rule numbers are stable for citation.

1. **Class binds licence and derivation.** Every `source_class` admits only the licences and
   derivations in this table; anything else fails. (`LICENSING.md` §3–4)

   | `source_class`             | `source_license` allowed                                      | `derivation` allowed                                                               |
   | -------------------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
   | `solus_authored`           | `solus-proprietary`                                           | `solus_original`                                                                   |
   | `us_government_work`       | `public-domain-us-gov`                                        | `verbatim` `summary` `facts_extracted`                                             |
   | `open_license_permissive`  | `CC0-1.0` `CC-BY-*` `MIT` `BSD-*` `Apache-2.0` `ISC`          | `verbatim` `summary` `facts_extracted`                                             |
   | `open_license_restricted`  | `CC-BY-SA-*` `CC-BY-NC-*` `CC-BY-ND-4.0` `GFDL-1.3-only`      | `summary` `facts_extracted`                                                        |
   | `vendor_documentation`     | `vendor-terms`                                                | `summary` `facts_extracted`                                                        |
   | `datasheet`                | `datasheet-terms`                                             | `facts_extracted` `summary`                                                        |
   | `standards_body`           | `standard-summary`                                            | `summary`                                                                          |
   | `open_source_project_docs` | any SPDX value in the enum                                    | `verbatim` only if the licence is a SHIP licence; else `summary` `facts_extracted` |
   | `academic_paper`           | `CC-BY-*` `CC-BY-NC-*` `CC-BY-NC-ND-4.0` `arxiv-nonexclusive` | `verbatim` only if `CC-BY-*`; else `summary` `facts_extracted`                     |

   A vendor document published under an open licence in a public repository is classified as
   `open_license_permissive` or `open_source_project_docs`, never as `vendor_documentation`
   (`LICENSING.md` §4.5). The vendor-terms-register path (§7) is empty at v1 and is not
   modelled; adding it is a policy change that edits this table.

2. `derivation = verbatim` requires `source_license` ∈ SHIP licences, independently of rule 1,
   so a future row cannot relax it by accident. (`LICENSING.md` §1)
3. `source_class = standards_body` forbids `facts_extracted`: a "fact" from a standard is
   usually a requirement, which is the standard's expression. (§4.7)
4. `derivation = solus_original` ⇔ `source_class = solus_authored`. (§4.1)
5. `source_class = solus_authored` requires `source_url = null`, `source_locator = ""`, and
   `checked_against` non-empty when `drafting = llm_assisted`. (§4.1, §4.12)
6. `provenance.attribution` is non-empty when `source_license` is a `CC-BY-*` value or a
   permissive software licence and `derivation = verbatim`. (§5)
7. `further_reading` entries never carry a `url` to a host that is not the rights-holder's; C2
   applies the same host allowlist as rule 14.
8. `reviewer` matches the Solus staff-id pattern `^[a-z][a-z0-9_-]{2,63}$` and is not a UUID, an
   email address, or a model name (`claude`, `gpt`, `model`, `llm`, `assistant`, `sol`, … as a
   handle token); `reviewed_at` is not in the future.
9. `status = active` requires `source_license ≠ unknown`, `reviewer` present, and
   `confidence > 0`. `draft` is the only status that may carry `unknown`.
10. `status = superseded` requires that some active chunk has this id in `supersedes`;
    `withdrawn` chunks keep `id`, `title`, `status`, `corpus_version`, `revised_in`, and an empty
    `body`. `applicability`, `related`, `further_reading`, and `checked_against` are cleared,
    the embedding is dropped, and `revised_in` becomes the release that withdrew it; the
    provenance block (class, licence, publisher) is kept so a takedown is auditable (rule 5's
    `checked_against` requirement therefore does not apply to a withdrawn chunk).
11. `topic` is bound to `domain`; a mechanical topic on an electrical chunk fails.
12. `applicability` keys are unique per chunk; values belong to their key's enum.
13. `body` contains no `<<<` sequence (the fence delimiter; the same rule `prompt.py` relies on),
    no raw HTML, no image syntax, and no link whose target differs from `provenance.source_url`.
14. `source_url` and every `Citation.url` are `https`, have no userinfo, and resolve to a host on
    the per-class source-host allowlist in `packages/api/src/solus_api/corpus/hosts.py` (the
    corpus equivalent of `VENDOR_DOC_DOMAINS` in the tool-knowledge ingestion guard). Citation
    URLs may use any class's host (they are pointers, not provenance).
15. `content_hash` recomputes; `embedding` is null at v1 and, when present later, is excluded
    from the hash.
16. `license = solus-proprietary` (the only value).

`LICENSING.md` §8's worked classifications double as the fixture set: each SHIP/SUMMARISE row
yields one valid fixture, each EXCLUDE row yields one illegal construction (no `source_class`
value can express it), and each "same candidate, different facts" pair yields one rule test.

## 6. Prompt assembly and retrieval

- **A chunk is data.** It enters a prompt only as `<<<SOLUS-DATA {nonce} kind=corpus>>>` with
  `id`, `title`, `body`, `attribution`, and `confidence`; never `reviewer`, never
  `source_locator` beyond what the attribution string carries. Solus wrote or curated it, and it
  is still not an instruction. Red-team fixtures in the agent suite include a chunk whose body
  says "ignore previous instructions" and assert non-compliance, exactly as for ingested content.
- **SOL cites by id.** An answer that leans on a chunk names `corpus:<domain>/<topic>/<slug>`;
  Guide mode renders the attribution and further reading, Expert mode renders the id and the
  value. Rendering is text-only (model output is untrusted, CLAUDE.md §7).
- **Retrieval filters first** (ADR-033 rule 4, ADR-036): `domain` + `topic` + `applicability`
  are SQL WHERE clauses, then ANN over `embedding` when a query vector exists and English
  full-text over `title` and `body` otherwise (`corpus/retrieval.py`). The domain of a free-text
  question is routed deterministically from a Solus-authored lexicon (`corpus/domains.py`).
  Only `status = active` rows serve.
- **Preferences select, never speak.** The Layer-2 `.solus/project.toml` facts map to
  `applicability` keys and filter or rank the candidate set. No preference value is ever
  interpolated into prompt text. This is the entire interaction between the corpus and the
  preferences layer at v1.
- **Mode is a rank, not a filter.** Guide mode ranks `fundamentals` first; Expert ranks
  `reference` first; both can reach both (ADR-016: mode changes presentation, never facts).

## 7. Example

```json
{
  "id": "corpus:electrical/decoupling/loop-area",
  "domain": "electrical",
  "topic": "decoupling",
  "title": "Decoupling capacitor placement is about loop area, not distance",
  "body": "A decoupling capacitor supplies the transient current an IC draws when its outputs switch, so the supply does not have to. What limits how well it does that is the inductance of the loop from the capacitor through the IC's power and ground pins and back, and inductance scales with the area of that loop. ...",
  "kind": "principle",
  "audience": "fundamentals",
  "applicability": [{ "key": "fabrication_class", "value": "prototype" }],
  "derivation": "solus_original",
  "provenance": {
    "source_class": "solus_authored",
    "source_title": "Solus engineering corpus",
    "source_publisher": "Solus",
    "source_url": null,
    "source_locator": "",
    "source_license": "solus-proprietary",
    "accessed_at": "2026-09-05",
    "attribution": "",
    "checked_against": [
      {
        "title": "Application note on decoupling capacitor placement",
        "author": "Texas Instruments",
        "identifier": "TI document number, recorded at review",
        "url": "https://www.ti.com/"
      }
    ]
  },
  "further_reading": [
    {
      "title": "High-Speed Digital Design: A Handbook of Black Magic",
      "author": "Johnson, Graham",
      "identifier": "ISBN 978-0133957242",
      "url": null
    }
  ],
  "license": "solus-proprietary",
  "confidence": 0.9,
  "confidence_basis": "vendor_stated",
  "drafting": "llm_assisted",
  "reviewer": "solus-staff-placeholder",
  "reviewed_at": "2026-09-05",
  "status": "draft",
  "supersedes": null,
  "related": ["corpus:electrical/pcb_layout_basics/return-paths"],
  "corpus_version": "1.0.0",
  "revised_in": "1.0.0",
  "content_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  "embedding": null
}
```

The example is `draft` on purpose: its reviewer id is a placeholder and its citation identifier is
unresolved, and rule 9 would refuse to activate it. That is the intended behaviour.

## 8. Corpus manifest

The corpus ships with one manifest, whichever storage C2 chooses:

```json
{
  "schema_version": 1,
  "corpus_version": "1.0.0",
  "released_at": "2026-...",
  "policy_revision": "docs/corpus/LICENSING.md@<commit>",
  "chunks": [{ "id": "...", "content_hash": "sha256:...", "status": "active" }]
}
```

The manifest is what the desktop, the API, and SOL agree on when they say which corpus they are
using; a chunk not in the manifest is not served. Local-state rules (ADR-034 Layer 1) apply if C2
caches the corpus under `~/.solus`: JSON, `schema_version`, atomic writes, 0600 files, hash
verified before use, deletable at any time, never a source of truth.

## 9. Open items carried to C2 — resolution

- **Storage:** `corpus_chunk` table, ADR-036. Citations are a typed child table
  (`corpus_citation`); each applied version is a `corpus_release` row.
- **Staff-id pattern:** rule 8 above.
- **Per-class host allowlist:** `corpus/hosts.py` (rule 14).
- **Checker `Warning`s carrying chunk ids:** still open (also `SCOPE.md` §8).
- **Images:** not carried. The schema has no image field and C2 adds none.
