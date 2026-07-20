"""Supabase Auth JWT validation (ADR-009, API.md §1.2).

Supabase issues access tokens under one of two signing schemes, and Solus must
verify both:

* **ES256/RS256 (asymmetric)** — modern per-project signing keys published at the
  project JWKS endpoint (``{supabase_url}/auth/v1/.well-known/jwks.json``). New
  projects issue ES256 access tokens; the key is resolved by the token's ``kid``.
* **HS256 (legacy shared secret)** — the ``supabase_jwt_secret``. Still used by
  older projects and by the test suite.

SOLUSDEV-152: real projects had migrated to ES256, so HS256-only validation
rejected every genuine login token (401) — this is the ADR-009 JWKS hardening the
prior comment tracked. Algorithms are pinned per scheme, and the HS256 path
verifies against the shared secret only (never a public key), so a token cannot
pick a weaker verifier (alg-confusion is blocked).
"""

from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from solus_api.core.config import Settings
from solus_api.core.errors import APIError

# Asymmetric algorithms verified via the project JWKS. HS256 is handled separately
# against the shared secret; pinning per path blocks algorithm-confusion attacks.
_ASYMMETRIC_ALGS = ("ES256", "RS256")


class SigningKeyResolver(Protocol):
    """The slice of ``jwt.PyJWKClient`` that :func:`decode_token` needs — resolve a
    token's signing key from the JWKS by its ``kid``. A Protocol so tests can inject
    a static, network-free resolver."""

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    email: str | None
    # Whether Supabase considers the email verified. An ABSENT claim is treated
    # as verified (SOLUSDEV-82): Supabase access tokens do not always carry it,
    # and this gate is defense-in-depth behind the frontend's email_confirmed_at
    # check — an explicit `false` engages the gate, a missing claim never blocks a
    # legitimately-verified user. Guaranteeing the claim (a Supabase access-token
    # hook) is a follow-up.
    email_verified: bool = True


def _read_email_verified(payload: dict[str, object]) -> bool:
    """Read `email_verified` from trusted, non-user-writable claims only: the top
    level, then `app_metadata`. `user_metadata` is deliberately NOT consulted — it
    is writable by the authenticated user (Supabase `updateUser({ data })`), so
    trusting it would let an unverified user flip their own gate (SOLUSDEV-82 sec
    review H1). Absent ⇒ True: Supabase's own "no session until confirmed" is the
    primary barrier and this gate is defense-in-depth; a missing claim never
    blocks a legitimately-verified user. Guaranteeing the claim via a Supabase
    access-token hook is the tracked follow-up."""
    raw = payload.get("email_verified")
    if raw is None:
        app_metadata = payload.get("app_metadata")
        if isinstance(app_metadata, dict):
            raw = app_metadata.get("email_verified")
    return True if raw is None else bool(raw)


def supabase_issuer(supabase_url: str | None) -> str | None:
    """The `iss` Supabase stamps on tokens for `supabase_url`, or None when the URL
    is unconfigured (issuer is then not verified — e.g. the HS256 test path)."""
    if not supabase_url:
        return None
    return f"{supabase_url.rstrip('/')}/auth/v1"


def build_jwks_client(settings: Settings) -> PyJWKClient | None:
    """A cached JWKS client for the project's asymmetric signing keys, or None when
    `supabase_url` is unset (asymmetric tokens then cannot be verified). Keys are
    cached in-process and refetched on rotation/expiry, so the auth path does not
    hit Supabase on every request."""
    if not settings.supabase_url:
        return None
    uri = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return PyJWKClient(uri, cache_keys=True, lifespan=300)


def _decode_asymmetric(
    token: str, settings: Settings, jwks_client: SigningKeyResolver | None
) -> dict[str, Any]:
    """Verify an ES256/RS256 token against the project JWKS. Raises APIError(401)
    when no JWKS client is configured — an asymmetric token is unverifiable then."""
    if jwks_client is None:
        raise APIError(401, "unauthorized", "Invalid or expired token")
    signing_key = jwks_client.get_signing_key_from_jwt(token).key
    issuer = supabase_issuer(settings.supabase_url)
    return jwt.decode(
        token,
        signing_key,
        algorithms=list(_ASYMMETRIC_ALGS),
        audience=settings.supabase_jwt_audience,
        issuer=issuer,
        options={"verify_iss": issuer is not None},
    )


def decode_token(
    token: str,
    settings: Settings,
    jwks_client: SigningKeyResolver | None = None,
) -> TokenClaims:
    """Validate a Supabase JWT (ES256/RS256 via JWKS, or legacy HS256) and extract
    identity claims.

    Raises APIError(401) on any validation failure; the reason is logged by the
    error handler, never leaked to the client beyond the generic message.
    """
    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.InvalidTokenError as exc:
        raise APIError(401, "unauthorized", "Invalid or expired token") from exc

    try:
        if alg in _ASYMMETRIC_ALGS:
            payload = _decode_asymmetric(token, settings, jwks_client)
        else:
            # Signature IS cryptographically verified here (HMAC-SHA256 against the
            # shared secret; `algorithms` pinned blocks alg-confusion) and exp+aud
            # are checked.
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=settings.supabase_jwt_audience,
            )
    except (jwt.InvalidTokenError, PyJWKClientError) as exc:
        raise APIError(401, "unauthorized", "Invalid or expired token") from exc

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise APIError(401, "unauthorized", "Token missing subject claim")

    email = payload.get("email")
    return TokenClaims(
        sub=sub,
        email=email if isinstance(email, str) else None,
        email_verified=_read_email_verified(payload),
    )
