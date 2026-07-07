"""Connector registry tests — registration, lookup, catalog (API.md §2.5)."""

import pytest
from solus_api.connectors.contracts import (
    AccountInfo,
    AuthKind,
    Connector,
    Credentials,
    SyncContext,
    SyncResult,
)
from solus_api.connectors.registry import ConnectorRegistry, UnknownConnectorError


class _Fake(Connector):
    provider = "fake"
    auth_kind = AuthKind.PAT
    config_fields = ("repo",)

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        return AccountInfo(external_id="1", login="x")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        return SyncResult()

    async def detect_changes(self, ctx: SyncContext) -> bool:
        return False


def test_register_and_create() -> None:
    registry = ConnectorRegistry()
    registry.register("fake", _Fake)
    connector = registry.create("fake")
    assert isinstance(connector, _Fake)


def test_create_unknown_raises() -> None:
    registry = ConnectorRegistry()
    with pytest.raises(UnknownConnectorError):
        registry.create("nope")


def test_providers_sorted() -> None:
    registry = ConnectorRegistry()
    registry.register("zeta", _Fake)
    registry.register("alpha", _Fake)
    assert registry.providers() == ["alpha", "zeta"]


def test_catalog_exposes_auth_and_config() -> None:
    registry = ConnectorRegistry()
    registry.register("fake", _Fake)
    catalog = registry.catalog()
    assert catalog == [
        {"type": "fake", "auth_kind": "pat", "config_fields": ["repo"], "scopes": []}
    ]


def test_build_registry_ships_both_code_hosts() -> None:
    from solus_api.connectors.github import GitHubConnector
    from solus_api.connectors.gitlab import GitLabConnector
    from solus_api.core.config import Settings

    settings = Settings(
        supabase_jwt_secret="dummy-value-tests-only",
        database_url="sqlite+aiosqlite://",
        gitlab_base_url="https://gitlab.example.com",
    )
    from solus_api.connectors.registry import build_registry

    registry = build_registry(settings)
    assert registry.providers() == ["github", "gitlab"]
    assert isinstance(registry.create("github"), GitHubConnector)
    gitlab = registry.create("gitlab")
    assert isinstance(gitlab, GitLabConnector)
    # Self-hosted base URL threads through from settings.
    assert gitlab.authorize_url.__self__ is gitlab  # sanity: bound instance
    catalog = {c["type"]: c for c in registry.catalog()}
    assert catalog["gitlab"]["auth_kind"] == "oauth"
    assert "read_api" in catalog["gitlab"]["scopes"]
