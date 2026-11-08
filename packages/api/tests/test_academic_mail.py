"""Academic verification mailer (ADR-042): SES call shape, dev fallback, no sender."""

import logging
from typing import Any

import pytest
from solus_api.core.config import Settings
from solus_api.services.academic_mail import (
    DevLogMailer,
    SesAcademicMailer,
    build_academic_mailer,
)


class FakeSes:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_email(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(kwargs)
        return {"MessageId": "m-1"}


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, supabase_jwt_secret="test-only", **kw)  # type: ignore[call-arg]


async def test_ses_sends_the_code_to_the_address_only() -> None:
    ses = FakeSes()
    await SesAcademicMailer("Solus <verify@solusforge.com>", "us-east-1", ses).send_code(
        "ada@mit.edu", "042917"
    )
    (call,) = ses.calls
    assert call["FromEmailAddress"] == "Solus <verify@solusforge.com>"
    assert call["Destination"] == {"ToAddresses": ["ada@mit.edu"]}
    simple = call["Content"]["Simple"]
    assert "042917" in simple["Body"]["Text"]["Data"]
    assert "ada@mit.edu" not in simple["Body"]["Text"]["Data"]
    assert "042917" not in simple["Subject"]["Data"]


async def test_ses_errors_propagate() -> None:
    class Boom(FakeSes):
        def send_email(self, **kwargs: Any) -> dict[str, str]:
            raise RuntimeError("throttled")

    with pytest.raises(RuntimeError):
        await SesAcademicMailer("a@b.c", None, Boom()).send_code("ada@mit.edu", "1")


def test_sender_configured_builds_ses() -> None:
    mailer = build_academic_mailer(_settings(academic_email_sender="verify@solusforge.com"))
    assert isinstance(mailer, SesAcademicMailer)


@pytest.mark.parametrize("env", ["production", "staging"])
def test_no_sender_outside_dev_builds_nothing(env: str) -> None:
    assert build_academic_mailer(_settings(app_env=env)) is None


async def test_dev_without_sender_logs_the_code(caplog: pytest.LogCaptureFixture) -> None:
    mailer = build_academic_mailer(_settings(app_env="dev"))
    assert isinstance(mailer, DevLogMailer)
    with caplog.at_level(logging.WARNING, logger="solus.billing.academic_mail"):
        await mailer.send_code("ada@mit.edu", "123456")
    assert "123456" in caplog.text
