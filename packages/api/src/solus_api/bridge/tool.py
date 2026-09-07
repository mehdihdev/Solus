"""`BridgeTool` — the W0-04 `Tool` kind that routes through a live companion.

Registered per-SOL-turn from the live session's cloud-validated inventory
(runtime.build_sol_registry); unexported, like mcp_tool. `invoke` raises only
`ToolException` — the registry's never-raises invariant holds across the wire.
Outcome mapping mirrors `MCPTool.invoke`: transport-shaped failures are
retryable; companion-reported errors carry their (capped, untrusted) message.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from solus_api.agent.tools.shapes import ToolDescriptor, ToolError, ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.agent.tools.untrusted import UNTRUSTED_TEXT_CAP
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


class BridgeTool:
    """One allowlisted tool on the requesting user's connected companion."""

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
