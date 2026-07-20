"""JWT validation (ADR-009) — unit tests for token decoding.

Covers both signing schemes Supabase can use: the legacy HS256 shared secret and
the modern per-project ES256 asymmetric keys (published at the project JWKS
endpoint). SOLUSDEV-152: real projects issue ES256 access tokens, so the API must
verify them via JWKS — HS256-only validation rejected every real login (401).
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from conftest import TEST_AUDIENCE, TEST_JWT_SECRET, make_token
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.core.security import decode_token

SUPABASE_URL = "https://proj.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
KID = "test-signing-key"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        supabase_url=SUPABASE_URL,
        database_url="sqlite+aiosqlite://",
    )


# --- HS256 (legacy shared secret) -------------------------------------------


def test_decode_valid_token(settings: Settings) -> None:
    token = make_token("user-sub-1", "a@example.com")
    claims = decode_token(token, settings)
    assert claims.sub == "user-sub-1"
    assert claims.email == "a@example.com"


def test_decode_rejects_bad_signature(settings: Settings) -> None:
    token = make_token("user-sub-1", "a@example.com", secret="dummy-wrong-signing-value")
    with pytest.raises(APIError) as exc:
        decode_token(token, settings)
    assert exc.value.status_code == 401


def test_decode_rejects_expired(settings: Settings) -> None:
    token = make_token("user-sub-1", "a@example.com", expires_in=-60)
    with pytest.raises(APIError) as exc:
        decode_token(token, settings)
    assert exc.value.status_code == 401


def test_decode_rejects_wrong_audience(settings: Settings) -> None:
    token = make_token("user-sub-1", "a@example.com", audience="other")
    with pytest.raises(APIError) as exc:
        decode_token(token, settings)
    assert exc.value.status_code == 401


def test_decode_rejects_garbage(settings: Settings) -> None:
    with pytest.raises(APIError) as exc:
        decode_token("not-a-jwt", settings)
    assert exc.value.status_code == 401


def test_decode_requires_sub(settings: Settings) -> None:
    token = pyjwt.encode({"aud": TEST_AUDIENCE}, TEST_JWT_SECRET, algorithm="HS256")
    with pytest.raises(APIError) as exc:
        decode_token(token, settings)
    assert exc.value.status_code == 401


# --- ES256 (asymmetric, via JWKS) -------------------------------------------


class _StaticJwksClient:
    """A network-free stand-in for jwt.PyJWKClient that resolves a token's signing
    key from a fixed JWK by matching the token's `kid` (raises like the real one
    on an unknown kid, so unknown-key paths are exercised)."""

    def __init__(self, jwk: dict[str, Any]) -> None:
        self._by_kid = {jwk["kid"]: pyjwt.PyJWK.from_dict(jwk)}

    def get_signing_key_from_jwt(self, token: str) -> pyjwt.PyJWK:
        kid = pyjwt.get_unverified_header(token).get("kid")
        if kid not in self._by_kid:
            raise pyjwt.PyJWKClientError(f"no key for kid {kid!r}")
        return self._by_kid[kid]


def _es256_keypair(kid: str = KID) -> tuple[ec.EllipticCurvePrivateKey, dict[str, Any]]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(ECAlgorithm.to_jwk(private_key.public_key()))
    jwk.update(kid=kid, use="sig", alg="ES256")
    return private_key, jwk


def _es256_token(
    private_key: ec.EllipticCurvePrivateKey,
    *,
    sub: str = "es-user-1",
    audience: str = TEST_AUDIENCE,
    issuer: str = ISSUER,
    expires_in: int = 3600,
    kid: str = KID,
) -> str:
    payload = {
        "sub": sub,
        "email": "es@example.com",
        "aud": audience,
        "iss": issuer,
        "exp": datetime.now(UTC) + timedelta(seconds=expires_in),
    }
    return pyjwt.encode(payload, private_key, algorithm="ES256", headers={"kid": kid})


def test_decode_valid_es256_token_via_jwks(settings: Settings) -> None:
    private_key, jwk = _es256_keypair()
    token = _es256_token(private_key)
    claims = decode_token(token, settings, _StaticJwksClient(jwk))
    assert claims.sub == "es-user-1"
    assert claims.email == "es@example.com"


def test_es256_rejected_when_no_jwks_client(settings: Settings) -> None:
    private_key, _ = _es256_keypair()
    token = _es256_token(private_key)
    with pytest.raises(APIError) as exc:
        decode_token(token, settings, None)
    assert exc.value.status_code == 401


def test_es256_rejects_unknown_kid(settings: Settings) -> None:
    signing_key, _ = _es256_keypair(kid="attacker-kid")
    _, published_jwk = _es256_keypair(kid="real-kid")
    token = _es256_token(signing_key, kid="attacker-kid")
    with pytest.raises(APIError) as exc:
        decode_token(token, settings, _StaticJwksClient(published_jwk))
    assert exc.value.status_code == 401


def test_es256_rejects_wrong_issuer(settings: Settings) -> None:
    private_key, jwk = _es256_keypair()
    token = _es256_token(private_key, issuer="https://evil.supabase.co/auth/v1")
    with pytest.raises(APIError) as exc:
        decode_token(token, settings, _StaticJwksClient(jwk))
    assert exc.value.status_code == 401


def test_es256_rejects_expired(settings: Settings) -> None:
    private_key, jwk = _es256_keypair()
    token = _es256_token(private_key, expires_in=-60)
    with pytest.raises(APIError) as exc:
        decode_token(token, settings, _StaticJwksClient(jwk))
    assert exc.value.status_code == 401


def test_es256_rejects_signature_from_other_key(settings: Settings) -> None:
    signing_key, _ = _es256_keypair()
    _, published_jwk = _es256_keypair()  # different key, SAME kid
    token = _es256_token(signing_key)
    with pytest.raises(APIError) as exc:
        decode_token(token, settings, _StaticJwksClient(published_jwk))
    assert exc.value.status_code == 401
