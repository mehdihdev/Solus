"""Portable v1/v2 adapter invariants on PostgreSQL (SOLUSDEV-260 Phase 1)."""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from solus_api.core.errors import APIError
from solus_api.hardware.config import EntityHardwareConfig, HardwareConfig, is_private_source
from solus_api.hardware.migration import split_legacy_document
from solus_api.hardware.runtime import resolve_runtime_config
from solus_api.hardware.store import put_config, put_entity_config, read_entity_config
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, Team
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_FIXTURES = sorted((Path(__file__).parent / "fixtures/hardware").glob("*.json"))


async def _project(db: AsyncSession) -> Project:
    team = Team(name="Roundtrip fixture")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="Roundtrip fixture")
    db.add(project)
    await db.flush()
    return project


async def _seed(
    db: AsyncSession,
    project: Project,
    owner: uuid.UUID,
    documents: dict[uuid.UUID, EntityHardwareConfig],
) -> dict[uuid.UUID, GraphEntity]:
    nodes = {
        entity_id: GraphEntity(
            id=entity_id,
            project_id=project.id,
            kind="physical_robot" if entity_id == owner else "part",
            domain=Domain.PROJECT,
            origin="manual",
            name="Fixture hardware",
        )
        for entity_id in documents
    }
    db.add_all(nodes.values())
    await db.flush()
    for entity_id, config in documents.items():
        await put_entity_config(
            db, project.id, nodes[entity_id], config, expected_version=0, created_by=None
        )
    await db.commit()
    return nodes


def _leaves(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, f"{path}.{key}".strip("."))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaves(item, f"{path}.{index}")
    elif value is not None:
        yield path, value


def _portable_source(value: str | None, subject: uuid.UUID) -> str | None:
    if value is not None and is_private_source(value):
        return f"source:{uuid.uuid5(subject, value)}"
    return value


@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda path: path.stem)
async def test_all_fixture_values_and_effective_provenance_roundtrip(
    db: AsyncSession, fixture: Path
) -> None:
    legacy = HardwareConfig.model_validate_json(fixture.read_text())
    project = await _project(db)
    await _seed(
        db,
        project,
        legacy.robot_entity_id,
        split_legacy_document(legacy.model_dump(mode="json"), source_namespace=project.id),
    )
    resolved = await resolve_runtime_config(db, project.id, legacy.robot_entity_id)
    expected = legacy.model_dump(mode="json", exclude={"provenance"})
    assert expected["identity"] is not None
    expected["identity"]["last_seen_path"] = None
    for part in expected["parts"].values():
        if part["calibration"]:
            part["calibration"]["source"] = _portable_source(
                part["calibration"]["source"], project.id
            )
    assert resolved.model_dump(mode="json", exclude={"provenance"}) == expected
    for path, _ in _leaves(expected):
        if path in {"schema_version", "robot_entity_id"}:
            continue
        before, after = legacy.provenance_of(path), resolved.provenance_of(path)
        assert after.by == before.by, path
        assert after.source == _portable_source(before.source, project.id), path
    assert str(legacy.robot_entity_id) not in resolved.parts


async def test_owner_never_becomes_own_part_even_with_self_bus_reference(db: AsyncSession) -> None:
    project = await _project(db)
    owner = uuid.uuid4()
    config = EntityHardwareConfig.model_validate(
        {
            "entity_id": owner,
            "component": {"firmware": {"version": "1"}},
            "provenance": {"component": {"by": "user"}},
        }
    )
    await _seed(db, project, owner, {owner: config})
    entry, _ = await read_entity_config(db, project.id, owner)
    assert entry is not None and entry.payload is not None
    # Historical malformed self-reference may exist before the data migration.
    entry.payload = {
        **entry.payload,
        "bus_map": [{"protocol": "fixture", "address": "self", "part_entity_id": str(owner)}],
        "provenance": {"component": {"by": "user"}, "bus_map": {"by": "user"}},
    }
    await db.commit()
    resolved = await resolve_runtime_config(db, project.id, owner)
    assert resolved.parts == {}
    assert resolved.firmware == {"version": "1"}
    assert resolved.provenance_of("firmware.version").by.value == "user"


@pytest.mark.parametrize("firmware", [{"version": "2"}, {}])
@pytest.mark.parametrize("initial_firmware", [{"version": "1"}, {}])
async def test_legacy_write_preserves_v2_only_owner_component(
    db: AsyncSession, firmware: dict[str, str], initial_firmware: dict[str, str]
) -> None:
    project = await _project(db)
    owner = uuid.uuid4()
    original = EntityHardwareConfig.model_validate(
        {
            "entity_id": owner,
            "component": {
                "calibration": {"mode": "degrees", "values": {"offset": 3}},
                "limits": {"values": {"max": 50}},
                "telemetry": [{"name": "temperature"}],
                "lifecycle": "installed",
                "firmware": initial_firmware,
            },
            "provenance": {
                "component": {"by": "repo", "source": "source:fixture"},
                "component.lifecycle": {"by": "user"},
            },
        }
    )
    nodes = await _seed(db, project, owner, {owner: original})
    runtime = await resolve_runtime_config(db, project.id, owner)
    submitted = runtime.model_dump(mode="json")
    submitted["firmware"] = firmware
    submitted["provenance"]["firmware"] = {"by": "sol"}
    submitted["provenance"].pop("firmware.version", None)
    await put_config(
        db, project.id, nodes[owner], HardwareConfig.model_validate(submitted), created_by=None
    )
    await db.commit()
    _, current = await read_entity_config(db, project.id, owner)
    assert current is not None and current.component is not None and original.component is not None
    assert current.component.model_dump(exclude={"firmware"}) == original.component.model_dump(
        exclude={"firmware"}
    )
    assert current.component.firmware == firmware
    for path, _ in _leaves(original.component.model_dump(exclude={"firmware"}), "component"):
        assert current.provenance_of(path) == original.provenance_of(path)
    if firmware:
        assert current.provenance_of("component.firmware.version").by.value == "sol"


