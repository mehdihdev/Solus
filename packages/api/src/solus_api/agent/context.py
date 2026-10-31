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
#   Since SOLUSDEV-321 P0-T6 only a practice question consults it.
#
# - LAYERED (SOLUSDEV-252 S5; eleven layers since SOLUSDEV-321 P0-T4,
#   agent/layers.py): every section belongs to one layer of LAYER_ORDER; a binding
#   layer packs under its own cap and the total; an empty layer is PRESENT with a
#   reason.
# - PREFIX-STABLE (P0-T4): the layers before the conversation come from the
#   project, the person and the turn's anchors, and they pack before anything that
#   varies with the message, so two turns of one conversation that keep the same
#   anchors render a byte-identical prefix.
# - `.solus` ON THE TREE (P0-T6, agent/solus_layer.py): the standing digest, the
#   `errors` entries and open findings about the parts in scope, and the `.solus`
#   entries the message matches — read in ONE read-only session of the request's
#   sessionmaker, never through `systems`.
#
# The model-facing surface is `Context.fenced_prefix(nonce)` — the precedence
# note, then the layers before the conversation — and `fenced_suffix(nonce)`, the
# rest; the runner sends them apart, around the history. Each layer sits under a
# Solus-authored header, each section is its own nonce-fenced data block via
# agent/prompt.py. `render()` is the human/debugging view — a ratchet in the
# hardening tests keeps production code off it.

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from solus_contracts import RELATION_CLASS, RELATION_DOCS, RelationClass

from solus_api.agent import prompt
from solus_api.agent.interfaces import (
    ContextBudget,
    EdgeRead,
    EntityRead,
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
    _cite_part,
    _clip,
    _under_cap,
    counted_layer,
    sections_layer,
)
from solus_api.agent.reason import Anchor, DroppedAnchor, question_domains
from solus_api.agent.solus_layer import (
    SolusReads,
    _solus_reads,
    divergence_sections,
    envelope_sections,
    finding_sections,
    relevant_solus_sections,
    scoped_error_sections,
    standing_sections,
)
from solus_api.agent.tools.untrusted import redact_text
from solus_api.corpus.domains import route_domains
from solus_api.corpus.enums import Audience
from solus_api.corpus.retrieval import CORPUS_CONNECTOR, CorpusHit
from solus_api.fingerprint.contract import SourceRef
from solus_api.models import SolMode
from solus_api.orchestration.gateway import default_orchestration_config
from solus_api.orchestration.type_estimator import chars_for_tokens, estimate_tokens

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.research import ResearchDigest

