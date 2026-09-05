# Engineering Corpus — Licensing Policy (CORPUS C1)

**Ticket:** SOLUSDEV-241 (CORPUS C1) · **Status:** policy, tier-1 (ADR-032), reviewed at the MR.
**Scope it governs:** every chunk in the engineering corpus (`docs/corpus/SCOPE.md`), at every
corpus version. The chunk schema (`docs/schemas/corpus-chunk.md` §5) encodes the outcome table
below as cross-field validation rules, so a chunk that violates this policy is meant to be
unrepresentable once C2 lands. Until then, this document is the only gate.
**Decisions recorded in-session (2026-09-05, Phase 1 gate):** vendor application notes and
datasheets default to SUMMARISE, not verbatim; share-alike and non-commercial open licences are
SUMMARISE; C1 ships no code.

> **The rule.** The corpus is distributed to every Solus customer as part of a commercial product.
> Every byte in it is redistribution. **Anything not clearly allowed does not ship.** Free to read
> is not free to redistribute. When the reviewer cannot point at the licence statement, the
> outcome is EXCLUDE.

---

## 1. The three outcomes

| Outcome       | What may ship                                                                                                                                                                                            | Chunk `derivation` values allowed        |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| **SHIP**      | The source's own text, in excerpt or in full, with the attribution the licence requires. Solus may also summarise it.                                                                                    | `verbatim`, `summary`, `facts_extracted` |
| **SUMMARISE** | Solus-written text, in Solus's own words, stating the principle, the procedure, or the fact, with a citation to the source. No excerpt, no reproduced table, no reproduced figure.                       | `summary`, `facts_extracted`             |
| **EXCLUDE**   | Nothing from the source. The source may be named as further reading (title, author, edition, identifier) in a chunk written from an allowed source. Nothing in the chunk may be derived from reading it. | — (may appear only in `further_reading`) |

Definitions the reviewer needs:

- **Verbatim** — any run of the source's wording. There is no "short quotation" allowance in
  this policy; a defined term or a standard's title is a citation, not a quotation.
- **Summary** — Solus prose that could have been written by someone who understood the idea and
  closed the book. It restates principle and procedure. It does not track the source's sentence
  order, headings, or worked examples. Test: if the reviewer can line the chunk up paragraph by
  paragraph against the source, it is not a summary.
