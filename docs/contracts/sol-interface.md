# SOL Reasoning↔Systems Interface — Design Contract (SOLUS-W0-07)

**Status:** Design contract + Protocol + conformance suite — and the REAL systems impl is SHIPPED
(SYS-04, SOLUSDEV-138): `agent/feeds.py` (`DbSolSystems`), wired in production (`main.py`).
`FakeSolSystems` is a test double at `packages/api/tests/fixtures/fake_systems.py` (the old
`agent/fake_systems.py` path is gone; a ratchet keeps it out of `src/`). The telemetry streaming
transport (Live Bench) remains a separate ticket.
**Authority:** ADR-028 (Week-0 human-owned contract), ADR-027 + `models.py` (graph/error shapes),
ADR-026 (model routing — a SEPARATE interface), ADR-010 (SOL is an orchestrator). Reuses W0-01
(`graph_entity`/`graph_edge`/`error_solution`), W0-04 (`ArtifactRef`; the tool interface is separate),
W0-06 (`SourceRef` as provenance). Code: `packages/api/src/solus_api/agent/interfaces.py`.

Consumers — **the mock-and-swap seam, now swapped.** This is the second critical coordination seam
splitting SOL. Reasoning (Pratham — context construction, orchestration) imports ONLY `SolSystems` +
these shapes; it was built against the fake and now runs against the real impl (`DbSolSystems`)
behind the SAME Protocol — the swap happened with no change to reasoning, which is the seam's proof.
The interface is the COMPLETE list of what reasoning can ask of systems — nothing reasoning needs is
missing, and no systems internals leak.

---

## 1. Purpose & boundary

The reasoning layer assembles context and orchestrates; the systems layer provides stored/retrievable
data and execution. `SolSystems` is the ONLY thing reasoning depends on from systems.

- **Reasoning's context is BROADER than what systems provides.** Systems serves STORED/retrievable
  context (graph, telemetry, errors, RAG). Reasoning COMBINES that with the LIVE interaction context it
  already holds — the prompt/conversation, and data flowing in/out of integrated tools via the W0-04
  tool interface. This interface never sees the prompt: reasoning DERIVES the scope/anchors it passes in
  (e.g. the anchor entities for a graph pull come from what's active in the prompt or the tool the user
  is in). Systems serves stored context; reasoning targets the pulls using its broader live context.
- **Tools and routing are SEPARATE interfaces, not duplicated here.** Reasoning invokes capabilities
  through the W0-04 tool registry (`agent.tools`) and picks models through the W0-03 router
  (`orchestration`). This contract is specifically reasoning↔systems DATA access + the flywheel
  write-back.
- **`ArtifactRef` (W0-04) and `SourceRef` (W0-06) are REUSED, never redefined.**

---

## 2. The `SolSystems` Protocol — the complete ask-list

Async Python `Protocol` (structural — mypy verifies an impl satisfies it; there is no runtime
registration). One Protocol carries the whole surface reasoning can ask for:

```python
class SolSystems(Protocol):
    async def get_graph_context(self, project_id, scope, budget=None) -> GraphContext: ...
    async def get_telemetry(self, project_id, window) -> TelemetrySummaryView: ...
    async def get_error_history(self, query, k, filter=None) -> list[ErrorHit]: ...
    async def rag_query(self, text, k, filter=None) -> list[RagHit]: ...
    async def record_error_solution(self, project_id, error_text, solution_text, domain,
                                     attrs=None) -> UUID: ...
```

---

## 3. `get_graph_context` — anchored + degree traversal, with the SYS-05 sub-sampling hook

`scope` is an **anchored traversal**: from `anchor_entity_ids`, out `degree` hops, optionally filtered
by `kinds`/`domains`. Reasoning derives the anchors from its broader live context. The result is a
**serializable subgraph** (`EntityRead`/`EdgeRead`, NOT raw ORM objects) reasoning feeds to a model —
`EntityRead` deliberately **omits the embedding** (a 1536-float vector is noise in the reasoning
context).

| shape           | fields                                                                                               |
| --------------- | ---------------------------------------------------------------------------------------------------- |
| `GraphScope`    | `anchor_entity_ids: list[UUID]`, `degree: int (≥0)`, `kinds?`, `domains?`                            |
| `ContextBudget` | `max_entities?`, `max_tokens?` (both `>0`)                                                           |
| `EntityRead`    | `id, kind, domain, name, canonical_part_id?, source_connector?, external_ref?, attrs` (no embedding) |
| `EdgeRead`      | `src_id, dst_id, relation_type, domain_pair, confidence, attrs`                                      |
| `GraphContext`  | `entities, edges, truncated: bool`                                                                   |