#: The one token estimator's knob (models.yaml `type_estimator:`). Context packing
#: counts with `estimate_tokens` exactly as routing does, so calibrating the
#: divisor there moves both (tests/test_token_estimator_ratchet.py).
_ESTIMATOR = default_orchestration_config().type_estimator
#: The `scope:` word lists (models.yaml); `environment` gates the divergences table.
_SCOPE = default_orchestration_config().scope

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
SOLUS_NOT_LOADED = ".solus not loaded"
SOLUS_EMPTY = "no standing .solus entries"
_SOLUS_OVER_BUDGET = "no .solus entry fit the budget"
#: The layers besides the standing digest that the `.solus` reads feed (P0-T6).
_SOLUS_READ_LAYERS: Final[frozenset[LayerKind]] = frozenset({"solus_scoped", "findings"})
#: Header labels avoid the gateway type estimator's trigger words (screenshot,
#: logs, plot…) — Solus prose must not steer the model choice. The layer NAMES are
#: fixed and one is `telemetry`; a SOL turn routes by its interaction context, which
#: the gateway ranks ahead of any text estimate (orchestration/resolution.py).
_LAYER_LABEL: dict[LayerKind, str] = {
    "preferences": "root .solus engineering preferences",
    "project_card": "what this project is",
    "solus_standing": "this project's standing .solus entries",
    "graph": "the project graph around what the person pointed at",
    "solus_scoped": ".solus entries about the parts in scope",
    "findings": "open findings on the parts in scope",
    "conversation": "prior turns and the live message",
    "retrieval": "evidence retrieved for this message",
    "corpus": "shipped engineering references",
    "telemetry": "recent runtime windows",
    "screen": "what is on the user's display right now",
}
#: Why a section layer is empty, for the manifest; the prompt only ever says
#: "<layer>: none" (`_layer_note`). The `.solus` layer's reason is the Context's own
#: (`_solus_reason`), and the two counted layers carry theirs in `Context.layers`.
_EMPTY_REASON: Final[dict[LayerKind, str]] = {
    "project_card": "no project card",
    "graph": "no graph context",
    "solus_scoped": "no scoped .solus entries",
    "findings": "no findings in scope",
    "retrieval": "no retrieval hits",
    "corpus": "no corpus hits",
    "telemetry": "no telemetry window on this turn",
    "screen": "no screenshot on this turn",
}
#: SOLUSDEV-321 P0-T4: how many layers form the stable prefix — the ones before the
#: conversation, built from the project, the person and the turn's anchors — which
#: the runner sends ahead of the history, where a provider prompt cache can hold them.
_PREFIX_LAYER_COUNT: Final = LAYER_ORDER.index("conversation")


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
    #: Why the `.solus` layer is empty, or None.
    solus_empty_reason: str | None = SOLUS_NOT_LOADED
    #: Where the graph scope was anchored and why, and the anchors that never
    #: reached it (`turn_scope.plan_scope`) — the manifest says why SOL looked there.
    anchors: tuple[Anchor, ...] = ()
    anchors_dropped: tuple[DroppedAnchor, ...] = ()
    #: The findings read found an open non-info finding (warning or critical) observing a part
    #: in scope: P0-T7 routes such a turn HARD. An info finding renders and routes nothing.
    finding_in_scope: bool = False
    #: SOLUSDEV-321 P7 fix 1 (I1): the ids of the entities the project-scoped graph pull returned.
    scoped_ids: frozenset[UUID] = frozenset()

    def tokens(self) -> int:
        return sum(section.tokens for section in self.sections)

    def scoped_anchors(self) -> tuple[Anchor, ...]:
        """The turn's anchors the project-scoped pull returned: the only ones whose
        `[entity:<id>]` a reply may keep (`citations.with_anchor_citations`) and the graph
        layer offers. An id pasted into the message (`ref_match`) that the pull did not return —
        another team's, a deleted one, one that never existed — is neither."""
        return tuple(anchor for anchor in self.anchors if anchor.id in self.scoped_ids)

    @property
    def layers(self) -> ContextLayers:
        """The eleven layers, derived from the sections — never a second copy. When the
        `.solus` reads did not happen, the scoped and findings layers they feed say so too."""
        by: dict[LayerKind, list[ContextSection]] = {kind: [] for kind in LAYER_ORDER}
        for section in self.sections:
            by[SECTION_LAYER[section.kind]].append(section)
        unread = self.solus_empty_reason == SOLUS_NOT_LOADED
        return ContextLayers(
            preferences=counted_layer("preferences", self.preferences_tokens, "no preferences"),
            conversation=counted_layer(
                "conversation", self.conversation_tokens, "no conversation reported"
            ),
            solus_standing=sections_layer(
                "solus_standing", tuple(by["solus_standing"]), self.solus_empty_reason
            ),
            **{
                kind: sections_layer(
                    kind,
                    tuple(by[kind]),
                    SOLUS_NOT_LOADED if unread and kind in _SOLUS_READ_LAYERS else reason,
                )
                for kind, reason in _EMPTY_REASON.items()
            },
        )

    def with_screen(self, section_text: str, tokens: int) -> Context:
        """Slot the runner's already-fenced screen read (agent/screen.py
        `screen_section`) into the screen layer, so it renders in layer order
        instead of after the context."""
        section = ContextSection(kind="screen", text=section_text, tokens=tokens, score=1.0)
        return self.model_copy(update={"sections": (*self.sections, section)})

    def with_card(self, section: ContextSection | None) -> Context:
        """Slot the project card (agent/project_card.py `project_card_section`) first in
        `sections`; it renders in layer 2. It is not packed: `render_card` holds it to its
        own ceiling. None leaves the layer honestly empty ("no project card")."""
        if section is None:
            return self
        return self.model_copy(update={"sections": (section, *self.sections)})

    def with_conversation(self, *, tokens: int) -> Context:
        """Report the tokens the runner's history + live message occupy."""
        return self.model_copy(update={"conversation_tokens": tokens})

    def with_anchors(
        self, anchors: tuple[Anchor, ...], dropped: tuple[DroppedAnchor, ...]
    ) -> Context:
        """Record the plan's anchors and the ones that never reached the scope."""
        return self.model_copy(update={"anchors": anchors, "anchors_dropped": dropped})

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
            "anchors": [{"id": str(a.id), "reason": a.reason} for a in self.anchors],
            "anchors_dropped": [
                {"id": str(a.id), "reason": a.reason, "cause": a.cause}
                for a in self.anchors_dropped
            ],
        }

    def render(self) -> str:
        """The human/debugging view. NOT the model-facing surface — prompts use
        `fenced_prefix`/`fenced_suffix` (ratchet-enforced in the hardening tests)."""
        parts: list[str] = []
        for section in self.sections:
            suffix = f" {section.citation}" if section.citation else ""
            parts.append(f"{section.text}{suffix}")
        return "\n".join(parts)

    def fenced_prefix(self, nonce: str) -> str:
        """The STABLE PREFIX of the model-facing surface: the precedence note, then
        every layer before the conversation. Built from the project, the person and
        the turn's anchors, it is byte-identical across the turns of one conversation
        that keep the same anchors (at one routing tier: the tier sets the caps, and
        another tier is another model with its own cache). The runner sends it ahead
        of the history."""
        return "\n".join((PRECEDENCE_NOTE, *self._fenced_layers(nonce, 0, _PREFIX_LAYER_COUNT)))

    def fenced_suffix(self, nonce: str) -> str:
        """The conversation layer's header, then every layer that varies with the
        message (retrieval, corpus, telemetry, screen) — the live turn's head."""
        return "\n".join(self._fenced_layers(nonce, _PREFIX_LAYER_COUNT, len(LAYER_ORDER)))

    def fenced(self, nonce: str) -> str:
        """The whole model-facing surface — both halves, in one string."""
        return f"{self.fenced_prefix(nonce)}\n{self.fenced_suffix(nonce)}"

    def _fenced_layers(self, nonce: str, start: int, stop: int) -> list[str]:
        """Layers `start`..`stop` of LAYER_ORDER, each under a Solus-authored header
        numbered across the split, each section its own nonce-fenced data block
        (agent/prompt.py). Empty layers say so. Nothing inside a fence can pose as
        a Solus instruction."""
        parts: list[str] = []
        for index, layer in enumerate(self.layers.order()[start:stop], start + 1):
            parts.append(
                f"## Layer {index}/{len(LAYER_ORDER)} — {layer.kind} ({_LAYER_LABEL[layer.kind]})"
            )
            parts.extend(_fence_section(nonce, section) for section in layer.sections)
            parts.extend(_layer_note(layer))
            if layer.kind == "graph":
                parts.extend(_anchor_tokens_line(self.scoped_anchors()))
        return parts


