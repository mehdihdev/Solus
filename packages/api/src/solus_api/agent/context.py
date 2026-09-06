# SOLUSDEV-129 (SOL-01) — context construction: the AI-engineering core of SOL.
#
# build_context assembles the reasoning context for one query by pulling graph,
# telemetry, error history, and documents through the W0-07 `SolSystems`
# Protocol ONLY — never systems internals. The real feeds (`agent/feeds.py`,
# SYS-04) sit behind the same calls; the seam is the design, and doubles slot
# in behind it for tests with no change here.
#
# Properties the tests pin:
# - RANKED, not dumped: retrieval hits from every feed interleave by score,
#   packed under the budget with a STRICT relevance cutoff — the first hit
#   that does not fit ends packing; a less relevant hit never sneaks in on
#   size alone.
# - DEDUPED: the same chunk retrieved by two feeds appears once (the
#   error-feed copy wins — it carries the recorded fix).
# - BOUNDED: every untrusted field is capped before rendering, and the whole
#   context never exceeds `ContextBudget.max_tokens` — ingested content sets
#   neither the token bill nor which legitimate hits survive (§7 / ADR-019).
# - DETERMINISTIC + INSPECTABLE: same inputs → same sections; every cut —
#   ranked hit, telemetry window, or clipped graph floor — is recorded in
#   `dropped`, so "why did SOL reason this way" is answerable from the object.
# - ATTRIBUTED: every hit carries a `[connector:ref]` citation whose parts are
#   charset-restricted and capped — ingested provenance strings cannot forge
#   labels or extra citations.
# - REDACTED: entity attrs, chunks, fixes, and summaries pass the same
#   redaction gate as every other path into model context (bridge/frames).
#
# - LAYERED (CORPUS C2, ADR-036): the shipped engineering corpus is its own
#   section kind, retrieved through the same `rag_query` seam as a GLOBAL source
#   type (no tenant scope exists for it), domain-routed deterministically, and
#   packed AFTER every tenant hit — the team's own graph, errors, and documents
#   always outrank general knowledge, and the user's preferences sit above all
#   of it in the system prompt. Low-confidence chunks are marked, never dropped.
#
# The model-facing surface is `Context.fenced(nonce)`: each section rendered
# as its own nonce-fenced data block via agent/prompt.py. `render()` is the
# human/debugging view — a ratchet in the hardening tests keeps production
# code off it.

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from solus_api.agent import prompt
from solus_api.agent.interfaces import (
    ContextBudget,
    ErrorHit,
    GraphContext,
    GraphScope,
    RagHit,
    RetrievalFilter,
    SolSystems,
    TelemetrySummaryView,
    TelemetryWindow,
)
from solus_api.agent.tools.untrusted import redact_text, redact_value
from solus_api.corpus.domains import route_domains
from solus_api.corpus.enums import Audience
from solus_api.corpus.retrieval import CORPUS_CONNECTOR, CorpusHit
from solus_api.fingerprint.contract import SourceRef
from solus_api.models import SolMode

#: Cheap deterministic token estimate, same heuristic as the gateway's
#: type_estimator (len // chars_per_token). Kept local so context packing does
#: not depend on routing config; calibrate both if real usage shows drift.
_CHARS_PER_TOKEN = 4

#: How many retrieval hits to ask each feed for, and the hard cap on the knob
#: (a caller-plumbed k must not become a retrieval-amplification lever).
DEFAULT_K = 5
MAX_K = 20

#: Per-field caps on rendered untrusted content: a hostile ingested value must
#: not set the token bill or evict legitimate context (SEC-C2). Chunks are
#: retrieval-sized; names/attrs/summaries are labels and stats.
_CHUNK_CAP = 2000
_FIELD_CAP = 500
#: A corpus chunk is Solus-curated prose up to 6,000 chars; it gets more room
#: than an ingested snippet but still packs under the same budget.
_CORPUS_CAP = 4000
_LOW_CONFIDENCE_NOTE = "LOW CONFIDENCE — a rule of thumb; verify before relying on it"

#: Citation components are charset-restricted and capped (SEC-C1) — mirrors
#: tools/untrusted.SAFE_REMOTE_NAME. No `]`, whitespace, or newline can
#: survive, so ingested provenance cannot mint labels or extra citations.
_CITE_UNSAFE = re.compile(r"[^A-Za-z0-9._/#:-]")
_CITE_CAP = 128

SectionKind = Literal["graph", "telemetry", "error", "document", "corpus"]


