"""SOLUSDEV-216 team GitHub App link routes (docs/api/github-orgs.md, ADR-039).

`install/start` + `install/complete` link an installation to a team, `installation`
reads or removes it. Credentials never appear in any response: the installation token is
minted on demand elsewhere and the install-time user token is revoked after the proof.
"""

from __future__ import annotations

from typing import Any, Final, Literal, Self

from fastapi import APIRouter, Request, Response
from pydantic import Field, model_validator

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import (
    IntegrationCacheDep,
    RequireVerified,
    SessionDep,
    SettingsDep,
    TeamCtx,
    require_role,
)
from solus_api.extensions.ratelimit import get_or_create_limiter, rate_limited_response
from solus_api.models import Role
from solus_api.routers.integrations import _resolve_redirect_uri
from solus_api.schemas import StrictModel, serialize_team_installation
from solus_api.services import team_github_link as link
from solus_api.services.team_installations import (
    count_bound_sources,
    get_live_installation,
    revoke_installation,
)

router = APIRouter(prefix="/api/v1/teams/{team_id}/github", tags=["github-org"])

_REDIRECT_PROVIDER = "github"
INSTALL_FLOW_PER_MINUTE: Final = 10
_WINDOW_SECONDS: Final = 60
_START_LIMITER: Final = "github_install_start_limiter"
_COMPLETE_LIMITER: Final = "github_install_complete_limiter"


def _throttled(request: Request, attr: str, user: Any) -> Any | None:
    """A 429 response when `user` is over the install-flow budget for this route, else None.

    Checked before any state is created or consumed and before any GitHub call."""
    limiter = get_or_create_limiter(request.app.state, attr, _WINDOW_SECONDS)
    if limiter.bump(str(user.id)) > INSTALL_FLOW_PER_MINUTE:
        return rate_limited_response("Too many GitHub link attempts; slow down", _WINDOW_SECONDS)
    return None


class InstallStart(StrictModel):
    redirect_uri: str | None = Field(default=None, max_length=2048)


class InstallComplete(StrictModel):
    state: str = Field(min_length=1, max_length=128)
    # A "request" (a non-owner asked the org owner to install) may arrive with no code.
    code: str | None = Field(default=None, min_length=1, max_length=512)
    installation_id: int | None = Field(default=None, ge=1)
    setup_action: Literal["install", "update", "request"]

    @model_validator(mode="after")
    def _id_and_code_required_unless_requested(self) -> Self:
        if self.setup_action != "request" and (self.installation_id is None or self.code is None):
            raise ValueError("installation_id and code are required for install and update")
        return self


@router.post("/install/start", status_code=201)
async def install_start(
    request: Request,
    body: InstallStart,
    ctx: TeamCtx,
    session: SessionDep,
    settings: SettingsDep,
    _verified: RequireVerified,
) -> Any:
    require_role(ctx, Role.ADMIN)
    link.require_collaborative(ctx.team)
    if (limited := _throttled(request, _START_LIMITER, ctx.user)) is not None:
        return limited
    redirect_uri = _resolve_redirect_uri(_REDIRECT_PROVIDER, body.redirect_uri, settings)
    started = await link.start_install(
        session, user=ctx.user, team=ctx.team, settings=settings, redirect_uri=redirect_uri
    )
    return envelope(started)


@router.post("/install/complete", status_code=201)
async def install_complete(
    request: Request,
    body: InstallComplete,
    ctx: TeamCtx,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
    _verified: RequireVerified,
) -> Any:
    require_role(ctx, Role.ADMIN)
    link.require_collaborative(ctx.team)
    link.require_app_configured(settings)
    if (limited := _throttled(request, _COMPLETE_LIMITER, ctx.user)) is not None:
        return limited
    if body.setup_action == "request":
        await link.consume_state(session, state=body.state, user=ctx.user, team=ctx.team)
        response.status_code = 202
        return envelope({"status": "requested"})
    if body.installation_id is None or body.code is None:  # the validator rules this out
        raise APIError(422, "validation_error", "installation_id and code are required")
    outcome = await link.complete_install(
        session,
        user=ctx.user,
        team=ctx.team,
        state=body.state,
        code=body.code,
        installation_id=body.installation_id,
    )
    response.status_code = 201 if outcome.created else 200
    linker = await link.linked_by_user(session, outcome.installation)
    return envelope({"installation": serialize_team_installation(outcome.installation, linker)})


@router.get("/installation")
async def get_installation(ctx: TeamCtx, session: SessionDep) -> dict[str, Any]:
    row = await get_live_installation(session, ctx.team.id)
    if row is None:
        return envelope({"installation": None})
    linker = await link.linked_by_user(session, row)
    data = serialize_team_installation(row, linker).model_dump(mode="json")
    data["bound_source_count"] = await count_bound_sources(session, row)
    return envelope({"installation": data})


@router.delete("/installation")
async def delete_installation(
    ctx: TeamCtx, session: SessionDep, cache: IntegrationCacheDep
) -> dict[str, Any]:
    require_role(ctx, Role.ADMIN)
    link.require_collaborative(ctx.team)
    row = await get_live_installation(session, ctx.team.id)
    if row is None:
        raise APIError(404, "installation_missing", "This team has no linked GitHub organization.")
    manage_url = serialize_team_installation(row, None).manage_url
    disabled = await revoke_installation(session, row, actor=ctx.user, cache=cache)
    await session.commit()
    return envelope({"disabled_sources": disabled, "manage_url": manage_url})
