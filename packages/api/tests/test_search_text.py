"""SOLUSDEV-320 T7 — the Python twins of the generated search columns equal the SQL.

`graph_entity.search_text` / `solus_entries.search_text` are GENERATED ALWAYS columns, so no
write path can get them wrong; the Python twins exist so code that reasons about a row before
it is flushed (and the parity test) sees the same text the database stores.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from solus_api.graph.search_text import (
    MAX_PAYLOAD_DEPTH,
    SEARCH_TEXT_MAX_CHARS,
    entity_search_text,
    entry_search_text,
    flatten_payload,
)
from solus_api.models import (
    Domain,
    GraphEntity,
    Project,
    SolusEntry,
    SolusEntryKind,
    SolusSection,
    Team,
)
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

CAN_BASE = Path(__file__).parent / "fixtures" / "hardware" / "can_base.json"


async def _search_text_project(db: AsyncSession) -> uuid.UUID:
    team = Team(name="search-text")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="search-text")
    db.add(project)
    await db.flush()
    return project.id


def _search_text_entities(project_id: uuid.UUID) -> list[GraphEntity]:
    return [
        GraphEntity(
            project_id=project_id,
            kind="component",
            domain=Domain.ELECTRICAL,
            name="U3",
            external_ref="sch:U3",
            origin="connector",
            attrs={"footprint": "QFN-48"},
            modality_hints={"part_number": "OV9281"},
        ),
        GraphEntity(
            project_id=project_id,
            kind="code_file",
            domain=Domain.CODE,
            name="main.py",
            external_ref="firmware/src/main.py",
            origin="connector",
            attrs={"path": "firmware/src/main.py", "size": 1200},
        ),
        GraphEntity(
            project_id=project_id,
            kind="net",
            domain=Domain.ELECTRICAL,
            name="net:I2C_SDA",
            origin="connector",
            attrs={"net": "I2C_SDA", "address": "0x68"},
        ),
        GraphEntity(
            project_id=project_id,
            kind="part",
            domain=Domain.MECHANICAL,
            name="  Motor Mount ",
            origin="manual",
            attrs={"manufacturer": "ACME Robotics", "mpn": "MM-100", "part_number": 7},
        ),
        GraphEntity(
            project_id=project_id,
            kind="motor",
            domain=Domain.RUNTIME,
            name="joint_1",
            origin="system",
            attrs={"path": {"nested": True}},
        ),
    ]


async def test_entity_search_text_twin_equals_the_generated_column(db: AsyncSession) -> None:
    project_id = await _search_text_project(db)
    rows = _search_text_entities(project_id)
    db.add_all(rows)
    await db.flush()
    for row in rows:
        await db.refresh(row)
        assert row.search_text == entity_search_text(row), row.name
        assert row.search_text is not None and row.search_text == row.search_text.strip(" ")
    assert rows[0].search_text == "U3 sch:U3       OV9281"
    assert rows[1].search_text == "main.py firmware/src/main.py firmware/src/main.py"


def _nested_payload(depth: int) -> dict[str, Any]:
    doc: dict[str, Any] = {"leaf": "bottom"}
    for level in range(depth):
        doc = {f"l{level}": doc}
    return doc


async def _sql_flatten(db: AsyncSession, payload: Any) -> str | None:
    stmt = text("SELECT solus_payload_text(:p)").bindparams(bindparam("p", type_=JSONB))
    return (await db.execute(stmt, {"p": payload})).scalar()


async def test_flatten_payload_twin_equals_solus_payload_text(db: AsyncSession) -> None:
    can_base = json.loads(CAN_BASE.read_text())
    assert await _sql_flatten(db, can_base) == flatten_payload(can_base)
    flat = flatten_payload(can_base)
    assert "identity.binding ODRV-3F2A-CAN0" in flat
    assert "bus_map.1.model ODrive S1" in flat
    assert "protocol.params.bitrate 250000" in flat

    mixed = {
        "b": 1,
        "aa": 2,
        "a": [True, 1.5, None, {"z": "x y"}, []],
        "c": 1e-7,
        "d": 40.0,
        "e": {},
        "f": "",
    }
    assert await _sql_flatten(db, mixed) == flatten_payload(mixed)
    # jsonb key order: shorter keys first, then bytewise.
    assert flatten_payload(mixed).startswith("a.0 true a.1 1.5 a.3.z x y b 1 c 0.0000001 d 40.0")

    for depth in (MAX_PAYLOAD_DEPTH - 1, MAX_PAYLOAD_DEPTH, MAX_PAYLOAD_DEPTH + 1):
        doc = _nested_payload(depth)
        assert await _sql_flatten(db, doc) == flatten_payload(doc), depth
    assert flatten_payload(_nested_payload(MAX_PAYLOAD_DEPTH + 3)) == ""
    assert flatten_payload("scalar") == "scalar" == await _sql_flatten(db, "scalar")
    assert await _sql_flatten(db, None) == "" == flatten_payload(None)  # a JSON null


async def test_entry_search_text_twin_equals_the_generated_column(db: AsyncSession) -> None:
    project_id = await _search_text_project(db)
    robot = GraphEntity(
        project_id=project_id, kind="robot", domain=Domain.RUNTIME, name="base", origin="manual"
    )
    db.add(robot)
    await db.flush()
    entries = [
        SolusEntry(
            project_id=project_id,
            section=SolusSection.ENVIRONMENT,
            subsection="hardware",
            kind=SolusEntryKind.CONFIG,
            text="Hardware config — base",
            payload=json.loads(CAN_BASE.read_text()),
            entity_id=robot.id,
            configured_entity_id=robot.id,
            config_version=1,
        ),
        SolusEntry(
            project_id=project_id,
            section=SolusSection.GOALS,
            kind=SolusEntryKind.TEXT,
            text="Drive 10 m straight",
            entity_id=robot.id,
        ),
        SolusEntry(
            project_id=project_id,
            section=SolusSection.ERRORS,
            kind=SolusEntryKind.SOL,
            text=None,
            payload={"code": "E42"},
            entity_id=robot.id,
        ),
    ]
    db.add_all(entries)
    await db.flush()
    for entry in entries:
        await db.refresh(entry)
        assert entry.search_text == entry_search_text(entry), entry.section
    assert entries[1].search_text == "Drive 10 m straight"
    assert entries[2].search_text == "code E42"


async def test_solus_payload_text_does_not_depend_on_search_path(db: AsyncSession) -> None:
    """pg_restore recomputes the STORED columns under `search_path = ''` (DR of a logical
    backup); the recursive helper must resolve its own calls without it."""
    await db.execute(text("SET LOCAL search_path = ''"))
    payload = {"identity": {"device_ref": "usb:5B42"}, "bus_map": [{"model": "STS3215"}]}
    stmt = text("SELECT public.solus_payload_text(:p)").bindparams(bindparam("p", type_=JSONB))
    assert (await db.execute(stmt, {"p": payload})).scalar() == flatten_payload(payload)


async def test_oversized_ingested_fields_are_capped_not_fatal(db: AsyncSession) -> None:
    """A ~1 MB attr from a hostile source must not make the row's write fail
    (`string is too long for tsvector`); the index text is capped and the twin agrees."""
    project_id = await _search_text_project(db)
    huge = " ".join(f"tok{i}" for i in range(200_000))
    entity = GraphEntity(
        project_id=project_id,
        kind="code_file",
        domain=Domain.CODE,
        name="big.py",
        origin="connector",
        attrs={"path": huge},
    )
    entry = SolusEntry(
        project_id=project_id,
        section=SolusSection.GOALS,
        kind=SolusEntryKind.TEXT,
        text=huge,
    )
    db.add_all([entity, entry])
    await db.flush()
    for row in (entity, entry):
        await db.refresh(row)
    assert entity.search_text == entity_search_text(entity)
    assert entry.search_text == entry_search_text(entry)
    assert len(entity.search_text or "") == SEARCH_TEXT_MAX_CHARS
    assert len(entry.search_text or "") == SEARCH_TEXT_MAX_CHARS
    assert (entity.search_text or "").startswith("big.py  tok0 tok1")
