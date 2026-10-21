"""Request schemas (Pydantic v2). Unknown fields are rejected on every
mutating endpoint (CLAUDE.md §7 input handling)."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from solus_api.billing.entitlements import effective_limits, is_local_trial_expired
from solus_api.billing.plans import CHECKOUTABLE_PLANS
from solus_api.connectors.eda import MAX_EXPORT_BYTES
from solus_api.connectors.quota import QuotaState
from solus_api.models import (
    SOL_CUSTOM_INSTRUCTION_CAP,
    AccountConnection,
    Activity,
    Artifact,
    ArtifactScope,
    ArtifactStorage,
    ConnectionStatus,
    CreditTxnType,
    Domain,
    GraphEdge,
    GraphEntity,
    Invite,
    InviteStatus,
    Job,
    JobKind,
    JobStatus,
    Membership,
    MembershipStatus,
    Notification,
    NotificationType,
    PlanType,
    Project,
    Role,
    SolMode,
    Source,
    SourceType,
    Subscription,
    SubscriptionStatus,
    Sync,
    Team,
    TeamInstallation,
    TeamKind,
    User,
    ensure_utc,
)
from solus_api.orchestration.enums import Complexity, InteractionContext, RouteType
from solus_api.services.github_identity import GITHUB_LOGIN_PATTERN


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttachmentIn(StrictModel):
    """A measurable attachment fact for classify/completion requests (MO-04):
    what kind of artifact and how many tokens it contributes."""

    kind: str = Field(min_length=1, max_length=32)
    # Bounded well above any context window — cheap insurance against absurd
    # hints; the gateway/billing never trust this number for money anyway.
    tokens: int = Field(default=0, ge=0, le=10_000_000)


class ClassifyRequest(StrictModel):
    """MO-04 pre-flight preview input. `complexity`/`type` let the override UI
    preview a user's pick; extra fields (e.g. a raw model name) are rejected."""

    query: str = Field(max_length=1_000_000)
    context: InteractionContext | None = None
    complexity: Complexity | None = None
    type: RouteType | None = None
    attachments: list[AttachmentIn] = Field(default_factory=list, max_length=64)
    #: S1-W3: preview the composer's "Think harder" — one tier up, like the runtime.
    think_harder: bool = False


def _not_blank(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


class UserUpdate(StrictModel):
    name: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=2048)


class SettingsUpdate(StrictModel):
    sol_mode: Literal["guide", "expert"] | None = None
    # SOLUSDEV-233: standing preference note for SOL. Absent = unchanged;
    # explicit null = clear. Single-source cap (models.SOL_CUSTOM_INSTRUCTION_CAP).
    sol_custom_instruction: str | None = Field(default=None, max_length=SOL_CUSTOM_INSTRUCTION_CAP)
    # ADR-011: data collection is consent-gated; this is the opt-in/out switch.
    data_collection_consent: bool | None = None
    # FND-08 onboarding state machine; persisted so resume works anywhere.
    onboarding_step: Literal["about", "connect", "build", "done"] | None = None


class TeamSettings(StrictModel):
    """Validated team preferences (FND-07). Every key has a default so reads
    merge cleanly for teams created before a key existed."""

    # Whether project.created fans out to the rest of the team (FND-04/05).
    notify_project_created: bool = True


TEAM_SETTINGS_DEFAULTS: dict[str, Any] = TeamSettings().model_dump()


class TeamCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)

    _name_not_blank = field_validator("name")(_not_blank)


class TeamUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    settings: TeamSettings | None = None

    _name_not_blank = field_validator("name")(_not_blank)


class MemberRoleUpdate(StrictModel):
    role: Literal["owner", "admin", "member", "viewer"]


_MAX_GITHUB_ID = 2**63 - 1


