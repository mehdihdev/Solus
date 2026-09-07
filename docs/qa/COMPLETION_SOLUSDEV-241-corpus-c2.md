# Completion report — CORPUS C2: retrievable and measurable (SOLUSDEV-241)

**Branch:** `SOLUSDEV-244-home-h3-root-preferences` (shared with HOME H3/H4 and STORE ST3/ST4 by
instruction) · **Commits:** `6f7de44` (ADR-036), `10f6680` (pipeline), `60fc38d` (content + eval +
docs), plus the review-fix commit that follows this report. **Run for real:** yes (below).

## What was built

- **ADR-036** (DECISIONS.md, human-approved in-chat): a global long-prose table under extended
  ADR-033 containment.
- **Contract** `corpus/contract.py`: the Pydantic chunk with all 16 `corpus-chunk.md` §5 rules,
  NFKC normalisation, content hash; closed vocabularies in `corpus/enums.py` (41 topics bound to
  5 domains, rule-1 class→licence/derivation tables); per-class rights-holder host allowlist
  `corpus/hosts.py`.
- **Chunker** `corpus/chunking.py`: TOML-front-matter Markdown → chunks; splits at `##`, never
  inside a table or fence; packs oversize sections block-wise; cross-chunk rules; manifest.
  Authoring guide `docs/corpus/AUTHORING.md`.
- **Storage** `corpus/schema.py` + migration `a9c0d1e2f3b4` (chained after ST3/ST4's
  `e1f2a3b4c5d6`): `corpus_chunk` (natural-key id, HNSW on `embedding`), `corpus_citation`,
  `corpus_release`. Registered via `migrations/env.py`; `models.py` untouched.
- **Ingest** `corpus/ingest.py` — the only write path (tripwire test): manifest check, upsert by
  id, withdraw dropped ids (rule 10), best-effort unmetered embedding, release row. CLI
  `python -m solus_api.corpus {validate,manifest,ingest}`; Makefile `corpus-validate/ingest/eval`;
  Docker entrypoint runs ingest after migrations (non-blocking on failure).
- **Retrieval** `corpus/retrieval.py`: status/domain/topic/applicability as WHERE clauses; ANN or
  English full-text; `low_confidence` (< 0.6) marked, never dropped or promoted. Deterministic
  domain router `corpus/domains.py`. `rag/retrieval.py` serves `corpus` as a **global** source
  type through the existing SYS-02 `rag_query` seam; tenant types keep their in-query
  `project_id` refusal.
- **Context** `agent/context.py`: corpus sections (`kind=context_corpus`) pack after every tenant
  hit and are cut first under budget; optional `mode` orders ties (Guide→fundamentals,
  Expert→reference). Layering: preferences (system prompt) > project/tenant context > corpus.
- **Routes** `/api/v1/corpus/{manifest,search,chunks/{id}}` (`docs/api/corpus.md`, tier-1
  amendment): authenticated, read-only, full-text only over HTTP, drafts invisible, review
  metadata never on the wire.
- **Content v0.1.0**: 102 chunks across 40 topics (electrical 34, mechanical 23, robotics 16,
  software 15, systems 14); every P0 topic meets SCOPE §3's minimum. All `solus_authored`,
  `llm_assisted`, `reviewer = mhussain`, `status = active` per the gate decision.
- **Eval**: 89 questions (`tests/fixtures/corpus_eval/*.json`), run in the existing CI pytest
  job on the keyless full-text path. Results: **hit@5 1.000, answer support 0.989, domain purity
  1.000** (thresholds 0.90 / 0.85 / 1.00). Model-judged answer correctness is
  `tests/corpus/test_corpus_eval_live.py` under `-m live` (not run: no live key in this session).
- Docs: `docs/architecture/engineering-corpus.md` (new), `SCOPE.md` §8 and `corpus-chunk.md` §9
  open items resolved, `docs/api/corpus.md`, `COWORK_QA_corpus-c2.md`.

## Governing docs consulted

ADR-033/034/036, ADR-016, ADR-026 (deterministic gating), `docs/corpus/SCOPE.md`,
`docs/corpus/LICENSING.md`, `docs/schemas/corpus-chunk.md`, `docs/contracts/tool-knowledge.md`,
`docs/contracts/local-state.md` (preferences), `agent/prompt.py`, `rag/retrieval.py`,
`toolkb/schema.py` + `guard.py` (the global-table precedent). `docs/design/SPEC.md` and
`docs/design/screens/` do not exist in this repository (noted once, as in C1).

## Run for real

Local API (`uvicorn`, dev database migrated to head, `corpus ingest` applied: 102 inserted,
embedded 0 — no OpenAI key seeded, degraded to full-text as designed):

- `GET /corpus/manifest` → 0.1.0, 102 chunks. Search with `domain=electrical` on a question
  containing "clearance tolerance" returned only electrical ids; `domain=mechanical` on the same
  question returned only mechanical ids. Chunk view carries provenance and no review metadata;
  unknown id 404; no auth 401.
- **Live SOL turn (Anthropic key from the SecretStore)**: "wire for a 10 A motor run, 1.5 m each
  way" → `context_used` listed graph + five `corpus` sections; the answer recommended 14–16 AWG
  with the drop calculation and cited four chunk ids verbatim.
- **Override turn**: same question with `MessageCreate.preferences.electrical` = "every motor run
  uses 12 AWG silicone and XT60 only" → SOL recommended 12 AWG / XT60, stated that the drop
  budget alone would give 14–16 AWG and that the house rule is why it departs, and still cited
  the same chunks. **Acceptance 3 (preference overrides a corpus default end to end) holds.**

