"""Code-owned Build authorization; advertised tool metadata cannot opt into it."""

from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from typing import Any

from solus_api.agent.command_auto import AUTO_COMMAND_TOOL, SYSTEM_SCOPE, auto_eligible
from solus_api.agent.confirmations import _build_preview, validate_tool_arguments
from solus_api.agent.modes import ActionMode
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolError, ToolErrorCode, ToolResult
from solus_api.agent.tools.tool import Tool

logger = logging.getLogger("solus.agent.execution_policy")
_AUTHORITY = object()
_ONSHAPE = frozenset(
    {
        "onshape.create_circle_sketch",
        "onshape.extrude_cut",
        "onshape.set_variable",
        "onshape.update_feature",
        "onshape.insert_part",
        "onshape.create_face_mate_connector",
        "onshape.create_circle_mate_connector",
        "onshape.create_fastened_mate",
        "onshape.restore_fastened_pose",
        "onshape.create_revolute_mate",
    }
)
_ISAAC = frozenset(
    {
        "isaac.start",
        "isaac.stop",
        "isaac.load_model",
        "isaac.set_joint_limits",
        "isaac.set_sensor_pose",
        "isaac.run_routine",
    }
)
# Reviewed native schemas, canonical JSON SHA256. A fork schema change requires
# review before automatic execution; it cannot expand its own authority.
_BRIDGE_SCHEMAS = {
    "kicad.set_symbol_property": "fe54d27bb16d416c581bd0e935214c727494cb19dde9118087f3a2b68ef95460",
    "kicad.create_schematic": "1abaefefb6d7b3d1ce1991a6f3cd9ae0866dbd5fb0e25b8d258967b624069697",
    "kicad.add_symbol": "5fefa1e99937b7296ba450416560c3dba64463169278ef49d5644b905c601069",
    "kicad.add_wire": "5e6e4a48cc7945f30ca4e991d6957455bf12b97cfa3369bd084819f4f8711b3a",
    "kicad.add_net_label": "a33b8244417c825119c92bbf85cb2ef83dd4063af4eeb948ff2cc57dc3b50b49",
    "kicad.mark_no_connect": "17ad67f23274702a4adf46d6a03f140a7465c8fa448dfd4d79f379be357bff81",
    "code.git_commit": "4e10d162cd7921a0ea88d7b2440421d2818da182c2d82cc0b07ad863d4195665",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def register_owned_routine(tool: Tool, *, family: str) -> None:
    """Called only by trusted assembly, after scope and implementation binding."""
    from solus_api.agent.tools.isaac_tools import IsaacTool
    from solus_api.agent.tools.machine_writes import MachineWriteTool
    from solus_api.bridge.tool import BridgeTool
    from solus_api.connectors.onshape_confirmation import ConfirmedOnshapeTool
    from solus_api.services.code_environment_adapter import PlannedTool

    name = tool.descriptor.name
    eligible = (
        (family == "onshape" and type(tool) is ConfirmedOnshapeTool and name in _ONSHAPE)
        or (family == "isaac" and type(tool) is IsaacTool and name in _ISAAC)
        or (family == "machine" and type(tool) is MachineWriteTool and name == "machine.write_file")
        # §10.1: the plan-snapshot `code.exec` ONLY, and never as a blanket
        # routine — `prepare` re-judges every call (`auto_eligible`, program_scope).
        or (family == "command" and type(tool) is PlannedTool and name == AUTO_COMMAND_TOOL)
    )
    if family == "bridge" and type(tool) is BridgeTool and name in _BRIDGE_SCHEMAS:
        digest = hashlib.sha256(_canonical(tool.descriptor.params).encode()).hexdigest()
        eligible = digest == _BRIDGE_SCHEMAS[name]
    if (
        eligible
        and tool.descriptor.requires_confirmation
        and getattr(tool, "requires_complete_preview", False) is True
        and callable(getattr(tool, "preview", None))
    ):
        owned: Any = tool
        owned._build_authority = _AUTHORITY, _canonical(tool.descriptor.model_dump())


def _refuse(
    call: ToolCall, message: str, code: ToolErrorCode = ToolErrorCode.UNAUTHORIZED
) -> ToolResult:
    return ToolResult.failure(call.call_id, ToolError(code=code, message=message, retryable=False))


def _program_scope(tool: Tool, args: dict[str, Any]) -> str | None:
    """The plan-snapshot's `program_scope` for `args` (PlannedTool), else None."""
    reader = getattr(tool, "program_scope", None)
    scope = reader(args) if callable(reader) else None
    return scope if isinstance(scope, str) else None


class BuildExecutionPolicy:
    """One turn's authorizations; consuming before await prevents parallel replay."""

    def __init__(
        self, registry: ToolRegistry, mode: ActionMode, *, force_confirmation: bool = False
    ) -> None:
        self.registry = registry
        self.mode = mode
        self._force_confirmation = force_confirmation
        self._consumed: set[str] = set()
        self._consumed_ids: set[str] = set()
        #: Command keys whose plan kept the card (§10.1): later identical calls
        #: go straight to the gate, never to "already attempted".
        self._deferred: set[str] = set()
        self.executed_calls: set[str] = set()

    async def prepare(self, call: ToolCall) -> bool | ToolResult:
        # Review-only requests retain the normal central confirmation gate,
        # including for tools otherwise eligible for automatic Build execution.
        tool = None if self._force_confirmation else self._owned(call)
        if tool is None:
            return False
        command = call.tool == AUTO_COMMAND_TOOL
        # §10.1: a command is judged per call BEFORE anything is planned; a
        # risky, denied or oddly shaped one goes to the card (or its refusal).
        if command and not auto_eligible(call.args):
            return False
        claimed = self._claim(tool, call)
        if not isinstance(claimed, str):
            return claimed
        # Same-task previews preserve scoped adapter ContextVar bindings. The
        # second observation must match the first; invoke checks native state too.
        quota_failures: list[str] = []
        before = await _build_preview(
            tool, deepcopy(call.args), force_complete=True, quota_failures=quota_failures
        )
        scopes = [_program_scope(tool, call.args)]
        if not before:
            return _refuse(
                call,
                quota_failures[0]
                if quota_failures
                else "The complete routine preview is unavailable. Nothing was executed.",
                ToolErrorCode.UNAVAILABLE,
            )
        after = await _build_preview(
            tool, deepcopy(call.args), force_complete=True, quota_failures=quota_failures
        )
        scopes.append(_program_scope(tool, call.args))
        if quota_failures:
            return _refuse(call, quota_failures[0], ToolErrorCode.UNAVAILABLE)
        if not after or before != after:
            return _refuse(
                call,
                "The routine changed during validation. "
                "Nothing was executed; inspect current state.",
            )
        if command and scopes != [SYSTEM_SCOPE, SYSTEM_SCOPE]:
            # A workspace (or unknown) program is project code: it keeps its card.
            self._deferred.add(claimed)
            return False
        return True

    def _owned(self, call: ToolCall) -> Tool | None:
        tool = next(
            (tool for tool in self.registry.tools() if tool.descriptor.name == call.tool), None
        )
        if self.mode is not ActionMode.DO or tool is None:
            return None
        authority = getattr(tool, "_build_authority", None)
        if authority != (_AUTHORITY, _canonical(tool.descriptor.model_dump())):
            return None
        return tool

    def _claim(self, tool: Tool, call: ToolCall) -> str | bool | ToolResult:
        """Validate and consume the call BEFORE any await; the consumed key, or
        False (back to the gate) / a refusal."""
        invalid = validate_tool_arguments(tool.descriptor, call.args)
        if invalid:
            return _refuse(call, "Invalid routine arguments.", ToolErrorCode.INVALID_ARGS)
        try:
            key = _canonical({"tool": call.tool, "args": call.args})
        except (TypeError, ValueError):
            return _refuse(call, "Invalid routine arguments.", ToolErrorCode.INVALID_ARGS)
        if key in self._deferred:
            return False  # already sent to the card once; the gate dedups it
        if key in self._consumed or call.call_id in self._consumed_ids:
            return _refuse(
                call,
                "This Build action was already attempted. "
                "Inspect its outcome; do not retry automatically.",
            )
        self._consumed.add(key)
        self._consumed_ids.add(call.call_id)
        return key

    def execution_started(self, call: ToolCall) -> None:
        self.executed_calls.add(call.call_id)
        logger.info(
            "build action authorized tool=%s call_id=%s authorization_origin=build_policy",
            call.tool,
            call.call_id,
        )

    @staticmethod
    def finish(result: ToolResult) -> ToolResult:
        if result.error is not None and result.error.retryable:
            return result.model_copy(
                update={"error": result.error.model_copy(update={"retryable": False})}
            )
        return result