def _anchor_tokens_line(anchors: tuple[Anchor, ...]) -> list[str]:
    """SOLUSDEV-321 P7 fix 1 (R142a): the one Solus-authored line, outside the graph layer's
    fence, that offers the tokens the turn's pulled anchors serve; none without one. Built from
    UUIDs alone, it changes only when the anchors do, as the graph layer itself does."""
    if not anchors:
        return []
    tokens = ", ".join(f"[entity:{anchor.id}]" for anchor in anchors)
    return [f"Cite an entity this turn is anchored on by its token, exactly as given: {tokens}."]


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
    return [f"{layer.kind}: none"]


def _citation(ref: SourceRef) -> str:
    connector = _cite_part(ref.source_connector, "entity")
    target = _cite_part(ref.external_ref, str(ref.graph_entity_id) if ref.graph_entity_id else "?")
    return f"[{connector}:{target}]"


#: The attrs an entity line carries when they hold a scalar — what a tool needs to address the
#: entity. The rest stays in the graph: never an attrs blob in the prompt (SOLUSDEV-321 P1-T1).
_ENTITY_FIELDS: Final = ("definition_id", "address", "path")
#: A relation of the current vocabulary renders by name; a legacy one renders as its
#: RELATION_DOCS line, so the model reads what it means (any other type renders as itself).
_CURRENT_RELATIONS: Final = frozenset(
    relation.value for relation, kind in RELATION_CLASS.items() if kind is not RelationClass.LEGACY
)
#: How many of an edge's newest evidence items its triple shows.
_TRIPLE_EVIDENCE: Final = 3


def _graph_section(graph: GraphContext) -> ContextSection:
    """One curated line per entity, then one triple per fact edge — never a JSON blob."""
    names = {entity.id: _clip(entity.name, _FIELD_CAP) for entity in graph.entities}
    lines = [
        _entity_line(entity, names[entity.id])
        for entity in sorted(graph.entities, key=lambda e: (e.name, str(e.id)))
    ]
    lines += [
        _triple(edge, names)
        for edge in sorted(
            graph.edges, key=lambda e: (str(e.src_id), str(e.dst_id), e.relation_type)
        )
    ]
    text = redact_text("Graph context:\n" + "\n".join(lines))
    return ContextSection(
        kind="graph", text=text, tokens=estimate_tokens(text, config=_ESTIMATOR), score=1.0
    )


