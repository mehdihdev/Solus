"""SOLUSDEV-246 (STORE ST4) — the BOM view builder, pure (graph rows in, BOM rows out).

The BOM is a VIEW over canonical parts: an observation in CAD, in the schematic
and in a purchase list is ONE row when the fingerprint (or a confirmed `same_as`
link) says so. Cross-domain identity comes ONLY from those two shapes — the BOM
never merges a CAD part with a schematic symbol by name (ADR-012 zero-false-merge
posture). Within one domain, identical normalized part numbers aggregate into one
row with a quantity, which is what a bill of materials is.
"""

from __future__ import annotations

import uuid

import pytest
from solus_api.widgets.bom.rows import (
    DEFAULT_DESIGN_STATE,
    DEFAULT_ITEM_STATE,
    LIFECYCLE_STATES,
    QUANTITY_MAX,
    BomRow,
    Canonical,
    Item,
    Observation,
    build_rows,
    csv_cell,
    is_row_key,
    normalized_part_number,
    render_csv,
    totals,
)

U = uuid.UUID


def _id(n: int) -> uuid.UUID:
    return U(f"00000000-0000-7000-8000-{n:012d}")


def obs(
    n: int,
    kind: str,
    domain: str,
    name: str,
    *,
    part_number: str | None = None,
    value: str | None = None,
    manufacturer: str | None = None,
    canonical: uuid.UUID | None = None,
    is_assembly: bool = False,
) -> Observation:
    return Observation(
        id=_id(n),
        kind=kind,
        domain=domain,
        name=name,
        value=value,
        part_number=part_number,
        manufacturer=manufacturer,
        canonical_part_id=canonical,
        is_assembly=is_assembly,
    )


def item(
    n: int,
    name: str,
    category: str = "purchase",
    *,
    row_key: str | None = None,
    quantity: int = 1,
    state: str = DEFAULT_ITEM_STATE,
    supplier: str | None = None,
    unit_cost: float | None = None,
    part_number: str | None = None,
    notes: str | None = None,
) -> Item:
    return Item(
        id=_id(n),
        name=name,
        category=category,
        quantity=quantity,
        state=state,
        row_key=row_key,
        part_number=part_number,
        manufacturer=None,
        supplier=supplier,
        unit_cost=unit_cost,
        notes=notes,
    )


def by_key(rows: list[BomRow]) -> dict[str, BomRow]:
    return {row.key: row for row in rows}


# ------------------------------------------------------------------ identity


def test_a_fingerprinted_servo_in_cad_and_schematic_is_one_row() -> None:
    canonical = Canonical(id=_id(9), name="MG996R", manufacturer="TowerPro")
    servo_cad = obs(1, "part", "mechanical", "Servo bracket mount", part_number="MG996R")
    servo_sch = obs(2, "component", "electrical", "U3", part_number="MG996R")
    linked = [
        Observation(**{**servo_cad.__dict__, "canonical_part_id": canonical.id}),
        Observation(**{**servo_sch.__dict__, "canonical_part_id": canonical.id}),
    ]

    rows = build_rows(linked, [canonical], [], [])

    assert len(rows) == 1
    row = rows[0]
    assert row.key == f"canonical:{canonical.id}"
    assert row.kind == "design"
    assert row.name == "MG996R"
    assert row.manufacturer == "TowerPro"
    assert row.canonical_id == canonical.id
    assert sorted((s.domain, s.name) for s in row.sources) == [
        ("electrical", "U3"),
        ("mechanical", "Servo bracket mount"),
    ]
    # One schematic placement → quantity 1, not 2 (the CAD body is the same part).
    assert row.quantity == 1
    assert row.state == DEFAULT_DESIGN_STATE


def test_the_same_part_number_across_domains_is_not_merged_without_a_fingerprint() -> None:
    """Zero-false-merge: a CAD name and a schematic symbol sharing an MPN string
    stay two rows until the fingerprint (canonical) or a same_as link says otherwise."""
    rows = build_rows(
        [
            obs(1, "part", "mechanical", "Servo", part_number="MG996R"),
            obs(2, "component", "electrical", "U3", part_number="MG996R"),
        ],
        [],
        [],
        [],
    )
    assert len(rows) == 2
    assert {row.key for row in rows} == {"mpn:mechanical:MG996R", "mpn:electrical:MG996R"}


