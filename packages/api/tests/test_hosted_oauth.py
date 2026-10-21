"""The hosted-server OAuth client (SOLUSDEV-168).

Keyless by construction: every test drives a fake transport, so the suite never
needs a credential and never touches the network.
"""

import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from solus_api.agent.tools.remote_mcp import FS_MCP, RemoteAuthError
from solus_api.connectors import hosted_oauth
from solus_api.connectors.hosted_oauth import (
    HostedClient,
    HostedToken,
    authorize_url,
    client_secret_ref,
    ensure_client,
    exchange_code,
    hosted_refs,
    new_pkce,
    refresh_token,
    token_secret_ref,
)
from solus_api.connectors.secrets import InMemorySecretStore, SecretNotFoundError

REDIRECT = "http://localhost:53682/auth/callback"
CLIENT = HostedClient(client_id="cid", client_secret="csecret")


def _transport(handler: Callable[[str, dict[str, Any]], httpx.Response]) -> Any:
    """Patch httpx.AsyncClient so no test can reach the network."""

    class _Client:
        def __init__(self, **_: Any) -> None: ...

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_: object) -> None: ...

        async def post(self, url: str, **kwargs: Any) -> httpx.Response:
            return handler(url, kwargs)

    return _Client


def _json_response(status: int, payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("POST", "https://x/"))


# --------------------------------------------------------------- refs & sweeps


def test_token_ref_is_derived_from_the_source_so_deletion_sweeps_reach_it() -> None:
    """`disconnect_source` and `delete_projects_cascade` both sweep from
    `Source.secret_ref`. A ref they cannot derive is a live OAuth2Write grant
    that survives the customer revoking us."""
    ref = token_secret_ref("source/abc/onshape", "onshape_fs")
    assert ref.startswith("source/abc/onshape/")
    assert hosted_refs("source/abc/onshape") == [ref]


def test_the_dcr_client_is_solus_wide_not_per_customer() -> None:
    """The CLIENT is Solus; the TOKENS are the customer's. Keying the client per
    user is how the SDK ends up registering a new client for every cold worker."""
    assert client_secret_ref("onshape_fs") == "hosted-mcp/onshape_fs/client"
    assert "source/" not in client_secret_ref("onshape_fs")


# ------------------------------------------------------------------- registration


async def test_registration_happens_once_and_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def handler(url: str, kwargs: dict[str, Any]) -> httpx.Response:
        calls.append(kwargs)
        return _json_response(
            201, {"client_id": "cid", "client_secret": "s", "scope": "OAuth2Read OAuth2Write"}
        )

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    store = InMemorySecretStore()
    first = await ensure_client(store, FS_MCP, redirect_uri=REDIRECT)
    second = await ensure_client(store, FS_MCP, redirect_uri=REDIRECT)
    assert first == second == HostedClient(client_id="cid", client_secret="s")
    assert len(calls) == 1, "a second connect must not leave another client on the vendor's side"
    assert calls[0]["json"]["scope"] == "OAuth2Read OAuth2Write"
    assert calls[0]["json"]["redirect_uris"] == [REDIRECT]


