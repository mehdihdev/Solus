"""MO-04 pre-flight classification preview (`POST /api/v1/orchestration/classify`).

Returns the EXACT routing a completion would use — both this endpoint and the
gateway call the same `resolve_routing` on the same cached config, so the
preview cannot lie by construction. Makes NO provider call, debits NO credits,
and never touches the MO-03 model-call frequency cap (it is not a model call);
it carries its own generous rate bucket instead (`classify_rate_limit_per_minute`,
wired in main.py). Auth-required; the handler itself does no DB work.

Each override option carries VIABILITY: whether the model that value would
route to can actually hold this request, with a short reason when it can't —
that powers the UI's tiny "Too many tokens for this tier" message BEFORE the
user commits. Advisory only: the gateway independently enforces the window
guard on the real call (the client is never trusted).
"""

from typing import Any

from fastapi import APIRouter

from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser
from solus_api.orchestration import SOL_REASONER_NAME, bump_complexity, estimate_complexity
from solus_api.orchestration.config import OrchestrationConfig
from solus_api.orchestration.enums import Complexity, RouteType
from solus_api.orchestration.gateway import default_orchestration_config
from solus_api.orchestration.resolution import ResolvedRouting, resolve_routing
from solus_api.orchestration.type_estimator import AttachmentHint
from solus_api.schemas import ClassifyRequest

router = APIRouter(prefix="/api/v1")

#: S1-W3: what the user sees instead of a tier's model — effort on ONE reasoner.
_EFFORT: dict[Complexity, str] = {
    Complexity.TRIVIAL: "quick",
    Complexity.STANDARD: "standard",
    Complexity.HARD: "deep",
}


def _cost_tier(price_out: float, config: OrchestrationConfig) -> str:
    """Coarse relative cost from config prices only (terciles of the catalog's
    price_out range) — never raw prices or margins."""
    prices = [entry.price_out for entry in config.catalog]
    lo, hi = min(prices), max(prices)
    if hi == lo:
        return "standard"
    position = (price_out - lo) / (hi - lo)
    if position <= 1 / 3:
        return "low"
    if position <= 2 / 3:
        return "standard"
    return "premium"


def _option(resolved: ResolvedRouting, value: str, config: OrchestrationConfig) -> dict[str, Any]:
    return {
        "value": value,
        "viable": resolved.fits,
        "reason": resolved.reason,
        "cost_tier": _cost_tier(resolved.choice.price_out, config),
    }


@router.post("/orchestration/classify")
async def classify(body: ClassifyRequest, user: CurrentUser) -> dict[str, Any]:
    config = default_orchestration_config()
    attachments = tuple(AttachmentHint(kind=a.kind, tokens=a.tokens) for a in body.attachments)
    complexity = body.complexity
    if body.think_harder:
        # Mirrors LlmRunner: bump the (explicit or estimated) tier and pass it
        # EXPLICITLY, so an overflow refuses rather than escalates — same call.
        complexity = bump_complexity(
            complexity or estimate_complexity(body.query, config=config.estimator)
        )
    headline = resolve_routing(
        body.query,
        complexity=complexity,
        context=body.context,
        type=body.type,
        attachments=attachments,
        config=config,
    )
    # Option viability == exactly what picking that value would do: both axes
    # explicit (the pick + the currently-resolved other axis), same resolver.
    complexity_options = [
        _option(
            resolve_routing(
                body.query,
                complexity=tier,
                type=headline.choice.route_type,
                attachments=attachments,
                config=config,
            ),
            tier.value,
            config,
        )
        for tier in Complexity
    ]
    type_options = [
        _option(
            resolve_routing(
                body.query,
                complexity=headline.choice.complexity,
                type=route_type,
                attachments=attachments,
                config=config,
            ),
            route_type.value,
            config,
        )
        for route_type in RouteType
    ]
    return envelope(
        {
            "complexity": headline.choice.complexity.value,
            "type": headline.choice.route_type.value,
            "reasoner": {
                "name": SOL_REASONER_NAME,
                "effort": _EFFORT[headline.choice.complexity],
            },
            "cost_tier": _cost_tier(headline.choice.price_out, config),
            "source": {
                "complexity": headline.complexity_source,
                "type": headline.type_source,
            },
            "tokens_estimate": headline.tokens_estimate,
            "viable": headline.fits,
            "reason": headline.reason,
            "escalated": headline.escalated,
            "options": {"complexities": complexity_options, "types": type_options},
        }
    )
