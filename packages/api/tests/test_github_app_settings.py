"""GitHub App settings: configured gate, private key sources, secret redaction."""

from pathlib import Path
from typing import Any

import pytest
from solus_api.core.config import Settings

PEM_BODY = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAK\n-----END RSA PRIVATE KEY-----\n"
SECRETS = ("client-secret-value", "webhook-secret-value", "MIIBOgIBAAJBAK")


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "github_app_id": "123456",
        "github_app_slug": "solus-dev",
        "github_app_client_id": "Iv23liabc",
        "github_app_client_secret": "client-secret-value",
        "github_app_private_key": PEM_BODY,
        "github_app_webhook_secret": "webhook-secret-value",
    }
    base.update(overrides)
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        supabase_jwt_secret="dummy-jwt-signing-value-tests-only",
        database_url="sqlite+aiosqlite://",
        **base,
    )


def test_fully_configured() -> None:
    assert _settings().github_app_configured is True


def test_unconfigured_by_default() -> None:
    plain = Settings(
        _env_file=None,  # type: ignore[call-arg]
        supabase_jwt_secret="dummy-jwt-signing-value-tests-only",
        database_url="sqlite+aiosqlite://",
    )
    assert plain.github_app_configured is False


@pytest.mark.parametrize(
    "missing",
    [
        "github_app_id",
        "github_app_slug",
        "github_app_client_id",
        "github_app_client_secret",
        "github_app_private_key",
        "github_app_webhook_secret",
    ],
)
def test_missing_any_required_setting_means_unconfigured(missing: str) -> None:
    assert _settings(**{missing: None}).github_app_configured is False


def test_empty_string_counts_as_missing() -> None:
    assert _settings(github_app_slug="").github_app_configured is False


def test_private_key_path_variant(tmp_path: Path) -> None:
    key = tmp_path / "app.pem"
    key.write_text(PEM_BODY)
    s = _settings(github_app_private_key=None, github_app_private_key_path=str(key))
    assert s.github_app_configured is True
    assert s.github_app_private_key_pem == PEM_BODY


def test_missing_key_file_means_unconfigured(tmp_path: Path) -> None:
    s = _settings(
        github_app_private_key=None, github_app_private_key_path=str(tmp_path / "nope.pem")
    )
    assert s.github_app_configured is False


def test_inline_key_wins_over_path(tmp_path: Path) -> None:
    key = tmp_path / "app.pem"
    key.write_text("other")
    s = _settings(github_app_private_key_path=str(key))
    assert s.github_app_private_key_pem == PEM_BODY


def test_escaped_newlines_are_normalised() -> None:
    s = _settings(github_app_private_key=PEM_BODY.replace("\n", "\\n"))
    assert s.github_app_private_key_pem == PEM_BODY


def test_secrets_never_appear_in_repr_or_str() -> None:
    s = _settings()
    for text in (repr(s), str(s)):
        for secret in SECRETS:
            assert secret not in text
