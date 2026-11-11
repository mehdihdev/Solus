"""SOLUSDEV-322 P2-T2 — the per-call confirmation hook.

`ToolDescriptor.requires_confirmation` is static: one answer for every call. Simulator tools
need a per-call answer — the same action needs no card inside a session Solus itself started
and always needs one inside a session a person started — so a tool may carry a duck-typed
`needs_confirmation(args) -> bool` hook (like `preview`, not part of the `Tool` protocol).

`needs_card` is the ONE place that reads it, consulted beside the static flag by the fused
dispatch (`runtime.gate_tool_call`, `confirmations.request_confirmation`) and the Guide mode
layer (`modes.build_mode_dispatch`). It fails closed: the static flag wins without consulting
the hook, and a hook that raises or outlasts `HOOK_TIMEOUT_SECONDS` is a card.

`current_call_id` is set by `runtime.build_dispatch.gated` for the duration of one dispatch,
so a wrapper that starts a session can record which call started it without a signature
change. Outside a dispatch (the `decide_confirmation` replay path) it reads `None`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextvars import ContextVar
from typing import Any, Final

from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolError, ToolErrorCode, ToolResult
from solus_api.agent.tools.tool import Tool

logger = logging.getLogger("solus.agent.dynamic_gate")

#: Duck-typed attribute `needs_confirmation` on a Tool: the call's args → "card it?".
GateHook = Callable[[dict[str, Any]], Awaitable[bool]]
HOOK_TIMEOUT_SECONDS: Final = 5.0

#: The `call_id` of the dispatch in flight, `None` outside one.
current_call_id: ContextVar[str | None] = ContextVar("solus_current_call_id", default=None)

#: A preview row with this label means the tool itself demands a human approval for this
#: call (ADR-040 §5). It can only make a call stricter: Build's owned-routine policy defers
#: such a call to the card, and a simulator wrapper's hook cards it even on a session Solus
#: owns (P10 item 22).
APPROVAL_REQUIRED_LABEL: Final = "Approval required"


def approval_required(rows: Iterable[Any]) -> bool:
    """True when any preview row carries `APPROVAL_REQUIRED_LABEL` as its label."""
    return any(
        isinstance(row, Mapping) and row.get("label") == APPROVAL_REQUIRED_LABEL for row in rows
    )


async def needs_card(tool: Tool, args: Mapping[str, Any]) -> bool:
    """True when this concrete call must be shown to a person before it runs."""
    if tool.descriptor.requires_confirmation:
        return True
    hook: GateHook | None = getattr(tool, "needs_confirmation", None)
    if hook is None:
        return False
    try:
        return bool(await asyncio.wait_for(hook(dict(args)), HOOK_TIMEOUT_SECONDS))
    except Exception:
        # Fail closed (CLAUDE.md §7): where ownership cannot be proven, the answer is a card.
        logger.warning("confirmation hook failed for %.128r; carding", tool.descriptor.name)
        return True


async def with_current_call_id(
    dispatch: Callable[[ToolCall], Awaitable[ToolResult]], call: ToolCall
) -> ToolResult:
    """Run one dispatch with `current_call_id` set to its `call_id`. Same task through
    `run_tool` and the registry's `wait_for` on 3.12; reset so it never leaks to the runner."""
    token = current_call_id.set(call.call_id)
    try:
        return await dispatch(call)
    finally:
        current_call_id.reset(token)


def registered_tool(registry: ToolRegistry, name: str) -> Tool | None:
    """The tool OBJECT (the hook lives on it, not on the descriptor). Never handed to a model."""
    return next((t for t in registry.tools() if t.descriptor.name == name), None)


async def registry_needs_card(registry: ToolRegistry, call: ToolCall) -> bool:
    """`needs_card` by name; an unknown tool is the dispatcher's problem (NOT_FOUND), not a card."""
    tool = registered_tool(registry, call.tool)
    return tool is not None and await needs_card(tool, call.args)


def flow_unavailable_refusal(call: ToolCall) -> ToolResult:
    """The no-park fallback's refusal — one message whether the static flag or the hook said so."""
    return ToolResult.failure(
        call.call_id,
        ToolError(
            code=ToolErrorCode.UNAUTHORIZED,
            message=(
                f"{call.tool} is a destructive action requiring explicit user "
                "confirmation; the confirmation flow is not yet available"
            ),
            retryable=False,
        ),
    )
