"""SQLAlchemy ORM models — the canonical Solus data contract (SOLUSDEV-72).

UUIDv7 primary keys (§1.4 index locality). Enum columns store values, not names,
via portable VARCHAR (`_enum_column`). Soft-deletable tables carry `deleted_at`;
the intended remove path sets it rather than hard-deleting rows, though wiring the
delete routes to do so is a downstream ticket. The append-only credit ledger,
notifications and the data-collection log are exempt. The cross-domain graph
(entities, relations, embeddings) lives in Postgres + pgvector — no separate graph DB.
"""

import enum
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid6 import uuid7

# Embedding width shared by every pgvector column (OpenAI/Voyage-class models).
# NOTE: pgvector returns embeddings as numpy.ndarray on read, not list — call
# .tolist() before any list-only or truthiness operation on a loaded embedding.
EMBEDDING_DIM = 1536
# HNSW graph parameters (pgvector defaults; ADR-027 as amended 2026-08-07). HNSW has
# no training step, so the index is correct when built empty and needs no REINDEX or
# parameter retune as the corpus grows through ~10^6 vectors.
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize DB-returned datetimes (naive on some drivers) to aware UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def new_invite_token() -> str:
    return secrets.token_urlsafe(32)


class Base(DeclarativeBase):
    pass


# ------------------------------------------------------------------------- enums
class Role(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


ROLE_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}


class SolMode(enum.StrEnum):
    GUIDE = "guide"
    EXPERT = "expert"


class TeamKind(enum.StrEnum):
    PERSONAL = "personal"
    COLLABORATIVE = "collaborative"


class MembershipStatus(enum.StrEnum):
    ACTIVE = "active"
    INVITED = "invited"
    SUSPENDED = "suspended"


class InviteStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class PlanType(enum.StrEnum):
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(enum.StrEnum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    TRIALING = "trialing"


class CreditTxnType(enum.StrEnum):
    PURCHASE = "purchase"
    USAGE = "usage"
    TRIAL_GRANT = "trial_grant"
    # One-time starting credits when a paid plan first activates (ADR-023/024,
    # amended 2026-08-08). Distinct from PURCHASE for ledger auditability.
    PLAN_GRANT = "plan_grant"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class NotificationType(enum.StrEnum):
    # Dotted values match the repo-wide activity/event type convention and the
    # values main's notification flows already persist (SOLUSDEV-72 merge sweep;
    # flagged in the reconciliation report — W0-01 originally used underscores).
    TEAM_INVITE = "team.invite"
    INVITE_ACCEPTED = "invite.accepted"
    PROJECT_CREATED = "project.created"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    # Cancellation lifecycle (SOLUSDEV-102 follow-up): scheduled cancel (access
    # until term end), the cancel being undone, and the term actually ending.
    SUBSCRIPTION_CANCELED = "subscription.canceled"
    SUBSCRIPTION_RESUMED = "subscription.resumed"
    SUBSCRIPTION_ENDED = "subscription.ended"
    PROJECT_SHARED = "project.shared"
    CREDIT_LOW = "credit.low"
    MEMBER_LEFT = "member.left"


class Domain(enum.StrEnum):
    """The domains the graph spans (ADR-027). NOTE: `graph_entity.kind` and
    `graph_edge.relation_type` are free strings, NOT enums — connector kinds
    (code_repo, code_module, design_export, ros_node, ...) and relations
    (contains, part_of, mates_with, connected_to) exceed any closed set."""

    CODE = "code"
    ELECTRICAL = "electrical"
    MECHANICAL = "mechanical"
    SIMULATION = "simulation"
    RUNTIME = "runtime"


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


class ArtifactScope(enum.StrEnum):
    """Who may fetch an artifact's bytes. PROJECT (default) → any project member;
    PRIVATE → the creator only. Extensible (TEAM/PUBLIC later)."""

    PROJECT = "project"
    PRIVATE = "private"


class ArtifactStorage(enum.StrEnum):
    """Where an artifact's bytes physically live (the metadata always lives here)."""

    S3 = "s3"
    LOCAL = "local"
    CLIENT = "client"


class ConfirmationStatus(enum.StrEnum):
    """Lifecycle of one destructive-action approval (SOLUS-ONS-A5). Terminal in
    every state but PENDING — an approval is SINGLE USE, so a decided row can
    never be replayed into a second execution."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    #: Approved, but what the action would DO had changed since the user was
    #: shown it — so nothing ran. Distinct from EXPIRED: time did not run out,
    #: the world moved. Recorded rather than silently re-previewed, because a
    #: user who approved one thing did not consent to another.
    STALE = "stale"


class SourceType(enum.StrEnum):
    """Connector providers (CLAUDE.md §2.1, API.md §2.5 catalog)."""

    GITHUB = "github"
    GITLAB = "gitlab"
    KICAD = "kicad"
    ONSHAPE = "onshape"
    ROS = "ros"
    ALTIUM = "altium"  # committed-export EDA connector (SOLUSDEV-102)


class SourceStatus(enum.StrEnum):
    PENDING = "pending"  # created, awaiting OAuth/credentials
    CONNECTED = "connected"  # authenticated, ready to sync
    SYNCING = "syncing"  # a sync job is in flight
    ERROR = "error"  # last operation failed (see last_error)
    DISCONNECTED = "disconnected"  # credentials revoked / removed


class SyncTrigger(enum.StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"  # change-detection scheduler
    # ponytail: enum value reserved; the inbound webhook receiver + signature auth is a future
    # ticket (ADR-030). Not produced anywhere yet — sync is manual/scheduled only for now.
    WEBHOOK = "webhook"  # inbound provider webhook


class TurnRole(enum.StrEnum):
    """Who authored a conversation turn (SOLUS-SYS-01). `user` = the person,
    `assistant` = SOL's final reply, `tool` = a recorded tool call + its result
    (the plumbing SOL invoked mid-turn). No `system` turn is persisted — system
    instructions are authored by Solus per-request and never stored as data."""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


def _enum_column(enum_cls: type[enum.StrEnum]) -> Enum:
    # native_enum=False + create_constraint=True → VARCHAR with a DB CHECK on the
    # allowed values (portable, and validity enforced in the database, not just app code).
    return Enum(
        enum_cls,
        native_enum=False,
        length=32,
        create_constraint=True,
        values_callable=lambda e: [member.value for member in e],
    )


# ------------------------------------------------------------------------ mixins
class UuidPkMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SoftDeleteMixin:
    # Soft delete: set deleted_at instead of removing the row; live queries filter
    # deleted_at IS NULL (partial unique indexes below rely on this).
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )


def _partial_unique(name: str, *columns: str) -> Index:
    """Unique only among live (not soft-deleted) rows, so a re-add after soft
    delete does not collide."""
    return Index(name, *columns, unique=True, postgresql_where=text("deleted_at IS NULL"))


def _hnsw(name: str, column: str) -> Index:
    """Approximate-nearest-neighbour index for a pgvector column (cosine). HNSW: correct
    when built empty, no REINDEX ceremony as the corpus grows (ADR-027 amendment)."""
    return Index(
        name,
        column,
        postgresql_using="hnsw",
        postgresql_with={"m": HNSW_M, "ef_construction": HNSW_EF_CONSTRUCTION},
        postgresql_ops={column: "vector_cosine_ops"},
    )


# ----------------------------------------------------------------------- tenancy
#: SOLUSDEV-233: single source of truth for the custom-instruction cap —
#: enforced at the column, the API schema, and prompt assembly alike so the
#: three bounds can never drift apart on a prompt-input surface.
SOL_CUSTOM_INSTRUCTION_CAP = 500


class User(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    # Supabase JWT `sub` claim — the bridge between Supabase Auth and the app user.
    supabase_user_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), default=None)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    sol_mode: Mapped[SolMode] = mapped_column(_enum_column(SolMode), default=SolMode.GUIDE)
    # SOLUSDEV-233: user-authored standing preference for SOL answers. Enters the
    # prompt ONLY as a fenced data block (agent/prompt.py) — never instruction text.
    sol_custom_instruction: Mapped[str | None] = mapped_column(
        String(SOL_CUSTOM_INSTRUCTION_CAP), default=None
    )
    # ADR-011: collection is consent-gated; nothing is recorded until the user opts in.
    data_collection_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    # FND-08 first-run state machine: about -> connect -> build -> done.
    # Server-side so resume works across reloads and machines.
    onboarding_step: Mapped[str] = mapped_column(String(16), default="about")


class Team(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str | None] = mapped_column(String(255), default=None)
    # PERSONAL teams are solo-only and exempt from plan limits; COLLABORATIVE are
    # the real teams that count toward limits (ADR-015).
    kind: Mapped[TeamKind] = mapped_column(_enum_column(TeamKind), default=TeamKind.COLLABORATIVE)
    # Interim plan marker, retained until subscriptions drive the API surface.
    plan_status: Mapped[str] = mapped_column(String(32), default="trial")
    # Team preferences (FND-07). Keys are validated by schemas.TeamSettings —
    # never write unvalidated dicts here.
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Membership(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (_partial_unique("uq_membership_team_user", "team_id", "user_id"),)

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(_enum_column(Role), default=Role.MEMBER)
    status: Mapped[MembershipStatus] = mapped_column(
        _enum_column(MembershipStatus), default=MembershipStatus.ACTIVE
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
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


class Project(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "projects"

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    # Archive (FND-04): archived projects keep their graph but leave the default
    # listing. Distinct from soft delete (`deleted_at`) — archive is user-visible
    # and reversible; delete is the remove path. Both kept through the merge.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ProjectMembership(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Per-project access within a team. Seeded with the team's members on project
    creation (that seeding is a downstream ticket)."""

    __tablename__ = "project_memberships"
    __table_args__ = (_partial_unique("uq_project_member_project_user", "project_id", "user_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )


# --------------------------------------------------------------------- billing
class Subscription(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Per-USER billing (ADR-023/032, SOLUSDEV-72 Decisions C-E). Each user has their own
    subscription with their own `limits`; teams is a feature, not a plan tier, and the
    personal team is exempt from limits. Created as a 14-day trial during onboarding.
    The only multi-user case is Enterprise (an owner provisions seats), which the per-user
    model does not preclude."""

    __tablename__ = "subscriptions"
    # One live subscription per user.
    __table_args__ = (_partial_unique("uq_subscription_user", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    plan: Mapped[PlanType] = mapped_column(_enum_column(PlanType))
    status: Mapped[SubscriptionStatus] = mapped_column(
        _enum_column(SubscriptionStatus), default=SubscriptionStatus.TRIALING
    )
    # Plan limits AS DATA (null/absent key = unlimited). Enforcement reads this, never plan names.
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Trial/period end — stored only; charge/downgrade-at-expiry is the future Stripe work.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # When a scheduled cancellation takes effect (Stripe subscription.cancel_at).
    # Set while cancel-at-period-end is pending (drives the billing-page bar),
    # cleared on resume or once the term actually ends (SOLUSDEV-102 follow-up).
    cancel_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Stripe wiring is deferred; a trial has no customer yet (nullable).
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), default=None)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), default=None)
    seat_count: Mapped[int | None] = mapped_column(Integer, default=None)  # Enterprise (future)
    custom_price_per_seat: Mapped[int | None] = mapped_column(Integer, default=None)  # cents
    # `created` timestamp of the last Stripe event applied to this row (SOLUSDEV-83).
    # Out-of-order/replayed webhooks only apply when newer, so state converges.
    stripe_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class CreditBalance(UuidPkMixin, TimestampMixin, Base):
    """Cached per-user balance (no pooling). The ledger is the source of truth.
    `spent_total` is a rolling all-time USAGE total maintained atomically with
    each debit (MO-03) so spend-cap pre-flights read O(1), never ledger scans."""

    __tablename__ = "credit_balance"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    balance: Mapped[int] = mapped_column(Integer, default=0)
    spent_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class CreditLedger(UuidPkMixin, Base):
    """Immutable, append-only credit transaction log — the source of truth.

    The ledger outlives the user (ADR-024: never deleted). On account deletion
    the FK is SET NULL — the financial record is retained but anonymized; the
    deleted user's id is preserved in `attrs` on the forfeiture entry (SOLUSDEV-82).

    `idempotency_key` makes a debit/credit once-only (SOLUSDEV-83): a per-operation
    key (usage call_id, Stripe event id, …). The partial-unique index rejects a
    duplicate write for the same operation, so retries / replays never double-apply.
    It supersedes MO-03's `call_id` column (dropped in the merge migration)."""

    __tablename__ = "credit_ledger"
    __table_args__ = (
        Index(
            "uq_credit_ledger_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    amount: Mapped[int] = mapped_column(Integer)  # signed: + grant/purchase, - usage
    type: Mapped[CreditTxnType] = mapped_column(_enum_column(CreditTxnType))
    balance_after: Mapped[int] = mapped_column(Integer)  # snapshot for auditability
    # Per-operation dedupe key (usage call id / Stripe event id). Null for entries
    # that are not idempotent-guarded (e.g. one-off adjustments).
    idempotency_key: Mapped[str | None] = mapped_column(String(255), default=None)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class DeletedAccount(UuidPkMixin, Base):
    """Tombstone for a deleted identity (SOLUSDEV-82). Account deletion removes
    the user row and the Supabase auth user; this row makes deletion DURABLE —
    a still-valid access token for a deleted `sub` is refused (401) instead of
    silently re-provisioning a zombie account before the token expires."""

    __tablename__ = "deleted_accounts"

    supabase_user_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ProcessedStripeEvent(UuidPkMixin, Base):
    """Dedupe log for Stripe webhook events (SOLUSDEV-83). A `stripe_event_id` is
    recorded once; a duplicate delivery is a no-op. Never deleted (audit)."""

    __tablename__ = "processed_stripe_events"

    stripe_event_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(128))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class DebitReconcileStatus(enum.StrEnum):
    PENDING = "pending"
    RECONCILED = "reconciled"
    FAILED = "failed"


class PendingCreditDebit(UuidPkMixin, TimestampMixin, Base):
    """Dead-letter for a credit debit that could not be applied inline (ADR-024
    W0-03: never fail the user's already-paid result on the accounting write).
    An ARQ worker retries these idempotently until reconciled (SOLUSDEV-83)."""

    __tablename__ = "pending_credit_debits"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    credits: Mapped[int] = mapped_column(Integer)  # positive amount to debit
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[DebitReconcileStatus] = mapped_column(
        _enum_column(DebitReconcileStatus), default=DebitReconcileStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(1024), default=None)


PLAN_LIMITS: dict[PlanType, dict[str, int | None]] = {
    # `byo_paid_tools` (MCP-05): bring-your-own-license MCP tools — 0 = blocked,
    # null = unlimited. Boolean-shaped; enforcement reads it as data like every limit.
    PlanType.BASIC: {
        "max_integrations": 4,
        "max_projects": 3,
        "max_teams": 2,
        "byo_paid_tools": 0,
    },
    PlanType.PRO: {
        "max_integrations": None,
        "max_projects": None,
        "max_teams": None,
        "byo_paid_tools": None,
    },
    PlanType.ENTERPRISE: {},  # custom per deal; set explicitly at creation.
}


def default_limits(plan: PlanType) -> dict[str, int | None]:
    """Plan-default limits for a new subscription (ADR-018/019). null = unlimited."""
    return dict(PLAN_LIMITS[plan])


# ----------------------------------------------------------------------- graph
class GraphEntity(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A node in the cross-domain graph (ADR-027). Observations of one physical part
    collapse to a canonical entity via `canonical_part_id` (the fingerprint's output).
    Connector-owned when `source_id` is set (origin "connector", read-only via the API);
    "manual" entities are user-editable; `version` powers optimistic concurrency
    (API.md §2.4). `external_ref` is the identity linchpin — it equals the connector's
    `EntityOut.source_key` and the fingerprint `SourceRef.external_ref`."""

    __tablename__ = "graph_entity"
    __table_args__ = (
        _hnsw("ix_graph_entity_embedding", "embedding"),
        # Idempotent re-sync: one live row per (source, external id).
        _partial_unique("uq_graph_entity_source_ref", "source_id", "external_ref"),
        Index("ix_graph_entity_project_kind", "project_id", "kind"),
        # FP-02 idempotent canonical-part upsert: one live canonical entity per
        # (project, normalized identity). Raw Index (not _partial_unique): the
        # composite needs the extra canonical_key guard because project_id is
        # always present, so two same-project rows with NULL canonical_key would
        # otherwise both be indexed. Canonical entities are PROJECT-scoped by
        # design — the matcher's uuid5 is project-agnostic and would collide as
        # a PK; it lives in attrs for traceability only (uuid7 PK per ADR-027).
        Index(
            "uq_graph_entity_project_canonical_key",
            "project_id",
            "canonical_key",
            unique=True,
            postgresql_where=text("canonical_key IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(64), index=True)  # free string (see Domain docstring)
    domain: Mapped[Domain] = mapped_column(_enum_column(Domain))
    name: Mapped[str] = mapped_column(String(512))
    canonical_part_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("graph_entity.id", ondelete="SET NULL"), default=None, index=True
    )
    # Provenance: `source_id` is the connector-runtime FK (idempotency + cascade);
    # `source_connector`/`external_ref` are the fingerprint-facing mirror (W0-06).
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), default=None, index=True
    )
    source_connector: Mapped[str | None] = mapped_column(String(64), default=None)
    external_ref: Mapped[str | None] = mapped_column(String(512), default=None)  # id in source tool
    # FP-02 canonical-part identity: the normalized MPN base (matcher part_number,
    # bounded by matching.yaml max_mpn_len=64). Set ONLY on kind="canonical_part"
    # rows written by fingerprint ingestion (origin "fingerprint", source_id NULL).
    canonical_key: Mapped[str | None] = mapped_column(String(64), default=None)
    origin: Mapped[str] = mapped_column(String(16), default="connector")
    version: Mapped[int] = mapped_column(Integer, default=1)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # The multimodal fingerprint channel (W0-06): part numbers, schematic symbols,
    # datasheet refs, CAD model ids — kept separate from `attrs` so the matcher
    # queries it directly. Mirrors the connector's `EntityOut.modality_hints`.
    modality_hints: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Nullable: entities are often created by a connector before an embedding exists.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), default=None)


class GraphEdge(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A typed relation between two entities. `same_as` is the cross-domain identity
    link. `relation_type` is a free string (see Domain docstring). Connector-owned
    when `source_id` is set."""

    __tablename__ = "graph_edge"
    __table_args__ = (
        # Idempotent re-sync: one live edge per (source, src, dst, type).
        _partial_unique(
            "uq_graph_edge_source_edge", "source_id", "src_id", "dst_id", "relation_type"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), default=None, index=True
    )
    src_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_entity.id", ondelete="CASCADE"), index=True
    )
    dst_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_entity.id", ondelete="CASCADE"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(64))  # free string
    domain_pair: Mapped[str] = mapped_column(String(64))  # e.g. "code<->electrical"
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    origin: Mapped[str] = mapped_column(String(16), default="connector")
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ErrorSolution(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """RAG source for SOL: an error seen in a project and (optionally) its fix."""

    __tablename__ = "error_solution"
    __table_args__ = (_hnsw("ix_error_solution_embedding", "embedding"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    error_text: Mapped[str] = mapped_column(Text)
    solution_text: Mapped[str | None] = mapped_column(Text, default=None)
    domain: Mapped[Domain] = mapped_column(_enum_column(Domain))
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), default=None)


class ToolConfirmation(UuidPkMixin, TimestampMixin, Base):
    """A destructive tool call parked awaiting the user's explicit approval
    (SOLUS-ONS-A5, CLAUDE.md §7 "no silent execution").

    A SOL turn is a one-shot SSE stream and cannot block for a click, so a gated
    call records what it wants to do here, the turn ends, and the user decides
    through `POST .../sol/confirmations/{id}`.

    **`args` is the load-bearing column.** It holds the exact arguments the user
    was shown, and they are what executes — the decide endpoint accepts a
    decision and nothing else. Letting a client re-supply arguments at approval
    time would mean approving "change width" and executing "change everything".
    """

    __tablename__ = "tool_confirmations"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    #: Only this user may decide — a teammate never saw the proposed action.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), default=None, index=True
    )
    tool: Mapped[str] = mapped_column(String(128))
    args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: The concrete action in words. A user cannot meaningfully approve an id.
    summary: Mapped[str] = mapped_column(String(2048))
    #: The DIFF the user is approving: `[{"label", "before", "after"}, ...]`.
    #: Generic across every tool kind — a CAD edit, a firmware flash and a robot
    #: command all render the same way — and computed at PARK time, so what is
    #: displayed is derived from the same stored args that will execute. Empty
    #: when a tool offers no preview; the summary alone is then the consent.
    preview: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[ConfirmationStatus] = mapped_column(
        _enum_column(ConfirmationStatus), default=ConfirmationStatus.PENDING
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


# --------------------------------------------------------------------- artifacts
class Artifact(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Registry row for a large/binary tool output (image, point cloud, screenshot).
    The bytes live in S3/on a client; only this metadata lives in Postgres, so the
    reasoning path carries a lightweight `ArtifactRef`, never the bytes (W0-04)."""

    __tablename__ = "artifacts"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[ArtifactScope] = mapped_column(
        _enum_column(ArtifactScope), default=ArtifactScope.PROJECT
    )
    uri: Mapped[str] = mapped_column(String(2048))
    media_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(Integer, default=None)
    storage_location: Mapped[ArtifactStorage] = mapped_column(_enum_column(ArtifactStorage))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    source_tool: Mapped[str | None] = mapped_column(String(64), default=None)  # producing tool
    # Which W0-04 ToolCall this upload fulfils — the anti-forgery anchor of the
    # bridge acquirer's §4.3 consumption check (SOLUSDEV-100 T4c). Nullable:
    # pre-existing/non-tool-fulfilling artifacts have none.
    tool_call_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)


def artifact_is_accessible(
    *,
    scope: ArtifactScope,
    created_by: uuid.UUID | None,
    requester_id: uuid.UUID,
    requester_has_project_access: bool,
) -> bool:
    """Pure access rule for fetching an artifact's bytes (W0-04). PRIVATE → only the
    creator; PROJECT (and future TEAM/PUBLIC) → anyone with project access. The caller
    computes `requester_has_project_access` via the same project-scoping query as every
    other read, so this stays a pure decision (no DB, no user prompt)."""
    if scope == ArtifactScope.PRIVATE:
        return requester_id == created_by
    return requester_has_project_access


# ------------------------------------------------------------------ operational
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
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Notification(UuidPkMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[NotificationType] = mapped_column(_enum_column(NotificationType))
    title: Mapped[str] = mapped_column(String(512))
    body: Mapped[str | None] = mapped_column(Text, default=None)
    action_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
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
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
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


# The connector graph writes to graph_entity/graph_edge (unified in Decision A,
# SOLUSDEV-72). The former standalone `entities`/`relations` tables were removed —
# their operational columns (source_id/external_ref/origin/version) now live on
# GraphEntity/GraphEdge above.


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


class PanelBinding(UuidPkMixin, TimestampMixin, Base):
    """An Onshape panel linked to a Solus user (SOLUS-A7-01).

    THE PANEL'S CREDENTIAL, and the reason `{$userId}` is not one. Onshape hands
    the iframe a `{$userId}` query param, but that is an unsigned identifier
    from a third party — and Onshape user ids are visible to anyone sharing a
    document, so treating a match as access would let a collaborator read
    someone's Solus graph. The panel therefore holds a SECRET obtained through
    an explicit pairing the user approved while authenticated in Solus.

    `onshape_user_id` is a LABEL, never a lookup key: it exists so the
    revocation UI can say which panel this is, and it is validated to Onshape's
    id charset so it cannot carry markup onto that screen.

    References `User`, not `Source`: a Source is project-scoped and its CASCADE
    would silently destroy the pairing when someone disconnects and reconnects
    Onshape. Authorization is never carried here — it is re-derived per request
    from live membership, so this row is identity only.
    """

    __tablename__ = "panel_bindings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    #: sha256 hex of the token. HASHED AT REST: a 90-day silent full-user
    #: credential must not be readable from a DB dump or a stray repr. sha256
    #: rather than a KDF because the secret is 256 bits of entropy — a KDF only
    #: slows guesses of LOW-entropy secrets and would destroy indexed lookup.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    onshape_user_id: Mapped[str | None] = mapped_column(String(64), default=None)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PanelPairing(Base):
    """One in-flight panel pairing — an OAuth-device-flow-shaped handshake.

    The panel is unauthenticated and the Solus app is authenticated, in two
    different browser contexts, so the user carries a short code between them.

    `OAuthState` cannot be reused for this despite the similar shape: its
    `source_id` is a NOT NULL FK to `sources.id`, it has no approval column, and
    it has no attempt counter. Its row models a redirect round-trip with a
    10-minute life; a binding outlives the handshake indefinitely. One table
    doing both jobs would be half NULL columns and a CASCADE that is an outright
    correctness bug for the binding case.
    """

    __tablename__ = "panel_pairings"

    #: sha256 of the device code — the panel's bearer while polling. The
    #: plaintext is never stored, not even for the 10-minute window: the panel
    #: token is minted at REDEMPTION, not at approval.
    device_code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: The short code a human reads off the panel and types into Solus. Low
    #: entropy by necessity, which is why redeeming it requires an already
    #: authenticated caller.
    user_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    onshape_user_id: Mapped[str | None] = mapped_column(String(64), default=None)
    approved_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), default=None
    )
    #: Durable across ECS tasks, unlike the in-process rate limiter — which
    #: cannot see the client IP behind the ALB and so shares one bucket across
    #: every unauthenticated caller.
    poll_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
    #: PKCE (RFC 7636) verifier for providers that require it — SOLUSDEV-168.
    #: It has to survive authorize→callback, which are two separate requests
    #: possibly on different workers, so it cannot live on a coroutine (which is
    #: exactly why the MCP SDK's own OAuth client is unusable here). NULL for
    #: every connector that predates PKCE. Deleted with the row on every
    #: consumption path, so its lifetime is the handshake's.
    code_verifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
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
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ToolDoc(UuidPkMixin, Base):
    """Vendor API knowledge SOL consults to build a valid tool call (ADR-033).

    THE FIRST GLOBAL CONTENT-BEARING TABLE. Every other table storing text is
    project-scoped by `ForeignKey("projects.id", ondelete="CASCADE")`, and that
    FK is what makes cross-tenant leakage structurally impossible. This one has
    no such anchor, so its containment comes from three properties instead:

    1. **No tenant column and no FK.** There is nowhere to put a project, team
       or user reference — absence of the column IS the enforcement.
    2. **Typed columns only.** `parameters` holds structured vendor parameter
       specs with a known shape; there is deliberately no open `payload`/`extra`
       a request handler could stuff customer text (or a prompt) into.
    3. **No runtime write path.** Written only by the ingestion job in
       `tool_docs.py`, over VENDOR documentation — never by a sync, a tool call,
       or anything holding a `SyncContext` or a `GraphEntity`.

    Contrast `DataEvent`: also FK-free, but tenant-attributed and carrying an
    open payload. "No FK" alone is not containment.
    """

    __tablename__ = "tool_docs"
    __table_args__ = (
        UniqueConstraint("tool", "version", "symbol", name="uq_tool_docs_identity"),
        Index("ix_tool_docs_lookup", "tool", "version", "symbol"),
    )

    #: The vendor tool this documents: "onshape", "fusion", …
    tool: Mapped[str] = mapped_column(String(32))
    #: Vendor API version the entry was derived from, so a stale entry is
    #: identifiable rather than silently wrong.
    version: Mapped[str] = mapped_column(String(32))
    #: What is documented — a feature type, an endpoint, a FeatureScript symbol.
    symbol: Mapped[str] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(String(1024))
    #: Structured parameter specs: `[{id, name, kind, quantity_type?, options?}]`.
    parameters: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    #: Where it came from. An entry nobody can trace is one nobody can re-derive.
    source_url: Mapped[str] = mapped_column(String(512))
    #: 0-1. Machine-readable sources score high; anything inferred scores lower.
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    #: How it was acquired ("openapi", "featurespecs", …) — MCP-04 §2.1 wants
    #: identity content-derived and provenance explicit.
    acquisition_method: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    #: Reserved so adding vectors later is a backfill rather than a migration.
    #: Stays NULL: `embed()` does not exist yet (docs/api/gateway-embeddings.md
    #: is a deferred MO-01 proposal), and nothing may pretend otherwise.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), default=None)


# --------------------------------------------------------------------- SOL chat
class Conversation(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A SOL chat session (SOLUS-SYS-01). PROJECT-scoped (the tenant boundary) and
    OWNED by its creator: only `created_by` reaches it, so one teammate's thread never
    leaks to another within the same project. `team_id` is denormalized for one-hop
    team scoping (mirrors Source/Job)."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_project_owner", "project_id", "created_by"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    title: Mapped[str | None] = mapped_column(String(512), default=None)


class ConversationTurn(UuidPkMixin, TimestampMixin, Base):
    """One turn in a conversation (SOLUS-SYS-01). Append-only; deleted with its
    conversation via CASCADE. `content` is the message text (or a tool summary);
    `attrs` carries the structured detail — tool call/result envelope, model
    metadata, the sol_mode the turn ran under. `project_id` is denormalized so a
    turn read is team-scopable without joining through the conversation."""

    __tablename__ = "conversation_turns"
    __table_args__ = (
        Index("ix_conversation_turns_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[TurnRole] = mapped_column(_enum_column(TurnRole))
    content: Mapped[str] = mapped_column(Text, default="")
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