def _entity_line(entity: EntityRead, name: str) -> str:
    """`name (kind/domain) entity_id: <id>`, then the addressing attrs it has (scalars only)."""
    fields = [
        f"{key}: {_clip(str(entity.attrs[key]), _FIELD_CAP)}"
        for key in _ENTITY_FIELDS
        if isinstance(entity.attrs.get(key), str | int | float)
    ]
    return ", ".join([f"{name} ({entity.kind}/{entity.domain}) entity_id: {entity.id}", *fields])


def _triple(edge: EdgeRead, names: Mapping[UUID, str]) -> str:
    """`(src) -relation[0.80]-> (dst) — <evidence kind>: <ref>; …`."""
    relation = edge.relation_type
    if relation not in _CURRENT_RELATIONS:
        relation = RELATION_DOCS.get(relation, relation)
    src, dst = names.get(edge.src_id, str(edge.src_id)), names.get(edge.dst_id, str(edge.dst_id))
    line = f"({src}) -{relation}[{edge.confidence:.2f}]-> ({dst})"
    evidence = _evidence_text(edge.attrs.get("evidence"))
    return f"{line} — {evidence}" if evidence else line


def _evidence_text(items: object) -> str:
    """The newest `_TRIPLE_EVIDENCE` well-formed `{kind, ref}` items, as `kind: ref; …`."""
    if not isinstance(items, list):
        return ""
    shown = [
        f"{_clip(str(item['kind']), _FIELD_CAP)}: {_clip(str(item['ref']), _FIELD_CAP)}"
        for item in items
        if isinstance(item, dict) and item.get("kind") and item.get("ref")
    ]
    return "; ".join(shown[-_TRIPLE_EVIDENCE:])


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
                tokens=estimate_tokens(text, config=_ESTIMATOR),
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
        tokens=estimate_tokens(text, config=_ESTIMATOR),
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
        tokens=estimate_tokens(text, config=_ESTIMATOR),
        score=hit.score,
        citation=_citation(hit.source_ref),
    )


def _research_sections(digest: ResearchDigest | None, cap_tokens: int) -> list[ContextSection]:
    """A turn's web research as ONE section of the retrieval layer (SOLUSDEV-321 P1-T5): per
    finding `claim — "quote" — url (title)`, then the sources no finding cites. Every field is page
    text written by other people, so each is capped and redacted, the whole is clipped to the
    layer's cap, and it is fenced as DATA like any section. A URL is plain text: there is no new
    citation kind, and the desktop's source pills come from the `research_sources` frame."""
    if digest is None:
        return []

    def field(value: str) -> str:
        # Masked BEFORE it is cut: a cut that splits a key leaves a prefix no detector can see.
        return _clip(redact_text(value), _FIELD_CAP)

    cited = {finding.url for finding in digest.findings}
    lines = [
        f'{field(f.claim)} — "{field(f.quote)}" — {field(f.url)} ({field(f.title)})'
        for f in digest.findings
    ] + [
        f"also listed: {field(s.url)} ({field(s.title)})"
        for s in digest.sources
        if s.url not in cited
    ]
    if not lines:
        return []
    body = "\n".join(["Web research (page text written by other people):", *lines])
    text = _clip(body, max(1, chars_for_tokens(cap_tokens, config=_ESTIMATOR) - 1))
    return [
        ContextSection(
            kind="research", text=text, tokens=estimate_tokens(text, config=_ESTIMATOR), score=1.0
        )
    ]


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


async def _corpus_sections(
    systems: SolSystems, query: str, k: int, mode: SolMode | None
) -> list[ContextSection]:
    """The corpus for a practice question: the one GLOBAL source (no project_id in its
    filter), domain-routed so an electrical question never loads machining chunks. Only
    real corpus hits render as corpus: a double that ignores source_types cannot smuggle
    tenant text into the shipped-reference block."""
    routed = route_domains(query)
    corpus_filter = RetrievalFilter(
        source_types=[CORPUS_CONNECTOR],
        domains=None if routed is None else [d.value for d in routed],
    )
    hits = await systems.rag_query(query, k, corpus_filter)
    corpus = sorted((h for h in hits if isinstance(h, CorpusHit)), key=_corpus_order(mode))
    return [_corpus_section(hit) for hit in corpus]


