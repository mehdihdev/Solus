"""Supabase Auth JWT validation (ADR-009, API.md §1.2)."""

from dataclasses import dataclass

import jwt

from solus_api.core.config import Settings
from solus_api.core.errors import APIError


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


def decode_token(token: str, settings: Settings) -> TokenClaims:
    """Validate a Supabase JWT and extract identity claims.

    Raises APIError(401) on any validation failure; the reason is logged by
    the error handler, never leaked to the client beyond the generic message.
    """
    try:
        # Signature IS cryptographically verified here (HMAC-SHA256 against the
        # shared secret; `algorithms` pinned blocks alg-confusion) and exp+aud are
        # checked. Hardening deferred (tracked on ADR-009): migrate to Supabase
        # JWKS/RS256 asymmetric verification and add an issuer check.
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience=settings.supabase_jwt_audience,
        )
    except jwt.InvalidTokenError as exc:
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