def test_a_confirmed_same_as_link_merges_two_observations() -> None:
    cad = obs(1, "part", "mechanical", "Camera housing")
    sch = obs(2, "component", "electrical", "J7", part_number="OV9281")
    rows = build_rows([cad, sch], [], [(cad.id, sch.id)], [])
    assert len(rows) == 1
    assert rows[0].key == f"group:{cad.id}"
    assert rows[0].name == "OV9281"
    assert len(rows[0].sources) == 2


def test_identical_part_numbers_in_one_domain_aggregate_into_a_quantity() -> None:
    rows = build_rows(
        [
            obs(1, "component", "electrical", "R1", part_number="RC0402FR-0710KL", value="10k"),
            obs(2, "component", "electrical", "R2", part_number="RC0402FR-0710KL", value="10k"),
            obs(3, "component", "electrical", "R3", part_number="rc0402fr-0710kl", value="10k"),
        ],
        [],
        [],
        [],
    )
    assert len(rows) == 1
    assert rows[0].quantity == 3
    assert rows[0].key == f"mpn:electrical:{normalized_part_number('RC0402FR-0710KL')}"
    assert [s.name for s in rows[0].sources] == ["R1", "R2", "R3"]


def test_parts_without_a_part_number_stay_separate_rows_named_by_value() -> None:
    rows = build_rows(
        [
            obs(1, "component", "electrical", "C1", value="100n"),
            obs(2, "component", "electrical", "C2", value="100n"),
        ],
        [],
        [],
        [],
    )
    assert len(rows) == 2
    assert {row.name for row in rows} == {"100n"}
    assert {row.key for row in rows} == {f"entity:{_id(1)}", f"entity:{_id(2)}"}
    assert all(row.part_number is None for row in rows)


def test_cad_assemblies_and_non_part_kinds_are_not_bom_rows() -> None:
    rows = build_rows(
        [
            obs(1, "part", "mechanical", "Chassis", is_assembly=True),
            obs(2, "net", "electrical", "GND"),
            obs(3, "code_module", "code", "motor_driver.cpp"),
            obs(4, "part", "mechanical", "Bracket"),
        ],
        [],
        [],
        [],
    )
    assert [row.name for row in rows] == ["Bracket"]


def test_a_dangling_canonical_reference_does_not_merge() -> None:
    """The observation points at a canonical row that is soft-deleted (not in
    the live set): it is treated as unlinked rather than inventing a group."""
    rows = build_rows(
        [
            obs(1, "part", "mechanical", "Servo", canonical=_id(99)),
            obs(2, "component", "electrical", "U3", canonical=_id(99)),
        ],
        [],
        [],
        [],
    )
    assert len(rows) == 2
    assert {row.key for row in rows} == {f"entity:{_id(1)}", f"entity:{_id(2)}"}


# ------------------------------------------------------------------ items


