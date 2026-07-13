"""Query-based complexity estimation (MO-02) — the LAST fallback in the tier chain.

There are TWO ways a call's `Complexity` tier is determined, and they do not
conflict because the gateway consults them in a fixed order:

1. CONTEXT-based (`router.derive_complexity`, already functional — preferred):
   when the calling code knows the interaction context (e.g. editor
   autocomplete -> TRIVIAL), the tier comes from `CONTEXT_COMPLEXITY_DEFAULTS`.
2. QUERY-based (this module): when NO explicit complexity and NO context are
   supplied, deterministic text heuristics estimate the tier from the query.

Gateway resolution order (`gateway.stream`): explicit `complexity` arg ->
`derive_complexity(context)` if a context is supplied -> `estimate_complexity`
-> STANDARD (the estimator's own safe default when signals are absent or
ambiguous). No call ever goes unrouted.

Heuristics, not ML — deliberately transparent and debuggable: query length,
work-implying phrasing, diagnostic language, and domain breadth (a query
spanning code AND electronics AND mechanics needs cross-domain reasoning ->
harder). Every knob lives in `models.yaml` (`estimator:` section): entries are
EXPLICIT REGEX PATTERNS (MO-02b), compiled + validated at config load with
IGNORECASE — the pattern author writes anchors and morphology, so
`\\bdrift(s|ing|ed)?\\b` hits "drifting" but never "adrift", and
"currently"/"framework"/"ARM64" cannot fire the current/frame/arm markers.
Tuning "what counts as HARD" is a config edit, never a code change. NO model
call is made here — estimation must be free, instant, and deterministic (an
LLM-based estimator would be circular: a model call to decide the model call).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from solus_api.orchestration.enums import Complexity

if TYPE_CHECKING:
    import re

    from solus_api.orchestration.config import EstimatorConfig

logger = logging.getLogger("solus.orchestration.complexity")


def scan_window(text: str, max_chars: int) -> str:
    """The slice regex scans run over: first+last `max_chars` (signals cluster
    at the edges — a pasted log with the question at the end still hits). The
    newline seam prevents cross-boundary false matches. Length/size signals
    always measure the FULL text; this bound exists so a 1MB paste can never
    pin the event loop (security M1)."""
    if len(text) <= 2 * max_chars:
        return text
    return f"{text[:max_chars]}\n{text[-max_chars:]}"


def _distinct_hits(text: str, patterns: list[re.Pattern[str]]) -> int:
    """Count how many of a family's precompiled patterns match `text`.
    Distinct patterns only, so repetition cannot stack score."""
    return sum(1 for pattern in patterns if pattern.search(text))


def estimate_complexity(query: str, *, config: EstimatorConfig) -> Complexity:
    """Estimate a query's routing tier from its text alone — pure, deterministic,
    no model call. Same (query, config) -> same tier, always.

    STANDARD is the safe default: blank or signal-free-but-long queries land
    there rather than crashing, guessing TRIVIAL-and-underpowered, or guessing
    HARD-and-expensive.
    """
    word_count = len(query.split())
    if word_count == 0:
        return Complexity.STANDARD
    scannable = scan_window(query, config.scan_max_chars)
    tool_hits = _distinct_hits(scannable, config.tool_patterns)
    reasoning_hits = _distinct_hits(scannable, config.reasoning_patterns)
    domains = sum(
        1 for group in config.domain_patterns.values() if _distinct_hits(scannable, group)
    )
    score = (
        (config.weights.long_query if word_count >= config.hard_min_words else 0)
        + config.weights.tool_signal * tool_hits
        + config.weights.reasoning_signal * reasoning_hits
        + config.weights.extra_domain * max(0, domains - 1)
    )
    # §7: counts and score only — NEVER the query text.
    logger.debug(
        "complexity estimate words=%d tool_hits=%d reasoning_hits=%d domains=%d score=%d",
        word_count,
        tool_hits,
        reasoning_hits,
        domains,
        score,
    )
    if score >= config.hard_threshold:
        return Complexity.HARD
    if score >= config.standard_threshold:
        return Complexity.STANDARD
    if word_count <= config.trivial_max_words:
        return Complexity.TRIVIAL
    return Complexity.STANDARD
