"""Read code through its project graph identity; local saved text or synced commit."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, Tool, ToolException
from solus_api.agent.tools.untrusted import redact_text
from solus_api.bridge.registry import BridgeSession, BridgeSessionRegistry
from solus_api.bridge.service import dispatch
from solus_api.connectors.code_content import (
    CodeContentError,
    CodeContentReader,
    decode_code,
    safe_code_path,
)
from solus_api.connectors.github import GitHubConnector
from solus_api.connectors.gitlab import GitLabConnector
from solus_api.connectors.local_acquire import BridgeFolderAcquirer
from solus_api.connectors.local_folder import FolderScan, normalize_remote
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.runtime import resolve_credentials
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore
from solus_api.graph.read_scope import GraphReadScope, current_scope
from solus_api.models import GraphEntity, Source, SourceStatus, SourceType

MAX_LINES = 200
MAX_TEXT_CHARS = 16_000
READ_CODE_DESCRIPTOR = ToolDescriptor(
    name="read_code_file",
    description=(
        "Read a mentioned code_file before explaining its contents; graph metadata alone "
        "is not code. Returns bounded line-numbered text from the caller's matching saved "
        "working copy, otherwise the immutable synced remote commit. Cite origin, path, "
        "revision and lines. Read related graph files with their entity IDs when needed."
    ),
    params={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "format": "uuid"},
            "start_line": {"type": "integer", "minimum": 1, "maximum": 100000},
            "max_lines": {"type": "integer", "minimum": 1, "maximum": MAX_LINES},
        },
        "required": ["entity_id"],
        "additionalProperties": False,
    },
    returns={"type": "object"},
    result_cap=24_000,
    timeout_seconds=60,
)


@dataclass(frozen=True)
class CodeRevision:
    entity_id: uuid.UUID
    source_id: uuid.UUID
    provider: str
    repo: str
    path: str
    commit: str
    branch: str
    secret_ref: str
    explicit_revision: bool = False
    blob_sha: str | None = None


async def load_revision(
    session: AsyncSession, project_id: uuid.UUID, entity_id: uuid.UUID, scope: GraphReadScope
) -> CodeRevision:
    row = (
        await session.execute(
            select(GraphEntity, Source)
            .join(Source, GraphEntity.source_id == Source.id)
            .where(
                GraphEntity.id == entity_id,
                scope.entity_predicate(),
                GraphEntity.project_id == project_id,
                GraphEntity.deleted_at.is_(None),
                GraphEntity.kind == "code_file",
                Source.project_id == project_id,
                Source.type.in_((SourceType.GITHUB, SourceType.GITLAB)),
                Source.status == SourceStatus.CONNECTED,
            )
        )
    ).one_or_none()
    if row is None:
        raise ToolException(
            "Connected code file not found in this project.", code=ToolErrorCode.NOT_FOUND
        )
    entity, source = row
    path = safe_code_path(entity.external_ref or "")
    # The cursor describes the graph actually synced, even after config changes.
    commit, branch = source.cursor.get("sha"), source.cursor.get("branch")
    explicit = source.revision_base_source_id is not None
    if explicit:
        branch = scope.branch_for_source(source.id) or branch
        source = await session.scalar(
            select(Source).where(
                Source.id == source.revision_base_source_id,
                Source.project_id == project_id,
                Source.status == SourceStatus.CONNECTED,
                Source.revision_base_source_id.is_(None),
            )
        )
        if source is None:
            raise ToolException("Connected repository not found.", code=ToolErrorCode.NOT_FOUND)
    if not isinstance(commit, str) or not isinstance(branch, str) or not source.secret_ref:
        raise ToolException(
            "Sync this code source before reading its contents.", code=ToolErrorCode.UNAVAILABLE
        )
    repo = source.config.get("repo")
    if not isinstance(repo, str):
        raise ToolException(
            "The connected repository identity is missing.", code=ToolErrorCode.UNAVAILABLE
        )
    return CodeRevision(
        entity.id,
        source.id,
        str(source.type),
        repo,
        path,
        commit,
        branch,
        source.secret_ref,
        explicit,
        entity.attrs.get("sha") if isinstance(entity.attrs.get("sha"), str) else None,
    )


class CodeFileTool:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        *,
        secret_store: SecretStore | None,
        connectors: ConnectorRegistry,
        bridge: BridgeSessionRegistry | None = None,
        user_id: uuid.UUID | None = None,
        team_id: uuid.UUID | None = None,
        bridge_call_cap_bytes: int = 262_144,
    ) -> None:
        self.sessions, self.project_id = session_factory, project_id
        self.secrets, self.connectors = secret_store, connectors
        self.bridge, self.user_id, self.team_id = bridge, user_id, team_id
        self.call_cap = bridge_call_cap_bytes
        self.scope = current_scope(project_id)

    async def read(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._read(args)
        except CodeContentError as exc:
            code = {
                401: ToolErrorCode.UNAUTHORIZED,
                403: ToolErrorCode.UNAUTHORIZED,
                404: ToolErrorCode.NOT_FOUND,
            }.get(exc.status or 0, ToolErrorCode.TOOL_ERROR)
            raise ToolException(
                str(exc), code=code, retryable=exc.status in {429, 502, 503, 504}
            ) from exc
        except SecretNotFoundError as exc:
            raise ToolException(
                "Reconnect this repository to restore file access.", code=ToolErrorCode.UNAUTHORIZED
            ) from exc

    async def _read(self, args: dict[str, Any]) -> dict[str, Any]:
        start, count = int(args.get("start_line", 1)), int(args.get("max_lines", MAX_LINES))
        if not 1 <= start <= 100000 or not 1 <= count <= MAX_LINES:
            raise ToolException("Invalid line range.", code=ToolErrorCode.INVALID_ARGS)
        async with self.sessions() as session:
            revision = await load_revision(
                session, self.project_id, uuid.UUID(args["entity_id"]), self.scope
            )
        connector = self.connectors.create(revision.provider)
        if not isinstance(connector, (GitHubConnector, GitLabConnector)):
            raise ToolException("Repository reader is unavailable.", code=ToolErrorCode.UNAVAILABLE)
        local = await self._local(revision, connector)
        if local is None:
            if revision.provider == "github" and revision.blob_sha is None:
                raise ToolException(
                    "Sync this GitHub source to establish the file blob identity.",
                    code=ToolErrorCode.UNAVAILABLE,
                )
            if self.secrets is None:
                raise ToolException(
                    "Repository credentials unavailable.", code=ToolErrorCode.UNAUTHORIZED
                )
            credentials = await resolve_credentials(self.secrets, revision.secret_ref)
            text = await CodeContentReader(connector).read(
                credentials,
                repo=revision.repo,
                path=revision.path,
                commit=revision.commit,
                blob_sha=revision.blob_sha,
            )
            origin, commit, branch = "remote", revision.commit, revision.branch
        else:
            text, commit, branch = local
            origin = "local_saved"
        lines = text.splitlines()
        selected = lines[start - 1 : start - 1 + count]
        numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(selected, start))
        return {
            "entity_id": str(revision.entity_id),
            "source_id": str(revision.source_id),
            "path": revision.path,
            "repo": revision.repo,
            "branch": branch,
            "commit": commit,
            "origin": origin,
            "start_line": start,
            "end_line": start + len(selected) - 1,
            "text": redact_text(numbered)[:MAX_TEXT_CHARS],
            "truncated": start - 1 + len(selected) < len(lines) or len(numbered) > MAX_TEXT_CHARS,
            "provenance": "Current saved working-copy text; may include uncommitted edits."
            if local
            else "No verified local read; using the last synced immutable remote commit.",
        }

    async def _local(
        self, revision: CodeRevision, connector: GitHubConnector | GitLabConnector
    ) -> tuple[str, str, str] | None:
        if self.bridge is None or self.user_id is None or self.team_id is None:
            return None
        acquirer = BridgeFolderAcquirer(
            sessions=self.bridge,
            project_id=self.project_id,
            team_id=self.team_id,
            acting_user_id=self.user_id,
            call_cap_bytes=self.call_cap,
        )
        async with self.sessions() as session:
            sources = list(
                await session.scalars(
                    select(Source)
                    .where(
                        Source.project_id == self.project_id,
                        Source.type == SourceType.LOCAL,
                        Source.created_by == self.user_id,
                        Source.status == SourceStatus.CONNECTED,
                    )
                    .limit(32)
                )
            )
        for source in sources:
            result = await self._local_source(acquirer, source, revision, connector)
            if result is not None:
                return result
        return None

    async def _local_source(
        self,
        acquirer: BridgeFolderAcquirer,
        source: Source,
        revision: CodeRevision,
        connector: GitHubConnector | GitLabConnector,
    ) -> tuple[str, str, str] | None:
        live = acquirer.session_for(source.config)
        if live is None or not _has_readers(live):
            return None
        scan = await acquirer.scan(source.config)
        if not local_matches(scan, revision, connector):
            return None
        assert scan is not None and scan.git is not None
        if acquirer.session_for(source.config) is not live:
            return None
        result = await dispatch(
            live, "machine.read_code_file", {"path": revision.path}, call_cap_bytes=self.call_cap
        )
        if not result.ok or result.value is None:
            # A deleted local file is evidence, never replaced by an older remote copy.
            raise ToolException(
                "The matching local checkout could not read this file; "
                "it may have been deleted or moved.",
                code=ToolErrorCode.NOT_FOUND,
            )
        after = await acquirer.scan(source.config)
        if (
            acquirer.session_for(source.config) is not live
            or after is None
            or after.git != scan.git
            or after.root_name != scan.root_name
        ):
            raise ToolException(
                "Local checkout changed during the read; try again.",
                code=ToolErrorCode.UNAVAILABLE,
                retryable=True,
            )
        value = result.value
        if (
            value.get("path") != revision.path
            or value.get("encoding") != "utf-8"
            or not isinstance(value.get("content"), str)
        ):
            raise ToolException("Local file was not returned as matching UTF-8 text.")
        return (
            decode_code(value["content"].encode("utf-8")),
            scan.git.head or "unknown",
            scan.git.branch or "detached",
        )


def _has_readers(live: BridgeSession) -> bool:
    names = {
        spec.descriptor.name for spec in live.inventory if not spec.descriptor.requires_confirmation
    }
    return {"machine.read_code_file", "local.scan_folder"} <= names


def local_matches(
    scan: FolderScan | None, revision: CodeRevision, connector: GitHubConnector | GitLabConnector
) -> bool:
    if scan is None or scan.git is None:
        return False
    if revision.explicit_revision and scan.git.branch != revision.branch:
        return False
    host = (
        urlsplit(connector._base_url).hostname if isinstance(connector, GitLabConnector) else None
    )
    raw_remote = scan.git.remote_url or ""
    remote_host = (
        urlsplit(raw_remote).hostname
        if "://" in raw_remote
        else raw_remote.partition(":")[0].rpartition("@")[2]
    )
    expected_host = host if isinstance(connector, GitLabConnector) else "github.com"
    if not remote_host or remote_host.lower() != expected_host:
        return False
    remote = normalize_remote(raw_remote, gitlab_host=host)
    return (
        remote is not None
        and remote.host == revision.provider
        and remote.repo.casefold() == revision.repo.casefold()
    )


def build_read_code_file_tool(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    secret_store: SecretStore | None,
    connectors: ConnectorRegistry,
    bridge: BridgeSessionRegistry | None = None,
    user_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    bridge_call_cap_bytes: int = 262_144,
) -> Tool:
    implementation = CodeFileTool(
        session_factory,
        project_id,
        secret_store=secret_store,
        connectors=connectors,
        bridge=bridge,
        user_id=user_id,
        team_id=team_id,
        bridge_call_cap_bytes=bridge_call_cap_bytes,
    )
    return InProcessTool(READ_CODE_DESCRIPTOR, implementation.read)
