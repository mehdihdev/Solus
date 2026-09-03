"""§10 Team extension policies — owner-set defaults and team-wide blocks
(SOLUSDEV-235 / ADR-035, task EXT-10; docs/api/extensions.md §10–§12).

`TeamCtx` (non-member → 404) then `require_role(OWNER)` (everyone else → 403).
Writes ride a per-team `FixedWindowLimiter` (§12) and emit the §11 events:
`extension.grants_changed` with `scope: "team"` for every policy write and one
`extension.disable` per project whose install a block just switched off.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import func, select

from solus_api.core.errors import APIError, error_response
from solus_api.core.pagination import cursor_filter, page_meta
from solus_api.core.responses import envelope
from solus_api.deps import SessionDep, SettingsDep, TeamContext, TeamCtx, require_role
from solus_api.extensions.policy import (
    NO_POLICY_STATE,
    DisabledInstall,
    changed_keys,
    disable_installs_for_block,
    get_policy,
    policy_state,
    resolve_approved_extension,
    upsert_policy,
    validate_default_settings,
)
from solus_api.extensions.schemas import serialize_policy
from solus_api.models import Extension, Role, TeamExtensionPolicy
from solus_api.services.artifacts import FixedWindowLimiter
from solus_api.services.events import emit_event

router = APIRouter(prefix="/api/v1/teams/{team_id}/extensions/policies")

#: §3 — `{slug}` is the manifest `extension.id`; garbage is 422 before any lookup.
SLUG_PATTERN = r"^[a-z][a-z0-9-]{1,63}$"
Slug = Annotated[str, Path(pattern=SLUG_PATTERN)]

WRITE_BUDGET_SETTING = "extension_policy_writes_per_minute_per_team"
WRITE_WINDOW_SECONDS = 60
#: `app.state` slot for the §12 per-team write budget (created lazily so the
#: router needs no `main.create_app` wiring of its own).
LIMITER_STATE_ATTR = "extension_policy_write_limiter"


class PolicyWrite(BaseModel):
    """§10 PUT body: `extra="forbid"`, at least one key, never blocked AND default."""

    model_config = ConfigDict(extra="forbid", strict=True)

    blocked: bool | None = None
    default_installed: bool | None = None
    default_settings: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _shape(self) -> "PolicyWrite":
        if not self.changes():
            raise ValueError("at least one of blocked, default_installed, default_settings")
        if self.blocked and self.default_installed:
            raise ValueError("a blocked extension cannot also be default_installed")
        return self

    def changes(self) -> dict[str, Any]:
        """The keys the caller actually set (explicit nulls count as unset)."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


# ------------------------------------------------------------------ helpers
def _limiter(request: Request) -> FixedWindowLimiter:
    limiter: FixedWindowLimiter | None = getattr(request.app.state, LIMITER_STATE_ATTR, None)
    if limiter is None:
        limiter = FixedWindowLimiter(window_seconds=WRITE_WINDOW_SECONDS)
        setattr(request.app.state, LIMITER_STATE_ATTR, limiter)
    return limiter


async def _write_budget_exceeded(
    request: Request, ctx: TeamContext, session: SessionDep, settings: SettingsDep
) -> Response | None:
    """§12: over budget → 429 + Retry-After, recorded as a data event (CLAUDE.md §7)."""
    limit: int = getattr(settings, WRITE_BUDGET_SETTING)
    if _limiter(request).bump(str(ctx.team.id)) <= limit:
        return None
    emit_event(
        session,
        user=ctx.user,
        event_type="extension.rate_limited",
        team_id=ctx.team.id,
        payload={"budget": WRITE_BUDGET_SETTING, "limit": limit},
    )
    await session.commit()
    response = error_response(429, "rate_limited", "Too many policy writes; slow down")
    response.headers["Retry-After"] = str(WRITE_WINDOW_SECONDS)
    return response


def _emit_policy_changed(session: SessionDep, ctx: TeamContext, slug: str, keys: list[str]) -> None:
    """§11 `extension.grants_changed` with `scope: "team"` — the policy-write event."""
    emit_event(
        session,
        user=ctx.user,
        event_type="extension.grants_changed",
        team_id=ctx.team.id,
        payload={
            "slug": slug,
            "scope": "team",
            "added_scopes": [],
            "removed_scopes": [],
            "added_network": [],
            "removed_network": [],
            "changed_keys": keys,
        },
    )


def _emit_disables(
    session: SessionDep, ctx: TeamContext, slug: str, disabled: list[DisabledInstall]
) -> None:
    for item in disabled:
        emit_event(
            session,
            user=ctx.user,
            event_type="extension.disable",
            team_id=ctx.team.id,
            project_id=item.project_id,
            payload={"slug": slug, "version": item.version, "reason": "team_policy"},
        )


# ------------------------------------------------------------------- routes
@router.get("")
async def list_policies(
    ctx: TeamCtx,
    session: SessionDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    require_role(ctx, Role.OWNER)
    stmt = (
        select(TeamExtensionPolicy, Extension)
        .join(Extension, Extension.id == TeamExtensionPolicy.extension_id)
        .where(TeamExtensionPolicy.team_id == ctx.team.id)
        .order_by(TeamExtensionPolicy.created_at.desc(), TeamExtensionPolicy.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(
            cursor_filter(TeamExtensionPolicy.created_at, TeamExtensionPolicy.id, cursor)
        )
    pairs = list((await session.execute(stmt)).all())
    visible, meta = page_meta([policy for policy, _ in pairs], limit)
    items = [serialize_policy(policy, ext).payload() for policy, ext in pairs[: len(visible)]]
    return envelope(items, meta=meta)


@router.put("/{slug}", response_model=None)
async def put_policy(
    slug: Slug,
    body: PolicyWrite,
    request: Request,
    ctx: TeamCtx,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    require_role(ctx, Role.OWNER)
    if limited := await _write_budget_exceeded(request, ctx, session, settings):
        return limited
    extension, latest = await resolve_approved_extension(session, slug)
    changes = body.changes()
    if "default_settings" in changes:
        validate_default_settings(latest.manifest, changes["default_settings"])

    result = await upsert_policy(
        session,
        team_id=ctx.team.id,
        extension_id=extension.id,
        changes=changes,
        set_by=ctx.user.id,
    )
    if result.newly_blocked:
        disabled = await disable_installs_for_block(
            session, team_id=ctx.team.id, extension_id=extension.id
        )
        _emit_disables(session, ctx, extension.slug, disabled)
    if result.changed_keys:
        _emit_policy_changed(session, ctx, extension.slug, result.changed_keys)
    await session.commit()
    await session.refresh(result.policy)
    return JSONResponse(
        status_code=201 if result.created else 200,
        content=envelope(serialize_policy(result.policy, extension).payload()),
    )


@router.delete("/{slug}", status_code=204, response_model=None)
async def delete_policy(
    slug: Slug,
    request: Request,
    ctx: TeamCtx,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    require_role(ctx, Role.OWNER)
    if limited := await _write_budget_exceeded(request, ctx, session, settings):
        return limited
    extension = await session.scalar(
        select(Extension).where(func.lower(Extension.slug) == slug.lower())
    )
    policy = await get_policy(session, ctx.team.id, extension.id) if extension else None
    if extension is None or policy is None:
        raise APIError(404, "not_found", "No policy for this extension")
    reset_keys = changed_keys(policy_state(policy), NO_POLICY_STATE)
    await session.delete(policy)
    _emit_policy_changed(session, ctx, extension.slug, reset_keys)
    await session.commit()
    return Response(status_code=204)


__all__ = ["router"]
