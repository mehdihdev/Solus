"""`BridgeFolderAcquirer` — reach the linked folder on the user's machine over the
bridge (SOLUSDEV-249; `docs/api/local-folder.md` §1/§4).

Modelled on `mcp_acquire.BridgeExportAcquirer` (SOLUSDEV-100 T4b), with one
extra rule the local source needs: a `local` source belongs to ONE machine
(`config["machine_id"]` — the companion instance id), so a dispatch is refused
unless the live session's `companion_instance_id` equals it. Machine A's scan
can therefore never land on machine B's source, even when the same user is
signed in on both. Every decline returns `None` and logs a static reason —
never the folder name, never companion text (CLAUDE.md §7).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Final

from pydantic import BaseModel, ValidationError

from solus_api.agent.tools.registry import DEFAULT_TIMEOUT_SECONDS
from solus_api.agent.tools.shapes import ToolResult
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.registry import BridgeSession, BridgeSessionRegistry
from solus_api.bridge.service import dispatch
from solus_api.connectors.local_folder import (
    DIGEST_TOOL,
    MACHINE_ID_RE,
    SCAN_TOOL,
    FolderDigest,
    FolderScan,
)

_LOGGER: Final = logging.getLogger("solus.connectors.local_acquire")


class BridgeFolderAcquirer:
    """One acquirer per sync run, bound to the run's `(user, team, project)`."""

    def __init__(
        self,
        *,
        sessions: BridgeSessionRegistry,
        project_id: uuid.UUID,
        team_id: uuid.UUID,
        acting_user_id: uuid.UUID | None,
        call_cap_bytes: int,
        dispatch_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._sessions = sessions
        self._project_id = project_id
        self._team_id = team_id
        self._acting_user_id = acting_user_id
        self._call_cap_bytes = call_cap_bytes
        self._dispatch_timeout_seconds = dispatch_timeout_seconds

    async def scan(self, config: dict[str, Any]) -> FolderScan | None:
        result = await self._call(SCAN_TOOL, config)
        return None if result is None else self._parse(result, FolderScan)

    async def digest(self, config: dict[str, Any]) -> str | None:
        result = await self._call(DIGEST_TOOL, config)
        parsed = None if result is None else self._parse(result, FolderDigest)
        return None if parsed is None else parsed.digest

    def session_for(self, config: dict[str, Any]) -> BridgeSession | None:
        """The caller's live session for THIS source's machine, or None."""
        if self._acting_user_id is None:
            self._decline("no acting user resolved for this sync")
            return None
        machine_id = config.get("machine_id")
        if not isinstance(machine_id, str) or MACHINE_ID_RE.fullmatch(machine_id) is None:
            self._decline("source has no valid machine_id")
            return None
        if config.get("user_id") != str(self._acting_user_id):
            # The source belongs to the user who linked it; another member's
            # companion never scans into it (security review H1).
            self._decline("source belongs to another user")
            return None
        session = self._sessions.get(self._acting_user_id, self._team_id, self._project_id)
        if session is None:
            self._decline("bridge offline")
            return None
        if session.companion_instance_id != machine_id:
            self._decline("bridge session belongs to another machine")
            return None
        return session

    async def _call(self, tool_name: str, config: dict[str, Any]) -> ToolResult | None:
        session = self.session_for(config)
        if session is None:
            return None
        if not any(spec.descriptor.name == tool_name for spec in session.inventory):
            self._decline("companion does not offer this tool")
            return None
        try:
            async with asyncio.timeout(self._dispatch_timeout_seconds):
                result = await dispatch(session, tool_name, {}, call_cap_bytes=self._call_cap_bytes)
        except TimeoutError:
            self._decline("dispatch timed out")
            return None
        except ToolException as exc:
            self._decline(f"dispatch failed: {exc.code.value}")
            return None
        if not result.ok:
            code = result.error.code.value if result.error is not None else "unknown"
            self._decline(f"companion reported failure: {code}")
            return None
        return result

    def _parse[T: BaseModel](self, result: ToolResult, model: type[T]) -> T | None:
        try:
            return model.model_validate(result.value)
        except ValidationError:
            self._decline("tool result value has an unexpected shape")
            return None

    def _decline(self, reason: str) -> None:
        _LOGGER.warning("local folder acquisition declined reason=%s", reason)
