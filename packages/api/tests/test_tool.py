"""The Tool protocol's v1 implementation + ToolException (SOLUS-W0-04)."""

from typing import Any

from solus_api.agent.tools import (
    InProcessTool,
    ToolDescriptor,
    ToolErrorCode,
    ToolException,
)

_DESC = ToolDescriptor(
    name="echo", description="echo the args", params={"type": "object"}, returns={"type": "object"}
)


async def test_inprocesstool_exposes_its_descriptor_and_runs_the_handler() -> None:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        return {"got": args}

    tool = InProcessTool(_DESC, handler)
    assert tool.descriptor.name == "echo"  # advertises its descriptor
    assert await tool.invoke({"x": 1}) == {"got": {"x": 1}}  # invoke runs the callable


def test_toolexception_carries_a_typed_code_message_and_retryable() -> None:
    exc = ToolException("gone", code=ToolErrorCode.NOT_FOUND, retryable=False)
    assert exc.code is ToolErrorCode.NOT_FOUND
    assert exc.message == "gone"
    assert exc.retryable is False
    assert str(exc) == "gone"  # message flows to the base Exception too


def test_toolexception_defaults_to_a_permanent_tool_error() -> None:
    default = ToolException("boom")
    assert default.code is ToolErrorCode.TOOL_ERROR
    assert default.retryable is False
