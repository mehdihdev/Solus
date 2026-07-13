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
compiled at config load, sharing the MO-02b matcher machinery.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from solus_api.orchestration.complexity import scan_window
from solus_api.orchestration.enums import InteractionContext, RouteType

if TYPE_CHECKING:
    from collections.abc import Sequence

    from solus_api.orchestration.config import TypeEstimatorConfig

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
    """Cheap deterministic token estimate: len(text) // chars_per_token.
    A deliberate heuristic (no tokenizer dependency) — the divisor is a config
    knob; calibrate it if real usage shows drift."""
    return len(text) // config.chars_per_token


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
