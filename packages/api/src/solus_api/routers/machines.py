"""Project-scoped member routes (SOLUSDEV-320 resolution 9; docs/api/solus.md §2.1,
docs/api/findings.md): `PUT …/members/me/machines/{companion_id}` populated over the
caller's live bridge (P5-T1), `PUT …/members/me/preferences` (P5-T2) and
`GET …/environment/divergences` (P5-T3). "me" is `ctx.user`; the team members router
stays at `/teams/{id}/members`.
"""

from __future__ import annotations

import logging
import re
from typing import Annotated, Any, Final

from fastapi import APIRouter, Path, Request

from solus_api.agent.tools.tool import ToolException
from solus_api.core.responses import envelope
from solus_api.deps import BridgeSessionsDep, ProjectCtx, SessionDep, SettingsDep, require_role
from solus_api.graph.live import graph_changed_frame
from solus_api.models import Role, SolusSection, utcnow
from solus_api.routers.code_environment import _cached_probe
from solus_api.routers.local_folder import _live_session
from solus_api.schemas import serialize_entity
from solus_api.services.code_env import CodeEnvironment, HostPlatform, upsert_code_environment
from solus_api.services.code_environment_adapter import observed_environments
from solus_api.services.environment_divergence import (
    find_divergences_entry,
    recompute_divergences,
    recompute_divergences_guarded,
)
from solus_api.services.machines import MachineIn, ensure_member, find_machine, upsert_machine
from solus_api.services.physical_robots import GraphChangeCounts
from solus_api.services.solus_config import put_config_entry, serialize_entry
from solus_api.services.solus_payloads import MemberPreferences

logger = logging.getLogger("solus.routers.machines")

router = APIRouter(prefix="/api/v1/projects/{project_id}")

CompanionId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]
TOOL_VERSIONS_TOOL: Final = "machine.tool_versions"
#: The server's copy of the companion's fixed list (`solus_companion.config
#: DEFAULT_VERSION_BINARIES`): any other key the bridge answers with is dropped.
TOOL_VERSION_BINARIES: Final = frozenset(
    {"python3", "node", "git", "kicad-cli", "arduino-cli", "ros2", "docker", "uv", "pip", "conda"}
)
_LINE_CAP: Final = 200
_ABS_PATH_RE: Final = re.compile(r"(?:[A-Za-z]:\\|/)[^\s)]+")


def _redact_version(line: str) -> str:
    """Printable, path-free, bounded: the companion redacts too, but attrs every member and
    SOL read are not trusted to one side (`pip 24.0 from /home/<user>/...` → `pip 24.0`)."""
    head = "".join(ch for ch in line.split(" from ", 1)[0] if ch.isprintable())
    return _ABS_PATH_RE.sub("<path>", head).strip()[:_LINE_CAP]


def _versions_of(result: dict[str, Any] | None) -> dict[str, str] | None:
    """The companion's `{tool_versions: {name: line}}` over the fixed binaries, redacted;
    None when it did not answer (then the stored dict is kept rather than emptied)."""
    if result is None or not isinstance(result.get("tool_versions"), dict):
        return None
    redacted = {
        k: _redact_version(v)
        for k, v in result["tool_versions"].items()
        if k in TOOL_VERSION_BINARIES and isinstance(v, str)
    }
    return {k: v for k, v in redacted.items() if v}


def _primary_environment(probe: dict[str, Any] | None, body: MachineIn) -> CodeEnvironment | None:
    """The probe's first observed environment, on the platform this PUT reports — or None
    when nothing was observed (a malformed probe records nothing)."""
    if probe is None:
        return None
    try:
        rows = observed_environments(probe)["environments"]
    except ToolException:
        return None
    if not rows:
        return None
    env = CodeEnvironment.model_validate(rows[0])
    return env.model_copy(update={"detected_on": HostPlatform(os=body.os, arch=body.arch)})


@router.put("/members/me/machines/{companion_id}")
async def put_machine(
    companion_id: CompanionId,
    body: MachineIn,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    sessions: BridgeSessionsDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    require_role(ctx, Role.MEMBER)
    project_id, user_id = ctx.project.id, ctx.user.id
    live = _live_session(sessions, ctx, companion_id)
    cap = settings.bridge_tool_call_max_bytes
    # Both dispatches ride the probe cache: a PUT storm must not start ten subprocesses
    # on the caller's machine per request (security review M6).
    key = (user_id, project_id, companion_id)
    versions = (
        _versions_of(await _cached_probe(key, live, cap, tool=TOOL_VERSIONS_TOOL))
        if live is not None
        else None
    )
    probe = await _cached_probe(key, live, cap) if live is not None else None
    created = await find_machine(session, project_id, companion_id) is None
    machine = await upsert_machine(
        session, project_id, user_id, companion_id, body, tool_versions=versions
    )
    env = _primary_environment(probe, body)
    if env is not None:
        await upsert_code_environment(
            session,
            project_id,
            env,
            created_by=user_id,
            author="system",
            configured_entity_id=machine.id,
        )
    await recompute_divergences_guarded(session, project_id)
    logger.info(
        "machine put project=%s user=%s companion=%s bridge=%s tool_versions=%s environment=%s",
        project_id,
        user_id,
        companion_id,
        live is not None,
        versions is not None,
        env is not None,
    )
    data = serialize_entity(machine)
    await session.commit()
    await request.app.state.graph_hub.publish(
        project_id,
        graph_changed_frame(
            project_id=project_id,
            source_id=None,
            sync_id=None,
            counts=GraphChangeCounts(
                entities_created=2 if created else 0,
                entities_updated=0 if created else 1,
                relations_created=1 if created else 0,
            ),
            at=utcnow().isoformat(),
        ),
    )
    return envelope(data)


@router.put("/members/me/preferences")
async def put_preferences(
    body: MemberPreferences, ctx: ProjectCtx, session: SessionDep
) -> dict[str, Any]:
    """The member's shared preference sections as ONE `members/<uid.hex>` CONFIG bound to
    the member node; a second PUT replaces it (same id, version +1)."""
    require_role(ctx, Role.MEMBER)
    member = await ensure_member(session, ctx.project.id, ctx.user.id)
    entry = await put_config_entry(
        session,
        ctx.project.id,
        SolusSection.MEMBERS,
        ctx.user.id.hex,
        body,
        text=f"{member.name} · preferences",
        configured_entity_id=member.id,
        created_by=ctx.user.id,
        author="user",
    )
    logger.info(
        "member preferences project=%s user=%s sections=%s version=%d",
        ctx.project.id,
        ctx.user.id,
        sorted(body.shared),
        entry.config_version,
    )
    data = serialize_entry(entry)
    await session.commit()
    return envelope(data)


@router.get("/environment/divergences")
async def get_environment_divergences(ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    """The stored `environment/divergences` document, computed on first read. A share-only
    reader (no team role) gets the computed document but stores nothing."""
    entry = await find_divergences_entry(session, ctx.project.id)
    if entry is None:
        entry = await recompute_divergences(session, ctx.project.id)
        if ctx.membership is not None:
            await session.commit()
    return envelope(entry.payload)