- **Facts extracted** — individual uncopyrightable facts (a pin count, a rated current, a
  thermal resistance, a formula's form) recorded as structured values with a locator into the
  source. A _selection and arrangement_ of many facts (a whole table) is not a fact; it is the
  source's table, and it does not ship from any SUMMARISE-class source.
- **Further reading** — a bibliographic pointer only. Never a link to a copy of the work the
  rights-holder did not publish.

## 2. The classification procedure

Answer in order. The first question that resolves gives the outcome. Record the answers on the
chunk's `provenance` block.

1. **Is any part of it derived from a customer's project, files, telemetry, or conversation?**
   Yes → **EXCLUDE**, no exceptions, including anonymised or "illustrative" versions. This is
   the tenancy boundary (CLAUDE.md §7, ADR-033); it is not a licensing question and no licence
   changes the answer.
2. **Can the reviewer point at the licence or rights statement?** A page, a front-matter notice,
   a repository `LICENSE`, a site terms page, a document-level copyright line. No → **EXCLUDE**.
   "Everyone uses it" and "it is on the internet" are not statements.
3. **Does that statement permit commercial redistribution of the text itself?** Public domain,
   CC0, CC BY, or a permissive software licence covering the documentation → **SHIP**, subject to
   the attribution rules in §5.
4. **Does the statement permit the reviewer to read it lawfully, and does it not prohibit
   restating its ideas in Solus's own words?** Open licences with share-alike, non-commercial, or
   no-derivatives terms; vendor documentation offered for download; standards the reviewer holds
   a licensed copy of; open-access papers; datasheets → **SUMMARISE**.
5. **Otherwise** — all-rights-reserved textbooks, paywalled papers, courseware, community
   content, anything whose terms are unclear → **EXCLUDE**.

Two overriding checks after the outcome:

- **Accuracy is not licensing.** A SHIP-class source can still be wrong. Community wikis and
  forums are EXCLUDE (§4.9) for accuracy, not only for licence.
- **The reviewer, not the drafter, decides.** Every chunk records a Solus reviewer (§6). A chunk
  drafted with an LLM's help is `solus_authored` and goes through §4.1's verbatim check.

## 3. Outcome table by source class

| §    | Source class                                         | Default outcome | Notes                                                                                              |
| ---- | ---------------------------------------------------- | --------------- | -------------------------------------------------------------------------------------------------- |
| 4.1  | Solus-authored                                       | SHIP            | Reviewer-signed; no verbatim from any EXCLUDE or SUMMARISE source                                  |
| 4.2  | US federal government works                          | SHIP            | Per-document check; contractor and grantee works may be copyrighted                                |
| 4.3  | Open licences — CC0, CC BY, permissive               | SHIP            | Attribution per licence; check the licence _version_ and any per-page variance                     |
| 4.4  | Open licences — share-alike, NC, ND, GFDL            | SUMMARISE       | Never excerpt; share-alike must never attach to the corpus                                         |
| 4.5  | Vendor application notes, guides, ref designs        | SUMMARISE       | Verbatim only after a per-vendor terms entry in §7 — none exist at v1                              |
| 4.6  | Datasheets                                           | SUMMARISE       | `facts_extracted` with page/table locator; no prose, no figures                                    |
| 4.7  | Standards bodies                                     | SUMMARISE       | Principle and clause pointer only; no text, tables, or figures; reviewer must hold a licensed copy |
| 4.8  | Open-source project documentation                    | by licence      | Apache/MIT/CC BY docs → SHIP; GPL/GFDL/SA docs → SUMMARISE                                         |
| 4.9  | Community content — Q&A, wikis, forums, blogs, video | EXCLUDE         | Leads to primary sources only                                                                      |
| 4.10 | All-rights-reserved textbooks and courseware         | EXCLUDE         | Further-reading pointer only                                                                       |
| 4.11 | Academic papers                                      | by licence      | CC BY → SHIP; arXiv default licence or OA-by-access → SUMMARISE; paywalled → EXCLUDE               |
| 4.12 | LLM output and model memory                          | not a source    | Drafting aid only; provenance must name a real source or be `solus_authored`                       |
| 4.13 | Customer content                                     | EXCLUDE         | Always; see §2 step 1                                                                              |
| 4.14 | Images, figures, tables                              | stricter        | See §4.14                                                                                          |

## 4. Source classes in detail

### 4.1 Solus-authored — SHIP

Text written by Solus staff or contractors under a Solus work-for-hire or assignment agreement.
Licence recorded as `solus-proprietary`.

Conditions:

- A named Solus reviewer other than the drafter signs it (§6).
- **Verbatim check.** The drafter states which sources were open while writing. If any was a
  SUMMARISE or EXCLUDE class, the reviewer spot-checks that no run of the chunk matches the
  source. Any matching run of more than a defined term or a formula in standard notation fails
  the chunk. There is no word-count threshold to argue about; matching prose fails.
- **LLM-assisted drafting is allowed and must be declared** (`drafting: llm_assisted`). Models
  reproduce copyrighted passages from memory; the verbatim check is the control, and the reviewer
  treats an LLM draft as if the drafter had every textbook open.
- The chunk cites the sources it was checked against, even when none is quoted, so a later
  reviewer can repeat the check.

### 4.2 US federal government works — SHIP, per document

Works prepared by US government employees as part of their duties are not subject to US
copyright. Candidate publishers: NASA, NIST, DoD (MIL-STD and MIL-HDBK via ASSIST), FAA, NRL,
DOE national laboratories (see the caveat), USGS, Army and Navy technical manuals.

Conditions:

- **Check the document, not the publisher.** NASA's technical report server also distributes
  contractor and grantee reports; the report's own copyright line governs. A line such as
  "Work of the US Government, public use permitted" → SHIP. A contractor copyright line, or no
  line at all → SUMMARISE if the terms of access allow, else EXCLUDE.
- National laboratory reports are frequently authored by contractor employees and may carry a
  copyright notice with a government-purpose licence. That licence is not a public licence →
  SUMMARISE.
- **Jurisdiction.** The public-domain status is a US-law fact. Solus accepts the residual
  exposure that some jurisdictions recognise foreign-government copyright; record
  `public-domain-us-gov` as the licence so the exposure is queryable, not hidden.
- Attribution is not legally required. The corpus cites anyway (§5), because every chunk cites.

### 4.3 Open licences permitting commercial redistribution — SHIP

- **CC0 1.0**, **CC BY 4.0**, **CC BY 3.0**, **CC BY 2.5** → SHIP with attribution in the
  licence's required form (title, author, source, licence: §5).
- **Permissive software licences applied to documentation** — MIT, BSD-2/3, Apache-2.0, ISC →
  SHIP; retain the licence notice as the attribution.
- **Check per page, not per site.** Aggregators (LibreTexts, some wikis, some university OER
  portals) carry different licences on different pages or books. The chunk's `source_license`
  records the licence of the page it was taken from, verified on that page.
- **Check the version.** A "CC BY" statement without a version is treated as the most
  restrictive plausible reading until the reviewer finds the version; record what was found.
- **Candidate open textbook publishers to evaluate per book** (licences vary by title and edition;
  none are asserted here — verify before pinning): OpenStax, LibreTexts, Open Textbook Library,
  MIT OpenCourseWare (frequently CC BY-NC-SA, which is §4.4), university-hosted lecture notes with
  an explicit licence page.

### 4.4 Open licences with share-alike, non-commercial, or no-derivatives terms — SUMMARISE

CC BY-SA (any version), CC BY-NC, CC BY-NC-SA, CC BY-NC-ND, CC BY-ND, GNU FDL.

- **Never excerpt.** Share-alike attaches to adaptations; a verbatim excerpt in the corpus would
  put the corpus under SA terms. Solus does not license the corpus outward, so SA must never
  attach. NC forbids commercial use of the work; the corpus is commercial. ND forbids adaptation.
- **Summaries of ideas and facts ship.** Copyright protects expression, not ideas or facts. A
  Solus-written statement of the principle, with citation, is not an adaptation. This is the
  in-session decision of 2026-09-05; it is a considered legal posture, not a certainty, and the
  chunk's `source_license` makes every such chunk enumerable if the posture changes.
- The §1 summary test applies with full force here: a paraphrase that tracks the source's
  structure is an adaptation and fails review.
- Wikipedia and the StackExchange network are CC BY-SA and would fall here on licence, but are
  EXCLUDE on accuracy (§4.9). Use them to find primary sources.

### 4.5 Vendor application notes, user guides, and reference designs — SUMMARISE

Texas Instruments, Analog Devices, Microchip, STMicroelectronics, NXP, Nordic, Espressif, Bosch,
TDK InvenSense, Infineon, onsemi, Renesas, Würth, Molex, JST, TE, and similar.

- These documents are published for free **access**. The publisher's terms of use typically
  grant a personal, non-transferable right to download and use the documentation with the
  publisher's products. That is not a right to redistribute the text inside a third-party product.
  The ticket's assumption that they "publish freely" conflates access with licence; the Phase 1
  gate resolved this to SUMMARISE by default.
- **SHIP verbatim only when a per-vendor entry exists in §7** naming the terms page, the
  reviewer, the date, and the exact clause that permits redistribution. **At v1 the register is
  empty**: no vendor's terms have been verified, so no vendor text ships verbatim.
- Some vendors publish specific documentation under open licences in public repositories (SDK
  docs in a GitHub repository with a `LICENSE` file). Those documents are classified by that
  licence under §4.3 or §4.8, per file, not by the vendor's site terms.
- Attribution in the summary names the vendor and the document number (for example "per TI
  SLVA-series application note on decoupling"), which is a citation, not a reproduction.

### 4.6 Datasheets — SUMMARISE, as extracted facts

- A datasheet's individual values are facts: pin count, absolute maximum ratings, recommended
  operating conditions, thermal resistance, package dimensions, register addresses. They ship as
  `facts_extracted` with a locator (revision, page, table, or parameter name).
- The datasheet's prose, figures, application circuits, and complete tables do not ship.
  A complete electrical-characteristics table is the manufacturer's selection and arrangement.
- Record the datasheet revision. A fact from an outdated revision is a defect, not a licence
  problem, but the field exists so it can be found.
- This class is the natural home of the part-level facts checkers already consume (voltage
  ranges for `power_compatibility`, supply rails for `op_amp_mismatch`). Whether checker facts
  live in the corpus or in the graph's part attributes is a C2 question; the licence outcome is
  the same either way.

### 4.7 Standards bodies — SUMMARISE, never the text

IPC, ISO, IEC, ASME (Y14.5 and the B-series), ASTM, SAE, UL, IEEE standards, JEDEC, USB-IF, NEMA,
DIN, BS, JIS, and the ROS REPs' upstream standards where applicable.

- **No text, no tables, no figures, no numbered requirement reproduced in its own words at the
  sentence level.** A chunk may state what a standard is for, the principle behind its approach,
  the names of the quantities it governs, and a clause pointer ("IPC-2221, the external-conductor
  current-capacity method"). It may give a single representative value only when that value is
  independently and widely published as a fact and the chunk says so.
- **Freely downloadable is not public domain.** JEDEC and USB-IF distribute at no charge under
  terms that retain copyright → SUMMARISE. Standards incorporated by reference into regulation
  have been litigated toward public availability in some jurisdictions; the corpus does not rely
  on that.
- **The reviewer must hold a licensed copy** of any standard a chunk summarises, or the chunk's
  summary is written from a secondary source that is itself SHIP or SUMMARISE class and the
  chunk cites that secondary source, not the standard. Summarising a standard from memory or
  from a forum post is EXCLUDE-by-construction.
- Chunk `source_license` for this class is `standard-summary`. `derivation` must be `summary`;
  `facts_extracted` is not available for standards because a "fact" from a standard is usually a
  requirement, which is the standard's expression.

### 4.8 Open-source project documentation — by licence

ROS and ROS 2 documentation, REPs, MuJoCo, KiCad, Zephyr, FreeRTOS, Arduino, PlatformIO, micro-ROS,
Foxglove, and similar.

- Classify by the **documentation's** licence, which often differs from the code's. Find the
  `LICENSE` in the docs tree, the footer of the docs site, or the per-file header. Do not assume;
  none of the projects above have their documentation licence asserted by this policy —
  verify before pinning, record what was found.
- Apache-2.0, MIT, BSD, CC BY → SHIP (§4.3). GPL (any version), GFDL, CC BY-SA → SUMMARISE
  (§4.4). The repository already carries one flagged GPLv3 fixture from the TU-02 KiCad ingestion
  (`docs/qa/COMPLETION_SOLUSDEV-205-tu02-kicad-docs-ingestion.md`, flag 1); that precedent is
  why copyleft documentation does not ship verbatim in the corpus.
- REPs (ROS Enhancement Proposals) carry their own per-document licence statements; classify each
  REP individually.

### 4.9 Community content — EXCLUDE

StackExchange and Stack Overflow, Reddit, Discourse and vendor forums, hobbyist wikis, personal
blogs, YouTube and other video transcripts, Discord and Slack exports, hackathon write-ups.

- EXCLUDE regardless of licence, for accuracy and provenance: the corpus cannot carry a
  `confidence` for an anonymous author's claim.
- Permitted use: as a lead. The reviewer follows the community post to the datasheet, standard,
  paper, or vendor document it draws on and classifies that.
- A named engineer's personal blog with an explicit CC BY licence is still EXCLUDE at v1. Adding
  an "expert-authored, individually reviewed" class is a policy amendment, not a reviewer call.

### 4.10 All-rights-reserved textbooks and courseware — EXCLUDE

The canonical engineering references — Shigley, Norton, Horowitz & Hill, Ott, Johnson & Graham,
Craig, Siciliano, Lynch & Park, Åström & Murray, Franklin, and paid courses.

- Nothing in the chunk is derived from reading them. Not a summary, not a paraphrase, not a
  worked example with the numbers changed, not the chapter's structure.
- They may be named in `further_reading` — title, author, edition, ISBN or DOI. That is the
  full extent of their presence in the corpus.
- The same topics are covered from §4.1, §4.2, §4.3, and §4.7-class sources. If no such source
  exists for a topic, the topic stays empty and `SCOPE.md` §5 applies: empty beats invented.
- The distinction from §4.4 is deliberate. Open non-commercial sources chose to publish under a
  licence that anticipates reading and reuse of ideas; an all-rights-reserved textbook did not,
  and a "summary" of a chapter is where a reviewer is most likely to produce an adaptation
  without noticing.

### 4.11 Academic papers — by licence

- Published under CC BY → SHIP (§4.3). Under CC BY-NC or CC BY-NC-ND (common for open-access
  publishing) → SUMMARISE (§4.4).
- arXiv: the licence is per paper and shown on the abstract page. arXiv's default non-exclusive
  licence permits arXiv to distribute; it does not permit Solus to → SUMMARISE. A CC BY arXiv
  paper → SHIP.
- Paywalled or "free to read" without a licence statement → EXCLUDE; the abstract page may be
  cited as further reading.
- Author-posted preprints on personal pages are EXCLUDE unless the page states a licence.

### 4.12 LLM output and model memory — not a source class

- A model's answer has no provenance. A chunk cannot cite "Claude" or "the model" as a source.
- Models may draft. The result is `solus_authored`, declared `llm_assisted`, and every claim in
  it is sourced by the reviewer to a real §4.1–4.11 source before the chunk is accepted. A claim
  the reviewer cannot source is removed.
- The `confidence` of an LLM-drafted chunk is the reviewer's confidence after sourcing, never
  the model's.

### 4.13 Customer content — EXCLUDE, always

Any customer's design files, part names, dimensions, schematics, code, telemetry, SOL
conversations, support tickets, or screenshots. Anonymisation does not change the answer.
The chunk schema has no provenance value for this class and no field that could carry a customer
identifier (`docs/schemas/corpus-chunk.md` §3), mirroring `docs/contracts/tool-knowledge.md`.

### 4.14 Images, figures, and tables — stricter than text

- Figures and tables ship only from **SHIP-class** sources and only when the licence covers the
  figure (a CC BY book may embed an all-rights-reserved figure with its own credit line; the
  credit line governs).
- From every other class, Solus redraws. A redrawn diagram that conveys the same idea with
  Solus's own layout and labels is `solus_authored`. A redrawn diagram that reproduces a
  standard's figure element for element is the standard's figure and fails.
- Tables are the §1 "selection and arrangement" case: a table is never `facts_extracted`.
- C1 defines no image field on the chunk; whether the corpus carries images at all is a C2
  decision. This section exists so that decision starts from the right constraint.

## 5. Attribution and licence recording

Every chunk records, in `provenance`:

- `source_class` — the §4 class (closed enum, schema §4).
- `source_title`, `source_publisher`, `source_url` (a canonical, rights-holder-hosted URL, never
  a mirror), `source_locator` (revision, page, clause, section, table, or commit), `accessed_at`.
- `source_license` — an SPDX identifier where one exists (`CC-BY-4.0`, `CC0-1.0`, `Apache-2.0`,
  `MIT`, `CC-BY-SA-4.0`, `CC-BY-NC-4.0`, `GFDL-1.3-only`, `GPL-3.0-only`), or one of the corpus
  vocabulary values: `public-domain-us-gov`, `vendor-terms`, `datasheet-terms`,
  `standard-summary`, `solus-proprietary`, `arxiv-nonexclusive`, `unknown`. `unknown` is a valid
  value only on a chunk with `status: draft`; an active chunk with `unknown` fails validation.
- `attribution` — the rendered attribution string when the licence requires one. For CC BY: title,
  author, source link, licence name and link, and a note of changes if the text was modified. For
  permissive software licences: the notice text. For everything else: the citation form
  "publisher, document, locator".

The chunk's own outgoing `license` (what Solus licenses the chunk under) is `solus-proprietary`
for every chunk. A verbatim CC BY excerpt inside it remains CC BY and is attributed as such;
that is what the attribution field is for.

## 6. Review and accountability

- Every chunk names a `reviewer` — a Solus staff identifier, never a customer, never a model —
  and a `reviewed_at` date. The reviewer attests to the §2 procedure and, for `solus_authored`,
  the §4.1 verbatim check.
- Review is recorded on the chunk and is part of the corpus version. A chunk without a reviewer
  is `draft` and does not ship.
- **Disputes and takedowns.** A rights-holder claim, or an internal finding that a chunk fails
  this policy, moves the chunk to `status: withdrawn` in the next corpus release, which is a
  version bump. The id survives so past SOL citations resolve to a withdrawal notice. The
  reviewer of record is notified; the classification is re-run and recorded.
- **Policy changes.** Widening any outcome (moving a class from SUMMARISE to SHIP, adding a class
  to SHIP, adding a quotation allowance) is a human decision recorded in this document with the
  date and the approver, then reflected in the schema's validation rules in the same MR.
  Narrowing may be done by any reviewer with a note here.

## 7. Vendor terms register

A vendor's documentation ships verbatim only if it has a row here. **Empty at v1.** Nothing has
been verified; every vendor is SUMMARISE.

| Vendor | Terms page (URL) | Clause permitting redistribution | Reviewer | Date | Outcome |
| ------ | ---------------- | -------------------------------- | -------- | ---- | ------- |
| —      | —                | —                                | —        | —    | —       |

## 8. Worked classifications

The acceptance test for this policy is that a reviewer with no other context reaches these
outcomes. Each line gives the §2 step that decided it.

| Candidate                                                                    | Outcome                                         | Decided at                                                                       |
| ---------------------------------------------------------------------------- | ----------------------------------------------- | -------------------------------------------------------------------------------- |
| NASA technical report with "Work of the US Government, public use permitted" | SHIP                                            | §2.3 via §4.2                                                                    |
| NASA contractor report on NTRS with the contractor's copyright line          | SUMMARISE                                       | §2.4 via §4.2 (access permitted, not redistribution)                             |
| MIL-HDBK-5 (metallic materials) downloaded from ASSIST                       | SHIP                                            | §2.3 via §4.2                                                                    |
| OpenStax "College Physics", page states CC BY 4.0                            | SHIP                                            | §2.3 via §4.3, attribution TASL                                                  |
| MIT OpenCourseWare lecture notes, CC BY-NC-SA 4.0                            | SUMMARISE                                       | §2.4 via §4.4                                                                    |
| Wikipedia article on creepage distance                                       | EXCLUDE                                         | §2 accuracy override, §4.9 (use as a lead)                                       |
| TI application note on buck converter layout, downloaded from ti.com         | SUMMARISE                                       | §2.4 via §4.5 (no §7 row)                                                        |
| TI application note, verbatim, with a §7 row citing a permitting clause      | SHIP                                            | §2.3 via §4.5 — no such row exists at v1                                         |
| STM32F4 datasheet, absolute maximum ratings table                            | SUMMARISE                                       | §2.4 via §4.6, `facts_extracted` per value, not the table                        |
| IPC-2221 trace-width tables, reviewer holds a licensed PDF                   | SUMMARISE                                       | §2.4 via §4.7 — principle and clause only, no values from the table              |
| IPC-2221 trace-width tables, reviewer found them on a forum                  | EXCLUDE                                         | §4.7 — no licensed copy, forum is §4.9                                           |
| JEDEC JESD22 test method, free download                                      | SUMMARISE                                       | §2.4 via §4.7                                                                    |
| ROS 2 documentation page, footer shows CC BY 4.0 (verify on the page)        | SHIP                                            | §2.3 via §4.8                                                                    |
| KiCad source comment describing an action, GPLv3                             | SUMMARISE                                       | §2.4 via §4.8 (copyleft)                                                         |
| REP 103 (units and coordinate conventions), REP's own licence statement      | by that statement                               | §4.8, per document                                                               |
| Shigley's Mechanical Engineering Design, chapter on bolted joints            | EXCLUDE                                         | §2.5 via §4.10; further-reading pointer allowed                                  |
| Horowitz & Hill, The Art of Electronics                                      | EXCLUDE                                         | §2.5 via §4.10                                                                   |
| arXiv paper on IMU calibration, abstract page shows CC BY 4.0                | SHIP                                            | §2.3 via §4.11                                                                   |
| arXiv paper, "arXiv.org perpetual non-exclusive license"                     | SUMMARISE                                       | §2.4 via §4.11                                                                   |
| IEEE Xplore paper, subscription access                                       | EXCLUDE                                         | §2.5 via §4.11                                                                   |
| Stack Overflow answer on I2C pull-up sizing                                  | EXCLUDE                                         | §4.9; follow it to the I2C specification (NXP UM10204, §4.5 → SUMMARISE)         |
| An FSAE team's public GitHub wiring guide, no LICENSE file                   | EXCLUDE                                         | §2.2 — no licence statement                                                      |
| The same guide with an MIT LICENSE in the repository                         | SHIP on licence, EXCLUDE on §4.9 accuracy at v1 | §4.9 — expert-authored class not yet defined                                     |
| A customer's schematic used as "a typical example" with names removed        | EXCLUDE                                         | §2.1 — tenancy, before any licence question                                      |
| A paragraph SOL wrote in a customer conversation that a reviewer liked       | EXCLUDE                                         | §2.1 — generated in a customer context; redraft from sources as `solus_authored` |
| A chunk drafted by an LLM, sources listed, reviewer verified every claim     | SHIP                                            | §4.1 with `llm_assisted`, verbatim check passed                                  |
| The same draft where one claim could not be sourced                          | SHIP after the claim is removed                 | §4.12                                                                            |
| Solus engineer's own explanation of PID anti-windup written from experience  | SHIP                                            | §4.1; cites what it was checked against                                          |

If a candidate does not resolve from this table and §2, the reviewer records it as EXCLUDE and
opens a policy question. The default is exclusion, and that default is the policy.
