"""The never-raises invariant across anyio task groups (SOLUSDEV-168).

`ToolRegistry.invoke` promises it NEVER raises, and `except Exception` was the
whole of that promise. It is not enough: the MCP transports (stdio and
streamable-http) and the bridge all run inside anyio task groups, and a task
group whose failure races a cancellation raises a `BaseExceptionGroup` — which
is NOT an `Exception`.

This is the one hole the FeatureScript handoff flagged as able to silently break
the invariant, so it is pinned here against the language itself, not against a
transport we would have to mock.
"""

import asyncio
from typing import Any

import pytest
from solus_api.agent.tools import (
    InProcessTool,
    ToolCall,
    ToolDescriptor,
    ToolErrorCode,
    ToolException,
    ToolRegistry,
)

NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


def _registry(boom: Exception | BaseException) -> ToolRegistry:
    async def handler(_args: dict[str, Any]) -> dict[str, Any]:
        raise boom

    registry = ToolRegistry()
    registry.register(
        InProcessTool(
            ToolDescriptor(
                name="explode",
                description="raises whatever it was given",
                params=NO_ARGS,
                returns={"type": "object"},
            ),
            handler,
        )
    )
    return registry


def test_the_language_actually_behaves_the_way_the_fix_assumes() -> None:
    """The premise, asserted rather than trusted: an all-`Exception` group is an
    `ExceptionGroup` (already caught), and one carrying a `CancelledError` is a
    `BaseExceptionGroup` (was not)."""
    assert isinstance(BaseExceptionGroup("g", [ValueError()]), Exception)
    assert not isinstance(
        BaseExceptionGroup("g", [ValueError(), asyncio.CancelledError()]), Exception
    )


async def test_a_group_of_ordinary_errors_is_a_structured_failure() -> None:
    result = await _registry(
        BaseExceptionGroup("transport", [OSError("connection reset"), RuntimeError("x")])
    ).invoke(ToolCall(tool="explode"))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.TOOL_ERROR
    assert "connection reset" not in result.error.message, "upstream text must not leak"


async def test_a_group_carrying_a_cancel_and_a_failure_does_not_escape() -> None:
    """THE REGRESSION. Before the fix this raised straight out of `invoke`."""
    group = BaseExceptionGroup("torn down", [OSError("reset"), asyncio.CancelledError()])
    with pytest.raises(BaseExceptionGroup):
        # Cancellation MUST still propagate — swallowing it would strand the turn
        # when the client disconnects or the worker shuts down.
        await _registry(group).invoke(ToolCall(tool="explode"))


async def test_a_pure_cancel_group_still_propagates() -> None:
    with pytest.raises(BaseExceptionGroup):
        await _registry(BaseExceptionGroup("cancelled", [asyncio.CancelledError()])).invoke(
            ToolCall(tool="explode")
        )


async def test_a_typed_failure_survives_being_wrapped_by_a_task_group() -> None:
    """Otherwise "reconnect FeatureScript" arrives as "the tool failed
    unexpectedly" and SOL cannot tell the user what to do."""
    wrapped = BaseExceptionGroup(
        "transport",
        [
            ToolException(
                "Reconnect FeatureScript on the Onshape source.",
                code=ToolErrorCode.UNAUTHORIZED,
                retryable=False,
            )
        ],
    )
    result = await _registry(wrapped).invoke(ToolCall(tool="explode"))
    assert result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED
    assert result.error.retryable is False
    assert "Reconnect FeatureScript" in result.error.message


async def test_a_typed_failure_nested_two_groups_deep_still_surfaces() -> None:
    inner = BaseExceptionGroup("inner", [ToolException("nope", code=ToolErrorCode.NOT_FOUND)])
    result = await _registry(BaseExceptionGroup("outer", [inner])).invoke(ToolCall(tool="explode"))
    assert result.error is not None
    assert result.error.code is ToolErrorCode.NOT_FOUND


async def test_an_ordinary_exception_is_unchanged() -> None:
    result = await _registry(RuntimeError("boom")).invoke(ToolCall(tool="explode"))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.TOOL_ERROR
    assert "boom" not in result.error.message
