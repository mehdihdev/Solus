"""Query-TYPE estimation (MO-04) — the fallback rung of the type chain.

Deliberately symmetric with the complexity chain (see `complexity.py`):

    explicit `type` arg -> `derive_type(context)` when the caller knows the
    interaction -> `estimate_type(query, attachments)` -> GENERAL.

The estimator is the FALLBACK, not the only path — SOL and source-driven
callers often KNOW the type (a log artifact -> VISUAL_LOG, a code repo ->
CODE) and should supply it or a context.

PRECEDENCE inside the estimator (the design rule — hard constraints beat soft
preferences): LONG_CONTEXT (the window is a physical constraint: the input
must FIT) > VISUAL_LOG (modality is a physical constraint: the model must be
able to SEE the artifact) > CODE (a strength preference — a weaker-at-code
model still works) > GENERAL. Size is MEASURED (chars/attachment token hints),
never inferred from wording.

Deterministic, pure, NO model call; every knob lives in `models.yaml`
(`type_estimator:`, see `TypeEstimatorConfig`) — patterns are explicit regexes
compiled at config load, sharing the MO-02b matcher machinery. The one constant here,
`CODE_WINDOW_SHARE`, is a safety margin, not a knob.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field

from solus_api.graph.kinds import ARDUINO_SKETCH, CODE_FILE, CODE_MODULE
from solus_api.orchestration.complexity import scan_window
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.orchestration.router import route

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from solus_api.orchestration.config import OrchestrationConfig, TypeEstimatorConfig

logger = logging.getLogger("solus.orchestration.type_estimator")


class AttachmentHint(BaseModel):
    """A measurable fact about an attached artifact: what kind it is and how
    many tokens it contributes to the assembled context. Supplied by callers —
    never inferred."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str  # e.g. "image", "log", "file" — matched against config kinds
    tokens: int = Field(default=0, ge=0)


# Context -> type, mirroring router.CONTEXT_COMPLEXITY_DEFAULTS (which stays
# untouched in router.py). Extend as new callers appear.
CONTEXT_TYPE_DEFAULTS: dict[InteractionContext, RouteType] = {
    InteractionContext.CODE_AUTOCOMPLETE: RouteType.CODE,
    InteractionContext.TELEMETRY_SUMMARY: RouteType.VISUAL_LOG,
    InteractionContext.SOL_OPEN_QUESTION: RouteType.GENERAL,
    InteractionContext.COMPATIBILITY_RESEARCH: RouteType.GENERAL,
}


def derive_type(context: InteractionContext) -> RouteType:
    """Context rung of the type chain — deterministic dict lookup, no model
    call. Unknown contexts fall back to GENERAL."""
    return CONTEXT_TYPE_DEFAULTS.get(context, RouteType.GENERAL)