class ContextSection(BaseModel):
    """One inspectable piece of the assembled context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: SectionKind
    text: str
    tokens: int
    #: Relevance for packing. Retrieval hits carry their retrieval score;
    #: graph/telemetry are scoped pulls, not ranked candidates (see packing).
    score: float
    citation: str | None = None


class Context(BaseModel):
    """The deterministic, inspectable reasoning context for one query."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    project_id: UUID
    sections: tuple[ContextSection, ...]
    #: Every cut, by citation/tag — ranked hits, telemetry windows, and the
    #: clipped graph floor alike. The debugging trail.
    dropped: tuple[str, ...] = ()
    truncated: bool = False

    def tokens(self) -> int:
        return sum(section.tokens for section in self.sections)

    def render(self) -> str:
        """The human/debugging view. NOT the model-facing surface — use
        `fenced(nonce)` for prompts (ratchet-enforced in the hardening tests)."""
        parts: list[str] = []
        for section in self.sections:
            suffix = f" {section.citation}" if section.citation else ""
            parts.append(f"{section.text}{suffix}")
        return "\n".join(parts)

    def fenced(self, nonce: str) -> str:
        """The model-facing surface: each section as its own nonce-fenced data
        block (agent/prompt.py), labeled by kind, citation carried inside the
        fence. Nothing here can pose as a Solus instruction."""
        return "\n".join(
            prompt.data_block(
                nonce,
                f"context_{section.kind}",
                {"text": section.text, "citation": section.citation},
            )
            for section in self.sections
        )


