"""The BOM view builder (SOLUSDEV-246, STORE ST4) — pure: graph rows in, BOM rows out.

A bill of materials is a VIEW over canonical parts. Cross-domain identity comes
from exactly two graph shapes, both written by Solus code that already carries
the zero-false-merge posture (ADR-012): `graph_entity.canonical_part_id` (the
fingerprint's assertion) and `same_as` edges (the linker / a confirmed match).
This module never merges a CAD part with a schematic symbol on its own — two
observations that share an MPN string across domains stay two rows until the
fingerprint says otherwise. Within ONE domain, identical normalized part numbers
aggregate into one row with a quantity, which is what a BOM is.

Rows the design does not know about — raw materials, purchases, a motor that is
still being sourced — are `ext:bom:item` entities (origin `extension`, domain
`project`). An item with `category = "overlay"` annotates a design row (lifecycle
state, supplier, cost, notes) without ever touching the connector-owned rows.
"""

from __future__ import annotations

import csv
import io
import math
import re
import uuid
from dataclasses import dataclass
from typing import Any

from solus_contracts.extension_manifest import graph_kind_name

from solus_api.fingerprint.config import default_fingerprint_config
from solus_api.fingerprint.normalize import normalize_mpn
from solus_api.models import GraphEntity

SLUG = "bom"
ITEM_KIND = graph_kind_name(SLUG, "item")
CANONICAL_KIND = "canonical_part"
RELATION_SAME_AS = "same_as"
#: Connector kinds that are physical parts: EDA `component` (eda.py), CAD `part` (mechanical.py).
DESIGN_KINDS = frozenset({"component", "part"})

#: R5 lifecycle, in order (locked in-chat 2026-09-06).
LIFECYCLE_STATES = ("planned", "ordered", "received", "installed", "retired")
DEFAULT_DESIGN_STATE = "installed"
DEFAULT_ITEM_STATE = "planned"

ITEM_CATEGORIES = ("raw_material", "purchase")
OVERLAY = "overlay"
DESIGN = "design"

NAME_MAX = 120
TEXT_MAX = 80
NOTES_MAX = 500
QUANTITY_MAX = 100_000
#: One bound for every cost field, route AND tool (security review H1): a unit
#: cost past this is refused at the boundary and dropped on read, so a stored
#: value can never make `line_cost` non-finite and 500 the whole view.
COST_MAX = 1e9
#: Live hand-added rows (items + overlays) per project unless the bundle's
#: `max_items` setting says otherwise (security review M4).
DEFAULT_MAX_ITEMS = 2000

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_DOMAINS = "code|electrical|mechanical|simulation|runtime|project"
ROW_KEY_RE = re.compile(
    rf"^(?:(?:canonical|group|entity|item):{_UUID}|mpn:(?:{_DOMAINS}):[A-Z0-9.]{{1,64}})$"
)

_CONFIG = default_fingerprint_config()
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


# ------------------------------------------------------------------ inputs


@dataclass(frozen=True)
class Observation:
    """A connector-owned part as the BOM reads it — or a MANUAL planned part
    (STORE ST5 sourcing), which additionally carries its own lifecycle,
    supplier, unit cost and quantity."""

    id: uuid.UUID
    kind: str
    domain: str
    name: str
    value: str | None
    part_number: str | None
    manufacturer: str | None
    canonical_part_id: uuid.UUID | None
    is_assembly: bool = False
    lifecycle: str | None = None
    supplier: str | None = None
    unit_cost: float | None = None
    quantity: int | None = None


@dataclass(frozen=True)
class Canonical:
    id: uuid.UUID
    name: str
    manufacturer: str | None


@dataclass(frozen=True)
class Item:
    """An `ext:bom:item` row: a standalone raw material / purchase, or an overlay."""

    id: uuid.UUID
    name: str
    category: str
    quantity: int
    state: str
    row_key: str | None
    part_number: str | None
    manufacturer: str | None
    supplier: str | None
    unit_cost: float | None
    notes: str | None


@dataclass(frozen=True)
class BomSource:
    entity_id: uuid.UUID
    kind: str
    domain: str
    name: str