class InviteCreate(StrictModel):
    """Exactly one target: an `email`, or a GitHub org member (`github_user_id` + display-only
    `github_login`, docs/api/github-orgs.md)."""

    email: EmailStr | None = None
    github_user_id: Annotated[int, Field(strict=True, gt=0, le=_MAX_GITHUB_ID)] | None = None
    github_login: str | None = None
    # Owner is granted only via the members route, by an existing owner.
    role: Literal["admin", "member", "viewer"] = "member"

    @field_validator("github_login")
    @classmethod
    def _login_shape(cls, value: str | None) -> str | None:
        if value is not None and GITHUB_LOGIN_PATTERN.fullmatch(value) is None:
            raise ValueError("not a valid GitHub login")
        return value

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "InviteCreate":
        has_github = self.github_user_id is not None or self.github_login is not None
        if has_github and (self.github_user_id is None or self.github_login is None):
            raise ValueError("github_user_id and github_login must be sent together")
        if (self.email is not None) == has_github:
            raise ValueError("send exactly one of email or github_user_id + github_login")
        return self


class ProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)

    _name_not_blank = field_validator("name")(_not_blank)


class ProjectUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)

    _name_not_blank = field_validator("name")(_not_blank)


class SolusEntryIn(StrictModel):
    """POST /solus/{section}/entries (docs/api/solus.md): typed text, or an
    already-uploaded artifact to file as a document node."""

    kind: Literal["text", "artifact"]
    text: str | None = Field(default=None, max_length=4000)
    artifact_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def _shape(self) -> "SolusEntryIn":
        if self.kind == "text":
            if self.text is None or not self.text.strip():
                raise ValueError("text is required for a text entry")
            if self.artifact_id is not None or self.name is not None:
                raise ValueError("artifact_id/name are not allowed on a text entry")
        else:
            if self.artifact_id is None or self.name is None or not self.name.strip():
                raise ValueError("artifact_id and name are required for an artifact entry")
            if self.text is not None:
                raise ValueError("text is not allowed on an artifact entry")
        return self


class SolusEntryPatch(StrictModel):
    text: str = Field(min_length=1, max_length=4000)


SourceTypeLiteral = Literal["github", "gitlab", "kicad", "onshape", "ros", "altium", "local"]


#: Bulk config keys (committed-export scaffold content, up to 8MB of untrusted
#: netlist text) are stored but never echoed by the API — a source list must not
#: round-trip megabytes of ingested content (§7 — bound message sizes).
_BULK_CONFIG_KEYS = frozenset({"export", "board"})


def _bound_bulk_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Reject an over-cap design input AT THE BOUNDARY (SOLUSDEV-252).

    The committed-export family enforces `MAX_EXPORT_BYTES` when it parses, but
    that is after the value has been accepted, parsed by Pydantic and written
    to the row — a 200 MB `board` would be stored and only refused at the next
    sync. Bound the known bulk keys here so oversized untrusted content never
    reaches the database (§7 input validation)."""
    if config is None:
        return config
    for key in sorted(_BULK_CONFIG_KEYS):
        value = config.get(key)
        if (
            isinstance(value, str)
            and len(value.encode("utf-8", "surrogatepass")) > MAX_EXPORT_BYTES
        ):
            raise ValueError(f"config['{key}'] exceeds the {MAX_EXPORT_BYTES}-byte limit")
    return config


class SourceCreate(StrictModel):
    """Connect a source directly (type + config; non-OAuth / token providers).
    OAuth providers use the integrations oauth/start flow instead."""

    type: SourceTypeLiteral
    name: str = Field(min_length=1, max_length=512)
    config: dict[str, Any] = Field(default_factory=dict)
    # Optional pre-supplied token (e.g. a PAT). Goes straight to the secret
    # store, is validated, and is never echoed back (CLAUDE.md §7).
    token: str | None = Field(default=None, max_length=4096)
    # SOLUSDEV-241: attach the project to an ACCOUNT the caller already
    # authorized (Home), instead of running a second OAuth. Exclusive with
    # `token`; must be the caller's own connection for this provider.
    connection_id: str | None = Field(default=None, max_length=64)
    # SOLUSDEV-216: bind to the team's GitHub App installation instead of a personal
    # token or connection (github only; exclusive with `token` and `connection_id`).
    installation: bool = False

    _name_not_blank = field_validator("name")(_not_blank)
    _config_bounded = field_validator("config")(_bound_bulk_config)


class LocalFolderLink(StrictModel):
    """Link THIS machine's working copy to the project (SOLUSDEV-249). The path
    never travels: the companion scans its own workspace. `machine_id` is the
    companion instance id (`~/.solus/companion_id`)."""

    machine_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    machine_name: str = Field(min_length=1, max_length=255)
    folder_name: str = Field(min_length=1, max_length=255)

    _machine_name_not_blank = field_validator("machine_name")(_not_blank)
    _folder_name_not_blank = field_validator("folder_name")(_not_blank)


class LocalFolderOpen(StrictModel):
    """Open one detected project in a tool on the source's machine (SOLUSDEV-249)."""

    entity_id: uuid.UUID
    tool: Literal["kicad", "altium", "vscode", "system"]


class SourceUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=512)
    config: dict[str, Any] | None = None

    _name_not_blank = field_validator("name")(_not_blank)
    _config_bounded = field_validator("config")(_bound_bulk_config)


class SourceDisconnect(StrictModel):
    retain_entities: bool = False


class DocumentAdd(StrictModel):
    """Track one more of the account's documents in this project (SOLUSDEV-241).
    The id is validated by the CONNECTOR's own rule before it can reach a
    request path — the schema only bounds it."""

    id: str = Field(min_length=1, max_length=255)


class ConfirmationDecision(StrictModel):
    """Approve or reject one parked destructive action (SOLUS-ONS-A5).

    A decision and NOTHING ELSE. `StrictModel` forbids extra fields, so a body
    carrying its own `args` is a 422 rather than a merge — the arguments that
    execute are the stored ones the user was shown. That is the whole security
    property of the round-trip.
    """

    decision: Literal["approve", "reject"]


class OAuthStart(StrictModel):
    # SOLUSDEV-241: optional. Absent, the handshake binds an ACCOUNT only
    # (Home); present, it also creates/reuses this project's source and binds
    # it on completion (the Workspace wizard, unchanged).
    project_id: str | None = Field(default=None, min_length=1, max_length=64)
    # Optional repo to pre-select; the user can also pick after connecting.
    repo: str | None = Field(default=None, max_length=512)
    name: str | None = Field(default=None, max_length=512)
    # Desktop loopback flow supplies its 127.0.0.1 callback here; web defaults
    # to the API's own callback. Validated against an allowlist server-side.
    redirect_uri: str | None = Field(default=None, max_length=2048)
    # Which access mode to request, for connectors that offer a choice
    # (SOLUS-ONS-A2). Omitted means the connector's declared DEFAULT, which is
    # always the narrowest — an absent choice can only ever under-grant.
    access: str | None = Field(default=None, max_length=32)


class OAuthExchange(StrictModel):
    """Desktop loopback flow: the app captured the code and posts it back with
    the state from oauth/start, so the server can exchange it for a token."""

    state: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=2048)


# --- Response serializers (snake_case dicts inside the §1.4 envelope) ---


def _account_label(account: Source | AccountConnection) -> str | None:
    provider = account.type if isinstance(account, Source) else account.provider
    if provider is SourceType.ONSHAPE and (
        not account.account_login or account.account_login == account.account_external_id
    ):
        return "Onshape account"
    return account.account_login


def _local_remote(source: Source) -> dict[str, str] | None:
    """SOLUSDEV-317: a local folder's git origin as the sync normalised it
    (`owner/name` + host kind) so Home can mark it as a clone of the project's
    GitHub/GitLab repo. Only these two cursor values leave the server — never
    the raw remote URL, the digest or the detected list."""
    if source.type is not SourceType.LOCAL:
        return None
    cursor = source.cursor or {}
    repo, host = cursor.get("remote"), cursor.get("host")
    if not isinstance(repo, str) or not repo or not isinstance(host, str) or not host:
        return None
    return {"repo": repo, "host": host}


