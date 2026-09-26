"""Authorized byte extraction is read-only, tenant-scoped and refuses stale evidence."""

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import ALICE, BOB, add_member, bearer, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.models import GraphEdge, GraphEntity, HardwareOperation, SolusEntry, utcnow
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from test_hardware_router import _hw_project, _hw_url, _robot, _saved_serial_arm


async def setup(
    client: AsyncClient,
    headers: dict[str, str],
    app: FastAPI,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, str, str, dict[str, Any], Path, Path]:
    from solus_api.hardware.local_sources import LocalHardwareSources

    project, team = await _hw_project(client, headers)
    robot = await _robot(client, headers, project)
    config = await _saved_serial_arm(client, headers, project, robot["id"])
    result = await client.put(
        _hw_url(project, "robots", robot["id"], "config"), headers=headers, json={"config": config}
    )
    assert result.status_code == 200, result.text
    topology = (
        await client.get(_hw_url(project, "robots", robot["id"], "topology"), headers=headers)
    ).json()["data"]
    brain = next(n["id"] for n in topology["nodes"] if n["role"] == "brain")
    user = (await me(client, headers))["id"]
    source_id = str(uuid.uuid4())
    selected = tmp_path / "private-config.json"
    selected.write_text(
        '{"port":"/dev/private", "calibration_file":"/home/private/key.json",'
        ' "parts":{"elbow":{"address":"06","model":"servo"}}}'
    )
    state = tmp_path / ".solus" / "projects" / project / "hardware.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "accounts": {
                    user: {
                        "bindings": {},
                        "sources": {
                            source_id: {
                                "path": str(selected),
                                "contentSha256": hashlib.sha256(selected.read_bytes()).hexdigest(),
                            }
                        },
                    }
                },
            }
        )
    )
    factory = LocalHardwareSources.for_local_runner
    monkeypatch.setattr(
        LocalHardwareSources,
        "for_local_runner",
        classmethod(lambda cls, runner: factory(runner, home=tmp_path)),
    )
    app.state.bench_local = object()
    body = {"brain_id": brain, "source_ref": f"source:{source_id}", "source_kind": "host_config"}
    return project, team, robot["id"], body, selected, state


def url(project: str, robot: str) -> str:
    return _hw_url(project, "robots", robot, "topology", "extraction", "propose")


async def snapshot(db: AsyncSession) -> list[list[dict[str, Any]]]:
    return [
        list((await db.execute(select(model.__table__).order_by(model.id))).mappings())
        for model in (GraphEntity, GraphEdge, SolusEntry, HardwareOperation)
    ]


@pytest.mark.asyncio
async def test_private_source_proposal_is_stable_readonly_and_path_free(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _, robot, body, selected, _ = await setup(
        client, alice_headers, app, tmp_path, monkeypatch
    )
    before = await snapshot(db)
    response = await client.post(url(project, robot), headers=alice_headers, json=body)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["robot_id"] == robot and data["brain_id"] == body["brain_id"]
    assert data["source_ref"] == body["source_ref"]
    assert len(data["proposal_digest"]) == 64
    assert data["extraction"]["status"] == "success"
    assert data["extraction"]["rows"][0]["address"] == "06"
    assert str(selected) not in response.text and "/private" not in response.text
    assert (
        await client.post(url(project, robot), headers=alice_headers, json=body)
    ).json() == response.json()
    assert await snapshot(db) == before


@pytest.mark.asyncio
async def test_authority_and_validation_refuse_without_path_echo(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, team, robot, body, _, _ = await setup(
        client, alice_headers, app, tmp_path, monkeypatch
    )
    route = url(project, robot)
    assert (await client.post(route, json=body)).status_code == 401
    assert (
        await client.post(route, headers=bearer(**ALICE, email_verified=False), json=body)
    ).status_code == 403
    assert (await client.post(route, headers=bob_headers, json=body)).status_code == 404
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team)
    assert (await client.post(route, headers=bob_headers, json=body)).status_code == 404
    assert (
        await client.post(route, headers=alice_headers, json={**body, "brain_id": robot})
    ).status_code == 404
    for invalid in (
        {**body, "source_ref": "/home/private/source.py"},
        {**body, "path": "/home/private/source.py"},
        {**body, "source_kind": "probe"},
        {**body, "brain_id": "bad"},
    ):
        response = await client.post(route, headers=alice_headers, json=invalid)
        assert response.status_code == 422, response.text
        assert "/home/private" not in response.text
    assert (
        await client.post(
            route, headers=alice_headers, json={**body, "source_ref": f"source:{uuid.uuid4()}"}
        )
    ).status_code == 404
    other, _ = await _hw_project(client, alice_headers)
    assert (
        await client.post(url(other, robot), headers=alice_headers, json=body)
    ).status_code == 404
    app.state.bench_local = None
    assert (await client.post(route, headers=alice_headers, json=body)).status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["content", "deleted", "kind", "version", "grant"])
