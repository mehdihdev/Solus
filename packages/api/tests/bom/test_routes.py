"""SOLUSDEV-246 (STORE ST4) — the BOM widget's backend over HTTP and the SOL tool.

`/api/v1/projects/{id}/widgets/bom/…` behind the ST1 guard: the view (a
fingerprinted servo once; a planned motor from sourcing; a raw-material row with
no design counterpart), lifecycle state per row, supplier preferences and cost
targets from the bundle's settings / `[ext.bom]` section, CSV export, tenant
isolation, and the "no orphans" uninstall.
"""

from __future__ import annotations

import uuid
from typing import Any

from conftest import add_member, me
from fixtures.extensions.bom_manifest import BOM_MANIFEST
from fixtures.extensions.routes import (
    consent,
    events_of,
    install,
    project_for,
    seed_extension,
)
from fixtures.injection_corpus import PAYLOADS, Surface
from httpx import AsyncClient
from solus_api.agent.prompt import tool_specs
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode
from solus_api.models import GraphEdge, GraphEntity
from solus_api.widgets.bom import CAPABILITY, SLUG
from solus_api.widgets.bom.rows import ITEM_KIND, NAME_MAX
from solus_contracts.extension_manifest import parse_extension_manifest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

NO_GRANTS: dict[str, list[str]] = {"scopes": [], "network": []}


def _bom(project_id: str, path: str = "rows") -> str:
    return f"/api/v1/projects/{project_id}/widgets/{SLUG}/{path}"


async def _seed_and_install(
    client: AsyncClient, db: AsyncSession, headers: dict[str, str]
) -> tuple[str, str]:
    team_id, project_id = await project_for(client, headers)
    await seed_extension(db, SLUG, {"0.1.0": BOM_MANIFEST})
    installed = await install(client, headers, project_id, SLUG, grants=NO_GRANTS)
    assert installed.status_code == 201, installed.text
    return team_id, project_id


def _entity(project_id: str, kind: str, domain: str, name: str, **extra: Any) -> GraphEntity:
    return GraphEntity(
        project_id=uuid.UUID(project_id), kind=kind, domain=domain, name=name, **extra
    )


async def _seed_design(db: AsyncSession, project_id: str) -> dict[str, uuid.UUID]:
    """A fingerprinted servo (CAD part + schematic symbol → one canonical), two
    identical resistors, an unlinked camera pair, and an assembly."""
    canonical = _entity(
        project_id,
        "canonical_part",
        "electrical",
        "MG996R",
        canonical_key="MG996R",
        origin="fingerprint",
        attrs={"fingerprint": {"manufacturer": "TowerPro"}},
    )
    db.add(canonical)
    await db.flush()
    rows = {
        "servo_cad": _entity(
            project_id,
            "part",
            "mechanical",
            "Servo body",
            modality_hints={"part_number": "MG996R", "cad_model": "ps/1"},
            canonical_part_id=canonical.id,
        ),
        "servo_sch": _entity(
            project_id,
            "component",
            "electrical",
            "U3",
            modality_hints={"part_number": "MG996R"},
            canonical_part_id=canonical.id,
            attrs={"value": "MG996R"},
        ),
        "r1": _entity(
            project_id,
            "component",
            "electrical",
            "R1",
            modality_hints={"part_number": "RC0402FR-0710KL"},
            attrs={"value": "10k"},
        ),
        "r2": _entity(
            project_id,
            "component",
            "electrical",
            "R2",
            modality_hints={"part_number": "RC0402FR-0710KL"},
            attrs={"value": "10k"},
        ),
        "cam_cad": _entity(project_id, "part", "mechanical", "Camera housing"),
        "cam_sch": _entity(
            project_id, "component", "electrical", "J7", modality_hints={"part_number": "OV9281"}
        ),
        "chassis": _entity(
            project_id, "part", "mechanical", "Chassis", attrs={"is_assembly": True}
        ),
    }
    db.add_all(rows.values())
    await db.flush()
    db.add(
        GraphEdge(
            project_id=uuid.UUID(project_id),
            src_id=rows["cam_cad"].id,
            dst_id=rows["cam_sch"].id,
            relation_type="same_as",
            domain_pair="electrical<->mechanical",
            origin="linking",
        )
    )
    await db.commit()
    return {name: row.id for name, row in rows.items()} | {"canonical": canonical.id}


