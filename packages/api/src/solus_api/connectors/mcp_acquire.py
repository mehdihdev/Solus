"""`BridgeExportAcquirer` — the live half of the acquisition chain (MCP-04,
SOLUSDEV-100 T4b; docs/contracts/metadata-extraction.md §2.1).

Implements `ExportAcquirer` (`connectors/acquisition.py`, T4a's transport-agnostic
seam): dispatches a vendored MCP server's export tool through the bridge on the
EXACT server-bound scope triple `(user_id, team_id, project_id)` (`bridge/tool.py`'s
model), then resolves the untrusted result — inline `content` or an `artifact_ref`
consumed through T4c's anti-forgery-checked artifact service
(`services/artifacts.py`, docs/api/artifacts.md §4.3) — into export TEXT. Every
failure mode (no acting user, no session, tool not offered, dispatch failure,
malformed/oversize/refused result, undecodable bytes) declines by returning
`None`: `EdaExportConnector._read_export` treats that identically to "no
acquirer" and falls back to the inline committed export (§2.1 invariant 3).

Config key decision (documented per the task): the committed-export connectors'
`SyncContext.config` today carries only the `export` key (the inline text).
Live acquisition needs to know WHERE the KiCad project lives on the companion
machine, so this module reads a new, additive `project_path` key from the same
`config` dict — chosen to need no change to `EdaExportConnector`/`KicadConnector`
(not owned by this task) and to collide with nothing existing. A source with no
`project_path` configured simply cannot use live acquisition (declines cleanly);
the committed `export` key remains sufficient on its own. Flagged in the T4b
completion report as a gap: `KicadConnector.config_fields` should eventually
list `project_path` too — that edit belongs to whoever owns `connectors/kicad.py`.

Logging (CLAUDE.md §7 — never log secrets/local paths cloud-side): every decline
logs the dispatched tool name and a short, static, author-written reason string
ONLY — never `ctx.config` values (the project_path is a local filesystem path),
never tool args, never the export content, and never a companion's free-text
error message (only its structured `ToolErrorCode`).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.registry import DEFAULT_TIMEOUT_SECONDS
from solus_api.agent.tools.shapes import ArtifactRef, ToolResult
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.registry import BridgeSessionRegistry
from solus_api.bridge.service import dispatch
from solus_api.connectors.contracts import SyncContext
from solus_api.core.errors import APIError
from solus_api.deps import live_membership
from solus_api.models import ProjectMembership
from solus_api.services.artifacts import consume_tool_artifact
from solus_api.storage import ArtifactStore

_LOGGER: Final = logging.getLogger("solus.connectors.mcp_acquire")

#: The `SyncContext.config` key carrying the companion-machine KiCad project
#: directory — see the module docstring's "config key decision".
PROJECT_PATH_CONFIG_KEY: Final = "project_path"

#: Phase 4 C1 default dispatch bound — mirrors `ToolRegistry.invoke`'s own
#: default so the acquirer's OWN bound (which `dispatch()` bypasses entirely,
#: since it awaits the wire directly) is never looser than the registry's.
DEFAULT_DISPATCH_TIMEOUT_SECONDS: Final = DEFAULT_TIMEOUT_SECONDS


class _ExportToolValue(BaseModel):
    """The plan-locked export-tool result envelope (SOLUSDEV-100 F1 amendment;
    produced by `integrations/mcp/kicad/solus/netlist_export.py`, relayed by the
    companion with `artifact_path` rewritten to `artifact_ref` before the frame
    leaves the machine). Everything here is untrusted and ADVISORY except
    content/artifact_ref — `format`/`filename`/`bytes`/`degraded`/`reason` are
    never authority for anything (CLAUDE.md §7; the DB row is the authority for
    artifact size/location). `extra="forbid"` still rejects unknown keys, and
    `artifact_path` is declared only so its PRESENCE is a hard shape violation:
    a raw companion-machine path reaching the cloud means the companion did not
    perform the upload rewrite, and nothing here may ever consume a local path
    (Phase 4 review finding: the previous two-field model rejected every real
    fork envelope, silently killing live acquisition).

    `bytes` is aliased to `bytes_` (Phase 4 L6 hygiene): the wire field name
    stays `bytes` (the companion's envelope shape, unchanged), but shadowing
    the builtin `bytes` type as an attribute name on a Python class is
    confusing to read/maintain — the alias keeps the wire contract and the
    Python attribute name both clean.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content: str | None = None
    artifact_ref: ArtifactRef | None = None
    format: str | None = None
    filename: str | None = None
    bytes_: int | None = Field(default=None, alias="bytes")
    degraded: bool = False
    reason: str | None = None
    artifact_path: str | None = None

    @model_validator(mode="after")
    def _exactly_one_present(self) -> Self:
        if self.artifact_path is not None:
            raise ValueError("artifact_path must never reach the cloud unrewritten")
        if (self.content is None) == (self.artifact_ref is None):
            raise ValueError("exactly one of content/artifact_ref must be present")
        return self


def _byte_len(text: str) -> int:
    # surrogatepass (not "ignore"), mirroring eda.py's own bound: an
    # adversarial surrogate-heavy string must not under-count past the cap.
    return len(text.encode("utf-8", "surrogatepass"))


class BridgeExportAcquirer:
    """One (provider, tool) export acquirer bound to a single source's scope.

    Constructed fresh per sync run (registry factories build one per
    `ConnectorContext`, `connectors/registry.py`) so `acting_user_id` always
    reflects THIS run's resolved acting user (F3) — never cached across runs.
    """

    def __init__(
        self,
        *,
        sessions: BridgeSessionRegistry,
        sessionmaker: async_sessionmaker[AsyncSession],
        store: ArtifactStore,
        project_id: uuid.UUID,
        team_id: uuid.UUID,
        acting_user_id: uuid.UUID | None,
        tool_name: str,
        call_cap_bytes: int,
        artifact_ttl_seconds: int,
        inline_max_bytes: int,
        dispatch_timeout_seconds: float = DEFAULT_DISPATCH_TIMEOUT_SECONDS,
    ) -> None:
        self._sessions = sessions
        self._sessionmaker = sessionmaker
        self._store = store
        self._project_id = project_id
        self._team_id = team_id
        self._acting_user_id = acting_user_id
        self._tool_name = tool_name
        self._call_cap_bytes = call_cap_bytes
        self._artifact_ttl_seconds = artifact_ttl_seconds
        self._inline_max_bytes = inline_max_bytes
        self._dispatch_timeout_seconds = dispatch_timeout_seconds

    async def acquire(self, ctx: SyncContext) -> str | None:
        if self._acting_user_id is None:
            # F3: neither the manual requester nor source.created_by resolved
            # to a user — no live acquisition is possible for this run.
            self._decline("no acting user resolved for this sync")
            return None
        project_path = ctx.config.get(PROJECT_PATH_CONFIG_KEY)
        if not isinstance(project_path, str) or not project_path:
            self._decline("no project_path configured")
            return None
        session = self._sessions.get(self._acting_user_id, self._team_id, self._project_id)
        if session is None:
            self._decline("bridge offline")
            return None
        if not any(spec.descriptor.name == self._tool_name for spec in session.inventory):
            self._decline("companion does not offer this export tool")
            return None
        try:
            # Phase 4 C1: `dispatch()` awaits the wire directly and has no
            # bound of its own — the registry-level timeout (`ToolRegistry.invoke`)
            # is bypassed entirely by this direct call, so THIS is the only
            # bound standing between a silent companion and a hung sync.
            async with asyncio.timeout(self._dispatch_timeout_seconds):
                result = await dispatch(
                    session,
                    self._tool_name,
                    {"project_path": project_path},
                    call_cap_bytes=self._call_cap_bytes,
                )
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
        return await self._extract_export(result)

    async def _acting_user_has_project_access(self, session: AsyncSession) -> bool:
        """Phase 4 M4: the acting user (resolved once, at the START of this
        sync run — F3) may have been removed from the team/project SINCE
        then. The acquirer used to hardcode `requester_has_project_access=True`
        downstream of this check; this queries the SAME live state every other
        access decision uses, in the SAME session already open for the
        consumption attempt, and declines if the access is gone."""
        assert self._acting_user_id is not None
        membership = await live_membership(session, self._team_id, self._acting_user_id)
        if membership is not None:
            return True
        share = await session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == self._project_id,
                ProjectMembership.user_id == self._acting_user_id,
                ProjectMembership.deleted_at.is_(None),
            )
        )
        return share is not None

    async def _extract_export(self, result: ToolResult) -> str | None:
        try:
            value = _ExportToolValue.model_validate(result.value)
        except ValidationError:
            self._decline("tool result value has an unexpected shape")
            return None
        if value.content is not None:
            return self._validate_inline_content(value.content)
        assert value.artifact_ref is not None  # the model enforces exactly-one
        return await self._consume_artifact_ref(value.artifact_ref, tool_call_id=result.call_id)

    def _validate_inline_content(self, content: str) -> str | None:
        if _byte_len(content) > self._inline_max_bytes:
            self._decline("inline content exceeds the inline size cap")
            return None
        return content

    async def _consume_artifact_ref(self, ref: ArtifactRef, *, tool_call_id: str) -> str | None:
        # ref.uri / ref.storage / ref.size_bytes / ref.summary are companion-
        # supplied and ADVISORY ONLY (§2.1 invariant 4) — never used to locate
        # bytes. Only ref.artifact_id addresses OUR DB row; the bytes are read
        # via that row's OWN storage key (services/artifacts.py), never a
        # wire-supplied locator.
        #
        # Phase 4 H1/M3: all six docs/api/artifacts.md §4.3 anti-forgery
        # conditions (project scope, team scope, created_by, source_tool,
        # tool_call_id, liveness/one-shot) are now enforced in ONE place —
        # `services.artifacts.consume_tool_artifact` — the only consumption
        # path in the codebase; this acquirer no longer carries any of those
        # checks locally.
        assert self._acting_user_id is not None
        async with self._sessionmaker() as session:
            if not await self._acting_user_has_project_access(session):
                self._decline("acting user no longer has access to this project")
                return None
            try:
                data, _media_type = await consume_tool_artifact(
                    session,
                    self._store,
                    project_id=self._project_id,
                    team_id=self._team_id,
                    artifact_id=ref.artifact_id,
                    requester_id=self._acting_user_id,
                    source_tool=self._tool_name,
                    tool_call_id=tool_call_id,
                    ttl_seconds=self._artifact_ttl_seconds,
                )
            except APIError:
                self._decline(
                    "artifact not found, expired, replayed, or failed an anti-forgery check"
                )
                return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            self._decline("artifact bytes are not valid utf-8 text")
            return None

    def _decline(self, reason: str) -> None:
        _LOGGER.warning(
            "bridge export acquisition declined tool=%s reason=%s", self._tool_name, reason
        )
