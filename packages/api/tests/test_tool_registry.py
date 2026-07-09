"""The ToolRegistry safety contract (SOLUS-W0-04).

Every path proves the invariant: `invoke()` NEVER raises. Unknown tool, bad args,
tool exception, and timeout all come back as `ToolResult(ok=False)` — SOL only ever
branches on `ok` and reads `error`, and a traceback is never surfaced.
"""

import asyncio
from typing import Any

import pytest
from jsonschema.exceptions import SchemaError
from solus_api.agent.tools import (
    InProcessTool,
    ToolCall,
    ToolDescriptor,
    ToolError,
    ToolErrorCode,
    ToolException,
    ToolRegistry,
    ToolResult,
)

_X_SCHEMA = {
    "type": "object",
    "properties": {"x": {"type": "string"}},
    "required": ["x"],
    "additionalProperties": False,
}


async def _ok(args: dict[str, Any]) -> dict[str, Any]:
    return {"echoed": args}


def _tool(
    name: str,
    handler: Any,
    *,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> InProcessTool:
    return InProcessTool(
        ToolDescriptor(
            name=name,
            description="t",
            params=params or {"type": "object"},
            returns={"type": "object"},
            timeout_seconds=timeout,
        ),
        handler,
    )


def _err(result: ToolResult) -> ToolError:
    assert result.error is not None  # narrows the type; asserts the failure path
    return result.error


def test_register_and_list_returns_descriptors_sorted_by_name() -> None:
    reg = ToolRegistry()
    reg.register(_tool("bravo", _ok))
    reg.register(_tool("alpha", _ok))
    assert [d.name for d in reg.list()] == ["alpha", "bravo"]


def test_duplicate_registration_is_rejected() -> None:
    reg = ToolRegistry()
    reg.register(_tool("dup", _ok))
    with pytest.raises(ValueError):
        reg.register(_tool("dup", _ok))


def test_a_malformed_params_schema_fails_fast_at_registration() -> None:
    reg = ToolRegistry()
    with pytest.raises(SchemaError):
        reg.register(_tool("bad", _ok, params={"type": "not-a-real-type"}))


async def test_invoking_an_unknown_tool_returns_not_found_not_an_exception() -> None:
    reg = ToolRegistry()
    call = ToolCall(tool="ghost", args={})
    result = await reg.invoke(call)
    assert isinstance(result, ToolResult) and result.ok is False
    assert _err(result).code is ToolErrorCode.NOT_FOUND
    assert _err(result).retryable is False
    assert result.call_id == call.call_id  # correlation is preserved


async def test_bad_args_become_invalid_args_not_a_crash() -> None:
    reg = ToolRegistry()
    reg.register(_tool("needs_x", _ok, params=_X_SCHEMA))
    missing = await reg.invoke(ToolCall(tool="needs_x", args={}))
    assert _err(missing).code is ToolErrorCode.INVALID_ARGS
    wrong_type = await reg.invoke(ToolCall(tool="needs_x", args={"x": 123}))
    assert _err(wrong_type).code is ToolErrorCode.INVALID_ARGS


async def test_a_successful_call_returns_ok_with_the_handlers_value() -> None:
    reg = ToolRegistry()
    reg.register(_tool("echo", _ok))
    call = ToolCall(tool="echo", args={"a": 1})
    result = await reg.invoke(call)
    assert result.ok is True and result.error is None
    assert result.value == {"echoed": {"a": 1}}
    assert result.call_id == call.call_id


async def test_a_toolexception_maps_to_its_code_and_message() -> None:
    async def boom(args: dict[str, Any]) -> dict[str, Any]:
        raise ToolException("entity 42 not here", code=ToolErrorCode.NOT_FOUND)

    reg = ToolRegistry()
    reg.register(_tool("boom", boom))
    result = await reg.invoke(ToolCall(tool="boom", args={}))
    assert _err(result).code is ToolErrorCode.NOT_FOUND
    assert _err(result).message == "entity 42 not here"  # author message is safe to surface


# A distinctive, obviously-fake sentinel standing in for whatever internal detail an
# unexpected exception might carry (a DSN, a path, a token). It must never surface.
_INTERNAL_SENTINEL = "DO-NOT-SURFACE-internal-detail-xyz"


async def test_an_unexpected_exception_is_tool_error_with_no_traceback_leak() -> None:
    async def leak(args: dict[str, Any]) -> dict[str, Any]:
        raise ValueError(_INTERNAL_SENTINEL)

    reg = ToolRegistry()
    reg.register(_tool("leak", leak))
    result = await reg.invoke(ToolCall(tool="leak", args={}))
    assert _err(result).code is ToolErrorCode.TOOL_ERROR
    assert _err(result).retryable is False
    # the exception text (which could carry internals) is NEVER placed in the result:
    assert _INTERNAL_SENTINEL not in _err(result).message


async def test_a_slow_tool_times_out_as_a_retryable_result() -> None:
    async def slow(args: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(1)
        return {}

    reg = ToolRegistry()
    reg.register(_tool("slow", slow, timeout=0.05))
    result = await reg.invoke(ToolCall(tool="slow", args={}))
    assert _err(result).code is ToolErrorCode.TIMEOUT
    assert _err(result).retryable is True


async def test_a_tool_that_returns_a_non_dict_is_tool_error_not_a_raise() -> None:
    async def bad(args: dict[str, Any]) -> dict[str, Any]:
        return None  # type: ignore[return-value]  # a misbehaving tool

    reg = ToolRegistry()
    reg.register(_tool("bad_return", bad))
    # The invariant holds even for a buggy tool: a bad return is trapped, invoke never raises.
    result = await reg.invoke(ToolCall(tool="bad_return", args={}))
    assert _err(result).code is ToolErrorCode.TOOL_ERROR
