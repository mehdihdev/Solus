"""`BridgeTool` — the W0-04 `Tool` kind that routes through a live companion.

Registered per-SOL-turn from the live session's cloud-validated inventory
(runtime.build_sol_registry); unexported, like mcp_tool. `invoke` raises only
`ToolException` — the registry's never-raises invariant holds across the wire.
Outcome mapping mirrors `MCPTool.invoke`: transport-shaped failures are
retryable; companion-reported errors carry their (capped, untrusted) message.
"""

import logging
import shlex
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from solus_api.agent.tools.shapes import ToolDescriptor, ToolError, ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.agent.tools.untrusted import UNTRUSTED_TEXT_CAP
from solus_api.bridge.allowlist import requires_complete_preview, supports_dry_run
from solus_api.bridge.registry import BridgeSessionRegistry
from solus_api.bridge.service import dispatch

logger = logging.getLogger("solus.bridge.tool")


def _raise_companion_error(tool_name: str, error: ToolError) -> None:
    # The companion's error text is untrusted → capped; its code string maps
    # into the locked ToolErrorCode enum (it already validated as one — the
    # W0-04 ToolResult parsed at ingress), retryable passes through.
    raise ToolException(
        error.message[:UNTRUSTED_TEXT_CAP] or f"bridge tool {tool_name!r} failed",
        code=error.code,
        retryable=error.retryable,
    )


def _row(label: str, value: str) -> dict[str, Any]:
    return {"label": label, "before": None, "after": value}


def _diff_rows(preview: Any) -> list[dict[str, Any]]:
    """Validate bounded companion-supplied changes without altering their values."""
    if not isinstance(preview, list) or not 1 <= len(preview) <= 40:
        return []
    for row in preview:
        if (
            not isinstance(row, dict)
            or set(row) != {"label", "before", "after"}
            or not isinstance(row["label"], str)
            or not row["label"].strip()
            or any(
                value is not None and (not isinstance(value, str) or len(value) > 400)
                for value in row.values()
            )
        ):
            return []
    return [dict(row) for row in preview]


def _plan_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """A companion dry-run plan as consent rows (action-gate.md `DiffRow`).

    Covers both plan shapes the machine server returns: one command
    (`argv`/`cwd`/`env`) and an ordered multi-step build (`steps`), plus the
    file a `dockerfile` environment would write. Unknown keys are ignored rather
    than dumped — a row a person cannot read is not consent.
    """
    rows: list[dict[str, Any]] = []
    if "preview" in plan:
        return _diff_rows(plan["preview"])
    if isinstance(plan.get("argv"), list):
        rows.append(_row("command", shlex.join(str(part) for part in plan["argv"])))
    for key in ("cwd", "kind", "name", "path", "content"):
        if isinstance(plan.get(key), str):
            rows.append(_row(key, plan[key]))
    env = plan.get("env")
    # ponytail: of the whole resolved environment only the activated venv is
    # decision-relevant (a conda activation is already visible in the argv
    # prefix); render more of it only if an approval ever turns on another var.
    if isinstance(env, dict) and isinstance(env.get("VIRTUAL_ENV"), str):
        rows.append(_row("environment", env["VIRTUAL_ENV"]))
    steps = plan.get("steps")
    for index, step in enumerate(steps if isinstance(steps, list) else [], start=1):
        if isinstance(step, list):
            rows.append(_row(f"step {index}", shlex.join(str(part) for part in step)))
    return rows


class BridgeTool:
    """One allowlisted tool on the requesting user's connected companion."""

    #: Set ONLY for allowlist entries that opt into `dry_run`. It is duck-typed
    #: by `confirmations._build_preview`, so a tool that cannot plan its own
    #: change simply has no attribute here and the card shows argument rows.
    preview: Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]]

    def __init__(
        self,
        *,
        descriptor: ToolDescriptor,
        sessions: BridgeSessionRegistry,
        user_id: uuid.UUID,
        team_id: uuid.UUID,
        project_id: uuid.UUID,
        call_cap_bytes: int,
        preflight: Callable[[], Awaitable[None]] | None = None,
        preview: Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]] | None = None,
    ) -> None:
        self._descriptor = descriptor
        self.requires_complete_preview = requires_complete_preview(descriptor.name)
        if preview is not None:
            # SOLUSDEV-251: set on the INSTANCE only (as MCPTool does) — the
            # confirmation gate reads `getattr(tool, "preview", None)` and treats
            # a present attribute as "this tool can describe its own change".
            self.preview = preview
        self._sessions = sessions
        self._user_id = user_id
        self._team_id = team_id
        self._project_id = project_id
        self._call_cap_bytes = call_cap_bytes
        # MCP-05: an optional gate (entitlement + license presence) that raises
        # ToolException. Runs FIRST — an entitlement refusal must win over
        # "bridge offline" so a blocked user sees the upgrade path.
        self._preflight = preflight
        if supports_dry_run(descriptor.name):
            self.preview = self._preview

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        if self._preflight is not None:
            await self._preflight()
        session = self._sessions.get(self._user_id, self._team_id, self._project_id)
        if session is None:
            # "Bridge offline" (contract §3): fail fast, retryable, machine-
            # readable (UNAVAILABLE — the BRG-03 contract-change extension).
            raise ToolException("bridge offline", code=ToolErrorCode.UNAVAILABLE, retryable=True)
        result = await dispatch(
            session, self._descriptor.name, args, call_cap_bytes=self._call_cap_bytes
        )
        if result.ok and result.value is not None:
            return result.value
        if result.error is not None:
            _raise_companion_error(self._descriptor.name, result.error)
        raise ToolException(  # pragma: no cover — the ToolResult invariant forbids this
            f"bridge tool {self._descriptor.name!r} returned an empty result"
        )

    async def _preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        """What this call would ACTUALLY run, from the companion itself.

        The same call down the same session, with one flag: the machine tools
        answer `dry_run: true` with the resolved plan and execute nothing. Only
        the companion can resolve it — the argv gains a `conda run -n <env>`
        prefix, an install resolves an interpreter the caller never named, and
        a create_environment is several commands. Argument rows show none of
        that, so the person was approving something other than what would run.

        Legacy tools may fall back to argument rows if previewing fails. Tools
        covered by requires_complete_preview must return explicit, complete
        change rows; the confirmation gate refuses them otherwise.
        """
        plan = await self.invoke({**args, "dry_run": True})
        # `dry_run: false` coming back means it RAN — an execution result, not a
        # plan. Render nothing rather than pass it off as a preview.
        if plan.get("dry_run") is not True:
            return []
        if self.requires_complete_preview:
            return _diff_rows(plan.get("preview"))
        return _plan_rows(plan)
