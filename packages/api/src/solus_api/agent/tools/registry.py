"""The `ToolRegistry` — the safety contract (SOLUS-W0-04).

`invoke()` NEVER raises. Every failure — unknown tool, bad args, tool exception,
timeout — comes back as a `ToolResult(ok=False)`. SOL always branches on `ok` and
reads `error`; it never try/catches and never sees a traceback. Tracebacks are logged
server-side and never placed in a result.
"""

import asyncio
import logging
from dataclasses import dataclass

from jsonschema import Draft202012Validator

from solus_api.agent.tools.shapes import (
    ToolCall,
    ToolDescriptor,
    ToolError,
    ToolErrorCode,
    ToolResult,
)
from solus_api.agent.tools.tool import Tool, ToolException

logger = logging.getLogger("solus.tools")

# ponytail: global default; a slow tool overrides it via descriptor.timeout_seconds.
DEFAULT_TIMEOUT_SECONDS = 30.0
# Generic message for unexpected exceptions — the traceback is logged, never surfaced.
_INTERNAL_ERROR_MESSAGE = "The tool failed unexpectedly."


@dataclass(frozen=True)
class _Registration:
    tool: Tool
    validator: Draft202012Validator


class ToolRegistry:
    """Holds the tool set and dispatches calls. Uniform: every tool looks identical to
    SOL, so adding a capability never rewires the agent."""

    def __init__(self, *, default_timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._registry: dict[str, _Registration] = {}
        self._default_timeout = default_timeout

    def register(self, tool: Tool) -> None:
        """Add a tool. Its `params` JSON Schema is validated now (fail fast on a bad
        schema) and cached as a compiled validator. Duplicate names are rejected so
        dispatch stays deterministic."""
        name = tool.descriptor.name
        if name in self._registry:
            raise ValueError(f"tool {name!r} is already registered")
        params = tool.descriptor.params
        Draft202012Validator.check_schema(params)  # raises SchemaError on a malformed schema
        validator = Draft202012Validator(params, format_checker=Draft202012Validator.FORMAT_CHECKER)
        self._registry[name] = _Registration(tool=tool, validator=validator)

    def list(self) -> list[ToolDescriptor]:
        """Every registered tool's descriptor, name-sorted for a stable model view."""
        descriptors = (reg.tool.descriptor for reg in self._registry.values())
        return sorted(descriptors, key=lambda d: d.name)

    async def invoke(self, call: ToolCall) -> ToolResult:
        """THE SAFETY SEQUENCE — look up, validate args, run (timeout-bounded and
        exception-trapped), return a `ToolResult`. This method NEVER raises."""
        registration = self._registry.get(call.tool)
        if registration is None:
            return _failure(call, ToolErrorCode.NOT_FOUND, f"No tool named {call.tool!r}")

        try:
            schema_errors = sorted(registration.validator.iter_errors(call.args), key=str)
        except Exception:
            # A schema can pass `check_schema` at register time yet explode during
            # validation (e.g. an unresolvable $ref) — that is the TOOL's defect,
            # not the caller's args, and it must not break the never-raises seam.
            logger.exception(
                "tool %s (call %s) schema failed during validation", call.tool, call.call_id
            )
            return _failure(call, ToolErrorCode.TOOL_ERROR, "The tool's schema is invalid.")
        if schema_errors:
            return _failure(call, ToolErrorCode.INVALID_ARGS, schema_errors[0].message)

        override = registration.tool.descriptor.timeout_seconds
        timeout = override if override is not None else self._default_timeout
        try:
            value = await asyncio.wait_for(registration.tool.invoke(call.args), timeout)
            # Built inside the try so a misbehaving tool (a None/non-dict return that
            # trips ToolResult's invariant) becomes a TOOL_ERROR, never an escaped raise.
            return ToolResult.success(call.call_id, value)
        except TimeoutError:
            return _failure(
                call, ToolErrorCode.TIMEOUT, f"Tool {call.tool!r} timed out", retryable=True
            )
        except ToolException as exc:
            return _failure(call, exc.code, exc.message, retryable=exc.retryable)
        except Exception:
            # Full traceback to the server log; the model only ever sees the generic message.
            logger.exception("tool %s (call %s) raised", call.tool, call.call_id)
            return _failure(call, ToolErrorCode.TOOL_ERROR, _INTERNAL_ERROR_MESSAGE)


def _failure(
    call: ToolCall, code: ToolErrorCode, message: str, *, retryable: bool = False
) -> ToolResult:
    return ToolResult.failure(
        call.call_id, ToolError(code=code, message=message, retryable=retryable)
    )
