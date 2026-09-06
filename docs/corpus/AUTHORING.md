# Engineering Corpus — Authoring Guide (CORPUS C2)

**Ticket:** SOLUSDEV-241 (CORPUS C2) · **Status:** tier-1 (ADR-032) · **Authority:** ADR-036,
`docs/corpus/SCOPE.md`, `docs/corpus/LICENSING.md`, `docs/schemas/corpus-chunk.md`.

This is how a chunk is written so that `solus_api.corpus.chunking` accepts it. The chunker is
strict on purpose: a file that violates the licensing policy does not load.

## 1. Where files live

```
packages/api/src/solus_api/corpus/content/
├── corpus.toml                 ← corpus_version, policy_revision, released_at
├── manifest.json               ← generated: python -m solus_api.corpus manifest
└── <domain>/<topic>/<slug>.md  ← one authored document
```

`<domain>` is one of `mechanical electrical software systems robotics`; `<topic>` is that
domain's `topic` value from `SCOPE.md` §4 (a topic under the wrong domain fails to load);
`<slug>` is lowercase `[a-z0-9-]`. The chunk id is derived: `corpus:<domain>/<topic>/<slug>`.
Front matter may not set `id`, `domain`, `topic`, `body`, `content_hash`, or `embedding`.

## 2. The file

```markdown
+++
title = "Decoupling capacitor placement is about loop area, not distance"
kind = "principle"            # principle procedure rule_of_thumb reference_value pitfall glossary
audience = "fundamentals"     # fundamentals (Guide pulls first) | reference (Expert pulls first)
applicability = [{ key = "fabrication_class", value = "prototype" }]   # may be []
derivation = "solus_original" # verbatim summary facts_extracted solus_original
confidence = 0.9              # the REVIEWER's confidence, 0..1
confidence_basis = "vendor_stated"  # standard_derived vendor_stated government_published
                                    # peer_reviewed solus_measured rule_of_thumb consensus
drafting = "llm_assisted"     # human | llm_assisted
reviewer = "mhussain"         # a Solus staff handle — never a model, uuid, or email
reviewed_at = 2026-09-06
status = "active"             # draft active superseded withdrawn
related = ["corpus:electrical/pcb_layout_basics/return-paths"]   # ids in THIS corpus
further_reading = [
  { title = "High-Speed Digital Design", author = "Johnson, Graham", identifier = "ISBN 978-0133957242" },
]
corpus_version = "0.1.0"      # introduced in
revised_in = "0.1.0"          # last change; equals corpus_version when unchanged

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "Application note on decoupling", author = "Texas Instruments", identifier = "SLVA-series", url = "https://www.ti.com/" },
]
+++

The body starts after the closing fence. Markdown subset: headings, lists, inline code,
tables you wrote, fenced formulae. No images, no raw HTML, no links except to `source_url`.
```

Omitted optional fields default to: `source_url = null`, `source_locator = ""`,
`attribution = ""`, `checked_against = []`, `further_reading = []`, `applicability = []`,
`related = []`, `supersedes = null`, citation `author`/`identifier` `""`, citation `url` null.

## 3. How the body becomes chunks

- No `## ` headings → the file is one chunk, titled from `title`.
- `## Heading` lines split the body: text before the first heading is a chunk titled from
  `title`; each heading section is a chunk titled by the heading, id
  `corpus:<domain>/<topic>/<slug>-<heading-slug>`. All chunks share the front matter.