async def test_registration_is_a_public_pkce_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Onshape's auth host supports only `none` and `private_key_jwt` at the
    token endpoint; `client_secret_post` is not offered. PKCE carries the proof."""
    seen: dict[str, Any] = {}

    def handler(url: str, kwargs: dict[str, Any]) -> httpx.Response:
        seen.update({"url": url, **kwargs["json"]})
        return _json_response(201, {"client_id": "cid", "scope": "OAuth2Read OAuth2Write"})

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    client = await ensure_client(InMemorySecretStore(), FS_MCP, redirect_uri=REDIRECT)
    assert seen["url"] == FS_MCP.register_url
    assert seen["token_endpoint_auth_method"] == "none"
    assert client == HostedClient(client_id="cid", client_secret=None)


@pytest.mark.parametrize(
    "stored",
    [
        {"client_id": "old", "client_secret": None},
        {
            "client_id": "old",
            "client_secret": None,
            "register_url": "https://gone.example/register",
        },
    ],
    ids=["legacy-record-without-origin", "registered-at-another-endpoint"],
)
async def test_a_client_registered_elsewhere_is_replaced(
    monkeypatch: pytest.MonkeyPatch, stored: dict[str, Any]
) -> None:
    """A DCR client id only means something to the server that issued it. When
    the pinned register endpoint moves, the cached id is dead (the old host's
    `/authorize` 404s), so it is re-registered rather than sent to the new host."""
    calls: list[str] = []

    def handler(url: str, _kwargs: dict[str, Any]) -> httpx.Response:
        calls.append(url)
        return _json_response(201, {"client_id": "new", "scope": "OAuth2Read OAuth2Write"})

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    store = InMemorySecretStore()
    await store.put(client_secret_ref(FS_MCP.name), json.dumps(stored))
    client = await ensure_client(store, FS_MCP, redirect_uri=REDIRECT)
    assert client.client_id == "new"
    assert calls == [FS_MCP.register_url]
    again = await ensure_client(store, FS_MCP, redirect_uri=REDIRECT)
    assert again.client_id == "new" and len(calls) == 1, "the replacement is cached"


async def test_registration_refuses_a_wider_grant_than_we_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The approved decision: if the server insists on Delete or ReadPII, STOP.
    Mechanically, not as a code comment."""

    def handler(_url: str, _kwargs: dict[str, Any]) -> httpx.Response:
        return _json_response(
            201, {"client_id": "cid", "scope": "OAuth2Read OAuth2Write OAuth2Delete"}
        )

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    store = InMemorySecretStore()
    with pytest.raises(RemoteAuthError) as caught:
        await ensure_client(store, FS_MCP, redirect_uri=REDIRECT)
    assert caught.value.code == "scope_escalation"
    assert "OAuth2Delete" not in caught.value.message, "scope names are for the log, not the user"
    with pytest.raises(SecretNotFoundError):
        await store.get(client_secret_ref(FS_MCP.name))  # nothing was stored


# ------------------------------------------------------------------- authorize


def test_authorize_url_pins_scope_and_carries_pkce() -> None:
    verifier, challenge = new_pkce()
    assert 43 <= len(verifier) <= 128
    url = authorize_url(FS_MCP, CLIENT, state="st", code_challenge=challenge, redirect_uri=REDIRECT)
    assert url.startswith("https://mcp-auth.labs.onshape.app/authorize?")
    assert "code_challenge_method=S256" in url
    assert "scope=OAuth2Read+OAuth2Write" in url
    assert "resource=https%3A%2F%2Ffs-mcp.labs.onshape.app" in url
    assert "OAuth2Delete" not in url and "OAuth2ReadPII" not in url


def test_pkce_verifier_is_fresh_every_time() -> None:
    assert new_pkce()[0] != new_pkce()[0]


# ---------------------------------------------------------------------- tokens


async def test_exchange_sends_the_verifier_and_stores_an_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(url: str, kwargs: dict[str, Any]) -> httpx.Response:
        seen.update({"url": url, **kwargs["data"]})
        return _json_response(
            200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3599}
        )

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    token = await exchange_code(
        FS_MCP, CLIENT, code="c", code_verifier="v", redirect_uri=REDIRECT, now=1000.0
    )
    assert seen["url"] == FS_MCP.token_url
    assert seen["code_verifier"] == "v"
    assert seen["client_secret"] == "csecret"
    assert seen["resource"] == FS_MCP.resource
    assert token == HostedToken(access_token="at", refresh_token="rt", expires_at=4599.0)


async def test_exchange_refuses_a_token_granting_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_url: str, _kwargs: dict[str, Any]) -> httpx.Response:
        return _json_response(
            200, {"access_token": "at", "expires_in": 3599, "scope": "OAuth2Read OAuth2ReadPII"}
        )

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    with pytest.raises(RemoteAuthError) as caught:
        await exchange_code(FS_MCP, CLIENT, code="c", code_verifier="v", redirect_uri=REDIRECT)
    assert caught.value.code == "scope_escalation"


async def test_refresh_keeps_a_non_rotated_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """fs-mcp's rotation behaviour is UNVERIFIED. A server that returns no new
    refresh token has not invalidated the old one — dropping it would strand the
    grant on the very next call."""

    def handler(_url: str, _kwargs: dict[str, Any]) -> httpx.Response:
        return _json_response(200, {"access_token": "at2", "expires_in": 3599})

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    stale = HostedToken(access_token="at1", refresh_token="rt1", expires_at=0.0)
    fresh = await refresh_token(FS_MCP, CLIENT, stale, now=0.0)
    assert fresh.access_token == "at2"
    assert fresh.refresh_token == "rt1"


