"""Supabase Auth JWT validation (ADR-009, API.md §1.2)."""

from dataclasses import dataclass

import jwt

from solus_api.core.config import Settings
from solus_api.core.errors import APIError


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    email: str | None


def decode_token(token: str, settings: Settings) -> TokenClaims:
    """Validate a Supabase JWT and extract identity claims.

    Raises APIError(401) on any validation failure; the reason is logged by
    the error handler, never leaked to the client beyond the generic message.
    """
    try:
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
    return TokenClaims(sub=sub, email=email if isinstance(email, str) else None)
