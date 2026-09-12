"""Real Alembic migrations on a run/worker-scoped reusable test database.

Each case resets the public schema and rebuilds the predecessor. The database is
retained empty, like the ordinary API test databases: DROP DATABASE forces a
cluster-wide checkpoint and can exceed the test timeout under concurrent API
TRUNCATE traffic. Schema reset preserves case isolation without that checkpoint.
"""

import asyncio
import hashlib
import json
import os
import re
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from solus_api.hardware.config import EntityHardwareConfig
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
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

API_DIR = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures/hardware_migration/nested.json"
PREVIOUS = "a25100000001"
BACKFILL = "a26000000002"
HEAD = "a26000000003"


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """Never let the shared suite schema fixture migrate this module's databases."""


def _migration_url(base_url: str, worker: str) -> URL:
    base = make_url(base_url)
    if (
        base.drivername != "postgresql+asyncpg"
        or bool(base.query)
        or re.fullmatch(r"solus_test(?:_[a-z0-9_]+)?", base.database or "") is None
        or re.fullmatch(r"(?:gw[0-9]+|master)", worker) is None
    ):
        raise ValueError("Migration fixtures require an isolated test database and worker")
    scope = f"{API_DIR.resolve()}:{base.database}:{worker}"
    digest = hashlib.sha256(scope.encode()).hexdigest()[:32]
    return base.set(database=f"solus_test_migration_{digest}")


@dataclass
class MigrationDatabase:
    url: str
    config: Config

    def reset(self) -> None:
        # A test URL is never itself a reset target; only our derived namespace is.
        target = make_url(self.url)
        if (
            target.query
            or re.fullmatch(r"solus_test_migration_[0-9a-f]{32}", target.database or "") is None
        ):
            raise ValueError("Refusing schema reset outside the migration test database")

        async def clean() -> None:
            engine = create_async_engine(self.url)
            try:
                async with engine.begin() as connection:
                    await connection.execute(text("SET LOCAL lock_timeout = '5s'"))
                    await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
                    await connection.execute(text("CREATE SCHEMA public"))
            finally:
                await engine.dispose()

        asyncio.run(clean())

    def upgrade(self, revision: str = HEAD) -> None:
        command.upgrade(self.config, revision)

    def rows(self, sql: str) -> list[dict[str, Any]]:
        async def query() -> list[dict[str, Any]]:
            engine = create_async_engine(self.url)
            try:
                async with engine.connect() as connection:
                    return [dict(row) for row in (await connection.execute(text(sql))).mappings()]
            finally:
                await engine.dispose()

        return asyncio.run(query())

    def execute(self, sql: str, parameters: dict[str, Any] | None = None) -> None:
        async def mutate() -> None:
            engine = create_async_engine(self.url)
            try:
                async with engine.begin() as connection:
                    await connection.execute(text(sql), parameters or {})
            finally:
                await engine.dispose()

        asyncio.run(mutate())

    def seed(self, variant: str = "normal") -> dict[str, uuid.UUID]:
        return asyncio.run(_seed(self.url, variant))


@pytest.fixture
def migration_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[MigrationDatabase]:
    url = _migration_url(
        os.environ["SOLUS_TEST_DATABASE_URL"], os.environ.get("PYTEST_XDIST_WORKER", "master")
    )
    name = url.database
    assert name is not None
    admin = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )

    async def ensure_database() -> None:
        connection = await asyncpg.connect(admin)
        try:
            if not await connection.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", name):
                # Name is generated from a fixed namespace and hexadecimal digest.
                await connection.execute(f'CREATE DATABASE "{name}"')
        finally:
            await connection.close()

    asyncio.run(ensure_database())
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.set_main_option("prepend_sys_path", str(API_DIR))
    monkeypatch.setenv("SOLUS_DATABASE_URL", url.render_as_string(hide_password=False))
    db = MigrationDatabase(url.render_as_string(hide_password=False), cfg)
    try:
        db.reset()
        db.upgrade(PREVIOUS)
        yield db
    finally:
        db.reset()