async def test_unmigrated_owner_part_requires_upgrade(db: AsyncSession) -> None:
    project = await _project(db)
    owner = uuid.uuid4()
    await _seed(db, project, owner, {owner: EntityHardwareConfig(entity_id=owner)})
    entry, _ = await read_entity_config(db, project.id, owner)
    assert entry is not None
    entry.payload = {
        "robot_entity_id": str(owner),
        "parts": {str(owner): {}},
        "provenance": {"parts": {"by": "user"}},
    }
    await db.commit()
    with pytest.raises(APIError) as result:
        await resolve_runtime_config(db, project.id, owner)
    assert result.value.status_code == 409
    assert result.value.code == "config_upgrade_required"


async def test_disabled_bus_reindexes_effective_provenance(db: AsyncSession) -> None:
    legacy = HardwareConfig.model_validate_json((_FIXTURES[0]).read_text())
    project = await _project(db)
    documents = split_legacy_document(legacy.model_dump(mode="json"), source_namespace=project.id)
    owner = legacy.robot_entity_id
    owner_doc = documents[owner].model_dump(mode="json")
    owner_doc["provenance"]["bus_map.1.model"] = {"by": "sol", "source": "review:fixture"}
    documents[owner] = EntityHardwareConfig.model_validate(owner_doc)
    await _seed(db, project, owner, documents)
    edge = await db.scalar(
        select(GraphEdge).where(
            GraphEdge.project_id == project.id,
            GraphEdge.relation_type == "binds",
            GraphEdge.dst_id == legacy.bus_map[0].part_entity_id,
        )
    )
    assert edge is not None
    edge.attrs = {**edge.attrs, "enabled": False}
    await db.commit()
    runtime = await resolve_runtime_config(db, project.id, owner)
    assert runtime.bus_map == legacy.bus_map[1:]
    assert runtime.provenance_of("bus_map.0.model").by.value == "sol"
    assert runtime.provenance_of("bus_map.0.model").source == "review:fixture"
    assert runtime.provenance_of("bus_map.1.model").by == legacy.provenance_of("bus_map.2.model").by


async def test_disabled_binding_blocks_compatibility_promotion_without_losing_evidence(
    db: AsyncSession,
) -> None:
    from solus_api.hardware.config import LifecycleState
    from solus_api.hardware.store import promote

    legacy = HardwareConfig.model_validate_json(_FIXTURES[0].read_text())
    project = await _project(db)
    owner = legacy.robot_entity_id
    nodes = await _seed(
        db,
        project,
        owner,
        split_legacy_document(legacy.model_dump(mode="json"), source_namespace=project.id),
    )
    target = legacy.bus_map[0].part_entity_id
    assert target is not None
    edge = await db.scalar(
        select(GraphEdge).where(
            GraphEdge.project_id == project.id,
            GraphEdge.relation_type == "binds",
            GraphEdge.dst_id == target,
        )
    )
    assert edge is not None
    edge.attrs = {**edge.attrs, "enabled": False, "disabled_reason": "ownership_changed"}
    await db.commit()
    _, before = await read_entity_config(db, project.id, owner)
    edge_id, project_id = edge.id, project.id
    with pytest.raises(APIError) as result:
        await promote(db, project_id, nodes[owner], target, LifecycleState.LIVE, created_by=None)
    assert result.value.status_code == 409 and result.value.code == "config_upgrade_required"
    await db.rollback()
    _, after = await read_entity_config(db, project_id, owner)
    assert after == before
    refreshed = await db.get(GraphEdge, edge_id)
    assert refreshed is not None and refreshed.attrs["enabled"] is False


async def test_child_connection_survives_parent_component_mutation(db: AsyncSession) -> None:
    from solus_api.hardware.config import LifecycleState
    from solus_api.hardware.store import promote

    legacy = HardwareConfig.model_validate_json(_FIXTURES[0].read_text())
    project = await _project(db)
    owner = legacy.robot_entity_id
    target = legacy.bus_map[0].part_entity_id
    assert target is not None
    documents = split_legacy_document(legacy.model_dump(mode="json"), source_namespace=project.id)
    child = documents[target].model_dump(mode="json")
    child.update(
        identity={"kind": "wifi", "binding": "child-fixture"},
        protocol={"driver_id": "fixture", "params": {"baud": 115200}},
        disambiguated_by="user",
    )
    child["bus_map"] = [
        {
            "protocol": "fixture",
            "address": "nested",
            "part_entity_id": str(legacy.bus_map[2].part_entity_id),
        }
    ]
    child["provenance"].update(
        {
            key: {"by": "user", "source": "review:child"}
            for key in ("identity", "protocol", "bus_map", "disambiguated_by")
        }
    )
    documents[target] = EntityHardwareConfig.model_validate(child)
    nodes = await _seed(db, project, owner, documents)
    await promote(db, project.id, nodes[owner], target, LifecycleState.LIVE, created_by=None)
    await db.commit()
    _, after = await read_entity_config(db, project.id, target)
    assert after is not None and after.component is not None
    assert after.identity == documents[target].identity
    assert after.protocol == documents[target].protocol
    assert after.bus_map == documents[target].bus_map
    assert after.disambiguated_by == "user"
    assert after.component.lifecycle == LifecycleState.LIVE
    for path, _ in _leaves(child["identity"], "identity"):
        assert after.provenance_of(path) == documents[target].provenance_of(path)
