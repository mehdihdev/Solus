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
# - LAYERED, FIVE-WAY (SOLUSDEV-252 S5, agent/layers.py): every section belongs
#   to one of corpus → preferences → project (.solus + tenant evidence) →
#   screen → conversation; later layers override earlier; each layer packs
#   under its own cap and the total; an empty layer is PRESENT with a reason.
#   The project's `.solus` entries load read-only through
#   services.solus_config.load_sections (newest first, per-entry capped).
#
# The model-facing surface is `Context.fenced(nonce)`: the precedence note,
# then each layer under a Solus-authored header, each section as its own
# nonce-fenced data block via agent/prompt.py. `render()` is the
# human/debugging view — a ratchet in the hardening tests keeps production
# code off it.

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any
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
from solus_api.agent.layers import (
    LAYER_ORDER,
    PRECEDENCE_NOTE,
    SECTION_LAYER,
    ContextLayer,
    ContextLayers,
    ContextSection,
    LayerBudget,
    LayeredContextBudget,
    LayerKind,
    SectionKind,
    counted_layer,
    sections_layer,
)
from solus_api.agent.tools.untrusted import redact_text, redact_value
from solus_api.corpus.domains import route_domains
from solus_api.corpus.enums import Audience
from solus_api.corpus.retrieval import CORPUS_CONNECTOR, CorpusHit
from solus_api.fingerprint.contract import SourceRef
from solus_api.models import SolMode, SolusSection
from solus_api.services.solus_config import SECTION_LABELS, load_sections

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
#: One `.solus` entry renders to at most this many chars (docs/api/solus.md
#: allows 4,000 per entry; the layer is a digest, not the panel).
_SOLUS_ENTRY_CAP = 500
SOLUS_NOT_LOADED = ".solus not loaded"
SOLUS_EMPTY = "no .solus entries"
_SOLUS_OVER_BUDGET = "no .solus entry fit the budget"
#: Header wording is ALSO routing input: the gateway's type estimator scans the
#: flattened conversation, so these labels avoid its trigger words (telemetry,
#: screenshot, logs, plot…) — Solus prose must not steer the model choice.
_LAYER_LABEL: dict[LayerKind, str] = {
    "corpus": "shipped engineering references",
    "preferences": "root .solus engineering preferences",
    "project_solus": "this project's graph, runtime windows, retrieved evidence, .solus entries",
    "screen": "what is on the user's display right now",
    "conversation": "prior turns and the live message",
}