def serialize_source(
    source: Source,
    *,
    entity_count: int | None = None,
    quota: "QuotaState | None" = None,
) -> dict[str, Any]:
    """Source view for the API — secrets (secret_ref/token) are never included."""
    name = source.name
    if (
        source.type is SourceType.ONSHAPE
        and source.account_external_id
        and name == f"Onshape · {source.account_external_id}"
    ):
        name = _account_label(source) or "Onshape account"
    data: dict[str, Any] = {
        "id": source.id,
        "project_id": source.project_id,
        "type": source.type.value,
        "name": name,
        "status": source.status.value,
        # Defensive: drop transient/underscore-prefixed and bulk config keys.
        "config": {
            k: v
            for k, v in source.config.items()
            if not k.startswith("_") and k not in _BULK_CONFIG_KEYS
        },
        "account_login": _account_label(source),
        # SOLUSDEV-241: the account grant this source rides, when it rides one.
        "connection_id": source.connection_id,
        "last_synced_at": source.last_synced_at,
        "last_error": source.last_error,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }
    if entity_count is not None:
        data["entity_count"] = entity_count
    remote = _local_remote(source)
    if remote is not None:
        data["remote"] = remote
    if quota is not None:
        # SOLUSDEV-167 acceptance #5: the degraded state, visible BEFORE the wall.
        #
        # Read from the meter, never inferred from `last_error` — that is only
        # written when a SYNC fails, so a team pushed into the degraded band by
        # SOL tool traffic and picker opens alone would have reported healthy.
        #
        # `estimated` is always true and the UI must say so: we count only our
        # own calls from whenever the counter started, so this is a floor on our
        # spend and never a remaining balance (ADR-019 as amended).
        # ADR-038 §4 adds pool, distribution, by_label and rate_limit_remaining.
        data["quota"] = quota.readout()
    return data


def serialize_connection(
    connection: AccountConnection,
    projects: list[dict[str, Any]] | None = None,
    *,
    health: str = "healthy",
    quota: "QuotaState | None" = None,
) -> dict[str, Any]:
    """Account-connection view (SOLUSDEV-241). No secret material, no secret
    ref — the grant's existence and identity, never its credential.

    SOLUSDEV-244 (H4): `health` is the derived state Home badges
    (`healthy` / `token_expired` / `degraded`, `services/connection_health.py`);
    `quota` is the meter's ESTIMATED position for a metered provider, the same
    block `serialize_source` carries, and is omitted when unknowable."""
    config = connection.config if isinstance(connection.config, dict) else {}
    data: dict[str, Any] = {
        "id": connection.id,
        "provider": connection.provider.value,
        "status": connection.status.value,
        "account_login": _account_label(connection),
        "access": config.get("access"),
        # SOLUSDEV-242 (H2): Home offers Re-authorize when the last handshake failed.
        "needs_reauth": "token_error" if connection.status is ConnectionStatus.ERROR else None,
        "last_error": connection.last_error,
        "health": health,
        "projects": [{"project_id": p["project_id"], "name": p["name"]} for p in (projects or [])],
        "created_at": connection.created_at,
        "updated_at": connection.updated_at,
    }
    if quota is not None:
        # ADR-038 §4 adds pool, distribution, by_label and rate_limit_remaining.
        data["quota"] = quota.readout()
    return data


class AdoptRequest(StrictModel):
    """SOLUSDEV-242 (H2): the explicit, confirmed move of NAMED legacy sources
    to the caller's proved account. `confirm_access` is the caller accepting a
    grant wider than a source ever recorded (shown in the confirmation)."""

    source_ids: list[UUID] = Field(min_length=1, max_length=50)
    confirm_access: bool = False


