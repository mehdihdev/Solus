"""Translate the I3 probe into CODE records without probing or executing locally."""

from __future__ import annotations

import json
import logging
import uuid
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.command_gate import COMPLETE_PREVIEW_TOOLS, PLAN_PREVIEW_TOOLS
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import (
    InProcessTool,
    Tool,
    ToolException,
    ToolHandler,
    ToolPreview,
)
from solus_api.services.code_env import (
    CodeEnvironment,
    EnvironmentProvenance,
    EnvironmentType,
    PackagePin,
    upsert_code_environment,
)

logger = logging.getLogger(__name__)


#: Code tools whose card is the server's own `code.plan`, guarded by the one-use
#: plan snapshot below (SOLUSDEV-250; SOLUSDEV-317 adds the executing tools).
PLANNED_TOOLS: Final = PLAN_PREVIEW_TOOLS


ScopeReader = Callable[[dict[str, Any]], str | None]


class PlannedTool(InProcessTool):
    """A `code.plan`-previewed tool; `requires_complete_preview` is read by the
    confirmation gate (duck-typed, like `preview`)."""

    def __init__(
        self,
        descriptor: ToolDescriptor,
        handler: ToolHandler,
        preview: ToolPreview,
        *,
        requires_complete_preview: bool,
        scope: ScopeReader,
    ) -> None:
        super().__init__(descriptor, handler, preview=preview)
        self.requires_complete_preview = requires_complete_preview
        self._scope = scope

    def program_scope(self, args: dict[str, Any]) -> str | None:
        """The `program_scope` of the plan the latest preview of `args` showed
        (§10.1); None when there is no such snapshot or the plan named none."""
        return self._scope(args)


class EnvironmentFetch(Protocol):
    async def __call__(self, environment: str | None = None) -> Any: ...


class _Observed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Interpreter(_Observed):
    path: str = Field(min_length=1, max_length=1024)
    version: str | None = Field(default=None, max_length=64)


class _Venv(_Observed):
    path: str = Field(min_length=1, max_length=128)
    python_version: str | None = Field(default=None, max_length=64)
    packages: list[PackagePin] = Field(max_length=300)
    truncated: bool


class _Probe(_Observed):
    python: _Interpreter | None
    interpreters: list[_Interpreter] = Field(max_length=8)
    venv: _Venv | None
    conda: dict[str, Any] | None
    uv: dict[str, Any] | None


def observed_environments(value: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Return the linker's established inventory shape using only I3 evidence.

    Host OS/architecture and a venv's interpreter path are not in this probe.
    They remain null. Conda's names alone cannot establish its package inventory.
    """
    try:
        probe = _Probe.model_validate(value)
    except ValidationError:
        raise ToolException(
            "The code environment probe is unavailable or malformed.",
            code=ToolErrorCode.UNAVAILABLE,
        ) from None
    captured = now or datetime.now(UTC)
    environments: list[CodeEnvironment] = []
    unavailable: list[str] = []
    if probe.venv is not None:
        if probe.venv.truncated:
            unavailable.append("Workspace package inventory is truncated; linking was refused.")
        else:
            environments.append(
                CodeEnvironment(
                    type=EnvironmentType.VENV,
                    name=probe.venv.path,
                    path=probe.venv.path,
                    version=probe.venv.python_version,
                    packages=probe.venv.packages,
                    detected_on=None,
                    provenance=EnvironmentProvenance.DETECTED,
                    captured_at=captured,
                )
            )
    if probe.conda is not None:
        unavailable.append("I3 does not support conda environment linking or execution.")
    # System interpreters are reported by the probe for selecting a venv creator;
    # they are not writable workspace environments and are never invented as one.
    return {
        "environments": [env.model_dump(mode="json") for env in environments],
        "unavailable": unavailable,
    }


def _snapshot(rows: list[dict[str, Any]]) -> tuple[str, str | None]:
    """The rows a card showed plus the plan's `program_scope` (§10.1)."""
    scope = getattr(rows, "program_scope", None)
    return json.dumps(rows, sort_keys=True), scope if isinstance(scope, str) else None


def with_environment_recording(
    tool: Tool,
    fetch: EnvironmentFetch | None,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Tool:
    """Decorate the existing approved I3 action; never introduce an executor.

    Capture only after an actual successful create/install. Probe failures cannot
    undo the action, so return a portable recording status with its original result.
    The original preview and confirmation descriptor remain authoritative.
    """
    if tool.descriptor.name not in PLANNED_TOOLS:
        return tool

    #: args → (the rows the card showed, the plan's program_scope).
    previews: OrderedDict[str, tuple[str, str | None]] = OrderedDict()

    def key(args: dict[str, Any]) -> str:
        return json.dumps(args, sort_keys=True, separators=(",", ":"))

    async def plan(args: dict[str, Any]) -> list[dict[str, Any]]:
        original = getattr(tool, "preview", None)
        if original is None:
            raise ToolException(
                "I3 command planning is unavailable; no command was run.",
                code=ToolErrorCode.UNAVAILABLE,
            )
        rows: list[dict[str, Any]] = await original(args)
        return rows

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        identity = key(args)
        previews.pop(identity, None)
        rows = await plan(args)
        previews[identity] = _snapshot(rows)
        while len(previews) > 64:
            previews.popitem(last=False)
        return rows

    def scope(args: dict[str, Any]) -> str | None:
        shown = previews.get(key(args))
        return None if shown is None else shown[1]

    async def invoke(args: dict[str, Any]) -> dict[str, Any]:
        shown = previews.pop(key(args), None)
        if shown is None or _snapshot(await plan(args)) != shown:
            raise ToolException(
                "The command plan changed or was not previewed; request approval again.",
                code=ToolErrorCode.UNAUTHORIZED,
            )
        result = await tool.invoke(args)
        return await _record_environment(
            tool.descriptor.name, args, result, fetch, sessions, project_id, user_id
        )

    # SOLUSDEV-317 §5.1: a failed or unrenderable plan REFUSES the call; the
    # gate must never fall back to argument rows for an arbitrary argv.
    return PlannedTool(
        tool.descriptor,
        invoke,
        preview,
        requires_complete_preview=tool.descriptor.name in COMPLETE_PREVIEW_TOOLS,
        scope=scope,
    )


async def _record_environment(
    tool_name: str,
    args: dict[str, Any],
    result: dict[str, Any],
    fetch: EnvironmentFetch | None,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    """Best-effort observation after execution; never changes its outcome."""
    if tool_name not in {"code.create_environment", "code.install"} or fetch is None:
        return result
    if type(result.get("exit_code")) is not int or result["exit_code"] != 0:
        return result
    target = args.get("path" if tool_name == "code.create_environment" else "environment", ".venv")
    try:
        inventory = await fetch(target)
        matches = [
            CodeEnvironment.model_validate(row)
            for row in inventory.get("environments", [])
            if row.get("path") == target and row.get("type") == "venv"
        ]
        if len(matches) != 1:
            return {
                **result,
                "environment_recording": "unavailable: target environment was not observed",
            }
        observed = matches[0].model_copy(update={"provenance": EnvironmentProvenance.SOL})
        async with sessions() as session:
            await upsert_code_environment(
                session, project_id, observed, created_by=user_id, author="sol"
            )
            await session.commit()
    except Exception as exc:
        logger.warning(
            "environment recording skipped project=%s error=%s", project_id, type(exc).__name__
        )
        return {
            **result,
            "environment_recording": (
                "unavailable: action succeeded, but environment recording failed"
            ),
        }
    return {**result, "environment_recording": "updated"}