#: Citation components are charset-restricted and capped (SEC-C1) — mirrors
#: tools/untrusted.SAFE_REMOTE_NAME. No `]`, whitespace, or newline can
#: survive, so ingested provenance cannot mint labels or extra citations.
_CITE_UNSAFE = re.compile(r"[^A-Za-z0-9._/#:-]")
_CITE_CAP = 128


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
    #: Layers whose TEXT lives outside this object (system prompt; the runner's
    #: turns) report their token counts here so the manifest stays honest.
    preferences_tokens: int = 0
    conversation_tokens: int = 0
    #: Why the project layer's optional component is absent, or None.
    solus_empty_reason: str | None = SOLUS_NOT_LOADED

    def tokens(self) -> int:
        return sum(section.tokens for section in self.sections)

    @property
    def layers(self) -> ContextLayers:
        """The five layers, derived from the sections — never a second copy."""
        by: dict[LayerKind, list[ContextSection]] = {kind: [] for kind in LAYER_ORDER}
        for section in self.sections:
            by[SECTION_LAYER[section.kind]].append(section)
        return ContextLayers(
            corpus=sections_layer(
                "corpus", tuple(by["corpus"]), None if by["corpus"] else "no corpus hits"
            ),
            preferences=counted_layer("preferences", self.preferences_tokens, "no preferences"),
            project_solus=sections_layer(
                "project_solus", tuple(by["project_solus"]), self.solus_empty_reason
            ),
            screen=sections_layer(
                "screen",
                tuple(by["screen"]),
                None if by["screen"] else "no screenshot on this turn",
            ),
            conversation=counted_layer(
                "conversation", self.conversation_tokens, "no conversation reported"
            ),
        )

    def with_screen(self, section_text: str, tokens: int) -> Context:
        """Slot the runner's already-fenced screen read (agent/screen.py
        `screen_section`) into the screen layer, so it renders in layer order
        instead of after the context."""
        section = ContextSection(kind="screen", text=section_text, tokens=tokens, score=1.0)
        return self.model_copy(update={"sections": (*self.sections, section)})

    def with_conversation(self, *, tokens: int) -> Context:
        """Report the tokens the runner's history + live message occupy."""
        return self.model_copy(update={"conversation_tokens": tokens})

    def manifest(self) -> dict[str, Any]:
        """The `context_used` payload: labels and counts only, never text."""
        return {
            "sections": [
                {
                    "kind": s.kind,
                    "citation": s.citation,
                    "tokens": s.tokens,
                    "layer": SECTION_LAYER[s.kind],
                }
                for s in self.sections
            ],
            "layers": [
                {
                    "layer": layer.kind,
                    "tokens": layer.tokens,
                    "sections": len(layer.sections),
                    "empty_reason": layer.empty_reason,
                }
                for layer in self.layers.order()
            ],
            "truncated": self.truncated,
            "dropped": len(self.dropped),
        }

    def render(self) -> str:
        """The human/debugging view. NOT the model-facing surface — use
        `fenced(nonce)` for prompts (ratchet-enforced in the hardening tests)."""
        parts: list[str] = []
        for section in self.sections:
            suffix = f" {section.citation}" if section.citation else ""
            parts.append(f"{section.text}{suffix}")
        return "\n".join(parts)

    def fenced(self, nonce: str) -> str:
        """The model-facing surface: the precedence note, then each layer under a
        Solus-authored header, each section as its own nonce-fenced data block
        (agent/prompt.py). Empty layers say so. Nothing inside a fence can pose
        as a Solus instruction."""
        parts = [PRECEDENCE_NOTE]
        for index, layer in enumerate(self.layers.order(), 1):
            parts.append(
                f"## Layer {index}/{len(LAYER_ORDER)} — {layer.kind} ({_LAYER_LABEL[layer.kind]})"
            )
            parts.extend(_fence_section(nonce, section) for section in layer.sections)
            parts.extend(_layer_note(layer))
        return "\n".join(parts)


def _fence_section(nonce: str, section: ContextSection) -> str:
    # The screen read arrives ALREADY fenced under this turn's nonce
    # (screen.screen_section); wrapping it again would fence a fence.
    if section.kind == "screen" and prompt.close_token(nonce) in section.text:
        return section.text
    return prompt.data_block(
        nonce, f"context_{section.kind}", {"text": section.text, "citation": section.citation}
    )


def _layer_note(layer: ContextLayer) -> list[str]:
    """The Solus-authored line for what a layer holds outside the fences. The
    empty REASON stays in the manifest (UI); the prompt gets a bare "none" —
    reason wording would otherwise feed the route-type estimator."""
    if layer.kind == "preferences" and layer.tokens:
        return [f"preferences: {layer.tokens} tokens, carried in the system prompt"]
    if layer.kind == "conversation" and layer.tokens:
        return [f"conversation: {layer.tokens} tokens, carried as the surrounding turns"]
    if layer.empty_reason is None:
        return []
    return [f"{'.solus' if layer.kind == 'project_solus' else layer.kind}: none"]


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
        line = f"{names[entity.id]} ({entity.kind}/{entity.domain}) entity_id: {entity.id}"
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


def _solus_body(entry: Mapping[str, Any]) -> str:
    kind = entry.get("kind")
    if kind == "artifact":
        media = entry.get("media_type")
        return f"file {entry.get('name') or '?'}" + (f" ({media})" if media else "")
    if kind == "config":
        return str(redact_value(entry.get("payload"))) if entry.get("payload") else ""
    return str(entry.get("text") or "")


def _solus_section(entry: Mapping[str, Any]) -> ContextSection:
    raw_section = str(entry.get("section") or "?")
    try:
        label = SECTION_LABELS[SolusSection(raw_section)]
    except ValueError:
        label = raw_section
    author = str(entry.get("author") or "user")
    text = redact_text(f"{label} · {author}: {_clip(_solus_body(entry), _SOLUS_ENTRY_CAP)}")
    return ContextSection(
        kind="solus",
        text=text,
        tokens=_estimate(text),
        score=1.0,
        citation=f"[solus:{_cite_part(raw_section, '?')}:{_cite_part(str(entry.get('id')), '?')}]",
    )