**SYS-05 sub-sampling hook (perf work fits behind the contract).** The request carries the constraints
(`degree` + `budget`); **systems is free to sub-sample within them and set `truncated=True`**. When
SYS-05 optimizes sub-sampling (2-degree, token-budgeted), the INTERFACE does not change — the params
were always here. That is how the perf work fits behind the contract.

---

## 4. `get_telemetry` — a bounded, batch-summarized window SEQUENCE (not raw streams)

Telemetry is high-volume; reasoning gets BOUNDED, BATCH-SUMMARIZED views, NOT raw high-frequency
streams (the edge-observer principle — heavy data stays out of the reasoning loop). Systems
BATCH-PROCESSES raw telemetry into windowed summaries so reasoning sees a fuller picture per window
(summarize windows, not instants) and a PROGRESSION across windows (a sequence of summaries), not one
snapshot. Raw data is REFERENCED (`raw_ref: ArtifactRef`) and fetched only if a step needs the bytes.

| shape                    | fields                                                                          |
| ------------------------ | ------------------------------------------------------------------------------- |
| `TelemetryWindow`        | `duration_seconds (>0)`, `signals?`                                             |
| `TelemetryWindowSummary` | `window_start, window_end, summary, signals, anomalies?, raw_ref: ArtifactRef?` |
| `TelemetrySummaryView`   | `windows: list[TelemetryWindowSummary]` (the progression)                       |

**Streaming extension (designed-for, NOT built here).** The LIVE case — a continuous stream of
`TelemetryWindowSummary` with real-time updates as windows complete — is a STREAMING EXTENSION of this
interface (reasoning subscribes, receives successive window-summaries). The streaming TRANSPORT
(subscription mechanism) is part of the REAL-TIME SEAM / Live Bench and is built THERE, using the SAME
`TelemetryWindowSummary` shape. This contract defines the summary shape + the request-response form now;
the continuous delivery drops in later WITHOUT a contract change. This ticket does not build the
subscription.

---

## 5. RAG — semantic retrieval + the distinct error-scoped capability

`rag_query(text, k, filter?)` does semantic retrieval over the pgvector store, optionally
filtered/targeted. `get_error_history(query, k, filter?)` is the distinctly-named error-scoped version
("recall how we fixed this before") — implemented as error-scoped retrieval underneath but exposed as
its own capability for clarity.

| shape              | fields                                                                                      |
| ------------------ | ------------------------------------------------------------------------------------------- |
| `RetrievalFilter`  | `project_id?`, `domains?`, `source_types?` (e.g. error, datasheet, entity)                  |
| `RagHit`           | `chunk: str`, `source_ref: SourceRef` (provenance), `score: float` (higher = more relevant) |
| `ErrorHit(RagHit)` | `+ solution_text: str?`                                                                     |

**Provenance:** `source_ref` is the reused W0-06 `SourceRef` — it tells reasoning what document/error/
entity a chunk came from, so it can cite/trace it. `SourceRef` enforces resolvability at construction
(a `graph_entity_id`, or `source_connector` + `external_ref`), so every hit is traceable.

