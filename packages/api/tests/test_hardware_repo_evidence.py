"""Picker authorization, content review and account isolation on stable proposals."""

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import BOB, add_member, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.hardware.local_sources import LocalHardwareSources
from test_hardware_detect import (
    DEVICE_REF,
    _confirm_body,
    _detect_project,
    _detect_url,
    _DetectLocal,
)


class SourceLocal(_DetectLocal):
    def propose_device(self, device_ref: str, **kwargs: Any) -> dict[str, Any] | None:
        sources = kwargs.pop("repo_sources", [])
        result = super().propose_device(device_ref, **kwargs)
        assert result is not None
        if sources:
            from livebench.hardware.repo_config import RepoParserRegistry, parse_repo_sources
            from livebench.local import _repo_match_wire

            matches = parse_repo_sources(sources, RepoParserRegistry.with_generic())
            result["repo_matches"] = [_repo_match_wire(match) for match in matches]
        return result


async def setup_source(
    client: AsyncClient,
    headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[str, str, str, Path, Path, SourceLocal]:
    project, team = await _detect_project(client, headers)
    account = (await me(client, headers))["id"]
    selected = tmp_path / "motors.json"
    selected.write_text('{"motors":{"joint":{"id":1,"mode":"degrees"},"gripper":{"id":2}}}')
    ref = str(uuid.uuid4())
    state = tmp_path / ".solus" / "projects" / project / "hardware.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "accounts": {
                    account: {
                        "bindings": {},
                        "sources": {
                            ref: {
                                "path": str(selected),
                                "contentSha256": hashlib.sha256(selected.read_bytes()).hexdigest(),
                            }
                        },
                    }
                },
            }
        )
    )
    monkeypatch.setattr(
        LocalHardwareSources, "for_local_runner", classmethod(lambda cls, runner: cls(tmp_path))
    )
    fake = SourceLocal()
    app.state.bench_local = fake
    return project, team, f"source:{ref}", selected, state, fake


async def test_source_proposal_and_confirm_preserve_verified_names(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project, _, ref, _, _, fake = await setup_source(
        client, alice_headers, app, monkeypatch, tmp_path
    )
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "propose"),
        headers=alice_headers,
        json={"source_refs": [ref]},
    )
    assert response.status_code == 200, response.text
    [match] = response.json()["data"]["repo_matches"]
    assert match["source"] == ref
    assert match["parts"][0]["name"] == "joint"
    assert match["parts"][0]["calibration_mode"] is None
    assert match["params"]["declared_calibration_modes"] == {"1": "degrees"}
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(source_refs=[ref], repo_config_id=match["config_id"]),
    )
    assert response.status_code == 201, response.text
    assert len(fake.propose_calls) == 1
    for part_id in response.json()["data"]["part_ids"]:
        config_response = await client.get(
            _detect_url(project, "entities", part_id, "config"), headers=alice_headers
        )
        assert config_response.status_code == 200, config_response.text
        component = config_response.json()["data"]["config"]["component"]
        assert component["calibration"]["mode"] is None
        assert all(channel["unit"] is None for channel in component["telemetry"])


@pytest.mark.parametrize("change", ["bytes", "revoked", "relinked"])
async def test_confirm_revalidates_source_before_graph_write(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    change: str,
) -> None:
    project, _, ref, selected, state, _ = await setup_source(
        client, alice_headers, app, monkeypatch, tmp_path
    )
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "propose"),
        headers=alice_headers,
        json={"source_refs": [ref]},
    )
    assert response.status_code == 200, response.text
    match = response.json()["data"]["repo_matches"][0]
    if change == "revoked":
        state.unlink()
    else:
        selected.write_text('{"motors":{"changed":{"id":1}}}')
        if change == "relinked":
            document = json.loads(state.read_text())
            account = next(iter(document["accounts"].values()))
            account["sources"][ref[7:]]["contentSha256"] = hashlib.sha256(
                selected.read_bytes()
            ).hexdigest()
            state.write_text(json.dumps(document))
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "confirm"),
        headers=alice_headers,
        json=_confirm_body(source_refs=[ref], repo_config_id=match["config_id"]),
    )
    assert response.status_code == (404 if change == "revoked" else 409), response.text


async def test_other_account_cannot_consume_source_proposal(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project, team, ref, _, _, _ = await setup_source(
        client, alice_headers, app, monkeypatch, tmp_path
    )
    await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team, role="member")
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "propose"),
        headers=alice_headers,
        json={"source_refs": [ref]},
    )
    assert response.status_code == 200, response.text
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "confirm"),
        headers=bob_headers,
        json=_confirm_body(source_refs=[ref]),
    )
    assert response.status_code == 404, response.text


@pytest.mark.parametrize(
    "refs",
    [
        ["/tmp/code.py"],
        ["source:bad"],
        [f"source:{uuid.UUID(int=1)}"] * 2,
        [f"source:{uuid.UUID(int=i)}" for i in range(33)],
    ],
)
async def test_refs_are_strictly_bounded(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    refs: list[str],
) -> None:
    project, _ = await _detect_project(client, alice_headers)
    app.state.bench_local = SourceLocal()
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "propose"),
        headers=alice_headers,
        json={"source_refs": refs},
    )
    assert response.status_code == 422, response.text


async def test_shared_file_grant_does_not_share_another_accounts_review(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project, team, ref, _, state, _ = await setup_source(
        client, alice_headers, app, monkeypatch, tmp_path
    )
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, team, role="member")
    document = json.loads(state.read_text())
    document["accounts"][bob["id"]] = next(iter(document["accounts"].values()))
    state.write_text(json.dumps(document))
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "propose"),
        headers=alice_headers,
        json={"source_refs": [ref]},
    )
    assert response.status_code == 200, response.text
    response = await client.post(
        _detect_url(project, "detected", DEVICE_REF, "confirm"),
        headers=bob_headers,
        json=_confirm_body(source_refs=[ref]),
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "proposal_changed"
