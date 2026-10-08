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
    CHAR,
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
    # Project-level configuration and documents (the `.solus` node and imported
    # files) — cross-domain by nature, so they carry their own domain (SOLUSDEV-240).
    PROJECT = "project"
    #: SOLUSDEV-246 ST2 (ADR-027 amendment 2026-09-06): the layer describing the
    #: workspace itself — `solus:workspace`, `solus:live_bench`, `solus:widget`.
    #: Never emitted by a connector; excluded from SOL context, checkers and
    #: fingerprinting.
    WORKSPACE = "workspace"


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
    # SOLUSDEV-235 / ADR-035 §5: validates a published extension bundle.
    EXTENSION_REVIEW = "extension_review"
    # SOLUSDEV-246 (STORE ST5): one sourcing request → candidate parts (metered model call).
    SOURCING = "sourcing"


class ExtensionReviewStatus(enum.StrEnum):
    """Lifecycle of one published extension version (docs/schemas/extensions.md §5).
    `pending → checking → approved | rejected` are the only transitions and the
    review job is the only writer. Unpublish is `deleted_at`, never a status."""

    PENDING = "pending"
    CHECKING = "checking"
    APPROVED = "approved"
    REJECTED = "rejected"


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
    LOCAL = "local"  # a working copy on one machine, scanned over the bridge (SOLUSDEV-249)


class SourceStatus(enum.StrEnum):
    PENDING = "pending"  # created, awaiting OAuth/credentials
    CONNECTED = "connected"  # authenticated, ready to sync
    SYNCING = "syncing"  # a sync job is in flight
    ERROR = "error"  # last operation failed (see last_error)
    DISCONNECTED = "disconnected"  # credentials revoked / removed


class ConnectionStatus(enum.StrEnum):
    """Lifecycle of an account-scoped OAuth grant (SOLUSDEV-241 / I1)."""

    PENDING = "pending"  # oauth/start issued, handshake not completed
    CONNECTED = "connected"  # token stored, usable by every bound source
    ERROR = "error"  # the last handshake failed (see last_error)
    REVOKED = "revoked"  # the user revoked it; bound sources were disconnected


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


