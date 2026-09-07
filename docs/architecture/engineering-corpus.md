# Engineering corpus — architecture (CORPUS C1/C2, ADR-036)

**Ticket:** SOLUSDEV-241 · **Status:** tier-1 (ADR-032), added with the C2 implementation.
**Authority:** ADR-036 (storage and containment), ADR-033 (the global-table precedent),
ADR-034 as amended 2026-09-06 (where preferences sit), ADR-016 (mode ranks, never filters),
`docs/corpus/SCOPE.md`, `docs/corpus/LICENSING.md`, `docs/schemas/corpus-chunk.md`,
`docs/api/corpus.md`.

## 1. What it is

The corpus is **what SOL ships knowing**: reviewer-signed engineering prose, identical for every
tenant, versioned as an asset of the product. It is content, not code: checkers still decide
whether a design is wrong; the corpus is what SOL reaches for to explain why and to cite.

```
 authored Markdown ──► chunker ──► contract ──► manifest ──► ingest ──► corpus_chunk ──► retrieval ──► context ──► prompt
 (content tree)        (§3)        (16 rules)   (§8)       (only      (pgvector,     (SQL filters, (kind=       (fenced
                                                            writer)    typed cols)    ANN/FTS)      context_corpus) data)
```

## 2. Components (all under `packages/api/src/solus_api/corpus/`)

| Module         | Role                                                                                                                                                                                           |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `content/`     | The shipped tree: `corpus.toml` (release), `manifest.json` (generated), `<domain>/<topic>/<slug>.md`. Packaged with the API wheel and the Docker image.                                        |
| `enums.py`     | Every closed vocabulary (domains, 41 topics bound to domains, kinds, audiences, applicability keys and values, source classes, licences, statuses); the rule-1 class→licence/derivation tables |
| `hosts.py`     | Per-source-class rights-holder host allowlist (rules 7 and 14)                                                                                                                                 |
| `contract.py`  | `CorpusChunk` — the Pydantic contract with all sixteen schema rules and the content hash                                                                                                       |
| `chunking.py`  | TOML-front-matter Markdown → chunks; splits at `##`, never inside a table or fence; cross-chunk rules; manifest                                                                                |
| `schema.py`    | ORM: `corpus_chunk` (natural-key id), `corpus_citation` (typed child), `corpus_release`                                                                                                        |
| `ingest.py`    | **The only write path.** Validates tree ↔ manifest, upserts by id, withdraws dropped ids, embeds best-effort, records the release                                                             |
| `domains.py`   | Deterministic domain router for free-text questions (Solus-authored lexicon, precision-first)                                                                                                  |
| `retrieval.py` | `corpus_hits`: SQL filters (status, domain, topic, applicability) then ANN or English full-text; `CorpusHit`                                                                                   |
| `router.py`    | `/api/v1/corpus` read-only routes                                                                                                                                                              |
| `__main__.py`  | `validate`, `manifest [--check]`, `ingest` CLI                                                                                                                                                 |

Touch points outside the package: `rag/retrieval.py` serves `corpus` as a **global** source type
through the SYS-02 `rag_query` seam (tenant types keep their in-query `project_id` refusal);
`agent/context.py` pulls it and packs it; `migrations/versions/a9c0d1e2f3b4_*` creates the
tables; `main.py` mounts the router and shares SOL's unmetered embed seam for search.

## 3. Containment (why a global prose table is safe)

1. **Nowhere to put a tenant.** No `project_id`/`team_id`/`user_id` column, no FK to those
   tables, no JSONB, no free-form field. The tables' column sets are asserted in
   `tests/corpus/test_corpus_ingest.py`.
2. **Closed vocabularies.** Every categorical field is an enum; `source_class` has no customer,
   community, model, or other value, so EXCLUDE-class content is unrepresentable.
3. **One writer.** `ingest.py` reads only the committed tree; a tripwire test fails the suite if
   `CorpusChunkRow(` is constructed anywhere else in `src/`. There is no HTTP write route.
4. **Human review gates serving.** A chunk without a reviewer is `draft`; `draft` never serves,
   over HTTP or to SOL. The model is never the reviewer (rule 8).
5. **Data, not instructions.** A chunk enters a prompt only as a nonce-fenced
   `kind=context_corpus` block through `agent/prompt.py`; red-team fixtures assert a hostile body
   cannot escape its fence or forge a citation.

## 4. Layering in a SOL turn

```
 system prompt   Solus instructions → mode note → [engineering_preferences fenced] → … (ADR-034 amendment; HOME H3)
 context         graph floor → telemetry → tenant hits (errors, documents) → corpus hits (context_corpus)
```

The user's root preferences (free text) sit in the system prompt above everything; project
`.solus` context and tenant retrieval pack first; corpus chunks pack last and are cut first under
budget. The framing note in `prompt.py` tells SOL the person's conventions override shipped
references. Nothing from the corpus is ever interpolated into instruction text.

## 5. Retrieval

- **Route.** `route_domains(question)` scores Solus-authored lexicon hits per domain. A domain is
  searched alone only when it clearly leads; mixed vocabulary searches several domains; no
  vocabulary searches all. It never spends a model call (ADR-026 pattern).
- **Filter.** `status = active`, `domain ∈ …`, `topic ∈ …`, applicability (a chunk is excluded
  only when tagged with a _different_ value for a supplied key) — all WHERE clauses.
- **Rank.** Cosine ANN over the HNSW-indexed embedding when a query vector exists; OR-semantics
  English full-text (`ts_rank_cd`) otherwise. Scores are comparable within one list only.
- **Mark.** `confidence < 0.6` ⇒ `low_confidence`, rendered as a line in the section. Never
  dropped, never promoted.
- **Mode.** Guide prefers `fundamentals`, Expert prefers `reference` — as a tiebreak on equal
  relevance (ADR-016).

## 6. Versioning and migration path

`content/corpus.toml` names the release; `manifest.json` lists every chunk id with its content
hash and status and is regenerated by `python -m solus_api.corpus manifest` (CI fails when
stale). Ingest is idempotent: new ids insert, changed hashes update in place, ids absent from a
newer manifest are marked `withdrawn` (id and title kept so past citations resolve; body,
links, and embedding cleared). Every applied version is a `corpus_release` row, exposed at
`GET /api/v1/corpus/manifest`. A rights-holder takedown is therefore a content change plus a
version bump plus an ingest — never a row delete.

## 7. Measurement

`tests/corpus/test_corpus_eval.py` ingests the shipped tree into the test database and scores
89 questions (`tests/fixtures/corpus_eval/<domain>.json`) on the keyless path CI runs:
hit@5 ≥ 0.90, domain purity = 1.00 for domain-filtered queries, answer support ≥ 0.85, plus a
router precision guard (a question is never sent alone to a wrong domain). The thresholds were
agreed at the Phase 1 gate on 2026-09-06. A model-judged answer-correctness run is the `-m live`
twin and never runs in CI.

## 8. Deployment

`alembic upgrade head` creates the tables; `python -m solus_api.corpus ingest` (or
`make corpus-ingest`) applies the packaged tree — run it after migrations in the same deploy
step. Without an embedding key the corpus serves on full-text; a later `ingest` backfills vectors
without touching text. No environment variable is specific to the corpus.
