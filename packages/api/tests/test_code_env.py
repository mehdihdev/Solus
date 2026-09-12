"""Code environments as first-class `.solus` entries (SOLUSDEV-252 S5, docs/api/solus.md
§2.1). A `code` CONFIG entry's payload is a validated `CodeEnvironment`; one entry per
(type, name/path); the POST route accepts `{kind: "config", payload}` for `code` only."""

import uuid
from typing import Any

import pytest
from conftest import create_project, create_team, me
from httpx import AsyncClient
from pydantic import ValidationError
from solus_api.core.errors import APIError
from solus_api.models import GraphEntity, SolusEntry, SolusEntryKind, SolusSection
from solus_api.services.code_env import (
    MAX_PACKAGES,
    CodeEnvironment,
    list_code_environments,
    resolve_environment,
    upsert_code_environment,
)
from solus_api.services.solus_config import validate_config_payload
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _env(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": 1,
        "type": "venv",
        "name": "robot-venv",
        "path": "/home/dev/robot/.venv",
        "interpreter": "/home/dev/robot/.venv/bin/python",
        "image": None,
        "packages": [{"name": "numpy", "version": "2.1.0"}, {"name": "pyserial", "version": None}],
        "detected_on": {"os": "linux", "arch": "x86_64"},
        "provenance": "detected",
        "captured_at": "2026-09-07T10:00:00Z",
    }
    doc.update(overrides)
    return doc


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    user = await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return uuid.UUID(project["id"]), uuid.UUID(user["id"])


# ------------------------------------------------------------------------ model


def test_document_is_capped_and_forbids_extras() -> None:
    CodeEnvironment.model_validate(_env())
    with pytest.raises(ValidationError):
        CodeEnvironment.model_validate(_env(evil=1))
    with pytest.raises(ValidationError):
        CodeEnvironment.model_validate(_env(type="virtualenvwrapper"))
    with pytest.raises(ValidationError):
        CodeEnvironment.model_validate(
            _env(packages=[{"name": f"p{i}"} for i in range(MAX_PACKAGES + 1)])
        )
    with pytest.raises(ValidationError):
        CodeEnvironment.model_validate(_env(name=""))


def test_config_payload_validation_dispatches_by_section() -> None:
    env = validate_config_payload(SolusSection.CODE, _env())
    assert isinstance(env, CodeEnvironment)
    with pytest.raises(APIError) as bad:
        validate_config_payload(SolusSection.CODE, {"type": "venv"})
    assert bad.value.status_code == 422
    with pytest.raises(APIError) as wrong_section:
        validate_config_payload(SolusSection.DOCS, _env())
    assert wrong_section.value.status_code == 422


# ---------------------------------------------------------------------- service


async def test_upsert_is_one_entry_per_type_and_name(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, user_id = await _project(client, alice_headers)
    env = CodeEnvironment.model_validate(_env())
    first = await upsert_code_environment(
        db, project_id, env, created_by=user_id, author="detected"
    )
    await db.commit()
    assert first.kind is SolusEntryKind.CONFIG
    assert first.section is SolusSection.CODE
    assert first.text == "robot-venv"
    assert first.payload == env.model_dump(mode="json")
    node = await db.get(GraphEntity, first.entity_id)
    assert node is not None and node.attrs["section"] == "code"

    updated_env = CodeEnvironment.model_validate(
        _env(packages=[{"name": "numpy", "version": "2.2.0"}])
    )
    second = await upsert_code_environment(
        db, project_id, updated_env, created_by=user_id, author="detected"
    )
    await db.commit()
    assert second.id == first.id
    assert second.payload is not None
    assert second.payload["packages"][0]["version"] == "2.2.0"
    other = await upsert_code_environment(
        db,
        project_id,
        CodeEnvironment.model_validate(_env(type="conda", name="robot-conda", path=None)),
        created_by=user_id,
        author="user",
    )
    await db.commit()
    assert other.id != first.id
    count = await db.scalar(
        select(func.count())
        .select_from(SolusEntry)
        .where(SolusEntry.project_id == project_id, SolusEntry.deleted_at.is_(None))
    )
    assert count == 2
    listed = await list_code_environments(db, project_id)
    assert sorted(e.name for e in listed) == ["robot-conda", "robot-venv"]


async def test_resolve_by_name_or_id_and_cross_project_is_404(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_id, user_id = await _project(client, alice_headers)
    bob_project, _ = await _project(client, bob_headers)
    entry = await upsert_code_environment(
        db,
        project_id,
        CodeEnvironment.model_validate(_env()),
        created_by=user_id,
        author="user",
    )
    await db.commit()
    assert (await resolve_environment(db, project_id, "robot-venv")).name == "robot-venv"
    assert (await resolve_environment(db, project_id, str(entry.id))).name == "robot-venv"
    for project, key in ((bob_project, "robot-venv"), (bob_project, str(entry.id))):
        with pytest.raises(APIError) as exc:
            await resolve_environment(db, project, key)
        assert exc.value.status_code == 404
    with pytest.raises(APIError):
        await resolve_environment(db, project_id, "nope")


# ------------------------------------------------------------------------ route


async def test_post_config_entry_into_code_section(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    url = f"/api/v1/projects/{project_id}/solus/code/entries"
    resp = await client.post(url, json={"kind": "config", "payload": _env()}, headers=alice_headers)
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["kind"] == "config"
    assert data["text"] == "robot-venv"
    assert data["payload"]["type"] == "venv"
    assert data["payload"]["provenance"] == "detected"
    # upsert: same (type, name) → same entry
    again = await client.post(
        url, json={"kind": "config", "payload": _env()}, headers=alice_headers
    )
    assert again.status_code == 201
    assert again.json()["data"]["id"] == data["id"]
    listing = await client.get(f"/api/v1/projects/{project_id}/solus", headers=alice_headers)
    assert [e["id"] for e in listing.json()["data"]["sections"]["code"]] == [data["id"]]

    bad = await client.post(
        url, json={"kind": "config", "payload": {"type": "venv"}}, headers=alice_headers
    )
    assert bad.status_code == 422
    hardware = await client.post(
        f"/api/v1/projects/{project_id}/solus/hardware/entries",
        json={"kind": "config", "payload": _env()},
        headers=alice_headers,
    )
    assert hardware.status_code == 422
    text_still_works = await client.post(
        url, json={"kind": "text", "text": "uses python 3.12"}, headers=alice_headers
    )
    assert text_still_works.status_code == 201
