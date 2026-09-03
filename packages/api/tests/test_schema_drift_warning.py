"""The dev-only guard that says when the database is behind the models.

`create_all` creates missing TABLES and silently does nothing about missing
COLUMNS on tables that already exist. So a dev database that predates a new
column boots perfectly and then fails deep inside whichever request first
touches it. SOLUSDEV-168 lost an evening to exactly that: the app came up clean,
the FeatureScript enable flow registered its OAuth client, and only then died on
`oauth_states.code_verifier does not exist`.
"""

import logging

import pytest
from solus_api.main import _warn_on_missing_columns
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_it_warns_when_a_column_the_models_expect_is_missing(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """Drop a real column, then assert the guard both notices and says what to do
    about it — a warning that does not name the fix is decoration."""
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE oauth_states DROP COLUMN code_verifier"))
        try:
            with caplog.at_level(logging.WARNING, logger="solus.main"):
                await conn.run_sync(_warn_on_missing_columns)
        finally:
            await conn.execute(
                text("ALTER TABLE oauth_states ADD COLUMN code_verifier VARCHAR(128)")
            )

    assert "oauth_states.code_verifier" in caplog.text
    assert "alembic upgrade head" in caplog.text


async def test_it_is_silent_when_the_schema_matches(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    """A guard that cries wolf on every boot gets ignored on the boot that counts."""
    async with engine.begin() as conn:
        with caplog.at_level(logging.WARNING, logger="solus.main"):
            await conn.run_sync(_warn_on_missing_columns)

    assert "BEHIND THE MODELS" not in caplog.text


async def test_a_broken_check_never_stops_the_server_booting(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Advisory only. A drift check that raises would be worse than the drift."""
    with caplog.at_level(logging.WARNING, logger="solus.main"):
        _warn_on_missing_columns(object())  # not a connection at all

    assert "BEHIND THE MODELS" not in caplog.text
