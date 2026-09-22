"""OAuth for vendor-hosted MCP servers, on behalf of the CUSTOMER (SOLUSDEV-168).

The same two-legged authorization-code dance `OnshapeConnector` already runs,
against endpoints PINNED in `RemoteMCPSpec` rather than a provider class — so the
next hosted server is a registry entry, not another connector.

**Why this is hand-rolled rather than delegated to the MCP SDK.** The SDK ships
`OAuthClientProvider` (`mcp/client/auth/oauth2.py:217`) which does DCR + PKCE +
refresh, and the obvious move is to use it. Three findings say otherwise:

1. **It cannot span our redirect.** `_perform_authorization_code_grant`
   (`oauth2.py:317`) generates the PKCE verifier as a COROUTINE LOCAL (`:336`),
   awaits `callback_handler()` in the same frame (`:359`) and returns the
   verifier up the stack (`:368`). It never touches `TokenStorage`. Our
   authorization code arrives on a different request entirely, so the coroutine
   that minted the verifier is gone. There is no setter and no subclass seam.
2. **It would escalate our scopes.** On every 401 it rewrites
   `client_metadata.scope` from the resource's advertised `scopes_supported`
   (`auth/utils.py:119-121`, applied `oauth2.py:565-569`). fs-mcp advertises
   `OAuth2Delete` and `OAuth2ReadPII`, which are forbidden on the record.
3. **Its discovery is an SSRF + AS-substitution primitive.** It fetches the URL
   read verbatim from the server's own `WWW-Authenticate` header and then trusts
   that document's `authorization_servers[0]` (`oauth2.py:518-528`,
   `utils.py:52-62`) — letting the vendor point DCR, the customer's browser and
   the token exchange at a host of its choosing.

We do reuse the SDK's PKCE generator, which is just RFC 7636 arithmetic.

**Tokens are one JSON value under one ref.** The connector path stores access and
refresh under two refs and survives Onshape's rotate-on-every-use only by writing
them in a careful order (`connectors/runtime.py:344-351`). One value is written
atomically instead, so two concurrent refreshes can never leave a live access
token beside a dead refresh token.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from mcp.client.auth.oauth2 import PKCEParameters

from solus_api.agent.tools.remote_mcp import RemoteAuthError, RemoteMCPSpec
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore

logger = logging.getLogger("solus.connectors.hosted_oauth")

_REQUEST_TIMEOUT = httpx.Timeout(15.0)
#: Refresh this many seconds before the server's own expiry, so a token cannot
#: die in flight between our check and the vendor's clock.
_EXPIRY_SKEW_SECONDS = 60.0
#: fs-mcp's DCR response is small; anything larger is not a client registration.
_MAX_RESPONSE_BYTES = 64_000

#: The redirect a hosted server's DCR client is registered with, and the ONLY
#: one it will accept. Must equal the desktop's `connectorRedirectUrl()`
#: (`apps/desktop/src/main/oauthCallback.ts:39-41`) byte for byte: strict
#: providers match the registered URI exactly, and DCR bakes it into the
#: registration, so a mismatch is not a failed call — it is a re-registration.
#: The desktop already binds this loopback and captures the code there, which
#: is why completion goes through the AUTHENTICATED exchange route: the
#: existing web callback (`integrations.py:251-280`) never checks
#: `record.user_id`, and with OAuth2Write that is an account-linking CSRF that
#: writes FeatureScript into the victim's Feature Studios.
LOOPBACK_REDIRECT_URI = "http://localhost:53682/auth/callback"


def registered_redirect_uri(spec: RemoteMCPSpec) -> str:
    """Where this hosted server sends the authorization code back."""
    del spec  # one redirect for every hosted server today; kept per-spec-shaped
    return LOOPBACK_REDIRECT_URI


def client_secret_ref(server: str) -> str:
    """Where the SHARED Solus DCR client lives.

    Solus-wide, NOT per user: the *client* is Solus and the *tokens* are the
    customer's — the same split the existing Onshape OAuth app has. Keyed per
    server so two hosted vendors never read each other's registration.
    """
    return f"hosted-mcp/{server}/client"


def token_secret_ref(source_secret_ref: str, server: str) -> str:
    """Where ONE customer's grant for ONE hosted server lives.

    Derived from the authoritative account connection ref for account-backed
    Sources, or the legacy Source ref. It inherits that owner's DELETION: `disconnect_source` and
    `delete_projects_cascade` both sweep from `Source.secret_ref`, and a
    credential family they cannot derive is a live OAuth2Write grant that
    outlives the customer revoking us (the bug `mcp-license/{team_id}/…` already
    has). `hosted_refs` below is what those sweeps iterate.
    """
    return f"{source_secret_ref}/hosted/{server}"


def hosted_refs(source_secret_ref: str) -> list[str]:
    """Every hosted-server credential ref derived from one Source. For sweeps."""
    from solus_api.agent.tools.remote_mcp import HOSTED_SERVERS

    return [token_secret_ref(source_secret_ref, name) for name in HOSTED_SERVERS]


@dataclass(frozen=True)
class HostedClient:
    """The Solus DCR registration for one hosted server."""

    client_id: str
    client_secret: str | None


@dataclass(frozen=True)
class HostedToken:
    """One customer's grant. Serialized whole, written atomically."""

    access_token: str
    refresh_token: str | None
    expires_at: float

    def expired(self, *, now: float) -> bool:
        return now >= self.expires_at - _EXPIRY_SKEW_SECONDS

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_at": self.expires_at,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> HostedToken:
        data = json.loads(raw)
        return cls(
            access_token=str(data["access_token"]),
            refresh_token=data.get("refresh_token"),
            expires_at=float(data.get("expires_at", 0.0)),
        )


