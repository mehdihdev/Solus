"""Desktop export acquisition stays with the API bridge while provider sync uses ARQ."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks, Response
from solus_api.models import SourceType
from solus_api.routers import sources


@pytest.mark.parametrize(
    "provider,api_owned",
    [
        (SourceType.LOCAL, True),
        (SourceType.KICAD, True),
        (SourceType.ALTIUM, True),
        (SourceType.ONSHAPE, False),
        (SourceType.GITHUB, False),
        (SourceType.GITLAB, False),
    ],
)
async def test_manual_sync_uses_the_process_that_owns_its_acquirer(
    monkeypatch, provider, api_owned
):
    actor = uuid.uuid4()
    source = SimpleNamespace(id=uuid.uuid4(), type=provider)
    ctx = SimpleNamespace(
        project=SimpleNamespace(id=uuid.uuid4()),
        team=SimpleNamespace(id=uuid.uuid4()),
        user=SimpleNamespace(id=actor),
    )
    session = SimpleNamespace(
        add=lambda job: setattr(job, "id", uuid.uuid4()), flush=AsyncMock(), commit=AsyncMock()
    )
    monkeypatch.setattr(sources, "record_activity", Mock())
    monkeypatch.setattr(sources, "emit_event", Mock())
    pool = SimpleNamespace(enqueue_job=AsyncMock())
    monkeypatch.setattr(sources, "_arq_pool", AsyncMock(return_value=pool))
    run = AsyncMock()
    monkeypatch.setattr(sources, "_run_inline", run)
    background = BackgroundTasks()
    app = object()
    settings = SimpleNamespace(sync_inline=False, redis_url="redis://localhost:6379/0")
    response = Response()
    job = await sources.enqueue_sync(
        session, ctx, source, SimpleNamespace(app=app), background, settings, response
    )
    run.assert_not_awaited()
    if api_owned:
        pool.enqueue_job.assert_not_awaited()
        assert len(background.tasks) == 1
        await background()
        run.assert_awaited_once_with(app, source.id, job, acting_user_id=actor)
    else:
        assert not background.tasks
        pool.enqueue_job.assert_awaited_once_with(
            "sync_source", str(source.id), str(job), str(actor)
        )
    assert response.headers["Location"] == f"/api/v1/jobs/{job}"
