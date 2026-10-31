# SOLUSDEV-252 (S5) — context layering: the layers SOL reasons over on every
# turn, in prompt order, each with its own token cap and an HONEST empty state
# (docs/architecture/sol-context-layers.md).
#
# SOLUSDEV-321 P0-T4 — eleven layers, ordered so the prompt PREFIX is
# byte-stable across the turns of one conversation (provider prompt caches hit):
#
#   preferences → project_card → solus_standing → graph → solus_scoped → findings
#     → conversation (the history) → retrieval → corpus → telemetry → screen
#
# Every layer before `conversation` comes from the project, the person and the
# turn's anchors; retrieval, corpus, telemetry, the screen and the message itself
# follow the history. The graph scope's anchors include the message's own
# @-mentions and pasted UUIDs (`ref_match`, reason.py), so the graph layer — and the
# scoped and findings layers that follow the anchors (P0-T6) — change when a
# message brings new anchors; the prefix is byte-stable across turns that keep the
# same anchors. Up to the conversation, later layers override earlier ones. A
# layer that has nothing this turn is still present, with `empty_reason` saying
# why — never omitted, never stubbed. `ContextSection` lives here (not in
# context.py) so both modules share it without a cycle; context.py re-exports it.
# (Named ContextLayer, not Layer: a vendored EDA MCP fork already has PCB `Layer`s — H6.)

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from solus_api.agent.interfaces import ContextBudget

if TYPE_CHECKING:
    from solus_api.orchestration.config import ContextBudgetConfig
    from solus_api.orchestration.enums import Complexity

SectionKind = Literal[
    "project_card",
    "solus_standing",
    "solus",
    "graph",
    "solus_scoped",
    "finding",
    "envelope",
    "error",
    "document",
    "research",
    "corpus",
    "telemetry",
    "screen",
]
LayerKind = Literal[
    "preferences",
    "project_card",
    "solus_standing",
    "graph",
    "solus_scoped",
    "findings",
    "conversation",
    "retrieval",
    "corpus",
    "telemetry",
    "screen",
]

#: Prompt order, general to specific. The layers before `conversation` are the
#: stable prefix; the rest render in the live turn, after the history (context.py).
LAYER_ORDER: Final[tuple[LayerKind, ...]] = (
    "preferences",
    "project_card",
    "solus_standing",
    "graph",
    "solus_scoped",
    "findings",
    "conversation",
    "retrieval",
    "corpus",
    "telemetry",
    "screen",
)
#: Solus-authored, rendered OUTSIDE every fence.
PRECEDENCE_NOTE: Final = (
    "Blocks up to the conversation run from general to specific; where they disagree, "
    "the later, more specific block wins. The conversation is what was said. Retrieved "
    "evidence and shipped references are supporting material, telemetry is what is "
    "happening now, and the live message is the question."
)
#: Which layer each section kind belongs to. SOLUSDEV-321 P0-T6: `solus` is the
#: standing digest, `solus_scoped` the `errors` entries about the parts in scope, and
#: the `.solus` entries a message matches render as `error`/`document` retrieval hits. P1-T5:
#: a turn's web research digest is one `research` section in the same retrieval layer.
SECTION_LAYER: Final[dict[SectionKind, LayerKind]] = {
    "project_card": "project_card",
    "solus_standing": "solus_standing",
    "solus": "solus_standing",
    "graph": "graph",
    "solus_scoped": "solus_scoped",
    "finding": "findings",
    "envelope": "findings",
    "error": "retrieval",
    "document": "retrieval",
    "research": "retrieval",
    "corpus": "corpus",
    "telemetry": "telemetry",
    "screen": "screen",
}


