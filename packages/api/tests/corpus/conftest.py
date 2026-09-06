"""`clean_corpus`: empties the three global corpus tables before and after a test
(they are tenant-free, so the per-project truncation elsewhere never touches them).
This directory is a package, so this conftest is `corpus.conftest` and cannot
shadow tests/conftest.py, which older suites import helpers from by name."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from solus_api.corpus.schema import CorpusChunkRow, CorpusCitationRow, CorpusRelease
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def clean_corpus(db: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Empty the three global corpus tables before AND after the test."""

    async def wipe() -> None:
        await db.execute(delete(CorpusCitationRow))
        await db.execute(delete(CorpusChunkRow))
        await db.execute(delete(CorpusRelease))
        await db.commit()

    await wipe()
    yield db
    await wipe()
