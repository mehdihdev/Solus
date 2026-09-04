"""API.md §2.13 — client-originated data-event ingest (ADR-011).

The desktop host is the first client producer: it batches bridge refusals
(`extension.bridge_refused`, ADR-035 §2) and posts them here. Server-originated
events never take this route. Everything in the body is untrusted:

- `event_type` is a CLOSED set (a client cannot mint server event names);
- bodies are strict (unknown fields reject), batches and payloads are capped;
- the caller's identity comes from the JWT, never the body;
- `project_id` is kept only when the caller can resolve that project — a
  foreign id is dropped silently (never an existence oracle), and the team id
  is derived server-side from the project.

Consent gating stays in `emit_event`: without `data_collection_consent` the
call still succeeds and nothing is stored.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import error_response
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, SessionDep, SettingsDep
from solus_api.extensions.ratelimit import get_or_create_limiter
from solus_api.models import Membership, MembershipStatus, Project, ProjectMembership
from solus_api.services.events import emit_event

router = APIRouter(prefix="/api/v1/events")

#: Event names a client may assert. Everything else is server-originated.
CLIENT_EVENT_TYPES = frozenset({"extension.bridge_refused"})
MAX_EVENTS_PER_BATCH = 50
MAX_PAYLOAD_BYTES = 4096
MAX_PAYLOAD_KEYS = 16
LIMITER_ATTR = "client_event_limiter"


class ClientEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    project_id: uuid.UUID | None = None
    payload: dict[str, Any]

    @field_validator("event_type")
    @classmethod
    def _closed_set(cls, value: str) -> str:
        if value not in CLIENT_EVENT_TYPES:
            raise ValueError("event_type is not a client-originated event")
        return value

    @field_validator("payload")
    @classmethod
    def _bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > MAX_PAYLOAD_KEYS:
            raise ValueError(f"payload has more than {MAX_PAYLOAD_KEYS} keys")
        size = sum(len(str(k)) + len(str(v)) for k, v in value.items())
        if size > MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload exceeds {MAX_PAYLOAD_BYTES} bytes")
        return value


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: Annotated[list[ClientEvent], Field(min_length=1, max_length=MAX_EVENTS_PER_BATCH)]


async def _resolvable_projects(
    session: AsyncSession, user_id: uuid.UUID, ids: set[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """project id → team id for the ids this user can resolve (active team
    member or direct project member). Anything else is dropped by the caller."""
    if not ids:
        return {}
    live = (Project.id.in_(ids), Project.deleted_at.is_(None))
    team_member = (
        select(Project.id, Project.team_id)
        .join(Membership, Membership.team_id == Project.team_id)
        .where(*live, Membership.user_id == user_id, Membership.status == MembershipStatus.ACTIVE)
    )
    direct = (
        select(Project.id, Project.team_id)
        .join(ProjectMembership, ProjectMembership.project_id == Project.id)
        .where(*live, ProjectMembership.user_id == user_id, ProjectMembership.deleted_at.is_(None))
    )
    rows = [*(await session.execute(team_member)).all(), *(await session.execute(direct)).all()]
    return {project_id: team_id for project_id, team_id in rows}


@router.post("", status_code=202, response_model=None)
async def ingest_events(
    batch: EventBatch,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
) -> dict[str, Any] | Response:
    limiter = get_or_create_limiter(request.app.state, LIMITER_ATTR, 60)
    if limiter.bump(str(user.id)) > settings.client_event_batches_per_minute_per_user:
        resp = error_response(429, "rate_limited", "Too many event batches; try again shortly")
        resp.headers["Retry-After"] = "60"
        return resp
    wanted = {e.project_id for e in batch.events if e.project_id is not None}
    resolvable = await _resolvable_projects(session, user.id, wanted)
    for event in batch.events:
        team_id = resolvable.get(event.project_id) if event.project_id else None
        emit_event(
            session,
            user=user,
            event_type=event.event_type,
            team_id=team_id,
            project_id=event.project_id if team_id is not None else None,
            payload=event.payload,
        )
    await session.commit()
    return envelope({"accepted": len(batch.events)})