async def _seed(url: str, variant: str) -> dict[str, uuid.UUID]:
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            team = Team(name="Migration fixture")
            session.add(team)
            await session.flush()
            project = Project(team_id=team.id, name="Migration fixture")
            session.add(project)
            await session.flush()
            payload = json.loads(FIXTURE.read_text())
            owner = uuid.UUID(payload["robot_entity_id"])
            part_ids = [uuid.UUID(value) for value in payload["parts"]]
            nodes = [
                GraphEntity(
                    id=value,
                    project_id=project.id,
                    domain=Domain.PROJECT,
                    origin="manual",
                    kind="physical_robot" if value == owner else "part",
                    name="Original robot" if value == owner else "Original part",
                )
                for value in [owner, *part_ids]
            ]
            section = GraphEntity(
                project_id=project.id,
                domain=Domain.PROJECT,
                origin="manual",
                kind="solus_section",
                name="Hardware configs",
                attrs={"section": "hardware"},
            )
            config_node = GraphEntity(
                project_id=project.id,
                domain=Domain.PROJECT,
                origin="manual",
                kind="hardware_config",
                name="Original config",
            )
            session.add_all([*nodes, section, config_node])
            await session.flush()
            if variant == "deleted_owner":
                nodes[0].deleted_at = utcnow()
            if variant == "conflicting_part":
                payload["parts"][str(part_ids[0])]["calibration"]["values"]["offset"] = 99
            if variant == "invalid_provenance":
                payload["provenance"] = {}
            if variant == "missing_subject":
                payload["robot_entity_id"] = str(uuid.uuid4())
            entry = SolusEntry(
                project_id=project.id,
                section=SolusSection.HARDWARE,
                kind=SolusEntryKind.CONFIG,
                entity_id=config_node.id,
                text="Original configuration",
                payload=payload,
            )
            session.add(entry)
            session.add_all(
                [
                    GraphEdge(
                        project_id=project.id,
                        src_id=section.id,
                        dst_id=config_node.id,
                        relation_type="contains",
                        domain_pair="project<->project",
                        origin="manual",
                    ),
                    GraphEdge(
                        project_id=project.id,
                        src_id=config_node.id,
                        dst_id=owner,
                        relation_type="configures",
                        domain_pair="project<->project",
                        origin="manual",
                    ),
                ]
            )
            await session.flush()
            if variant in {"duplicate", "conflict"}:
                duplicate_node = GraphEntity(
                    project_id=project.id,
                    domain=Domain.PROJECT,
                    origin="manual",
                    kind="hardware_config",
                    name="Duplicate config",
                )
                session.add(duplicate_node)
                await session.flush()
                duplicate = json.loads(json.dumps(payload))
                if variant == "conflict":
                    duplicate["parts"][str(part_ids[0])]["calibration"]["values"]["offset"] = 99
                session.add(
                    SolusEntry(
                        project_id=project.id,
                        section=SolusSection.HARDWARE,
                        kind=SolusEntryKind.CONFIG,
                        entity_id=duplicate_node.id,
                        text="Duplicate configuration",
                        payload=duplicate,
                    )
                )
                session.add_all(
                    [
                        GraphEdge(
                            project_id=project.id,
                            src_id=section.id,
                            dst_id=duplicate_node.id,
                            relation_type="contains",
                            domain_pair="project<->project",
                            origin="manual",
                        ),
                        GraphEdge(
                            project_id=project.id,
                            src_id=duplicate_node.id,
                            dst_id=owner,
                            relation_type="configures",
                            domain_pair="project<->project",
                            origin="manual",
                        ),
                    ]
                )
            await session.commit()
            return {
                "project": project.id,
                "owner": owner,
                "part": part_ids[0],
                "part2": part_ids[1],
                "entry": entry.id,
                "node": config_node.id,
                "section": section.id,
            }
    finally:
        await engine.dispose()


def test_nested_extraction_preserves_ids_values_sources_and_timestamps(
    migration_db: MigrationDatabase,
) -> None:
    ids = migration_db.seed()
    before = migration_db.rows(
        "SELECT id, created_at, updated_at, text, entity_id FROM solus_entries"
    )[0]
    migration_db.upgrade()
    rows = migration_db.rows("SELECT * FROM solus_entries ORDER BY id")
    assert len(rows) == 3
    owner = next(row for row in rows if row["id"] == ids["entry"])
    assert {key: owner[key] for key in before} == before
    assert owner["configured_entity_id"] == ids["owner"] and owner["config_version"] == 1
    assert owner["payload"]["component"]["firmware"] == {"version": "1"}
    children = [EntityHardwareConfig.model_validate(row["payload"]) for row in rows if row != owner]
    assert all(child.component is not None for child in children)
    sources = {
        child.provenance_of("component.calibration.values.offset").source for child in children
    }
    assert (
        len(sources) == 1
        and next(iter(sources))
        == f"source:{uuid.uuid5(ids['project'], '/fixture/private/calibration.json')}"
    )
    assert "/fixture/private" not in json.dumps([row["payload"] for row in rows])
    assert "last_seen_path" not in json.dumps([row["payload"] for row in rows])
    assert (
        migration_db.rows("SELECT count(*) AS n FROM graph_edge WHERE relation_type='binds'")[0][
            "n"
        ]
        == 0
    )


