"""Orchestration enums (ADR-026). Values are lowercase to match the repo's
StrEnum convention (see `solus_api.models.CreditTxnType`) and the keys used in
`models.yaml`.

All three enums are **extensible**: adding a member is a config + (for the
gateway/matrix) a `models.yaml` change, never a change to `route()` logic.
"""

import enum


class Complexity(enum.StrEnum):
    """Routing tier, derived automatically by the Step-1 gateway — never supplied
    by the end user (see `router.derive_complexity`)."""

    TRIVIAL = "trivial"
    STANDARD = "standard"
    HARD = "hard"


class RouteType(enum.StrEnum):
    """Query kind, routed to the frontier model whose strength matches it. A REAL
    v1 input (not a no-op): e.g. Gemini-class models are strong for VISUAL_LOG /
    LONG_CONTEXT, Claude-class for CODE. `GENERAL` is the fallback when `type` is
    None. Truly-specialist future models (e.g. spatial reasoning) get new members
    here without touching routing code."""

    CODE = "code"
    VISUAL_LOG = "visual_log"
    LONG_CONTEXT = "long_context"
    GENERAL = "general"


class InteractionContext(enum.StrEnum):
    """What kind of interaction the caller is in. The gateway maps this →
    `Complexity` with no model call. Extend as new callers appear."""

    CODE_AUTOCOMPLETE = "code_autocomplete"
    TELEMETRY_SUMMARY = "telemetry_summary"
    SOL_OPEN_QUESTION = "sol_open_question"
    COMPATIBILITY_RESEARCH = "compatibility_research"