@dataclass(frozen=True)
class BomRow:
    key: str
    kind: str  # design | raw_material | purchase
    name: str
    part_number: str | None
    manufacturer: str | None
    quantity: int
    state: str
    supplier: str | None
    unit_cost: float | None
    notes: str | None
    sources: tuple[BomSource, ...]
    item_id: uuid.UUID | None
    canonical_id: uuid.UUID | None

    @property
    def line_cost(self) -> float | None:
        if self.unit_cost is None:
            return None
        total = round(self.unit_cost * self.quantity, 2)
        return total if math.isfinite(total) else None

    def payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "name": self.name,
            "part_number": self.part_number,
            "manufacturer": self.manufacturer,
            "quantity": self.quantity,
            "state": self.state,
            "supplier": self.supplier,
            "unit_cost": self.unit_cost,
            "line_cost": self.line_cost,
            "notes": self.notes,
            "sources": [
                {
                    "entity_id": str(s.entity_id),
                    "kind": s.kind,
                    "domain": s.domain,
                    "name": s.name,
                }
                for s in self.sources
            ],
            "item_id": str(self.item_id) if self.item_id else None,
            "canonical_id": str(self.canonical_id) if self.canonical_id else None,
        }


# ------------------------------------------------------------- from the graph


def _str(value: Any, cap: int = 512) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:cap]
    return None


