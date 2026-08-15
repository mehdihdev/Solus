"""The Onshape panel — SOLUS-A7-01.

An HTTPS page Onshape loads in an iframe. Everything under `/api/v1/panel` is
**unauthenticated or panel-token authenticated, never Supabase authenticated**,
and that is the point: the Supabase dependency chain in `deps.py` provisions a
User + Team + Membership + Subscription + trial credits on first sight of any
valid JWT, and an Onshape-supplied identifier must never reach that path.

`test_panel.py` greps this file for the names of those dependencies, so it is
deliberately written without them — the ratchet is the point, not the prose.

**`{$userId}` is not a credential and is never accepted as one.** Onshape
appends it to the panel URL, but it is an unsigned string from a third party,
and Onshape user ids are visible to anyone sharing a document — so treating a
match as access would let a collaborator read someone's Solus graph. Its entire
role is client-side: the panel uses it to pick which stored token to send.

The approve / list / revoke half deliberately lives in `routers/users.py`, where
the authenticated-session dependency belongs. Keeping it out of this module is
what makes "no route under this prefix reaches provisioning" checkable.

Scope (A7 Decision 1): the panel DISPLAYS Solus content and PUSHES into Onshape.
It does not read click-selections back — the graph has no face-level key, and
every published description of Onshape's selection payload traces to someone
reading a minified bundle rather than documentation. SOL's REST path is
unaffected and keeps full read/write at face and feature granularity.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select

from solus_api.connectors.onshape import ONSHAPE_ID_RE, SELECTION_KEY
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import (
    PANEL_TOKEN_TTL_DAYS,
    PanelUser,
    SessionDep,
    SettingsDep,
    get_project_context,
    panel_token_hash,
    visible_project_ids,
)
from solus_api.models import (
    PanelBinding,
    PanelPairing,
    Source,
    SourceStatus,
    SourceType,
    ensure_utc,
    utcnow,
)
from solus_api.routers.entities import list_entities
from solus_api.routers.panel_assets import PANEL_CSS, PANEL_HTML, PANEL_JS

router = APIRouter(tags=["panel"])

#: Mirrors OAUTH_STATE_TTL_MINUTES — a handshake, not a session.
PAIRING_TTL_MINUTES = 10
#: interval 5s over a 600s TTL is ~120 legitimate polls. Durable on the row,
#: unlike the in-process rate limiter, which cannot see the client IP behind the
#: ALB and therefore shares one bucket across every unauthenticated caller.
MAX_POLLS = 200
POLL_INTERVAL_SECONDS = 5
#: Unambiguous alphabet: no O/0, I/1, or U (which can read as V in some fonts).
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTVWXYZ23456789"
_CODE_GROUPS = 2
_CODE_GROUP_LEN = 4

_panel_bearer = HTTPBearer(auto_error=False)


def _user_code() -> str:
    body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_GROUPS * _CODE_GROUP_LEN))
    return "-".join(body[i : i + _CODE_GROUP_LEN] for i in range(0, len(body), _CODE_GROUP_LEN))


def _onshape_id(value: str | None, field: str) -> str | None:
    """Validate an Onshape-supplied id, or refuse it.

    These strings reach a human's approval screen and a database column, so they
    pass the connector's own id charset first — an unauthenticated third party
    must not be able to put markup in front of the person approving a pairing.

    Empty means ABSENT, which is only meaningful for the optional
    `onshape_user_id` hint. Route params that are required carry
    `min_length=1` so an empty one is a 422 here rather than a silent no-match
    downstream — an empty document id matches no tracked selection and would
    otherwise render as "this document isn't in a project you can see", which
    answers a question the caller never asked.
    """
    if value is None or value == "":
        return None
    if not ONSHAPE_ID_RE.fullmatch(value):
        raise APIError(422, "validation_error", f"{field} is not an Onshape id")
    return value


# --------------------------------------------------------------- pairing


@router.post("/api/v1/panel/pair/start")
async def pair_start(session: SessionDep, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Begin a pairing. Grants nothing — it only mints a code to be approved."""
    raw = (body or {}).get("onshape_user_id")
    onshape_user_id = _onshape_id(raw if isinstance(raw, str) else None, "onshape_user_id")

    # Opportunistic cleanup; no cron needed for a table this small.
    await session.execute(delete(PanelPairing).where(PanelPairing.expires_at <= utcnow()))

    device_code = secrets.token_urlsafe(32)
    pairing = PanelPairing(
        device_code_hash=hashlib.sha256(device_code.encode()).hexdigest(),
        user_code=_user_code(),
        onshape_user_id=onshape_user_id,
        expires_at=utcnow() + timedelta(minutes=PAIRING_TTL_MINUTES),
    )
    session.add(pairing)
    await session.commit()
    return envelope(
        {
            "user_code": pairing.user_code,
            "device_code": device_code,
            "expires_at": pairing.expires_at.isoformat(),
            "interval": POLL_INTERVAL_SECONDS,
        }
    )


