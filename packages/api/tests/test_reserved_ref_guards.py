"""SOLUSDEV-216 T2 — defence in depth for the reserved `github-app/` ref (ADR-039 §3).

An installation source's ref is not a stored secret: nothing may get/put/delete it
against a SecretStore, no account-reuse path may adopt the source, and disconnecting it
deletes no secret. The call sites outside this task's files are proven here by test.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from conftest import ALICE, create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.connectors.contracts import OAuthConnector
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.secrets import (
    InMemorySecretStore,
    LocalEncryptedSecretStore,
    ReservedSecretRefError,
    SecretStore,
)
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    InstallationStatus,
    Project,
    Source,
    SourceStatus,
    SourceType,
    TeamInstallation,
    User,
)
from solus_api.services.connections import (
    _is_oauth_source,
    _own_token_sources,
    is_connection_owned,
    legacy_sources,
    named_legacy_sources,
    reusable_source,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

REF = "github-app/installation/0190f0e0-0000-7000-8000-000000000001"
RESERVED_REFS = [REF, f"{REF}/refresh", "github-app/anything", "github-app/"]


# ------------------------------------------------------------------ every backend


class _BareBackend(SecretStore):
    """A third-party backend that only implements the abstract methods."""

    def __init__(self) -> None:
        self.touched = False

    async def put(self, ref: str, value: str) -> None:
        self.touched = True

    async def get(self, ref: str) -> str:
        self.touched = True
        return "x"

    async def delete(self, ref: str) -> None:
        self.touched = True


class _FakeAws:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError("AWS must not be called for a reserved ref")


def _aws_store() -> SecretStore:
    from solus_api.connectors.secrets import AwsSecretsManagerStore

    store = AwsSecretsManagerStore.__new__(AwsSecretsManagerStore)
    store._client = _FakeAws()  # type: ignore[assignment]
    store._prefix = "solus/connectors/"
    return store


def _local_store(maker: async_sessionmaker[AsyncSession]) -> SecretStore:
    from cryptography.fernet import Fernet

    return LocalEncryptedSecretStore(Fernet(Fernet.generate_key()), maker)


@pytest.fixture
def backends(db: AsyncSession) -> dict[str, SecretStore]:
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    return {
        "memory": InMemorySecretStore(),
        "local": _local_store(maker),
        "aws": _aws_store(),
        "bare": _BareBackend(),
    }


@pytest.mark.parametrize("ref", RESERVED_REFS)
@pytest.mark.parametrize("backend", ["memory", "local", "aws", "bare"])
async def test_every_backend_refuses_the_reserved_prefix(
    backends: dict[str, SecretStore], backend: str, ref: str
) -> None:
    store = backends[backend]
    with pytest.raises(ReservedSecretRefError):
        await store.get(ref)
    with pytest.raises(ReservedSecretRefError):
        await store.put(ref, "tok")
    with pytest.raises(ReservedSecretRefError):
        await store.delete(ref)
    if isinstance(store, _BareBackend):
        assert store.touched is False


async def test_the_guard_covers_subclasses_of_subclasses() -> None:
    class Derived(InMemorySecretStore):
        async def get(self, ref: str) -> str:
            return await super().get(ref)

    with pytest.raises(ReservedSecretRefError):
        await Derived().get(REF)


async def test_the_reserved_error_is_a_value_error_not_a_missing_secret() -> None:
    assert issubclass(ReservedSecretRefError, ValueError)
    from solus_api.connectors.secrets import SecretNotFoundError

    assert not issubclass(ReservedSecretRefError, SecretNotFoundError)


@pytest.mark.parametrize(
    "ref", ["source/1/github", "connection/x/github", "github-apple/1", "x/github-app/1"]
)
async def test_ordinary_refs_still_work(ref: str) -> None:
    store = InMemorySecretStore()
    await store.put(ref, "v")
    assert await store.get(ref) == "v"
    await store.delete(ref)


# ------------------------------------------------------------------ ownership


@pytest.mark.parametrize(
    "ref", [REF, "github-app/installation/0190f0e0-0000-7000-8000-000000000002"]
)
def test_installation_refs_are_connection_owned(ref: str) -> None:
    assert is_connection_owned(ref) is True


def test_ownership_unchanged_for_other_refs() -> None:
    assert is_connection_owned("connection/abc/github") is True
    assert is_connection_owned("source/abc/github") is False
    assert is_connection_owned(None) is False
    assert is_connection_owned("") is False


# ------------------------------------------------------------------ DB-backed helpers


class _OAuthGitHub(OAuthConnector):
    provider = "github"
    selection = {"mode": "multi", "config_key": "repos", "label": "repo"}

    def authorize_url(self, *, state: str, redirect_uri: str, access: str | None = None) -> str:
        return ""

    async def exchange_code(self, *, code: str, redirect_uri: str) -> Any:
        raise NotImplementedError

    async def validate_credentials(self, creds: Any) -> Any:
        raise NotImplementedError

    async def sync(self, ctx: Any) -> Any:
        raise NotImplementedError

    async def detect_changes(self, ctx: Any) -> bool:
        return False


@pytest.fixture
def registry() -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register("github", _OAuthGitHub)
    return reg


async def _world(
    client: AsyncClient, db: AsyncSession, headers: dict[str, str]
) -> tuple[User, Project, TeamInstallation]:
    await me(client, headers)
    team = await create_team(client, headers)
    project_json = await create_project(client, headers, team["id"])
    user = (await db.scalars(select(User).where(User.email == ALICE["email"]))).one()
    project = (
        await db.scalars(select(Project).where(Project.id == uuid.UUID(project_json["id"])))
    ).one()
    installation = TeamInstallation(
        team_id=project.team_id,
        external_installation_id=1001,
        account_login="octocat",
        # A User-account installation whose account id equals the caller's GitHub id.
        account_external_id=42,
        account_type="User",
        repository_selection="all",
        status=InstallationStatus.ACTIVE,
    )
    db.add(installation)
    await db.flush()
    return user, project, installation


def _installation_source(
    project: Project, installation: TeamInstallation, user: User, **kw: Any
) -> Source:
    return Source(
        project_id=project.id,
        team_id=project.team_id,
        type=SourceType.GITHUB,
        name="org repo",
        config={"repo": "octocat/fw", "branch": "main"},
        status=SourceStatus.CONNECTED,
        created_by=user.id,
        installation_id=installation.id,
        secret_ref=REF,
        account_login="octocat",
        account_external_id="installation:1001",
        **kw,
    )


async def _connection(db: AsyncSession, user: User) -> AccountConnection:
    connection = AccountConnection(
        user_id=user.id,
        provider="github",
        status=ConnectionStatus.CONNECTED,
        secret_ref="connection/x/github",
        account_external_id="42",  # the SAME id as the installation's account
        account_login="octocat",
        config={},
    )
    db.add(connection)
    await db.flush()
    return connection


async def test_reusable_source_never_adopts_an_installation_source(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    user, project, installation = await _world(client, db, alice_headers)
    source = _installation_source(project, installation, user)
    # Even a source whose account id collides with the caller's GitHub id.
    source.account_external_id = "42"
    db.add(source)
    connection = await _connection(db, user)
    found = await reusable_source(
        db, project, SourceType.GITHUB, _OAuthGitHub(), connection=connection, config={}
    )
    assert found is None


async def test_reusable_source_still_adopts_a_plain_matching_source(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    user, project, installation = await _world(client, db, alice_headers)
    plain = Source(
        project_id=project.id,
        team_id=project.team_id,
        type=SourceType.GITHUB,
        name="pat",
        config={},
        status=SourceStatus.CONNECTED,
        created_by=user.id,
        secret_ref=f"source/{uuid.uuid4()}/github",
        account_external_id="42",
    )
    db.add(plain)
    connection = await _connection(db, user)
    found = await reusable_source(
        db, project, SourceType.GITHUB, _OAuthGitHub(), connection=connection, config={}
    )
    assert found is not None and found.id == plain.id


async def test_legacy_and_own_token_listings_exclude_installation_sources(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    registry: ConnectorRegistry,
) -> None:
    user, project, installation = await _world(client, db, alice_headers)
    source = _installation_source(project, installation, user)
    db.add(source)
    await db.flush()
    assert await legacy_sources(db, registry, user) == []
    assert await named_legacy_sources(db, registry, user, {source.id}) == []
    assert (await db.scalars(_own_token_sources(user))).all() == []
    assert _is_oauth_source(registry, source) is False


async def test_the_installation_flag_alone_excludes_a_source(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    registry: ConnectorRegistry,
) -> None:
    """Defence in depth: even with an ordinary-looking ref, installation_id excludes."""
    user, project, installation = await _world(client, db, alice_headers)
    source = _installation_source(project, installation, user)
    source.secret_ref = f"source/{uuid.uuid4()}/github"
    db.add(source)
    await db.flush()
    assert await legacy_sources(db, registry, user) == []
    assert _is_oauth_source(registry, source) is False


async def test_a_plain_own_token_source_is_still_listed(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    registry: ConnectorRegistry,
) -> None:
    user, project, _ = await _world(client, db, alice_headers)
    plain = Source(
        project_id=project.id,
        team_id=project.team_id,
        type=SourceType.GITHUB,
        name="pat",
        config={},
        status=SourceStatus.CONNECTED,
        created_by=user.id,
        secret_ref=f"source/{uuid.uuid4()}/github",
    )
    db.add(plain)
    await db.flush()
    assert [s.id for s in await legacy_sources(db, registry, user)] == [plain.id]


# ------------------------------------------------------------------ the disconnect route


class _SpyStore(InMemorySecretStore):
    def __init__(self) -> None:
        super().__init__()
        self.ops: list[tuple[str, str]] = []

    async def put(self, ref: str, value: str) -> None:
        self.ops.append(("put", ref))
        await super().put(ref, value)

    async def get(self, ref: str) -> str:
        self.ops.append(("get", ref))
        return await super().get(ref)

    async def delete(self, ref: str) -> None:
        self.ops.append(("delete", ref))
        await super().delete(ref)


async def test_disconnecting_an_installation_source_deletes_no_secret(
    client: AsyncClient,
    app: FastAPI,
    db: AsyncSession,
    alice_headers: dict[str, str],
) -> None:
    user, project, installation = await _world(client, db, alice_headers)
    source = _installation_source(project, installation, user)
    db.add(source)
    await db.commit()
    source_id, installation_id = source.id, installation.id
    spy = _SpyStore()
    app.state.secret_store = spy
    resp = await client.delete(
        f"/api/v1/projects/{project.id}/sources/{source_id}", headers=alice_headers
    )
    assert resp.status_code in {200, 204}, resp.text
    assert spy.ops == []
    db.expire_all()
    remaining = (await db.scalars(select(Source).where(Source.id == source_id))).one_or_none()
    # The row is gone or disconnected; either way no SecretStore call was made.
    assert remaining is None or remaining.status is SourceStatus.DISCONNECTED
    assert await db.get(TeamInstallation, installation_id) is not None


async def test_project_teardown_deletes_no_secret_for_an_installation_source(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    from solus_api.services.account_deletion import delete_projects_cascade

    user, project, installation = await _world(client, db, alice_headers)
    db.add(_installation_source(project, installation, user))
    await db.flush()
    spy = _SpyStore()
    await delete_projects_cascade(db, [project.id], spy, None)
    assert spy.ops == []


def test_the_installation_prefix_sits_under_the_reserved_store_prefix() -> None:
    from solus_api.connectors.github_app import INSTALLATION_REF_PREFIX
    from solus_api.connectors.secrets import RESERVED_REF_PREFIX

    assert INSTALLATION_REF_PREFIX.startswith(RESERVED_REF_PREFIX)