def solus_sections(
    rows: Mapping[str, Sequence[Mapping[str, Any]]], *, cap_tokens: int
) -> tuple[list[ContextSection], list[str]]:
    """The project `.solus` layer from `load_sections` rows: newest first, one
    capped section per entry, packed under `cap_tokens` with the same strict
    cutoff as every other group. Returns (kept, dropped citations)."""
    # str(datetime) sorts chronologically within one tz — the ORM's utcnow.
    entries = sorted(
        (entry for group in rows.values() for entry in group),
        key=lambda e: (str(e.get("created_at") or ""), str(e.get("id"))),
        reverse=True,
    )
    kept: list[ContextSection] = []
    dropped: list[str] = []
    used = 0
    for index, entry in enumerate(entries):
        section = _solus_section(entry)
        if used + section.tokens > cap_tokens:
            dropped += [_solus_section(e).citation or "solus" for e in entries[index:]]
            break
        kept.append(section)
        used += section.tokens
    return kept, dropped


async def _load_solus(
    sessionmaker: async_sessionmaker[AsyncSession] | None, project_id: UUID
) -> dict[str, list[dict[str, Any]]] | None:
    if sessionmaker is None:
        return None
    async with sessionmaker() as session:
        return await load_sections(session, project_id)


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
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    preferences_tokens: int = 0,
) -> Context:
    """Assemble the reasoning context for `query` through W0-07 only.

    `project_id` is the tenant scope: it is forwarded to the graph pull and
    into every tenant RetrievalFilter, and callers derive it from ProjectCtx —
    never from model output or ingested content (CLAUDE.md §7). The engineering
    corpus is the one GLOBAL source (ADR-036): its filter carries no project_id
    and a deterministic domain route, so an electrical question never loads
    machining chunks. `mode` only orders corpus ties (ADR-016).

    `sessionmaker` (the request's) loads the project's live `.solus` entries for
    the project layer — read-only, tenant-scoped by `project_id`; without it the
    layer is honestly empty (".solus not loaded"). `preferences_tokens` is what
    the system prompt spends on the root preferences (prompt.py renders them;
    the layer only reports the count). A `LayeredContextBudget` carries per-layer
    caps; a plain ContextBudget gets the defaults (S5)."""
    k = min(k, MAX_K)
    layer_caps = budget.layers if isinstance(budget, LayeredContextBudget) else LayerBudget()
    solus_rows = await _load_solus(sessionmaker, project_id)
    solus, solus_dropped = solus_sections(solus_rows or {}, cap_tokens=layer_caps.project_solus)
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
    dropped: list[str] = list(solus_dropped)
    truncated = graph.truncated or bool(solus_dropped)

    limit = budget.max_tokens if budget is not None and budget.max_tokens is not None else None
    reference, over_cap = _under_cap(reference, layer_caps.corpus)
    dropped += over_cap
    truncated = truncated or bool(over_cap)
    if limit is None:
        sections = [floor, *telemetry_sections, *ranked, *solus, *reference]
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
        for group in (ranked, solus, reference):
            kept, cut = _under_cap(group, limit - used)
            sections += kept
            used += sum(s.tokens for s in kept)
            dropped += cut
            truncated = truncated or bool(cut)

    return Context(
        query=query,
        project_id=project_id,
        sections=tuple(sections),
        dropped=tuple(dropped),
        truncated=truncated,
        preferences_tokens=preferences_tokens,
        solus_empty_reason=_solus_reason(sections, solus_rows),
    )


def _solus_reason(
    sections: list[ContextSection], rows: dict[str, list[dict[str, Any]]] | None
) -> str | None:
    if any(s.kind == "solus" for s in sections):
        return None
    if rows is None:
        return SOLUS_NOT_LOADED
    return SOLUS_EMPTY if not any(rows.values()) else _SOLUS_OVER_BUDGET


def _under_cap(group: list[ContextSection], cap: int) -> tuple[list[ContextSection], list[str]]:
    """A layer's own cap, with the same strict cutoff as the total budget."""
    used = 0
    for index, section in enumerate(group):
        if used + section.tokens > cap:
            return group[:index], [s.citation or s.kind for s in group[index:]]
        used += section.tokens
    return group, []