def _enum_column(enum_cls: type[enum.StrEnum], *, name: str | None = None) -> Enum:
    # native_enum=False + create_constraint=True → VARCHAR with a DB CHECK on the
    # allowed values (portable, and validity enforced in the database, not just app code).
    # `name` overrides the CHECK's name (default: lower-cased class) — needed when one
    # table holds two columns of the same enum, whose constraint names would collide.
    return Enum(
        enum_cls,
        name=name,
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


class WorkspaceLayout(TimestampMixin, Base):
    """Project-shared graph coordinates, separate from entity/connector properties."""

    __tablename__ = "workspace_layouts"
    __table_args__ = (
        CheckConstraint("version >= 0", name="ck_workspace_layouts_version_nonnegative"),
        CheckConstraint(
            "jsonb_typeof(positions) = 'object'", name="ck_workspace_layouts_positions_object"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    positions: Mapped[dict[str, dict[str, float]]] = mapped_column(JSONB, default=dict)


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
    # Staff-set per-key limit override (ADR-023 clarification 2026-10-07, SOLUSDEV-313):
    # merged over plan defaults at read time (`billing/entitlements.py`); explicit null
    # = unlimited, an absent key falls through. Billing events never write or clear it.
    limits_override: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    # Staff comp: grants `comp_plan`'s defaults without a Stripe purchase. NULL
    # `comp_expires_at` with `comp_plan` set = forever; an expired comp is ignored at read.
    comp_plan: Mapped[PlanType | None] = mapped_column(
        _enum_column(PlanType, name="subscription_comp_plan"), default=None
    )
    comp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


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
    # SOLUSDEV-235 / ADR-035 §2: which extension caused a `sol.ask` debit.
    # Attribution ONLY — the debit stays on `user_id`; never used for
    # authorization or budget scoping (docs/schemas/extensions.md §4.9).
    extension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extensions.id", ondelete="SET NULL"), index=True, default=None
    )
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


class CadPurgeRequest(UuidPkMixin, Base):
    """A durable "delete this account's CAD objects" obligation (ADR-038 §1).

    Written in the SAME transaction as the revocation / account deletion / legacy
    source disconnect that creates the duty, so the duty exists if and only if the
    grant is gone. It holds ONLY `sha256("<provider>:<account_ref>")` — never an id,
    token, name or email. `services/cad_purge.py` runs it (inline after commit, then
    the ARQ cron and API startup) until the account's prefix lists empty, twice: a
    second pass after a delay catches a sync that was already in flight."""

    __tablename__ = "cad_purge_requests"

    account_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    passes_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class StripeCancelRequest(UuidPkMixin, Base):
    """A durable "cancel this Stripe customer's subscription" obligation, written in the
    SAME transaction as the account deletion that creates the duty (SOLUSDEV-313).

    It holds ONLY Stripe identifiers — never a user id, email or token. It doubles as the
    deleted-customer tombstone (a late webhook for `stripe_customer_id` is ignored), so it
    is RETAINED after success (`completed_at`), never deleted. `stripe_customer_id` is
    UNIQUE: one row per customer. A later subscription for the same customer re-arms the
    existing row (reset `completed_at`/`attempts`, update the subscription id) instead of
    inserting, which keeps the tombstone lookup a single-row read and makes a concurrent
    double-enqueue a harmless unique violation rather than a duplicate duty."""

    __tablename__ = "stripe_cancel_requests"

    stripe_customer_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), default=None)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(
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
        # SOLUSDEV-246 ST2: the workspace layer's singletons and one widget node
        # per (project, slug) — see widgets/graph_nodes.py; migration d5e6f7a8b9c0.
        Index(
            "uq_graph_entity_workspace_singleton",
            "project_id",
            "kind",
            unique=True,
            postgresql_where=text(
                "kind IN ('solus:workspace', 'solus:live_bench') AND domain = 'workspace' "
                "AND origin = 'system' AND deleted_at IS NULL"
            ),
        ),
        Index(
            "uq_graph_entity_workspace_widget_slug",
            "project_id",
            text("(attrs->>'slug')"),
            unique=True,
            postgresql_where=text(
                "kind = 'solus:widget' AND domain = 'workspace' AND origin = 'system' "
                "AND deleted_at IS NULL"
            ),
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
    # SOLUSDEV-240: an artifact filed into the project `.solus` is a kept document,
    # not a hand-off buffer — exempt from the TTL sweep and one-shot consumption.
    retained: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


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


# ------------------------------------------------------------------ .solus
class SolusSection(enum.StrEnum):
    """The five sections of a project's `.solus` (SOLUSDEV-240)."""

    HARDWARE = "hardware"
    DETAILS = "details"
    ERRORS = "errors"
    DOCS = "docs"
    CODE = "code"


class SolusEntryKind(enum.StrEnum):
    TEXT = "text"  # typed by a person
    ARTIFACT = "artifact"  # an imported file — a `document` graph node
    SOL = "sol"  # filed by SOL via `add_solus_entry`
    CONFIG = "config"  # a Physical Robot's HardwareConfig (ADR-034 amendment 2026-09-06)


class SolusEntry(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One row under a `.solus` section. Configuration, not graph facts: parts live
    in the graph, their configs live here. Every live entry has a selectable graph
    identity (`entity_id`); full text remains here. ARTIFACT entries retain their
    `document` graph identity and the retained `artifacts` row."""

    __tablename__ = "solus_entries"
    __table_args__ = (
        Index("ix_solus_entries_project_section", "project_id", "section"),
        Index(
            "uq_solus_config_subject_live",
            "project_id",
            "configured_entity_id",
            unique=True,
            postgresql_where=text("kind = 'config' AND deleted_at IS NULL"),
        ),
        CheckConstraint(
            "config_version >= 0 AND (kind = 'config' OR "
            "(configured_entity_id IS NULL AND config_version = 0))",
            name="ck_solus_config_subject",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[SolusSection] = mapped_column(_enum_column(SolusSection))
    kind: Mapped[SolusEntryKind] = mapped_column(_enum_column(SolusEntryKind))
    # TEXT/SOL: the note. ARTIFACT: the display name of the file.
    text: Mapped[str | None] = mapped_column(Text, default=None)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"), default=None
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("graph_entity.id", ondelete="SET NULL"), default=None
    )
    author: Mapped[str] = mapped_column(String(16), default="user")  # "user" | "sol"
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # CONFIG only: the HardwareConfig document, validated by its Pydantic model on every
    # write (solus_api.hardware.config) — never free-form JSON (ADR-034 amendment).
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    configured_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("graph_entity.id", ondelete="RESTRICT"), default=None
    )
    config_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class HardwareOperation(UuidPkMixin, Base):
    """A reviewed hardware write and its saved result; never a transient connection result."""

    __tablename__ = "hardware_operations"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", "idempotency_key", name="uq_hardware_operation_scope"
        ),
        CheckConstraint(
            "octet_length(response::text) <= 65536", name="ck_hardware_operation_response_size"
        ),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid)
    operation: Mapped[str] = mapped_column(String(64))
    payload_digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SuggestionStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"  # a sibling for the same subject was accepted


class HardwareSuggestion(UuidPkMixin, TimestampMixin, Base):
    """A link-suggestion engine row (docs/api/hardware.md §3): "this observed device/part
    belongs to that robot", with evidence and confidence. Durable because nothing auto-accepts
    and the user decides later; two plausible robots are two rows."""

    __tablename__ = "hardware_suggestions"
    __table_args__ = (Index("ix_hardware_suggestions_project_status", "project_id", "status"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    subject_ref: Mapped[str] = mapped_column(String(512))  # device ref, part ref or entity:<id>
    subject_kind: Mapped[str] = mapped_column(String(16))  # "device" | "part"
    candidate_robot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_entity.id", ondelete="CASCADE"), index=True
    )
    confidence: Mapped[float] = mapped_column(Float)
    tier: Mapped[str] = mapped_column(String(8))  # high | medium | low
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[SuggestionStatus] = mapped_column(
        _enum_column(SuggestionStatus), default=SuggestionStatus.PENDING
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )


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


class AccountConnection(UuidPkMixin, TimestampMixin, Base):
    """One provider ACCOUNT bound to one Solus user by OAuth (SOLUSDEV-241 / I1).

    The grant is the user's — an Onshape/GitHub authorization is account-wide
    and belongs to the person who clicked "Authorize" — so this row references
    `User`, not a team or a project (the same reasoning `PanelBinding` records:
    a project-scoped row would be torn down by CASCADE the moment one project
    disconnected, taking every other project's credential with it). Projects
    attach to it through `Source.connection_id`; a document may therefore be
    tracked by several projects on one grant, and their fetches share one
    integration cache keyed on the account.

    The credential itself is never here: `secret_ref` names it in the secret
    store (`connection/{id}/{provider}`, refresh token under `/refresh`, hosted
    add-on grants under `/hosted/{server}`). `config` carries the non-secret
    grant shape — the access mode the user chose (`read`/`write`).

    The ref is derivable from the row id, which the API returns. That is only
    safe while NO endpoint accepts a secret ref as input; keep it that way
    (a ref-accepting route would turn every connection id into a lookup key).
    """

    __tablename__ = "account_connections"
    __table_args__ = (
        Index(
            "uq_account_connections_live_identity",
            "user_id",
            "provider",
            "account_external_id",
            unique=True,
            postgresql_where=text("status <> 'revoked' AND account_external_id IS NOT NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[SourceType] = mapped_column(_enum_column(SourceType))
    status: Mapped[ConnectionStatus] = mapped_column(
        _enum_column(ConnectionStatus), default=ConnectionStatus.PENDING
    )
    account_login: Mapped[str | None] = mapped_column(String(255), default=None)
    account_external_id: Mapped[str | None] = mapped_column(String(255), default=None)
    secret_ref: Mapped[str | None] = mapped_column(String(512), default=None)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_error: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)


class Source(UuidPkMixin, TimestampMixin, Base):
    """A connected external tool that populates the graph (API.md §2.5).

    Credentials never live here — `secret_ref` points into the secret store
    (AWS Secrets Manager / local encrypted dev backend). `config` holds
    non-secret settings (repo, branch); `cursor` holds the connector's last
    sync state for incremental change detection.

    SOLUSDEV-241 (I1, the connection model): OAuth binds at ACCOUNT scope. A
    source bound to an `AccountConnection` carries `connection_id` and MIRRORS
    the connection's `secret_ref` (`connection/{id}/{provider}`), so every
    existing credential read path — sync, the sweep, the picker, the SOL tools,
    hosted add-ons — works unchanged. The one rule that changes is OWNERSHIP:
    a connection-owned ref is never deleted by a source disconnect or a project
    teardown (`connections.is_connection_owned`); only revoking the connection
    deletes it. A source without `connection_id` owns its own ref (PAT connects,
    committed-export connectors, pre-I1 rows) exactly as before.
    """

    __tablename__ = "sources"

    revision_base_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), default=None, index=True
    )

    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("account_connections.id", ondelete="SET NULL"), default=None, index=True
    )

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


class SourceRevision(UuidPkMixin, TimestampMixin, Base):
    """An immutable acquired commit graph, shared only within its base source."""

    __tablename__ = "source_revisions"
    __table_args__ = (UniqueConstraint("base_source_id", "commit_id"),)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    base_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    materialized_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), unique=True
    )
    commit_id: Mapped[str] = mapped_column(String(64))
    branch: Mapped[str] = mapped_column(String(255))


class SourceViewSelection(UuidPkMixin, TimestampMixin, Base):
    """A caller's active view plus a replaceable acquisition request."""

    __tablename__ = "source_view_selections"
    __table_args__ = (
        UniqueConstraint("user_id", "base_source_id"),
        CheckConstraint("status IN ('pending', 'ready', 'failed')", name="ck_source_view_status"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    base_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    active_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_revisions.id", ondelete="SET NULL"), default=None, index=True
    )
    active_branch: Mapped[str | None] = mapped_column(String(255), default=None)
    requested_branch: Mapped[str | None] = mapped_column(String(255), default=None)
    request_generation: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(String(512), default=None)


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
    returning `state` to the user, the pending ACCOUNT connection and — when the
    handshake was started from a project — the pending source, so a forged or
    replayed callback cannot attach a token to someone else's account.

    SOLUSDEV-241: the grant binds at account scope, so `connection_id` is the
    row the token lands on and `source_id` is nullable — a Home-started
    handshake has no project and no source. `project_id` is recorded so the
    completion can bind the source without a second lookup."""

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True, nullable=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("account_connections.id", ondelete="CASCADE"), index=True, nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
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


# ------------------------------------------------------------------ extensions
#
# SOLUSDEV-235 / ADR-035 — docs/schemas/extensions.md is the authoritative
# column-for-column description; the migration `solusdev_235_extensions` and
# these classes must match it. The catalog (publishers, extensions, versions,
# assets) is GLOBAL by construction (ADR-033 precedent): no team/project column
# exists, and its absence is the tenancy boundary. Installs, storage and layouts
# are project-scoped (reached only via ProjectCtx); policies are team-scoped
# (TeamCtx). Bundle and asset bytes ride the ArtifactStore PROTOCOL keyed by the
# owning row's uuid — no `artifacts` row (that table is project-scoped).

#: 25 MiB — `MANIFEST_LIMITS.bundle` (docs/contracts/extension-manifest.md).
EXTENSION_BUNDLE_MAX_BYTES = 26_214_400
#: A widget canvas holds at most this many slots (docs/schemas/extensions.md §4.8).
WIDGET_LAYOUT_MAX_SLOTS = 24


class ExtensionPublisher(UuidPkMixin, SoftDeleteMixin, Base):
    """One per publishing account (§4.1). `user_id` is SET NULL on account
    deletion so published extensions survive their author (ADR-024 pattern);
    a publisher with no user can no longer publish but keeps attribution."""

    __tablename__ = "extension_publishers"
    __table_args__ = (
        Index(
            "uq_extension_publishers_user_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    display_name: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Extension(UuidPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """The catalog entry, one per manifest `id` (§4.2). Soft delete = unpublish:
    pinned installs keep working, the entry leaves search. `slug` is unique
    case-insensitively across ALL rows, live or not, so a slug is never
    re-claimable by another publisher (functional index on lower(slug))."""

    __tablename__ = "extensions"
    __table_args__ = (Index("uq_extensions_slug_lower", text("lower(slug)"), unique=True),)

    slug: Mapped[str] = mapped_column(String(64))
    publisher_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extension_publishers.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(60))
    summary: Mapped[str] = mapped_column(String(160))
    # Set ONLY by Solus staff (RequireStaff) — never derived from the publisher.
    verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Cache of live installs — recomputed by the install handlers, never trusted.
    install_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    latest_approved_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "extension_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_extensions_latest_approved_version_id",
        ),
        index=True,
        default=None,
    )


class ExtensionVersion(UuidPkMixin, SoftDeleteMixin, Base):
    """One row per published semver (§4.3). `(extension_id, version)` is unique
    over ALL rows — a withdrawn or rejected number is burned, never reused.
    Bundle bytes live in the ArtifactStore under key = this row's `id`."""

    __tablename__ = "extension_versions"
    __table_args__ = (
        UniqueConstraint("extension_id", "version", name="uq_extension_versions_extension_version"),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="ck_extension_versions_content_hash_hex"
        ),
        CheckConstraint(
            f"bundle_size_bytes > 0 AND bundle_size_bytes <= {EXTENSION_BUNDLE_MAX_BYTES}",
            name="ck_extension_versions_bundle_size_range",
        ),
    )

    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(Text)
    # The decoded extension.toml, ALREADY validated by parse_extension_manifest.
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    bundle_storage: Mapped[ArtifactStorage] = mapped_column(_enum_column(ArtifactStorage))
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    bundle_size_bytes: Mapped[int] = mapped_column(BigInteger)
    review_status: Mapped[ExtensionReviewStatus] = mapped_column(
        _enum_column(ExtensionReviewStatus),
        default=ExtensionReviewStatus.PENDING,
        server_default=ExtensionReviewStatus.PENDING.value,
        index=True,
    )
    review_problems: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ExtensionVersionAsset(UuidPkMixin, Base):
    """A store-facing file the review job extracted from a version (§4.4) —
    overview, privacy policy, section bodies, screenshots, the page icon. Entry
    HTML/JS is never extracted server-side. Derived data: hard-deleted by
    cascade from the version. `storage_key` names the bytes in the ArtifactStore
    and defaults to this row's own id (the §4.4 convention) — resolved at
    construction so the review job knows the key before it stores the bytes."""

    __tablename__ = "extension_version_assets"
    __table_args__ = (
        UniqueConstraint("version_id", "path", name="uq_extension_version_assets_version_path"),
        CheckConstraint("size_bytes >= 0", name="ck_extension_version_assets_size_nonneg"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extension_versions.id", ondelete="CASCADE")
    )
    path: Mapped[str] = mapped_column(String(200))
    storage_key: Mapped[uuid.UUID] = mapped_column(Uuid)
    storage: Mapped[ArtifactStorage] = mapped_column(_enum_column(ArtifactStorage))
    media_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)

    def __init__(self, **fields: Any) -> None:
        row_id = fields.setdefault("id", uuid7())
        fields.setdefault("storage_key", row_id)
        super().__init__(**fields)


class ExtensionInstall(UuidPkMixin, TimestampMixin, Base):
    """A project's pinned install (§4.5). State, not history — hard-deleted on
    uninstall, cascaded on project delete; the history is in `data_events`.
    Both extension and version FKs are RESTRICT: a pin never dangles."""

    __tablename__ = "extension_installs"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "extension_id", name="uq_extension_installs_project_extension"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="RESTRICT"), index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extension_versions.id", ondelete="RESTRICT"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # Keys ⊆ the pinned manifest's settings.fields[].key (validated at the route).
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    # ⊆ the pinned manifest's permissions.scopes / permissions.network.
    granted_scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'")
    )
    granted_network: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'")
    )
    installed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )


class ExtensionStorage(UuidPkMixin, TimestampMixin, Base):
    """The extension's per-project key-value store behind `storage.own` (§4.6).
    Values are opaque to Solus. The 256 KiB per-(project, extension) total and
    the 64 KiB per-value cap are enforced by the write path under a row lock."""

    __tablename__ = "extension_storage"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "extension_id",
            "key",
            name="uq_extension_storage_project_extension_key",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_extension_storage_size_nonneg"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[Any] = mapped_column(JSONB)
    # Byte length of the canonical JSON encoding of `value`.
    size_bytes: Mapped[int] = mapped_column(Integer)


class TeamExtensionPolicy(UuidPkMixin, TimestampMixin, Base):
    """Owner-set defaults and blocks, one per (team, extension) (§4.7). A
    blocked extension cannot also be a default — the CHECK makes that structural."""

    __tablename__ = "team_extension_policies"
    __table_args__ = (
        UniqueConstraint(
            "team_id", "extension_id", name="uq_team_extension_policies_team_extension"
        ),
        CheckConstraint(
            "NOT (blocked AND default_installed)",
            name="ck_team_extension_policies_blocked_not_default",
        ),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="RESTRICT"), index=True
    )
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    default_installed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    default_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    set_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )


class WidgetLayout(UuidPkMixin, TimestampMixin, Base):
    """One user's arrangement of a project's widget canvas (§4.8): an ordered
    list of `{ref, size}` entries, at most WIDGET_LAYOUT_MAX_SLOTS. Personal —
    every read filters on both project_id and user_id = current_user.id."""

    __tablename__ = "widget_layouts"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_widget_layouts_project_user"),
        CheckConstraint(
            "jsonb_typeof(layout) = 'array' AND "
            f"jsonb_array_length(layout) <= {WIDGET_LAYOUT_MAX_SLOTS}",
            name="ck_widget_layouts_layout_bounded",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    layout: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)