class LayerBudget(BaseModel):
    """Per-layer token caps. `solus_standing` (the `.solus` digest), `solus_scoped`,
    `findings` and `corpus` bind inside build_context's packing; the graph floor,
    ranked hits, and telemetry pack under the total. `preferences`, `screen`, and
    `conversation` are caps their producers (prompt.py, screen.py, the runner) are
    held to — the layer reports what it was handed — and `project_card` is held by
    `render_card`'s own ceiling. The total is ContextBudget.max_tokens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    preferences: int = Field(default=800, gt=0)
    project_card: int = Field(default=400, gt=0)
    solus_standing: int = Field(default=600, gt=0)
    graph: int = Field(default=1200, gt=0)
    solus_scoped: int = Field(default=400, gt=0)
    findings: int = Field(default=600, gt=0)
    conversation: int = Field(default=6000, gt=0)
    retrieval: int = Field(default=1200, gt=0)
    corpus: int = Field(default=4000, gt=0)
    telemetry: int = Field(default=600, gt=0)
    screen: int = Field(default=600, gt=0)


class LayeredContextBudget(ContextBudget):
    """A ContextBudget that also carries the layer caps. Still a ContextBudget
    for every SolSystems pull — `interfaces.py` is not touched."""

    layers: LayerBudget = LayerBudget()

    @classmethod
    def for_tier(cls, tier: Complexity, config: ContextBudgetConfig) -> LayeredContextBudget:
        """The budget for a routing tier (SOLUSDEV-321): the tier's total from
        models.yaml `context_budget:`, each layer's cap that layer's configured
        share of it. A share naming no layer fails here — `LayerBudget` forbids
        extras. `max_entities` does not depend on the tier (SEC-H3); the caller
        sets it."""
        total = config.total_for(tier)
        caps = {name: max(1, round(total * share)) for name, share in config.layer_scale.items()}
        return cls(max_tokens=total, layers=LayerBudget(**caps))


class ContextSection(BaseModel):
    """One inspectable piece of the assembled context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: SectionKind
    text: str
    tokens: int
    #: Relevance for packing. Retrieval hits carry their retrieval score;
    #: graph/telemetry/solus/screen are scoped pulls, not ranked candidates.
    score: float
    citation: str | None = None


class ContextLayer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: LayerKind
    sections: tuple[ContextSection, ...] = ()
    tokens: int = 0
    #: Set exactly when the layer has nothing this turn.
    empty_reason: str | None = None


class ContextLayers(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    preferences: ContextLayer
    project_card: ContextLayer
    solus_standing: ContextLayer
    graph: ContextLayer
    solus_scoped: ContextLayer
    findings: ContextLayer
    conversation: ContextLayer
    retrieval: ContextLayer
    corpus: ContextLayer
    telemetry: ContextLayer
    screen: ContextLayer

    def order(self) -> tuple[ContextLayer, ...]:
        """Prompt order (LAYER_ORDER)."""
        return tuple(getattr(self, kind) for kind in LAYER_ORDER)


def sections_layer(
    kind: LayerKind, sections: tuple[ContextSection, ...], empty_reason: str | None
) -> ContextLayer:
    """A layer made of fenced sections; `empty_reason` applies only when it has none."""
    return ContextLayer(
        kind=kind,
        sections=sections,
        tokens=sum(s.tokens for s in sections),
        empty_reason=None if sections else empty_reason,
    )


def counted_layer(kind: LayerKind, tokens: int, empty_reason: str) -> ContextLayer:
    """A layer whose text lives elsewhere (system prompt, the runner's turns);
    the layer reports the count so the manifest is honest."""
    return ContextLayer(kind=kind, tokens=tokens, empty_reason=None if tokens > 0 else empty_reason)


# Section primitives context.py and solus_layer.py share — here, beside ContextSection,
# so neither imports the other (SOLUSDEV-321 P0-T6 moved them out of context.py).

#: Citation components are charset-restricted and capped (SEC-C1) — mirrors
#: tools/untrusted.SAFE_REMOTE_NAME. No `]`, whitespace, or newline can
#: survive, so ingested provenance cannot mint labels or extra citations.
_CITE_UNSAFE = re.compile(r"[^A-Za-z0-9._/#:-]")
_CITE_CAP = 128


def _clip(value: str, cap: int) -> str:
    return value if len(value) <= cap else value[:cap] + "…"


def _cite_part(value: str | None, fallback: str) -> str:
    cleaned = _CITE_UNSAFE.sub("_", value or fallback)[:_CITE_CAP]
    return cleaned or "?"


def _under_cap(group: list[ContextSection], cap: int) -> tuple[list[ContextSection], list[str]]:
    """A layer's own cap, with the same strict cutoff as the total budget."""
    used = 0
    for index, section in enumerate(group):
        if used + section.tokens > cap:
            return group[:index], [s.citation or s.kind for s in group[index:]]
        used += section.tokens
    return group, []
