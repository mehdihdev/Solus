"""Boot-time report of the SecretStore refs SOL needs (SOLUSDEV-252).

Provider keys are SecretStore refs, not env vars, so a fresh database has none
of them and the first SOL turn fails with ProviderCredentialsMissingError —
which reads like a code bug. This logs the missing refs by NAME at startup so
the fix (`make seed-secrets`) is visible before anyone sends a message.
Never raises; never logs a value.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from solus_api.agent.tools.mcp_servers import WEB_SEARCH
from solus_api.connectors.secrets import SecretStore
from solus_api.core.config import Settings
from solus_api.orchestration.providers import (
    ANTHROPIC_API_KEY_NAME,
    GOOGLE_API_KEY_NAME,
    OPENAI_API_KEY_NAME,
)

logger = logging.getLogger("solus.core.startup_checks")

EXPECTED_REFS: frozenset[str] = frozenset(
    {ANTHROPIC_API_KEY_NAME, OPENAI_API_KEY_NAME, GOOGLE_API_KEY_NAME}
    | set(WEB_SEARCH.required_secrets)
)


@dataclass(frozen=True)
class ProviderRefReport:
    present: tuple[str, ...]
    missing: tuple[str, ...]
    onshape_pair_configured: bool


async def report_provider_refs(store: SecretStore, settings: Settings) -> ProviderRefReport:
    """Probe every expected ref; a store error counts as missing (never raises)."""
    present: list[str] = []
    missing: list[str] = []
    for ref in sorted(EXPECTED_REFS):
        try:
            await store.get(ref)
        except Exception:  # noqa: BLE001 — SecretNotFoundError or a dead backend; both "missing"
            missing.append(ref)
        else:
            present.append(ref)
    for ref in missing:
        # ponytail: provider name derived from the ref; brave is the web_search tool, same fix
        logger.warning(
            "SecretStore ref '%s' missing — SOL turns on %s will fail with "
            "ProviderCredentialsMissingError; run `make seed-secrets`",
            ref,
            ref.removesuffix("_api_key"),
        )
    logger.info("SecretStore provider refs present: %s", ", ".join(present) or "none")
    return ProviderRefReport(
        present=tuple(present),
        missing=tuple(missing),
        onshape_pair_configured=bool(settings.onshape_client_id and settings.onshape_client_secret),
    )
