"""GitHub App support for team-owned installations (SOLUSDEV-216, ADR-039).

Skeleton: holds the process-wide App settings. JWT signing and installation-token
minting are added by the next task.
"""

from solus_api.core.config import Settings

_settings: Settings | None = None


def configure_github_app(settings: Settings) -> None:
    """Store the settings the App client reads (called at API and worker startup)."""
    global _settings
    _settings = settings


def is_configured() -> bool:
    """True when every GitHub App credential is present."""
    return _settings is not None and _settings.github_app_configured
