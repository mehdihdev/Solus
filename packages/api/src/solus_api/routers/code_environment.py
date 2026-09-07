"""`GET /projects/{id}/code-environment` — this machine's Code environment
(SOLUSDEV-250 / INTEGRATIONS I3; `docs/api/code-environment.md` §2).

The probe is LIVE over the caller's own bridge session (`code.probe_environment`);
requirements, conflicts and the proposal are pure reads of the graph. Nothing
here executes a command — that is SOL + the approval card only.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Final

from fastapi import APIRouter, Query

from solus_api.agent.tools.environment import resolve_environment
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.service import dispatch
from solus_api.core.responses import envelope
from solus_api.deps import BridgeSessionsDep, ProjectCtx, SessionDep, SettingsDep, require_role
from solus_api.models import Role
from solus_api.routers.local_folder import _live_session, _machine_source
from solus_api.schemas import serialize_source
from solus_api.services.events import emit_event

logger = logging.getLogger("solus.routers.code_environment")

router = APIRouter(prefix="/api/v1/projects/{project_id}/code-environment")

PROBE_TOOL: Final = "code.probe_environment"
_PROBE_TIMEOUT_SECONDS: Final = 25.0
#: Security review M6: the desktop polls this route every 30 s and on window
#: focus while a probe can take longer than that — without a bound, probes
#: overlap and each one spawns several subprocesses on the customer machine.
#: One live probe per (user, project, machine) is reused for this long.
PROBE_CACHE_SECONDS: Final = 10.0
_ProbeKey = tuple[uuid.UUID, uuid.UUID, str]
_probe_cache: dict[_ProbeKey, tuple[float, dict[str, Any] | None]] = {}
_probe_locks: dict[_ProbeKey, asyncio.Lock] = {}


async def _cached_probe(key: _ProbeKey, live: Any, call_cap: int) -> dict[str, Any] | None:
    """The probe for `key`, at most once per PROBE_CACHE_SECONDS and never
    two in flight for the same key (the second caller awaits the first)."""
    lock = _probe_locks.setdefault(key, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _probe_cache.get(key)
        if cached is not None and now - cached[0] < PROBE_CACHE_SECONDS:
            return cached[1]
        probe = await _probe(live, call_cap)
        _probe_cache[key] = (now, probe)
        for stale in [k for k, (at, _) in _probe_cache.items() if now - at >= PROBE_CACHE_SECONDS]:
            _probe_cache.pop(stale, None)
            _probe_locks.pop(stale, None)
        return probe


async def _probe(live: Any, call_cap: int) -> dict[str, Any] | None:
    if live is None or not any(spec.descriptor.name == PROBE_TOOL for spec in live.inventory):
        return None
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            result = await dispatch(live, PROBE_TOOL, {}, call_cap_bytes=call_cap)
    except (TimeoutError, ToolException):
        logger.info("code environment probe declined")
        return None
    return result.value if result.ok and isinstance(result.value, dict) else None


@router.get("")
async def get_code_environment(
    ctx: ProjectCtx,
    session: SessionDep,
    sessions: BridgeSessionsDep,
    settings: SettingsDep,
    machine_id: str = Query(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$"),
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    source = await _machine_source(session, ctx, machine_id)
    live = _live_session(sessions, ctx, machine_id)
    code_server = live is not None and any(
        spec.descriptor.name == PROBE_TOOL for spec in live.inventory
    )
    probe = (
        await _cached_probe(
            (ctx.user.id, ctx.project.id, machine_id), live, settings.bridge_tool_call_max_bytes
        )
        if source
        else None
    )
    proposal = await resolve_environment(session, ctx.project.id) if source else None
    emit_event(
        session,
        user=ctx.user,
        event_type="code_environment.viewed",
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload={
            "linked": source is not None,
            "probed": probe is not None,
            "conflicts": len((proposal or {}).get("conflicts", [])),
        },
    )
    files = sorted(
        {
            r["source_file"]
            for env in (proposal or {}).get("environments", [])
            for r in env["requirements"]
        }
    )
    return envelope(
        {
            "source": serialize_source(source) if source is not None else None,
            "bridge": {"connected": live is not None, "code_server": code_server},
            "probe": probe,
            "requirements": {
                "count": (proposal or {}).get("requirement_count", 0),
                "files": files,
            },
            "conflicts": (proposal or {}).get("conflicts", []),
            "proposal": (
                {"environments": proposal["environments"], "split": proposal["split"]}
                if proposal
                else None
            ),
        }
    )
