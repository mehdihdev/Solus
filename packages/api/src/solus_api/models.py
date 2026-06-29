"""SQLAlchemy ORM models for Phase 1 (Foundation) — API.md §2.1–§2.3, §2.16.

UUIDv7 primary keys (§1.4, index locality). Enum columns store values, not
names, and use portable VARCHAR storage (no native PG enums before Alembic
baselines land).
"""

import enum
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid6 import uuid7


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize DB-returned datetimes (naive on SQLite) to aware UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def new_invite_token() -> str:
    return secrets.token_urlsafe(32)


class Base(DeclarativeBase):
    pass


class Role(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


ROLE_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}


class SolMode(enum.StrEnum):
    GUIDE = "guide"
    EXPERT = "expert"


class InviteStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobKind(enum.StrEnum):
    SYNC = "sync"
    CHECK_RUN = "check_run"
    PROVING = "proving"
    FINGERPRINT_SCAN = "fingerprint_scan"
    SIM_REBUILD = "sim_rebuild"


def _enum_column(enum_cls: type[enum.StrEnum]) -> Enum:
    return Enum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [member.value for member in e],
    )


class UuidPkMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class User(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "users"

    auth_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str | None] = mapped_column(String(255), default=None)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    sol_mode: Mapped[SolMode] = mapped_column(_enum_column(SolMode), default=SolMode.GUIDE)
    # ADR-011: collection is consent-gated; nothing is recorded until the user opts in.
    data_collection_consent: Mapped[bool] = mapped_column(Boolean, default=False)


class Team(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(255))
    is_personal: Mapped[bool] = mapped_column(Boolean, default=False)
    plan_status: Mapped[str] = mapped_column(String(32), default="trial")


class Membership(Base):
    __tablename__ = "memberships"

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(_enum_column(Role), default=Role.MEMBER)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Invite(UuidPkMixin, Base):
    __tablename__ = "invites"

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[Role] = mapped_column(_enum_column(Role), default=Role.MEMBER)
    token: Mapped[str] = mapped_column(String(64), unique=True, default=new_invite_token)
    status: Mapped[InviteStatus] = mapped_column(
        _enum_column(InviteStatus), default=InviteStatus.PENDING
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Project(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, default=None)


class Job(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # Denormalized for one-hop team scoping on /jobs/{job_id} (§1.3).
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[JobKind] = mapped_column(_enum_column(JobKind))
    status: Mapped[JobStatus] = mapped_column(_enum_column(JobStatus), default=JobStatus.QUEUED)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    result_ref: Mapped[str | None] = mapped_column(String(1024), default=None)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Notification(UuidPkMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512))
    body: Mapped[str | None] = mapped_column(Text, default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Activity(UuidPkMixin, Base):
    """Team activity feed (§2.2). Append-only; deleted with its team."""

    __tablename__ = "activities"

    team_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    type: Mapped[str] = mapped_column(String(64), index=True)
    domain: Mapped[str | None] = mapped_column(String(32), default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class DataEvent(UuidPkMixin, Base):
    """ADR-011 data-collection store. Append-only log, internal only — no FKs
    so account deletion never rewrites history (ids are anonymized refs)."""

    __tablename__ = "data_events"

    event_type: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
