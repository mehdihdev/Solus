"""§2.16 Jobs — status, project job list, cancel. No Phase 1 endpoint creates
jobs (sync/checks/proving land in Phases 3–4), so tests seed rows directly."""

import uuid

from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.models import Job, JobKind, JobStatus
from sqlalchemy.ext.asyncio import AsyncSession


async def seed_job(
    db: AsyncSession,
    project_id: str,
    team_id: str,
    *,
    kind: JobKind = JobKind.SYNC,
    status: JobStatus = JobStatus.QUEUED,
) -> Job:
    job = Job(
        project_id=uuid.UUID(project_id),
        team_id=uuid.UUID(team_id),
        kind=kind,
        status=status,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def test_get_job_status(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    job = await seed_job(db, project["id"], team["id"])

    resp = await client.get(f"/api/v1/jobs/{job.id}", headers=alice_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "queued"
    assert data["kind"] == "sync"
    assert data["progress"] == 0


async def test_list_project_jobs_with_filters(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    await seed_job(db, project["id"], team["id"], kind=JobKind.SYNC)
    await seed_job(
        db, project["id"], team["id"], kind=JobKind.CHECK_RUN, status=JobStatus.SUCCEEDED
    )

    all_jobs = await client.get(f"/api/v1/projects/{project['id']}/jobs", headers=alice_headers)
    assert len(all_jobs.json()["data"]) == 2

    filtered = await client.get(
        f"/api/v1/projects/{project['id']}/jobs?kind=check_run&status=succeeded",
        headers=alice_headers,
    )
    rows = filtered.json()["data"]
    assert len(rows) == 1
    assert rows[0]["kind"] == "check_run"


async def test_cancel_queued_job(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    job = await seed_job(db, project["id"], team["id"])

    resp = await client.post(f"/api/v1/jobs/{job.id}/cancel", headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"


async def test_cancel_finished_job_conflicts(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    job = await seed_job(db, project["id"], team["id"], status=JobStatus.SUCCEEDED)

    resp = await client.post(f"/api/v1/jobs/{job.id}/cancel", headers=alice_headers)
    assert resp.status_code == 409


async def test_jobs_are_team_scoped(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    job = await seed_job(db, project["id"], team["id"])
    await me(client, bob_headers)

    read = await client.get(f"/api/v1/jobs/{job.id}", headers=bob_headers)
    assert read.status_code == 404

    cancel = await client.post(f"/api/v1/jobs/{job.id}/cancel", headers=bob_headers)
    assert cancel.status_code == 404

    listing = await client.get(f"/api/v1/projects/{project['id']}/jobs", headers=bob_headers)
    assert listing.status_code == 404
