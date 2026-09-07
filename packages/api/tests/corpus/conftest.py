"""`clean_corpus`: the `db` session with the three global corpus tables emptied
before the test. The base `db` fixture already truncates every mapped table
(corpus tables included) in teardown, so no second wipe runs here: under
concurrent suites on one database an extra DELETE only widens the window in
which this session waits on another's TRUNCATE lock. This directory is a
package, so this conftest is `corpus.conftest` and cannot shadow
tests/conftest.py, which older suites import helpers from by name."""

from __future__ import annotations

import pytest
from solus_api.corpus.schema import CorpusChunkRow, CorpusCitationRow, CorpusRelease
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def clean_corpus(db: AsyncSession) -> AsyncSession:
    """Empty the three global corpus tables, then hand back the session."""
    await db.execute(delete(CorpusCitationRow))
    await db.execute(delete(CorpusChunkRow))
    await db.execute(delete(CorpusRelease))
    await db.commit()
    return db
