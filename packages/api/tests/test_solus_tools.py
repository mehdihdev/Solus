"""Gated `.solus` write tools (SOLUSDEV-252 S5): `edit_solus_entry`, `delete_solus_entry`,
`set_hardware_config_field`. Every one is confirmation-gated with a Solus consent sentence
and a preview that shows the exact edit; foreign ids are NOT_FOUND (no existence oracle);
the registry's never-raises invariant holds on bad input."""

import io
import uuid
from typing import Any

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.tools import ToolCall, ToolRegistry
from solus_api.agent.tools.solus_tools import register_solus_write_tools
from solus_api.agent.tools.tool import Tool, ToolException
from solus_api.models import Artifact, GraphEntity, SolusEntry
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

TOOLS = ("edit_solus_entry", "delete_solus_entry", "set_hardware_config_field")
#: What the companion answered for `machine.list_environments` — the only source
#: the link tool may file from.
DETECTED = {
    "environments": [
        {
            "schema_version": 1,
            "type": "venv",
            "name": "solus-gate",
            "path": "/w/solus-gate",
            "interpreter": "/w/solus-gate/bin/python",
            "version": "3.12.3",
            "packages": [{"name": "six", "version": "1.17.0"}],
            "detected_on": {"os": "linux", "arch": "aarch64"},
            "provenance": "detected",
            "captured_at": "2026-09-08T01:00:00Z",
        }
    ],
    "unavailable": [],
}


