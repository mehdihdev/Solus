"""SOL reasoning↔systems interface contract (SOLUS-W0-07).

The COMPLETE list of what the REASONING layer (context construction, orchestration) can ask of
the SYSTEMS layer (stored/retrievable data access + the flywheel write-back). Reasoning depends
ONLY on `SolSystems` and these shapes — NEVER on systems internals; systems provides a concrete
impl (`agent/feeds.py`). Locking this seam lets both halves be built in parallel and meet at the
Protocol (mock-and-swap; the canned double lives in the test fixtures).

Boundary:
- Systems serves STORED context (graph, telemetry, errors, RAG). Reasoning COMBINES that with the
  LIVE context it already holds (the prompt/conversation, tool I/O via the W0-04 tool interface)
  and DERIVES the anchors/scope it passes into these methods. This interface never sees the prompt.
- TOOLS (W0-04 `agent.tools`) and MODEL ROUTING (W0-03 `orchestration`) are SEPARATE interfaces,
  NOT duplicated here. This contract is reasoning↔systems DATA access + the flywheel write-back.
- `ArtifactRef` (W0-04) and `SourceRef` (W0-06) are REUSED as-is, never redefined.

Security (CLAUDE.md §7):
- TENANT SCOPING is the SYSTEMS impl's job and the highest-severity invariant. Reasoning MUST pass
  the authenticated request's project scope: `project_id` on the three methods that carry it, and
  `RetrievalFilter.project_id` on `get_error_history`/`rag_query` whenever they touch TENANT source
  types (`error`, `entity`). An ABSENT `project_id` is valid ONLY for genuinely-GLOBAL corpora (e.g.
  shared `datasheet`s) — never tenant data. Systems enforces this; the real impl's conformance suite
  MUST include a cross-tenant isolation case (write under team A, read under team B returns none of
  A's data). `project_id` is derived from the authenticated request, NEVER from ingested content.
- UNTRUSTED DATA: string fields that carry ingested or model-generated content — `EntityRead.name`/
  `attrs`, `TelemetryWindowSummary.summary`/`anomalies`, the `TelemetryWindowSummary.signals` KEYS
  (device-authored signal names, verbatim off the LB-06 wire: up to 256 per packet at 128 chars
  each), `RagHit.chunk`, `ErrorHit.solution_text` —
  are attacker-influenceable ("ignore previous instructions…" in a CAD part name or a recorded fix).
  The reasoning layer MUST wrap them as delimited DATA in prompt assembly, never emit them as
  instructions. The flywheel does not launder trust: a model-generated `solution_text` recorded via
  `record_error_solution` returns later as `ErrorHit.solution_text` and stays untrusted.
"""

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from solus_api.agent.tools import ArtifactRef
from solus_api.fingerprint.contract import SourceRef

# --------------------------------------------------------------------- graph context


class GraphScope(BaseModel):
    """Anchored + degree traversal. Reasoning derives the anchors from its broader live context
    (what's active in the prompt / the tool the user is in)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    anchor_entity_ids: list[UUID]  # the entities to traverse from
    degree: int = Field(ge=0)  # how many hops to traverse (the 2-degree perf lever)
    kinds: list[str] | None = None  # optional filter by entity kind
    domains: list[str] | None = None  # optional filter by domain


class ContextBudget(BaseModel):
    """A sub-sampling constraint on a graph pull. Systems is free to sub-sample within it and set
    `GraphContext.truncated=True` — so SYS-05's token-budgeted sub-sampling fits behind this
    contract without a signature change (the params were always here)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_entities: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)


class EntityRead(BaseModel):
    """A serializable, model-consumable read of `graph_entity` — deliberately OMITS the embedding
    (a 1536-float vector is noise in the reasoning context, not signal). `from_attributes` so
    systems can build it straight from an ORM row."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    kind: str
    domain: str
    name: str
    canonical_part_id: UUID | None = None
    source_connector: str | None = None
    external_ref: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)


class EdgeRead(BaseModel):
    """A serializable read of `graph_edge`. `domain_pair` is lowercase Domain values joined by
    `<->` (e.g. `code<->electrical`), matching `graph_edge.domain_pair`."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    src_id: UUID
    dst_id: UUID
    relation_type: str
    domain_pair: str
    confidence: float = Field(ge=0, le=1)
    attrs: dict[str, Any] = Field(default_factory=dict)


class GraphContext(BaseModel):
    """A serializable subgraph reasoning feeds to a model — NOT raw ORM objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entities: list[EntityRead]
    edges: list[EdgeRead]
    truncated: bool = False  # true if sub-sampled to fit the budget


# ------------------------------------------------------------------------- telemetry


class TelemetryWindow(BaseModel):
    """The time window to summarize, optionally narrowed to specific signals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    duration_seconds: float = Field(gt=0)
    signals: list[str] | None = None  # which components/signals (else all)