def _fail(code: str, message: str, *, retryable: bool = False) -> RemoteAuthError:
    return RemoteAuthError(code, message, retryable=retryable)


def _body(response: httpx.Response, *, code: str) -> dict[str, Any]:
    """Parse a small JSON body, or refuse. Upstream text is never echoed."""
    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise _fail(code, "the FeatureScript service returned an unexpected response")
    try:
        data = response.json()
    except ValueError as exc:
        raise _fail(code, "the FeatureScript service returned an unexpected response") from exc
    if not isinstance(data, dict):
        raise _fail(code, "the FeatureScript service returned an unexpected response")
    return data


def _granted_scopes(data: dict[str, Any], spec: RemoteMCPSpec) -> frozenset[str]:
    """What the server says it granted. Absent means 'as requested' (RFC 6749)."""
    raw = data.get("scope")
    if not isinstance(raw, str) or not raw.strip():
        return frozenset(spec.scopes)
    return frozenset(raw.split())


def _refuse_escalation(granted: frozenset[str], spec: RemoteMCPSpec) -> None:
    """STOP AND ESCALATE, mechanically.

    The approved decision pins this client to Read + Write and says to stop if
    the server ever insists on `OAuth2Delete` or `OAuth2ReadPII`. A grant wider
    than we asked for is exactly that, and storing it would leave a delete-capable
    token on a customer's documents that no one decided to accept.
    """
    extra = granted - frozenset(spec.scopes)
    if extra:
        logger.error(
            "hosted server %r granted scopes beyond the pinned set: %s",
            spec.name,
            ",".join(sorted(extra)),
        )
        raise _fail(
            "scope_escalation",
            "Onshape granted more access than Solus asked for, so the connection "
            "was refused and nothing was saved. Tell the Solus team — this needs "
            "a human decision before FeatureScript can be enabled.",
        )


async def _post(url: str, *, data: dict[str, str], code: str) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            return await client.post(url, data=data)
    except httpx.HTTPError as exc:
        raise _fail(
            code,
            "Could not reach the Onshape FeatureScript service. Try again in a moment.",
            retryable=True,
        ) from exc


# ---------------------------------------------------------------- registration