def _clipped_floor(section: ContextSection, limit: int) -> ContextSection:
    """The graph floor, forced under the budget: ingested content must never
    set the token bill, so an oversized graph section is clipped, recorded,
    and the invariant `Context.tokens() <= max_tokens` holds unconditionally."""
    keep_chars = max(1, chars_for_tokens(limit, config=_ESTIMATOR) - 1)  # -1: the ellipsis
    text = _clip(section.text, keep_chars)
    return ContextSection(
        kind=section.kind,
        text=text,
        tokens=estimate_tokens(text, config=_ESTIMATOR),
        score=section.score,
    )


async def build_context(
    systems: SolSystems,
    query: str,
    *,
    project_id: UUID,
    scope: GraphScope,
    graph: GraphContext | None = None,
    window: TelemetryWindow | None = None,
    budget: ContextBudget | None = None,
    k: int = DEFAULT_K,
    mode: SolMode | None = None,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    preferences_tokens: int = 0,
    practice_question: bool = False,
    research: ResearchDigest | None = None,
) -> Context:
    """Assemble the reasoning context for `query` through W0-07 only.

    `project_id` is the tenant scope: it is forwarded to the graph pull and
    into every tenant RetrievalFilter, and callers derive it from ProjectCtx —
    never from model output or ingested content (CLAUDE.md §7). The engineering
    corpus is the one GLOBAL source (ADR-036), consulted only when the plan marks a
    `practice_question` (models.yaml `practice_patterns`); `mode` only orders its
    ties (ADR-016).

    `graph` is the scope planner's one pull (`turn_scope.plan_scope`, SOLUSDEV-321
    P1-T1): handed in, it is packed as it is and nothing is pulled again; without it
    (callers outside the runner) the pull is made here, from `scope`.

    `sessionmaker` (the request's) reads the project's `.solus` entries, open
    findings and the envelopes of the parts in scope — read-only, one session,
    tenant-scoped by `project_id` (agent/solus_layer.py) — into the standing, scoped,
    findings and retrieval layers. Without it, or when a read fails (logged, never
    raised), the standing, scoped and findings layers say ".solus not loaded" and
    retrieval carries no `.solus` hit; a failed envelope read costs only the envelope
    sections. `preferences_tokens` is what the system prompt spends on the root
    preferences (prompt.py renders them; the layer only reports the count). A
    `LayeredContextBudget` carries per-layer caps; a plain ContextBudget gets the
    defaults (S5). `research` (SOLUSDEV-321 P1-T5) is the digest the turn's web research
    returned: ONE `research` section of the retrieval layer, ranked first among its hits and
    clipped to that layer's cap."""
    k = min(k, MAX_K)
    layer_caps = budget.layers if isinstance(budget, LayeredContextBudget) else LayerBudget()
    if graph is None:
        graph = await systems.get_graph_context(project_id, scope, budget)
    scoped = frozenset(entity.id for entity in graph.entities)
    reads = await _solus_reads(
        sessionmaker,
        project_id,
        query=query,
        scoped_ids=scoped,
        # Over-fetch: entries the prefix already carries must not take the k slots.
        search_limit=MAX_K,
        environment_question="environment" in question_domains(query, scope=_SCOPE),
    )
    found = reads or SolusReads()
    standing, standing_cut, carried = standing_sections(found, cap_tokens=layer_caps.solus_standing)
    in_scope, scoped_cut = _under_cap(scoped_error_sections(found), layer_caps.solus_scoped)
    findings, findings_cut = _under_cap(
        [*finding_sections(found, graph.entities), *envelope_sections(found, graph.entities)],
        layer_caps.findings,
    )
    telemetry = await systems.get_telemetry(project_id, window) if window is not None else None
    tenant_filter = RetrievalFilter(project_id=project_id)
    errors = await systems.get_error_history(query, k, tenant_filter)
    documents = await systems.rag_query(query, k, tenant_filter)
    reference = await _corpus_sections(systems, query, k, mode) if practice_question else []
    rendered = {*carried, *(s.citation for s in in_scope)}
    bound, unbound = relevant_solus_sections(found.hits, rendered=rendered, scoped=scoped, k=k)
    divergences = divergence_sections(found.divergences)
    # The `.solus` hits bound to a part in scope (its datasheets) lead; then relevance, where
    # the turn's web research (P1-T5, a digest it asked for) ranks first.
    web = _research_sections(research, layer_caps.retrieval)
    ranked = [
        *_by_score(bound),
        *_by_score([*web, *_hits(errors, documents), *unbound, *divergences]),
    ]

    floor = _graph_section(graph)
    telemetry_sections = _telemetry_sections(telemetry) if telemetry is not None else []
    reference, over_cap = _under_cap(reference, layer_caps.corpus)
    limit = budget.max_tokens if budget is not None and budget.max_tokens is not None else None
    prefix = (standing, in_scope, findings)
    sections, cut = _pack(floor, prefix, telemetry_sections, ranked, reference, limit)
    dropped = (*standing_cut, *scoped_cut, *findings_cut, *over_cap, *cut)

    return Context(
        query=query,
        project_id=project_id,
        sections=tuple(sections),
        dropped=dropped,
        truncated=graph.truncated or bool(dropped),
        preferences_tokens=preferences_tokens,
        solus_empty_reason=_solus_reason(
            sections, loaded=reads is not None, standing=len(standing) + len(standing_cut)
        ),
        finding_in_scope=found.finding_in_scope,
        scoped_ids=scoped,
    )