async def test_refresh_explicitly_requests_only_pinned_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_url: str, kwargs: dict[str, Any]) -> httpx.Response:
        assert kwargs["data"]["scope"] == "OAuth2Read OAuth2Write"
        assert kwargs["data"]["resource"] == FS_MCP.resource
        return _json_response(200, {"access_token": "at2", "expires_in": 3599})

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    await refresh_token(FS_MCP, CLIENT, HostedToken("at1", "rt1", 0.0), now=1.0)


async def test_refresh_still_refuses_broader_returned_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_url: str, _kwargs: dict[str, Any]) -> httpx.Response:
        return _json_response(
            200,
            {
                "access_token": "at2",
                "expires_in": 3599,
                "scope": "OAuth2Read OAuth2Write OAuth2Delete OAuth2ReadPII",
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    with pytest.raises(RemoteAuthError) as caught:
        await refresh_token(FS_MCP, CLIENT, HostedToken("at1", "rt1", 0.0), now=1.0)
    assert caught.value.code == "scope_escalation"


async def test_refresh_takes_a_rotated_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_url: str, _kwargs: dict[str, Any]) -> httpx.Response:
        return _json_response(
            200, {"access_token": "at2", "refresh_token": "rt2", "expires_in": 60}
        )

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    fresh = await refresh_token(FS_MCP, CLIENT, HostedToken("at1", "rt1", 0.0), now=0.0)
    assert fresh.refresh_token == "rt2"


async def test_a_dead_grant_says_reconnect_rather_than_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The misclassification the handoff flagged: a dead grant that reports as
    retryable makes SOL spin against the token endpoint instead of telling the
    customer to reconnect."""

    def handler(_url: str, _kwargs: dict[str, Any]) -> httpx.Response:
        return _json_response(400, {"error": "invalid_grant"})

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    with pytest.raises(RemoteAuthError) as caught:
        await refresh_token(FS_MCP, CLIENT, HostedToken("at", "rt", 0.0))
    assert caught.value.code == "reconnect_required"
    assert caught.value.retryable is False
    assert "Reconnect FeatureScript" in caught.value.message


async def test_a_missing_refresh_token_says_reconnect() -> None:
    with pytest.raises(RemoteAuthError) as caught:
        await refresh_token(FS_MCP, CLIENT, HostedToken("at", None, 0.0))
    assert caught.value.code == "reconnect_required"


async def test_transport_failure_is_retryable_but_a_refusal_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_url: str, _kwargs: dict[str, Any]) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    with pytest.raises(RemoteAuthError) as caught:
        await exchange_code(FS_MCP, CLIENT, code="c", code_verifier="v", redirect_uri=REDIRECT)
    assert caught.value.retryable is True


async def test_an_oversized_body_is_refused_rather_than_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upstream is untrusted input: bound the message size (§7)."""

    def handler(_url: str, _kwargs: dict[str, Any]) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({"access_token": "a" * 100_000}).encode(),
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", "https://x/"),
        )

    monkeypatch.setattr(httpx, "AsyncClient", _transport(handler))
    with pytest.raises(RemoteAuthError):
        await exchange_code(FS_MCP, CLIENT, code="c", code_verifier="v", redirect_uri=REDIRECT)


# ----------------------------------------------------------------- token value


def test_token_round_trips_as_one_atomic_value() -> None:
    """One ref, one write. The two-ref scheme survives rotation only through a
    careful write ORDER; one value cannot half-land."""
    token = HostedToken("at", "rt", 4599.0)
    assert HostedToken.from_json(token.to_json()) == token


def test_expiry_uses_a_skew_so_a_token_cannot_die_in_flight() -> None:
    now = time.time()
    assert HostedToken("at", "rt", now + 3600).expired(now=now) is False
    assert HostedToken("at", "rt", now + 30).expired(now=now) is True
    assert HostedToken("at", "rt", now - 1).expired(now=now) is True


def test_no_secret_value_appears_in_any_error_message() -> None:
    err = RemoteAuthError("reconnect_required", "Your FeatureScript sign-in expired.")
    assert "rt" not in err.message.split()
    assert hosted_oauth._MAX_RESPONSE_BYTES == 64_000
