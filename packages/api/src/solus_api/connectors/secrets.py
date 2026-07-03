"""Pluggable secret store for connector credentials (CLAUDE.md §7).

Credentials (users' GitHub/OAuth tokens) are encrypted at rest, never logged,
never returned by any API response. The store is addressed by an opaque `ref`
held on the Source row; the secret material lives only here.

Backends:
- AwsSecretsManagerStore — production (ADR-006). Secrets Manager encrypts at rest.
- LocalEncryptedSecretStore — dev. Fernet-encrypts into the DB; key from env.
- InMemorySecretStore — last-resort dev fallback (lost on restart; warns).
"""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.models import ConnectorSecret

if TYPE_CHECKING:
    from solus_api.core.config import Settings

logger = logging.getLogger("solus.connectors.secrets")


class SecretNotFoundError(KeyError):
    """No secret stored under the given ref."""


class SecretStore(abc.ABC):
    """Opaque ref → secret value. Implementations encrypt at rest."""

    @abc.abstractmethod
    async def put(self, ref: str, value: str) -> None: ...

    @abc.abstractmethod
    async def get(self, ref: str) -> str:
        """Return the secret, or raise SecretNotFoundError."""

    @abc.abstractmethod
    async def delete(self, ref: str) -> None:
        """Remove the secret; a no-op if absent."""


class InMemorySecretStore(SecretStore):
    """Process-local, unencrypted. Tests and bare dev only — never shared/prod."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def put(self, ref: str, value: str) -> None:
        self._store[ref] = value

    async def get(self, ref: str) -> str:
        try:
            return self._store[ref]
        except KeyError as exc:
            raise SecretNotFoundError(ref) from exc

    async def delete(self, ref: str) -> None:
        self._store.pop(ref, None)


class LocalEncryptedSecretStore(SecretStore):
    """Fernet-encrypts secrets into the connector_secrets table (dev)."""

    def __init__(self, fernet: Fernet, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._fernet = fernet
        self._sessionmaker = sessionmaker

    async def put(self, ref: str, value: str) -> None:
        ciphertext = self._fernet.encrypt(value.encode()).decode()
        async with self._sessionmaker() as session:
            row = await session.get(ConnectorSecret, ref)
            if row is None:
                session.add(ConnectorSecret(ref=ref, ciphertext=ciphertext))
            else:
                row.ciphertext = ciphertext
            await session.commit()

    async def get(self, ref: str) -> str:
        async with self._sessionmaker() as session:
            row = await session.get(ConnectorSecret, ref)
        if row is None:
            raise SecretNotFoundError(ref)
        return self._fernet.decrypt(row.ciphertext.encode()).decode()

    async def delete(self, ref: str) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(ConnectorSecret, ref)
            if row is not None:
                await session.delete(row)
                await session.commit()


class AwsSecretsManagerStore(SecretStore):
    """AWS Secrets Manager backend (production). boto3 is sync, so each call is
    offloaded to a thread to keep the event loop free."""

    def __init__(self, region: str, prefix: str = "solus/connectors/") -> None:
        import boto3  # lazy — only prod needs the SDK / AWS creds

        self._client = boto3.client("secretsmanager", region_name=region)
        self._prefix = prefix

    def _name(self, ref: str) -> str:
        return f"{self._prefix}{ref}"

    async def put(self, ref: str, value: str) -> None:
        await asyncio.to_thread(self._put_sync, self._name(ref), value)

    def _put_sync(self, name: str, value: str) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.create_secret(Name=name, SecretString=value)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceExistsException":
                self._client.put_secret_value(SecretId=name, SecretString=value)
            else:
                raise

    async def get(self, ref: str) -> str:
        from botocore.exceptions import ClientError

        try:
            resp = await asyncio.to_thread(self._client.get_secret_value, SecretId=self._name(ref))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                raise SecretNotFoundError(ref) from exc
            raise
        secret: str = resp["SecretString"]
        return secret

    async def delete(self, ref: str) -> None:
        from botocore.exceptions import ClientError

        try:
            await asyncio.to_thread(
                self._client.delete_secret,
                SecretId=self._name(ref),
                ForceDeleteWithoutRecovery=True,
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise


def build_secret_store(
    settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]
) -> SecretStore:
    """Select a backend from settings (explicit `secrets_backend` wins)."""
    backend = settings.secrets_backend
    if backend == "aws" or (backend is None and settings.aws_region and settings.app_env != "dev"):
        if not settings.aws_region:
            raise RuntimeError("secrets_backend=aws requires SOLUS_AWS_REGION")
        return AwsSecretsManagerStore(settings.aws_region)
    if backend == "local" or (backend is None and settings.secrets_key):
        if not settings.secrets_key:
            raise RuntimeError("secrets_backend=local requires SOLUS_SECRETS_KEY")
        return LocalEncryptedSecretStore(Fernet(settings.secrets_key.encode()), sessionmaker)
    # No encrypted backend configured. Tolerated only in dev (in-memory, tokens
    # lost on restart). Anywhere else this is an existential misconfiguration —
    # fail fast rather than store credentials in plaintext process memory (§7).
    if settings.app_env != "dev":
        raise RuntimeError(
            "No secret store configured: set SOLUS_AWS_REGION (prod) or "
            "SOLUS_SECRETS_KEY (local). Refusing to use the in-memory store "
            f"in app_env={settings.app_env!r}."
        )
    logger.warning(
        "No secret store configured (SOLUS_SECRETS_KEY / SOLUS_AWS_REGION unset) — "
        "using in-memory store. Tokens are lost on restart. Dev only."
    )
    return InMemorySecretStore()
