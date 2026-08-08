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


def test_build_registry_ships_the_roster() -> None:
    from solus_api.connectors.altium import AltiumConnector
    from solus_api.connectors.github import GitHubConnector
    from solus_api.connectors.gitlab import GitLabConnector
    from solus_api.connectors.kicad import KicadConnector
    from solus_api.core.config import Settings

    settings = Settings(
        supabase_jwt_secret="dummy-value-tests-only",
        database_url="sqlite+aiosqlite://",
        gitlab_base_url="https://gitlab.example.com",
    )
    from solus_api.connectors.registry import build_registry

    registry = build_registry(settings)
    assert registry.providers() == ["altium", "github", "gitlab", "kicad"]
    assert isinstance(registry.create("github"), GitHubConnector)
    gitlab = registry.create("gitlab")
    assert isinstance(gitlab, GitLabConnector)
    assert isinstance(registry.create("altium"), AltiumConnector)
    assert isinstance(registry.create("kicad"), KicadConnector)
    catalog = {c["type"]: c for c in registry.catalog()}
    assert catalog["gitlab"]["auth_kind"] == "oauth"
    assert "read_api" in catalog["gitlab"]["scopes"]
    # The committed-export EDA family (Altium SOLUSDEV-102, KiCad SOLUSDEV-100):
    # no tool credential, configured with the export content in v1.
    for eda_provider in ("altium", "kicad"):
        assert catalog[eda_provider]["auth_kind"] == "none"
    # Altium additionally advertises the live-acquisition project_path key
    # (SOLUSDEV-102 ALT-8; mcp_acquire.py's config-key decision). KiCad's
    # matching update belongs to whoever owns connectors/kicad.py.
    assert catalog["altium"]["config_fields"] == ["export", "project_path"]
    assert catalog["kicad"]["config_fields"] == ["export"]
