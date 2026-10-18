"""SOLUSDEV-216 T2 — runtime dispatch of the reserved installation ref (ADR-039 §3).

`resolve_credentials` hands `github-app/installation/{id}` to the App minter and never
touches the SecretStore for it; `call_with_refresh` never writes a refreshed token back.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from solus_api.connectors import github_app, runtime
from solus_api.connectors.contracts import ConnectorError, Credentials, OAuthConnector
from solus_api.connectors.runtime import (
    _resolve_credentials,
    call_with_refresh,
    resolve_credentials,
)
from solus_api.connectors.secrets import InMemorySecretStore, SecretStore
from solus_api.core.config import Settings


class SpyStore(SecretStore):
    """Raises on any call: proves the SecretStore is never consulted."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def put(self, ref: str, value: str) -> None:
        self.calls.append(("put", ref))
        raise AssertionError("SecretStore.put must not be called")

    async def get(self, ref: str) -> str:
        self.calls.append(("get", ref))
        raise AssertionError("SecretStore.get must not be called")

    async def delete(self, ref: str) -> None:
        self.calls.append(("delete", ref))
        raise AssertionError("SecretStore.delete must not be called")


@pytest.fixture
def resolved(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def fake_resolve(ref: str) -> Credentials:
        seen.append(ref)
        return Credentials(
            token="ghs_fake",
            metadata={"kind": "github_app_installation", "installation_id": 7},
        )

    monkeypatch.setattr(runtime, "resolve_installation_credentials", fake_resolve)
    return seen


async def test_installation_ref_dispatches_without_touching_the_store(
    resolved: list[str],
) -> None:
    store = SpyStore()
    creds = await resolve_credentials(store, "github-app/installation/7")
    assert resolved == ["github-app/installation/7"]
    assert store.calls == []
    assert creds.token == "ghs_fake" and creds.refresh_token is None
    assert creds.metadata["installation_id"] == 7


async def test_the_private_alias_still_resolves() -> None:
    assert _resolve_credentials is resolve_credentials


async def test_ordinary_refs_still_read_the_store(resolved: list[str]) -> None:
    store = InMemorySecretStore()
    await store.put("source/1/github", "tok")
    await store.put("source/1/github/refresh", "ref")
    creds = await resolve_credentials(store, "source/1/github")
    assert (creds.token, creds.refresh_token) == ("tok", "ref")
    assert resolved == []


@pytest.mark.parametrize(
    "ref",
    [
        "github-app/installation/abc",
        "github-app/installation/../1",
        "github-app/installation/1/refresh",
        "github-app/installation/01",
        "github-app/installation/",
    ],
)
async def test_malformed_reserved_refs_are_refused_without_the_store(ref: str) -> None:
    store = SpyStore()
    with pytest.raises(ConnectorError) as exc:
        await resolve_credentials(store, ref)
    assert exc.value.code == "invalid_secret_ref"
    assert store.calls == []


async def test_the_real_resolver_is_reached_through_the_dispatch(settings: Settings) -> None:
    """No stub: an unconfigured App proves the dispatch hit github_app, not the store."""
    github_app.configure_github_app(settings)
    store = SpyStore()
    with pytest.raises(ConnectorError) as exc:
        await resolve_credentials(store, "github-app/installation/7")
    assert exc.value.code == "github_app_unconfigured"
    assert store.calls == []


class _RefreshingConnector(OAuthConnector):
    """Overrides refresh_credentials, so the refresh path is live for it."""

    provider = "github"
    refreshes = 0

    def authorize_url(self, *, state: str, redirect_uri: str, access: str | None = None) -> str:
        return ""

    async def exchange_code(self, *, code: str, redirect_uri: str) -> Credentials:
        raise NotImplementedError

    async def validate_credentials(self, creds: Credentials) -> Any:
        raise NotImplementedError

    async def sync(self, ctx: Any) -> Any:
        raise NotImplementedError

    async def detect_changes(self, ctx: Any) -> bool:
        return False

    async def refresh_credentials(self, creds: Credentials) -> Credentials:
        type(self).refreshes += 1
        return Credentials(token="refreshed", refresh_token="rotated")


@pytest.fixture
async def attempts() -> AsyncIterator[list[str]]:
    _RefreshingConnector.refreshes = 0
    yield []


async def test_call_with_refresh_never_puts_for_an_installation_ref(attempts: list[str]) -> None:
    store = SpyStore()

    async def run(creds: Credentials) -> str:
        attempts.append(creds.token)
        raise ConnectorError("invalid_credentials", "expired")

    creds = Credentials(token="ghs_old", refresh_token="r")
    with pytest.raises(ConnectorError) as exc:
        await call_with_refresh(
            connector=_RefreshingConnector(),
            credentials=creds,
            secret_store=store,
            secret_ref="github-app/installation/7",
            run=run,
        )
    assert exc.value.code == "invalid_credentials"
    assert store.calls == []
    assert attempts == ["ghs_old"]  # not retried, not refreshed
    assert _RefreshingConnector.refreshes == 0


async def test_call_with_refresh_still_refreshes_ordinary_refs(attempts: list[str]) -> None:
    store = InMemorySecretStore()

    async def run(creds: Credentials) -> str:
        attempts.append(creds.token)
        if creds.token == "old":
            raise ConnectorError("invalid_credentials", "expired")
        return "ok"

    result = await call_with_refresh(
        connector=_RefreshingConnector(),
        credentials=Credentials(token="old", refresh_token="r"),
        secret_store=store,
        secret_ref="source/1/github",
        run=run,
    )
    assert result == "ok" and attempts == ["old", "refreshed"]
    assert await store.get("source/1/github") == "refreshed"