def test_identical_duplicates_become_soft_history(migration_db: MigrationDatabase) -> None:
    migration_db.seed("duplicate")
    migration_db.upgrade()
    rows = migration_db.rows("SELECT configured_entity_id, deleted_at, payload FROM solus_entries")
    assert len(rows) == 4 and sum(row["deleted_at"] is None for row in rows) == 3
    assert all(row["payload"]["schema_version"] == 2 for row in rows)


@pytest.mark.parametrize("variant", ["conflict", "invalid_provenance", "missing_subject"])
def test_invalid_dataset_rolls_back_every_row(
    migration_db: MigrationDatabase, variant: str
) -> None:
    migration_db.seed(variant)
    before = migration_db.rows(
        "SELECT id, payload, configured_entity_id FROM solus_entries ORDER BY id"
    )
    with pytest.raises((RuntimeError, ValueError)):
        migration_db.upgrade()
    assert (
        migration_db.rows("SELECT version_num FROM alembic_version")[0]["version_num"] == PREVIOUS
    )
    assert (
        migration_db.rows("SELECT id, payload, configured_entity_id FROM solus_entries ORDER BY id")
        == before
    )


def test_deleted_owner_is_nonoperational_but_parts_are_retained(
    migration_db: MigrationDatabase,
) -> None:
    ids = migration_db.seed("deleted_owner")
    migration_db.upgrade()
    rows = migration_db.rows("SELECT configured_entity_id, deleted_at FROM solus_entries")
    assert (
        next(row for row in rows if row["configured_entity_id"] == ids["owner"])["deleted_at"]
        is not None
    )
    assert all(
        row["deleted_at"] is None for row in rows if row["configured_entity_id"] != ids["owner"]
    )


