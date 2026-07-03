"""The connector interface — W0-05 (DRAFT, promote to packages/contracts/).

This is the spine of parallel connector development (CLAUDE.md §9): every
connector implements `Connector` (and `OAuthConnector` when it authenticates
via OAuth), translating tool-specific data into graph `EntityOut`/`RelationOut`
records. The runtime depends only on these abstractions, never on a concrete
connector — so the whole roster (GitLab, KiCad, Onshape, ROS) plugs in the same
way GitHub does.

Everything here is immutable (frozen Pydantic models) per the coding-style
immutability rule. Ingested content is data, never instructions (CLAUDE.md §7).
"""

from __future__ import annotations

import abc
import enum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field


class AuthKind(enum.StrEnum):
    """How a connector authenticates. Fixed by Solus code, never by user data."""

    OAUTH = "oauth"
    PAT = "pat"
    APP = "app"
    NONE = "none"


class Domain(enum.StrEnum):
    """The four worlds a robot lives in (CLAUDE.md §1) + cross-domain exports."""

    SOFTWARE = "software"
    ELECTRICAL = "electrical"
    MECHANICAL = "mechanical"
    RUNTIME = "runtime"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EntityOut(FrozenModel):
    """A typed graph node a connector wants to land (ADR-001).

    `source_key` is the entity's stable natural key *within its source* (e.g. a
    repo-relative file path). The runtime keys graph rows on
    `(source_id, source_key)`, so a re-sync updates rather than duplicates.
    """

    source_key: str = Field(min_length=1, max_length=1024)
    type: str = Field(min_length=1, max_length=64)
    domain: Domain
    name: str = Field(min_length=1, max_length=512)
    properties: dict[str, Any] = Field(default_factory=dict)


class RelationOut(FrozenModel):
    """A typed graph edge between two entities, addressed by their source keys."""

    from_key: str = Field(min_length=1, max_length=1024)
    to_key: str = Field(min_length=1, max_length=1024)
    type: str = Field(min_length=1, max_length=64)
    properties: dict[str, Any] = Field(default_factory=dict)


class Credentials(FrozenModel):
    """Resolved auth material for one sync. Sourced from the secret store —
    never from config, never logged, never echoed back by the API (CLAUDE.md §7)."""

    token: str
    refresh_token: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AccountInfo(FrozenModel):
    """Identity proven by `validate_credentials` — shown to the user, stored on
    the source so "whose token is this?" is answerable without the token."""

    external_id: str
    login: str
    name: str | None = None


class SyncContext(FrozenModel):
    """Everything a connector needs to run one sync. Assembled by the runtime,
    team-scoped before it is built (CLAUDE.md §7 — no cross-tenant content)."""

    credentials: Credentials
    config: dict[str, Any] = Field(default_factory=dict)
    cursor: dict[str, Any] = Field(default_factory=dict)


class SyncError(FrozenModel):
    """A non-fatal per-item failure. Surfaced on the Sync record so
    "why did this user's sync partially fail?" is answerable (CLAUDE.md §6)."""

    item: str
    message: str


class SyncResult(FrozenModel):
    """A connector's output for one sync: the entities/relations to land, the
    new cursor to persist for next time, and any per-item errors."""

    entities: list[EntityOut] = Field(default_factory=list)
    relations: list[RelationOut] = Field(default_factory=list)
    cursor: dict[str, Any] = Field(default_factory=dict)
    errors: list[SyncError] = Field(default_factory=list)


class ConnectorError(Exception):
    """Raised by a connector when a sync cannot proceed (auth, network, config).

    Carries a stable `code` for the API/UI and a human-readable message.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class Connector(abc.ABC):
    """A source of graph data. Implementations are stateless and reusable; all
    per-sync state arrives in `SyncContext` and leaves in `SyncResult.cursor`."""

    provider: ClassVar[str]
    auth_kind: ClassVar[AuthKind] = AuthKind.NONE
    #: JSON-schema-ish description of the per-source config the connector needs
    #: (e.g. {"repo": "owner/name", "branch": "main"}). Surfaced by the catalog.
    config_fields: ClassVar[tuple[str, ...]] = ()
    #: Whether a directly-supplied token (e.g. a PAT) is an accepted way to
    #: connect this source. OAuth-only connectors leave this False so the
    #: token-connect path can't bypass the OAuth flow (CLAUDE.md §7).
    supports_token_connect: ClassVar[bool] = False

    @abc.abstractmethod
    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        """Confirm the credentials work and return the authenticated identity.

        Raises ConnectorError('invalid_credentials', ...) when they do not."""

    @abc.abstractmethod
    async def sync(self, ctx: SyncContext) -> SyncResult:
        """Walk the source and produce graph entities/relations + a new cursor."""

    @abc.abstractmethod
    async def detect_changes(self, ctx: SyncContext) -> bool:
        """Cheap probe: has the source changed since `ctx.cursor`? Drives the
        scheduled change-detection that decides whether to enqueue a full sync."""


class OAuthConnector(Connector):
    """A connector whose `auth_kind` is OAUTH. Adds the authorize/exchange half
    of the flow. The runtime owns `state` and credential storage; the connector
    only knows how to talk to the provider's OAuth endpoints."""

    auth_kind: ClassVar[AuthKind] = AuthKind.OAUTH
    #: OAuth scopes Solus requests. Fixed in code (CLAUDE.md §7).
    scopes: ClassVar[tuple[str, ...]] = ()

    @abc.abstractmethod
    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        """Build the provider authorize URL the user's browser is sent to."""

    @abc.abstractmethod
    async def exchange_code(self, *, code: str, redirect_uri: str) -> Credentials:
        """Exchange an OAuth `code` for access credentials.

        Raises ConnectorError('oauth_exchange_failed', ...) on failure."""
