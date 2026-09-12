# SOLUSDEV-130 (SOL-02) — the reasoning layer's deterministic halves.
#
# `plan_query` decides WHAT TO PULL for a query — graph anchors, traversal
# degree, whether a telemetry window is warranted, retrieval k, and the token
# budget — deterministically, with no model call (the ADR-026 pattern:
# classification that gates spend never spends). WHICH MODEL answers stays
# with the gateway's `resolve_routing`, the single routing brain — this module
# deliberately does not duplicate it.
#
# `verified_citations` closes the loop on attribution: the model is asked to
# cite `[connector:ref]` tokens, but only citations the assembled Context
# actually contains survive into the Sources line — a hallucinated citation
# is stripped, never rendered as provenance (§7: model output is untrusted).
#
# RAG knobs (k, degree, budget, telemetry heuristics) are tuned against the
# eval set in tests/test_reason_eval.py; change them there first.

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict

from solus_api.agent.context import Context
from solus_api.agent.interfaces import ContextBudget, GraphScope, TelemetryWindow
from solus_api.agent.layers import LayerBudget, LayeredContextBudget

#: Standard UUID literal. THE shared instance — runtime.py imports it too
#: (review: a security-relevant parser must not drift between copies).
UUID_RE: Final = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_UUID_RE: Final = UUID_RE  # local alias

#: Words that mark a query as being about RUNTIME behaviour — those pulls get
#: a telemetry window; purely structural questions do not pay for one.
#: Tuned against the eval set (test_reason_eval.py).
_RUNTIME_WORDS: Final = frozenset(
    {
        "runtime",
        "telemetry",
        "spike",
        "spikes",
        "glitch",
        "crash",
        "crashes",
        "drops",
        "dropping",
        "intermittent",
        "during",
        "run",
        "moving",
        "moves",
        "live",
    }
)

_TELEMETRY_WINDOW_SECONDS: Final = 120.0
_GRAPH_DEGREE: Final = 2  # the SYS-05 2-degree perf lever's ceiling
_RETRIEVAL_K: Final = 5
_CONTEXT_MAX_TOKENS: Final = 4000
#: SEC-H3: an 8000-char message can carry hundreds of UUIDs; anchors and the
#: entity count are capped so a hostile query bounds DB work, not just the
#: rendered prompt (the SYS-05 sub-sampling lever, actually pulled).
MAX_ANCHORS: Final = 8
_MAX_ENTITIES: Final = 200


class QueryPlan(BaseModel):
    """What build_context should pull for one query — inspectable, like the
    Context it produces."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: GraphScope
    window: TelemetryWindow | None
    #: A LayeredContextBudget in practice (S5: per-layer caps ride along); typed
    #: as the base so every SolSystems pull keeps its contract.
    budget: ContextBudget
    k: int


def plan_query(query: str, *, mentions: Sequence[uuid.UUID] = ()) -> QueryPlan:
    """Deterministic pull-plan for a query. No model call, no I/O.

    `mentions` are entities the user pointed at explicitly (the composer's `@`).
    They lead the anchor list because they are deliberate, where a UUID found in
    the prose may just be quoted log output — so when `MAX_ANCHORS` bites, the
    inferred ids are the ones dropped. The cap binds them too: the request
    schema also limits the list, but a client is not trusted to respect it, and
    this cap is what bounds the neighbourhood query's DB work (SEC-H3).

    Mentioned ids are NOT checked for existence here. `load_neighborhood` is
    project-scoped, so an id from another team simply yields nothing — the same
    posture `get_entity` takes, and the reason there is no cross-tenant
    existence oracle to probe.
    """
    found = (uuid.UUID(match) for match in _UUID_RE.findall(query))
    anchors = list(dict.fromkeys([*mentions, *found]))[:MAX_ANCHORS]
    words = frozenset(re.findall(r"[a-z]+", query.lower()))
    runtime_shaped = bool(words & _RUNTIME_WORDS)
    return QueryPlan(
        scope=GraphScope(anchor_entity_ids=anchors, degree=_GRAPH_DEGREE),
        window=(
            TelemetryWindow(duration_seconds=_TELEMETRY_WINDOW_SECONDS) if runtime_shaped else None
        ),
        # S5: layer caps ride with the total; the total (_CONTEXT_MAX_TOKENS)
        # still binds every packed section — layers.py has the per-layer defaults.
        budget=LayeredContextBudget(
            max_tokens=_CONTEXT_MAX_TOKENS, max_entities=_MAX_ENTITIES, layers=LayerBudget()
        ),
        k=_RETRIEVAL_K,
    )


_CITATION_RE: Final = re.compile(r"\[[A-Za-z0-9._/#:-]+:[A-Za-z0-9._/#:-]+\]")


_SOURCES_LINE_RE: Final = re.compile(r"^\s*sources?\s*:.*$", re.IGNORECASE | re.MULTILINE)


def sanitize_reply(text: str, context: Context) -> tuple[str, tuple[str, ...]]:
    """The final reply, split into prose and PROVENANCE.

    Model prose cannot be the provenance surface: `_CITE_NOTE` trains the model
    to emit bracket tokens, so it could also write its own convincing
    "Sources:" line. Any model-authored Sources line is stripped from the
    prose, and the verified citations travel as structured data on the message
    event — a region model text cannot reach.

    KNOWN LIMIT (documented, not solved here): verification is token-set
    membership. A poisoned chunk can still tell the model to attribute a
    fabricated CLAIM to a genuine citation the context served — the citation
    list proves "these sources were in context", not "each sentence is faithful
    to its source". Per-claim binding is future work; renderers must not
    present the citation list as more than that."""
    prose = _SOURCES_LINE_RE.sub("", text).strip()
    return prose, verified_citations(text, context)


def verified_citations(text: str, context: Context) -> tuple[str, ...]:
    """The citations from `text` that the context actually contains, in first-
    appearance order, deduplicated. Model output is untrusted — a citation the
    context never served is stripped, not rendered as provenance."""
    genuine = {section.citation for section in context.sections if section.citation}
    seen: list[str] = []
    for token in _CITATION_RE.findall(text):
        if token in genuine and token not in seen:
            seen.append(token)
    return tuple(seen)
