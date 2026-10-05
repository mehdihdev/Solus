"""ADR-011 data events: sync outcomes, disconnect, and rate-limit/budget hits.

Consent-gated, no design content in payloads, attributed to the user who acted."""

from __future__ import annotations

import io
import uuid
from typing import Any

from conftest import me
from fixtures.kicad_audit import connect_kicad, new_project, patch_config, sync
from fixtures.kicad_sample import KICAD_XML
from httpx import AsyncClient
from solus_api.models import DataEvent, User
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


async def _consent(db: AsyncSession, user_id: str, value: bool = True) -> None:
    await db.execute(
        update(User).where(User.id == uuid.UUID(user_id)).values(data_collection_consent=value)
    )
    await db.commit()


async def _events(db: AsyncSession, project_id: uuid.UUID, prefix: str) -> list[DataEvent]:
    rows = await db.scalars(
        select(DataEvent)
        .where(DataEvent.project_id == project_id)
        .order_by(DataEvent.created_at, DataEvent.id)
    )
    return [e for e in rows.all() if e.event_type.startswith(prefix)]


async def test_successful_sync_emits_sync_succeeded_with_counts_only(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    user = await me(client, alice_headers)
    await _consent(db, user["id"])
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=KICAD_XML)
    record = await sync(client, alice_headers, project_id, source["id"])

    done = await _events(db, project_id, "source.sync_succeeded")
    assert len(done) == 1
    event = done[0]
    assert str(event.user_id) == user["id"] and event.team_id is not None
    assert event.payload["source_id"] == source["id"]
    assert event.payload["sync_id"] == record["id"]
    assert event.payload["source_type"] == "kicad"
    assert event.payload["entities_created"] == record["entities_created"] > 0
    assert set(event.payload) == {
        "source_id",
        "sync_id",
        "source_type",
        "entities_created",
        "entities_updated",
        "relations_created",
        "relations_deleted",
        "error_count",
    }
    assert "STM32" not in str(event.payload)


async def test_failed_sync_emits_sync_failed_with_code_not_message(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    user = await me(client, alice_headers)
    await _consent(db, user["id"])
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=KICAD_XML)
    await patch_config(
        client, alice_headers, project_id, source["id"], {"export": "<not-a-netlist SECRET-TEXT"}
    )
    await sync(client, alice_headers, project_id, source["id"])

    failed = await _events(db, project_id, "source.sync_failed")
    assert len(failed) == 1
    payload = failed[0].payload
    assert set(payload) == {"source_id", "sync_id", "source_type", "error_code"}
    assert payload["error_code"] and "SECRET-TEXT" not in str(payload)
    assert await _events(db, project_id, "source.sync_succeeded") == []


async def test_sync_outcome_events_need_consent(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    user = await me(client, alice_headers)
    await _consent(db, user["id"], False)
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=KICAD_XML)
    await sync(client, alice_headers, project_id, source["id"])
    assert await _events(db, project_id, "source.") == []


async def test_disconnect_emits_source_disconnected(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    user = await me(client, alice_headers)
    await _consent(db, user["id"])
    project_id = await new_project(client, alice_headers)
    source = await connect_kicad(client, alice_headers, project_id, export=KICAD_XML)
    resp = await client.delete(
        f"/api/v1/projects/{project_id}/sources/{source['id']}", headers=alice_headers
    )
    assert resp.status_code == 200, resp.text
    gone = await _events(db, project_id, "source.disconnected")
    assert len(gone) == 1
    assert gone[0].payload == {
        "source_id": source["id"],
        "source_type": "kicad",
        "retain_entities": False,
    }


def _file() -> dict[str, Any]:
    return {"file": ("x.zip", io.BytesIO(b"hello artifact"), "application/octet-stream")}


async def _upload(client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID) -> Any:
    return await client.post(
        f"/api/v1/projects/{project_id}/artifacts",
        data={"media_type": "application/zip"},
        files=_file(),
        headers=headers,
    )


async def test_request_budget_429_emits_rate_limit_event(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, app: Any
) -> None:
    user = await me(client, alice_headers)
    await _consent(db, user["id"])
    project_id = await new_project(client, alice_headers)
    app.state.settings.artifact_uploads_per_minute_per_user = 1
    assert (await _upload(client, alice_headers, project_id)).status_code == 201
    assert (await _upload(client, alice_headers, project_id)).status_code == 429

    hits = await _events(db, project_id, "rate_limit.exceeded")
    assert len(hits) == 1
    assert hits[0].payload == {"budget": "artifact_upload_requests", "retry_after_seconds": 60}
    assert str(hits[0].user_id) == user["id"] and hits[0].team_id is not None


async def test_byte_budget_429_emits_rate_limit_event(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, app: Any
) -> None:
    user = await me(client, alice_headers)
    await _consent(db, user["id"])
    project_id = await new_project(client, alice_headers)
    app.state.settings.artifact_upload_bytes_per_hour_per_team = 5
    assert (await _upload(client, alice_headers, project_id)).status_code == 429
    hits = await _events(db, project_id, "rate_limit.exceeded")
    assert [h.payload["budget"] for h in hits] == ["artifact_upload_bytes"]
    assert hits[0].payload["retry_after_seconds"] == 3600


async def test_rate_limit_event_needs_consent(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, app: Any
) -> None:
    user = await me(client, alice_headers)
    await _consent(db, user["id"], False)
    project_id = await new_project(client, alice_headers)
    app.state.settings.artifact_uploads_per_minute_per_user = 0
    assert (await _upload(client, alice_headers, project_id)).status_code == 429
    assert await _events(db, project_id, "rate_limit.") == []
