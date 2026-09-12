# SOLUSDEV-252 (S5) — context layering: the five layers SOL reasons over on
# every turn, in precedence order, each with its own token cap and an HONEST
# empty state (docs/architecture/sol-context-layers.md).
#
#   corpus (C2) → preferences (H3) → project .solus + tenant evidence (W1)
#          → screen capture (S3) → conversation
#
# Later layers override earlier ones. A layer that has nothing this turn is
# still present, with `empty_reason` saying why — never omitted, never stubbed.
# `ContextSection` lives here (not in context.py) so both modules share it
# without a cycle; context.py re-exports it. (Named ContextLayer, not Layer:
# the Altium MCP fork already has PCB `Layer`s — H6.)

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from solus_api.agent.interfaces import ContextBudget

SectionKind = Literal["graph", "telemetry", "error", "document", "corpus", "solus", "screen"]
LayerKind = Literal["corpus", "preferences", "project_solus", "screen", "conversation"]

#: Weakest first. The prompt renders layers in this order, under the note.
LAYER_ORDER: Final[tuple[LayerKind, ...]] = (
    "corpus",
    "preferences",
    "project_solus",
    "screen",
    "conversation",
)
#: Solus-authored, rendered OUTSIDE every fence.
PRECEDENCE_NOTE: Final = (
    "Layers below are ordered from general to specific; where they disagree, "
    "the later, more specific layer wins."
)
#: Which layer each section kind belongs to. Graph, telemetry, errors, and
#: documents are project-specific evidence: they sit with the project .solus.
SECTION_LAYER: Final[dict[SectionKind, LayerKind]] = {
    "corpus": "corpus",
    "graph": "project_solus",
    "telemetry": "project_solus",
    "error": "project_solus",
    "document": "project_solus",
    "solus": "project_solus",
    "screen": "screen",
}


class LayerBudget(BaseModel):
    """Per-layer token caps. `corpus` and `project_solus` bind inside
    build_context's packing; `preferences`, `screen`, and `conversation` are
    caps their producers (prompt.py, screen.py, the runner) are held to — the
    layer reports what it was handed. The total is ContextBudget.max_tokens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corpus: int = Field(default=4000, gt=0)
    preferences: int = Field(default=800, gt=0)
    project_solus: int = Field(default=2500, gt=0)
    screen: int = Field(default=600, gt=0)
    conversation: int = Field(default=6000, gt=0)


class LayeredContextBudget(ContextBudget):
    """A ContextBudget that also carries the layer caps. Still a ContextBudget
    for every SolSystems pull — `interfaces.py` is not touched."""

    layers: LayerBudget = LayerBudget()


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
    #: Set exactly when the layer has nothing this turn (for the project layer,
    #: when its optional component — the .solus entries — is absent).
    empty_reason: str | None = None


class ContextLayers(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    corpus: ContextLayer
    preferences: ContextLayer
    project_solus: ContextLayer
    screen: ContextLayer
    conversation: ContextLayer

    def order(self) -> tuple[ContextLayer, ...]:
        """Precedence order, weakest first."""
        return tuple(getattr(self, kind) for kind in LAYER_ORDER)


def sections_layer(
    kind: LayerKind, sections: tuple[ContextSection, ...], empty_reason: str | None
) -> ContextLayer:
    """A layer made of fenced sections; `empty_reason` applies when it has none
    (the project layer passes the .solus reason — see ContextLayer.empty_reason)."""
    return ContextLayer(
        kind=kind,
        sections=sections,
        tokens=sum(s.tokens for s in sections),
        empty_reason=empty_reason,
    )


def counted_layer(kind: LayerKind, tokens: int, empty_reason: str) -> ContextLayer:
    """A layer whose text lives elsewhere (system prompt, the runner's turns);
    the layer reports the count so the manifest is honest."""
    return ContextLayer(kind=kind, tokens=tokens, empty_reason=None if tokens > 0 else empty_reason)
