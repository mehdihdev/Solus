"""Sends the Academic plan's verification code (ADR-042, SOLUSDEV-319).

`AcademicMailer` is the seam: the route depends on it and tests inject a fake.
Production uses AWS SES with the task's IAM role (no key in config). With no sender
configured, `app_env=dev` with no AWS region falls back to a logging mailer so the flow
can be exercised locally; every other environment gets no mailer and the route answers 503.

The message body is Solus-authored only: the code and fixed copy. The recipient address
is the only user-influenced value and goes in the SES Destination, never into the text.
"""

import asyncio
import logging
from typing import Any, Protocol

from solus_api.core.config import Settings

logger = logging.getLogger("solus.billing.academic_mail")

SUBJECT = "Your Solus academic verification code"


def _body(code: str) -> str:
    return (
        f"Your Solus verification code is {code}.\n\n"
        "Enter it on the Billing page to turn on the free Academic plan. "
        "It expires in 15 minutes.\n\n"
        "If you didn't ask for this, you can ignore this email."
    )


class AcademicMailer(Protocol):
    async def send_code(self, to: str, code: str) -> None: ...


class SesAcademicMailer:
    """AWS SES v2 `SendEmail`, run off the event loop (boto3 is synchronous)."""

    def __init__(self, sender: str, region: str | None, client: Any = None) -> None:
        self._sender = sender
        self._region = region
        self._client = client

    def _ses(self) -> Any:
        if self._client is None:
            import boto3
            from botocore.config import Config

            # Short timeouts: the send runs while the caller's row lock is held.
            config = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 2})
            self._client = boto3.client("sesv2", region_name=self._region, config=config)
        return self._client

    def _send(self, to: str, code: str) -> None:
        self._ses().send_email(
            FromEmailAddress=self._sender,
            Destination={"ToAddresses": [to]},
            Content={
                "Simple": {
                    "Subject": {"Data": SUBJECT, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": _body(code), "Charset": "UTF-8"}},
                }
            },
        )

    async def send_code(self, to: str, code: str) -> None:
        await asyncio.to_thread(self._send, to, code)


class DevLogMailer:
    """Development only: logs the code instead of sending it. Never built outside dev."""

    async def send_code(self, to: str, code: str) -> None:
        logger.warning("dev: academic verification code for %s is %s (no SES sender)", to, code)


def build_academic_mailer(settings: Settings) -> AcademicMailer | None:
    """The mailer for these settings, or None when sending is not configured."""
    if settings.academic_email_sender:
        return SesAcademicMailer(settings.academic_email_sender, settings.aws_region)
    # Logging the code is only for a local machine: `app_env` defaults to "dev", so also
    # require that no AWS region is set (every deployed environment sets one for Secrets
    # Manager). A deployment that forgets APP_ENV still gets no mailer, never a log of codes.
    if settings.app_env == "dev" and not settings.aws_region:
        return DevLogMailer()
    return None
