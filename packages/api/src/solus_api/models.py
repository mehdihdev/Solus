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

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
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


class SourceType(enum.StrEnum):
    """Connector providers (CLAUDE.md §2.1, API.md §2.5 catalog)."""

    GITHUB = "github"
    GITLAB = "gitlab"
    KICAD = "kicad"
    ONSHAPE = "onshape"
    ROS = "ros"


class SourceStatus(enum.StrEnum):
    PENDING = "pending"  # created, awaiting OAuth/credentials
    CONNECTED = "connected"  # authenticated, ready to sync
    SYNCING = "syncing"  # a sync job is in flight
    ERROR = "error"  # last operation failed (see last_error)
    DISCONNECTED = "disconnected"  # credentials revoked / removed


class SyncTrigger(enum.StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"  # change-detection scheduler
    WEBHOOK = "webhook"  # inbound provider webhook


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


class Source(UuidPkMixin, TimestampMixin, Base):
    """A connected external tool that populates the graph (API.md §2.5).

    Credentials never live here — `secret_ref` points into the secret store
    (AWS Secrets Manager / local encrypted dev backend). `config` holds
    non-secret settings (repo, branch); `cursor` holds the connector's last
    sync state for incremental change detection.
    """

    __tablename__ = "sources"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # Denormalized for one-hop team scoping (mirrors Job; §1.3).
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[SourceType] = mapped_column(_enum_column(SourceType))
    name: Mapped[str] = mapped_column(String(512))
    status: Mapped[SourceStatus] = mapped_column(
        _enum_column(SourceStatus), default=SourceStatus.PENDING
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    secret_ref: Mapped[str | None] = mapped_column(String(512), default=None)
    account_login: Mapped[str | None] = mapped_column(String(255), default=None)
    account_external_id: Mapped[str | None] = mapped_column(String(255), default=None)
    cursor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)


class Entity(UuidPkMixin, TimestampMixin, Base):
    """A typed graph node (ADR-001). Connector-owned when `source_id` is set
    (origin "connector", read-only via the API); `origin` "manual" entities are
    user-editable. `version` powers optimistic concurrency (API.md §2.4)."""

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("source_id", "source_key", name="uq_entity_source_key"),
        Index("ix_entities_project_type", "project_id", "type"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), default=None, index=True
    )
    origin: Mapped[str] = mapped_column(String(16), default="connector")
    source_key: Mapped[str] = mapped_column(String(1024))
    type: Mapped[str] = mapped_column(String(64), index=True)
    domain: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(512))
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Relation(UuidPkMixin, TimestampMixin, Base):
    """A typed graph edge between two entities (ADR-001)."""

    __tablename__ = "relations"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "from_entity_id", "to_entity_id", "type", name="uq_relation_edge"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), default=None, index=True
    )
    from_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    to_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    origin: Mapped[str] = mapped_column(String(16), default="connector")
    type: Mapped[str] = mapped_column(String(64), index=True)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Sync(UuidPkMixin, Base):
    """One sync run of a source (API.md §2.5 sync history). Records the delta
    counts and per-item errors so "why did this user's sync fail?" is
    answerable (CLAUDE.md §6)."""

    __tablename__ = "syncs"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    trigger: Mapped[SyncTrigger] = mapped_column(
        _enum_column(SyncTrigger), default=SyncTrigger.MANUAL
    )
    status: Mapped[JobStatus] = mapped_column(_enum_column(JobStatus), default=JobStatus.QUEUED)
    entities_created: Mapped[int] = mapped_column(Integer, default=0)
    entities_updated: Mapped[int] = mapped_column(Integer, default=0)
    relations_created: Mapped[int] = mapped_column(Integer, default=0)
    relations_deleted: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class OAuthState(Base):
    """Short-lived CSRF state for the connector OAuth handshake (CLAUDE.md §7).

    Created at oauth/start, consumed (and deleted) at the callback. Binds the
    returning `state` to the user, project, and pending source so a forged or
    replayed callback cannot attach a token to someone else's source."""

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    redirect_uri: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConnectorSecret(Base):
    """Encrypted credential storage for the local dev secret store (CLAUDE.md §7).

    Production uses AWS Secrets Manager and never touches this table. `ciphertext`
    is Fernet-encrypted; the key lives in the environment, never in the DB.
    Isolated from `sources` so secret storage can move to a separate store
    without touching graph data."""

    __tablename__ = "connector_secrets"

    ref: Mapped[str] = mapped_column(String(512), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
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