def _number(value: Any) -> float | None:
    """A stored cost, or None when it is not a finite number within COST_MAX —
    a row written before a bound existed can never poison the view."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > COST_MAX:
        return None
    return number


def _manufacturer(attrs: dict[str, Any]) -> str | None:
    for key in ("manufacturer", "Manufacturer", "mfr", "MFR", "mfg"):
        found = _str(attrs.get(key), TEXT_MAX)
        if found:
            return found
    return None


def _manual_fields(entity: GraphEntity) -> dict[str, Any]:
    """A manual part's own BOM facts (a sourced part enters as `planned` with
    its supplier and cost); connector rows never carry these."""
    if entity.origin != "manual":
        return {}
    attrs = entity.attrs or {}
    lifecycle = attrs.get("lifecycle")
    quantity = attrs.get("quantity")
    return {
        "lifecycle": lifecycle if lifecycle in LIFECYCLE_STATES else None,
        "supplier": _str(attrs.get("supplier"), TEXT_MAX),
        "unit_cost": _number(attrs.get("unit_cost")),
        "quantity": (
            min(int(quantity), QUANTITY_MAX)
            if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity >= 1
            else None
        ),
    }


def observation_from_entity(entity: GraphEntity) -> Observation:
    hints = entity.modality_hints or {}
    attrs = entity.attrs or {}
    return Observation(
        id=entity.id,
        kind=entity.kind,
        domain=str(entity.domain.value),
        name=entity.name,
        value=_str(attrs.get("value"), TEXT_MAX),
        part_number=_str(hints.get("part_number"), 64) or _str(attrs.get("part_number"), 64),
        manufacturer=_manufacturer(attrs),
        canonical_part_id=entity.canonical_part_id,
        is_assembly=attrs.get("is_assembly") is True,
        **_manual_fields(entity),
    )


def canonical_from_entity(entity: GraphEntity) -> Canonical:
    fingerprint = (entity.attrs or {}).get("fingerprint")
    manufacturer = (
        _str(fingerprint.get("manufacturer"), TEXT_MAX) if isinstance(fingerprint, dict) else None
    )
    return Canonical(id=entity.id, name=entity.name, manufacturer=manufacturer)


def item_from_entity(entity: GraphEntity) -> Item | None:
    """A validated item, or None for a malformed row (dropped, never rendered)."""
    attrs = entity.attrs or {}
    category = attrs.get("category")
    state = attrs.get("state")
    if category not in (*ITEM_CATEGORIES, OVERLAY) or state not in LIFECYCLE_STATES:
        return None
    quantity = attrs.get("quantity", 1)
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        quantity = 1
    row_key = _str(attrs.get("row_key"), 200)
    if category == OVERLAY and (row_key is None or not is_row_key(row_key)):
        return None
    return Item(
        id=entity.id,
        name=entity.name,
        category=str(category),
        quantity=min(quantity, QUANTITY_MAX),
        state=str(state),
        row_key=row_key,
        part_number=_str(attrs.get("part_number"), 64),
        manufacturer=_str(attrs.get("manufacturer"), TEXT_MAX),
        supplier=_str(attrs.get("supplier"), TEXT_MAX),
        unit_cost=_number(attrs.get("unit_cost")),
        notes=_str(attrs.get("notes"), NOTES_MAX),
    )


# ------------------------------------------------------------------- helpers


def is_row_key(value: str) -> bool:
    return bool(ROW_KEY_RE.fullmatch(value))


def normalized_part_number(raw: str | None) -> str | None:
    """The fingerprint's normalized base (one normalizer for the whole product);
    None when no stable identity is derivable ("10k" is a value, not an MPN)."""
    if not raw or not raw.strip():
        return None
    normalized = normalize_mpn(raw, _CONFIG)
    return normalized.base if normalized is not None else None


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[uuid.UUID, uuid.UUID] = {}

    def find(self, node: uuid.UUID) -> uuid.UUID:
        self._parent.setdefault(node, node)
        root = node
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[node] != root:  # path compression
            self._parent[node], node = root, self._parent[node]
        return root

    def union(self, a: uuid.UUID, b: uuid.UUID) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[max(ra, rb)] = min(ra, rb)


def _group_key(
    members: list[Observation],
    canonical_ids: list[uuid.UUID],
    linked: bool,
) -> str:
    if canonical_ids:
        return f"canonical:{min(canonical_ids)}"
    if linked:
        return f"group:{min(m.id for m in members)}"
    # An MPN key survives a re-sync that re-creates the entity; an id key does not.
    base = normalized_part_number(members[0].part_number)
    if base:
        return f"mpn:{members[0].domain}:{base}"
    return f"entity:{members[0].id}"


def _first(values: list[str | None]) -> str | None:
    return next((v for v in values if v), None)


def _design_row(
    members: list[Observation],
    canonicals: list[Canonical],
    linked: bool,
    overlays: dict[str, Item],
) -> BomRow:
    members = sorted(members, key=lambda m: (m.domain != "electrical", m.name.lower(), m.id))
    canonical_ids = sorted(c.id for c in canonicals)
    key = _group_key(members, canonical_ids, linked)
    part_number = _first([m.part_number for m in members]) or _first([c.name for c in canonicals])
    name = part_number or _first([m.value for m in members]) or members[0].name
    manufacturer = _first([c.manufacturer for c in canonicals]) or _first(
        [m.manufacturer for m in members]
    )
    electrical = sum(1 for m in members if m.domain == "electrical")
    mechanical = sum(1 for m in members if m.domain == "mechanical")
    overlay = overlays.get(key)
    # A manual (sourced) part carries its own lifecycle, supplier, cost and
    # quantity; an overlay still wins so the BOM's edits apply to it too.
    own_state = _first([m.lifecycle for m in members])
    own_quantity = next((m.quantity for m in members if m.quantity), None)
    return BomRow(
        key=key,
        kind=DESIGN,
        name=name[:NAME_MAX],
        part_number=part_number,
        manufacturer=manufacturer,
        quantity=own_quantity or electrical or mechanical or 1,
        state=overlay.state if overlay else (own_state or DEFAULT_DESIGN_STATE),
        supplier=overlay.supplier if overlay else _first([m.supplier for m in members]),
        unit_cost=(
            overlay.unit_cost
            if overlay
            else next((m.unit_cost for m in members if m.unit_cost is not None), None)
        ),
        notes=overlay.notes if overlay else None,
        sources=tuple(BomSource(m.id, m.kind, m.domain, m.name) for m in members),
        item_id=overlay.id if overlay else None,
        canonical_id=canonical_ids[0] if canonical_ids else None,
    )


def row_for_item(item: Item) -> BomRow:
    """A hand-added row on its own — the shape POST/PATCH answer with."""
    return _item_row(item)


def _item_row(item: Item) -> BomRow:
    return BomRow(
        key=f"item:{item.id}",
        kind=item.category,
        name=item.name[:NAME_MAX],
        part_number=item.part_number,
        manufacturer=item.manufacturer,
        quantity=item.quantity,
        state=item.state,
        supplier=item.supplier,
        unit_cost=item.unit_cost,
        notes=item.notes,
        sources=(),
        item_id=item.id,
        canonical_id=None,
    )


_KIND_ORDER = {DESIGN: 0, "purchase": 1, "raw_material": 2}


def _link(
    design: dict[uuid.UUID, Observation],
    canonical_ids: set[uuid.UUID],
    same_as: list[tuple[uuid.UUID, uuid.UUID]],
) -> tuple[_UnionFind, set[uuid.UUID]]:
    """Union observations that are one part: fingerprint assertion, confirmed
    `same_as` link, or identical normalized part number WITHIN one domain."""
    union = _UnionFind()
    linked: set[uuid.UUID] = set()
    for o in design.values():
        union.find(o.id)
        if o.canonical_part_id in canonical_ids:
            union.union(o.id, o.canonical_part_id)
    for a, b in same_as:
        if a in design and b in design:
            union.union(a, b)
            linked.add(a)
    by_mpn: dict[tuple[str, str], list[uuid.UUID]] = {}
    for o in design.values():
        base = normalized_part_number(o.part_number)
        if base:
            by_mpn.setdefault((o.domain, base), []).append(o.id)
    for ids in by_mpn.values():
        for other in ids[1:]:
            union.union(ids[0], other)
    return union, {union.find(a) for a in linked}


def build_rows(
    observations: list[Observation],
    canonicals: list[Canonical],
    same_as: list[tuple[uuid.UUID, uuid.UUID]],
    items: list[Item],
) -> list[BomRow]:
    """Pure. `canonicals` are the LIVE canonical rows — an observation whose
    `canonical_part_id` names a row outside that set is treated as unlinked."""
    design = {o.id: o for o in observations if o.kind in DESIGN_KINDS and not o.is_assembly}
    canonical_by_id = {c.id: c for c in canonicals}
    union, linked = _link(design, set(canonical_by_id), same_as)

    groups: dict[uuid.UUID, list[Observation]] = {}
    group_canonicals: dict[uuid.UUID, list[Canonical]] = {}
    for o in design.values():
        root = union.find(o.id)
        groups.setdefault(root, []).append(o)
        canonical = canonical_by_id.get(o.canonical_part_id) if o.canonical_part_id else None
        if canonical is not None and canonical not in group_canonicals.setdefault(root, []):
            group_canonicals[root].append(canonical)

    overlays = {i.row_key: i for i in items if i.category == OVERLAY and i.row_key}
    rows = [
        _design_row(members, group_canonicals.get(root, []), root in linked, overlays)
        for root, members in groups.items()
    ]
    rows.extend(_item_row(i) for i in items if i.category in ITEM_CATEGORIES)
    return sorted(rows, key=lambda r: (_KIND_ORDER.get(r.kind, 9), r.name.lower(), r.key))


def totals(rows: list[BomRow], cost_target: float | None) -> dict[str, Any]:
    priced = [r.line_cost for r in rows if r.line_cost is not None]
    total = round(sum(priced), 2)
    return {
        "rows": len(rows),
        "priced_rows": len(priced),
        "line_cost_total": total,
        "cost_target": cost_target,
        "over_target": (total > cost_target) if cost_target is not None else None,
    }


# ----------------------------------------------------------------------- csv

CSV_COLUMNS = (
    "key",
    "kind",
    "name",
    "part_number",
    "manufacturer",
    "quantity",
    "state",
    "supplier",
    "unit_cost",
    "line_cost",
    "sources",
    "notes",
)


def csv_cell(value: str) -> str:
    """Neutralise spreadsheet formula injection: a cell that starts like a
    formula is prefixed with a quote so every consumer reads it as text."""
    return f"'{value}" if value.startswith(_FORMULA_PREFIXES) else value


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    return csv_cell(value) if isinstance(value, str) else value


def render_csv(rows: list[BomRow]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                _cell(row.key),
                _cell(row.kind),
                _cell(row.name),
                _cell(row.part_number),
                _cell(row.manufacturer),
                row.quantity,
                _cell(row.state),
                _cell(row.supplier),
                _cell(row.unit_cost),
                _cell(row.line_cost),
                _cell("; ".join(f"{s.domain}:{s.name}" for s in row.sources)),
                _cell(row.notes),
            ]
        )
    return out.getvalue()
