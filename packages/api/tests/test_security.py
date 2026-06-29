"""JWT validation (ADR-009) — unit tests for token decoding."""

import pytest
from conftest import TEST_AUDIENCE, TEST_JWT_SECRET, make_token
from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.core.security import decode_token


@pytest.fixture
def settings() -> Settings:
    return Settings(
        supabase_jwt_secret=TEST_JWT_SECRET,
        supabase_jwt_audience=TEST_AUDIENCE,
        database_url="sqlite+aiosqlite://",
    )


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
    import jwt as pyjwt

    token = pyjwt.encode({"aud": TEST_AUDIENCE}, TEST_JWT_SECRET, algorithm="HS256")
    with pytest.raises(APIError) as exc:
        decode_token(token, settings)
    assert exc.value.status_code == 401