async def _project(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    user = await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    return project["id"], user["id"]


async def _text_entry(
    client: AsyncClient, headers: dict[str, str], project_id: str, text: str
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/solus/errors/entries",
        json={"kind": "text", "text": text},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json()["data"])


async def _artifact_entry(
    client: AsyncClient, headers: dict[str, str], project_id: str
) -> dict[str, Any]:
    upload = await client.post(
        f"/api/v1/projects/{project_id}/artifacts",
        data={"media_type": "application/pdf"},
        files={"file": ("rules.pdf", io.BytesIO(b"%PDF-1.4 rules"), "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    resp = await client.post(
        f"/api/v1/projects/{project_id}/solus/docs/entries",
        json={
            "kind": "artifact",
            "artifact_id": upload.json()["data"]["artifact_id"],
            "name": "r.pdf",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json()["data"])


async def _robot(client: AsyncClient, headers: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/entities",
        headers=headers,
        json={"type": "physical_robot"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["id"])


async def _part(client: AsyncClient, headers: dict[str, str], project_id: str, robot: str) -> str:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/hardware/robots/{robot}/parts",
        headers=headers,
        json={"name": "elbow", "category": "actuators", "specs": {}, "lifecycle": "planned"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["entity"]["id"])


def _registry(
    app: FastAPI,
    engine: AsyncEngine,
    project_id: str,
    user_id: str,
    fetch_environments: Any = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    register_solus_write_tools(
        registry,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        store=app.state.artifact_store,
        project_id=uuid.UUID(project_id),
        user_id=uuid.UUID(user_id),
        fetch_environments=fetch_environments,
    )
    return registry


def _detector(payload: Any = DETECTED) -> Any:
    async def fetch(_environment: str | None = None) -> Any:
        return payload

    return fetch


def _tool(registry: ToolRegistry, name: str) -> Any:
    tool: Tool = next(t for t in registry.tools() if t.descriptor.name == name)
    return tool


async def _invoke(registry: ToolRegistry, name: str, args: dict[str, Any]) -> Any:
    return await registry.invoke(ToolCall(call_id="c", tool=name, args=args))


# ------------------------------------------------------------------ descriptors


def test_every_write_tool_is_gated_with_a_solus_consent_sentence_and_a_preview(
    app: FastAPI, engine: AsyncEngine
) -> None:
    registry = _registry(app, engine, str(uuid.uuid4()), str(uuid.uuid4()))
    assert {d.name for d in registry.list()} == set(TOOLS)
    for descriptor in registry.list():
        assert descriptor.requires_confirmation is True
        assert descriptor.consent_summary
        assert descriptor.description_trusted is True
        assert descriptor.params["additionalProperties"] is False
        assert not {"project_id", "user_id", "team_id"} & set(descriptor.params["properties"])
        assert callable(getattr(_tool(registry, descriptor.name), "preview", None))


# ------------------------------------------------------------------ edit / delete


async def test_edit_preview_shows_before_after_and_handler_edits_in_place(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    db: AsyncSession,
) -> None:
    project_id, user_id = await _project(client, alice_headers)
    entry = await _text_entry(client, alice_headers, project_id, "old text")
    registry = _registry(app, engine, project_id, user_id)
    args = {"entry_id": entry["id"], "text": "new text"}
    rows = await _tool(registry, "edit_solus_entry").preview(args)
    assert rows == [{"label": "Entry", "before": "old text", "after": "new text"}]
    result = await _invoke(registry, "edit_solus_entry", args)
    assert result.ok, result.error
    row = await db.get(SolusEntry, uuid.UUID(entry["id"]))
    assert row is not None and row.text == "new text" and row.author == "user"
    node = await db.get(GraphEntity, row.entity_id)
    assert node is not None and node.name == "new text"

    art = await _artifact_entry(client, alice_headers, project_id)
    conflict = await _invoke(registry, "edit_solus_entry", {"entry_id": art["id"], "text": "x"})
    assert conflict.ok is False and conflict.error is not None
    assert conflict.error.code.value == "invalid_args"


async def test_delete_previews_the_entry_and_removes_it_including_artifact_bytes(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    db: AsyncSession,
) -> None:
    project_id, user_id = await _project(client, alice_headers)
    registry = _registry(app, engine, project_id, user_id)
    text = await _text_entry(client, alice_headers, project_id, "gone soon")
    rows = await _tool(registry, "delete_solus_entry").preview({"entry_id": text["id"]})
    assert rows == [{"label": "Entry", "before": "gone soon", "after": None}]
    assert (await _invoke(registry, "delete_solus_entry", {"entry_id": text["id"]})).ok
    row = await db.get(SolusEntry, uuid.UUID(text["id"]))
    assert row is not None and row.deleted_at is not None

    art = await _artifact_entry(client, alice_headers, project_id)
    rows = await _tool(registry, "delete_solus_entry").preview({"entry_id": art["id"]})
    assert rows[0]["before"] == "r.pdf"
    assert (await _invoke(registry, "delete_solus_entry", {"entry_id": art["id"]})).ok
    artifact = await db.get(Artifact, uuid.UUID(art["artifact_id"]))
    assert artifact is not None and artifact.deleted_at is not None
    document = await db.get(GraphEntity, uuid.UUID(art["entity_id"]))
    assert document is not None and document.deleted_at is not None

    twice = await _invoke(registry, "delete_solus_entry", {"entry_id": art["id"]})
    assert twice.ok is False and twice.error is not None
    assert twice.error.code.value == "not_found"


async def test_foreign_entry_ids_are_not_found_and_bad_args_never_raise(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    db: AsyncSession,
) -> None:
    alice_project, _ = await _project(client, alice_headers)
    bob_project, bob_id = await _project(client, bob_headers)
    alice_entry = await _text_entry(client, alice_headers, alice_project, "alice's")
    registry = _registry(app, engine, bob_project, bob_id)
    for name, args in (
        ("edit_solus_entry", {"entry_id": alice_entry["id"], "text": "pwned"}),
        ("delete_solus_entry", {"entry_id": alice_entry["id"]}),
    ):
        result = await _invoke(registry, name, args)
        assert result.ok is False and result.error is not None
        assert result.error.code.value == "not_found"
    # A preview of a foreign entry raises → the gate falls back to argument rows.
    row = await db.get(SolusEntry, uuid.UUID(alice_entry["id"]))
    assert row is not None and row.text == "alice's" and row.deleted_at is None
    bad = await _invoke(registry, "edit_solus_entry", {"entry_id": "not-a-uuid", "text": "x"})
    assert bad.ok is False and bad.error is not None
    assert bad.error.code.value == "invalid_args"


# ------------------------------------------------------------ hardware config field


async def test_set_hardware_config_field_previews_and_writes_with_sol_provenance(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, engine: AsyncEngine
) -> None:
    project_id, user_id, robot, part = await _configured_pair(client, alice_headers)
    registry = _registry(app, engine, project_id, user_id)
    tool = _tool(registry, "set_hardware_config_field")

    args = {"robot_entity_id": robot, "path": "firmware.board_rev", "value": "B"}
    assert await tool.preview(args) == [
        {"label": "firmware.board_rev", "before": "(unset)", "after": "B"},
        {"label": "Config version", "before": "2", "after": "3"},
    ]
    result = await _invoke(registry, "set_hardware_config_field", args)
    assert result.ok, result.error
    assert result.value == {
        "robot_entity_id": robot,
        "path": "firmware.board_rev",
        "value": "B",
        "provenance": "sol",
    }
    assert await tool.preview({**args, "value": "C"}) == [
        {"label": "firmware.board_rev", "before": "B", "after": "C"},
        {"label": "Config version", "before": "3", "after": "4"},
    ]

    part_path = f"parts.{part}.firmware.baud"
    await tool.preview({"robot_entity_id": robot, "path": part_path, "value": 1000000})
    ok = await _invoke(
        registry,
        "set_hardware_config_field",
        {"robot_entity_id": robot, "path": part_path, "value": 1000000},
    )
    assert ok.ok, ok.error
    await tool.preview(
        {"robot_entity_id": robot, "path": f"parts.{part}.lifecycle", "value": "installed"}
    )
    lifecycle = await _invoke(
        registry,
        "set_hardware_config_field",
        {"robot_entity_id": robot, "path": f"parts.{part}.lifecycle", "value": "installed"},
    )
    assert lifecycle.ok, lifecycle.error

    config = await client.get(
        f"/api/v1/projects/{project_id}/hardware/robots/{robot}/config", headers=alice_headers
    )
    doc = config.json()["data"]["config"]
    assert doc["firmware"]["board_rev"] == "B"
    assert doc["parts"][part]["firmware"]["baud"] == 1000000
    assert doc["parts"][part]["lifecycle"] == "installed"
    assert doc["provenance"]["firmware.board_rev"] == {"by": "sol", "source": "sol turn"}
    assert doc["provenance"][part_path] == {"by": "sol", "source": "sol turn"}
    # a part's own record (user) is untouched by SOL setting one leaf beneath it
    assert doc["provenance"][f"parts.{part}"]["by"] == "user"


async def test_set_hardware_config_field_refuses_bad_paths_values_and_foreign_robots(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
) -> None:
    project_id, user_id = await _project(client, alice_headers)
    robot = await _robot(client, alice_headers, project_id)
    part = await _part(client, alice_headers, project_id, robot)
    registry = _registry(app, engine, project_id, user_id)

    async def refused(path: str, value: Any, code: str = "invalid_args") -> None:
        try:
            await _tool(registry, "set_hardware_config_field").preview(
                {"robot_entity_id": robot, "path": path, "value": value}
            )
        except ToolException as failure:
            assert failure.code.value == code
            return
        result = await _invoke(
            registry,
            "set_hardware_config_field",
            {"robot_entity_id": robot, "path": path, "value": value},
        )
        assert result.ok is False and result.error is not None, path
        assert result.error.code.value == code, (path, result.error)

    await refused("provenance.x", "y")  # reserved
    await refused("schema_version", 2)  # reserved
    await refused("entity_id", str(uuid.uuid4()))
    await refused("robot_entity_id", str(uuid.uuid4()))  # reserved
    await refused("protocol.driver_id", "x")  # intermediate container does not exist
    await refused("bus_map.0.address", "7")  # index into an empty list
    await refused(f"parts.{uuid.uuid4()}.lifecycle", "live", "not_found")  # unknown part
    await refused(f"parts.{part}.lifecycle", "bogus")  # fails HardwareConfig validation
    await refused("firmware.a.b", "c")  # a scalar cannot be descended into
    await refused("firmware", "flat")  # cannot replace a container with a scalar

    bob_project, bob_id = await _project(client, bob_headers)
    foreign = _registry(app, engine, bob_project, bob_id)
    with pytest.raises(ToolException) as failure:
        await _tool(foreign, "set_hardware_config_field").preview(
            {"robot_entity_id": robot, "path": "firmware.board_rev", "value": "B"}
        )
    assert failure.value.code.value == "not_found"


# ------------------------------------------------------------ link_environment


async def test_link_environment_is_registered_only_with_a_machine_to_ask(
    app: FastAPI, engine: AsyncEngine
) -> None:
    """No companion, no environments — and no tool offering to link one."""
    plain = _registry(app, engine, str(uuid.uuid4()), str(uuid.uuid4()))
    assert "link_environment" not in {d.name for d in plain.list()}
    wired = _registry(app, engine, str(uuid.uuid4()), str(uuid.uuid4()), _detector())
    descriptor = next(d for d in wired.list() if d.name == "link_environment")
    assert descriptor.requires_confirmation is True and descriptor.consent_summary
    assert "machine.list_environments" not in descriptor.description
    assert "code.probe_environment" in descriptor.description
    assert "environment" in descriptor.description


async def test_link_environment_files_what_the_machine_reported(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
) -> None:
    """The model names WHICH environment; every recorded fact comes from the
    companion's own answer. `.solus` says so: never a package or a path that was
    not observed."""
    project_id, user_id = await _project(client, alice_headers)
    registry = _registry(app, engine, project_id, user_id, _detector())
    result = await _invoke(
        registry, "link_environment", {"name": "solus-gate", "packages": ["invented"]}
    )
    assert result.ok is False  # `packages` is not an argument this tool takes

    result = await _invoke(registry, "link_environment", {"name": "solus-gate"})
    assert result.ok is True, result.error
    from solus_api.services.code_env import list_code_environments

    (env,) = await list_code_environments(db, uuid.UUID(project_id))
    assert env.name == "solus-gate" and env.interpreter == "/w/solus-gate/bin/python"
    assert [(p.name, p.version) for p in env.packages] == [("six", "1.17.0")]
    # SET by Solus, not accepted from the companion, which could claim `user`.
    assert env.provenance.value == "sol"
    from sqlalchemy import select

    entry = await db.scalar(
        select(SolusEntry).where(SolusEntry.project_id == uuid.UUID(project_id))
    )
    assert entry is not None and entry.author == "sol"


async def test_relinking_updates_the_same_entry(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
) -> None:
    project_id, user_id = await _project(client, alice_headers)
    registry = _registry(app, engine, project_id, user_id, _detector())
    assert (await _invoke(registry, "link_environment", {"name": "solus-gate"})).ok
    assert (await _invoke(registry, "link_environment", {"name": "solus-gate"})).ok
    from solus_api.services.code_env import list_code_environments

    assert len(await list_code_environments(db, uuid.UUID(project_id))) == 1


async def test_link_environment_refuses_a_name_the_machine_does_not_report(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
) -> None:
    project_id, user_id = await _project(client, alice_headers)
    registry = _registry(app, engine, project_id, user_id, _detector())
    result = await _invoke(registry, "link_environment", {"name": "sim"})
    assert result.ok is False and result.error is not None
    from solus_api.services.code_env import list_code_environments

    assert await list_code_environments(db, uuid.UUID(project_id)) == []


async def test_link_environment_preview_shows_the_observed_environment(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], engine: AsyncEngine
) -> None:
    project_id, user_id = await _project(client, alice_headers)
    registry = _registry(app, engine, project_id, user_id, _detector())
    rows = await _tool(registry, "link_environment").preview({"name": "solus-gate"})
    shown = {row["label"]: row["after"] for row in rows}
    assert shown["type"] == "venv" and shown["interpreter"] == "/w/solus-gate/bin/python"
    # Identities, not a count: the gate compares these rows again at decision
    # time, so an install that leaves the COUNT unchanged must still move a row.
    assert "six 1.17.0" in shown["packages"]


async def test_link_environment_never_raises_on_a_broken_machine_answer(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], engine: AsyncEngine
) -> None:
    """The companion's answer is untrusted input: a shape change must be a failed
    result, never an exception out of the registry."""
    project_id, user_id = await _project(client, alice_headers)
    for payload in ({"environments": "many"}, {"environments": [{"type": "venv"}]}, None):
        registry = _registry(app, engine, project_id, user_id, _detector(payload))
        result = await _invoke(registry, "link_environment", {"name": "solus-gate"})
        assert result.ok is False and result.error is not None


async def test_link_environment_refuses_an_ambiguous_name(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
) -> None:
    """A conda env and a workspace venv can share a name. Picking one silently
    links the wrong environment and then duplicates it on the next link."""
    project_id, user_id = await _project(client, alice_headers)
    twin = dict(
        DETECTED["environments"][0], type="conda", path=None, interpreter="/conda/bin/python"
    )
    registry = _registry(
        app,
        engine,
        project_id,
        user_id,
        _detector({"environments": [DETECTED["environments"][0], twin], "unavailable": []}),
    )
    result = await _invoke(registry, "link_environment", {"name": "solus-gate"})
    assert result.ok is False and result.error is not None
    from solus_api.services.code_env import list_code_environments

    assert await list_code_environments(db, uuid.UUID(project_id)) == []


async def test_link_environment_rejects_a_machine_answer_it_cannot_read(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], engine: AsyncEngine
) -> None:
    """The named environment is found but its description is not a CodeEnvironment."""
    project_id, user_id = await _project(client, alice_headers)
    registry = _registry(
        app,
        engine,
        project_id,
        user_id,
        _detector({"environments": [{"name": "solus-gate", "type": "venv"}], "unavailable": []}),
    )
    result = await _invoke(registry, "link_environment", {"name": "solus-gate"})
    assert result.ok is False and result.error is not None
    assert "code environment" in result.error.message


async def _configured_pair(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[str, str, str, str]:
    project, user = await _project(client, headers)
    robot = await _robot(client, headers, project)
    part = await _part(client, headers, project, robot)
    for subject, owner in ((robot, True), (part, False)):
        endpoint = f"/api/v1/projects/{project}/hardware/entities/{subject}/config"
        version = (await client.get(endpoint, headers=headers)).json()["data"]["version"]
        document = {
            "schema_version": 2,
            "entity_id": subject,
            "identity": {
                "kind": "usb_serial",
                "binding": "fixture-owner" if owner else "fixture-child",
            },
            "protocol": {"driver_id": "fixture", "params": {"baud": 115200}},
            "bus_map": [{"protocol": "fixture", "address": "1", "part_entity_id": part}]
            if owner
            else [],
            "component": {
                "firmware": {"version": "v1"},
                "calibration": {"values": {"offset": 7}},
                "limits": {"values": {"max": 12}},
                "telemetry": [{"name": "fixture", "unit": "deg"}],
            },
            "provenance": {
                key: {"by": "user"} for key in ("identity", "protocol", "bus_map", "component")
            },
        }
        response = await client.put(
            endpoint, headers={**headers, "If-Match": str(version)}, json={"config": document}
        )
        assert response.status_code == 200, response.text
    return project, user, robot, part


@pytest.mark.parametrize("stale", [False, True])
async def test_confirmed_field_edit_is_direct_v2_and_refuses_changed_versions(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    stale: bool,
) -> None:
    from solus_api.agent.confirmations import decide_confirmation, request_confirmation
    from solus_api.agent.tools import solus_tools
    from solus_api.models import ConfirmationStatus, Project, ToolConfirmation

    project, user, robot, part = await _configured_pair(client, alice_headers)

    async def read(subject: str) -> dict[str, Any]:
        response = await client.get(
            f"/api/v1/projects/{project}/hardware/entities/{subject}/config", headers=alice_headers
        )
        return dict(response.json()["data"])

    before, child_before = await read(robot), await read(part)
    if not stale:

        async def forbidden(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("Compatibility config round trip is forbidden")

        monkeypatch.setattr(solus_tools, "ensure_config", forbidden, raising=False)
        monkeypatch.setattr(solus_tools, "put_config", forbidden, raising=False)
    registry = _registry(app, engine, project, user)
    project_row = await db.get(Project, uuid.UUID(project))
    assert project_row is not None
    call = ToolCall(
        call_id="field",
        tool="set_hardware_config_field",
        args={"robot_entity_id": robot, "path": "firmware.version", "value": "v2"},
    )
    parked = await request_confirmation(
        db,
        registry,
        call,
        project_id=uuid.UUID(project),
        team_id=project_row.team_id,
        user_id=uuid.UUID(user),
    )
    assert parked is not None and parked.confirmation_id is not None
    await db.commit()
    assert await read(robot) == before and await read(part) == child_before
    if stale:
        document = before["config"]
        document["protocol"]["params"]["baud"] = 9600
        response = await client.put(
            f"/api/v1/projects/{project}/hardware/entities/{robot}/config",
            headers={**alice_headers, "If-Match": str(before["version"])},
            json={"config": document},
        )
        assert response.status_code == 200, response.text
    result = await decide_confirmation(
        db,
        registry,
        parked.confirmation_id,
        approve=True,
        project_id=uuid.UUID(project),
        user_id=uuid.UUID(user),
    )
    await db.commit()
    actual = await read(robot)
    if stale:
        assert not result.ok
        row = await db.get(ToolConfirmation, parked.confirmation_id)
        assert row is not None and row.status is ConfirmationStatus.STALE
        assert actual["config"]["component"]["firmware"]["version"] == "v1"
    else:
        assert result.ok, result.error
        expected = before["config"]
        expected["component"]["firmware"]["version"] = "v2"
        expected["provenance"]["component.firmware.version"] = {"by": "sol", "source": "sol turn"}
        assert actual["config"] == expected
        assert (
            actual["entry_id"] == before["entry_id"] and actual["version"] == before["version"] + 1
        )
    assert await read(part) == child_before


async def test_field_preview_on_absent_config_never_locks_or_creates(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.agent.tools.tool import ToolException
    from solus_api.hardware import store
    from sqlalchemy import func, select

    project, user = await _project(client, alice_headers)
    robot = await _robot(client, alice_headers, project)
    before = await db.scalar(select(func.count()).select_from(SolusEntry))
    await db.commit()

    async def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Preview may not lock")

    monkeypatch.setattr(store, "lock_project", forbidden)
    with pytest.raises(ToolException):
        await _tool(_registry(app, engine, project, user), "set_hardware_config_field").preview(
            {"robot_entity_id": robot, "path": "firmware.version", "value": "v2"}
        )
    assert await db.scalar(select(func.count()).select_from(SolusEntry)) == before


async def test_field_write_refuses_a_version_changed_before_its_project_lock(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solus_api.agent.tools import solus_tools

    project, user, robot, _ = await _configured_pair(client, alice_headers)
    endpoint = f"/api/v1/projects/{project}/hardware/entities/{robot}/config"
    saved = (await client.get(endpoint, headers=alice_headers)).json()["data"]
    from solus_api.services.solus_graph import lock_project as original

    async def concurrent_edit(*args: Any, **kwargs: Any) -> Any:
        document = saved["config"]
        document["protocol"]["params"]["baud"] = 9600
        changed = await client.put(
            endpoint,
            headers={**alice_headers, "If-Match": str(saved["version"])},
            json={"config": document},
        )
        assert changed.status_code == 200, changed.text
        return await original(*args, **kwargs)

    monkeypatch.setattr(solus_tools, "lock_project", concurrent_edit)
    registry = _registry(app, engine, project, user)
    await _tool(registry, "set_hardware_config_field").preview(
        {"robot_entity_id": robot, "path": "firmware.version", "value": "v2"}
    )
    result = await _invoke(
        registry,
        "set_hardware_config_field",
        {"robot_entity_id": robot, "path": "firmware.version", "value": "v2"},
    )
    assert not result.ok and result.error is not None
    actual = (await client.get(endpoint, headers=alice_headers)).json()["data"]
    assert actual["config"]["component"]["firmware"]["version"] == "v1"
    assert actual["config"]["protocol"]["params"]["baud"] == 9600
    assert actual["version"] == saved["version"] + 1


async def test_field_refuses_change_after_final_approval_preview(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, engine: AsyncEngine
) -> None:
    project, user, robot, _ = await _configured_pair(client, alice_headers)
    registry = _registry(app, engine, project, user)
    args = {"robot_entity_id": robot, "path": "firmware.version", "value": "v2"}
    await _tool(registry, "set_hardware_config_field").preview(args)
    endpoint = f"/api/v1/projects/{project}/hardware/entities/{robot}/config"
    saved = (await client.get(endpoint, headers=alice_headers)).json()["data"]
    saved["config"]["protocol"]["params"]["baud"] = 9600
    changed = await client.put(
        endpoint,
        headers={**alice_headers, "If-Match": str(saved["version"])},
        json={"config": saved["config"]},
    )
    assert changed.status_code == 200, changed.text
    result = await _invoke(registry, "set_hardware_config_field", args)
    assert not result.ok
    actual = (await client.get(endpoint, headers=alice_headers)).json()["data"]
    assert actual["config"] == saved["config"]


async def test_field_write_without_matching_preview_is_refused(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, engine: AsyncEngine
) -> None:
    project, user, robot, _ = await _configured_pair(client, alice_headers)
    registry = _registry(app, engine, project, user)
    endpoint = f"/api/v1/projects/{project}/hardware/entities/{robot}/config"
    before = (await client.get(endpoint, headers=alice_headers)).json()["data"]
    args = {"robot_entity_id": robot, "path": "firmware.version", "value": "v2"}
    for prior_preview in (False, True):
        if prior_preview:
            await _tool(registry, "set_hardware_config_field").preview(
                {**args, "value": "different"}
            )
        result = await _invoke(registry, "set_hardware_config_field", args)
        assert not result.ok and result.error is not None
        assert result.error.code.value == "unauthorized"
    assert (await client.get(endpoint, headers=alice_headers)).json()["data"] == before


async def test_child_field_preserves_its_connection_and_rejects_another_owners_part(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, engine: AsyncEngine
) -> None:
    project, user, robot, part = await _configured_pair(client, alice_headers)
    registry = _registry(app, engine, project, user)
    tool = _tool(registry, "set_hardware_config_field")
    owner_url = f"/api/v1/projects/{project}/hardware/entities/{robot}/config"
    child_url = f"/api/v1/projects/{project}/hardware/entities/{part}/config"
    owner_before = (await client.get(owner_url, headers=alice_headers)).json()["data"]
    child_before = (await client.get(child_url, headers=alice_headers)).json()["data"]
    other_robot = await _robot(client, alice_headers, project)
    other_part = await _part(client, alice_headers, project, other_robot)
    with pytest.raises(ToolException) as failure:
        await tool.preview(
            {"robot_entity_id": robot, "path": f"parts.{other_part}.lifecycle", "value": "live"}
        )
    assert failure.value.code.value == "invalid_args"
    args = {"robot_entity_id": robot, "path": f"parts.{part}.firmware.version", "value": "v2"}
    await tool.preview(args)
    result = await _invoke(registry, "set_hardware_config_field", args)
    assert result.ok, result.error
    actual = (await client.get(child_url, headers=alice_headers)).json()["data"]
    expected = child_before["config"]
    expected["component"]["firmware"]["version"] = "v2"
    expected["provenance"]["component.firmware.version"] = {"by": "sol", "source": "sol turn"}
    assert actual["config"] == expected and actual["entry_id"] == child_before["entry_id"]
    assert actual["version"] == child_before["version"] + 1
    assert (await client.get(owner_url, headers=alice_headers)).json()["data"] == owner_before


async def test_link_environment_probes_the_named_target(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
) -> None:
    from solus_api.services.code_env import list_code_environments

    project_id, user_id = await _project(client, alice_headers)
    requested: list[str | None] = []

    async def fetch(environment: str | None = None) -> dict[str, Any]:
        requested.append(environment)
        return (
            {
                "environments": [
                    {
                        "name": "sim",
                        "type": "venv",
                        "path": "sim",
                        "interpreter": "sim/bin/python",
                        "version": "3.12",
                        "provenance": "detected",
                        "captured_at": "2026-09-10T12:00:00Z",
                        "packages": [{"name": "mujoco", "version": "3.2.0"}],
                    }
                ]
            }
            if environment == "sim"
            else {"environments": []}
        )

    registry = _registry(app, engine, project_id, user_id, fetch)
    tool = _tool(registry, "link_environment")
    rows = await tool.preview({"name": "sim"})
    assert any(row["after"] == "sim" for row in rows)
    result = await _invoke(registry, "link_environment", {"name": "sim"})
    assert result.ok, result.error
    assert requested and all(target == "sim" for target in requested)
    (saved,) = await list_code_environments(db, uuid.UUID(project_id))
    assert saved.name == "sim" and saved.packages[0].name == "mujoco"
