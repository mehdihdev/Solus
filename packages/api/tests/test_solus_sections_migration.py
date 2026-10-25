"""a32000000002/0003 (SOLUSDEV-320 T5a): five `.solus` sections become seven, with
subsections. The frozen sibling `migrations/solus_sections_remap.py` moves every row
(live and deleted), rewrites node/edge attrs, retires the four old section nodes and
their `contains` edges, and refuses to finish when a count disagrees."""

from __future__ import annotations

import asyncio
import sys
import uuid
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from solus_api.models import (
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    SolusEntry,
    SolusEntryKind,
    SolusSection,
    Team,
    utcnow,
)
from solus_api.services.solus_config import add_text_entry
from solus_api.services.solus_graph import SolusGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_hardware_data_migration import MigrationDatabase
from test_hardware_data_migration import _schema as _schema
from test_hardware_data_migration import migration_db as migration_db

API_DIR = Path(__file__).resolve().parents[1]
SCHEMA = "a32000000002"
DATA = "a32000000003"
OLD = ("hardware", "details", "docs", "code")
NEW = ("goals", "constraints", "documentation", "errors", "environment", "members", "history")
NEW_ONLY = tuple(s for s in NEW if s != "errors")


def _module() -> Any:
    name = "solus_sections_remap_320_test"
    spec = spec_from_file_location(name, API_DIR / "migrations" / "solus_sections_remap.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _tree_node(project_id: uuid.UUID, kind: str, name: str, **attrs: Any) -> GraphEntity:
    return GraphEntity(
        project_id=project_id,
        kind=kind,
        domain=Domain.PROJECT,
        origin="manual",
        name=name,
        attrs=attrs,
    )


def _tree_edge(
    project_id: uuid.UUID, src: GraphEntity, dst: GraphEntity, kind: str, section: str
) -> GraphEdge:
    return GraphEdge(
        project_id=project_id,
        src_id=src.id,
        dst_id=dst.id,
        relation_type=kind,
        domain_pair="project<->project",
        origin="manual",
        attrs={"section": section, "evidence": []},
    )


async def _seed_old_world(url: str) -> dict[str, Any]:
    """The old world at a32000000002: five section nodes, one entry per old section plus a
    deleted hardware text entry and a configured hardware CONFIG entry."""
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            team = Team(name="sections")
            session.add(team)
            await session.flush()
            project = Project(team_id=team.id, name="sections")
            session.add(project)
            await session.flush()
            pid = project.id
            root = _tree_node(pid, "solus_config", ".solus")
            sections = {
                key: _tree_node(pid, "solus_section", key.title(), section=key)
                for key in (*OLD, "errors")
            }
            part = _tree_node(pid, "part", "IMU")
            config_node = _tree_node(pid, "hardware_config", "Hardware config", section="hardware")
            notes = {
                "details": _tree_node(pid, "solus_note", "48 V bus", section="details"),
                "docs": _tree_node(pid, "solus_note", "Rules", section="docs"),
                "code": _tree_node(pid, "solus_note", "robot-venv", section="code"),
                "errors": _tree_node(pid, "solus_error", "exit 1", section="errors"),
            }
            session.add_all([root, *sections.values(), part, config_node, *notes.values()])
            await session.flush()
            rows = {
                "config": SolusEntry(
                    project_id=pid,
                    section="hardware",  # the old vocabulary
                    kind=SolusEntryKind.CONFIG,
                    text="Hardware config",
                    payload={"schema_version": 2, "entity_id": str(part.id), "provenance": {}},
                    entity_id=config_node.id,
                    configured_entity_id=part.id,
                    config_version=1,
                ),
                "deleted": SolusEntry(
                    project_id=pid,
                    section="hardware",
                    kind=SolusEntryKind.TEXT,
                    text="gone",
                    deleted_at=utcnow(),
                ),
            }
            for key, node in notes.items():
                rows[key] = SolusEntry(
                    project_id=pid,
                    section=key,
                    kind=SolusEntryKind.SOL if key == "errors" else SolusEntryKind.TEXT,
                    text=node.name,
                    entity_id=node.id,
                    payload={"type": "venv", "name": "robot-venv"} if key == "code" else None,
                )
            session.add_all(rows.values())
            await session.flush()
            for key, node in notes.items():
                node.attrs = {**node.attrs, "solus_entry_id": str(rows[key].id)}
            edges = [_tree_edge(pid, root, s, "contains", k) for k, s in sections.items()]
            edges.append(_tree_edge(pid, sections["hardware"], config_node, "contains", "hardware"))
            edges.append(_tree_edge(pid, config_node, part, "configures", "hardware"))
            edges += [_tree_edge(pid, sections[k], n, "contains", k) for k, n in notes.items()]
            session.add_all(edges)
            await session.commit()
            return {
                "project": pid,
                "config_node": config_node.id,
                "notes": {k: n.id for k, n in notes.items()},
                "sections": {k: s.id for k, s in sections.items()},
                "entries": {k: e.id for k, e in rows.items()},
            }
    finally:
        await engine.dispose()


async def _run_remap(url: str, module: Any, fn: str) -> dict[str, Any]:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            result: dict[str, Any] = await connection.run_sync(
                lambda sync: dict(getattr(module, fn)(sync))
            )
            return result
    finally:
        await engine.dispose()


async def _ensure_and_add_goal(url: str, project_id: uuid.UUID) -> uuid.UUID:
    """The new world's write path over the migrated rows: ensure() attaches every live
    entry (a kind mismatch is a 404), then a goal is filed under goals/general."""
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await SolusGraph.ensure(session, project_id)
            entry = await add_text_entry(
                session, project_id, SolusSection.GOALS, "ship it", author="user", created_by=None
            )
            await session.commit()
            parent = await session.scalar(
                select(GraphEntity)
                .join(GraphEdge, GraphEdge.src_id == GraphEntity.id)
                .where(GraphEdge.dst_id == entry.entity_id, GraphEdge.relation_type == "contains")
            )
            assert parent is not None and parent.kind == "solus_subsection"
            assert parent.attrs["section"] == "goals" and parent.attrs["subsection"] == "general"
            assert entry.entity_id is not None
            return entry.entity_id
    finally:
        await engine.dispose()


def _solus_check(db: MigrationDatabase) -> str:
    rows = db.rows(
        "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint WHERE conname='solussection'"
    )
    return str(rows[0]["def"])


def test_remap_moves_rows_rewrites_attrs_and_retires_old_sections(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.upgrade(SCHEMA)
    for value in (*OLD, *NEW):
        assert f"'{value}'" in _solus_check(migration_db)  # old ∪ new while the data moves
    ids = asyncio.run(_seed_old_world(migration_db.url))
    live_configs_sql = (
        "SELECT count(*) AS n FROM solus_entries WHERE kind='config' AND deleted_at IS NULL"
    )
    live_configs = migration_db.rows(live_configs_sql)[0]["n"]

    counts = asyncio.run(_run_remap(migration_db.url, _module(), "remap_sections"))

    assert counts == {
        "before": {"hardware": 2, "details": 1, "docs": 1, "code": 1, "errors": 1},
        "after": {
            "environment/hardware": 2,
            "goals/general": 1,
            "documentation/guides": 1,
            "environment/software": 1,
            "errors": 1,
        },
        "section_nodes_retired": 4,
        "edges_retired": 8,
    }
    entries = ids["entries"]
    rows = {
        row["id"]: row
        for row in migration_db.rows(
            "SELECT id, section, subsection, deleted_at FROM solus_entries"
        )
    }
    assert (rows[entries["config"]]["section"], rows[entries["config"]]["subsection"]) == (
        "environment",
        "hardware",
    )
    assert rows[entries["deleted"]]["section"] == "environment"
    assert rows[entries["deleted"]]["deleted_at"] is not None
    assert rows[entries["details"]]["subsection"] == "general"
    assert rows[entries["docs"]]["subsection"] == "guides"
    assert rows[entries["code"]]["subsection"] == "software"
    assert rows[entries["errors"]]["subsection"] is None
    nodes = {
        row["id"]: row
        for row in migration_db.rows("SELECT id, kind, attrs, deleted_at FROM graph_entity")
    }
    assert nodes[ids["notes"]["details"]]["kind"] == "solus_goal"  # entry_node_kind(goals)
    assert nodes[ids["notes"]["docs"]]["kind"] == "solus_note"
    assert nodes[ids["config_node"]]["kind"] == "hardware_config"
    assert nodes[ids["config_node"]]["attrs"]["section"] == "environment"
    assert nodes[ids["config_node"]]["attrs"]["subsection"] == "hardware"
    assert nodes[ids["notes"]["details"]]["attrs"] == {
        "solus_entry_id": str(entries["details"]),
        "section": "goals",
        "subsection": "general",
    }
    assert nodes[ids["notes"]["errors"]]["attrs"]["section"] == "errors"
    assert nodes[ids["notes"]["errors"]]["attrs"]["subsection"] is None
    for key in OLD:
        retired = nodes[ids["sections"][key]]
        assert retired["deleted_at"] is not None and retired["attrs"]["retired_by"] == DATA
    assert nodes[ids["sections"]["errors"]]["deleted_at"] is None
    edges = migration_db.rows("SELECT relation_type, attrs, deleted_at FROM graph_edge")
    live = [e for e in edges if e["deleted_at"] is None]
    assert len(live) == 3  # root→errors, errors→entry, config→part
    assert all(e["attrs"].get("section") not in OLD for e in live)
    assert all(e["attrs"]["retired_by"] == DATA for e in edges if e["deleted_at"] is not None)
    assert migration_db.rows(live_configs_sql)[0]["n"] == live_configs

    migration_db.upgrade(DATA)  # re-runs the remap idempotently, then swaps the CHECK
    check = _solus_check(migration_db)
    assert all(f"'{value}'" in check for value in NEW)
    assert all(f"'{value}'" not in check for value in OLD)
    assert (
        migration_db.rows(
            "SELECT count(*) AS n FROM solus_entries WHERE section IN "
            "('hardware','details','docs','code')"
        )[0]["n"]
        == 0
    )
    with pytest.raises(Exception, match="solussection"):
        migration_db.execute(
            "INSERT INTO solus_entries (id, project_id, section, kind, author, config_version, "
            "created_at, updated_at) "
            "VALUES (:id, :pid, 'hardware', 'text', 'user', 0, now(), now())",
            {"id": uuid.uuid4(), "pid": ids["project"]},
        )

    # The new world's ORM maps the generated search columns (a32000000004), so the
    # write path runs at head; the downgrade below walks back through them.
    migration_db.upgrade("head")
    goal_node = asyncio.run(_ensure_and_add_goal(migration_db.url, ids["project"]))
    tree_sql = (
        "SELECT id, kind, attrs, deleted_at FROM graph_entity "
        "WHERE kind IN ('solus_section', 'solus_subsection')"
    )
    new_tree = [n for n in migration_db.rows(tree_sql) if n["attrs"]["section"] in NEW_ONLY]
    assert len(new_tree) == 6 + 4 + 4 + 4 + 1  # sections, fixed subsections, goals/general
    assert all(n["deleted_at"] is None for n in new_tree)

    command.downgrade(migration_db.config, SCHEMA)
    back = {
        row["id"]: row
        for row in migration_db.rows("SELECT id, section, subsection FROM solus_entries")
    }
    assert back[entries["config"]]["section"] == "hardware"
    assert back[entries["details"]]["section"] == "details"
    assert all(row["subsection"] is None for row in back.values())
    nodes = {
        row["id"]: row
        for row in migration_db.rows("SELECT id, kind, attrs, deleted_at FROM graph_entity")
    }
    assert all(nodes[ids["sections"][key]]["deleted_at"] is None for key in OLD)
    assert "retired_by" not in nodes[ids["sections"]["hardware"]]["attrs"]
    assert nodes[ids["notes"]["details"]]["kind"] == "solus_note"
    assert nodes[goal_node]["kind"] == "solus_note"
    assert nodes[ids["notes"]["details"]]["attrs"]["section"] == "details"
    assert "subsection" not in nodes[ids["notes"]["details"]]["attrs"]
    # The tree the new world built is retired, edges included: one live parent per entry.
    gone = [nodes[n["id"]] for n in new_tree]
    assert all(n["deleted_at"] is not None for n in gone)
    assert {n["attrs"]["retired_by"] for n in gone} == {f"{DATA}:downgrade"}
    edges = migration_db.rows(
        "SELECT src_id, dst_id, attrs FROM graph_edge WHERE deleted_at IS NULL"
    )
    retired_ids = {n["id"] for n in gone}
    assert not [e for e in edges if e["src_id"] in retired_ids or e["dst_id"] in retired_ids]
    parents = [e["src_id"] for e in edges if e["dst_id"] == ids["notes"]["details"]]
    assert parents == [ids["sections"]["details"]]

    migration_db.upgrade(DATA)  # a rollback is not one-way: the retired tree comes back
    nodes = {row["id"]: row for row in migration_db.rows(tree_sql)}
    assert all(nodes[n["id"]]["deleted_at"] is None for n in new_tree)
    assert all("retired_by" not in nodes[n["id"]]["attrs"] for n in new_tree)
    migration_db.upgrade("head")
    asyncio.run(_ensure_and_add_goal(migration_db.url, ids["project"]))


def test_a_count_mismatch_is_refused() -> None:
    module = _module()

    class _Result:
        def __init__(self, rows: list[Any]) -> None:
            self.rows, self.rowcount = rows, 0

        def all(self) -> list[Any]:
            return self.rows

        def scalar(self) -> Any:
            return self.rows[0][0] if self.rows else None

    class _Connection:
        def execute(self, statement: Any, *args: Any, **kwargs: Any) -> _Result:
            text = str(statement)
            if "GROUP BY section, subsection" in text:
                return _Result([("environment", "hardware", 1)])
            if "GROUP BY section" in text:
                return _Result([("hardware", 3)])
            return _Result([])

    with pytest.raises(RuntimeError, match="hardware"):
        module.remap_sections(_Connection())