@router.post("/api/v1/panel/pair/poll")
async def pair_poll(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_panel_bearer)] = None,
) -> dict[str, Any]:
    """Exchange an approved device code for a panel token, exactly once.

    The device code travels as a Bearer so this loop lands in a per-credential
    rate-limit bucket rather than the shared unauthenticated one.
    """
    if credentials is None:
        raise APIError(404, "invalid_pairing", "No such pairing")
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    pairing = await session.get(PanelPairing, digest)

    # Unknown, expired and exhausted are indistinguishable — no oracle.
    if pairing is None or ensure_utc(pairing.expires_at) <= utcnow():
        if pairing is not None:
            await session.delete(pairing)
            await session.commit()
        raise APIError(404, "invalid_pairing", "No such pairing")

    pairing.poll_count += 1
    if pairing.poll_count > MAX_POLLS:
        await session.delete(pairing)
        await session.commit()
        raise APIError(404, "invalid_pairing", "No such pairing")

    if pairing.approved_user_id is None:
        await session.commit()
        return envelope({"status": "pending", "interval": POLL_INTERVAL_SECONDS})

    # Minted at REDEMPTION, not at approval: the plaintext is never stored, not
    # even for the ten-minute window.
    token = secrets.token_urlsafe(32)
    binding = PanelBinding(
        user_id=pairing.approved_user_id,
        token_hash=panel_token_hash(token),
        onshape_user_id=pairing.onshape_user_id,
        expires_at=utcnow() + timedelta(days=PANEL_TOKEN_TTL_DAYS),
    )
    session.add(binding)
    await session.delete(pairing)  # single use
    await session.commit()
    return envelope(
        {"status": "linked", "token": token, "expires_at": binding.expires_at.isoformat()}
    )


# --------------------------------------------------------------- context


@router.get("/api/v1/panel/context")
async def panel_context(
    user: PanelUser,
    session: SessionDep,
    document_id: Annotated[str, Query(min_length=1, max_length=64)],
    element_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> dict[str, Any]:
    """Which Solus projects this user can see that track this Onshape document.

    Resolved at REQUEST time from live membership rather than stored on the
    binding: a document can appear in several projects, one Onshape account maps
    to many projects, and a stored answer would go stale the moment someone
    edits a source's document selection.

    Zero matches is an empty list, never a 403 — a panel must not become an
    existence oracle for other tenants' documents.
    """
    _onshape_id(document_id, "document_id")
    _onshape_id(element_id, "element_id")

    visible = await visible_project_ids(session, user.id)
    if not visible:
        return envelope({"projects": []})

    sources = await session.scalars(
        select(Source).where(
            Source.type == SourceType.ONSHAPE,
            Source.status == SourceStatus.CONNECTED,
            Source.project_id.in_(visible),
        )
    )
    projects: list[dict[str, Any]] = []
    for source in sources.all():
        config = source.config if isinstance(source.config, dict) else {}
        tracked = config.get(SELECTION_KEY)
        documents = tracked if isinstance(tracked, list) else []
        # Legacy single-document shape (CAD-01) still accepted.
        if config.get("document_id"):
            documents = [*documents, config["document_id"]]
        if document_id not in documents:
            continue
        projects.append(
            {
                "id": str(source.project_id),
                "team_id": str(source.team_id),
                "source_id": str(source.id),
                "name": source.name,
            }
        )
    return envelope({"projects": projects})


@router.get("/api/v1/panel/projects/{project_id}/parts")
async def panel_parts(
    project_id: uuid.UUID,
    user: PanelUser,
    session: SessionDep,
    document_id: Annotated[str, Query(min_length=1, max_length=64)],
    element_id: Annotated[str, Query(min_length=1, max_length=64)],
) -> dict[str, Any]:
    """Parts Solus knows for this document/element, in this project.

    The project the panel names carries NO authority: `get_project_context` is
    called directly with the user resolved from the binding, so a project the
    binding cannot see 404s exactly as it would for any other caller. Calling it
    as a plain function (the `routers/bridge.py` precedent) means it never
    touches the provisioning dependency.
    """
    _onshape_id(document_id, "document_id")
    _onshape_id(element_id, "element_id")
    ctx = await get_project_context(project_id, user, session)
    return await list_entities(
        ctx=ctx, session=session, external_ref_prefix=f"{document_id}:{element_id}:"
    )


# ------------------------------------------------------------ the page


def _asset(settings: Settings, body: str, media_type: str) -> Response:
    return Response(
        body,
        media_type=media_type,
        headers={
            "Content-Security-Policy": _panel_csp(settings),
            # These are served from the API origin, so a sniffed type here
            # would be a script running under it.
            "X-Content-Type-Options": "nosniff",
        },
    )


def _panel_csp(settings: Settings) -> str:
    ancestors = settings.panel_frame_ancestors
    return (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        f"img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors {ancestors}"
    )


@router.get("/panel", response_class=HTMLResponse, include_in_schema=False)
async def panel_page(settings: SettingsDep) -> Response:
    """The panel document.

    CSP is set on THIS response only. `frame-ancestors` is meaningless on a JSON
    body, so a global policy would touch every response for no benefit — and a
    global `default-src 'self'` would break the Swagger UI, which loads from a
    CDN. Equally, no global `X-Frame-Options`: it has no allowlist form, so it
    could only ever forbid the framing this feature exists to permit.
    """
    return _asset(settings, PANEL_HTML, "text/html; charset=utf-8")


@router.get("/panel/app.css", include_in_schema=False)
async def panel_style(settings: SettingsDep) -> Response:
    return _asset(settings, PANEL_CSS, "text/css; charset=utf-8")


@router.get("/panel/app.js", include_in_schema=False)
async def panel_script(settings: SettingsDep) -> Response:
    """Separate from the page so the CSP can be `script-src 'self'` rather than a
    hand-maintained inline hash."""
    return _asset(settings, PANEL_JS, "application/javascript; charset=utf-8")


__all__ = ["router"]
