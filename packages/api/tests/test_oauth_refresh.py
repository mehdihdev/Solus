"""OAuth access-token refresh at sync time (SOLUS-CAD-01).

Before this ticket the OAuth path stored ONLY the access token: `_complete_oauth`
persisted `creds.token` and `run_sync` rebuilt `Credentials(token=...)`, dropping
`refresh_token` entirely. GitHub's tokens are long-lived so nothing noticed —
but **Onshape access tokens expire after 60 minutes**, so an Onshape source
would have broken within the hour.

The seam: the runtime owns persistence (it holds the SecretStore), the connector
owns the provider-specific refresh call. On `invalid_credentials` the runtime
refreshes once, re-persists BOTH tokens (Onshape rotates the refresh token on
every use, so failing to persist it breaks the chain), and retries the sync once.
"""

from __future__ import annotations

import uuid

import pytest
from solus_api.connectors.contracts import (
    AccountInfo,
    AuthKind,
    Connector,
    ConnectorError,
    Credentials,
    Domain,
    EntityOut,
    OAuthConnector,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.runtime import refresh_secret_ref, run_sync
from solus_api.connectors.secrets import InMemorySecretStore, SecretNotFoundError
from solus_api.models import (
    Project,
    Source,
    SourceStatus,
    SourceType,
    Sync,
    Team,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


class _RefreshingConnector(OAuthConnector):
    """Fails the first sync with `invalid_credentials`, succeeds after a refresh.

    Records what it saw so the tests can assert the runtime handed over the
    stored refresh token and retried with the NEW access token.
    """

    provider = "onshapefake"
    scopes = ("OAuth2Read",)

    def __init__(self, *, refresh_result: Credentials | Exception | None = None) -> None:
        self.seen_tokens: list[str] = []
        self.seen_refresh_tokens: list[str | None] = []
        self.refresh_calls = 0
        self._refresh_result = refresh_result or Credentials(
            token="fresh-access", refresh_token="rotated-refresh"
        )

    def authorize_url(self, *, state: str, redirect_uri: str, access: str | None = None) -> str:
        return f"https://example.invalid/authorize?state={state}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> Credentials:
        return Credentials(token="a", refresh_token="r")

    async def refresh_credentials(self, creds: Credentials) -> Credentials:
        self.refresh_calls += 1
        if isinstance(self._refresh_result, Exception):
            raise self._refresh_result
        return self._refresh_result

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        return AccountInfo(external_id="1", login="cad-user")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        self.seen_tokens.append(ctx.credentials.token)
        self.seen_refresh_tokens.append(ctx.credentials.refresh_token)
        if ctx.credentials.token != "fresh-access":
            raise ConnectorError("invalid_credentials", "access token expired")
        return SyncResult(
            entities=[
                EntityOut(source_key="p1", type="part", domain=Domain.MECHANICAL, name="Part")
            ]
        )

    async def detect_changes(self, ctx: SyncContext) -> bool:
        return True


class _StaleConnector(Connector):
    """PAT connector that always reports invalid credentials — proves the retry
    is OAuth-only and a non-OAuth connector still fails fast."""

    provider = "patfake"
    auth_kind = AuthKind.PAT

    def __init__(self) -> None:
        self.calls = 0

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        return AccountInfo(external_id="1", login="x")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        self.calls += 1
        raise ConnectorError("invalid_credentials", "nope")

    async def detect_changes(self, ctx: SyncContext) -> bool:
        return True


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(maker: async_sessionmaker[AsyncSession]) -> Source:
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.ONSHAPE,
            name="doc",
            status=SourceStatus.CONNECTED,
            config={},
            secret_ref=f"source/{uuid.uuid4()}/onshape",
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
    return source


async def _sync_row(maker: async_sessionmaker[AsyncSession], sync_id: uuid.UUID) -> Sync:
    async with maker() as db:
        row = (await db.scalars(select(Sync).where(Sync.id == sync_id))).one()
        return row


def test_refresh_ref_is_derived_from_the_access_ref() -> None:
    """One definition, so the write ref and the read ref cannot drift."""
    assert refresh_secret_ref("source/abc/onshape") == "source/abc/onshape/refresh"


async def test_stored_refresh_token_reaches_the_connector(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    source = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(source.secret_ref or "", "stale-access")
    await store.put(refresh_secret_ref(source.secret_ref or ""), "stored-refresh")
    connector = _RefreshingConnector()

    await run_sync(source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store)

    assert connector.seen_refresh_tokens[0] == "stored-refresh"


async def test_expired_token_is_refreshed_and_the_sync_retried_once(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    source = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(source.secret_ref or "", "stale-access")
    await store.put(refresh_secret_ref(source.secret_ref or ""), "stored-refresh")
    connector = _RefreshingConnector()

    sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )

    assert connector.refresh_calls == 1
    assert connector.seen_tokens == ["stale-access", "fresh-access"]
    assert sync_id is not None
    assert (await _sync_row(maker, sync_id)).entities_created == 1


async def test_rotated_refresh_token_is_persisted(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Onshape rotates the refresh token on every use — persisting only the
    access token would break the chain on the NEXT refresh."""
    source = await _seed(maker)
    store = InMemorySecretStore()
    ref = source.secret_ref or ""
    await store.put(ref, "stale-access")
    await store.put(refresh_secret_ref(ref), "stored-refresh")

    await run_sync(
        source_id=source.id,
        sessionmaker=maker,
        connector=_RefreshingConnector(),
        secret_store=store,
    )

    assert await store.get(ref) == "fresh-access"
    assert await store.get(refresh_secret_ref(ref)) == "rotated-refresh"


async def test_refresh_is_attempted_only_once_per_sync(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The retry must not loop: a connector that stays broken fails after one
    refresh, never spinning against the provider's token endpoint."""
    source = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(source.secret_ref or "", "stale-access")
    await store.put(refresh_secret_ref(source.secret_ref or ""), "stored-refresh")
    # Refresh "succeeds" but returns another stale token.
    connector = _RefreshingConnector(
        refresh_result=Credentials(token="still-stale", refresh_token="r2")
    )

    sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )

    assert connector.refresh_calls == 1
    assert len(connector.seen_tokens) == 2
    assert sync_id is not None
    assert (await _sync_row(maker, sync_id)).status.value == "failed"


async def test_missing_refresh_token_fails_without_calling_the_provider(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    source = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(source.secret_ref or "", "stale-access")  # no refresh secret
    connector = _RefreshingConnector()

    sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )

    assert connector.refresh_calls == 0
    assert sync_id is not None
    assert (await _sync_row(maker, sync_id)).status.value == "failed"


async def test_a_failing_refresh_records_the_original_auth_failure(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    source = await _seed(maker)
    store = InMemorySecretStore()
    ref = source.secret_ref or ""
    await store.put(ref, "stale-access")
    await store.put(refresh_secret_ref(ref), "stored-refresh")
    connector = _RefreshingConnector(
        refresh_result=ConnectorError("oauth_refresh_failed", "refresh token revoked")
    )

    sync_id = await run_sync(
        source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store
    )

    assert sync_id is not None
    row = await _sync_row(maker, sync_id)
    assert row.status.value == "failed"
    # The stored credentials are left alone when refresh fails.
    assert await store.get(ref) == "stale-access"


async def test_non_oauth_connector_is_not_retried(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    source = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(source.secret_ref or "", "tok")
    connector = _StaleConnector()

    await run_sync(source_id=source.id, sessionmaker=maker, connector=connector, secret_store=store)

    assert connector.calls == 1


async def test_refresh_secret_is_absent_by_default_for_existing_sources(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Backwards compatibility: sources connected before this ticket have no
    refresh secret, and reading their access token must still work."""
    source = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(source.secret_ref or "", "tok")

    with pytest.raises(SecretNotFoundError):
        await store.get(refresh_secret_ref(source.secret_ref or ""))


class _NonRefreshingOAuth(OAuthConnector):
    """OAuth connector that never opted into refresh (GitLab's situation)."""

    provider = "legacyoauth"

    def authorize_url(self, *, state: str, redirect_uri: str, access: str | None = None) -> str:
        return "https://example.invalid/authorize"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> Credentials:
        return Credentials(token="a", refresh_token="r")

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        return AccountInfo(external_id="1", login="x")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        raise ConnectorError("invalid_credentials", "token rejected")

    async def detect_changes(self, ctx: SyncContext) -> bool:
        return True


class _FlakyStore(InMemorySecretStore):
    """Fails the SECOND put — the crash window the write ordering must survive."""

    def __init__(self) -> None:
        super().__init__()
        self.puts = 0
        self.armed = False  # so test SETUP writes aren't the ones that blow up

    async def put(self, ref: str, value: str) -> None:
        if self.armed:
            self.puts += 1
            if self.puts == 2:
                raise RuntimeError("secrets manager throttled")
        await super().put(ref, value)


async def test_connector_without_a_refresh_override_keeps_its_original_error(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The base `refresh_credentials` refuses, so calling it would swap the real
    `invalid_credentials` for a misleading `oauth_refresh_failed`."""
    source = await _seed(maker)
    store = InMemorySecretStore()
    ref = source.secret_ref or ""
    await store.put(ref, "stale")
    await store.put(refresh_secret_ref(ref), "stored-refresh")

    sync_id = await run_sync(
        source_id=source.id,
        sessionmaker=maker,
        connector=_NonRefreshingOAuth(),
        secret_store=store,
    )

    assert sync_id is not None
    assert (await _sync_row(maker, sync_id)).status.value == "failed"
    async with maker() as db:
        refreshed = await db.get(Source, source.id)
    assert refreshed is not None
    assert refreshed.last_error is not None
    # NOT `oauth_refresh_failed` — the base refusal must not mask the real cause.
    assert refreshed.last_error["code"] == "invalid_credentials"


async def test_refresh_token_is_written_before_the_access_token(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Onshape invalidates the OLD refresh token the moment it issues a new one.
    If the second write fails, the surviving state must be a stale ACCESS token
    beside a VALID refresh token — recoverable on the next sync. The reverse
    ordering would strand the source permanently."""
    source = await _seed(maker)
    store = _FlakyStore()
    ref = source.secret_ref or ""
    await store.put(ref, "stale-access")
    await store.put(refresh_secret_ref(ref), "stored-refresh")
    store.armed = True  # only the refresh-path writes are under test

    await run_sync(
        source_id=source.id,
        sessionmaker=maker,
        connector=_RefreshingConnector(),
        secret_store=store,
    )

    # The first write landed and it was the ROTATED REFRESH token.
    assert await store.get(refresh_secret_ref(ref)) == "rotated-refresh"
