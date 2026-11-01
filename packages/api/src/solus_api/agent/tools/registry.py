"""The `ToolRegistry` — the safety contract (SOLUS-W0-04).

`invoke()` NEVER raises. Every failure — unknown tool, bad args, tool exception,
timeout — comes back as a `ToolResult(ok=False)`. SOL always branches on `ok` and
reads `error`; it never try/catches and never sees a traceback. Tracebacks are logged
server-side and never placed in a result.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

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
    #: Validates a PARKED call's stored arguments (`stored_params`); None means
    #: the stored arguments are the model's and `validator` applies.
    stored_validator: Draft202012Validator | None = None


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
        validator = _compiled(tool.descriptor.params)
        # Optional, duck-typed like `preview`: a tool whose `stored_args` adds
        # Solus-derived fields declares their schema. Never shown to the model.
        stored_params = getattr(tool, "stored_params", None)
        stored = _compiled(stored_params) if stored_params is not None else None
        self._registry[name] = _Registration(tool, validator, stored_validator=stored)

    def tools(self) -> list[Tool]:
        """The registered tool OBJECTS, name-sorted.

        `list()` returns descriptors — the model's view. This is for SOLUS CODE
        that needs the tool itself, e.g. the confirmation flow asking a tool to
        describe its own diff (SOLUS-ONS-A5). Never handed to a model.
        """
        return [self._registry[name].tool for name in sorted(self._registry)]

    def list(self) -> list[ToolDescriptor]:
        """Every registered tool's descriptor, name-sorted for a stable model view."""
        descriptors = (reg.tool.descriptor for reg in self._registry.values())
        return sorted(descriptors, key=lambda d: d.name)

    async def invoke(self, call: ToolCall) -> ToolResult:
        """THE SAFETY SEQUENCE — look up, validate args, run (timeout-bounded and
        exception-trapped), return a `ToolResult`. This method NEVER raises.
        Arguments are validated against the MODEL schema (`descriptor.params`)."""
        return await self._invoke(call, stored=False)

    async def invoke_stored(self, call: ToolCall) -> ToolResult:
        """The same safety sequence for an APPROVED parked call: its stored
        arguments are validated against the tool's `stored_params` (falling back
        to the model schema). Only the confirmation gate calls this — model
        dispatch goes through `invoke`, so the model can never supply a
        stored-only field (SOLUSDEV-319)."""
        return await self._invoke(call, stored=True)

    async def _invoke(self, call: ToolCall, *, stored: bool) -> ToolResult:
        registration = self._registry.get(call.tool)
        if registration is None:
            return _failure(call, ToolErrorCode.NOT_FOUND, f"No tool named {call.tool!r}")

        validator = (stored and registration.stored_validator) or registration.validator
        try:
            schema_errors = sorted(validator.iter_errors(call.args), key=str)
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
        except BaseExceptionGroup as group:
            return _group_failure(call, group)
        except Exception:
            # Full traceback to the server log; the model only ever sees the generic message.
            logger.exception("tool %s (call %s) raised", call.tool, call.call_id)
            return _failure(call, ToolErrorCode.TOOL_ERROR, _INTERNAL_ERROR_MESSAGE)


def _compiled(schema: dict[str, Any]) -> Draft202012Validator:
    """Check a JSON Schema now (fail fast: raises SchemaError) and compile it."""
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _group_failure(call: ToolCall, group: BaseExceptionGroup) -> ToolResult:
    """THE HOLE IN "NEVER RAISES", closed once here for every tool kind.

    `except Exception` does not catch a `BaseExceptionGroup`. Verified on CPython
    3.12.3: the constructor downgrades an all-`Exception` group to
    `ExceptionGroup` (which IS an `Exception`, so it was already caught), but a
    group carrying a `CancelledError` stays a `BaseExceptionGroup` and escaped.
    Any tool whose transport runs an anyio task group — MCP over stdio or
    streamable-http, the bridge — can produce one when a cancel races a real
    failure. `exec.run_tool_calls` papers over it at BATCH level by filling
    unfinished slots, but `LlmRunner` dispatches sequentially and a bare
    `await registry.invoke(call)` had nothing underneath it.

    Cancellation still propagates: `wait_for` has already converted its OWN
    timeout, so a `CancelledError` arriving here is an EXTERNAL cancel (client
    gone, worker shutting down) and swallowing it would strand the turn.
    """
    if group.subgroup(asyncio.CancelledError) is not None:
        raise group
    first = _first_tool_exception(group)
    if first is not None:
        # A deliberate typed failure must survive being wrapped by a task group,
        # or "reconnect FeatureScript" becomes "the tool failed unexpectedly".
        return _failure(call, first.code, first.message, retryable=first.retryable)
    logger.exception("tool %s (call %s) raised a group", call.tool, call.call_id)
    return _failure(call, ToolErrorCode.TOOL_ERROR, _INTERNAL_ERROR_MESSAGE)


def _first_tool_exception(exc: BaseException) -> ToolException | None:
    """The first `ToolException` at any depth of a (possibly nested) group.

    A typed failure a tool raised deliberately must survive being wrapped by a
    task group: reporting it as the generic internal error would, for example,
    turn "reconnect FeatureScript" into "the tool failed unexpectedly".
    """
    if isinstance(exc, ToolException):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for member in exc.exceptions:
            found = _first_tool_exception(member)
            if found is not None:
                return found
    return None


def _failure(
    call: ToolCall, code: ToolErrorCode, message: str, *, retryable: bool = False
) -> ToolResult:
    return ToolResult.failure(
        call.call_id, ToolError(code=code, message=message, retryable=retryable)
    )
