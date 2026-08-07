"""SYS-02 retrieval load/latency probe — run manually, paste numbers into the report.

Seeds N deterministic unit vectors across P projects (plus error rows), then
measures under C concurrent workers:

- p50/p95 latency for the ANN path and the keyless (full-text) degraded path
- recall@k of the planner-chosen plan vs a forced exact scan
- EXPLAIN (ANALYZE, BUFFERS) of one representative project-scoped ANN query

Usage (DB must exist and be migrated to head — running the pytest suite once
does both; the probe reuses the suite's per-checkout database by default):

    uv run python scripts/perf_rag_retrieval.py            # N=10k
    uv run python scripts/perf_rag_retrieval.py --n 100000 # the 10x point

Seeded rows are deleted afterwards (team-cascade); the probe never truncates.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import math
import os
import random
import statistics
import time
import uuid
from pathlib import Path

from solus_api.agent.interfaces import RetrievalFilter
from solus_api.models import (
    EMBEDDING_DIM,
    Domain,
    ErrorSolution,
    GraphEntity,
    Membership,
    Project,
    Role,
    Team,
    User,
)
from solus_api.rag import rag_query
from sqlalchemy import delete, insert, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_API_DIR = Path(__file__).resolve().parent.parent
_WORDS = ("servo", "driver", "imu", "camera", "bracket", "regulator", "encoder", "harness")


def _probe_database_url() -> str:
    """The pytest suite's per-checkout database (conftest idiom) unless overridden."""
    checkout = hashlib.sha1(str(_API_DIR).encode()).hexdigest()[:8]  # noqa: S324 — id, not crypto
    default = f"postgresql+asyncpg://solus:solus@localhost:5432/solus_test_{checkout}"
    return os.environ.get("SOLUS_TEST_DATABASE_URL", default)


def _unit_vector(rng: random.Random) -> list[float]:
    raw = [rng.gauss(0.0, 1.0) for _ in range(EMBEDDING_DIM)]
    norm = math.sqrt(sum(component * component for component in raw)) or 1.0
    return [component / norm for component in raw]