- Fenced blocks (` ``` `) and tables (`|` lines) are atomic. A `## ` inside a fence is
  text, not a split. A section over 6,000 characters is packed block by block into
  `<id>`, `<id>-2`, `<id>-3`; a single block over the cap is an error — split it yourself.
- Prefer one idea per file. Use headings only when a document genuinely has parts.

## 4. What a chunk must say (SCOPE.md §3)

The v1 minimum per topic is one `fundamentals` principle, one `reference` rule or value, and
one `pitfall`. Write for the consumer named in `SCOPE.md` §4: SOL explains it, a checker cites
it, autocomplete shows it as a warning explanation. A rule of thumb states its limits. A
reference value carries the condition it holds under. A pitfall says how it usually goes wrong
and what to check. Use SI with the imperial equivalent only where the field uses it (AWG).

## 5. Licensing in one screen (LICENSING.md decides; this is the summary)

| You are writing…                                   | `source_class`             | `source_license`       | `derivation`                     |
| -------------------------------------------------- | -------------------------- | ---------------------- | -------------------------------- |
| Your own explanation, checked against real sources | `solus_authored`           | `solus-proprietary`    | `solus_original`                 |
| A NASA/NIST/MIL-HDBK document, public-use line     | `us_government_work`       | `public-domain-us-gov` | verbatim / summary / facts       |
| A CC BY or MIT/Apache page (checked on the page)   | `open_license_permissive`  | that SPDX id           | verbatim (with attribution) etc. |
| CC BY-SA / NC / ND, GFDL                           | `open_license_restricted`  | that SPDX id           | summary / facts only             |
| A TI/ADI/ST/NXP application note                   | `vendor_documentation`     | `vendor-terms`         | summary / facts only             |
| A datasheet                                        | `datasheet`                | `datasheet-terms`      | facts (with locator) / summary   |
| IPC / ISO / IEC / ASME / JEDEC / USB-IF            | `standards_body`           | `standard-summary`     | summary only, no values          |
| ROS / MuJoCo / KiCad / Zephyr docs                 | `open_source_project_docs` | the docs' licence      | verbatim only if SHIP licence    |
| A paper                                            | `academic_paper`           | CC BY / NC / arXiv     | verbatim only if CC BY           |

Not writable at all (no `source_class` exists): textbooks, Stack Overflow, Wikipedia, forums,
blogs, videos, anything from a customer, anything "the model remembers". Textbooks may be
named in `further_reading` only. **Empty beats invented**: if you cannot point at an allowed
source, leave the topic thinner and say so in the completion report.

`solus_authored` + `llm_assisted` requires a non-empty `checked_against` naming the real
sources the claims were checked against, and the reviewer runs the §4.1 verbatim check.
`source_url` and citation `url`s must be `https` on the rights-holder's own host
(`solus_api/corpus/hosts.py`); a mirror or aggregator fails. When unsure of a deep link, cite
the rights-holder's root (`https://www.nxp.com/`) and put the document number in `identifier`.

## 6. Checklist before you commit a file

- [ ] Path is `<domain>/<topic>/<slug>.md` with a topic that belongs to that domain
- [ ] Every claim is one you could source to a SHIP or SUMMARISE class; the sources are named
- [ ] No sentence tracks a textbook, standard, or vendor document paragraph by paragraph
- [ ] Numbers carry their conditions; rules of thumb carry their limits
- [ ] No `<<<`, no HTML, no images, no foreign links in the body
- [ ] `python -m solus_api.corpus validate` passes and `manifest` was regenerated

## 7. Eval questions (`packages/api/tests/fixtures/corpus_eval/<domain>.json`)

The CI eval (`tests/corpus/test_eval.py`) scores retrieval against these. One JSON array per
domain; every entry:

```json
{
  "id": "electrical-decoupling-01",
  "domain": "electrical",
  "topic": "decoupling",
  "question": "Where should the 100 nF cap for my MCU go — does 5 mm away matter?",
  "gold_chunk_ids": ["corpus:electrical/decoupling/loop-area"],
  "required_facts": ["loop", "inductance"],
  "answer": "As close to the IC's power/ground pin pair as the layout allows: what matters is the loop area through the capacitor and pins, because loop inductance limits how fast it can supply transient current."
}
```

- `question` is phrased the way an engineer types it — never a copy of a chunk title. Include
  vocabulary from OTHER domains where realistic (a trace-width question that says
  "tolerance"), because the eval also checks that a domain-filtered query returns only that
  domain.
- `gold_chunk_ids` are ids that exist in the tree (1–3). `required_facts` are 1–3 short,
  lowercase substrings that a correct set of retrieved chunks must contain; pick words that
  appear in the gold chunk and would be absent from an off-topic one.
- `answer` is the known-good answer in prose, for the model-judged `-m live` run.
- Two questions per P0 topic minimum, in the domain's file.