async def _rows(client: AsyncClient, headers: dict[str, str], project_id: str) -> dict[str, Any]:
    resp = await client.get(_bom(project_id), headers=headers)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


def _by_name(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in rows}


# --------------------------------------------------------------------- view


async def test_the_view_shows_a_fingerprinted_servo_once_and_aggregates_by_mpn(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await _seed_and_install(client, db, alice_headers)
    ids = await _seed_design(db, project_id)

    data = await _rows(client, alice_headers, project_id)

    rows = _by_name(data["rows"])
    servo = rows["MG996R"]
    assert servo["key"] == f"canonical:{ids['canonical']}"
    assert servo["manufacturer"] == "TowerPro"
    assert servo["quantity"] == 1
    assert servo["state"] == "installed"
    assert sorted(s["domain"] for s in servo["sources"]) == ["electrical", "mechanical"]
    assert rows["RC0402FR-0710KL"]["quantity"] == 2
    camera = rows["OV9281"]
    assert camera["key"] == f"group:{min(ids['cam_cad'], ids['cam_sch'])}"
    assert "Chassis" not in rows
    assert len(data["rows"]) == 3
    assert data["states"] == ["planned", "ordered", "received", "installed", "retired"]
    assert data["config"] == {"preferred_suppliers": [], "cost_target": None, "currency": "USD"}
    assert data["totals"]["rows"] == 3
    assert data["truncated"] is False


async def test_an_empty_project_is_an_empty_bom_not_an_invented_one(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await _seed_and_install(client, db, alice_headers)
    data = await _rows(client, alice_headers, project_id)
    assert data["rows"] == []
    assert data["totals"] == {
        "rows": 0,
        "priced_rows": 0,
        "line_cost_total": 0.0,
        "cost_target": None,
        "over_target": None,
    }


async def test_routes_answer_only_where_the_bundle_is_installed(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await project_for(client, alice_headers)
    await seed_extension(db, SLUG, {"0.1.0": BOM_MANIFEST})
    assert (await client.get(_bom(project_id), headers=alice_headers)).status_code == 404
    assert (
        await client.get(_bom(project_id, "export.csv"), headers=alice_headers)
    ).status_code == 404


# ------------------------------------------------------------------- writes


async def test_a_planned_motor_and_a_raw_material_row_are_created_and_edited(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await _seed_and_install(client, db, alice_headers)
    alice = await me(client, alice_headers)
    await consent(db, alice["id"])

    motor = await client.post(
        _bom(project_id),
        json={
            "name": "NEMA 17 stepper",
            "category": "purchase",
            "quantity": 2,
            "part_number": "17HS4401",
            "supplier": "StepperOnline",
            "unit_cost": 14.5,
        },
        headers=alice_headers,
    )
    assert motor.status_code == 201, motor.text
    row = motor.json()["data"]
    assert row["kind"] == "purchase"
    assert row["state"] == "planned"
    assert row["line_cost"] == 29.0
    assert row["key"].startswith("item:")

    plate = await client.post(
        _bom(project_id),
        json={"name": "6061-T6 plate 3 mm", "category": "raw_material", "quantity": 4},
        headers=alice_headers,
    )
    assert plate.status_code == 201, plate.text
    assert plate.json()["data"]["part_number"] is None

    edited = await client.patch(
        _bom(project_id, f"rows/{row['key']}"),
        json={"state": "ordered", "quantity": 3, "notes": "ETA next week"},
        headers=alice_headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["state"] == "ordered"
    assert edited.json()["data"]["quantity"] == 3
    assert edited.json()["data"]["line_cost"] == 43.5

    data = await _rows(client, alice_headers, project_id)
    assert [r["kind"] for r in data["rows"]] == ["purchase", "raw_material"]
    assert data["totals"]["line_cost_total"] == 43.5

    removed = await client.delete(_bom(project_id, f"rows/{row['key']}"), headers=alice_headers)
    assert removed.status_code == 204
    assert [r["name"] for r in (await _rows(client, alice_headers, project_id))["rows"]] == [
        "6061-T6 plate 3 mm"
    ]
    # Soft-deleted per ADR-027, never hard-deleted.
    tombstones = await db.scalars(
        select(GraphEntity).where(
            GraphEntity.kind == ITEM_KIND, GraphEntity.deleted_at.is_not(None)
        )
    )
    assert len(list(tombstones)) == 1
    assert [e.payload["category"] for e in await events_of(db, "bom.item_added")] == [
        "purchase",
        "raw_material",
    ]


async def test_a_design_row_takes_lifecycle_state_through_an_overlay(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await _seed_and_install(client, db, alice_headers)
    ids = await _seed_design(db, project_id)
    key = f"canonical:{ids['canonical']}"

    patched = await client.patch(
        _bom(project_id, f"rows/{key}"),
        json={"state": "received", "supplier": "Mouser", "unit_cost": 8.25},
        headers=alice_headers,
    )
    assert patched.status_code == 200, patched.text
    row = patched.json()["data"]
    assert row["key"] == key
    assert row["state"] == "received"
    assert row["supplier"] == "Mouser"
    assert row["quantity"] == 1  # design quantity is the design's
    assert row["item_id"]

    # A second PATCH updates the same overlay; there is never a second one.
    again = await client.patch(
        _bom(project_id, f"rows/{key}"), json={"state": "installed"}, headers=alice_headers
    )
    assert again.json()["data"]["item_id"] == row["item_id"]
    overlays = await db.scalars(
        select(GraphEntity).where(GraphEntity.kind == ITEM_KIND, GraphEntity.deleted_at.is_(None))
    )
    assert len(list(overlays)) == 1

    # Design quantity and name are the design's — refused, not silently ignored.
    refused = await client.patch(
        _bom(project_id, f"rows/{key}"), json={"quantity": 5}, headers=alice_headers
    )
    assert refused.status_code == 422

    # DELETE on a design row clears its overlay; the part itself stays.
    assert (
        await client.delete(_bom(project_id, f"rows/{key}"), headers=alice_headers)
    ).status_code == 204
    rows = _by_name((await _rows(client, alice_headers, project_id))["rows"])
    assert rows["MG996R"]["state"] == "installed"
    assert rows["MG996R"]["supplier"] is None


async def test_bad_writes_are_422_and_unknown_rows_404(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await _seed_and_install(client, db, alice_headers)
    bad = [
        {"name": "", "category": "purchase"},
        {"name": "x", "category": "widget"},
        {"name": "x", "category": "purchase", "state": "lost"},
        {"name": "x", "category": "purchase", "quantity": 0},
        {"name": "x", "category": "purchase", "unit_cost": -1},
        {"name": "x", "category": "purchase", "project_id": project_id},
    ]
    for body in bad:
        resp = await client.post(_bom(project_id), json=body, headers=alice_headers)
        assert resp.status_code == 422, body
    assert (
        await client.patch(
            _bom(project_id, "rows/item:" + str(uuid.uuid4())),
            json={"state": "ordered"},
            headers=alice_headers,
        )
    ).status_code == 404
    assert (
        await client.patch(
            _bom(project_id, "rows/nonsense"), json={"state": "ordered"}, headers=alice_headers
        )
    ).status_code == 422
    assert (
        await client.patch(
            _bom(project_id, "rows/item:" + str(uuid.uuid4())), json={}, headers=alice_headers
        )
    ).status_code == 422


async def test_config_comes_from_install_settings(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await _seed_and_install(client, db, alice_headers)
    patched = await client.patch(
        f"/api/v1/projects/{project_id}/extensions/{SLUG}",
        json={
            "settings": {
                "preferred_suppliers": "Mouser, Digi-Key ,,LCSC",
                "cost_target": 250,
                "currency": "EUR",
            }
        },
        headers=alice_headers,
    )
    assert patched.status_code == 200, patched.text
    await client.post(
        _bom(project_id),
        json={"name": "Motor", "category": "purchase", "quantity": 10, "unit_cost": 30},
        headers=alice_headers,
    )
    data = await _rows(client, alice_headers, project_id)
    assert data["config"] == {
        "preferred_suppliers": ["Mouser", "Digi-Key", "LCSC"],
        "cost_target": 250.0,
        "currency": "EUR",
    }
    assert data["totals"]["over_target"] is True


# --------------------------------------------------------------------- csv


async def test_csv_export_is_a_text_csv_attachment(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await _seed_and_install(client, db, alice_headers)
    await _seed_design(db, project_id)
    await client.post(
        _bom(project_id),
        json={"name": "Plate", "category": "raw_material", "quantity": 2, "unit_cost": 3.5},
        headers=alice_headers,
    )
    resp = await client.get(_bom(project_id, "export.csv"), headers=alice_headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    assert "bom-" in resp.headers["content-disposition"]
    lines = [line for line in resp.text.split("\r\n") if line]
    assert lines[0].startswith("key,kind,name,part_number")
    assert len(lines) == 5
    assert any("MG996R" in line and "TowerPro" in line for line in lines)


# ------------------------------------------------------------------- roles


async def test_viewers_read_but_cannot_write_and_strangers_see_nothing(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    team_id, project_id = await _seed_and_install(client, db, alice_headers)
    await client.post(
        _bom(project_id),
        json={"name": "Secret motor", "category": "purchase"},
        headers=alice_headers,
    )
    assert (await client.get(_bom(project_id), headers=bob_headers)).status_code == 404

    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, bob, team_id, role="viewer")
    seen = await client.get(_bom(project_id), headers=bob_headers)
    assert seen.status_code == 200
    assert [r["name"] for r in seen.json()["data"]["rows"]] == ["Secret motor"]
    forbidden = await client.post(
        _bom(project_id), json={"name": "x", "category": "purchase"}, headers=bob_headers
    )
    assert forbidden.status_code == 403

    # Bob's own project, same bundle installed: none of Alice's rows.
    _, bobs_project = await project_for(client, bob_headers)
    assert (
        await install(client, bob_headers, bobs_project, SLUG, grants=NO_GRANTS)
    ).status_code == 201
    own = await client.get(_bom(bobs_project), headers=bob_headers)
    assert own.status_code == 200 and own.json()["data"]["rows"] == []


# --------------------------------------------------------------- SOL tool


async def test_the_sol_tool_adds_a_planned_item_scoped_by_solus_code(
    client: AsyncClient, db: AsyncSession, engine: AsyncEngine, alice_headers: dict[str, str]
) -> None:
    _, project_id = await _seed_and_install(client, db, alice_headers)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = build_sol_registry(
        factory,
        uuid.UUID(project_id),
        bundle_capabilities=[(CAPABILITY, parse_extension_manifest(BOM_MANIFEST))],
    )
    assert "bom.add_item" in {d.name for d in registry.list()}

    result = await registry.invoke(
        ToolCall(
            tool="bom.add_item",
            args={"name": "Planned motor", "category": "purchase", "quantity": 2},
        )
    )
    assert result.ok and result.value is not None, result.error
    assert result.value["state"] == "planned"
    assert result.value["key"].startswith("item:")

    smuggled = await registry.invoke(
        ToolCall(
            tool="bom.add_item",
            args={"name": "x", "category": "purchase", "project_id": str(uuid.uuid4())},
        )
    )
    assert not smuggled.ok and smuggled.error is not None
    assert smuggled.error.code == ToolErrorCode.INVALID_ARGS

    rows = (await _rows(client, alice_headers, project_id))["rows"]
    assert [r["name"] for r in rows] == ["Planned motor"]


# ---------------------------------------------------------------- uninstall


async def test_uninstall_soft_deletes_bom_items_but_never_design_rows(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await _seed_and_install(client, db, alice_headers)
    ids = await _seed_design(db, project_id)
    await client.post(
        _bom(project_id), json={"name": "Plate", "category": "raw_material"}, headers=alice_headers
    )
    await client.patch(
        _bom(project_id, f"rows/canonical:{ids['canonical']}"),
        json={"state": "ordered"},
        headers=alice_headers,
    )

    gone = await client.delete(
        f"/api/v1/projects/{project_id}/extensions/{SLUG}", headers=alice_headers
    )
    assert gone.status_code == 204

    live_items = await db.scalars(
        select(GraphEntity).where(GraphEntity.kind == ITEM_KIND, GraphEntity.deleted_at.is_(None))
    )
    assert list(live_items) == []
    design = await db.scalars(
        select(GraphEntity).where(
            GraphEntity.kind.in_(["part", "component", "canonical_part"]),
            GraphEntity.deleted_at.is_(None),
        )
    )
    assert len(list(design)) == 8  # 7 observations + the canonical row
    assert (await client.get(_bom(project_id), headers=alice_headers)).status_code == 404


# ------------------------------------------------------ security review fixes


async def test_a_row_key_from_another_project_never_resolves(
    client: AsyncClient,
    db: AsyncSession,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    """H2: keys are project-scoped. An item minted in Alice's project is a 404
    in Bob's (PATCH and DELETE), and a non-member's writes are 404 (no leak)."""
    _, project_a = await _seed_and_install(client, db, alice_headers)
    made = await client.post(
        _bom(project_a),
        json={"name": "Secret motor", "category": "purchase"},
        headers=alice_headers,
    )
    key = made.json()["data"]["key"]
    _, project_b = await project_for(client, bob_headers)
    assert (
        await install(client, bob_headers, project_b, SLUG, grants=NO_GRANTS)
    ).status_code == 201

    for method, url, body in (
        ("PATCH", _bom(project_b, f"rows/{key}"), {"state": "ordered"}),
        ("DELETE", _bom(project_b, f"rows/{key}"), None),
        ("PATCH", _bom(project_a, f"rows/{key}"), {"state": "ordered"}),
        ("DELETE", _bom(project_a, f"rows/{key}"), None),
        ("POST", _bom(project_a), {"name": "x", "category": "purchase"}),
    ):
        resp = await client.request(method, url, json=body, headers=bob_headers)
        assert resp.status_code == 404, (method, url, resp.text)
    rows = (await _rows(client, alice_headers, project_a))["rows"]
    assert [r["name"] for r in rows] == ["Secret motor"]
    assert rows[0]["state"] == "planned"


async def test_costs_are_bounded_on_every_path_and_never_break_the_view(
    client: AsyncClient, db: AsyncSession, engine: AsyncEngine, alice_headers: dict[str, str]
) -> None:
    """H1: the route and the tool share COST_MAX; a stored non-finite or
    over-cap value (written before the bound) is read as unknown, so the view
    and the CSV stay serialisable."""
    _, project_id = await _seed_and_install(client, db, alice_headers)
    too_much = await client.post(
        _bom(project_id),
        json={"name": "x", "category": "purchase", "unit_cost": 1e12},
        headers=alice_headers,
    )
    assert too_much.status_code == 422
    registry = build_sol_registry(
        async_sessionmaker(engine, expire_on_commit=False),
        uuid.UUID(project_id),
        bundle_capabilities=[(CAPABILITY, parse_extension_manifest(BOM_MANIFEST))],
    )
    result = await registry.invoke(
        ToolCall(
            tool="bom.add_item", args={"name": "x", "category": "purchase", "unit_cost": 1e300}
        )
    )
    assert not result.ok and result.error is not None
    assert result.error.code == ToolErrorCode.INVALID_ARGS
    # A poisoned row (as if written before the bound existed).
    db.add(
        _entity(
            project_id,
            ITEM_KIND,
            "project",
            "Poisoned",
            origin="extension",
            attrs={
                "category": "purchase",
                "state": "planned",
                "quantity": 100000,
                "unit_cost": 1e308,
            },
        )
    )
    await db.commit()
    data = await _rows(client, alice_headers, project_id)
    poisoned = _by_name(data["rows"])["Poisoned"]
    assert poisoned["unit_cost"] is None and poisoned["line_cost"] is None
    assert data["totals"]["line_cost_total"] == 0.0
    assert (
        await client.get(_bom(project_id, "export.csv"), headers=alice_headers)
    ).status_code == 200


async def test_hand_added_rows_are_capped_per_project(
    client: AsyncClient, db: AsyncSession, engine: AsyncEngine, alice_headers: dict[str, str]
) -> None:
    """M4: `max_items` (manifest default ← [ext.bom] ← install settings) bounds
    items AND overlays, on the route and on the tool."""
    _, project_id = await _seed_and_install(client, db, alice_headers)
    ids = await _seed_design(db, project_id)
    patched = await client.patch(
        f"/api/v1/projects/{project_id}/extensions/{SLUG}",
        json={"settings": {"max_items": 2}},
        headers=alice_headers,
    )
    assert patched.status_code == 200, patched.text
    for name in ("one", "two"):
        ok = await client.post(
            _bom(project_id), json={"name": name, "category": "purchase"}, headers=alice_headers
        )
        assert ok.status_code == 201, ok.text
    full = await client.post(
        _bom(project_id), json={"name": "three", "category": "purchase"}, headers=alice_headers
    )
    assert full.status_code == 422 and "max_items" in full.json()["error"]["message"]
    overlay = await client.patch(
        _bom(project_id, f"rows/canonical:{ids['canonical']}"),
        json={"state": "ordered"},
        headers=alice_headers,
    )
    assert overlay.status_code == 422
    registry = build_sol_registry(
        async_sessionmaker(engine, expire_on_commit=False),
        uuid.UUID(project_id),
        bundle_capabilities=[(CAPABILITY, parse_extension_manifest(BOM_MANIFEST))],
    )
    result = await registry.invoke(
        ToolCall(tool="bom.add_item", args={"name": "four", "category": "purchase"})
    )
    assert not result.ok and result.error is not None
    assert "max_items" in result.error.message
    # Removing one frees a slot.
    first = _by_name((await _rows(client, alice_headers, project_id))["rows"])["one"]
    assert (
        await client.delete(_bom(project_id, f"rows/{first['key']}"), headers=alice_headers)
    ).status_code == 204
    assert (
        await client.post(
            _bom(project_id), json={"name": "three", "category": "purchase"}, headers=alice_headers
        )
    ).status_code == 201


async def test_control_characters_are_refused_at_the_boundary(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    _, project_id = await _seed_and_install(client, db, alice_headers)
    for body in (
        {"name": "Mo\x00tor", "category": "purchase"},
        {"name": "Motor", "category": "purchase", "supplier": "A\u202eB"},
        {"name": "Motor", "category": "purchase", "notes": "line\x07bell"},
    ):
        resp = await client.post(_bom(project_id), json=body, headers=alice_headers)
        assert resp.status_code == 422, body
    fine = await client.post(
        _bom(project_id),
        json={"name": "Motor", "category": "purchase", "notes": "two\nlines"},
        headers=alice_headers,
    )
    assert fine.status_code == 201, fine.text


async def test_a_hostile_part_name_is_data_in_the_view_the_csv_and_the_tool_result(
    client: AsyncClient, db: AsyncSession, engine: AsyncEngine, alice_headers: dict[str, str]
) -> None:
    """H3 (CLAUDE.md §7 red team): an injection payload carried by a connector
    part name or a hand-added row reaches the BOM only as a string field —
    never as markup, never outside its JSON value, and never changes the tool
    set offered to SOL."""
    _, project_id = await _seed_and_install(client, db, alice_headers)
    # The corpus payload, cut to the BOM's name cap (the content is the point).
    hostile = next(p.text for p in PAYLOADS if p.surface is Surface.PART_NAME)[:NAME_MAX]
    db.add(
        _entity(
            project_id,
            "component",
            "electrical",
            hostile,
            modality_hints={"part_number": "INJ-01"},
            external_ref="INJ",
        )
    )
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = build_sol_registry(
        factory,
        uuid.UUID(project_id),
        bundle_capabilities=[(CAPABILITY, parse_extension_manifest(BOM_MANIFEST))],
    )
    baseline = tool_specs(tuple(registry.list()))
    result = await registry.invoke(
        ToolCall(tool="bom.add_item", args={"name": hostile, "category": "raw_material"})
    )
    assert result.ok and result.value is not None
    assert result.value["name"] == hostile  # a value, echoed as a value
    assert tool_specs(tuple(registry.list())) == baseline

    data = await _rows(client, alice_headers, project_id)
    rows = data["rows"]
    # The hand-added row carries it as its name; the connector row shows its
    # part number and carries the hostile string as a SOURCE name — text either way.
    assert [r["name"] for r in rows if r["kind"] == "raw_material"] == [hostile]
    assert any(s["name"] == hostile for r in rows for s in r["sources"])
    csv_text = (await client.get(_bom(project_id, "export.csv"), headers=alice_headers)).text
    entry = next(row for row in csv_text.splitlines() if "raw_material" in row)
    assert hostile.split(" ")[0] in entry
    assert "\n" not in entry.rstrip("\r")