def _hits(errors: Sequence[ErrorHit], documents: Sequence[RagHit]) -> list[ContextSection]:
    """Error and document hits, deduped by chunk identity; errors first, so the copy that
    carries a recorded fix wins over a bare retrieval of the same text."""
    sections: list[ContextSection] = []
    seen_chunks: set[str] = set()
    feeds: tuple[tuple[SectionKind, Sequence[RagHit]], ...] = (
        ("error", errors),
        ("document", documents),
    )
    for kind, hits in feeds:
        for hit in hits:
            if hit.chunk in seen_chunks:
                continue
            seen_chunks.add(hit.chunk)
            sections.append(_hit_section(kind, hit))
    return sections


def _by_score(sections: Iterable[ContextSection]) -> list[ContextSection]:
    """Relevance order across feeds; citation tie-break keeps it deterministic."""
    return sorted(sections, key=lambda s: (-s.score, s.citation or ""))


def _pack(
    floor: ContextSection,
    prefix: Sequence[list[ContextSection]],
    telemetry: list[ContextSection],
    ranked: list[ContextSection],
    reference: list[ContextSection],
    limit: int | None,
) -> tuple[list[ContextSection], list[str]]:
    """Every group under the total, in packing order; returns (sections, cuts).

    The scoped graph pull is the floor, clipped under the total if ingested content
    bloats it. The prefix groups pack next — the standing digest, the scoped `.solus`
    entries, the findings: the stable prefix packs before anything that varies with the
    message, so what it carries never depends on how much room the message's own hits
    took (SOLUSDEV-321 P0-T4). Then telemetry, trimmed oldest-window-first, then ranked
    hits and corpus. Every group has a STRICT cutoff — the first section that does not
    fit ends its group, so a less relevant hit never displaces a better one."""
    if limit is None:
        return [floor, *(s for group in prefix for s in group), *telemetry, *ranked, *reference], []
    cut: list[str] = []
    if floor.tokens > limit:
        cut.append("graph:clipped")
        floor = _clipped_floor(floor, limit)
    sections, prefix_cut = _fill([floor], prefix, limit)
    cut += prefix_cut
    used = sum(s.tokens for s in sections)
    windows = list(telemetry)
    while windows and used + sum(s.tokens for s in windows) > limit:
        cut.append(windows.pop(0).citation or "telemetry")  # oldest window first
    sections, hit_cut = _fill([*sections, *windows], (ranked, reference), limit)
    return sections, [*cut, *hit_cut]


def _fill(
    sections: list[ContextSection], groups: Iterable[list[ContextSection]], limit: int
) -> tuple[list[ContextSection], list[str]]:
    """`sections`, then each group under what the total has left (strict cutoff)."""
    cut: list[str] = []
    for group in groups:
        kept, group_cut = _under_cap(group, limit - sum(s.tokens for s in sections))
        sections, cut = [*sections, *kept], [*cut, *group_cut]
    return sections, cut


def _solus_reason(sections: list[ContextSection], *, loaded: bool, standing: int) -> str | None:
    """Why the standing layer is empty: not loaded, nothing standing, or nothing that fit."""
    if any(s.kind == "solus" for s in sections):
        return None
    if not loaded:
        return SOLUS_NOT_LOADED
    return _SOLUS_OVER_BUDGET if standing else SOLUS_EMPTY