async def _seed_corpus(
    session: AsyncSession, *, n: int, projects: int, rng: random.Random, tag: str
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    project_ids: list[uuid.UUID] = []
    team_ids: list[uuid.UUID] = []
    for index in range(projects):
        user = User(supabase_user_id=f"perf-{tag}-{index}", email=f"perf-{tag}-{index}@ex.com")
        team = Team(name=f"perf-{tag}-{index}")
        session.add_all([user, team])
        await session.flush()
        session.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
        project = Project(team_id=team.id, name=f"perf-{tag}-{index}", created_by=user.id)
        session.add(project)
        await session.flush()
        project_ids.append(project.id)
        team_ids.append(team.id)
    await session.commit()

    batch: list[dict[str, object]] = []
    for index in range(n):
        name = f"{_WORDS[index % len(_WORDS)]} {_WORDS[(index // 3) % len(_WORDS)]} {index}"
        batch.append(
            {
                "id": uuid.uuid4(),
                "project_id": project_ids[index % projects],
                "kind": "component",
                "domain": Domain.ELECTRICAL,
                "name": name,
                "attrs": {},
                "embedding": _unit_vector(rng),
                "origin": "connector",
                "version": 1,
            }
        )
        if len(batch) >= 500:
            await session.execute(insert(GraphEntity), batch)
            await session.commit()
            batch = []
    if batch:
        await session.execute(insert(GraphEntity), batch)
    for index in range(max(n // 5, 1)):
        session.add(
            ErrorSolution(
                project_id=project_ids[index % projects],
                error_text=f"fault {_WORDS[index % len(_WORDS)]} {index}",
                solution_text="fix",
                domain=Domain.ELECTRICAL,
                attrs={},
                embedding=_unit_vector(rng),
            )
        )
    await session.commit()
    print(f"seeded n={n} entities + {max(n // 5, 1)} errors across {projects} projects")
    return project_ids, team_ids


async def _cleanup_corpus(session: AsyncSession, team_ids: list[uuid.UUID], tag: str) -> None:
    for team_id in team_ids:
        await session.execute(delete(Team).where(Team.id == team_id))
    # Scoped to THIS run's tag so a concurrent probe's rows are never deleted.
    await session.execute(delete(User).where(User.supabase_user_id.like(f"perf-{tag}-%")))
    await session.commit()


def _pct_ms(samples: list[float], q: int) -> float:
    if len(samples) < 2:
        return samples[0] * 1000 if samples else float("nan")
    return statistics.quantiles(samples, n=100)[q - 1] * 1000


async def _query_worker(
    maker: async_sessionmaker[AsyncSession],
    project_ids: list[uuid.UUID],
    rng: random.Random,
    queries: int,
    ann_latencies: list[float],
    degraded_latencies: list[float],
) -> None:
    async def embed(_text: str) -> list[float] | None:
        return _unit_vector(rng)

    async with maker() as session:
        for index in range(queries):
            retrieval_filter = RetrievalFilter(
                project_id=project_ids[rng.randrange(len(project_ids))]
            )
            word = _WORDS[rng.randrange(len(_WORDS))]
            started = time.perf_counter()
            if index % 10 < 7:  # 70% ANN / 30% degraded
                await rag_query(session, text=word, k=10, filter=retrieval_filter, embed=embed)
                ann_latencies.append(time.perf_counter() - started)
            else:
                await rag_query(session, text=word, k=10, filter=retrieval_filter, embed=None)
                degraded_latencies.append(time.perf_counter() - started)


async def _measure_recall(
    session: AsyncSession, project_ids: list[uuid.UUID], rng: random.Random, samples: int, k: int
) -> float:
    """recall@k of the planner-chosen plan vs a forced exact scan (same query)."""
    total = 0.0
    for _ in range(samples):
        project_id = project_ids[rng.randrange(len(project_ids))]
        vector = _unit_vector(rng)

        async def embed(_text: str, v: list[float] = vector) -> list[float] | None:
            return v

        chosen = await rag_query(
            session, text="q", k=k, filter=RetrievalFilter(project_id=project_id), embed=embed
        )
        chosen_ids = {hit.source_ref.graph_entity_id for hit in chosen}
        await session.execute(text("SET LOCAL enable_indexscan = off"))
        await session.execute(text("SET LOCAL enable_bitmapscan = off"))
        exact = await rag_query(
            session, text="q", k=k, filter=RetrievalFilter(project_id=project_id), embed=embed
        )
        await session.commit()  # ends the SET LOCAL transaction
        exact_ids = {hit.source_ref.graph_entity_id for hit in exact}
        total += len(chosen_ids & exact_ids) / max(len(exact_ids), 1)
    return total / samples


async def _explain_scoped_ann(
    session: AsyncSession, project_id: uuid.UUID, rng: random.Random
) -> str:
    rows = await session.execute(
        text(
            "EXPLAIN (ANALYZE, BUFFERS) "
            "SELECT id FROM graph_entity "
            "WHERE project_id = :p AND deleted_at IS NULL AND embedding IS NOT NULL "
            "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 10"
        ),
        {"p": project_id, "q": str(_unit_vector(rng))},
    )
    return "\n".join(row[0] for row in rows)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10_000)
    parser.add_argument("--projects", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--queries", type=int, default=50, help="queries per worker")
    parser.add_argument("--recall-samples", type=int, default=100)
    args = parser.parse_args()

    rng = random.Random(42)  # noqa: S311 — deterministic seeding, not cryptography
    run_tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(_probe_database_url())
    maker = async_sessionmaker(engine, expire_on_commit=False)
    team_ids: list[uuid.UUID] = []
    # NOTE: never run concurrently with the pytest suite on the same DB — the
    # suite TRUNCATEs all tables after every test and will kill the probe mid-run.
    try:
        async with maker() as session:
            seed_started = time.perf_counter()
            project_ids, team_ids = await _seed_corpus(
                session, n=args.n, projects=args.projects, rng=rng, tag=run_tag
            )
            print(
                f"seed time: {time.perf_counter() - seed_started:.1f}s (HNSW builds incrementally)"
            )
        ann: list[float] = []
        degraded: list[float] = []
        run_started = time.perf_counter()
        async with asyncio.TaskGroup() as group:
            for _ in range(args.concurrency):
                group.create_task(
                    _query_worker(
                        maker,
                        project_ids,
                        random.Random(rng.random()),  # noqa: S311 — see above
                        args.queries,
                        ann,
                        degraded,
                    )
                )
        elapsed = time.perf_counter() - run_started
        total = len(ann) + len(degraded)
        print(
            f"\n{total} queries, concurrency={args.concurrency}, "
            f"{elapsed:.1f}s wall ({total / elapsed:.0f} q/s)"
        )
        print(f"ANN      n={len(ann)}  p50={_pct_ms(ann, 50):.1f}ms  p95={_pct_ms(ann, 95):.1f}ms")
        print(
            f"degraded n={len(degraded)}  p50={_pct_ms(degraded, 50):.1f}ms  "
            f"p95={_pct_ms(degraded, 95):.1f}ms"
        )

        async with maker() as session:
            recall = await _measure_recall(
                session, project_ids, rng, samples=args.recall_samples, k=10
            )
            print(f"recall@10 vs forced-exact over {args.recall_samples} samples: {recall:.3f}")
            plan = await _explain_scoped_ann(session, project_ids[0], rng)
            print("\nEXPLAIN (ANALYZE, BUFFERS) — representative scoped ANN query:")
            print(plan)
    finally:
        async with maker() as session:
            await _cleanup_corpus(session, team_ids, run_tag)
        await engine.dispose()
        print("\nseeded rows cleaned up")


if __name__ == "__main__":
    asyncio.run(main())