class TelemetryWindowSummary(BaseModel):
    """Systems BATCH-PROCESSES raw high-frequency telemetry into a windowed summary — reasoning
    sees a fuller picture per window (summarize windows, not instants). Raw data is REFERENCED
    (`raw_ref`) and fetched only if a step needs it (heavy data stays off the reasoning loop)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_start: datetime
    window_end: datetime
    summary: str  # what's happening in this window
    signals: dict[str, Any] = Field(default_factory=dict)  # per-signal compact stats/state
    anomalies: list[str] | None = None
    raw_ref: ArtifactRef | None = None  # reference to raw data for drill-in (W0-04 ArtifactRef)


class TelemetrySummaryView(BaseModel):
    """A SEQUENCE of window-summaries — a progression over time, not one static snapshot. The LIVE
    case (a continuous stream of `TelemetryWindowSummary` as windows complete) is a streaming
    EXTENSION built in the Live Bench real-time seam using this SAME shape — no contract change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    windows: list[TelemetryWindowSummary]


# ------------------------------------------------------------------------------ RAG


class RetrievalFilter(BaseModel):
    """Targeting for retrieval. `project_id` scopes to a tenant — systems enforces isolation, and
    reasoning MUST supply it whenever `source_types` includes TENANT data (`error`, `entity`). An
    ABSENT `project_id` is valid ONLY for genuinely-GLOBAL corpora (e.g. shared `datasheet`s), never
    tenant source types — see the module Security note."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID | None = None
    domains: list[str] | None = None
    source_types: list[str] | None = None  # e.g. error, datasheet, entity


class RagHit(BaseModel):
    """One semantic-retrieval hit. `source_ref` is PROVENANCE (what document/error/entity this
    chunk came from) so reasoning can cite/trace it — the reused W0-06 `SourceRef`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk: str  # the retrieved text
    source_ref: SourceRef  # provenance
    score: float  # relevance (higher = more relevant)


class ErrorHit(RagHit):
    """Error-scoped retrieval result — a `RagHit` that may also carry the recorded fix."""

    solution_text: str | None = None


# ------------------------------------------------------------------------- the interface


class SolSystems(Protocol):
    """The reasoning↔systems seam. Reasoning imports THIS (and the shapes above) and nothing else
    from systems. A concrete impl (`agent/feeds.py`) or a canned test double
    satisfies it structurally, verified by `systems: SolSystems = <impl>()` — mypy checks the
    method set, parameter TYPES/order/count, and return types. It does NOT check parameter NAMES
    for positional-or-keyword params; making these params keyword-only (a `*`) would enforce names
    too — a recommended hardening for the independent parallel build. No runtime registration."""

    async def get_graph_context(
        self,
        project_id: UUID,
        scope: GraphScope,
        budget: ContextBudget | None = None,
    ) -> GraphContext:
        """Anchored, degree-bounded, optionally kind/domain-filtered subgraph, sub-sampled to
        `budget` (systems sets `truncated` if it dropped anything). Serializable for a model."""
        ...

    async def get_telemetry(
        self,
        project_id: UUID,
        window: TelemetryWindow,
    ) -> TelemetrySummaryView:
        """A bounded, batch-summarized SEQUENCE of window-summaries — never raw streams."""
        ...

    async def get_error_history(
        self,
        query: str,
        k: int,
        filter: RetrievalFilter | None = None,
    ) -> list[ErrorHit]:
        """Error-scoped retrieval ("recall how we fixed this before") — top-`k`. `error_solution`
        rows are TENANT data: reasoning MUST pass `filter.project_id` (the request's project) and
        systems MUST scope to it — an unscoped call never crosses tenants (module Security note)."""
        ...

    async def rag_query(
        self,
        text: str,
        k: int,
        filter: RetrievalFilter | None = None,
    ) -> list[RagHit]:
        """Semantic retrieval over the pgvector store — top-`k`, optionally filtered/targeted. If
        `filter.source_types` includes TENANT data (`error`, `entity`), `filter.project_id` is
        REQUIRED; an unscoped query is restricted to GLOBAL corpora only (module Security note)."""
        ...

    async def record_error_solution(
        self,
        project_id: UUID,
        error_text: str,
        solution_text: str,
        domain: str,
        attrs: dict[str, Any] | None = None,
    ) -> UUID:
        """THE FLYWHEEL WRITE-BACK: persist a solved error so future retrieval recalls it. Returns
        the stored `error_solution` id."""
        ...