def estimate_tokens(text: str, *, config: TypeEstimatorConfig) -> int:
    """Cheap deterministic token estimate: len(text) // chars_per_token, floored
    at 1 (a section is never free). A deliberate heuristic (no tokenizer
    dependency) — the divisor is a config knob; calibrate it if real usage shows
    drift.

    THE one estimator: context packing and routing both call this, and
    tests/test_token_estimator_ratchet.py keeps every other char/token
    computation out of `agent/` and `orchestration/`."""
    return max(1, len(text) // config.chars_per_token)


def chars_for_tokens(tokens: int, *, config: TypeEstimatorConfig) -> int:
    """Inverse of `estimate_tokens`: how many characters `tokens` tokens span
    under the same knob — for clipping text to a token budget without a second
    copy of the ratio."""
    return tokens * config.chars_per_token


def estimate_type(
    query: str,
    *,
    config: TypeEstimatorConfig,
    attachments: Sequence[AttachmentHint] | None = None,
) -> RouteType:
    """Estimate a query's RouteType from its text + measurable attachments —
    pure, deterministic, no model call. See module docstring for precedence."""
    attached = tuple(attachments or ())
    total_tokens = estimate_tokens(query, config=config) + sum(a.tokens for a in attached)
    if total_tokens >= config.long_context_min_tokens:
        # Size decides FIRST (highest precedence) — and the regex scans never
        # run on inputs the size rule already settled (security M1).
        logger.debug("type estimate tokens=%d -> long_context (size rule)", total_tokens)
        return RouteType.LONG_CONTEXT
    scannable = scan_window(query, config.scan_max_chars)
    visual_kinds = {kind.lower() for kind in config.visual_attachment_kinds}
    code_hits = sum(1 for pattern in config.code_regexes if pattern.search(scannable))
    visual_hits = sum(1 for pattern in config.visual_regexes if pattern.search(scannable))
    has_visual_attachment = any(a.kind.lower() in visual_kinds for a in attached)
    # §7: counts and sizes only — never the query text.
    logger.debug(
        "type estimate tokens=%d code_hits=%d visual_hits=%d visual_attachment=%s",
        total_tokens,
        code_hits,
        visual_hits,
        has_visual_attachment,
    )
    if has_visual_attachment or visual_hits >= config.visual_min_hits:
        return RouteType.VISUAL_LOG
    if code_hits >= config.code_min_hits:
        return RouteType.CODE
    return RouteType.GENERAL


#: Entity kinds that make a turn's scope code (SOLUSDEV-321 P0-T7); a repository on its own
#: does not. The scope planner's `read_code_file` targets are of these kinds too (P1-T1).
CODE_KINDS: Final = frozenset({CODE_FILE, CODE_MODULE, ARDUINO_SKETCH})
#: The share of the CODE role's window a turn's measured input may fill for round 1 to ask for
#: CODE explicitly. An explicit type REFUSES on overflow (`resolution.resolve_routing`) rather
#: than escalating, so 20 % stays spare: headroom for the later rounds, which keep round 1's
#: route.
CODE_WINDOW_SHARE: Final = 0.8


def route_type_for_kinds(
    kinds: Iterable[str], text: str, *, config: TypeEstimatorConfig
) -> RouteType | None:
    """CODE when the turn is anchored on code (a code file, module or sketch among the anchors'
    `kinds`) or when the
    estimator reads `text` as code; otherwise None. Never VISUAL_LOG or LONG_CONTEXT:
    those stay with the estimator and the attachments. Pure, no model call."""
    if not CODE_KINDS.isdisjoint(kinds) or estimate_type(text, config=config) is RouteType.CODE:
        return RouteType.CODE
    return None


def round_one_complexity(explicit: Complexity | None, *, about_finding: bool) -> Complexity | None:
    """The tier a SOL turn's first round passes explicitly (SOLUSDEV-321 P0-T7): HARD for a
    turn about a finding, above "think harder" too; otherwise `explicit`, which is "think
    harder"'s tier, or None to leave the gateway's estimator to decide. Pure, no model call."""
    return Complexity.HARD if about_finding else explicit


def round_one_route_type(
    hint: RouteType | None,
    *,
    query: str,
    tier: Complexity,
    config: OrchestrationConfig,
) -> RouteType | None:
    """The type a SOL turn's first round passes explicitly (SOLUSDEV-321 P0-T7): CODE when the
    scope planner's `hint` is CODE (`TurnScope.type_hint`, P1-T1: `route_type_for_kinds` over
    the anchored kinds and the person's message), AND the measured `query` (what the gateway
    measures) fills at most `CODE_WINDOW_SHARE` of the window of the CODE role at `tier`, the
    tier round 1 routes at. Otherwise None: the call stays system-routed, so a window miss
    escalates instead of being refused. Pure, no model call."""
    if hint is not RouteType.CODE:
        return None
    choice = route(query, tier, RouteType.CODE, config=config)
    tokens = estimate_tokens(query, config=config.type_estimator)
    if tokens <= CODE_WINDOW_SHARE * choice.context_window:
        return RouteType.CODE
    # Sizes only, never the text (§7).
    logger.info(
        "explicit code type withheld: ~%d tokens > %s of role=%s window=%d",
        tokens,
        CODE_WINDOW_SHARE,
        choice.role,
        choice.context_window,
    )
    return None