## Verification

- `tests/corpus/` (8 modules, 195 tests) + `test_context.py`, `test_reason.py`,
  `test_reason_eval.py`, `test_retrieval.py`, `test_feeds.py`, `test_sol_red_team.py`: 301
  passed on a private test database. ruff and mypy clean on every touched module.
- Coverage of `solus_api.corpus` measured with an ephemeral `pytest-cov` (numbers in the
  handoff message; `pytest-cov` is not a repo dependency).
- Phase 4 review and security subagents were launched twice and both died on the account's
  spend limit (HTTP 429). **The review was done in-line by the orchestrator instead**; findings
  and fixes are in the next section. A second-human review at the MR is still owed.

## In-line review findings (fixed)

1. **Unmetered embedding exposed over HTTP** (§7 cost control): `/corpus/search` embedded every
   caller-supplied `q` through the Solus-paid seam. Fixed: HTTP search is full-text only; SOL's
   own pull (admission-capped) keeps ANN. `docs/api/corpus.md` updated.
2. `hosts.py`: stray `iso20022.org` removed; the deliberately broad hosts (`github.com`,
   `gitlab.com`, `.readthedocs.io`, `.mil`) documented as a net under the reviewer, per
   LICENSING.md §4.8/§4.2 (licence per repository/document, not per host).
3. `schema.py`: dead import hack removed.
4. Two pre-existing test doubles asserted that every `rag_query` carries a `project_id`; they
   now exempt the one global corpus pull and assert it carries NONE (tenant assertions intact).

Checked and left as is: `to_tsquery` input is `[a-z0-9]+` terms joined by `|`, capped at 32 —
no operator injection; applicability values are server-built from closed enums; the semantic
cache bypasses unscoped (corpus) pulls, so tenant and corpus results never share a bucket;
`chunk_id:path` goes to a parameterised primary-key lookup; nothing logs bodies; the
confirmation_refusal gate, never-raises tool invariant, fingerprint posture and tool-knowledge
boundary are untouched.

## Decisions under delegated judgment

- Corpus is a **separate context section kind** rather than merged into `document` hits: ANN and
  full-text scores are not comparable across lists, and the ticket's layering requires tenant
  context to win structurally, not by score.
- Domain routing is a **Solus-authored lexicon** (no model call, ADR-026 pattern), tuned so a
  domain is searched alone only on clear evidence; contested vocabulary searches every scoring
  domain. The eval's router-precision test guards it.
- `revised_in` of a withdrawn chunk becomes the withdrawing release; provenance is kept for
  auditability (rule 10 clarified in the schema doc).
- Content shipped as **active** with `reviewer = mhussain` per the gate answer: the MR review of
  the content files is the LICENSING.md §6 review. Every writer's report of hedged claims and
  least-certain sources is preserved below for that review.

## Content notes for the human reviewer (from the five writers)

- **Electrical (34):** IPC/IEC named, no table values; numeric claims limited to NXP UM10204
  I2C limits, AWG geometry, CAN/USB termination, cell voltages, 1 oz ≈ 35 µm, SNR formula,
  common I2C addresses. Least-certain citation titles: TI SLVA139/SCEA035/SLYT499/SLOA034
  (identifiers left blank), Molex crimp handbook, Murata/KEMET generic entries. Connector
  ceilings hedged at 0.75.
- **Mechanical (23):** K ≈ 0.2 nut factor and ±25 % torque scatter (NASA RP-1228/STD-5020),
  E and yield for 6061/7075/steel, printed-plastic Tg values at 0.7 with TDS caveat. Confirm
  DIN 6935 title; McMaster-Carr cited as a source for heat-set inserts (a distributor).
- **Software (15):** JetPack↔CUDA at major-line granularity only; STM32 RDP2 "designed to be
  permanent"; Arduino CLI docs cited at the arduino.cc root.
- **Systems (14):** safety chunks are vocabulary only with an explicit non-compliance line; no
  PFH, θJA, IP test values. NVIDIA thermal guides cited as a family; NPR 7123.1 without revision.
- **Robotics (16):** maxon selection guidance title generic; Bosch BMI088/BMI270 datasheet
  choice to confirm.
- Left thin on purpose (empty beats invented): mechanisms reference values, locomotion_basics
  (P2), DMA/fixed-point/launch conventions sub-items, shaft misalignment.

## Deviations and flags

1. **Phase 4 subagent reviews did not run** (spend limit). In-line review substituted; flagged
   for the MR reviewer.
2. `docs/api/API.md` index row for §2.18 is owed — the file belongs to the ST3/ST4 session; asked
   them to add it.
3. `CLAUDE.md` §3 map still lacks `docs/corpus/` (tier-2; C1's suggested line stands) and could
   list `packages/api/src/solus_api/corpus/`.
4. **Values you must set:** none new. Production embeddings require `openai_api_key` in the
   SecretStore (already the SOL requirement); without it the corpus serves on full-text.
   `SOLUS_CORPUS_INGEST_TIMEOUT_SECONDS` (default 300) is optional.
5. Shared-branch hygiene incident: one `git commit --amend` of mine landed on the H3 session's
   commit (`58591c5` → `1eb594a`, one blank-line prettier fix in DECISIONS.md); the peer
   verified content intact. No history a human had seen was rewritten; nothing pushed.
6. The live eval (`-m live`) has not been executed; the deterministic proxies are what CI gates.
7. `.solus/project.toml` applicability keys still have no live source; the filter exists, every
   chunk applies regardless at v1 (SCOPE §8).
