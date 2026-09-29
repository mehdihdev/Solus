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

import logging
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import error_response
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, SessionDep, SettingsDep, visible_project_ids
from solus_api.extensions.ratelimit import get_or_create_limiter
from solus_api.models import Project
from solus_api.services.events import emit_event

logger = logging.getLogger("solus.events.ingest")

router = APIRouter(prefix="/api/v1/events")

#: Event names a client may assert. Everything else is server-originated.
CLIENT_EVENT_TYPES = frozenset(
    {
        "extension.bridge_refused",
        # SOLUSDEV-242 (HOME H1): the desktop opened/switched to a project.
        "project.switched",
        # SOLUSDEV-246 (STORE ST3): the desktop suggested a widget in context after a
        # source kind connected.
        "store.suggested",
        # SOLUSDEV-311: a desktop error caught by a boundary or global handler, or a
        # prior-session main/renderer crash reported on the next launch.
        "client.error",
    }
)
MAX_EVENTS_PER_BATCH = 50
MAX_PAYLOAD_BYTES = 4096
MAX_PAYLOAD_KEYS = 16
LIMITER_ATTR = "client_event_limiter"


class ProjectSwitchedPayload(BaseModel):
    """`project.switched` (SOLUSDEV-242): the project left (resolvability-checked
    at ingest like the top-level id) and which surface drove the switch."""

    model_config = ConfigDict(extra="forbid")

    from_project_id: uuid.UUID | None = None
    surface: Literal["home", "topbar", "team", "validation", "onboarding", "overview"]


class StoreSuggestedPayload(BaseModel):
    """`store.suggested` (SOLUSDEV-246 ST3): which extension the desktop
    suggested, the newly connected source kinds that unlocked it, and how many
    candidates there were. Slugs follow the manifest id rule; kinds are the
    contract's closed set."""

    model_config = ConfigDict(extra="forbid")

    slug: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,63}$")]
    unlocked_by: Annotated[
        list[Literal["code", "eda", "cad", "canbus", "runtime"]], Field(max_length=5)
    ]
    candidates: Annotated[int, Field(ge=1, le=500)]


class ClientErrorPayload(BaseModel):
    """`client.error` (SOLUSDEV-311): WHERE and WHAT KIND, never the message or
    stack — those stay in the local log / Sentry. Every field is closed or patterned."""

    model_config = ConfigDict(extra="forbid")

    origin: Literal[
        "render", "window_error", "unhandled_rejection", "main_process", "renderer_gone"
    ]
    surface: Literal[
        "root",
        "home",
        "workspace",
        "bench",
        "sol",
        "store",
        "billing",
        "settings",
        "alert",
        "extension",
        "sol_window",
        "overlay",
        "ext_window",
        "main",
    ]
    error_name: Literal[
        "Error", "TypeError", "ReferenceError", "RangeError", "SyntaxError", "ApiError", "other"
    ]
    fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
    app_version: Annotated[
        str, StringConstraints(pattern=r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]{1,32})?$")
    ]


#: Per-event payload schemas. A client event WITH a schema is validated against
#: it (unknown keys, bad enums and malformed ids reject); the data-collection
#: store never accepts free-form strings under a Solus-authored event name.
PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "project.switched": ProjectSwitchedPayload,
    "store.suggested": StoreSuggestedPayload,
    "client.error": ClientErrorPayload,
}


class ClientEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    project_id: uuid.UUID | None = None
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _typed_payload(self) -> ClientEvent:
        schema = PAYLOAD_SCHEMAS.get(self.event_type)
        if schema is None:
            return self
        try:
            schema.model_validate(self.payload)
        except ValidationError as exc:
            raise ValueError(
                f"payload does not match {self.event_type}: {exc.error_count()} error(s)"
            ) from exc
        return self

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
    """project id → team id for the ids this user may read — exactly the set
    `deps.visible_project_ids` (and so `get_project_context`) admits. Anything
    else is dropped by the caller, never reported."""
    if not ids:
        return {}
    visible = ids & await visible_project_ids(session, user_id)
    if not visible:
        return {}
    rows = await session.execute(
        select(Project.id, Project.team_id).where(
            Project.id.in_(visible), Project.deleted_at.is_(None)
        )
    )
    return {project_id: team_id for project_id, team_id in rows.all()}


def _from_project_id(event: ClientEvent) -> uuid.UUID | None:
    """The `from_project_id` a switch event names, already validated as a UUID."""
    if event.event_type != "project.switched":
        return None
    value = event.payload.get("from_project_id")
    return uuid.UUID(str(value)) if value is not None else None


def _scoped_payload(event: ClientEvent, resolvable: dict[uuid.UUID, uuid.UUID]) -> dict[str, Any]:
    """Apply the same rule to ids INSIDE the payload as to the top-level id: a
    project the caller cannot resolve is dropped to null, never stored, never
    reported (no existence oracle). New dict — the event body is not mutated."""
    fid = _from_project_id(event)
    if event.event_type != "project.switched":
        return event.payload
    return {**event.payload, "from_project_id": str(fid) if fid in resolvable else None}


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
        # Server-originated abuse signal (CLAUDE.md §7): the closed client set
        # cannot mint this name, so it is emitted here, not accepted from the body.
        logger.warning("client event batches rate-limited user=%s", user.id)
        emit_event(session, user=user, event_type="client_events.rate_limited", payload={})
        await session.commit()
        resp = error_response(429, "rate_limited", "Too many event batches; try again shortly")
        resp.headers["Retry-After"] = "60"
        return resp
    wanted = {e.project_id for e in batch.events if e.project_id is not None}
    wanted |= {fid for e in batch.events if (fid := _from_project_id(e)) is not None}
    resolvable = await _resolvable_projects(session, user.id, wanted)
    for event in batch.events:
        team_id = resolvable.get(event.project_id) if event.project_id else None
        emit_event(
            session,
            user=user,
            event_type=event.event_type,
            team_id=team_id,
            project_id=event.project_id if team_id is not None else None,
            payload=_scoped_payload(event, resolvable),
        )
    await session.commit()
    return envelope({"accepted": len(batch.events)})
