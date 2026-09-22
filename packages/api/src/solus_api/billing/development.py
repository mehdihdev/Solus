"""Explicit development-only admission exception; accounting is never bypassed."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.config import Settings

SESSION_SETTINGS_KEY = "solus_application_settings"


def is_development_unlimited(user_id: uuid.UUID, settings: Settings | None) -> bool:
    """Only the server's resolved dev configuration can grant this exception."""
    return (
        isinstance(settings, Settings)
        and settings.app_env == "dev"
        and user_id in settings.development_unlimited_credit_user_id_set
    )


def session_development_unlimited(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Session factory injection keeps apps isolated; absent settings fail closed."""
    return is_development_unlimited(user_id, session.info.get(SESSION_SETTINGS_KEY))