def serialize_legacy_connection(
    provider: str,
    account_login: str | None,
    sources: list[Source],
    names: dict[Any, str],
    claimable_connection_id: UUID | None,
) -> dict[str, Any]:
    """A project-scoped grant not yet claimed to account scope (SOLUSDEV-242 / H2):
    what Home lists as "sign in once to move it". Identity and where it is used;
    never a secret, never a ref."""
    return {
        "provider": provider,
        "account_login": account_login,
        "projects": [
            {"project_id": s.project_id, "name": names.get(s.project_id, "")} for s in sources
        ],
        "source_ids": [s.id for s in sources],
        # The caller's CONNECTED grant that proves this account, when they hold
        # one: Home then offers the confirmed move instead of a sign-in.
        "claimable_connection_id": claimable_connection_id,
    }


def serialize_entity(entity: GraphEntity) -> dict[str, Any]:
    # Connector-facing view: stable public keys (type/source_key/properties) sourced
    # from the unified graph columns (kind/external_ref/attrs). See Decision A.
    return {
        "id": entity.id,
        "project_id": entity.project_id,
        "source_id": entity.source_id,
        "origin": entity.origin,
        "source_key": entity.external_ref,
        "type": entity.kind,
        "domain": entity.domain.value,
        "name": entity.name,
        "properties": entity.attrs,
        "version": entity.version,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def serialize_relation(relation: GraphEdge) -> dict[str, Any]:
    return {
        "id": relation.id,
        "project_id": relation.project_id,
        "source_id": relation.source_id,
        "origin": relation.origin,
        "type": relation.relation_type,
        "from_entity_id": relation.src_id,
        "to_entity_id": relation.dst_id,
        "properties": relation.attrs,
        "created_at": relation.created_at,
    }


def serialize_sync(sync: Sync) -> dict[str, Any]:
    return {
        "id": sync.id,
        "source_id": sync.source_id,
        "status": sync.status.value,
        "trigger": sync.trigger.value,
        "entities_created": sync.entities_created,
        "entities_updated": sync.entities_updated,
        "relations_created": sync.relations_created,
        "relations_deleted": sync.relations_deleted,
        "errors": sync.errors,
        "started_at": sync.started_at,
        "finished_at": sync.finished_at,
        "created_at": sync.created_at,
    }


def serialize_team_summary(
    team: Team, role: Role, trial_ends_at: datetime | None
) -> dict[str, Any]:
    """`trial_ends_at` is the REQUESTING user's own trial end (SOLUSDEV-236) — the
    caller passes it from their own subscription, never another member's."""
    return {
        "team_id": team.id,
        "name": team.name,
        "role": role.value,
        "is_personal": team.kind == TeamKind.PERSONAL,
        "plan_status": team.plan_status,
        "trial_ends_at": trial_ends_at,
    }


def serialize_user(user: User, teams: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.display_name,
        "avatar_url": user.avatar_url,
        "created_at": user.created_at,
        "teams": teams,
    }


def serialize_team_detail(team: Team, role: Role, member_count: int) -> dict[str, Any]:
    return {
        "id": team.id,
        "name": team.name,
        "is_personal": team.kind == TeamKind.PERSONAL,
        "plan_status": team.plan_status,
        # Defaults merged so pre-column teams read complete settings.
        "settings": {**TEAM_SETTINGS_DEFAULTS, **team.settings},
        "created_at": team.created_at,
        "member_count": member_count,
        "role": role.value,
    }


def serialize_member(membership: Membership, user: User) -> dict[str, Any]:
    return {
        "user_id": user.id,
        "email": user.email,
        "name": user.display_name,
        "role": membership.role.value,
        "joined_at": membership.created_at,
    }


def serialize_invite(invite: Invite, *, include_token: bool = False) -> dict[str, Any]:
    data = {
        "id": invite.id,
        "team_id": invite.team_id,
        "email": invite.email,
        "github_user_id": invite.github_user_id,
        "github_login": invite.github_login,
        "role": invite.role.value,
        "status": invite.status.value,
        "created_at": invite.created_at,
        "expires_at": invite.expires_at,
    }
    if include_token:
        # Secret shown once at creation (§2.1 pattern) — never on listings.
        data["token"] = invite.token
    return data


class InstallationLinkedBy(BaseModel):
    user_id: UUID
    name: str


class TeamInstallationRead(BaseModel):
    """A team's linked GitHub App installation (docs/api/github-orgs.md §2). Never
    carries a token, key or JWT."""

    id: UUID
    provider: str
    account_login: str
    account_type: str
    account_avatar_url: str | None
    repository_selection: str
    status: str
    linked_by: InstallationLinkedBy | None
    linked_at: datetime
    html_url: str
    manage_url: str


def _installation_manage_url(row: TeamInstallation) -> str:
    base = row.web_base_url.rstrip("/")
    if row.account_type == "Organization":
        return (
            f"{base}/organizations/{row.account_login}"
            f"/settings/installations/{row.external_installation_id}"
        )
    return f"{base}/settings/installations/{row.external_installation_id}"


def serialize_team_installation(
    row: TeamInstallation, linked_by_user: User | None
) -> TeamInstallationRead:
    linked_by = (
        InstallationLinkedBy(
            user_id=linked_by_user.id, name=linked_by_user.display_name or linked_by_user.email
        )
        if linked_by_user is not None
        else None
    )
    return TeamInstallationRead(
        id=row.id,
        provider=row.provider,
        account_login=row.account_login,
        account_type=row.account_type,
        account_avatar_url=row.account_avatar_url,
        repository_selection=row.repository_selection,
        status=row.status.value,
        linked_by=linked_by,
        linked_at=ensure_utc(row.linked_at),
        html_url=f"{row.web_base_url.rstrip('/')}/{row.account_login}",
        manage_url=_installation_manage_url(row),
    )


def serialize_project(
    project: Project,
    *,
    stats: dict[str, int] | None = None,
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project view. `stats`/`sources` are supplied by the caller (list rows get
    summary counts, detail gets graph stats + connected sources)."""
    data: dict[str, Any] = {
        "id": project.id,
        "team_id": project.team_id,
        "name": project.name,
        "description": project.description,
        "archived_at": project.archived_at,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }
    if stats is not None:
        data["stats"] = stats
    if sources is not None:
        data["sources"] = sources
    return data


def serialize_job(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "kind": job.kind.value,
        "status": job.status.value,
        "progress": job.progress,
        "result_ref": job.result_ref,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "finished_at": job.finished_at,
    }


def serialize_notification(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "type": notification.type.value,
        "title": notification.title,
        "body": notification.body,
        "action_url": notification.action_url,
        "attrs": notification.attrs,
        "read_at": notification.read_at,
        "created_at": notification.created_at,
    }


def serialize_artifact_ref(artifact: Artifact) -> dict[str, Any]:
    """The W0-04 `ArtifactRef` shape, verbatim (docs/contracts/agent-tool.md §4)."""
    return {
        "artifact_id": artifact.id,
        "uri": artifact.uri,
        "media_type": artifact.media_type,
        "storage": artifact.storage_location.value,
        "size_bytes": artifact.size_bytes,
        "summary": None,
    }


def serialize_artifact(artifact: Artifact) -> dict[str, Any]:
    """The registry-row view (docs/api/artifacts.md §3)."""
    return {
        "id": artifact.id,
        "project_id": artifact.project_id,
        "scope": artifact.scope.value,
        "uri": artifact.uri,
        "media_type": artifact.media_type,
        "size_bytes": artifact.size_bytes,
        "storage_location": artifact.storage_location.value,
        "created_by": artifact.created_by,
        "source_tool": artifact.source_tool,
        "tool_call_id": artifact.tool_call_id,
        "created_at": artifact.created_at,
        "updated_at": artifact.updated_at,
        "deleted_at": artifact.deleted_at,
    }


def serialize_activity(activity: Activity) -> dict[str, Any]:
    return {
        "id": activity.id,
        "type": activity.type,
        "domain": activity.domain,
        "actor_id": activity.actor_id,
        "project_id": activity.project_id,
        "payload": activity.payload,
        "created_at": activity.created_at,
    }


# --- ORM read schemas: Pydantic v2 mirrors of every table (from_attributes) ---


class ReadModel(BaseModel):
    """Base for internal DB-layer read DTOs that mirror ORM rows 1:1.

    These are NOT HTTP response schemas: they mirror every column, including
    internal identifiers (`supabase_user_id`), billing references (`stripe_*`)
    and raw embeddings. Endpoints must return a narrowed, per-route response
    schema — never bind these straight to a FastAPI `response_model`.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)


class _Created(ReadModel):
    id: UUID
    created_at: datetime


class _Timestamped(_Created):
    updated_at: datetime


class _SoftDeletable(_Timestamped):
    deleted_at: datetime | None


class UserRead(_SoftDeletable):
    supabase_user_id: str
    email: str
    display_name: str | None
    avatar_url: str | None
    sol_mode: SolMode
    data_collection_consent: bool


class TeamRead(_SoftDeletable):
    name: str
    slug: str | None
    kind: TeamKind
    plan_status: str


class MembershipRead(_SoftDeletable):
    team_id: UUID
    user_id: UUID
    role: Role
    status: MembershipStatus
    invited_by: UUID | None


class InviteRead(_Created):
    team_id: UUID
    email: str
    role: Role
    status: InviteStatus
    invited_by: UUID | None
    expires_at: datetime
    # `token` is a one-time secret (shown once at creation) — deliberately omitted.


class ProjectRead(_SoftDeletable):
    team_id: UUID
    name: str
    description: str | None
    created_by: UUID | None


class ProjectMembershipRead(_SoftDeletable):
    project_id: UUID
    user_id: UUID


class SubscriptionRead(_SoftDeletable):
    user_id: UUID
    plan: PlanType
    status: SubscriptionStatus
    limits: dict[str, Any]
    expires_at: datetime | None
    # Pending cancel-at-period-end date; the client shows "your plan ends on X".
    cancel_at: datetime | None
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    seat_count: int | None
    custom_price_per_seat: int | None
    # Cadence of the Stripe Price and the raw renewal date (SOLUSDEV-236); null when unlinked.
    billing_interval: str | None
    current_period_end: datetime | None
    # Same predicate as the spend gate (SOLUSDEV-236); computed, not stored.
    trial_expired: bool = False

    @model_validator(mode="before")
    @classmethod
    def _serve_effective_limits(cls, data: Any) -> Any:
        """`limits` on the wire is what enforcement uses: the stored limits (or active staff
        comp) with the staff `limits_override` merged on top (ADR-023). Staff-only fields
        (`limits_override`, `comp_*`) are deliberately not exposed."""
        if isinstance(data, Subscription):
            values = {
                name: getattr(data, name) for name in cls.model_fields if name != "trial_expired"
            }
            return {
                **values,
                "limits": effective_limits(data),
                "trial_expired": is_local_trial_expired(data),
            }
        return data


class SubscriptionUpdate(StrictModel):
    """Trial plan pick: self-serve plans only (enterprise is contact-sales)."""

    plan: PlanType

    @field_validator("plan")
    @classmethod
    def _checkoutable(cls, plan: PlanType) -> PlanType:
        if plan not in CHECKOUTABLE_PLANS:
            raise ValueError("plan must be one of: basic, pro")
        return plan


class CheckoutSessionCreate(StrictModel):
    """Start a Stripe Checkout. `subscription` needs plan+interval (basic/pro,
    month/year); `pack` needs a price_id that maps to a configured credit pack."""

    kind: Literal["subscription", "pack"]
    plan: PlanType | None = None
    interval: Literal["month", "year"] | None = None
    price_id: str | None = None


class CheckoutSessionRead(BaseModel):
    url: str


class PortalSessionCreate(StrictModel):
    """Optional body of POST /billing/portal-session (SOLUSDEV-236). No ids: the
    subscription is always derived server-side from the caller's own row."""

    flow: Literal["update", "cancel"] | None = None


class PortalSessionRead(BaseModel):
    url: str


class BillingTrialRead(BaseModel):
    """Trial state derived at read time (SOLUSDEV-236)."""

    state: Literal["active", "expired", "none"]
    ends_at: datetime | None


class BillingInvoiceRead(BaseModel):
    amount_cents: int
    currency: str
    date: datetime


class BillingCardRead(BaseModel):
    """Brand and last four digits only (CLAUDE.md section 7)."""

    brand: str
    last4: str


class BillingPriceRead(BaseModel):
    plan: PlanType
    interval: Literal["month", "year"]
    amount_cents: int
    currency: str


class BillingSummaryRead(BaseModel):
    """GET /billing/summary read model for the Billing screen (SOLUSDEV-236). Carries no
    Stripe object ids; Stripe-derived fields are null in degraded mode."""

    plan: PlanType
    status: SubscriptionStatus
    billing_interval: str | None
    current_period_end: datetime | None
    cancel_at: datetime | None
    trial: BillingTrialRead
    next_invoice: BillingInvoiceRead | None
    payment_method: BillingCardRead | None
    prices: list[BillingPriceRead] | None
    packs_available: bool
    stripe_status: Literal["ok", "unavailable", "unconfigured"]


class CreditBalanceView(BaseModel):
    """Lightweight credit-balance response for the UI (always answerable, even
    before any ledger row exists — balance is then 0)."""

    user_id: UUID
    balance: int
    unlimited: bool = False


class CreditBalanceRead(_Timestamped):
    user_id: UUID
    balance: int


class CreditLedgerRead(_Created):
    user_id: UUID
    amount: int
    type: CreditTxnType
    balance_after: int
    attrs: dict[str, Any]


class NotificationRead(_Created):
    user_id: UUID
    type: NotificationType
    title: str
    body: str | None
    action_url: str | None
    attrs: dict[str, Any]
    read_at: datetime | None


class GraphEntityRead(_SoftDeletable):
    project_id: UUID
    kind: str
    domain: Domain
    name: str
    canonical_part_id: UUID | None
    source_connector: str | None
    external_ref: str | None
    attrs: dict[str, Any]
    embedding: list[float] | None


class GraphEdgeRead(_SoftDeletable):
    project_id: UUID
    src_id: UUID
    dst_id: UUID
    relation_type: str
    domain_pair: str
    confidence: float
    attrs: dict[str, Any]


class ErrorSolutionRead(_SoftDeletable):
    project_id: UUID
    error_text: str
    solution_text: str | None
    domain: Domain
    attrs: dict[str, Any]
    embedding: list[float] | None


class ArtifactRead(_SoftDeletable):
    project_id: UUID
    scope: ArtifactScope
    uri: str
    media_type: str
    size_bytes: int | None
    storage_location: ArtifactStorage
    created_by: UUID | None
    source_tool: str | None
    tool_call_id: str | None


class JobRead(_Timestamped):
    project_id: UUID
    team_id: UUID
    kind: JobKind
    status: JobStatus
    progress: int
    result_ref: str | None
    error: dict[str, Any] | None
    created_by: UUID | None
    finished_at: datetime | None


class ActivityRead(_Created):
    team_id: UUID
    project_id: UUID | None
    actor_id: UUID | None
    type: str
    domain: str | None
    payload: dict[str, Any]


class DataEventRead(_Created):
    event_type: str
    user_id: UUID | None
    team_id: UUID | None
    project_id: UUID | None
    payload: dict[str, Any]
