"""SOLUSDEV-321 P4-T4 (R110) — the mesh check as its own bounded ARQ job.

`simulate` never runs the mesh check in a SOL request: its worst case is about two million
edge-face tests. It enqueues `run_mesh_sim`, which runs the check off the worker's event loop and
records the run through the facts writer, as the other two rung-3 jobs do. A malformed request is
the enqueuer's bug and raises; a subject with nothing to check is refused, and nothing is recorded.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.graph import kinds
from solus_api.graph.live import LiveHub
from solus_api.models import Domain, GraphEntity, Project, Team
from solus_api.simulation.mesh_job import QueuedMeshCheck, run_mesh_sim
from solus_api.simulation.sim_facts import SimJobRequest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_mesh_interference import _attrs, _cube


async def _seed(
    maker: async_sessionmaker[AsyncSession], **attrs: Any
) -> tuple[uuid.UUID, uuid.UUID]:
    """A committed project holding one mechanical part with these attrs."""
    async with maker() as db:
        team = Team(name="mesh-job")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="mesh-job")
        db.add(project)
        await db.flush()
        part = GraphEntity(
            project_id=project.id,
            kind=kinds.PART,
            domain=Domain.MECHANICAL,
            origin="manual",
            name="two boxes",
            attrs=attrs,
        )
        db.add(part)
        await db.commit()
        return project.id, part.id


def _worker_context(maker: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    """What the worker hands a job: its sessionmaker and its hub."""
    return {"sessionmaker": maker, "graph_hub": LiveHub()}


async def _sim_results(maker: async_sessionmaker[AsyncSession]) -> int:
    async with maker() as db:
        found = select(func.count()).select_from(GraphEntity)
        return await db.scalar(found.where(GraphEntity.kind == kinds.SIM_RESULT)) or 0


async def test_the_mesh_job_records_its_run(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    attrs = _attrs(_cube((0, 0, 0), (20, 20, 20)), _cube((10, 10, 10), (20, 20, 20)))
    project_id, part_id = await _seed(maker, **attrs)
    request = SimJobRequest(project_id=project_id, subject_id=part_id, facts=attrs)

    status = await run_mesh_sim(_worker_context(maker), request.model_dump(mode="json"))

    assert status["status"] == "recorded", status
    async with maker() as db:
        result = await db.get(GraphEntity, uuid.UUID(str(status["sim_result_id"])))
        subject = await db.get(GraphEntity, part_id)
    assert result is not None and subject is not None
    assert (result.kind, result.attrs["rung"]) == (kinds.SIM_RESULT, 3)
    assert result.attrs["values"]["interference_mm"]["value"] == pytest.approx(10.0)
    assert result.attrs["provenance"]["solver"].startswith("mesh_interference:")
    assert subject.attrs["expected"]["interference_mm"]["sim_result_id"] == str(result.id)


async def test_a_subject_with_nothing_to_check_is_refused_and_nothing_is_recorded(
    engine: AsyncEngine,
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, part_id = await _seed(maker)
    request = SimJobRequest(project_id=project_id, subject_id=part_id, facts={})

    status = await run_mesh_sim(_worker_context(maker), request.model_dump(mode="json"))

    assert status["status"] == "refused"
    assert "nothing to compute" in str(status["reason"])
    assert await _sim_results(maker) == 0


async def test_a_malformed_request_raises_before_anything_runs(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    with pytest.raises(ValidationError):
        await run_mesh_sim(_worker_context(maker), {"project_id": "not a project"})
    assert await _sim_results(maker) == 0


def test_it_is_the_mesh_check_and_available_wherever_the_job_runs() -> None:
    check = QueuedMeshCheck()
    assert (check.name, check.domain, check.rung) == ("mesh_interference", "mechanical", 3)
    assert check.available is True
    assert "interference_mm" in check.quantities