**Tenant scoping (CLAUDE.md §7 — the highest-severity invariant).** `error_solution` rows and
`entity` chunks are TENANT data. **Systems enforces isolation**, and reasoning MUST pass
`filter.project_id` (the authenticated request's project) whenever `get_error_history`/`rag_query`
touch tenant `source_types` (`error`, `entity`). An absent `project_id` is valid **ONLY** for
genuinely-GLOBAL corpora (e.g. shared `datasheet`s) — never tenant source types. This is a binding
invariant, not a convenience: a tenant-`source_types` query with no `project_id` must be rejected or
scoped, never served cross-tenant. `project_id` is derived from the authenticated request, never from
ingested content.

> The ticket's signature keeps `project_id` optional (via `filter`) on these two retrieval methods —
> unlike the three methods that take a mandatory `project_id` — so the invariant above is upheld by
> documentation + the conformance requirement below, not by the type. The real systems impl's
> conformance suite **MUST** include a cross-tenant isolation case (write under team A, read under
> team B returns none of A's data); the `FakeSolSystems` is exempt (it ignores `project_id`).

**Untrusted content (CLAUDE.md §7 — prompt injection).** `RagHit.chunk`, `ErrorHit.solution_text`,
`EntityRead.name`/`attrs`, and `TelemetryWindowSummary.summary`/`anomalies` carry ingested OR
model-generated text that is attacker-influenceable (an "ignore previous instructions…" payload in a
CAD part name, a code comment, or a recorded fix). The reasoning layer MUST wrap these as delimited
DATA in prompt assembly, never emit them as instructions. The flywheel does not launder trust: a
model-generated `solution_text` recorded via `record_error_solution` returns later as
`ErrorHit.solution_text` and stays untrusted.

---

## 6. The flywheel write-back — `record_error_solution`

`record_error_solution(project_id, error_text, solution_text, domain, attrs?) -> UUID` persists a solved
error to `error_solution` so future retrieval (`get_error_history`) recalls it — the data flywheel
(ADR-011). It is the one WRITE reasoning makes through this interface; it returns the stored id.

---

## 7. Reused shapes & separate interfaces

- **Reused, not redefined:** `ArtifactRef` (`solus_api.agent.tools`, W0-04) for `raw_ref`; `SourceRef`
  (`solus_api.fingerprint.contract`, W0-06) for RAG provenance.
- **Separate interfaces (not here):** the tool-call shape (`ToolCall`/`ToolResult`, W0-04) — reasoning
  invokes tools via the tool registry; and model routing (`route()`, W0-03) — reasoning picks models via
  the router. A tool or the router is not reachable through `SolSystems`, and vice versa.

---

## 8. Mechanism — Protocol + `FakeSolSystems` (mock-and-swap)

`SolSystems` is a plain `Protocol`; an impl satisfies it structurally, proven by a
`systems: SolSystems = FakeSolSystems()` assignment (stronger than a runtime `isinstance`). mypy
checks the method set, parameter TYPES/order/count, and return types — but NOT parameter NAMES for
positional-or-keyword params, so an independent real impl that renames a param (`filter`→`filters`)
would pass mypy yet break at the first keyword call site. **Recommended hardening:** make the Protocol
params keyword-only (`*`) so mypy enforces names too. `FakeSolSystems` returns deterministic canned
data covering every corner (budget
sub-sampling with `truncated`, a telemetry window sequence with a `raw_ref`, resolvable `SourceRef`
provenance, a recorded id) — corners real data rarely hits, which is why it stays valuable as a test
double. The CORE contract assertions live in `tests/fixtures/sol_contract.py::assert_core_contract`
and run against BOTH the fake and the real impl (`test_feeds.py`). Three fake behaviors are
deliberately NOT contract: telemetry may be honestly empty (`windows=[]`); `raw_ref` is Optional and
a real impl may never set it (Live Bench work); unfiltered tenant retrieval is REFUSED by a real
impl (`ValueError`, §5) rather than tolerated. The real impl's suite additionally covers the
§7-mandated cross-tenant isolation case and asserts the unfiltered refusal as a passing guarantee.

---

## 9. Functional vs. future in W0-07

| Component                                       | W0-07 status                                                 |
| ----------------------------------------------- | ------------------------------------------------------------ |
| `SolSystems` Protocol + all shapes              | **Functional**                                               |
| `FakeSolSystems` + conformance test             | **Functional**                                               |
| SYS-05 budget/degree sub-sampling (`truncated`) | **Functional (SYS-05 — relevance pruning + semantic cache)** |
| Telemetry streaming (stream-of-summaries)       | **Same-shape extension — Live Bench, not built**             |
| The real systems impls                          | **Functional (SYS-04, SOLUSDEV-138)**                        |
| The reasoning layer                             | **Pratham's SOL reasoning tickets**                          |
| The RAG / pgvector wiring                       | **Downstream**                                               |

---

**Cross-references:** ADR-028 (human-owned), ADR-027 + `models.py` (`graph_entity`/`graph_edge`/
`error_solution`), ADR-026 (routing — separate, `orchestration`), ADR-010/011 (orchestrator + flywheel).
Reused: `ArtifactRef` (`agent/tools/shapes.py`, W0-04), `SourceRef` (`fingerprint/contract.py`, W0-06).
Code: `packages/api/src/solus_api/agent/interfaces.py`, `agent/feeds.py` (the real impl); test
double: `packages/api/tests/fixtures/fake_systems.py`. Separate interfaces:
`agent-tool.md` (W0-04 tools), `model-orchestration.md` (W0-03 routing). Sibling seam:
`fingerprint-output.md` (W0-06) — the other mock-and-swap contract.