def _estimate(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _clip(value: str, cap: int) -> str:
    return value if len(value) <= cap else value[:cap] + "…"


def _cite_part(value: str | None, fallback: str) -> str:
    cleaned = _CITE_UNSAFE.sub("_", value or fallback)[:_CITE_CAP]
    return cleaned or "?"


def _citation(ref: SourceRef) -> str:
    connector = _cite_part(ref.source_connector, "entity")
    target = _cite_part(ref.external_ref, str(ref.graph_entity_id) if ref.graph_entity_id else "?")
    return f"[{connector}:{target}]"


def _graph_section(graph: GraphContext) -> ContextSection:
    names = {entity.id: _clip(entity.name, _FIELD_CAP) for entity in graph.entities}
    lines = []
    for entity in sorted(graph.entities, key=lambda e: (e.name, str(e.id))):
        attrs = redact_value(dict(sorted(entity.attrs.items()))) if entity.attrs else None
        line = f"{names[entity.id]} ({entity.kind}/{entity.domain})"
        if attrs:
            line += f" attrs={_clip(str(attrs), _FIELD_CAP)}"
        lines.append(line)
    lines += [
        f"{names.get(edge.src_id, edge.src_id)} -[{edge.relation_type}]-> "
        f"{names.get(edge.dst_id, edge.dst_id)} ({edge.domain_pair}, {edge.confidence:.2f})"
        for edge in sorted(
            graph.edges, key=lambda e: (str(e.src_id), str(e.dst_id), e.relation_type)
        )
    ]
    text = redact_text("Graph context:\n" + "\n".join(lines))
    return ContextSection(kind="graph", text=text, tokens=_estimate(text), score=1.0)


def _telemetry_sections(view: TelemetrySummaryView) -> list[ContextSection]:
    sections: list[ContextSection] = []
    for window in view.windows:
        lines = [
            f"Telemetry {window.window_start.isoformat()} → {window.window_end.isoformat()}: "
            f"{_clip(window.summary, _FIELD_CAP)}"
        ]
        if window.anomalies:
            lines.append("Anomalies: " + _clip("; ".join(window.anomalies), _FIELD_CAP))
        text = redact_text("\n".join(lines))
        sections.append(
            ContextSection(
                kind="telemetry",
                text=text,
                tokens=_estimate(text),
                score=1.0,
                # Through the citation sanitizer like every other citation —
                # a tz-aware isoformat carries `+`, outside the charset the
                # verifier accepts (SOL-02 review: telemetry provenance was
                # silently unverifiable).
                citation=f"[telemetry:{_cite_part(window.window_start.isoformat(), '?')}]",
            )
        )
    return sections


def _hit_section(kind: SectionKind, hit: RagHit) -> ContextSection:
    text = _clip(hit.chunk, _CHUNK_CAP)
    if isinstance(hit, ErrorHit) and hit.solution_text:
        text = f"{text}\nRecorded fix: {_clip(hit.solution_text, _CHUNK_CAP)}"
    text = redact_text(text)
    return ContextSection(
        kind=kind,
        text=text,
        tokens=_estimate(text),
        score=hit.score,
        citation=_citation(hit.source_ref),
    )


def _corpus_section(hit: CorpusHit) -> ContextSection:
    """A shipped reference chunk: title, body, its confidence stated in words the
    model can repeat, and the attribution the licence asks for. Still DATA — it
    is fenced like every other section, and cited by chunk id."""
    lines = [_clip(hit.chunk, _CORPUS_CAP), f"Confidence: {hit.confidence:.2f}"]
    if hit.low_confidence:
        lines.append(_LOW_CONFIDENCE_NOTE)
    if hit.attribution:
        lines.append(f"Source: {_clip(hit.attribution, _FIELD_CAP)}")
    text = redact_text("\n".join(lines))
    return ContextSection(
        kind="corpus",
        text=text,
        tokens=_estimate(text),
        score=hit.score,
        citation=_citation(hit.source_ref),
    )


def _corpus_order(mode: SolMode | None) -> Callable[[CorpusHit], tuple[float, int, str]]:
    """Relevance first; SOL mode breaks ties — Guide prefers `fundamentals`,
    Expert prefers `reference` (ADR-016: mode ranks, never filters)."""
    preferred = (
        None
        if mode is None
        else (Audience.FUNDAMENTALS if mode is SolMode.GUIDE else Audience.REFERENCE)
    )

    def key(hit: CorpusHit) -> tuple[float, int, str]:
        tie = 0 if preferred is None or hit.audience == preferred.value else 1
        return (-hit.score, tie, hit.chunk_id)

    return key


def _clipped_floor(section: ContextSection, limit: int) -> ContextSection:
    """The graph floor, forced under the budget: ingested content must never
    set the token bill, so an oversized graph section is clipped, recorded,
    and the invariant `Context.tokens() <= max_tokens` holds unconditionally."""
    keep_chars = max(1, limit * _CHARS_PER_TOKEN - 1)
    text = _clip(section.text, keep_chars)
    return ContextSection(kind=section.kind, text=text, tokens=_estimate(text), score=section.score)


async def build_context(
    systems: SolSystems,
    query: str,
    *,
    project_id: UUID,
    scope: GraphScope,
    window: TelemetryWindow | None = None,
    budget: ContextBudget | None = None,
    k: int = DEFAULT_K,
    mode: SolMode | None = None,
) -> Context:
    """Assemble the reasoning context for `query` through W0-07 only.

    `project_id` is the tenant scope: it is forwarded to the graph pull and
    into every tenant RetrievalFilter, and callers derive it from ProjectCtx —
    never from model output or ingested content (CLAUDE.md §7). The engineering
    corpus is the one GLOBAL source (ADR-036): its filter carries no project_id
    and a deterministic domain route, so an electrical question never loads
    machining chunks. `mode` only orders corpus ties (ADR-016)."""
    k = min(k, MAX_K)
    graph = await systems.get_graph_context(project_id, scope, budget)
    telemetry = await systems.get_telemetry(project_id, window) if window is not None else None
    tenant_filter = RetrievalFilter(project_id=project_id)
    errors = await systems.get_error_history(query, k, tenant_filter)
    documents = await systems.rag_query(query, k, tenant_filter)
    routed = route_domains(query)
    corpus_filter = RetrievalFilter(
        source_types=[CORPUS_CONNECTOR],
        domains=None if routed is None else [d.value for d in routed],
    )
    # Only real corpus hits render as corpus: a double that ignores source_types
    # cannot smuggle tenant text into the shipped-reference block.
    corpus = sorted(
        (h for h in await systems.rag_query(query, k, corpus_filter) if isinstance(h, CorpusHit)),
        key=_corpus_order(mode),
    )
    reference = [_corpus_section(hit) for hit in corpus]

    # Dedupe across feeds by chunk identity; errors first, so the copy that
    # carries a recorded fix wins over a bare retrieval of the same text.
    ranked: list[ContextSection] = []
    seen_chunks: set[str] = set()
    for kind, hits in (("error", errors), ("document", documents)):
        for hit in hits:
            if hit.chunk in seen_chunks:
                continue
            seen_chunks.add(hit.chunk)
            ranked.append(_hit_section(kind, hit))  # type: ignore[arg-type]
    # Relevance order across feeds; citation tie-break keeps it deterministic.
    ranked.sort(key=lambda s: (-s.score, s.citation or ""))

    # Packing. The scoped graph pull is the floor (clipped under the budget if
    # ingested content bloats it); telemetry trims oldest-window-first; ranked
    # hits pack best-first with a STRICT cutoff — the first hit that does not
    # fit ends packing, so a less relevant hit never displaces a better one.
    floor = _graph_section(graph)
    telemetry_sections = _telemetry_sections(telemetry) if telemetry is not None else []
    dropped: list[str] = []
    truncated = graph.truncated

    limit = budget.max_tokens if budget is not None and budget.max_tokens is not None else None
    if limit is None:
        sections = [floor, *telemetry_sections, *ranked, *reference]
    else:
        if floor.tokens > limit:
            dropped.append("graph:clipped")
            floor = _clipped_floor(floor, limit)
            truncated = True
        sections = [floor]
        used = floor.tokens
        kept_telemetry = list(telemetry_sections)
        while kept_telemetry and used + sum(s.tokens for s in kept_telemetry) > limit:
            trimmed = kept_telemetry.pop(0)  # oldest window first
            dropped.append(trimmed.citation or "telemetry")
            truncated = True
        used += sum(s.tokens for s in kept_telemetry)
        sections += kept_telemetry
        for group in (ranked, reference):
            for index, section in enumerate(group):
                if used + section.tokens > limit:
                    dropped += [s.citation or s.kind for s in group[index:]]
                    truncated = True
                    break
                sections.append(section)
                used += section.tokens

    return Context(
        query=query,
        project_id=project_id,
        sections=tuple(sections),
        dropped=tuple(dropped),
        truncated=truncated,
    )
