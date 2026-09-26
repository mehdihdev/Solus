"""Recent captures stay visible independently of random UUID ordering."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from solus_api.livebench.runs.models import RunSummary
from solus_api.livebench.runs.store import new_record
from solus_api.models import GraphEntity
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_router import _hw_project


def record(project: str, identity: int, created: datetime) -> GraphEntity:
    summary = RunSummary(
        id=uuid.UUID(int=identity),
        robot_id=uuid.uuid4(),
        name=f"Run {identity}",
        origin="live",
        status="completed",
        started_at=created,
    )
    row = new_record(uuid.UUID(project), summary, uuid.uuid4())
    row.created_at = created
    return row


@pytest.mark.asyncio
async def test_new_low_uuid_run_stays_first_and_pages_by_time_with_ties(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    project, _ = await _hw_project(client, alice_headers)
    before = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [record(project, index, before) for index in range(2, 24)]
    rows.append(record(project, 1, before + timedelta(seconds=1)))
    db.add_all(rows)
    await db.commit()
    url = f"/api/v1/projects/{project}/bench/runs"
    first = await client.get(url, headers=alice_headers)
    assert first.status_code == 200, first.text
    page = first.json()["data"]
    expected = [1, *range(23, 1, -1)]
    ids = [uuid.UUID(run["id"]).int for run in page["runs"]]
    assert ids == expected[:20]
    second = await client.get(url, params={"cursor": page["next_cursor"]}, headers=alice_headers)
    assert second.status_code == 200, second.text
    rest = second.json()["data"]
    assert [uuid.UUID(run["id"]).int for run in rest["runs"]] == expected[20:]
    assert rest["next_cursor"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing", "foreign", "deleted", "wrong_kind"])
async def test_cursor_must_resolve_to_current_project_run(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    kind: str,
) -> None:
    project, _ = await _hw_project(client, alice_headers)
    target_project = project
    if kind == "foreign":
        target_project, _ = await _hw_project(client, bob_headers)
    identity = uuid.uuid4()
    if kind != "missing":
        row = record(target_project, identity.int, datetime.now(UTC))
        if kind == "deleted":
            row.deleted_at = datetime.now(UTC)
        if kind == "wrong_kind":
            row.kind = "unrelated"
        db.add(row)
        await db.commit()
    result = await client.get(
        f"/api/v1/projects/{project}/bench/runs",
        params={"cursor": str(identity)},
        headers=alice_headers,
    )
    assert result.status_code == 404, result.text
