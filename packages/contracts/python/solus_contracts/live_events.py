"""Live change-hint frames (ADR-037, SOLUSDEV-312); wire twin of shared-types `live-events.ts`.

Two SSE streams carry these frames:

* ``GET /api/v1/projects/{project_id}/events`` — the PROJECT channel.
* ``GET /api/v1/users/me/events`` — the caller's USER channel plus the TEAM channel of
  every team they belong to.

Every frame is an invalidation HINT: ids, counts and versions only. A frame never
carries names, emails, invite tokens or CAD data — the client answers it by
refetching through the ordinary REST route it already uses. The SSE ``event:`` name
is the frame's ``type``; the ``ready`` frame is the exception and carries no
``type`` field (its event name is ``ready``).

`hardware.devices_changed` is the one deliberate exception to hint-only (SOLUSDEV-250):
a small, machine-local full list delivered only in-process, never over Redis.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Redis pub/sub prefix: ``solus:live:{kind}:{id}``.
LIVE_CHANNEL_PREFIX = "solus:live"
ChannelKind = Literal["project", "team", "user"]
CHANNEL_KINDS: tuple[ChannelKind, ...] = ("project", "team", "user")

#: Idle keepalive comment interval on both streams.
KEEPALIVE_SECONDS = 25
#: Upper bound between access re-verifications of an open stream.
REVERIFY_SECONDS = 30

JobStatusName = Literal["queued", "running", "succeeded", "failed", "cancelled"]


def channel_name(kind: ChannelKind, scope_id: uuid.UUID) -> str:
    """The Redis channel for one scope. Routing is structural (ADR-037 §1)."""
    return f"{LIVE_CHANNEL_PREFIX}:{kind}:{scope_id}"


class _Frame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    #: ISO-8601 UTC timestamp of the committed change.
    at: str = Field(min_length=1, max_length=64)


# ------------------------------------------------------------ project channel


class GraphChangeCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entities_created: int = Field(ge=0)
    entities_updated: int = Field(ge=0)
    entities_deleted: int = Field(ge=0)
    relations_created: int = Field(ge=0)
    relations_deleted: int = Field(ge=0)


class GraphChanged(_Frame):
    """The project's graph moved (SOLUSDEV-167). Counts are advisory."""

    type: Literal["graph.changed"] = "graph.changed"
    project_id: uuid.UUID
    source_id: uuid.UUID | None
    sync_id: uuid.UUID | None
    counts: GraphChangeCounts


class HardwareDevicesChanged(_Frame):
    """SOLUSDEV-250 machine-local device list. Full list, local delivery only."""

    type: Literal["hardware.devices_changed"] = "hardware.devices_changed"
    project_id: uuid.UUID
    devices: list[dict[str, Any]]


class LayoutChanged(_Frame):
    """The shared workspace layout was saved at ``version``."""

    type: Literal["layout.changed"] = "layout.changed"
    project_id: uuid.UUID
    version: int = Field(ge=0)


class SourcesChanged(_Frame):
    """A source was added, removed, or changed status / sync state."""

    type: Literal["sources.changed"] = "sources.changed"
    project_id: uuid.UUID
    source_id: uuid.UUID | None


class ProjectUpdated(_Frame):
    """The project row changed (rename, archive, unarchive, delete)."""

    type: Literal["project.updated"] = "project.updated"
    project_id: uuid.UUID
    team_id: uuid.UUID


class JobUpdated(_Frame):
    """A project job changed status. Progress-only updates are not published."""

    type: Literal["job.updated"] = "job.updated"
    project_id: uuid.UUID
    job_id: uuid.UUID
    status: JobStatusName


class ProjectStreamReady(BaseModel):
    """Data of the project stream's ``ready`` event."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: uuid.UUID




# -------------------------------------------------------- team + user channels


class TeamUpdated(_Frame):
    """Team name or settings changed."""

    type: Literal["team.updated"] = "team.updated"
    team_id: uuid.UUID


class TeamMembersChanged(_Frame):
    """A member joined, left, was removed, or changed role."""

    type: Literal["team.members_changed"] = "team.members_changed"
    team_id: uuid.UUID


class TeamInvitesChanged(_Frame):
    """An invite was created, revoked or accepted. Only admins can refetch the list."""

    type: Literal["team.invites_changed"] = "team.invites_changed"
    team_id: uuid.UUID


class TeamProjectsChanged(_Frame):
    """A project in the team was created, renamed, archived or deleted."""

    type: Literal["team.projects_changed"] = "team.projects_changed"
    team_id: uuid.UUID
    project_id: uuid.UUID | None


class TeamActivity(_Frame):
    """An activity-feed row was appended."""

    type: Literal["team.activity"] = "team.activity"
    team_id: uuid.UUID
    project_id: uuid.UUID | None
    actor_id: uuid.UUID | None


class NotificationCreated(_Frame):
    """A notification landed for this user."""

    type: Literal["notification.created"] = "notification.created"
    user_id: uuid.UUID


class MembershipChanged(_Frame):
    """This user's team or project-share membership changed (joined, role, left)."""

    type: Literal["membership.changed"] = "membership.changed"
    user_id: uuid.UUID
    team_id: uuid.UUID | None
    project_id: uuid.UUID | None


class AccessRevoked(_Frame):
    """Access ended for a scope. Open streams re-verify immediately and close if needed."""

    type: Literal["access.revoked"] = "access.revoked"
    user_id: uuid.UUID | None
    team_id: uuid.UUID | None
    project_id: uuid.UUID | None

    @model_validator(mode="after")
    def _names_a_scope(self) -> Self:
        if self.user_id is None and self.team_id is None and self.project_id is None:
            raise ValueError("access.revoked must name a user, team or project")
        return self


class AccountStreamReady(BaseModel):
    """Data of the account stream's ``ready`` event: the teams now subscribed."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    user_id: uuid.UUID
    team_ids: list[uuid.UUID]


AccountFrame = (
    TeamUpdated
    | TeamMembersChanged
    | TeamInvitesChanged
    | TeamProjectsChanged
    | TeamActivity
    | NotificationCreated
    | MembershipChanged
    | AccessRevoked
)

ProjectFrame = (
    GraphChanged
    | HardwareDevicesChanged
    | LayoutChanged
    | SourcesChanged
    | ProjectUpdated
    | JobUpdated
    | AccessRevoked
)

PROJECT_EVENT_TYPES: tuple[str, ...] = (
    "graph.changed",
    "hardware.devices_changed",
    "layout.changed",
    "sources.changed",
    "project.updated",
    "job.updated",
    "access.revoked",
)
ACCOUNT_EVENT_TYPES: tuple[str, ...] = (
    "team.updated",
    "team.members_changed",
    "team.invites_changed",
    "team.projects_changed",
    "team.activity",
    "notification.created",
    "membership.changed",
    "access.revoked",
)
