"""BRG-03: status frames → cloud cache → GET /bridge (detect + surface)."""

import json
from collections.abc import Callable
from typing import Any

from conftest import ALICE, BOB, bearer
from fastapi import FastAPI
from starlette.testclient import TestClient
from test_bridge import _connect, _hello_frame, _setup_project


def _status_frame(*servers: dict[str, Any]) -> str:
    return json.dumps({"type": "status", "data": {"servers": list(servers)}})


def _mock_ready(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": "mock",
        "state": "ready",
        "detail": None,
        "updated_at": "2026-07-23T12:00:00Z",
    }
    entry.update(overrides)
    return entry


def _get_status(client: TestClient, project_id: str, headers: dict[str, str]) -> dict[str, Any]:
    resp = client.get(f"/api/v1/projects/{project_id}/bridge", headers=headers)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


def test_status_snapshot_cached_and_served(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    assert _get_status(client, project_id, alice) == {
        "connected": False,
        "companion_version": None,
        "servers": [],
    }
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_hello_frame())
        assert json.loads(ws.receive_text())["type"] == "hello_ack"
        # session, no snapshot yet
        body = _get_status(client, project_id, alice)
        assert body["connected"] is True and body["servers"] == []
        assert body["companion_version"] == "0.1.0"
        # snapshot arrives → served; unknown server names filtered out
        ws.send_text(_status_frame(_mock_ready(state="busy"), _mock_ready(name="not_a_known_fork")))
        ws.send_text(json.dumps({"type": "ping", "data": {}}))  # order barrier
        assert json.loads(ws.receive_text())["type"] == "pong"
        body = _get_status(client, project_id, alice)
        assert [s["name"] for s in body["servers"]] == ["mock"]
        assert body["servers"][0]["state"] == "busy"
        # a new snapshot replaces the old wholesale (snapshot-not-delta)
        ws.send_text(_status_frame(_mock_ready(state="error", detail="tool crashed")))
        ws.send_text(json.dumps({"type": "ping", "data": {}}))
        assert json.loads(ws.receive_text())["type"] == "pong"
        body = _get_status(client, project_id, alice)
        assert body["servers"][0]["state"] == "error"
        assert body["servers"][0]["detail"] == "tool crashed"
    # disconnect → offline again, cache gone with the session
    assert _get_status(client, project_id, alice)["connected"] is False


def test_malformed_status_dropped_session_survives(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice = bearer(**ALICE)
    _, project_id = _setup_project(client, alice)
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_hello_frame())
        assert json.loads(ws.receive_text())["type"] == "hello_ack"
        ws.send_text(_status_frame(_mock_ready(state="exploded")))  # bad enum
        ws.send_text(_status_frame(_mock_ready(detail="x" * 600)))  # oversize detail
        ws.send_text(json.dumps({"type": "ping", "data": {}}))
        assert json.loads(ws.receive_text())["type"] == "pong"  # alive
        assert _get_status(client, project_id, alice)["servers"] == []  # nothing cached


def test_status_is_per_user(bridge_app: FastAPI) -> None:
    """User B on the same project does not see A's companion (per-user scope)."""
    client = TestClient(bridge_app)
    alice, bob = bearer(**ALICE), bearer(**BOB)
    team_id, project_id = _setup_project(client, alice)
    assert client.get("/api/v1/users/me", headers=bob).status_code == 200
    invite = client.post(
        f"/api/v1/teams/{team_id}/invites",
        json={"email": BOB["email"], "role": "member"},
        headers=alice,
    ).json()["data"]
    assert client.post(f"/api/v1/invites/{invite['token']}/accept", headers=bob).status_code == 200
    with _connect(client, project_id, alice) as ws:
        ws.send_text(_hello_frame())
        assert json.loads(ws.receive_text())["type"] == "hello_ack"
        assert _get_status(client, project_id, alice)["connected"] is True
        assert _get_status(client, project_id, bob)["connected"] is False


def test_status_endpoint_is_project_scoped(bridge_app: FastAPI) -> None:
    client = TestClient(bridge_app)
    alice, bob = bearer(**ALICE), bearer(**BOB)
    _, project_id = _setup_project(client, alice)
    assert client.get("/api/v1/users/me", headers=bob).status_code == 200
    resp = client.get(f"/api/v1/projects/{project_id}/bridge", headers=bob)
    assert resp.status_code == 404  # non-member: no existence leak


def test_unavailable_error_code_round_trips_as_w004_result(
    make_app: Callable[..., FastAPI],
) -> None:
    """The BRG-03 ToolErrorCode.UNAVAILABLE extension is a valid wire value."""
    from solus_api.agent.tools.shapes import ToolError, ToolErrorCode, ToolResult

    result = ToolResult.model_validate(
        {
            "call_id": "c1",
            "ok": False,
            "error": {"code": "unavailable", "message": "bridge offline", "retryable": True},
        }
    )
    assert isinstance(result.error, ToolError)
    assert result.error.code is ToolErrorCode.UNAVAILABLE