def test_backfill_rerun_is_idempotent_and_downgrade_refuses(
    migration_db: MigrationDatabase,
) -> None:
    migration_db.seed()
    migration_db.upgrade()
    before = migration_db.rows("SELECT * FROM solus_entries ORDER BY id")
    upgrade_data = sys.modules["solus_hardware_backfill_260"].upgrade_data

    async def rerun() -> None:
        engine = create_async_engine(migration_db.url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(upgrade_data)
        finally:
            await engine.dispose()

    asyncio.run(rerun())
    assert migration_db.rows("SELECT * FROM solus_entries ORDER BY id") == before
    with pytest.raises(RuntimeError, match="v2"):
        command.downgrade(migration_db.config, PREVIOUS)
    assert migration_db.rows("SELECT version_num FROM alembic_version")[0]["version_num"] == HEAD


@pytest.mark.parametrize("fault", ["section", "configures", "missing_section", "cross_project"])
def test_graph_reference_failures_are_atomic(migration_db: MigrationDatabase, fault: str) -> None:
    ids = migration_db.seed()
    if fault == "section":
        migration_db.execute(
            "UPDATE graph_entity SET kind='part' WHERE id=:id", {"id": ids["section"]}
        )
    elif fault == "configures":
        migration_db.execute(
            "UPDATE graph_edge SET dst_id=:id WHERE relation_type='configures'", {"id": ids["part"]}
        )
    elif fault == "missing_section":
        migration_db.execute("DELETE FROM graph_edge WHERE relation_type='contains'")
    else:
        foreign = uuid.uuid4()
        migration_db.execute(
            "INSERT INTO projects(id,team_id,name,created_at,updated_at) SELECT "
            ":id,team_id,'Other fixture',created_at,updated_at FROM projects LIMIT 1",
            {"id": foreign},
        )
        migration_db.execute(
            "UPDATE graph_entity SET project_id=:project WHERE id=:id",
            {"project": foreign, "id": ids["part"]},
        )
    before = migration_db.rows(
        "SELECT id,payload,configured_entity_id FROM solus_entries ORDER BY id"
    )
    with pytest.raises(RuntimeError):
        migration_db.upgrade()
    assert (
        migration_db.rows("SELECT id,payload,configured_entity_id FROM solus_entries ORDER BY id")
        == before
    )


def test_existing_v2_payload_and_graph_are_unchanged(migration_db: MigrationDatabase) -> None:
    ids = migration_db.seed()
    payload = {
        "schema_version": 2,
        "entity_id": str(ids["owner"]),
        "component": {"firmware": {"version": "1"}},
        "provenance": {"component": {"by": "user"}},
    }
    migration_db.execute(
        "UPDATE solus_entries SET payload=CAST(:payload AS jsonb)", {"payload": json.dumps(payload)}
    )
    graph = migration_db.rows("SELECT * FROM graph_entity ORDER BY id")
    migration_db.upgrade()
    assert migration_db.rows("SELECT payload FROM solus_entries")[0]["payload"] == payload
    assert migration_db.rows("SELECT * FROM graph_entity ORDER BY id") == graph


def test_part_source_canonical_and_detached_identity_survive(
    migration_db: MigrationDatabase,
) -> None:
    ids = migration_db.seed("deleted_owner")
    migration_db.execute(
        "UPDATE graph_entity SET "
        "origin='connector',source_connector='onshape',"
        "external_ref='fixture:part',canonical_part_id=:canonical,"
        "attrs=CAST(:attrs AS jsonb) WHERE id=:id",
        {"canonical": ids["part2"], "id": ids["part"], "attrs": json.dumps({"fixture": True})},
    )
    before = next(
        row for row in migration_db.rows("SELECT * FROM graph_entity") if row["id"] == ids["part"]
    )
    migration_db.upgrade()
    after = next(
        row for row in migration_db.rows("SELECT * FROM graph_entity") if row["id"] == ids["part"]
    )
    assert after == before


@pytest.mark.parametrize("historical_empty", [False, True])
def test_preexisting_part_config_is_reused(
    migration_db: MigrationDatabase, historical_empty: bool
) -> None:
    from solus_api.hardware.migration import split_legacy_document

    ids = migration_db.seed()
    payload = split_legacy_document(
        json.loads(FIXTURE.read_text()), source_namespace=ids["project"]
    )[ids["part"]].model_dump(mode="json")
    entry_id, node_id = uuid.uuid4(), uuid.uuid4()
    parameters = {
        "node": node_id,
        "entry": entry_id,
        "project": ids["project"],
        "subject": ids["part"],
        "section": ids["section"],
        "payload": json.dumps(payload),
    }
    migration_db.execute(
        "INSERT INTO "
        "graph_entity(id,project_id,kind,domain,name,origin,version,attrs,"
        "modality_hints,created_at,updated_at) VALUES (:node,:project,"
        "'hardware_config','project','Existing child','manual',1,'{}','{}',"
        "now(),now())",
        parameters,
    )
    migration_db.execute(
        "INSERT INTO "
        "solus_entries(id,project_id,section,kind,entity_id,"
        "configured_entity_id,config_version,payload,author,created_at,"
        "updated_at) VALUES (:entry,:project,'hardware','config',:node,"
        ":subject,4,CAST(:payload AS jsonb),'user',now(),now())",
        parameters,
    )
    for relation, source, target in [
        ("contains", ids["section"], node_id),
        ("configures", node_id, ids["part"]),
    ]:
        migration_db.execute(
            "INSERT INTO "
            "graph_edge(id,project_id,src_id,dst_id,relation_type,domain_pair,"
            "origin,confidence,attrs,created_at,updated_at) VALUES (:edge,:project,"
            ":source,:target,:relation,'project<->project','manual',1,'{}',now(),"
            "now())",
            {
                "edge": uuid.uuid4(),
                "project": ids["project"],
                "source": source,
                "target": target,
                "relation": relation,
            },
        )
    if historical_empty:
        migration_db.execute(
            "UPDATE graph_entity SET deleted_at=now() WHERE id IN (:subject,:node)",
            {"subject": ids["part"], "node": node_id},
        )
        empty = {"schema_version": 2, "entity_id": str(ids["part"])}
        migration_db.execute(
            "UPDATE solus_entries SET deleted_at=now(),payload=CAST(:payload AS jsonb) "
            "WHERE id=:id",
            {"payload": json.dumps(empty), "id": entry_id},
        )
    migration_db.upgrade()
    rows = migration_db.rows("SELECT * FROM solus_entries")
    assert len(rows) == 3
    existing = next(row for row in rows if row["id"] == entry_id)
    assert existing["entity_id"] == node_id and existing["config_version"] == 4
    assert EntityHardwareConfig.model_validate(
        existing["payload"]
    ) == EntityHardwareConfig.model_validate(payload)
    if historical_empty:
        assert existing["deleted_at"] is not None


@pytest.mark.parametrize("variant", ["normal", "deleted_owner"])
def test_deleted_embedded_part_keeps_nonoperational_history(
    migration_db: MigrationDatabase, variant: str
) -> None:
    ids = migration_db.seed(variant)
    migration_db.execute(
        "UPDATE graph_entity SET deleted_at=now() WHERE id=:id", {"id": ids["part"]}
    )
    migration_db.upgrade()
    rows = migration_db.rows("SELECT * FROM solus_entries")
    part = next(row for row in rows if row["configured_entity_id"] == ids["part"])
    assert part["deleted_at"] is not None
    assert part["payload"]["component"]["calibration"]["values"] == {"offset": 7}
    assert (
        next(
            row
            for row in migration_db.rows("SELECT * FROM graph_entity")
            if row["id"] == part["entity_id"]
        )["deleted_at"]
        is not None
    )


@pytest.mark.parametrize(
    "fault", ["shared_node", "deleted_node", "retirement_link", "ambiguous_ownership"]
)
def test_unsafe_graph_history_requires_review(migration_db: MigrationDatabase, fault: str) -> None:
    ids = migration_db.seed(
        "duplicate" if fault in {"shared_node", "retirement_link"} else "normal"
    )
    if fault == "shared_node":
        migration_db.execute("UPDATE solus_entries SET entity_id=:node", {"node": ids["node"]})
    elif fault == "deleted_node":
        migration_db.execute(
            "UPDATE graph_entity SET deleted_at=now() WHERE id=:node", {"node": ids["node"]}
        )
    elif fault == "retirement_link":
        migration_db.execute(
            "INSERT INTO graph_edge(id,project_id,src_id,dst_id,relation_type,domain_pair,"
            "origin,confidence,attrs,created_at,updated_at) SELECT :id,project_id,id,:target,"
            "'references','project<->project','manual',1,'{}',now(),now() FROM graph_entity "
            "WHERE name='Duplicate config'",
            {"id": uuid.uuid4(), "target": ids["part"]},
        )
    else:
        # Two real manual roots claim one component through distinct live edges.
        second = uuid.uuid4()
        migration_db.execute(
            "INSERT INTO graph_entity(id,project_id,kind,domain,name,origin,version,attrs,"
            "modality_hints,created_at,updated_at) SELECT :id,project_id,kind,domain,'Other robot',"
            "origin,version,attrs,modality_hints,created_at,updated_at FROM "
            "graph_entity WHERE id=:owner",
            {"id": second, "owner": ids["owner"]},
        )
        for root in (ids["owner"], second):
            migration_db.execute(
                "INSERT INTO graph_edge(id,project_id,src_id,dst_id,relation_type,domain_pair,"
                "origin,confidence,attrs,created_at,updated_at) VALUES (:id,:project,:root,:part,"
                "'contains','project<->project','manual',1,'{}',now(),now())",
                {"id": uuid.uuid4(), "project": ids["project"], "root": root, "part": ids["part"]},
            )
    before = migration_db.rows("SELECT * FROM solus_entries ORDER BY id")
    with pytest.raises(RuntimeError):
        migration_db.upgrade()
    assert migration_db.rows("SELECT * FROM solus_entries ORDER BY id") == before


def test_validation_error_does_not_disclose_private_input(migration_db: MigrationDatabase) -> None:
    import traceback

    migration_db.seed()
    marker = "/private-fixture-sentinel/location"
    payload = json.loads(FIXTURE.read_text())
    payload["identity"]["binding"] = marker
    migration_db.execute(
        "UPDATE solus_entries SET payload=CAST(:payload AS jsonb)", {"payload": json.dumps(payload)}
    )
    with pytest.raises(RuntimeError) as result:
        migration_db.upgrade()
    assert marker not in "".join(traceback.format_exception(result.value))
