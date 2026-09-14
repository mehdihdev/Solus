# SOLUSDEV-200 (SOLX-01) — the Guide/Do action-mode layer.
#
# A request resolves each action to GUIDE (explain + point, never operate) or
# DO (operate the tool through the gated dispatcher). This is a different axis
# from SolMode (ADR-016), which sets the TONE of natural-language output; the
# action mode decides whether SOL is allowed to change anything at all.
#
# The enforcement is structural, mirroring build_dispatch (CTR-03): a runner in
# Guide mode holds a dispatch closure that refuses mutating tools before the
# dispatcher is reached, so "Guide never dispatches a mutation" is unwritable
# rather than merely forbidden. The wrapper composes OUTSIDE the confirmation
# gate — Do mode passes through to the gate untouched and cannot weaken it.
#
# Every action is logged with its mode (`agent.tool_invoked`, the emission the
# agent-tool contract §7 assigns to the SOL loop): identifiers, mode, and
# outcome only — never argument values (CLAUDE.md §7). When the data-collection
# event store lands, this log call is the one place to add the event write.

from __future__ import annotations

import enum
import logging
from collections.abc import Awaitable, Callable, Iterable

from solus_api.agent.tools.shapes import (
    ToolCall,
    ToolDescriptor,
    ToolError,
    ToolErrorCode,
    ToolResult,
)

logger = logging.getLogger("solus.agent.modes")

# Structurally identical to runtime.DispatchFn; declared here (not imported)
# so the dependency stays one-directional: runtime imports modes, never back.
DispatchFn = Callable[[ToolCall], Awaitable[ToolResult]]


class ActionMode(enum.StrEnum):
    """How SOL is allowed to act on this request: explain, or operate."""

    GUIDE = "guide"
    DO = "do"


def mode_refusal(call: ToolCall) -> ToolResult:
    """The Guide-mode refusal for a mutating tool. Same envelope as the
    confirmation gate's refusal so runners and the UI branch on one shape."""
    return ToolResult.failure(
        call.call_id,
        ToolError(
            code=ToolErrorCode.UNAUTHORIZED,
            message=(
                f"{call.tool} changes the connected tool. Guide mode can explain "
                "the change; switch to Build mode to carry it out. "
                "Actions needing approval will still ask."
            ),
            retryable=False,
        ),
    )


def build_mode_dispatch(
    mode: ActionMode,
    descriptors: Iterable[ToolDescriptor],
    dispatch: DispatchFn,
) -> DispatchFn:
    """Wrap an already-gated dispatcher with the action-mode policy.

    GUIDE: calls to tools whose descriptor declares `requires_confirmation`
    (the CTR-03 mutation marker) are refused here — the wrapped dispatcher is
    never invoked for them. Everything else flows through unchanged, including
    unknown tool names (the registry answers NOT_FOUND; unknown is not treated
    as read-only, it is treated as the dispatcher's problem).

    DO: every call flows through to the gated dispatcher; destructive tools
    still park or refuse there. The mode layer never grants anything.

    Either way the action is logged with its mode — explicit, per action.
    """
    mutating = frozenset(d.name for d in descriptors if d.requires_confirmation)

    async def mode_dispatch(call: ToolCall) -> ToolResult:
        refused = mode is ActionMode.GUIDE and call.tool in mutating
        result = mode_refusal(call) if refused else await dispatch(call)
        # §7 logging: identifiers, mode, and outcome only — never args/values.
        logger.info(
            "agent.tool_invoked tool=%s call_id=%s mode=%s ok=%s mode_refused=%s",
            call.tool,
            call.call_id,
            mode.value,
            result.ok,
            refused,
        )
        return result

    return mode_dispatch
