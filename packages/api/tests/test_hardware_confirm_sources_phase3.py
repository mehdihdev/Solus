"""Confirm saves durable config even when its subsequent local source check fails."""

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.models import SolusEntry, SolusEntryKind
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_detect import (
    DEVICE_REF,
    _confirm_body,
    _detect_project,
    _detect_url,
    _DetectLocal,
    _wire_proposal,
)


async def test_confirm_keeps_saved_config_when_calibration_changes_before_session(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _ = await _detect_project(client, alice_headers)
    account = await me(client, alice_headers)
    local = _DetectLocal()
    local.proposal = _wire_proposal(repo_matches=1)
    app.state.bench_local = local
    app.state.hardware_connections.local = local
    reference = uuid.uuid5(uuid.UUID(project), "/cal/cfg0.json")
    source = tmp_path / "fixture-calibration.json"
    source.write_bytes(b'{"fixture_only":true,"offset":3}')
    directory = tmp_path / ".solus" / "projects" / project
    directory.mkdir(parents=True)
    (directory / "hardware.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "accounts": {
                    account["id"]: {
                        "sources": {
                            str(reference): {
                                "path": str(source),
                                "contentSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                            }
                        },
                        "bindings": {},
                    }
                },
            }
        )
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    query = select(SolusEntry).where(
        SolusEntry.project_id == uuid.UUID(project), SolusEntry.kind == SolusEntryKind.CONFIG
    )
    persisted: dict[uuid.UUID, str] = {}
    original_publish = app.state.graph_hub.publish

    async def change_source_after_commit(*args: Any, **kwargs: Any) -> None:
        # Publication is after confirm's commit, before its optional session start.
        # This separate DB session proves the config is durable before the file changes.
        rows = list(await db.scalars(query))
        assert len(rows) == 3
        persisted.update({row.id: json.dumps(row.payload, sort_keys=True) for row in rows})
        source.write_bytes(b'{"fixture_only":true,"offset":4}')
        await original_publish(*args, **kwargs)

    monkeypatch.setattr(app.state.graph_hub, "publish", change_source_after_commit)
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(repo_config_id="repo:cfg0", start_session=True),
    )
    assert response.status_code == 201, response.text
    result = response.json()["data"]
    assert result["session_id"] is None
    assert result["session_error"] is None
    await app.state.hardware_connections.drain()
    robot = await client.get(
        f"/api/v1/projects/{project}/entities/{result['robot']['id']}", headers=alice_headers
    )
    state = robot.json()["data"]["properties"]["connection"]
    assert state["status"] == "failed"
    assert "changed" in state["error"] and "relink" in state["error"]
    assert str(tmp_path) not in robot.text and "/cal/cfg0.json" not in robot.text
    assert str(tmp_path) not in response.text and "/cal/cfg0.json" not in response.text
    assert local.opened == []
    rows = list(await db.scalars(query.execution_options(populate_existing=True)))
    assert {row.id: json.dumps(row.payload, sort_keys=True) for row in rows} == persisted
    components = [
        row.payload["component"] for row in rows if row.payload and row.payload["component"]
    ]
    assert len(components) == 2
    assert all(
        component["calibration"]["source"] == f"source:{reference}" for component in components
    )
    assert all(
        component["calibration"]["values"]["homing_offset"] == -2043 for component in components
    )
