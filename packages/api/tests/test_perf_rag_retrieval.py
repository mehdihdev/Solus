"""Smoke test for the SYS-02 retrieval perf probe (scripts/perf_rag_retrieval.py).

Runs the probe's stages at toy scale against the suite DB so the committed
harness stays runnable — the real numbers come from manual runs at N=10k/100k.
"""

import random
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from perf_rag_retrieval import (  # noqa: E402
    _cleanup_corpus,
    _explain_scoped_ann,
    _measure_recall,
    _query_worker,
    _seed_corpus,
)
from solus_api.models import GraphEntity  # noqa: E402


async def test_probe_stages_run_and_clean_up(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    rng = random.Random(7)
    async with maker() as session:
        project_ids, team_ids = await _seed_corpus(session, n=24, projects=2, rng=rng, tag="smoke")
        assert len(project_ids) == 2

    ann: list[float] = []
    degraded: list[float] = []
    await _query_worker(maker, project_ids, rng, 10, ann, degraded)
    assert ann and degraded  # both paths exercised

    async with maker() as session:
        recall = await _measure_recall(session, project_ids, rng, samples=3, k=5)
        assert 0.0 <= recall <= 1.0
        plan = await _explain_scoped_ann(session, project_ids[0], rng)
        assert "graph_entity" in plan

        await _cleanup_corpus(session, team_ids, "smoke")
        remaining = await session.scalar(
            select(func.count())
            .select_from(GraphEntity)
            .where(GraphEntity.project_id.in_(project_ids))
        )
        assert remaining == 0  # team-cascade removed every seeded row
