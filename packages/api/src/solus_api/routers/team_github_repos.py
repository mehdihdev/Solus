"""GET /api/v1/teams/{team_id}/github/repos (SOLUSDEV-216, docs/api/github-orgs.md s2).

The repos the team's GitHub App installation can see, in the OAuth picker's
`SelectableItem` shape. Any member (viewer included) may list. The list comes from the
per-installation integration cache; the installation token is minted on demand and never
leaves the connector.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from fastapi import APIRouter, Query, Request

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import SessionDep, TeamCtx
from solus_api.extensions.ratelimit import get_or_create_limiter, rate_limited_response
from solus_api.models import TeamKind
from solus_api.services.installation_sources import list_installation_repos
from solus_api.services.team_installations import require_active_installation

router = APIRouter(prefix="/api/v1/teams/{team_id}/github", tags=["github-org-repos"])

REPOS_PER_MINUTE: Final = 30
_WINDOW_SECONDS: Final = 60
_LIMITER_ATTR: Final = "github_repos_limiter"
MAX_QUERY_LENGTH: Final = 100
MAX_CURSOR_LENGTH: Final = 9
DEFAULT_LIMIT: Final = 50


def _offset(cursor: str | None) -> int:
    """The cursor is the opaque-by-contract offset of the next item."""
    if cursor is None:
        return 0
    if not cursor.isascii() or not cursor.isdigit() or len(cursor) > MAX_CURSOR_LENGTH:
        raise APIError(400, "invalid_cursor", "The cursor is not valid")
    return int(cursor)


def _item(record: dict[str, Any]) -> dict[str, Any] | None:
    name = record.get("full_name")
    if not isinstance(name, str) or not name:
        return None
    return {
        "id": name,
        "name": name,
        "subtitle": "private" if record.get("private") else "public",
        "config": {"repo": name, "branch": record.get("default_branch")},
    }


@router.get("/repos")
async def list_repos(
    request: Request,
    ctx: TeamCtx,
    session: SessionDep,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_LIMIT,
    q: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
) -> Any:
    limiter = get_or_create_limiter(request.app.state, _LIMITER_ATTR, _WINDOW_SECONDS)
    if limiter.bump(f"{ctx.user.id}:{ctx.team.id}") > REPOS_PER_MINUTE:
        return rate_limited_response("Too many repository listings; slow down", _WINDOW_SECONDS)
    if ctx.team.kind is TeamKind.PERSONAL:
        raise APIError(
            409,
            "personal_team_unsupported",
            "A personal team cannot link a GitHub organization.",
        )
    offset = _offset(cursor)
    inst = await require_active_installation(session, ctx.team.id)
    fetched = await list_installation_repos(request.app.state, inst)

    needle = (q or "").strip().casefold()
    items = [
        item
        for record in fetched.value
        if (item := _item(record)) is not None and needle in item["id"].casefold()
    ]
    page = items[offset : offset + limit]
    next_offset = offset + limit
    return envelope(
        page,
        meta={
            "total": len(items),
            "limit": limit,
            "has_next": next_offset < len(items),
            "next_cursor": str(next_offset) if next_offset < len(items) else None,
        },
    )
