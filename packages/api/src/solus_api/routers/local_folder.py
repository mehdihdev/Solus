"""`/projects/{id}/local-folder` — a working copy on THIS machine as a source
(SOLUSDEV-249 / INTEGRATIONS I2; `docs/api/local-folder.md` §3).

One `local` source per `(project, machine_id)`; the machine id is the companion
instance id, so every read and every dispatch is bound to the caller's OWN live
bridge session for that machine — a teammate sees their own folder, never
yours, and no path ever crosses the API (the companion scans its workspace).
Syncs run in the API process (the bridge lives here; ARQ has no bridge).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Final

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from sqlalchemy import select

from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.registry import BridgeSession
from solus_api.bridge.service import dispatch
from solus_api.connectors.local_folder import (
    CLONE_KEY,
    LOCAL_KINDS,
    OPEN_TOOL,
    PROJECT_KINDS,
    ROOT_KINDS,
)
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import (
    BridgeSessionsDep,
    ProjectCtx,
    RequireVerified,
    SessionDep,
    SettingsDep,
    require_role,
)
from solus_api.models import GraphEntity, Role, Source, SourceStatus, SourceType
from solus_api.routers.sources import enqueue_sync
from solus_api.schemas import LocalFolderLink, LocalFolderOpen, serialize_source
from solus_api.services.activity import record_activity
from solus_api.services.events import emit_event
from solus_api.services.limits import check_can_add_integration

logger = logging.getLogger("solus.routers.local_folder")

router = APIRouter(prefix="/api/v1/projects/{project_id}/local-folder")

#: Which detected-project kinds a given tool can open (`docs/api/local-folder.md` §3).
_TOOL_FOR_KIND: Final = {PROJECT_KINDS["kicad"]: "kicad", PROJECT_KINDS["altium"]: "altium"}
_OPEN_TIMEOUT_SECONDS: Final = 15.0


async def _machine_source(session: SessionDep, ctx: ProjectCtx, machine_id: str) -> Source | None:
    rows = await session.scalars(
        select(Source).where(
            Source.project_id == ctx.project.id,
            Source.type == SourceType.LOCAL,
            Source.status != SourceStatus.DISCONNECTED,
        )
    )
    for source in rows.all():
        if source.config.get("machine_id") == machine_id and source.created_by == ctx.user.id:
            return source
    return None


def _live_session(
    sessions: BridgeSessionsDep, ctx: ProjectCtx, machine_id: str
) -> BridgeSession | None:
    session = sessions.get(ctx.user.id, ctx.team.id, ctx.project.id)
    if session is None or session.companion_instance_id != machine_id:
        return None
    return session


def _open_targets(kind: str, tools_installed: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    tool = _TOOL_FOR_KIND.get(kind)
    if tool is not None and tools_installed.get(tool) is True:
        targets.append(tool)
    if tools_installed.get("vscode") is True:
        targets.append("vscode")
    targets.append("system")
    return targets


async def _detected(session: SessionDep, source: Source) -> list[dict[str, Any]]:
    cursor_entries = source.cursor.get("detected")
    by_key: dict[str, dict[str, Any]] = {}
    if isinstance(cursor_entries, list):
        for entry in cursor_entries:
            if isinstance(entry, dict) and isinstance(entry.get("entity_key"), str):
                by_key[entry["entity_key"]] = entry
    tools = source.cursor.get("tools_installed")
    installed = tools if isinstance(tools, dict) else {}
    rows = await session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.source_id == source.id,
            GraphEntity.deleted_at.is_(None),
            GraphEntity.kind.in_(sorted(LOCAL_KINDS)),
        )
        .order_by(GraphEntity.external_ref)
    )
    out: list[dict[str, Any]] = []
    for entity in rows.all():
        key = entity.external_ref or ""
        entry = by_key.get(key, {})
        is_root = entity.kind in ROOT_KINDS
        out.append(
            {
                "entity_id": str(entity.id),
                "entity_key": key,
                "tool": "root" if is_root else entry.get("tool"),
                "name": entity.name,
                "path": entry.get("path", "." if is_root else None),
                "open_targets": _open_targets(entity.kind, installed),
            }
        )
    # Root first, then projects in key order.
    out.sort(key=lambda d: (d["entity_key"] != CLONE_KEY, d["entity_key"]))
    return out


def _view(
    source: Source | None, live: BridgeSession | None, detected: list[dict[str, Any]]
) -> dict[str, Any]:
    tools = source.cursor.get("tools_installed") if source is not None else None
    return {
        "source": serialize_source(source) if source is not None else None,
        "bridge": {
            "connected": live is not None,
            "tools_installed": dict(tools) if isinstance(tools, dict) else {},
        },
        "detected": detected,
    }


@router.get("")
async def get_local_folder(
    ctx: ProjectCtx,
    session: SessionDep,
    sessions: BridgeSessionsDep,
    machine_id: str = Query(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$"),
) -> dict[str, Any]:
    source = await _machine_source(session, ctx, machine_id)
    live = _live_session(sessions, ctx, machine_id)
    detected = await _detected(session, source) if source is not None else []
    return envelope(_view(source, live, detected))


@router.post("", status_code=201)
async def link_local_folder(
    body: LocalFolderLink,
    ctx: ProjectCtx,
    session: SessionDep,
    sessions: BridgeSessionsDep,
    settings: SettingsDep,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    _verified: RequireVerified,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    # `user_id` is server-set: the acquirer refuses to scan for anyone else.
    config = {**body.model_dump(), "user_id": str(ctx.user.id)}
    source = await _machine_source(session, ctx, body.machine_id)
    reused = source is not None
    if source is None:
        await check_can_add_integration(session, ctx.user)
        source = Source(
            project_id=ctx.project.id,
            team_id=ctx.team.id,
            type=SourceType.LOCAL,
            name=body.machine_name,
            status=SourceStatus.CONNECTED,
            config=config,
            account_login="local folder",
            account_external_id="local",
            created_by=ctx.user.id,
        )
        session.add(source)
        await session.flush()
    else:
        source.name = body.machine_name
        source.config = config
        if source.status == SourceStatus.ERROR:
            source.status = SourceStatus.CONNECTED
    record_activity(
        session,
        team_id=ctx.team.id,
        activity_type="local_folder.linked",
        actor_id=ctx.user.id,
        project_id=ctx.project.id,
        domain="integrations",
        payload={"machine_name": body.machine_name, "folder_name": body.folder_name},
    )
    emit_event(
        session,
        user=ctx.user,
        event_type="local_folder.linked",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"reused": reused},
    )
    job_id: uuid.UUID | None = None
    if source.status != SourceStatus.SYNCING:
        job_id = await enqueue_sync(
            session, ctx, source, request, background_tasks, settings, response, inline_only=True
        )
    else:
        await session.commit()
    await session.refresh(source)
    response.status_code = 200 if reused else 201
    live = _live_session(sessions, ctx, body.machine_id)
    return envelope(
        {
            "source": serialize_source(source),
            "job_id": str(job_id) if job_id else None,
            "bridge": {"connected": live is not None},
        }
    )


@router.post("/{source_id}/open")
async def open_in_tool(
    source_id: uuid.UUID,
    body: LocalFolderOpen,
    ctx: ProjectCtx,
    session: SessionDep,
    sessions: BridgeSessionsDep,
    settings: SettingsDep,
    _verified: RequireVerified,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    source = await session.get(Source, source_id)
    if (
        source is None
        or source.project_id != ctx.project.id
        or source.type is not SourceType.LOCAL
        or source.status == SourceStatus.DISCONNECTED
        or source.created_by != ctx.user.id
    ):
        raise APIError(404, "not_found", "Not Found")
    detected = await _detected(session, source)
    entry = next((d for d in detected if d["entity_id"] == str(body.entity_id)), None)
    if entry is None or not isinstance(entry.get("path"), str):
        raise APIError(404, "not_found", "Not Found")
    if body.tool not in entry["open_targets"]:
        raise APIError(400, "unsupported_tool", f"This project cannot be opened in {body.tool}")
    machine_id = str(source.config.get("machine_id", ""))
    live = _live_session(sessions, ctx, machine_id)
    if live is None or not any(spec.descriptor.name == OPEN_TOOL for spec in live.inventory):
        raise APIError(409, "bridge_offline", "Solus companion is offline on this machine")
    try:
        async with asyncio.timeout(_OPEN_TIMEOUT_SECONDS):
            result = await dispatch(
                live,
                OPEN_TOOL,
                {"path": entry["path"], "tool": body.tool},
                call_cap_bytes=settings.bridge_tool_call_max_bytes,
            )
    except TimeoutError as exc:
        raise APIError(409, "bridge_offline", "The companion did not answer in time") from exc
    except ToolException as exc:
        raise APIError(409, "bridge_offline", "The companion could not be reached") from exc
    value = result.value if result.ok and isinstance(result.value, dict) else {}
    launched = value.get("launched") is True
    reason = value.get("reason")
    if not result.ok:
        reason = "the companion refused the launch"
    answer = {
        "launched": launched,
        "tool": body.tool,
        "reason": str(reason)[:500] if isinstance(reason, str) else None,
    }
    emit_event(
        session,
        user=ctx.user,
        event_type="local_folder.opened",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={"tool": body.tool, "entity_kind": entry["tool"], "launched": launched},
    )
    await session.commit()
    return envelope(answer)
