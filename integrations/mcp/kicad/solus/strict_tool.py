"""Validate owned tool arguments before FastMCP 2's coercing function adapter."""

import inspect
from collections.abc import Callable
from typing import Any

from fastmcp.tools.tool import FunctionTool, ToolResult
from pydantic import BaseModel, ConfigDict, PrivateAttr, ValidationError, create_model


class StrictFunctionTool(FunctionTool):
    _argument_model: type[BaseModel] = PrivateAttr()

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            self._argument_model.model_validate(arguments)
        except ValidationError:
            raise ValueError("invalid_arguments") from None
        return await super().run(arguments)


def register_strict_tool(backing: Any, fn: Callable[..., Any], **options: Any) -> None:
    fields: dict[str, Any] = {
        name: (
            parameter.annotation,
            ... if parameter.default is inspect.Parameter.empty else parameter.default,
        )
        for name, parameter in inspect.signature(fn).parameters.items()
    }
    model = create_model(
        fn.__name__ + "Arguments",
        __config__=ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True),
        **fields,
    )
    tool = StrictFunctionTool.from_function(fn, **options)
    if not isinstance(tool, StrictFunctionTool):
        raise TypeError("Owned tool registration failed")
    tool._argument_model = model
    tool.parameters = model.model_json_schema()
    backing.add_tool(tool)
