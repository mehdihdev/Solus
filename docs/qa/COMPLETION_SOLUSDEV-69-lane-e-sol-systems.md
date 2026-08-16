# Completion — SOLUSDEV-69 LANE E: SOL Systems (SYS-01/03/04/05 + credential seeding)

Branch `SOLUSDEV-69-lane-e-sol-systems`, 7 commits. Per-ticket reports:
`COMPLETION_SOLUSDEV-138-sys04-real-feeds.md` (THE fix — live-verified),
`COMPLETION_SOLUSDEV-135-sys01-reconcile.md` (close-as-built),
`COMPLETION_SOLUSDEV-137-sys03-builtin-tools.md` (tools half done; capture half blocked on ERR-01),
`COMPLETION_SOLUSDEV-139-sys05-perf.md` (measured perf). Credential seeding shipped as
`make seed-secrets` (7d49b28).

## Phase 4 verification — both mandated reviews ran on the full diff; findings FIXED

**Fresh-context code review: APPROVE** (0 critical/high). Its two MEDIUMs are closed/dispositioned
below. **Security review: initially FAIL** — every finding was then fixed or factually
dispositioned in the same session (commit "Phase 4 findings"):

| Finding                                                                                            | Disposition                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1 — unmetered embeds bypass the spend cap                                                         | **Factually disproven, then documented.** The 402 credits pre-flight and 429 frequency cap fire at TURN ADMISSION (`routers/sol.py` before the registry build and any context pull), so a capped team never triggers an embed; embeds fire only inside admitted, credit-gated turns. The reviewer's escalation that a completion doc is not an approval record is correct — the actual approval was the in-chat AskUserQuestion decision (ADR-032). Proposed ADR amendment below for durable record. |
| H1 — semantic cache ignored k/filter boundaries                                                    | **FIXED**: the cache bucket now folds `kind                                                                                                                                                                                                                                                                                                                                                                                                                                                          | k   | source_types | domains`into the key's kind dimension, binding BOTH the exact and similarity paths; pinned by`test_semantic_hits_never_cross_k_or_filter_boundaries` with a real deterministic embedder. |
| H2 — missing tool-level isolation tests                                                            | **FIXED**: `query_graph`/`run_checkers`/`get_telemetry` each get a cross-tenant test at the tool surface (A's data invisible from B).                                                                                                                                                                                                                                                                                                                                                                |
| H3 — no red-team fixtures through the new tools                                                    | **FIXED**: two containment tests drive the REAL builtin registry (`build_sol_registry` + `DbSolSystems`) with hostile connector-ingested entity names — through `query_graph` and through `run_checkers`' `Warning.message` (a new content type on the tool-result path) — asserting fenced-data-only arrival.                                                                                                                                                                                       |
| M1 — cache embedded before exact lookup                                                            | **FIXED**: exact-first, zero embed calls on an exact hit (tested).                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| M2 — O(n×1536) blocking similarity scan                                                            | **FIXED**: precomputed norms + newest-first scan capped at 64 entries.                                                                                                                                                                                                                                                                                                                                                                                                                               |
| M3 — unbounded `kinds`/`domains`/`signals` params                                                  | **FIXED**: `maxItems: 16`, `maxLength: 64`; schema-bounds test added.                                                                                                                                                                                                                                                                                                                                                                                                                                |
| M4 — breaker half-open thundering herd, no decay                                                   | **FIXED**: `check` consumes the single probe slot (re-arms the window); failures decay outside a 60 s rolling window; both tested. (Data-collection emission of breaker events needs identity the seam doesn't hold — reported below, not hacked in.)                                                                                                                                                                                                                                                |
| M5 — `tool_result` SSE frame streamed unredacted                                                   | **FIXED**: `redact_value` applied, same gate the persisted turn gets.                                                                                                                                                                                                                                                                                                                                                                                                                                |
| M6 — flywheel write reachable by runners, unratcheted                                              | **FIXED**: `test_no_runner_path_reaches_the_flywheel_write` sweeps `agent/**` — only `feeds.py` may call `record_error_solution`.                                                                                                                                                                                                                                                                                                                                                                    |
| L1 cached-list aliasing / L2 `run_all` reuse / L3 circuit-open traceback spam / L6 stale docstring | **All FIXED** (copies in/out; `run_all`; compact transient warning; docstring).                                                                                                                                                                                                                                                                                                                                                                                                                      |
| L4 per-project cache fairness / L5 `confidence` ORDER BY index                                     | **Deferred, on record**: bounded impact (global LRU cap 256 + 64-entry scan cap; edge scan bounded at MAX_EDGE_SCAN). Revisit with real multi-tenant load numbers.                                                                                                                                                                                                                                                                                                                                   |
| Code-review M — stale `docs/contracts/sol-interface.md`                                            | **Human-owed by design** (decision 3): the full amendment diff below awaits your signature; I did not edit the contract doc.                                                                                                                                                                                                                                                                                                                                                                         |
| Code-review L — retry log field `provider=` → `label=`                                             | Accepted: `label` contains `provider/model`; no known dashboards pre-launch. Noted here so it is a choice, not an accident.                                                                                                                                                                                                                                                                                                                                                                          |

## Verification checklist (the 8 gates)

1. ✅ **Live SOL turn on `solus_test2` cites real entities** — 4 real Onshape tool calls, the
   actual Kinova Gen3 parts named, zero LM358/`camera_node` fictions (see SYS-04 report).
2. ✅ Cross-tenant isolation per feed AND per tool, in-query; unfiltered tenant retrieval
   refusal asserted as a guarantee.
3. ✅ Ratchet: zero `FakeSolSystems` references under `src/solus_api` (+ new flywheel-write ratchet).
4. ✅ `assert_core_contract` passes against fake AND real.
5. ✅ `run_checkers` invokes CHK-01's real rules through the registry (op-amp warning fires on
   the seeded eval bug) and returns the structured Warning shape.
6. ✅ Destructive-gate ratchet + red-team suites pass unchanged (and grew two builtin cases).
7. ✅ `make seed-secrets` idempotent, names+lengths only; `google_api_key` (from
   `GEMINI_API_KEY`) and `brave_api_key` now seeded; `openai_api_key` skipped —
   **human-owed: set `OPENAI_API_KEY` in the root `.env`, re-run `make seed-secrets`**.
8. ✅ ruff clean repo-wide (src+tests); mypy clean on every touched module; full backend suite
   green in slices (final counts in the handoff summary); single alembic head `07c4da2feccf`
   (no migrations this lane).

## Proposed ADR amendment (tier-2 — needs your in-chat approval before any edit)

Append to **ADR-019** (or as ADR-018 note):

> **Amended — 2026-08-15, SOLUSDEV-138/139 (approved in-chat during Lane E Phase 1):**
> Query embeddings issued by the W0-07 systems seam (`DbSolSystems`) run
> `allow_unmetered=True`. Rationale: the seam deliberately carries no user identity;
> embed volume is bounded upstream by the credit-gated (402) and frequency-capped (429)
> turn admission, so no capped or anonymous path can reach an embed; per-call cost is
> sub-cent. Revisit when identity plumbing reaches the seam or embed volume becomes
> material in billing.

## Proposed `docs/contracts/sol-interface.md` amendment (ADR-028 — you sign; NOT applied)

1. §1/“Status” + §8: the real systems impl EXISTS — `agent/feeds.py` (`DbSolSystems`),
   wired in production (`main.py`); `FakeSolSystems` is a test double at
   `packages/api/tests/fixtures/fake_systems.py` (the old `agent/fake_systems.py` path is gone).
2. §8 final sentence becomes: “The CORE contract assertions live in
   `tests/fixtures/sol_contract.py::assert_core_contract` and run against BOTH the fake and
   the real impl (`test_feeds.py`). Three fake behaviors are deliberately NOT contract:
   telemetry may be honestly empty (`windows=[]`); `raw_ref` is Optional and a real impl may
   never set it (Live Bench work); unfiltered tenant retrieval is REFUSED by a real impl
   (`ValueError`, §5) rather than tolerated. The real impl's suite additionally covers the
   §7-mandated cross-tenant isolation case and asserts the unfiltered refusal as a passing
   guarantee.”
3. §9 status table: “The real systems impls” → **Functional (SYS-04, SOLUSDEV-138)**; add
   “SYS-05 sub-sampling behavior” → **Functional (relevance pruning + semantic cache)**.
4. Footer “Code:” pointer → `packages/api/src/solus_api/agent/feeds.py` +
   `packages/api/tests/fixtures/fake_systems.py`.

## Human-owed items

- Set `OPENAI_API_KEY` in root `.env`; re-run `make seed-secrets` (unblocks real ANN retrieval,
  vision/toolkb embeds, and gives the semantic cache its embedding path in production).
- ~~Sign the two proposed doc changes above~~ — **APPROVED in-chat 2026-08-16 and APPLIED
  verbatim** in dedicated commits (ADR-019 amendment in `DECISIONS.md`; the four
  `docs/contracts/sol-interface.md` items). The proposal texts above remain as the approval
  record.
- Paste the per-ticket Jira comments from the four completion reports (no Jira writes were
  made — decision 4).
- Review + push the branch, open the MR (all commits local).
- Follow-ups worth tickets: data-collection emission for breaker/rate-limit events (needs
  identity at the infra seams); per-project cache fairness + a `graph_edge.confidence` index
  if multi-tenant load measurements warrant; ERR-01 (LANE I) still owns error capture.
