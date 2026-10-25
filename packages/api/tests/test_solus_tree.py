"""SOLUSDEV-320 T5a: the seven-section `.solus` tree (docs/api/solus.md §1–§3.2, §7).

Subsection validation per section, the lazily built section/subsection nodes, entries
hanging under their subsection node, the per-section cap that ignores entity-bound
configs, error-filing dedupe, and `PATCH …/payload` per (section, subsection) cell."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import me
from httpx import AsyncClient
from solus_api.agent.errors_filing import error_dedupe_key, file_tool_error
from solus_api.agent.tools import ToolCall, ToolDescriptor, ToolError, ToolErrorCode, ToolResult
from solus_api.agent.tools.solus_entry import ADD_SOLUS_ENTRY_DESCRIPTOR
from solus_api.core.errors import APIError
from solus_api.hardware.config import EntityHardwareConfig
from solus_api.hardware.store import put_entity_config
from solus_api.models import DataEvent, GraphEdge, GraphEntity, SolusEntry, SolusSection, User
from solus_api.services.code_env import CodeEnvironment, upsert_code_environment
from solus_api.services.physical_robots import PhysicalRobotService
from solus_api.services.solus_config import (
    SECTION_LABELS,
    SUBSECTIONS,
    add_text_entry,
    validate_subsection,
)
from solus_api.services.solus_payloads import MAX_LINKED_IDS, ErrorMeta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_solus_config import FIXED_SUBSECTIONS, LABELS, SECTIONS, _get, _post, _project, _upload

# A fixed id: a parametrize id must collect identically on every xdist worker.
MEMBER = uuid.UUID("01a00743-7ae8-7d62-9d14-271b40253254").hex


# ------------------------------------------------------------------ vocabulary


def test_labels_and_fixed_subsections_are_the_route_plans() -> None:
    assert {s.value: label for s, label in SECTION_LABELS.items()} == LABELS
    assert {s.value: list(subs) for s, subs in SUBSECTIONS.items() if subs} == {
        key: list(value) for key, value in FIXED_SUBSECTIONS.items()
    }
    assert ADD_SOLUS_ENTRY_DESCRIPTOR.params["properties"]["section"]["enum"] == list(SECTIONS)


@pytest.mark.parametrize(
    "section,raw,expected",
    [
        ("constraints", "style", "style"),
        ("constraints", None, None),
        ("constraints", "foo", 422),
        ("documentation", "datasheets", "datasheets"),
        ("environment", "hardware", "hardware"),
        ("goals", None, "general"),
        ("goals", "drivetrain-v2", "drivetrain-v2"),
        ("goals", "Drivetrain", 422),
        ("goals", "-bad", 422),
        ("goals", "a" * 33, 422),
        ("errors", None, None),
        ("errors", "x", 422),
        ("history", None, 422),
        ("history", "x", 422),
        ("members", MEMBER, MEMBER),
        ("members", None, 422),
        ("members", "not-hex", 422),
    ],
)
def test_subsection_validation_table(section: str, raw: str | None, expected: Any) -> None:
    if expected == 422:
        with pytest.raises(APIError) as err:
            validate_subsection(SolusSection(section), raw)
        assert err.value.status_code == 422 and err.value.code == "validation_error"
    else:
        assert validate_subsection(SolusSection(section), raw) == expected


# --------------------------------------------------------------------- routes


async def test_get_keys_are_the_seven_and_old_names_are_404(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    data = await _get(client, alice_headers, project_id)
    assert list(data["sections"]) == list(SECTIONS)
    for old in ("hardware", "details", "docs", "code"):
        resp = await _post(client, alice_headers, project_id, old, {"kind": "text", "text": "x"})
        assert resp.status_code == 404, old


async def test_history_and_members_take_no_post_and_bad_subsections_are_422(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    project_id, _ = await _project(client, alice_headers)
    body = {"kind": "text", "text": "x"}
    history = await _post(client, alice_headers, project_id, "history", body)
    assert history.status_code == 422 and "history owns no entries" in history.text
    members = await _post(
        client, alice_headers, project_id, "members", {**body, "subsection": MEMBER}
    )
    assert members.status_code == 422
    for section, subsection in (("constraints", "foo"), ("errors", "x"), ("goals", "Bad")):
        resp = await _post(
            client, alice_headers, project_id, section, {**body, "subsection": subsection}
        )
        assert resp.status_code == 422, (section, subsection)
        assert resp.json()["error"]["code"] == "validation_error"


async def test_entries_attach_under_their_subsection_node(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    style = (
        await _post(
            client,
            alice_headers,
            project_id,
            "constraints",
            {"kind": "text", "text": "snake_case everywhere", "subsection": "style"},
        )
    ).json()["data"]
    assert style["subsection"] == "style"
    node = await db.get(GraphEntity, uuid.UUID(style["entity_id"]))
    assert node is not None and node.kind == "solus_constraint"
    assert node.attrs == {
        "solus_entry_id": style["id"],
        "section": "constraints",
        "subsection": "style",
    }
    parent_edge = await db.scalar(
        select(GraphEdge).where(GraphEdge.dst_id == node.id, GraphEdge.deleted_at.is_(None))
    )
    assert parent_edge is not None
    parent = await db.get(GraphEntity, parent_edge.src_id)
    assert parent is not None and parent.kind == "solus_subsection"
    assert parent.attrs == {"section": "constraints", "subsection": "style"}
    assert parent_edge.attrs["section"] == "constraints"
    assert parent_edge.attrs["subsection"] == "style"

    # A free goals slug gets its subsection node on first use, under the goals section.
    goal = (
        await _post(
            client,
            alice_headers,
            project_id,
            "goals",
            {"kind": "text", "text": "Reach 48 V", "subsection": "drivetrain"},
        )
    ).json()["data"]
    goal_node = await db.get(GraphEntity, uuid.UUID(goal["entity_id"]))
    assert goal_node is not None and goal_node.kind == "solus_goal"
    slug = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == uuid.UUID(project_id),
            GraphEntity.kind == "solus_subsection",
            GraphEntity.attrs["subsection"].astext == "drivetrain",
        )
    )
    assert slug is not None and slug.attrs["section"] == "goals" and slug.name == "drivetrain"
    section = await db.scalar(
        select(GraphEntity).where(
            GraphEntity.project_id == uuid.UUID(project_id),
            GraphEntity.kind == "solus_section",
            GraphEntity.attrs["section"].astext == "goals",
        )
    )
    assert section is not None
    edges = {
        (e.src_id, e.dst_id)
        for e in await db.scalars(
            select(GraphEdge).where(
                GraphEdge.project_id == uuid.UUID(project_id), GraphEdge.deleted_at.is_(None)
            )
        )
    }
    assert (section.id, slug.id) in edges and (slug.id, goal_node.id) in edges
    assert (section.id, goal_node.id) not in edges

    # An artifact filed without a subsection hangs off the section node itself.
    artifact_id = await _upload(client, alice_headers, project_id)
    doc = (
        await _post(
            client,
            alice_headers,
            project_id,
            "documentation",
            {"kind": "artifact", "artifact_id": artifact_id, "name": "rules.pdf"},
        )
    ).json()["data"]
    assert doc["subsection"] is None and doc["payload"] is None
    listing = await _get(client, alice_headers, project_id)
    assert [e["subsection"] for e in listing["sections"]["constraints"]] == ["style"]
    assert [e["subsection"] for e in listing["sections"]["goals"]] == ["drivetrain"]


async def test_members_entries_file_through_the_service_only(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    entry = await add_text_entry(
        db,
        uuid.UUID(project_id),
        SolusSection.MEMBERS,
        "prefers metric",
        author="user",
        created_by=None,
        subsection=MEMBER,
    )
    await db.commit()
    assert entry.subsection == MEMBER
    with pytest.raises(APIError) as err:
        await add_text_entry(
            db, uuid.UUID(project_id), SolusSection.HISTORY, "x", author="user", created_by=None
        )
    assert err.value.status_code == 422 and "history owns no entries" in err.value.message
    await db.rollback()
    listing = await _get(client, alice_headers, project_id)
    assert [e["subsection"] for e in listing["sections"]["members"]] == [MEMBER]


async def test_section_cap_ignores_entity_bound_configs(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("solus_api.services.solus_config.MAX_ENTRIES_PER_SECTION", 1)
    project_id, _ = await _project(client, alice_headers)
    user = await me(client, alice_headers)
    pid = uuid.UUID(project_id)
    robot = await PhysicalRobotService(db).create(pid, "Rover")
    config = EntityHardwareConfig.model_validate(
        {"schema_version": 2, "entity_id": str(robot.id), "provenance": {}}
    )
    entry = await put_entity_config(
        db, pid, robot, config, expected_version=0, created_by=uuid.UUID(user["id"])
    )
    await db.commit()
    assert entry.section is SolusSection.ENVIRONMENT and entry.subsection == "hardware"
    node = await db.get(GraphEntity, entry.entity_id)
    assert node is not None and node.kind == "hardware_config"
    # The bound config does not count: one free slot remains in `environment`.
    first = await _post(
        client, alice_headers, project_id, "environment", {"kind": "text", "text": "ubuntu 24.04"}
    )
    assert first.status_code == 201, first.text
    second = await _post(
        client, alice_headers, project_id, "environment", {"kind": "text", "text": "ros jazzy"}
    )
    assert second.status_code == 422
    listing = await _get(client, alice_headers, project_id)
    # P5: the system's `spec`/`divergences` CONFIGs are bound too and never count.
    by_cell = {(e["subsection"], e["kind"]): e for e in listing["sections"]["environment"]}
    assert set(by_cell) == {
        ("hardware", "config"),
        ("spec", "config"),
        ("divergences", "config"),
        (None, "text"),
    }
    assert by_cell[("hardware", "config")]["payload"]["schema_version"] == 2


async def test_machine_bound_code_environment_upserts_by_subject(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    pid = uuid.UUID(project_id)
    machine = GraphEntity(
        project_id=pid, kind="machine", domain="project", origin="manual", name="laptop"
    )
    db.add(machine)
    await db.flush()
    env = CodeEnvironment.model_validate(
        {
            "type": "venv",
            "name": "a",
            "path": "/a",
            "provenance": "detected",
            "captured_at": datetime.now(UTC).isoformat(),
        }
    )
    first = await upsert_code_environment(
        db, pid, env, created_by=None, author="user", configured_entity_id=machine.id
    )
    other = env.model_copy(update={"name": "b", "path": "/b"})
    second = await upsert_code_environment(
        db, pid, other, created_by=None, author="user", configured_entity_id=machine.id
    )
    unbound = await upsert_code_environment(db, pid, env, created_by=None, author="user")
    await db.commit()
    assert second.id == first.id and second.payload is not None
    assert second.payload["path"] == "/b" and second.configured_entity_id == machine.id
    assert unbound.id != first.id and unbound.configured_entity_id is None
    assert first.subsection == "software" and first.section is SolusSection.ENVIRONMENT


# --------------------------------------------------------------- errors dedupe

FILING = ToolDescriptor(
    name="companion.run_command",
    description="Runs a command on the person's machine.",
    params={"type": "object"},
    returns={"type": "object"},
    files_errors=True,
)
ENTITY = uuid.uuid4()
CALL = ToolCall(
    tool=FILING.name, call_id="c1", args={"command": ["pio", "run"], "entity_id": str(ENTITY)}
)
FAILED = ToolResult.failure("c1", ToolError(code=ToolErrorCode.TOOL_ERROR, message="exit 1"))


async def _file(engine: AsyncEngine, project_id: uuid.UUID, user_id: uuid.UUID, **kw: Any) -> None:
    await file_tool_error(
        async_sessionmaker(engine, expire_on_commit=False),
        project_id=project_id,
        user_id=user_id,
        call=kw.get("call", CALL),
        result=kw.get("result", FAILED),
        descriptor=FILING,
        executed=True,
    )


async def _consent(db: AsyncSession, user_id: uuid.UUID) -> None:
    user = await db.get(User, user_id)
    assert user is not None
    user.data_collection_consent = True
    await db.commit()


async def _events(db: AsyncSession, project_id: uuid.UUID, event_type: str) -> list[DataEvent]:
    rows = await db.scalars(
        select(DataEvent)
        .where(DataEvent.project_id == project_id, DataEvent.event_type == event_type)
        .order_by(DataEvent.created_at)
    )
    return list(rows)


async def _errors(db: AsyncSession, project_id: uuid.UUID) -> list[SolusEntry]:
    db.expire_all()
    rows = await db.scalars(
        select(SolusEntry)
        .where(SolusEntry.project_id == project_id, SolusEntry.section == SolusSection.ERRORS)
        .order_by(SolusEntry.created_at)
    )
    return list(rows)


async def test_errors_dedupe_counts_recurs_and_splits_on_code(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, _ = await _project(client, alice_headers)
    user_id = uuid.UUID((await me(client, alice_headers))["id"])
    pid = uuid.UUID(project_id)
    await _consent(db, user_id)
    db.add(
        GraphEntity(
            id=ENTITY, project_id=pid, kind="part", domain="project", origin="manual", name="IMU"
        )
    )
    await db.commit()
    await _file(engine, pid, user_id)
    (entry,) = await _errors(db, pid)
    meta = ErrorMeta.model_validate(entry.payload)
    assert meta.count == 1 and meta.status == "open" and meta.entity_id == ENTITY
    (added,) = await _events(db, pid, "solus.entry_added")
    assert added.payload["entry_id"] == str(entry.id) and added.payload["subsection"] is None
    assert meta.dedupe_key == error_dedupe_key(
        FILING.name, f'{{"command": ["pio", "run"], "entity_id": "{ENTITY}"}}', "tool_error"
    )
    assert meta.machine_id is None and meta.fix_ref is None

    await _file(engine, pid, user_id)
    (same,) = await _errors(db, pid)
    bumped = ErrorMeta.model_validate(same.payload)
    assert same.id == entry.id and bumped.count == 2 and bumped.status == "open"
    assert bumped.last_seen > meta.last_seen and bumped.first_seen == meta.first_seen
    (updated,) = await _events(db, pid, "solus.entry_updated")
    assert updated.payload["entry_id"] == str(entry.id) and updated.payload["tool"] == FILING.name
    assert len(await _events(db, pid, "solus.entry_added")) == 1

    timed_out = ToolResult.failure("c1", ToolError(code=ToolErrorCode.TIMEOUT, message="slow"))
    await _file(engine, pid, user_id, result=timed_out)
    rows = await _errors(db, pid)
    assert len(rows) == 2 and ErrorMeta.model_validate(rows[1].payload).count == 1

    same.payload = {**(same.payload or {}), "status": "resolved"}
    await db.commit()
    await _file(engine, pid, user_id)
    rows = await _errors(db, pid)
    recurring = ErrorMeta.model_validate(rows[0].payload)
    assert len(rows) == 2 and recurring.status == "recurring" and recurring.count == 3
    listing = await _get(client, alice_headers, project_id)
    assert listing["sections"]["errors"][0]["payload"]["status"] == "recurring"

    # A model-proposed entity id outside the project is not stored as a reference.
    foreign = ToolCall(
        tool=FILING.name, call_id="c2", args={"command": ["ls"], "entity_id": str(uuid.uuid4())}
    )
    await _file(engine, pid, user_id, call=foreign)
    rows = await _errors(db, pid)
    assert len(rows) == 3 and ErrorMeta.model_validate(rows[2].payload).entity_id is None


# ---------------------------------------------------------------- payload PATCH


async def _patch_payload(
    client: AsyncClient, headers: dict[str, str], project_id: str, entry_id: str, payload: Any
) -> Any:
    return await client.patch(
        f"/api/v1/projects/{project_id}/solus/entries/{entry_id}/payload",
        json={"payload": payload},
        headers=headers,
    )


async def test_payload_patch_validates_per_cell_and_refuses_config_and_artifact(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    project_id, _ = await _project(client, alice_headers)
    await _consent(db, uuid.UUID((await me(client, alice_headers))["id"]))
    goal = (
        await _post(client, alice_headers, project_id, "goals", {"kind": "text", "text": "48 V"})
    ).json()["data"]
    run = GraphEntity(
        project_id=uuid.UUID(project_id), kind="bench_run", domain="project", name="r"
    )
    db.add(run)
    await db.commit()
    run_id = str(run.id)
    ok = await _patch_payload(
        client,
        alice_headers,
        project_id,
        goal["id"],
        {"status": "met", "linked_run_ids": [run_id]},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["payload"] == {
        "status": "met",
        "owner": None,
        "linked_conversation_ids": [],
        "linked_entity_ids": [],
        "linked_run_ids": [run_id],
    }
    (event,) = await _events(db, uuid.UUID(project_id), "solus.entry_updated")
    assert event.payload == {
        "entry_id": goal["id"],
        "section": "goals",
        "subsection": "general",
        "kind": "text",
    }
    too_many = {"linked_run_ids": [str(uuid.uuid4())] * (MAX_LINKED_IDS + 1)}
    for bad in ({"status": "done"}, {"evil": 1}, {"linked_run_ids": ["nope"]}, too_many):
        resp = await _patch_payload(client, alice_headers, project_id, goal["id"], bad)
        assert resp.status_code == 422, bad
    listing = await _get(client, alice_headers, project_id)
    assert listing["sections"]["goals"][0]["payload"]["status"] == "met"  # bad PATCHes kept it

    style = (
        await _post(
            client,
            alice_headers,
            project_id,
            "constraints",
            {"kind": "text", "text": "mass", "subsection": "style"},
        )
    ).json()["data"]
    constraint = {"quantity": "mass", "limit": 2.5, "unit": "kg", "comparator": "<="}
    ok = await _patch_payload(client, alice_headers, project_id, style["id"], constraint)
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["payload"] == {
        **constraint,
        "scope_entity_ids": [],
        "source_entry_id": None,
        "excluded_suppliers": [],
        "required_certifications": [],
    }
    missing = await _patch_payload(
        client, alice_headers, project_id, style["id"], {"quantity": "mass"}
    )
    assert missing.status_code == 422
    nan = await client.patch(  # httpx refuses NaN; Python's json.loads on the server does not
        f"/api/v1/projects/{project_id}/solus/entries/{style['id']}/payload",
        content=json.dumps({"payload": {**constraint, "limit": float("nan")}}),
        headers={**alice_headers, "content-type": "application/json"},
    )
    assert nan.status_code == 422  # JSONB has no NaN; it fails validation, not the flush
    budgets = (
        await _post(
            client,
            alice_headers,
            project_id,
            "constraints",
            {"kind": "text", "text": "note", "subsection": "budgets"},
        )
    ).json()["data"]
    no_model = await _patch_payload(client, alice_headers, project_id, budgets["id"], constraint)
    assert no_model.status_code == 422

    error = (
        await _post(client, alice_headers, project_id, "errors", {"kind": "text", "text": "boom"})
    ).json()["data"]
    now = datetime.now(UTC).isoformat()
    meta = {
        "dedupe_key": "a" * 40,
        "count": 1,
        "status": "resolved",
        "first_seen": now,
        "last_seen": now,
    }
    assert (
        await _patch_payload(client, alice_headers, project_id, error["id"], meta)
    ).status_code == 200

    config = (
        await _post(
            client,
            alice_headers,
            project_id,
            "environment",
            {
                "kind": "config",
                "subsection": "software",
                "payload": {
                    "type": "venv",
                    "name": "v",
                    "provenance": "user",
                    "captured_at": now,
                },
            },
        )
    ).json()["data"]
    conflict = await _patch_payload(client, alice_headers, project_id, config["id"], {"x": 1})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "conflict"
    artifact_id = await _upload(client, alice_headers, project_id)
    doc = (
        await _post(
            client,
            alice_headers,
            project_id,
            "documentation",
            {"kind": "artifact", "artifact_id": artifact_id, "name": "a.pdf"},
        )
    ).json()["data"]
    assert (
        await _patch_payload(client, alice_headers, project_id, doc["id"], {})
    ).status_code == 409
    await me(client, bob_headers)
    foreign = await _patch_payload(client, bob_headers, project_id, goal["id"], {"status": "open"})
    assert foreign.status_code == 404


async def test_linked_run_ids_sync_verified_by_edges(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project_id, _ = await _project(client, alice_headers)
    pid = uuid.UUID(project_id)
    run = GraphEntity(project_id=pid, kind="bench_run", domain="project", origin="manual", name="r")
    db.add(run)
    await db.commit()
    goal = (
        await _post(client, alice_headers, project_id, "goals", {"kind": "text", "text": "48 V"})
    ).json()["data"]
    ok = await _patch_payload(
        client, alice_headers, project_id, goal["id"], {"linked_run_ids": [str(run.id)]}
    )
    assert ok.status_code == 200, ok.text
    edge = await db.scalar(
        select(GraphEdge).where(
            GraphEdge.src_id == uuid.UUID(goal["entity_id"]),
            GraphEdge.dst_id == run.id,
            GraphEdge.relation_type == "verified_by",
            GraphEdge.deleted_at.is_(None),
        )
    )
    assert edge is not None


async def test_an_entity_bound_software_environment_cannot_collide_with_its_hardware_config(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """One live CONFIG row per subject (uq_solus_config_subject_live), whatever the cell:
    a second cell for the same entity is a 409, never an IntegrityError."""
    project_id, _ = await _project(client, alice_headers)
    pid = uuid.UUID(project_id)
    robot = await PhysicalRobotService(db).create(pid, "Rover")
    config = EntityHardwareConfig.model_validate(
        {"schema_version": 2, "entity_id": str(robot.id), "provenance": {}}
    )
    await put_entity_config(db, pid, robot, config, expected_version=0, created_by=None)
    await db.commit()
    env = CodeEnvironment.model_validate(
        {"type": "venv", "name": "a", "provenance": "detected", "captured_at": datetime.now(UTC)}
    )
    with pytest.raises(APIError) as err:
        await upsert_code_environment(
            db, pid, env, created_by=None, author="user", configured_entity_id=robot.id
        )
    assert err.value.status_code == 409 and err.value.code == "conflict"