async def ensure_client(
    store: SecretStore, spec: RemoteMCPSpec, *, redirect_uri: str
) -> HostedClient:
    """The shared Solus DCR client, registering once and caching it.

    Registration is Solus-wide, so a per-customer connect must never re-register:
    the SDK's habit of registering whenever it holds no client info is what
    leaves stray clients on a vendor's side (the spike already left one).
    """
    ref = client_secret_ref(spec.name)
    try:
        stored = json.loads(await store.get(ref))
        return HostedClient(
            client_id=str(stored["client_id"]), client_secret=stored.get("client_secret")
        )
    except SecretNotFoundError:
        pass
    except (ValueError, KeyError):
        logger.warning("stored DCR client for %r is unreadable; re-registering", spec.name)

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.post(
                spec.register_url,
                json={
                    "client_name": "Solus",
                    "redirect_uris": [redirect_uri],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "client_secret_post",
                    # Pinned. Never derived from what the server advertises.
                    "scope": " ".join(spec.scopes),
                },
            )
    except httpx.HTTPError as exc:
        raise _fail(
            "registration_unreachable",
            "Could not reach the Onshape FeatureScript service to set up the connection.",
            retryable=True,
        ) from exc
    if response.status_code >= 400:
        raise _fail(
            "registration_failed",
            f"The Onshape FeatureScript service refused Solus's registration "
            f"({response.status_code}).",
        )
    data = _body(response, code="registration_failed")
    client_id = data.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise _fail("registration_failed", "The FeatureScript service issued no client id.")
    _refuse_escalation(_granted_scopes(data, spec), spec)
    secret = data.get("client_secret")
    record = HostedClient(
        client_id=client_id, client_secret=secret if isinstance(secret, str) else None
    )
    await store.put(
        ref, json.dumps({"client_id": record.client_id, "client_secret": record.client_secret})
    )
    logger.info("registered Solus as a DCR client with hosted server %r", spec.name)
    return record


# ------------------------------------------------------------------ authorize


def new_pkce() -> tuple[str, str]:
    """`(code_verifier, code_challenge)` — RFC 7636 S256, from the MCP SDK."""
    params = PKCEParameters.generate()
    return params.code_verifier, params.code_challenge


def authorize_url(
    spec: RemoteMCPSpec,
    client: HostedClient,
    *,
    state: str,
    code_challenge: str,
    redirect_uri: str,
) -> str:
    """The URL the customer's browser opens. Scopes are ours, never the server's."""
    from urllib.parse import urlencode

    return f"{spec.authorize_url}?" + urlencode(
        {
            "response_type": "code",
            "client_id": client.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": " ".join(spec.scopes),
        }
    )


# -------------------------------------------------------------------- tokens


def _token_from(data: dict[str, Any], spec: RemoteMCPSpec, *, now: float) -> HostedToken:
    _refuse_escalation(_granted_scopes(data, spec), spec)
    access = data.get("access_token")
    if not isinstance(access, str) or not access:
        raise _fail("token_failed", "The FeatureScript service returned no access token.")
    try:
        lifetime = float(data.get("expires_in", 0) or 0)
    except (TypeError, ValueError):
        lifetime = 0.0
    refresh = data.get("refresh_token")
    return HostedToken(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_at=now + lifetime,
    )


def _client_form(client: HostedClient) -> dict[str, str]:
    form = {"client_id": client.client_id}
    if client.client_secret:
        form["client_secret"] = client.client_secret
    return form


async def exchange_code(
    spec: RemoteMCPSpec,
    client: HostedClient,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    now: float | None = None,
) -> HostedToken:
    response = await _post(
        spec.token_url,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            **_client_form(client),
        },
        code="token_unreachable",
    )
    if response.status_code >= 400:
        raise _fail(
            "token_failed",
            f"Onshape refused the FeatureScript sign-in ({response.status_code}). "
            "Start the connection again.",
        )
    return _token_from(_body(response, code="token_failed"), spec, now=now or time.time())


async def refresh_token(
    spec: RemoteMCPSpec,
    client: HostedClient,
    token: HostedToken,
    *,
    now: float | None = None,
) -> HostedToken:
    if not token.refresh_token:
        raise _fail(
            "reconnect_required",
            "Your FeatureScript sign-in expired. Reconnect FeatureScript on the "
            "Onshape source to keep using it.",
        )
    response = await _post(
        spec.token_url,
        data={
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
            "scope": " ".join(spec.scopes),
            **_client_form(client),
        },
        code="token_unreachable",
    )
    if response.status_code >= 400:
        raise _fail(
            "reconnect_required",
            "Your FeatureScript sign-in expired. Reconnect FeatureScript on the "
            "Onshape source to keep using it.",
        )
    fresh = _token_from(_body(response, code="reconnect_required"), spec, now=now or time.time())
    # A server that rotates its refresh token has already killed the old one; a
    # server that does not returns nothing here and the existing one stays valid.
    if fresh.refresh_token is None:
        fresh = HostedToken(
            access_token=fresh.access_token,
            refresh_token=token.refresh_token,
            expires_at=fresh.expires_at,
        )
    return fresh


__all__ = [
    "HostedClient",
    "HostedToken",
    "authorize_url",
    "client_secret_ref",
    "ensure_client",
    "exchange_code",
    "hosted_refs",
    "new_pkce",
    "refresh_token",
    "token_secret_ref",
]