def test_a_planned_purchase_from_sourcing_appears_as_planned() -> None:
    rows = build_rows(
        [], [], [], [item(1, "NEMA 17 stepper", "purchase", quantity=2, unit_cost=14.5)]
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == "purchase"
    assert row.key == f"item:{_id(1)}"
    assert row.state == "planned"
    assert row.quantity == 2
    assert row.line_cost == 29.0
    assert row.sources == ()
    assert row.item_id == _id(1)


def test_a_raw_material_row_with_no_part_works() -> None:
    rows = build_rows([], [], [], [item(1, "6061-T6 plate 3 mm", "raw_material", quantity=4)])
    assert rows[0].kind == "raw_material"
    assert rows[0].part_number is None
    assert rows[0].canonical_id is None


def test_an_overlay_item_sets_state_supplier_and_cost_on_a_design_row() -> None:
    sch = obs(2, "component", "electrical", "U3", part_number="MG996R")
    key = "mpn:electrical:MG996R"
    overlay = item(
        5,
        "MG996R",
        "overlay",
        row_key=key,
        state="ordered",
        supplier="Digi-Key",
        unit_cost=9.9,
        notes="lead time 2w",
        quantity=50,  # ignored: design quantity comes from the design
    )
    rows = build_rows([sch], [], [], [overlay])
    assert len(rows) == 1
    row = rows[0]
    assert row.key == key
    assert row.state == "ordered"
    assert row.supplier == "Digi-Key"
    assert row.unit_cost == 9.9
    assert row.notes == "lead time 2w"
    assert row.quantity == 1
    assert row.item_id == overlay.id


def test_an_orphaned_overlay_is_dropped_not_shown_as_a_part() -> None:
    rows = build_rows([], [], [], [item(5, "x", "overlay", row_key="entity:" + str(_id(7)))])
    assert rows == []


def test_rows_are_ordered_design_then_purchases_then_raw_materials_by_name() -> None:
    rows = build_rows(
        [obs(1, "part", "mechanical", "Zeta bracket"), obs(2, "part", "mechanical", "Alpha arm")],
        [],
        [],
        [item(3, "Steel rod", "raw_material"), item(4, "Motor", "purchase")],
    )
    assert [(row.kind, row.name) for row in rows] == [
        ("design", "Alpha arm"),
        ("design", "Zeta bracket"),
        ("purchase", "Motor"),
        ("raw_material", "Steel rod"),
    ]


# ------------------------------------------------------------------ helpers


def test_lifecycle_states_are_the_r5_five_in_order() -> None:
    assert LIFECYCLE_STATES == ("planned", "ordered", "received", "installed", "retired")


@pytest.mark.parametrize(
    ("key", "ok"),
    [
        (f"canonical:{_id(1)}", True),
        (f"group:{_id(1)}", True),
        (f"entity:{_id(1)}", True),
        (f"item:{_id(1)}", True),
        ("mpn:electrical:RC0402FR0710KL", True),
        ("mpn:electrical:", False),
        ("mpn:workspace:ABC", False),
        ("canonical:not-a-uuid", False),
        ("bogus:" + str(_id(1)), False),
        ("", False),
    ],
)
def test_row_key_validation(key: str, ok: bool) -> None:
    assert is_row_key(key) is ok


def test_normalized_part_number_uses_the_fingerprint_normalizer() -> None:
    assert normalized_part_number("rc0402fr-0710kl") == normalized_part_number("RC0402FR-0710KL")
    assert normalized_part_number("10k") is None
    assert normalized_part_number("") is None
    assert normalized_part_number(None) is None


def test_totals_sum_priced_lines_and_compare_to_the_target() -> None:
    rows = build_rows(
        [],
        [],
        [],
        [
            item(1, "A", "purchase", quantity=2, unit_cost=10.0),
            item(2, "B", "purchase", quantity=1),
            item(3, "C", "raw_material", quantity=3, unit_cost=1.25),
        ],
    )
    assert totals(rows, cost_target=20.0) == {
        "rows": 3,
        "priced_rows": 2,
        "line_cost_total": 23.75,
        "cost_target": 20.0,
        "over_target": True,
    }
    assert totals(rows, cost_target=None)["over_target"] is None


def test_csv_has_a_header_one_line_per_row_and_neutralises_formulas() -> None:
    rows = build_rows(
        [obs(1, "component", "electrical", "U3", part_number='=HYPERLINK("x")', value="v")],
        [],
        [],
        [item(2, "Plate, steel", "raw_material", quantity=2, unit_cost=3.5, notes="-wide")],
    )
    text = render_csv(rows)
    lines = text.split("\r\n")
    assert lines[0] == (
        "key,kind,name,part_number,manufacturer,quantity,state,supplier,"
        "unit_cost,line_cost,sources,notes"
    )
    assert len([line for line in lines if line]) == 3
    # A cell that starts like a spreadsheet formula is prefixed so it is text.
    assert "'=HYPERLINK" in text
    assert "'-wide" in text
    assert '"Plate, steel"' in text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("plain", "plain"), ("=1+1", "'=1+1"), ("+1", "'+1"), ("@cmd", "'@cmd"), ("", "")],
)
def test_csv_cell_guard(raw: str, expected: str) -> None:
    assert csv_cell(raw) == expected


def test_costs_past_the_bound_or_non_finite_are_unknown_not_infinite() -> None:
    from solus_api.widgets.bom.rows import COST_MAX

    huge = item(1, "A", "purchase", quantity=QUANTITY_MAX, unit_cost=COST_MAX)
    [row] = build_rows([], [], [], [huge])
    assert row.line_cost == round(COST_MAX * QUANTITY_MAX, 2)
    assert row.line_cost is not None and row.line_cost < float("inf")
    assert totals([row], None)["line_cost_total"] == row.line_cost


@pytest.mark.parametrize("raw", [float("inf"), float("nan"), -1, 1e300, True, "12"])
def test_item_from_entity_drops_bad_costs(raw: object) -> None:
    from solus_api.models import GraphEntity
    from solus_api.widgets.bom.rows import item_from_entity

    entity = GraphEntity(
        id=_id(1),
        project_id=_id(2),
        kind="ext:bom:item",
        domain="project",
        name="x",
        attrs={"category": "purchase", "state": "planned", "unit_cost": raw},
    )
    parsed = item_from_entity(entity)
    assert parsed is not None and parsed.unit_cost is None