async def test_proposal_rechecks_authority_after_awaited_extraction(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    from solus_api.hardware import topology_proposals

    project, _, robot, body, selected, state = await setup(
        client, alice_headers, app, tmp_path, monkeypatch
    )
    parse = topology_proposals.parse_source

    async def changed(*args: Any, **kwargs: Any) -> Any:
        result = await parse(*args, **kwargs)
        if change == "content":
            selected.write_text("{}")
        elif change == "grant":
            state.write_text('{"schema_version":1,"accounts":{}}')
        else:
            values: dict[str, Any] = (
                {"deleted_at": utcnow()}
                if change == "deleted"
                else {"kind": "part"}
                if change == "kind"
                else {"version": GraphEntity.version + 1}
            )
            await db.execute(
                update(GraphEntity)
                .where(GraphEntity.id == uuid.UUID(body["brain_id"]))
                .values(**values)
            )
            await db.commit()
        return result

    monkeypatch.setattr(topology_proposals, "parse_source", changed)
    response = await client.post(url(project, robot), headers=alice_headers, json=body)
    assert response.status_code in (404, 409), response.text
    assert str(selected) not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content,suffix,kind,status",
    [
        (b"# no findings\n", ".py", "firmware", 200),
        (b"elbow = Servo(4)\n", ".py", "firmware", 200),
        (b"def broken(", ".py", "firmware", 422),
        (b"{}", ".json", "firmware", 422),
        (b"{", ".json", "host_config", 422),
        (
            b'{"parts":{"elbow":{"address":"06","model":"/home/private/model"}}}',
            ".json",
            "host_config",
            422,
        ),
        *[
            (
                json.dumps({"parts": {"elbow": {"address": "06", "model": path}}}).encode(),
                ".json",
                "host_config",
                422,
            )
            for path in (" /home/private/model ", " C:\\private\\model ", " file:///private/model ")
        ],
    ],
)
async def test_empty_invalid_and_unsupported_are_distinct(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
    suffix: str,
    kind: str,
    status: int,
) -> None:
    project, _, robot, body, selected, state = await setup(
        client, alice_headers, app, tmp_path, monkeypatch
    )
    replacement = selected.with_suffix(suffix)
    replacement.write_bytes(content)
    doc = json.loads(state.read_text())
    grant = next(iter(next(iter(doc["accounts"].values()))["sources"].values()))
    grant.update(path=str(replacement), contentSha256=hashlib.sha256(content).hexdigest())
    state.write_text(json.dumps(doc))
    response = await client.post(
        url(project, robot), headers=alice_headers, json={**body, "source_kind": kind}
    )
    assert response.status_code == status, response.text
    assert "/home/private" not in response.text
    if status == 200:
        rows = response.json()["data"]["extraction"]["rows"]
        if content.startswith(b"elbow"):
            assert rows[0]["address"] == "4" and rows[0]["part_candidate"] == "elbow"
        else:
            assert rows == []


@pytest.mark.asyncio
async def test_viewer_cannot_extract_private_sources(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, team, robot, body, _, _ = await setup(
        client, alice_headers, app, tmp_path, monkeypatch
    )
    await add_member(client, alice_headers, bob_headers, BOB, team, role="viewer")
    response = await client.post(url(project, robot), headers=bob_headers, json=body)
    assert response.status_code == 403