class UserExtensionPin(UuidPkMixin, TimestampMixin, Base):
    """SOLUSDEV-246 (STORE ST3) — "Pin for all projects". One row per (user,
    extension): the extension's tab shows in EVERY project this user opens,
    installed there or not. Account state, not project state: a pin carries no
    grants, installs nothing and is never visible to teammates. Reads filter
    `user_id = current_user.id`; the catalog row's soft delete hides the pin.
    Hard-deleted on unpin; the history is in `data_events`."""

    __tablename__ = "user_extension_pins"
    __table_args__ = (
        UniqueConstraint("user_id", "extension_id", name="uq_user_extension_pins_user_extension"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    extension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extensions.id", ondelete="CASCADE"), index=True
    )


class SourcingRequest(UuidPkMixin, TimestampMixin, Base):
    """SOLUSDEV-246 (STORE ST5) — one sourcing request: the requirement (typed
    or CAD-derived), the torque Solus derived, the job that ran the metered
    model call, and its outcome — candidates with trade-offs, exclusions with
    the rule text — plus the selection that entered the graph as PLANNED.
    Project-scoped (`ProjectCtx`); the model's answer is stored as DATA."""

    __tablename__ = "sourcing_requests"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    status: Mapped[JobStatus] = mapped_column(_enum_column(JobStatus), default=JobStatus.QUEUED)
    #: "workspace" | "bom" — which door asked (events + copy), never authorization.
    door: Mapped[str] = mapped_column(String(16), default="bom")
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    torque: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    assembly_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    excluded: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model: Mapped[str | None] = mapped_column(String(128), default=None)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    selected_candidate_id: Mapped[str | None] = mapped_column(String(32), default=None)
    selected_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
