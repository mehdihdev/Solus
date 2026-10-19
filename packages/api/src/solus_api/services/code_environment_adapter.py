"""Translate the I3 probe into CODE records without probing or executing locally."""

from __future__ import annotations

import json
import logging
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any, Final, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, Tool, ToolException
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
COMPLETE_PREVIEW_TOOLS: Final = frozenset(
    {"code.exec", "code.process_start", "code.profile_capture"}
)
PLANNED_TOOLS: Final = (
    frozenset({"code.create_environment", "code.install", "code.run", "code.test"})
    | COMPLETE_PREVIEW_TOOLS
)


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

    previews: OrderedDict[str, str] = OrderedDict()

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
        previews[identity] = json.dumps(rows, sort_keys=True)
        while len(previews) > 64:
            previews.popitem(last=False)
        return rows

    async def invoke(args: dict[str, Any]) -> dict[str, Any]:
        shown = previews.pop(key(args), None)
        if shown is None or json.dumps(await plan(args), sort_keys=True) != shown:
            raise ToolException(
                "The command plan changed or was not previewed; request approval again.",
                code=ToolErrorCode.UNAUTHORIZED,
            )
        result = await tool.invoke(args)
        return await _record_environment(
            tool.descriptor.name, args, result, fetch, sessions, project_id, user_id
        )

    wrapped = InProcessTool(tool.descriptor, invoke, preview=preview)
    if tool.descriptor.name in COMPLETE_PREVIEW_TOOLS:
        # SOLUSDEV-317 §5.1: a failed or unrenderable plan REFUSES the call; the
        # gate must never fall back to argument rows for an arbitrary argv.
        wrapped.requires_complete_preview = True  # type: ignore[attr-defined]
    return wrapped


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
